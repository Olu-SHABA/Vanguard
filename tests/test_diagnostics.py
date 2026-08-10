"""Diagnostics — why an advert produced what it did."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.diagnostics import (
    AdvertDiagnostic,
    Decision,
    RefusalReason,
    diagnose_advert,
)
from vanguard.store import Store

ROOT = Path(__file__).parent.parent

RECOGNISED = ("<strong>What you will have</strong><br /><br />"
              "<ul><li>Python and SQL</li><li>AWS experience</li></ul>")
UNRECOGNISED = ("<strong>Our Ideal Teammate Vibe</strong><br /><br />"
                "<ul><li>25 days holiday</li><li>Free parking</li></ul>")


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "v.db")
    s.initialise()
    return s


# --- 1. why something was rejected ----------------------------------------

def test_unrecognised_heading_is_named_as_the_reason() -> None:
    d = diagnose_advert("r:1", UNRECOGNISED, terms_extracted=0)
    assert d.refused
    assert d.refusal is RefusalReason.NO_REQUIREMENT_HEADING
    assert "widen classify_heading" in d.refusal.explanation


def test_advert_with_no_headings_is_distinguished() -> None:
    """Continuous prose is a different problem from an unrecognised heading."""
    d = diagnose_advert("r:1", "<p>We need someone good with data.</p>", terms_extracted=0)
    assert d.refusal is RefusalReason.NO_HEADINGS_AT_ALL


def test_successful_extraction_records_no_refusal() -> None:
    d = diagnose_advert("r:1", RECOGNISED, terms_extracted=3)
    assert not d.refused and d.refusal is RefusalReason.NONE


def test_plain_text_refusal_is_its_own_reason() -> None:
    d = diagnose_advert("r:1", "Some plain prose with no structure", terms_extracted=0)
    assert d.refusal is RefusalReason.NOT_HTML_NO_SECTIONS


# --- 2. what was gathered per advert --------------------------------------

def test_headings_and_their_classification_are_recorded() -> None:
    d = diagnose_advert("r:1", RECOGNISED, terms_extracted=3)
    assert "What you will have" in d.headings
    assert d.heading_kinds["What you will have"] == "requirement"


def test_unrecognised_headings_are_isolated() -> None:
    """These are the direct input to widening the phrase list."""
    d = diagnose_advert("r:1", UNRECOGNISED, terms_extracted=0)
    assert d.unrecognised_headings == ["Our Ideal Teammate Vibe"]


def test_bullet_counts_are_recorded() -> None:
    d = diagnose_advert("r:1", RECOGNISED, terms_extracted=3)
    assert d.bullet_count == 2 and d.requirement_bullets == 2


def test_bullets_outside_requirement_sections_are_counted_separately() -> None:
    advert = (RECOGNISED + "<strong>What we offer</strong><br /><br />"
              "<ul><li>Holiday</li><li>Pension</li><li>Parking</li></ul>")
    d = diagnose_advert("r:1", advert, terms_extracted=3)
    assert d.bullet_count == 5 and d.requirement_bullets == 2


def test_partial_and_length_are_recorded() -> None:
    d = diagnose_advert("r:1", RECOGNISED, partial=True, terms_extracted=1)
    assert d.partial and d.description_chars == len(RECOGNISED)


# --- 3. audit trail of decisions ------------------------------------------

def test_decisions_accumulate_in_order() -> None:
    d = AdvertDiagnostic(vacancy_id="r:1")
    d.record(Decision.HYDRATED)
    d.record(Decision.SCORED, "C=0.700")
    assert d.decisions == ["hydrated", "scored:C=0.700"]


def test_refusal_records_a_decision() -> None:
    d = diagnose_advert("r:1", UNRECOGNISED, terms_extracted=0)
    assert any(x.startswith("extraction_refused") for x in d.decisions)


# --- persistence and aggregation ------------------------------------------

def test_diagnostic_round_trips(store: Store) -> None:
    store.record_diagnostic(diagnose_advert("r:1", RECOGNISED, board_id="reed",
                                            terms_extracted=3))
    row = store.diagnostic_for("r:1")
    assert row["board_id"] == "reed" and row["terms_extracted"] == 3


def test_unrecognised_headings_are_ranked_by_frequency(store: Store) -> None:
    for i in range(3):
        store.record_diagnostic(diagnose_advert(f"r:{i}", UNRECOGNISED, terms_extracted=0))
    store.record_diagnostic(diagnose_advert(
        "r:9", "<strong>Who Thrives Here</strong><ul><li>x</li></ul>", terms_extracted=0))

    ranked = store.unrecognised_headings()
    assert ranked[0]["heading"] == "Our Ideal Teammate Vibe"
    assert ranked[0]["n"] == 3


def test_refusal_counts_aggregate(store: Store) -> None:
    store.record_diagnostic(diagnose_advert("r:1", UNRECOGNISED, terms_extracted=0))
    store.record_diagnostic(diagnose_advert("r:2", "<p>prose</p>", terms_extracted=0))
    counts = store.refusal_counts()
    assert counts.get("no_requirement_heading") == 1
    assert counts.get("no_headings_at_all") == 1


def test_parse_health_reports_the_scored_rate(store: Store) -> None:
    store.record_diagnostic(diagnose_advert("r:1", RECOGNISED, terms_extracted=3))
    store.record_diagnostic(diagnose_advert("r:2", UNRECOGNISED, terms_extracted=0))
    health = store.parse_health()
    assert health["total"] == 2 and health["scored"] == 1 and health["html"] == 2


def test_recording_never_fails_a_run(tmp_path: Path) -> None:
    """Diagnostics are observational. Losing one must not abort scoring."""
    broken = Store(tmp_path / "absent" / "v.db")
    broken.record_diagnostic(diagnose_advert("r:1", RECOGNISED, terms_extracted=1))


def test_summary_is_readable() -> None:
    assert "REFUSED" in diagnose_advert("r:1", UNRECOGNISED, terms_extracted=0).summary()
    assert "term(s)" in diagnose_advert("r:2", RECOGNISED, terms_extracted=3).summary()


# ---------------------------------------------------------------------------
# Aggregates must count each vacancy once, not once per run
# ---------------------------------------------------------------------------

def _diagnose_across_runs(store: Store, runs: int = 4) -> None:
    """Three vacancies, each diagnosed on several runs — the real situation."""
    for run in range(runs):
        for i, (html, terms) in enumerate([(RECOGNISED, 3), (UNRECOGNISED, 0),
                                           (UNRECOGNISED, 0)]):
            diagnostic = diagnose_advert(f"reed:{i}", html, board_id="reed",
                                         terms_extracted=terms)
            diagnostic.recorded_at = f"2026-08-1{run}T00:00:00+00:00"
            store.record_diagnostic(diagnostic)


def test_parse_health_counts_each_vacancy_once(store: Store) -> None:
    """`diagnostics` holds one row per advert per run. Mixing COUNT(DISTINCT)
    for the denominator with a plain SUM for the numerator produced 176 scored
    out of 33 parsed — 533%, and a negative refusal count."""
    _diagnose_across_runs(store)
    health = store.parse_health()

    assert health["total"] == 3
    assert health["scored"] == 1
    assert health["scored"] <= health["total"], "a percentage above 100 is impossible"
    assert health["total"] - health["scored"] >= 0, "refusals cannot be negative"


def test_refusal_counts_are_not_multiplied_by_runs(store: Store) -> None:
    _diagnose_across_runs(store)
    assert store.refusal_counts()["no_requirement_heading"] == 2


def test_heading_frequency_is_not_multiplied_by_runs(store: Store) -> None:
    """A heading appearing on 3 adverts across 8 runs is not 24 occurrences."""
    _diagnose_across_runs(store)
    ranked = {r["heading"]: r["n"] for r in store.unrecognised_headings()}
    assert ranked["Our Ideal Teammate Vibe"] == 2


def test_rescoring_reflects_the_latest_result(store: Store) -> None:
    """An advert that previously refused and now parses counts as scored."""
    first = diagnose_advert("reed:1", UNRECOGNISED, terms_extracted=0)
    first.recorded_at = "2026-08-01T00:00:00+00:00"
    store.record_diagnostic(first)

    later = diagnose_advert("reed:1", RECOGNISED, terms_extracted=5)
    later.recorded_at = "2026-08-09T00:00:00+00:00"
    store.record_diagnostic(later)

    health = store.parse_health()
    assert health["total"] == 1 and health["scored"] == 1
    assert store.refusal_counts() == {}
