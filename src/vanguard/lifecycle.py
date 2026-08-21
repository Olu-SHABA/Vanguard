"""
Application lifecycle — where an application got to, and where it stopped.

The process record counted rounds. A round is not a stage: "round 2" says
nothing about whether that was a phone screen, a take-home exercise or a
final panel, and the invitation almost always says which.

Worse, every rejection looked alike. Rejected on the CV and rejected after a
final panel were the same state, and they mean opposite things — the second
says the CV worked and something later did not.

## What is inferred, and what is not

**Stage identity** is inferred from the invitation. Employers name what they
are inviting you to, and the vocabulary is small.

**Stage outcome** is inferred from what follows. An invitation to a later
stage means the earlier one was passed; a decline means the current stage was
failed. Silence means neither, and is left as `PENDING` rather than guessed
at.

**The reason for failure is NOT inferred.**

This is the important line. Rejection emails rarely give a reason, and where
they do it is usually "we had many strong candidates". Manufacturing a cause
from an email that states none would be inventing exactly the kind of
authoritative-sounding content this system exists to prevent.

So a stated reason is extracted verbatim and labelled as stated. Where none
is given, the record says none was given.

## Where the answer actually is

Not in any single rejection — in the aggregate:

    12 of 20 applications ended at CV stage
     5 acknowledged, then silence
     2 failed at technical assessment
     1 reached final panel

That is a finding about where an application dies, and it is computed rather
than asserted. It is also the thing a coverage score cannot tell you.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

__all__ = [
    "Stage",
    "StageOutcome",
    "LifecyclePoint",
    "infer_stage",
    "extract_stated_reason",
    "FUNNEL_ORDER",
]


class Stage(str, Enum):
    """What an employer invited the applicant to.

    Ordered by how far through a process it usually sits, so a funnel can be
    built without a per-employer model.
    """

    APPLICATION = "APPLICATION"        # nothing beyond submission
    SCREEN = "SCREEN"                  # recruiter call, informal chat
    ASSESSMENT = "ASSESSMENT"          # test, take-home, coding exercise
    INTERVIEW = "INTERVIEW"            # a technical or competency interview
    PANEL = "PANEL"                    # multiple interviewers, later stage
    FINAL = "FINAL"                    # final round, meet-the-team, offer stage
    UNKNOWN = "UNKNOWN"                # invited to something unnamed


#: Funnel order. `UNKNOWN` sits with whatever round it belongs to rather than
#: at either end, so it never distorts the shape.
FUNNEL_ORDER: tuple[Stage, ...] = (
    Stage.APPLICATION, Stage.SCREEN, Stage.ASSESSMENT,
    Stage.INTERVIEW, Stage.PANEL, Stage.FINAL,
)


class StageOutcome(str, Enum):
    PENDING = "PENDING"    # invited, nothing since
    PASSED = "PASSED"      # a later stage followed
    FAILED = "FAILED"      # the process ended here
    LAPSED = "LAPSED"      # silence past the timeout


#: Phrases naming a stage, checked in order of specificity — "final interview"
#: must be read as FINAL rather than as INTERVIEW.
_STAGE_MARKERS: tuple[tuple[Stage, tuple[str, ...]], ...] = (
    (Stage.FINAL, (
        "final interview", "final stage", "final round", "last stage",
        "meet the team", "meet the founders", "meet our", "onsite",
        "on-site interview", "culture interview", "values interview",
    )),
    (Stage.PANEL, (
        "panel interview", "panel", "interview panel", "assessment centre",
        "assessment center", "with the team", "several members",
    )),
    (Stage.ASSESSMENT, (
        "technical assessment", "technical test", "coding test",
        "coding exercise", "take home", "take-home", "case study",
        "written exercise", "online assessment", "skills test",
        "psychometric", "aptitude test", "hackerrank", "codility",
        "practical exercise", "data challenge",
    )),
    (Stage.SCREEN, (
        "initial call", "introductory call", "intro call", "informal chat",
        "quick chat", "screening call", "phone screen", "telephone interview",
        "initial conversation", "first conversation", "short call",
        "recruiter call", "discovery call", "get to know",
    )),
    (Stage.INTERVIEW, (
        "second interview", "first interview", "technical interview",
        "competency interview", "formal interview", "interview with",
        "invite you to interview", "interview for the", "an interview",
    )),
)

#: Reason phrases. A rejection that gives one usually says so plainly; the
#: sentence containing the phrase is kept VERBATIM and nothing is
#: paraphrased, because a paraphrased reason is an invented one.
_REASON_MARKERS: tuple[str, ...] = (
    "we are looking for", "we were looking for", "we need someone with",
    "candidates with more", "more experience in", "closer match",
    "stronger match", "better aligned", "did not meet", "does not meet",
    "lacked", "lacking", "without the required", "requires experience",
    "essential criteria", "minimum requirement", "not enough experience",
    "decided to proceed with", "proceeding with candidates",
    "role has been filled", "position has been filled", "role is on hold",
    "on hold", "no longer recruiting", "withdrawn the role",
    "unable to offer sponsorship", "right to work", "security clearance",
    "salary expectations", "notice period",
)

#: Phrases that look like reasons and are not. "We had many strong
#: applicants" explains nothing about this application, and recording it as
#: a reason would fill the register with noise that reads as insight.
_NON_REASONS: tuple[str, ...] = (
    "many strong", "high volume", "large number of applic",
    "exceptionally strong field", "competitive process",
    "difficult decision", "very difficult", "not a reflection",
    "encourage you to apply", "keep your details", "future opportunities",
)


@dataclass
class LifecyclePoint:
    """How far an application got, and what ended it."""

    vacancy_id: str
    reached: Stage = Stage.APPLICATION
    outcome: StageOutcome = StageOutcome.PENDING
    stages: list[tuple[int, Stage, StageOutcome]] = field(default_factory=list)
    stated_reason: str = ""
    reason_is_stated: bool = False

    @property
    def depth(self) -> int:
        """How far through a typical process, for ordering a funnel."""
        try:
            return FUNNEL_ORDER.index(self.reached)
        except ValueError:
            return len(self.stages)

    def describe(self) -> str:
        if self.outcome is StageOutcome.FAILED:
            where = ("at application" if self.reached is Stage.APPLICATION
                     else f"at {self.reached.value.lower()}")
            return f"ended {where}"
        if self.outcome is StageOutcome.PASSED:
            return f"offer after {self.reached.value.lower()}"
        if self.outcome is StageOutcome.LAPSED:
            return f"silent after {self.reached.value.lower()}"
        return f"at {self.reached.value.lower()}"

    def why(self) -> str:
        """The stated reason, or an honest absence.

        Never a guess. A rejection that gives no reason is recorded as giving
        none, because the alternative is manufacturing one.
        """
        if self.reason_is_stated and self.stated_reason:
            return self.stated_reason
        if self.outcome is StageOutcome.FAILED:
            return "no reason given"
        return ""


def infer_stage(subject: str, body: str = "") -> Stage:
    """What is this message inviting the applicant to?

    Checked in order of specificity: "final interview" is FINAL, not
    INTERVIEW. Where an employer names nothing, UNKNOWN — a guess would put
    an application at the wrong depth in the funnel, and the funnel is the
    output that matters.
    """
    text = f"{subject or ''}\n{body or ''}".lower()
    for stage, markers in _STAGE_MARKERS:
        if any(marker in text for marker in markers):
            return stage
    return Stage.UNKNOWN


def extract_stated_reason(body: str) -> tuple[str, bool]:
    """A reason for rejection, verbatim, or nothing.

    Returns `(sentence, was_stated)`. The sentence is copied exactly — a
    paraphrased reason is an invented one, and this is the one place in the
    system where inventing would look most like insight.

    Softeners are excluded. "We had many strong applicants" says nothing
    about this application, and recording it would fill the register with
    noise that reads as a finding.
    """
    if not body:
        return "", False

    for raw in re.split(r"(?<=[.!?])\s+|\n+", body):
        sentence = raw.strip()
        if not sentence or len(sentence) > 400:
            continue
        low = sentence.lower()

        if any(phrase in low for phrase in _NON_REASONS):
            continue
        if any(marker in low for marker in _REASON_MARKERS):
            return sentence, True

    return "", False


def build_lifecycle(vacancy_id: str, messages: Sequence[dict]) -> LifecyclePoint:
    """Reconstruct how far an application got from its messages, in order.

    Each message is a mapping with `state`, `subject` and `body`.

    Outcomes are inferred from what FOLLOWS, which is the only honest source:
    an invitation to a later stage means the earlier one was passed. Silence
    means neither passed nor failed, and stays PENDING.
    """
    point = LifecyclePoint(vacancy_id=vacancy_id)
    ordered = sorted(messages, key=lambda m: m.get("received_at") or "")

    number = 0
    for message in ordered:
        state = (message.get("state") or "").upper()
        subject = message.get("subject") or ""
        body = message.get("body") or ""

        if state == "PROGRESS":
            # Whatever stage was open is now passed — they invited you on.
            if point.stages:
                index, stage, _ = point.stages[-1]
                point.stages[-1] = (index, stage, StageOutcome.PASSED)

            number += 1
            stage = infer_stage(subject, body)
            point.stages.append((number, stage, StageOutcome.PENDING))
            point.reached = stage if stage is not Stage.UNKNOWN else point.reached
            point.outcome = StageOutcome.PENDING

        elif state == "DECLINE":
            if point.stages:
                index, stage, _ = point.stages[-1]
                point.stages[-1] = (index, stage, StageOutcome.FAILED)
                point.reached = stage if stage is not Stage.UNKNOWN else point.reached
            else:
                point.reached = Stage.APPLICATION
            point.outcome = StageOutcome.FAILED

            reason, stated = extract_stated_reason(body)
            if stated:
                point.stated_reason, point.reason_is_stated = reason, True

        elif state == "OFFER":
            if point.stages:
                index, stage, _ = point.stages[-1]
                point.stages[-1] = (index, stage, StageOutcome.PASSED)
            point.outcome = StageOutcome.PASSED

    return point
