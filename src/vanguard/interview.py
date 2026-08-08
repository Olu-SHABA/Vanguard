"""
Templates D and E — operator-initiated, never autonomous.

Directive §6: no classification state triggers an outbound action. A DECLINE
does not send a feedback request; a PROGRESS does not start an interview
session. Both are invoked by the operator against a queued record.

Template D — Defensive Pivot
    A feedback request after a decline. **Drafted here, sent by the operator.**
    Vanguard has no transmission path and this module creates none.

Template E — Offensive Sprint
    Three-phase interview simulation, graded on D1–D5, 0–3 with behavioural
    anchors. Questions are generated from the CV that was actually submitted,
    because Phase 1's purpose is to test whether claims survive interrogation.

    D1 = 0 is terminal. An unsupported claim cannot be rescued by good
    reasoning, and catching that before a panel does is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Sequence

from vanguard.cv import CanonicalCV, CVSection
from vanguard.mail import State

__all__ = [
    "Dimension",
    "Phase",
    "InterviewQuestion",
    "ScoreVector",
    "draft_feedback_request",
    "build_session",
    "PASS_LINE",
]

PASS_LINE = 2
MAX_SCORE = 3


class OperatorActionError(RuntimeError):
    """An artefact was requested that the classification does not warrant."""


# ---------------------------------------------------------------------------
# Template D — Defensive Pivot
# ---------------------------------------------------------------------------

def draft_feedback_request(
    *,
    job_title: str,
    company: str,
    applicant_name: str,
    contact: str,
    recipient: str = "Recruitment Team",
    state: State = State.DECLINE,
) -> str:
    """Draft a feedback request. Returns text; sends nothing.

    Raises unless the classification is DECLINE. DORMANT is a derived state,
    not a classification — an application that has gone quiet has not been
    declined, and asking for feedback on a decision nobody made is worse than
    saying nothing.
    """
    if state is not State.DECLINE:
        raise OperatorActionError(
            f"Template D applies to DECLINE only, not {state.value}. "
            "Silence is not a rejection."
        )

    return f"""**Subject:** Re: {job_title} Application - {applicant_name}

Dear {recipient},

Thank you for providing the update regarding the {job_title} position at \
{company}. While I am disappointed that my application will not be moving \
forward at this time, I sincerely appreciate the effort your team invested in \
evaluating my profile.

As a data professional who prioritises continuous optimisation, I treat every \
outcome as valuable data. I am committed to refining my portfolio to meet the \
technical standards expected by teams operating at your scale.

If your schedule permits, I would be grateful for brief feedback on two areas:

* Were there specific technical competencies identified in my file that fell \
short of your requirements?
* Was there a particular aspect of my hands-on experience in infrastructure \
management or applied analytics that lacked the necessary depth?

Your insights will be valuable as I refine my approach for future applications. \
Thank you again, and I wish {company} continued success with the appointment.

Sincerely,

{applicant_name}
{contact}
"""


# ---------------------------------------------------------------------------
# Template E — Offensive Sprint
# ---------------------------------------------------------------------------

class Dimension(IntEnum):
    D1_CV_GROUNDING = 1
    D2_QUANTIFICATION = 2
    D3_CONSTRAINT_AWARENESS = 3
    D4_DECISION_JUSTIFICATION = 4
    D5_NARRATIVE_STRUCTURE = 5

    @property
    def label(self) -> str:
        return {
            1: "CV GROUNDING", 2: "QUANTIFICATION", 3: "CONSTRAINT AWARENESS",
            4: "DECISION JUSTIFICATION", 5: "NARRATIVE STRUCTURE",
        }[int(self)]

    @property
    def phase_3_only(self) -> bool:
        return self is Dimension.D5_NARRATIVE_STRUCTURE

    @property
    def terminal_at_zero(self) -> bool:
        """D1 = 0 fails the response outright, whatever else scores."""
        return self is Dimension.D1_CV_GROUNDING


class Phase(IntEnum):
    CV_CLAIMS_VERIFICATION = 1
    ADAPTIVE_RUNTIME_CASE_STUDY = 2
    EXECUTIVE_BEHAVIOURAL = 3

    @property
    def title(self) -> str:
        return {
            1: "CV CLAIMS VERIFICATION (TECHNICAL GROUNDING)",
            2: "ADAPTIVE RUNTIME CASE STUDY",
            3: "EXECUTIVE BEHAVIOURAL PRESSURE TEST",
        }[int(self)]

    @property
    def dimensions(self) -> tuple[Dimension, ...]:
        base = tuple(d for d in Dimension if not d.phase_3_only)
        return tuple(Dimension) if self is Phase.EXECUTIVE_BEHAVIOURAL else base

    @property
    def max_aggregate(self) -> int:
        return len(self.dimensions) * MAX_SCORE


@dataclass(frozen=True)
class InterviewQuestion:
    phase: Phase
    text: str
    cv_source: str = ""     # the CV line under interrogation, if any

    def __str__(self) -> str:
        return f"[Phase {int(self.phase)}] {self.text}"


@dataclass
class ScoreVector:
    """Per-dimension scores for one response. Report the vector, not the total.

    A 2/2/2/2 and a 3/3/1/1 both total 8 and mean different things.
    """

    scores: dict[Dimension, int] = field(default_factory=dict)
    justifications: dict[Dimension, str] = field(default_factory=dict)

    def record(self, dimension: Dimension, score: int, justification: str) -> None:
        if not 0 <= score <= MAX_SCORE:
            raise ValueError(f"score must be 0-{MAX_SCORE}, got {score}")
        if not justification.strip():
            raise ValueError(
                f"{dimension.label} scored {score} without justification — "
                "bare numbers are not permitted"
            )
        self.scores[dimension] = score
        self.justifications[dimension] = justification.strip()

    @property
    def total(self) -> int:
        return sum(self.scores.values())

    @property
    def terminal_failure(self) -> bool:
        return self.scores.get(Dimension.D1_CV_GROUNDING) == 0

    @property
    def below_pass_line(self) -> list[Dimension]:
        """Any dimension at 0-1 is re-interrogated before the phase advances."""
        return [d for d, s in self.scores.items() if s < PASS_LINE]

    def vector(self) -> str:
        return "/".join(
            str(self.scores.get(d, "-")) for d in sorted(self.scores, key=int)
        )

    def report(self) -> str:
        if self.terminal_failure:
            head = "TERMINAL — D1 = 0. An unsupported claim cannot be rescued."
        else:
            head = f"vector {self.vector()}   total {self.total}"
        lines = [head]
        for dimension in sorted(self.scores, key=int):
            lines.append(
                f"  D{int(dimension)} {dimension.label:<24} "
                f"{self.scores[dimension]}  {self.justifications[dimension]}"
            )
        if self.below_pass_line and not self.terminal_failure:
            names = ", ".join(f"D{int(d)}" for d in self.below_pass_line)
            lines.append(f"  re-interrogate before advancing: {names}")
        return "\n".join(lines)


def build_session(
    cv: CanonicalCV,
    *,
    company: str,
    job_title: str,
    phase: Phase = Phase.CV_CLAIMS_VERIFICATION,
    limit: int = 5,
) -> list[InterviewQuestion]:
    """Generate questions for one phase, grounded in the submitted CV.

    Phase 1 targets quantified bullets specifically. A claim carrying a figure
    is the one a panel will probe, and the one where an unsupported answer
    does most damage.
    """
    if phase is Phase.CV_CLAIMS_VERIFICATION:
        return _phase_1(cv, limit)
    if phase is Phase.ADAPTIVE_RUNTIME_CASE_STUDY:
        return _phase_2(company, job_title)
    return _phase_3(company)


_QUANTIFIED = ("%", "000", "99.", "seconds", "minutes", "hours")


def _phase_1(cv: CanonicalCV, limit: int) -> list[InterviewQuestion]:
    """Interrogate quantified claims: dependencies, bottlenecks, limits."""
    probes = (
        "How was this measured, against what baseline?",
        "What were the memory and throughput limits, and what did you do when you hit them?",
        "What dependencies did this rest on, and what happened when one failed?",
        "What alternative did you reject, and on what grounds?",
        "What broke first as the input grew, and how did you find out?",
    )
    questions: list[InterviewQuestion] = []
    for section, bullet in cv.all_bullets():
        if not any(token in bullet for token in _QUANTIFIED):
            continue
        probe = probes[len(questions) % len(probes)]
        questions.append(InterviewQuestion(
            Phase.CV_CLAIMS_VERIFICATION,
            f"You state: \"{bullet[:150]}\" — {probe}",
            cv_source=section.source_role,
        ))
        if len(questions) >= limit:
            break
    return questions


def _phase_2(company: str, job_title: str) -> list[InterviewQuestion]:
    return [
        InterviewQuestion(
            Phase.ADAPTIVE_RUNTIME_CASE_STUDY,
            f"A nightly pipeline feeding {company}'s reporting has silently produced "
            "partial output for three days. Nobody noticed until a stakeholder queried "
            "a figure. Blueprint your response in 15 minutes: detection, containment, "
            "root cause, and what you change so it cannot recur silently.",
        ),
        InterviewQuestion(
            Phase.ADAPTIVE_RUNTIME_CASE_STUDY,
            f"You inherit an undocumented ETL process critical to {job_title} work. "
            "It runs, but nobody knows how. What do you do first, and what do you "
            "refuse to change until you know more?",
        ),
    ]


def _phase_3(company: str) -> list[InterviewQuestion]:
    return [
        InterviewQuestion(
            Phase.EXECUTIVE_BEHAVIOURAL,
            "Describe a service failure you owned end to end. What was YOUR "
            "specific responsibility, distinguishable from the team's?",
        ),
        InterviewQuestion(
            Phase.EXECUTIVE_BEHAVIOURAL,
            "Tell me about a time you disagreed with a vendor or supplier on a "
            "technical decision under time pressure. How did it resolve?",
        ),
        InterviewQuestion(
            Phase.EXECUTIVE_BEHAVIOURAL,
            f"Describe an architecture change you argued for that carried real risk. "
            f"How did you make the case, and what would you tell {company} about it now?",
        ),
    ]
