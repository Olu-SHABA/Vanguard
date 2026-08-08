"""Templates D and E — operator-initiated, grading discipline."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.cv import load
from vanguard.interview import (
    MAX_SCORE,
    PASS_LINE,
    Dimension,
    OperatorActionError,
    Phase,
    ScoreVector,
    build_session,
    draft_feedback_request,
)
from vanguard.mail import State

ROOT = Path(__file__).parent.parent


@pytest.fixture
def cv():
    return load(ROOT / "data" / "canonical_cv.md")


# --- Template D: DECLINE only ---------------------------------------------

def test_feedback_request_drafts_on_decline() -> None:
    out = draft_feedback_request(
        job_title="Senior Data Engineer", company="MoJ",
        applicant_name="A", contact="a@b.c", state=State.DECLINE,
    )
    assert "Senior Data Engineer" in out and "MoJ" in out


@pytest.mark.parametrize(
    "state", [State.PROGRESS, State.ACK, State.QUERY, State.ADMIN, State.AMBIGUOUS]
)
def test_feedback_request_refuses_other_states(state: State) -> None:
    """Silence is not a rejection. Nor is an acknowledgement."""
    with pytest.raises(OperatorActionError, match="DECLINE only"):
        draft_feedback_request(job_title="X", company="Y", applicant_name="Z",
                               contact="c", state=state)


def test_feedback_request_asks_for_specifics() -> None:
    out = draft_feedback_request(job_title="X", company="Y", applicant_name="Z",
                                 contact="c", state=State.DECLINE)
    assert "technical competencies" in out and out.count("*") >= 2


# --- Template E: grading discipline ---------------------------------------

def test_d1_zero_is_terminal() -> None:
    """An unsupported claim cannot be rescued by good reasoning."""
    sv = ScoreVector()
    sv.record(Dimension.D1_CV_GROUNDING, 0, "claim absent from the CV")
    sv.record(Dimension.D4_DECISION_JUSTIFICATION, 3, "alternatives named and rejected")
    assert sv.terminal_failure and "TERMINAL" in sv.report()


def test_bare_numbers_are_not_permitted() -> None:
    sv = ScoreVector()
    with pytest.raises(ValueError, match="without justification"):
        sv.record(Dimension.D2_QUANTIFICATION, 2, "   ")


@pytest.mark.parametrize("score", [-1, 4, 10])
def test_score_must_be_in_range(score: int) -> None:
    with pytest.raises(ValueError, match=f"0-{MAX_SCORE}"):
        ScoreVector().record(Dimension.D1_CV_GROUNDING, score, "reason")


def test_vector_is_reported_not_only_the_total() -> None:
    """A 2/2/2/2 and a 3/3/1/1 both total 8 and mean different things."""
    a, b = ScoreVector(), ScoreVector()
    for d in list(Dimension)[:4]:
        a.record(d, 2, "adequate")
    for d, s in zip(list(Dimension)[:4], [3, 3, 1, 1]):
        b.record(d, s, "varies")
    assert a.total == b.total == 8
    assert a.vector() != b.vector()


def test_below_pass_line_is_flagged() -> None:
    sv = ScoreVector()
    sv.record(Dimension.D1_CV_GROUNDING, 3, "traceable")
    sv.record(Dimension.D3_CONSTRAINT_AWARENESS, 1, "gestured at, not specified")
    assert Dimension.D3_CONSTRAINT_AWARENESS in sv.below_pass_line
    assert "re-interrogate" in sv.report()


def test_pass_line_is_two() -> None:
    assert PASS_LINE == 2


# --- phase scoping --------------------------------------------------------

def test_d5_is_phase_3_only() -> None:
    assert Dimension.D5_NARRATIVE_STRUCTURE not in Phase.CV_CLAIMS_VERIFICATION.dimensions
    assert Dimension.D5_NARRATIVE_STRUCTURE in Phase.EXECUTIVE_BEHAVIOURAL.dimensions


def test_aggregate_ranges_differ_by_phase() -> None:
    """Never compare a Phase 3 total against a Phase 1-2 total."""
    assert Phase.CV_CLAIMS_VERIFICATION.max_aggregate == 12
    assert Phase.EXECUTIVE_BEHAVIOURAL.max_aggregate == 15


def test_only_d1_is_terminal_at_zero() -> None:
    terminal = [d for d in Dimension if d.terminal_at_zero]
    assert terminal == [Dimension.D1_CV_GROUNDING]


# --- question generation --------------------------------------------------

def test_phase_1_questions_come_from_the_cv(cv) -> None:
    """Phase 1 exists to test whether CV claims survive interrogation."""
    questions = build_session(cv, company="MoJ", job_title="Data Engineer", limit=3)
    assert len(questions) == 3
    assert all(q.cv_source for q in questions)
    assert all("You state:" in q.text for q in questions)


def test_phase_1_targets_quantified_claims(cv) -> None:
    questions = build_session(cv, company="MoJ", job_title="X", limit=5)
    assert any("%" in q.text or "000" in q.text for q in questions)


def test_phase_1_probes_vary(cv) -> None:
    questions = build_session(cv, company="MoJ", job_title="X", limit=4)
    tails = {q.text.split("—")[-1] for q in questions}
    assert len(tails) > 1


def test_phase_2_names_the_company(cv) -> None:
    questions = build_session(cv, company="Ministry of Justice", job_title="X",
                              phase=Phase.ADAPTIVE_RUNTIME_CASE_STUDY)
    assert any("Ministry of Justice" in q.text for q in questions)


def test_phase_3_asks_what_you_did(cv) -> None:
    """Sustained 'we' where the question asked what YOU did caps D5 at 1."""
    questions = build_session(cv, company="MoJ", job_title="X",
                              phase=Phase.EXECUTIVE_BEHAVIOURAL)
    assert any("YOUR" in q.text or "your" in q.text for q in questions)


def test_limit_is_respected(cv) -> None:
    assert len(build_session(cv, company="X", job_title="Y", limit=2)) == 2
