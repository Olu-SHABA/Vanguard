"""Application lifecycle — where an application got to, and where it stopped."""
from __future__ import annotations

import pytest

from vanguard.lifecycle import (
    FUNNEL_ORDER,
    Stage,
    StageOutcome,
    build_lifecycle,
    extract_stated_reason,
    infer_stage,
)


# --- stage inference ------------------------------------------------------

@pytest.mark.parametrize(
    "subject, stage",
    [
        ("We would like to invite you to an initial call", Stage.SCREEN),
        ("Quick chat about the role", Stage.SCREEN),
        ("Invitation: technical assessment", Stage.ASSESSMENT),
        ("Please complete this take-home exercise", Stage.ASSESSMENT),
        ("Second interview with the engineering team", Stage.INTERVIEW),
        ("Panel interview invitation", Stage.PANEL),
        ("Final interview — meet the team", Stage.FINAL),
    ],
)
def test_stages_are_named_from_the_invitation(subject: str,
                                              stage: Stage) -> None:
    """"Round 2" says nothing about whether that was a phone screen, a
    take-home or a panel. The invitation almost always says."""
    assert infer_stage(subject) is stage


def test_specificity_wins() -> None:
    """"Final interview" is FINAL, not INTERVIEW."""
    assert infer_stage("Final interview") is Stage.FINAL
    assert infer_stage("Panel interview") is Stage.PANEL


def test_an_unnamed_invitation_is_unknown() -> None:
    """A guess would put an application at the wrong depth, and the funnel is
    the output that matters."""
    assert infer_stage("We would like to speak with you") is Stage.UNKNOWN


# --- outcomes are inferred from what follows ------------------------------

def _messages(*pairs) -> list[dict]:
    return [{"state": state, "subject": subject, "body": body,
             "received_at": f"2026-08-{10 + i:02d}"}
            for i, (state, subject, body) in enumerate(pairs)]


def test_a_later_invitation_means_the_earlier_stage_passed() -> None:
    point = build_lifecycle("reed:1", _messages(
        ("PROGRESS", "Introductory call", ""),
        ("PROGRESS", "Technical assessment", ""),
    ))
    assert point.stages[0][2] is StageOutcome.PASSED
    assert point.stages[1][2] is StageOutcome.PENDING


def test_a_decline_fails_the_stage_it_arrives_at() -> None:
    point = build_lifecycle("reed:1", _messages(
        ("PROGRESS", "Introductory call", ""),
        ("PROGRESS", "Final panel interview", ""),
        ("DECLINE", "Update", "You have not been successful."),
    ))
    assert point.reached is Stage.PANEL
    assert point.outcome is StageOutcome.FAILED
    assert "panel" in point.describe()


def test_rejection_at_cv_stage_is_distinguishable() -> None:
    """Rejected on the CV and rejected after a final panel were the same
    state, and they mean opposite things."""
    early = build_lifecycle("reed:1", _messages(
        ("DECLINE", "Your application", "Not successful.")))
    late = build_lifecycle("reed:2", _messages(
        ("PROGRESS", "Final interview", ""),
        ("DECLINE", "Update", "Not successful.")))

    assert early.reached is Stage.APPLICATION
    assert late.reached is Stage.FINAL
    assert early.depth < late.depth


def test_silence_is_not_an_outcome() -> None:
    """An employer going quiet has neither passed nor failed the applicant."""
    point = build_lifecycle("reed:1", _messages(
        ("ACK", "Thank you for applying", "")))
    assert point.outcome is StageOutcome.PENDING


def test_an_offer_passes_the_last_stage() -> None:
    point = build_lifecycle("reed:1", _messages(
        ("PROGRESS", "Final interview", ""),
        ("OFFER", "We are pleased to offer you the position", ""),
    ))
    assert point.outcome is StageOutcome.PASSED
    assert point.stages[-1][2] is StageOutcome.PASSED


# --- reasons are never invented -------------------------------------------

def test_a_stated_reason_is_kept_verbatim() -> None:
    """A paraphrased reason is an invented one, and this is the place where
    inventing would look most like insight."""
    body = ("Thank you for your time. We are looking for someone with more "
            "experience in Spark.")
    reason, stated = extract_stated_reason(body)
    assert stated
    assert reason == "We are looking for someone with more experience in Spark."


def test_a_softener_is_not_a_reason() -> None:
    """"We had many strong applicants" says nothing about THIS application,
    and recording it would fill the register with noise that reads as a
    finding."""
    for body in ("We had many strong candidates on this occasion.",
                 "This was a very difficult decision.",
                 "It is not a reflection of your ability."):
        _, stated = extract_stated_reason(body)
        assert not stated, body


def test_a_reason_is_found_past_a_softener() -> None:
    body = ("We had many strong candidates. We decided to proceed with "
            "someone who has more experience in distributed systems.")
    reason, stated = extract_stated_reason(body)
    assert stated
    assert "distributed systems" in reason


def test_no_reason_means_no_reason() -> None:
    point = build_lifecycle("reed:1", _messages(
        ("DECLINE", "Your application",
         "Unfortunately you have not been successful on this occasion.")))
    assert not point.reason_is_stated
    assert point.why() == "no reason given"


def test_nothing_is_reported_where_nothing_failed() -> None:
    point = build_lifecycle("reed:1", _messages(
        ("ACK", "Thanks", "")))
    assert point.why() == ""


# --- funnel ordering ------------------------------------------------------

def test_the_funnel_is_ordered_by_depth() -> None:
    assert FUNNEL_ORDER.index(Stage.APPLICATION) < FUNNEL_ORDER.index(Stage.SCREEN)
    assert FUNNEL_ORDER.index(Stage.ASSESSMENT) < FUNNEL_ORDER.index(Stage.FINAL)


def test_an_unknown_stage_does_not_distort_depth() -> None:
    """An unnamed invitation must not push an application to the front or the
    back of the funnel."""
    point = build_lifecycle("reed:1", _messages(
        ("PROGRESS", "Technical assessment", ""),
        ("PROGRESS", "We would like to speak with you", ""),
    ))
    assert point.reached is Stage.ASSESSMENT
