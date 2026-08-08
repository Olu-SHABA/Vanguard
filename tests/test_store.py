"""Persistence — schema, instrumentation, audit trail."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanguard.adapters.base import Vacancy
from vanguard.coverage import compute_coverage, load_aliases
from vanguard.cv import load as load_cv
from vanguard.extract import extract
from vanguard.gaps import classify_all
from vanguard.rank import LexicalEmbedder
from vanguard.store import Store, StoreError

ROOT = Path(__file__).parent.parent
ADVERT = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "v.db")
    s.initialise()
    return s


def vac(vid="b:1", employer="MoJ", title="Data Engineer") -> Vacancy:
    return Vacancy(id=vid, board_id="b", employer=employer, title=title,
                   description="Python and SQL required.", location="London")


# --- schema ---------------------------------------------------------------

def test_initialise_is_idempotent(tmp_path: Path) -> None:
    s = Store(tmp_path / "v.db")
    s.initialise()
    s.initialise()
    assert s.count_vacancies() == 0


def test_vacancy_round_trips(store: Store) -> None:
    store.upsert_vacancy(vac())
    row = store.vacancy("b:1")
    assert row["employer"] == "MoJ" and row["dedup_key"]


def test_upsert_refreshes_description(store: Store) -> None:
    store.upsert_vacancy(vac())
    v = vac()
    v.description = "Updated advert text with more detail."
    store.upsert_vacancy(v)
    assert store.count_vacancies() == 1
    assert "Updated" in store.vacancy("b:1")["description"]


def test_unopenable_path_raises(tmp_path: Path) -> None:
    bad = tmp_path / "file.txt"
    bad.write_text("not a database")
    with pytest.raises(StoreError):
        Store(bad).initialise()


# --- instrumentation: the property that matters most ----------------------

def test_every_requirement_term_is_persisted(store: Store) -> None:
    """A gap list discarded at scoring time is gone. Recalibration needs it."""
    store.upsert_vacancy(vac())
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract(ADVERT.read_text(encoding="utf-8")), cv,
                              aliases, LexicalEmbedder())
    store.record_score("b:1", report, 0.5, embedder="lexical",
                       gaps=classify_all(report, cv))

    assert len(store.gaps_for("b:1")) == report.total


def test_embedder_is_recorded(store: Store) -> None:
    """A lexical result is degraded and must be distinguishable in the log."""
    store.upsert_vacancy(vac())
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract("Essential\n- strong Python skills needed"),
                              cv, aliases)
    store.record_score("b:1", report, embedder="lexical")
    assert store.latest_score("b:1")["embedder"] == "lexical"


def test_coverage_and_ceiling_both_stored(store: Store) -> None:
    store.upsert_vacancy(vac())
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases)
    store.record_score("b:1", report)
    row = store.latest_score("b:1")
    assert row["coverage"] == pytest.approx(report.coverage)
    assert row["ceiling"] == pytest.approx(report.ceiling)


def test_rescoring_replaces_gap_rows(store: Store) -> None:
    store.upsert_vacancy(vac())
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    r1 = compute_coverage(extract("Essential\n- strong Python skills required"), cv, aliases)
    store.record_score("b:1", r1)
    first = len(store.gaps_for("b:1"))
    r2 = compute_coverage(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases)
    store.record_score("b:1", r2)
    assert len(store.gaps_for("b:1")) == r2.total != first


def test_exclusion_reason_is_persisted(store: Store) -> None:
    store.upsert_vacancy(vac())
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases)
    store.record_score("b:1", report)
    rows = {r["term"]: r for r in store.gaps_for("b:1")}
    assert rows["pytest"]["exclusion"]


# --- analysis -------------------------------------------------------------

def test_unmet_term_frequency_aggregates(store: Store) -> None:
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases)
    for i in range(3):
        store.upsert_vacancy(vac(f"b:{i}", title=f"Role {i}"))
        store.record_score(f"b:{i}", report)
    top = {r["term"]: r["n"] for r in store.unmet_term_frequency(30)}
    assert top.get("pytest") == 3


def test_coverage_distribution_is_ordered(store: Store) -> None:
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract("Essential\n- strong Python skills required"), cv, aliases)
    for i in range(3):
        store.upsert_vacancy(vac(f"b:{i}", title=f"Role {i}"))
        store.record_score(f"b:{i}", report)
    assert len(store.coverage_distribution()) == 3


# --- audit trail ----------------------------------------------------------

def test_creation_writes_a_transition(store: Store) -> None:
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "PENDING")
    rows = store.transitions_for("b:1")
    assert len(rows) == 1 and rows[0]["from_state"] is None


def test_status_change_appends_never_overwrites(store: Store) -> None:
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "PENDING")
    store.set_status("b:1", "APPROVED", "ok")
    store.set_status("b:1", "DISPATCHED", "sent")
    rows = store.transitions_for("b:1")
    assert [r["to_state"] for r in rows] == ["PENDING", "APPROVED", "DISPATCHED"]


def test_transition_records_the_previous_state(store: Store) -> None:
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "PENDING")
    store.set_status("b:1", "APPROVED")
    assert store.transitions_for("b:1")[-1]["from_state"] == "PENDING"


def test_status_change_on_missing_record_raises(store: Store) -> None:
    with pytest.raises(StoreError, match="no queue record"):
        store.set_status("nope", "APPROVED")


def test_queue_ordered_by_rank_score(store: Store) -> None:
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract("Essential\n- strong Python skills required"), cv, aliases)
    for i, s in enumerate([0.2, 0.9, 0.5]):
        store.upsert_vacancy(vac(f"b:{i}", title=f"Role {i}"))
        store.record_score(f"b:{i}", report, s)
        store.create_queue_record(f"b:{i}", "PENDING")
    assert [r["vacancy_id"] for r in store.list_queue("PENDING")] == ["b:1", "b:2", "b:0"]


def test_counts_by_status(store: Store) -> None:
    for i, s in enumerate(["PENDING", "PENDING", "FLAGGED"]):
        store.upsert_vacancy(vac(f"b:{i}", title=f"Role {i}"))
        store.create_queue_record(f"b:{i}", s)
    assert store.counts_by_status() == {"PENDING": 2, "FLAGGED": 1}
