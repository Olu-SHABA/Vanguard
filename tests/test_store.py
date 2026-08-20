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



def legacy_schema() -> str:
    """SCHEMA as it stood before the post-release columns were added.

    Built by removing the migrated columns, so it stays correct as more are
    added — an earlier version stripped one line by hand and broke the moment
    a second column landed after it.
    """
    from vanguard.store import SCHEMA

    migrated = {column for _table, column, _ddl in Store.MIGRATIONS}
    out = []
    for line in SCHEMA.splitlines():
        name = line.strip().split(" ")[0].rstrip(",")
        if name in migrated:
            continue
        out.append(line)
    text = "\n".join(out)
    # The last column before the closing paren must not keep a trailing comma.
    return text.replace(",\n);", "\n);")


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
    """Amended 12 Aug 2026: the advert must yield enough requirements to be
    measurable, since the distribution now excludes unmeasured scores."""
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract(MEASURABLE_ADVERT), cv, aliases)
    for i in range(3):
        store.upsert_vacancy(vac(f"b:{i}", title=f"Role {i}"))
        store.record_score(f"b:{i}", report)
    assert len(store.coverage_distribution()) == 3


def test_unmeasured_scores_are_excluded_from_the_distribution(store: Store) -> None:
    """A score from one requirement is 0.000 or 1.000 depending on whether
    that term matched. Neither measures fit, and the distribution is the
    input to gate recalibration."""
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")

    thin = compute_coverage(extract("Essential\n- Python"), cv, aliases)
    full = compute_coverage(extract(MEASURABLE_ADVERT), cv, aliases)

    store.upsert_vacancy(vac("b:thin"))
    store.record_score("b:thin", thin)
    store.upsert_vacancy(vac("b:full"))
    store.record_score("b:full", full)

    ids = {r["vacancy_id"] for r in store.coverage_distribution()}
    assert ids == {"b:full"}
    assert store.unmeasured_count() == 1


def test_unreliable_scores_are_still_retained(store: Store) -> None:
    """Excluded from the distribution, not deleted. `diagnose` needs them."""
    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    store.upsert_vacancy(vac("b:thin"))
    store.record_score("b:thin", compute_coverage(extract("Essential\n- Python"),
                                                  cv, aliases))
    assert store.coverage_distribution(reliable_only=False)


#: An advert with enough requirements to be measurable — six or more, per
#: MIN_TERMS_FOR_CONFIDENCE.
MEASURABLE_ADVERT = """Essential
- strong Python skills required
- SQL and relational databases
- experience with ETL pipelines
- data visualisation and dashboards
- machine learning models in production
- stakeholder communication
- root cause analysis
"""


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


# ---------------------------------------------------------------------------
# Schema migration — a column added after release must reach old databases
# ---------------------------------------------------------------------------

def test_column_added_to_an_existing_database(tmp_path: Path) -> None:
    """`CREATE TABLE IF NOT EXISTS` does not alter an existing table.

    A database created before `reference` existed silently lacked it, and
    every insert failed at runtime with 'table vacancies has no column named
    reference' — after the vacancies had already been fetched and scored.
    """
    import sqlite3

    from vanguard.store import SCHEMA

    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(legacy_schema())
    conn.close()

    columns = {r[1] for r in sqlite3.connect(str(path)).execute("PRAGMA table_info(vacancies)")}
    assert "reference" not in columns and "partial" not in columns

    Store(path).initialise()

    columns = {r[1] for r in sqlite3.connect(str(path)).execute("PRAGMA table_info(vacancies)")}
    assert {"reference", "partial"} <= columns


def test_migration_is_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "v.db")
    store.initialise()
    store.initialise()
    store.initialise()
    store.upsert_vacancy(vac())
    assert store.count_vacancies() == 1


def test_migrated_database_accepts_writes(tmp_path: Path) -> None:
    """The failure was at insert time, after fetching and scoring. Prove the
    round trip, not merely that the column exists."""
    import sqlite3

    from vanguard.store import SCHEMA

    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(legacy_schema())
    conn.close()

    store = Store(path)
    store.initialise()
    v = vac()
    v.reference = "19568"
    store.upsert_vacancy(v)
    assert store.vacancy("b:1")["reference"] == "19568"


def test_partial_flag_is_persisted(store: Store) -> None:
    """Without this the operator cannot query which scores were degraded —
    it had to be inferred from average description lengths."""
    v = vac()
    v.description_is_partial = True
    store.upsert_vacancy(v)
    assert store.vacancy("b:1")["partial"] == 1


def test_full_text_vacancy_is_not_flagged(store: Store) -> None:
    store.upsert_vacancy(vac())
    assert store.vacancy("b:1")["partial"] == 0


# ---------------------------------------------------------------------------
# Score history must not multiply queue rows
# ---------------------------------------------------------------------------

def test_repeated_scoring_yields_one_queue_row(store: Store) -> None:
    """`scores` holds one row per run by design. Joining it naively rendered
    two vacancies as twenty rows after ten runs."""
    from vanguard.coverage import compute_coverage, load_aliases
    from vanguard.cv import load as load_cv
    from vanguard.extract import extract

    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "PENDING")

    cv = load_cv(ROOT / "data" / "canonical_cv.md")
    aliases = load_aliases(ROOT / "config" / "alias_table.yaml")
    report = compute_coverage(extract("Essential\n- strong Python skills here"), cv, aliases)

    from vanguard.store import utcnow
    for i in range(5):
        with store.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scores (vacancy_id, coverage, rank_score,"
                " ceiling, terms_total, terms_matched, soft_hits, embedder, computed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("b:1", 0.1 * i, 0.5 + i / 100, 1.0, 10, i, 0, "test",
                 f"2026-08-0{i + 1}T00:00:00+00:00"),
            )

    assert len(store.list_queue("PENDING")) == 1


def test_latest_score_is_the_one_shown(store: Store) -> None:
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "PENDING")
    with store.connect() as conn:
        for day, coverage in ((1, 0.20), (2, 0.90), (3, 0.55)):
            conn.execute(
                "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
                " terms_total, terms_matched, soft_hits, embedder, computed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("b:1", coverage, 0.5, 1.0, 10, 5, 0, "test",
                 f"2026-08-0{day}T00:00:00+00:00"),
            )
    assert store.list_queue("PENDING")[0]["coverage"] == 0.55


def test_score_history_is_retained(store: Store) -> None:
    """Seeing 0.333 -> 0.636 -> 1.000 across runs is how you tell whether a
    change to extraction helped. The history is deliberate."""
    store.upsert_vacancy(vac())
    with store.connect() as conn:
        for day in (1, 2, 3):
            conn.execute(
                "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
                " terms_total, terms_matched, soft_hits, embedder, computed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("b:1", 0.3, 0.5, 1.0, 10, 3, 0, "test",
                 f"2026-08-0{day}T00:00:00+00:00"),
            )
    assert len(store.score_history("b:1")) == 3


def test_coverage_distribution_counts_each_vacancy_once(store: Store) -> None:
    store.upsert_vacancy(vac())
    with store.connect() as conn:
        for day in (1, 2, 3):
            conn.execute(
                "INSERT INTO scores (vacancy_id, coverage, rank_score, ceiling,"
                " terms_total, terms_matched, soft_hits, embedder, computed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("b:1", 0.3, 0.5, 1.0, 10, 3, 0, "test",
                 f"2026-08-0{day}T00:00:00+00:00"),
            )
    assert len(store.coverage_distribution()) == 1
    assert len(store.coverage_distribution(latest_only=False)) == 3


# ---------------------------------------------------------------------------
# A decision is not something a scheduled run gets to undo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("decided", ["APPROVED", "REJECTED", "DISPATCHED"])
def test_operator_decisions_survive_re_enqueue(store: Store, decided: str) -> None:
    """An application dispatched at 22:15 came back as PENDING after the next
    run at 22:22, and the record then offered `approve` on something already
    submitted."""
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "PENDING")
    store.set_status("b:1", decided)

    for _ in range(3):
        store.create_queue_record("b:1", "PENDING")

    assert store.queue_record("b:1")["status"] == decided


def test_machine_states_are_still_recomputed(store: Store) -> None:
    """PENDING, FLAGGED and UNREACHABLE are the run's own conclusions and may
    change as scoring improves."""
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "UNREACHABLE")
    store.create_queue_record("b:1", "PENDING")
    assert store.queue_record("b:1")["status"] == "PENDING"


def test_unchanged_status_writes_no_transition(store: Store) -> None:
    """Twenty-four identical `- -> PENDING` lines make the trail unreadable."""
    store.upsert_vacancy(vac())
    for _ in range(5):
        store.create_queue_record("b:1", "PENDING")
    assert len(store.transitions_for("b:1")) == 1


def test_real_changes_record_the_previous_state(store: Store) -> None:
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "UNREACHABLE")
    store.create_queue_record("b:1", "PENDING")
    rows = store.transitions_for("b:1")
    assert [(r["from_state"], r["to_state"]) for r in rows] == [
        (None, "UNREACHABLE"), ("UNREACHABLE", "PENDING")
    ]


def test_re_scoring_still_refreshes_metadata(store: Store) -> None:
    """The decision is preserved; the numbers and flags are not frozen."""
    store.upsert_vacancy(vac())
    store.create_queue_record("b:1", "PENDING")
    store.set_status("b:1", "DISPATCHED")
    store.create_queue_record("b:1", "PENDING", submission_type="SUCCESS_PROFILE")

    row = store.queue_record("b:1")
    assert row["status"] == "DISPATCHED"
    assert row["submission_type"] == "SUCCESS_PROFILE"


def test_storage_footprint_reports_row_counts(store: Store) -> None:
    """Growth must be measurable, not estimated. The decision to archive or
    index is then made on numbers."""
    store.upsert_vacancy(vac())
    footprint = store.storage_footprint()
    assert footprint["counts"]["vacancies"] == 1
    assert footprint["rows"] >= 1
    assert footprint["bytes"] > 0


def test_footprint_survives_an_empty_database(tmp_path: Path) -> None:
    empty = Store(tmp_path / "v.db")
    empty.initialise()
    assert empty.storage_footprint()["bytes_per_vacancy"] == 0


# ---------------------------------------------------------------------------
# Responses must not multiply
#
# A mailbox is read repeatedly and the same message arrives every time.
# Polling twice recorded everything twice — the third occurrence of this
# defect after B-21 (score history multiplied queue rows) and B-32 (every
# re-enqueue wrote a duplicate transition).
# ---------------------------------------------------------------------------

def test_the_same_message_records_once(store: Store) -> None:
    for _ in range(3):
        store.record_response("reed:1", "ACK", sender="hr@acme.com",
                              subject="Thank you for applying",
                              received_at="2026-08-19T09:00:00+00:00",
                              message_id="<abc@mail>")
    assert len(store.responses()) == 1


def test_a_changed_message_id_does_not_duplicate(store: Store) -> None:
    """Keying on the mailbox's id created two schemes — rows written before
    the id was captured carried a synthetic key, rows after carried the real
    one, and the same message survived under both.

    The natural key is stable across that change.
    """
    for message_id in ("hr@acme.com|Thanks|2026-08-19", "<real@mail>", ""):
        store.record_response("reed:1", "ACK", sender="hr@acme.com",
                              subject="Thanks", received_at="2026-08-19",
                              message_id=message_id)
    assert len(store.responses()) == 1


def test_a_database_with_both_key_schemes_collapses(tmp_path: Path) -> None:
    """Exactly the operator's database on 19 Aug: some rows keyed
    synthetically, some by real message id, the same messages under both."""
    import sqlite3

    db = tmp_path / "v.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE responses (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " vacancy_id TEXT NOT NULL, message_id TEXT NOT NULL DEFAULT '',"
        " state TEXT NOT NULL, sender TEXT, subject TEXT,"
        " received_at TIMESTAMP, recorded_at TIMESTAMP NOT NULL, method TEXT);")
    for key in ("hr@x.com|Thanks|2026-08-11", "<real@mail>"):
        conn.execute(
            "INSERT INTO responses (vacancy_id, message_id, state, sender,"
            " subject, received_at, recorded_at, method)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("linkedin:a2d5", key, "ACK", "hr@x.com", "Thanks",
             "2026-08-11", "2026-08-11", "ats"))
    conn.commit()
    conn.close()

    store = Store(db)
    store.initialise()
    assert len(store.responses()) == 1


def test_recording_reports_whether_it_was_new(store: Store) -> None:
    assert store.record_response("reed:1", "ACK", message_id="<abc@mail>") is True
    assert store.record_response("reed:1", "ACK", message_id="<abc@mail>") is False


def test_a_message_without_an_id_still_deduplicates(store: Store) -> None:
    """Not every mailbox supplies one. Sender, subject and time identify the
    message well enough — two identical acknowledgements from one employer on
    one day are one message."""
    for _ in range(3):
        store.record_response("reed:1", "ACK", sender="hr@acme.com",
                              subject="Thank you for applying",
                              received_at="2026-08-19T09:00:00+00:00")
    assert len(store.responses()) == 1


def test_different_messages_are_both_kept(store: Store) -> None:
    """Amended 19 Aug 2026: the key is now the natural identity of a message,
    so two records need to differ in sender, subject or time — not merely in
    the mailbox id, which the operator's database showed can vary for the
    same message."""
    store.record_response("reed:1", "ACK", sender="hr@acme.com",
                          subject="Thank you for applying",
                          received_at="2026-08-11")
    store.record_response("reed:1", "DECLINE", sender="hr@acme.com",
                          subject="Update on your application",
                          received_at="2026-08-19")
    assert len(store.responses()) == 2


def test_the_same_message_to_two_applications_is_two_records(store: Store) -> None:
    """A recruiter mailing about two roles is two responses, not one."""
    store.record_response("reed:1", "ACK", message_id="<abc@mail>")
    store.record_response("reed:2", "ACK", message_id="<abc@mail>")
    assert len(store.responses()) == 2


def test_an_existing_database_with_duplicates_is_collapsed(tmp_path: Path) -> None:
    """The operator polled twice before this fix and has eight rows where
    four belong. The unique index cannot be created while they exist."""
    import sqlite3

    db = tmp_path / "v.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE responses (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " vacancy_id TEXT NOT NULL, state TEXT NOT NULL, sender TEXT,"
        " subject TEXT, received_at TIMESTAMP, recorded_at TIMESTAMP NOT NULL,"
        " method TEXT);")
    for _ in range(2):
        for employer in ("Beatport", "Sardine", "HSBC", "WPP-Media"):
            conn.execute(
                "INSERT INTO responses (vacancy_id, state, sender, subject,"
                " received_at, recorded_at, method) VALUES (?,?,?,?,?,?,?)",
                (f"linkedin:{employer}", "ACK", "hr@x.com",
                 f"Thank you for applying at {employer}",
                 "2026-08-19T09:00:00+00:00", "2026-08-19T10:00:00+00:00",
                 "ats"))
    conn.commit()
    conn.close()

    store = Store(db)
    store.initialise()
    assert len(store.responses()) == 4

    # And a further poll adds nothing.
    store.record_response("linkedin:Beatport", "ACK", sender="hr@x.com",
                          subject="Thank you for applying at Beatport",
                          received_at="2026-08-19T09:00:00+00:00")
    assert len(store.responses()) == 4


def test_the_earliest_row_survives_collapsing(tmp_path: Path) -> None:
    """`recorded_at` should say when the reply was first seen, not when it was
    last re-read."""
    import sqlite3

    db = tmp_path / "v.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE responses (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " vacancy_id TEXT NOT NULL, state TEXT NOT NULL, sender TEXT,"
        " subject TEXT, received_at TIMESTAMP, recorded_at TIMESTAMP NOT NULL,"
        " method TEXT);")
    for recorded in ("2026-08-11T08:00:00+00:00", "2026-08-19T08:00:00+00:00"):
        conn.execute(
            "INSERT INTO responses (vacancy_id, state, sender, subject,"
            " received_at, recorded_at, method) VALUES (?,?,?,?,?,?,?)",
            ("reed:1", "ACK", "hr@x.com", "Thanks", "2026-08-11T07:00:00+00:00",
             recorded, "ats"))
    conn.commit()
    conn.close()

    store = Store(db)
    store.initialise()
    rows = store.responses()
    assert len(rows) == 1
    assert rows[0]["recorded_at"].startswith("2026-08-11")
