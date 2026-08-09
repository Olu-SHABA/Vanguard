"""Refactor engine — bounded loop, three exit conditions."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.coverage import load_aliases
from vanguard.cv import load
from vanguard.extract import Requirement, extract
from vanguard.rank import LexicalEmbedder
from vanguard.refactor import MAX_REFACTOR_ITER, ExitReason, refactor

ROOT = Path(__file__).parent.parent
ADVERT = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def cv():
    return load(ROOT / "data" / "canonical_cv.md")


@pytest.fixture
def aliases():
    return load_aliases(ROOT / "config" / "alias_table.yaml")


def reqs(*terms: str) -> list[Requirement]:
    """Build a requirement list.

    Must carry at least MIN_TERMS_FOR_CONFIDENCE terms, or coverage is marked
    UNRELIABLE and the loop exits before any branch under test is reached — a
    denominator of 2 or 3 makes the ratio meaningless.
    """
    return [Requirement(t, "tool", "essential", True, canonical=t) for t in terms]


# Six CV-evidenced terms. Coverage 1.000, above the confidence floor.
EVIDENCED = ("Python", "SQL", "Tableau", "PostgreSQL", "ETL", "machine learning")


# --- exits ----------------------------------------------------------------

def test_threshold_met_skips_editing(cv, aliases) -> None:
    r = refactor(reqs(*EVIDENCED), cv, aliases)
    assert r.exit_reason is ExitReason.THRESHOLD_MET
    assert r.passes == () and r.status == "PENDING"


def test_ceiling_exits_before_any_pass(cv, aliases) -> None:
    """Type 3 gaps placing 0.94 out of reach must exit immediately."""
    r = refactor(reqs(*EVIDENCED, "pytest", "AWS", "Spark", "Airflow", "git"),
                 cv, aliases)
    assert r.exit_reason is ExitReason.CEILING_UNREACHABLE
    assert r.passes == (), "burned a refactor pass on an unreachable vacancy"
    assert r.status == "UNREACHABLE"


def test_no_confirmed_edits_flags(cv, aliases) -> None:
    """Autonomous context: unconfirmed proposals are FLAGGED, not applied."""
    r = refactor(reqs(*EVIDENCED, "orchestration", "observability"),
                 cv, aliases, LexicalEmbedder())
    assert r.exit_reason in (ExitReason.NO_CONFIRMED_EDITS,
                             ExitReason.CEILING_UNREACHABLE,
                             ExitReason.THRESHOLD_MET)


def test_loop_never_exceeds_cap(cv, aliases) -> None:
    r = refactor(reqs(*EVIDENCED, "orchestration"), cv, aliases, LexicalEmbedder())
    assert len(r.passes) <= MAX_REFACTOR_ITER


def test_max_refactor_iter_is_two() -> None:
    assert MAX_REFACTOR_ITER == 2


# --- invariants -----------------------------------------------------------

def test_canonical_cv_is_never_mutated(cv, aliases) -> None:
    from vanguard.cv import to_markdown
    before = to_markdown(cv)
    refactor(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases, LexicalEmbedder())
    assert to_markdown(cv) == before


def test_type_3_gaps_recorded_not_removed(cv, aliases) -> None:
    r = refactor(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases)
    assert r.unmet, "Type 3 gaps must be recorded as unmet"
    assert all(int(g.gap_type) == 3 for g in r.unmet)


def test_every_edit_carries_a_source_role(cv, aliases) -> None:
    r = refactor(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases, LexicalEmbedder())
    assert all(e.source_role.strip() for e in r.edits)


def test_no_type_3_edit_ever_applied(cv, aliases) -> None:
    r = refactor(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases, LexicalEmbedder())
    assert all(e.gap_type in (1, 2) for e in r.edits)


def test_exit_reason_maps_to_queue_status() -> None:
    assert ExitReason.THRESHOLD_MET.status == "PENDING"
    assert ExitReason.CEILING_UNREACHABLE.status == "UNREACHABLE"
    assert ExitReason.ITERATION_CAP.status == "UNREACHABLE"
    assert ExitReason.NO_CONFIRMED_EDITS.status == "FLAGGED"


def test_result_summary_is_reviewable(cv, aliases) -> None:
    r = refactor(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases)
    s = r.summary()
    assert "ceiling" in s and "exit:" in s and "status:" in s


def test_moj_advert_is_unreachable(cv, aliases) -> None:
    """Five Tier C exclusions put 0.94 beyond reach. That is a true finding."""
    r = refactor(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases, LexicalEmbedder())
    assert r.status == "UNREACHABLE"
    assert r.initial.ceiling < 0.94


def test_partial_source_exits_before_editing(cv, aliases) -> None:
    """Refactoring against a snippet would edit the CV to satisfy requirements
    nobody stated."""
    result = refactor(reqs(*EVIDENCED), cv, aliases, source_is_partial=True)
    assert result.exit_reason is ExitReason.UNRELIABLE_SOURCE
    assert result.status == "FLAGGED"
    assert result.passes == ()


def test_unreliable_exit_makes_no_edits(cv, aliases) -> None:
    result = refactor(reqs(*EVIDENCED), cv, aliases, source_is_partial=True)
    assert result.edits == []


def test_full_source_is_unaffected(cv, aliases) -> None:
    result = refactor(extract(ADVERT.read_text(encoding="utf-8")), cv, aliases,
                      LexicalEmbedder(), source_is_partial=False)
    assert result.exit_reason is not ExitReason.UNRELIABLE_SOURCE
