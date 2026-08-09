"""Gap classification — the layer where fabrication would enter."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.coverage import Outcome, Resolution, compute_coverage, load_aliases
from vanguard.cv import load
from vanguard.extract import Requirement, extract
from vanguard.gaps import Gap, GapError, GapType, classify, classify_all
from vanguard.rank import LexicalEmbedder

ROOT = Path(__file__).parent.parent
ADVERT = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def cv():
    return load(ROOT / "data" / "canonical_cv.md")


@pytest.fixture
def aliases():
    return load_aliases(ROOT / "config" / "alias_table.yaml")


def res(term, *, score=None, excluded=False, evidence="") -> Resolution:
    r = Requirement(term, "tool", "essential", True, canonical=term)
    return Resolution(
        requirement=r, outcome=Outcome.GAP, stage=3 if score is not None else 0,
        score=score, evidence=evidence,
        exclusion_reason="ruled non-equivalent" if excluded else "",
        alias_canonical="EXCLUDED_x" if excluded else "",
    )


# --- Type 3 is absolute ---------------------------------------------------

def test_tier_c_classifies_type_3(cv) -> None:
    g = classify(res("pytest", excluded=True), cv)
    assert g.gap_type is GapType.NOT_EVIDENCED
    assert g.blocked_by_exclusion


def test_type_3_cannot_be_confirmed(cv) -> None:
    g = classify(res("Spark"), cv)
    with pytest.raises(GapError, match="permits no CV edit"):
        g.confirm(section_id="x", source_role="y", before="a", after="b")


def test_type_3_cannot_become_an_edit(cv) -> None:
    with pytest.raises(GapError, match="NO CV EDIT PERMITTED"):
        classify(res("Spark"), cv).to_edit()


def test_high_score_excluded_term_stays_type_3(cv) -> None:
    """A near-miss score must not rescue a Tier C exclusion."""
    g = classify(res("AWS", score=0.99, excluded=True), cv)
    assert g.gap_type is GapType.NOT_EVIDENCED


# --- the classifier proposes, the operator confirms ------------------------

def test_proposal_is_never_pre_confirmed(cv) -> None:
    g = classify(res("orchestration", score=0.62, evidence="scheduled the daily cycle"), cv)
    assert g.gap_type is GapType.EVIDENCED_UNSTATED
    assert g.confirmed is False


def test_unconfirmed_proposal_cannot_edit(cv) -> None:
    g = classify(res("orchestration", score=0.62), cv)
    with pytest.raises(GapError, match="unconfirmed machine proposal"):
        g.to_edit()


def test_confirmed_edit_requires_source_role(cv) -> None:
    g = classify(res("orchestration", score=0.62), cv)
    with pytest.raises(GapError, match="no source role"):
        g.confirm(before="a", after="b").to_edit()


def test_confirmed_edit_requires_text(cv) -> None:
    g = classify(res("orchestration", score=0.62), cv)
    with pytest.raises(GapError, match="no proposed edit text"):
        g.confirm(source_role="MTN, 2018-2024").to_edit()


def test_fully_confirmed_gap_produces_edit(cv) -> None:
    role = cv.roles()[0]
    g = classify(res("orchestration", score=0.62), cv).confirm(
        section_id=role.id, source_role=role.source_role,
        before=role.bullets[0], after=role.bullets[0] + " Orchestrated nightly.",
    )
    edit = g.to_edit()
    assert edit.gap_type == 1 and edit.source_role == role.source_role


def test_low_score_is_type_3(cv) -> None:
    assert classify(res("quantum optics", score=0.05), cv).gap_type is GapType.NOT_EVIDENCED


def test_no_score_is_type_3(cv) -> None:
    assert classify(res("quantum optics"), cv).gap_type is GapType.NOT_EVIDENCED


# --- report ---------------------------------------------------------------

def test_soft_hits_are_not_gaps(cv, aliases) -> None:
    reqs = extract(ADVERT.read_text(encoding="utf-8"))
    report = compute_coverage(reqs, cv, aliases, LexicalEmbedder())
    gaps = classify_all(report, cv)
    assert len(gaps.gaps) == len(report.gaps)


def test_every_gap_is_typed(cv, aliases) -> None:
    reqs = extract(ADVERT.read_text(encoding="utf-8"))
    gaps = classify_all(compute_coverage(reqs, cv, aliases), cv)
    assert len(gaps.gaps) == len(gaps.type_1) + len(gaps.type_2) + len(gaps.type_3)


def test_unconfirmed_proposals_flag_the_record(cv) -> None:
    from vanguard.gaps import GapReport
    g = classify(res("orchestration", score=0.62), cv)
    assert GapReport((g,)).requires_operator


def test_moj_sdlc_criterion_is_type_3(cv, aliases) -> None:
    reqs = extract(ADVERT.read_text(encoding="utf-8"))
    gaps = classify_all(compute_coverage(reqs, cv, aliases), cv)
    unmet = {g.term for g in gaps.type_3}
    # `git` reclassified Tier B — see alias_table v0.5. Testing and CI remain
    # unevidenced, so the SDLC criterion as a whole is still not met.
    assert {"pytest", "CI/CD", "GitHub Actions"} <= unmet
    assert "git" not in unmet
