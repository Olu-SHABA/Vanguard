"""
Response tracking — Route 5.

Directive §6. Ingests inbound mail from the monitored mailbox. Autonomous
context: classify, record, exit. **Never sends. Never replies.**

Two operations, in strict order:

    1. CORRELATION   match the message to an open application
    2. CLASSIFICATION assign one of six mutually exclusive states

Correlation runs first and is not a classification outcome. Unmatched mail is
recorded `UNCORRELATED` and never classified — guessing which application a
message belongs to would attach a DECLINE to the wrong vacancy.

Classification order is load-bearing:

    RULE 1  DECLINE   checked FIRST
    RULE 2  PROGRESS
    RULE 3  ACK
    RULE 4  anything remaining -> AMBIGUOUS

**Decline outranks progress deliberately.** Rejection emails are written to
soften and routinely open with warm, encouraging language — "we were very
impressed", "we would like to keep your details". Checking PROGRESS first
would misclassify a substantial share of rejections as invitations, and the
operator would prepare for an interview that does not exist.

Matching is whole-phrase, case-insensitive, word-boundary anchored. Bare
substring matching is prohibited: the original design matched "Call", which
fires on *recall*, *called* and *callback*.

No state triggers an outbound action. Templates D and E are interactive
operations the operator initiates against a queued record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Sequence

__all__ = [
    "State",
    "Correlation",
    "Message",
    "Classification",
    "correlate",
    "classify",
    "dormant_sweep",
    "DECLINE_MARKERS",
    "PROGRESS_MARKERS",
    "ACK_MARKERS",
]


class State(str, Enum):
    ACK = "ACK"                    # receipt only, no decision conveyed
    PROGRESS = "PROGRESS"          # advancement requested
    DECLINE = "DECLINE"            # closed unsuccessfully
    QUERY = "QUERY"                # employer asks a question needing a human
    ADMIN = "ADMIN"                # scheduling logistics, no decision
    AMBIGUOUS = "AMBIGUOUS"        # confidence low, or signals conflict

    @property
    def needs_human(self) -> bool:
        return self in (State.QUERY, State.AMBIGUOUS, State.PROGRESS)

    @property
    def invites_template(self) -> str:
        """Which template the OPERATOR may choose to invoke. Never automatic."""
        if self is State.PROGRESS:
            return "E"   # Offensive Sprint — interview simulation
        if self is State.DECLINE:
            return "D"   # Defensive Pivot — feedback request
        return ""


class Correlation(str, Enum):
    REFERENCE = "reference"        # application reference or vacancy id
    SENDER_DOMAIN = "sender_domain"
    FUZZY = "fuzzy"                # employer + title in subject
    NONE = "none"


# --- markers ---------------------------------------------------------------
# Whole phrases only. A single token is never sufficient to classify.

DECLINE_MARKERS: tuple[str, ...] = (
    "not been successful",
    "unsuccessful on this occasion",
    "will not be progressing",
    "decided not to take your application further",
    "unsuccessful this time",
    "not to progress your application",
    "we will not be taking your application further",
    "have decided not to proceed",
    "regret to inform you",
)

PROGRESS_MARKERS: tuple[str, ...] = (
    "would like to invite",
    "invite you to interview",
    "invite you to an interview",
    "schedule a",
    "arrange a time",
    "next stage",
    "technical assessment",
    "would like to speak with you",
    "pleased to inform you that you have been shortlisted",
    "invite you to the next",
)

ACK_MARKERS: tuple[str, ...] = (
    "we have received your application",
    "thank you for applying",
    "application received",
    "your application has been received",
    "confirmation of your application",
)

QUERY_MARKERS: tuple[str, ...] = (
    "could you confirm",
    "please confirm",
    "we require further information",
    "can you provide",
    "we need some additional",
    "please let us know",
)

ADMIN_MARKERS: tuple[str, ...] = (
    "reset your password",
    "portal maintenance",
    "your account",
    "update your details",
    "calendar invitation",
    "reschedule",
)


def _phrase(text_low: str, marker: str) -> bool:
    """Whole-phrase, word-boundary anchored. Never bare substring."""
    return re.search(rf"(?<![\w-]){re.escape(marker)}(?![\w-])", text_low) is not None


def _matches(text_low: str, markers: Iterable[str]) -> list[str]:
    return [m for m in markers if _phrase(text_low, m)]


# --- models ----------------------------------------------------------------

@dataclass
class Message:
    """One inbound message. Parsed elsewhere; this is the shape."""

    message_id: str
    sender: str
    subject: str
    body: str
    received: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def text(self) -> str:
        return f"{self.subject}\n{self.body}"

    @property
    def sender_domain(self) -> str:
        return self.sender.rsplit("@", 1)[-1].lower().strip() if "@" in self.sender else ""


@dataclass
class Application:
    """The minimum an open application must expose to be correlated against."""

    vacancy_id: str
    employer: str
    title: str
    reference: str = ""
    employer_domain: str = ""
    submitted: datetime | None = None


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying one correlated message."""

    state: State
    rule: int                      # which rule fired: 1-4
    markers: tuple[str, ...] = ()
    note: str = ""

    def __str__(self) -> str:
        fired = ", ".join(self.markers[:2]) if self.markers else "no marker"
        return f"{self.state.value} (rule {self.rule}: {fired})"


@dataclass(frozen=True)
class CorrelationResult:
    application: Application | None
    method: Correlation

    @property
    def correlated(self) -> bool:
        return self.application is not None


# --- correlation -----------------------------------------------------------

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _norm(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", (text or "").lower())).strip()


def correlate(
    message: Message, applications: Sequence[Application]
) -> CorrelationResult:
    """Match a message to an open application. Runs BEFORE classification.

    Three stages, in order of confidence. Correlation failure is not a
    classification outcome — an uncorrelated message is queued for review, not
    guessed at.
    """
    text_low = message.text.lower()

    # 1. Application reference or vacancy id — highest confidence.
    for app in applications:
        for token in (app.reference, app.vacancy_id.split(":")[-1]):
            if token and len(token) >= 4 and token.lower() in text_low:
                return CorrelationResult(app, Correlation.REFERENCE)

    # 2. Sender domain against the employer domain on the vacancy record.
    domain = message.sender_domain
    if domain:
        for app in applications:
            emp_domain = (app.employer_domain or "").lower().strip()
            if emp_domain and (domain == emp_domain or domain.endswith("." + emp_domain)):
                return CorrelationResult(app, Correlation.SENDER_DOMAIN)

    # 3. Employer name AND job title in the subject. Both, not either —
    #    "Data Engineer" alone would match every open data application.
    subject = _norm(message.subject)
    for app in applications:
        employer, title = _norm(app.employer), _norm(app.title)
        if employer and title and employer in subject and title in subject:
            return CorrelationResult(app, Correlation.FUZZY)

    return CorrelationResult(None, Correlation.NONE)


# --- classification --------------------------------------------------------

def classify(message: Message) -> Classification:
    """Assign one of six states. First rule to fire wins.

    DECLINE is checked before PROGRESS. A decline phrase always wins over a
    progress phrase in the same message.
    """
    low = message.text.lower()

    # RULE 1 — DECLINE. First, and it outranks everything.
    declines = _matches(low, DECLINE_MARKERS)
    if declines:
        progress = _matches(low, PROGRESS_MARKERS)
        note = (
            "decline outranks progress phrasing in the same message"
            if progress else ""
        )
        return Classification(State.DECLINE, 1, tuple(declines), note)

    # RULE 2 — PROGRESS.
    progress = _matches(low, PROGRESS_MARKERS)
    if progress:
        return Classification(State.PROGRESS, 2, tuple(progress))

    # RULE 3 — ACK. Receipt only. An ACK carrying a question is a QUERY.
    acks = _matches(low, ACK_MARKERS)
    if acks:
        queries = _matches(low, QUERY_MARKERS)
        if queries:
            return Classification(
                State.QUERY, 3, tuple(acks + queries),
                "acknowledgement carrying a question requiring a human answer",
            )
        return Classification(State.ACK, 3, tuple(acks))

    # RULE 3b — QUERY and ADMIN, where no stronger signal is present.
    queries = _matches(low, QUERY_MARKERS)
    if queries:
        return Classification(State.QUERY, 3, tuple(queries))

    admin = _matches(low, ADMIN_MARKERS)
    if admin:
        return Classification(State.ADMIN, 3, tuple(admin))

    # RULE 4 — everything else. Surfaced to the operator, never forced.
    return Classification(
        State.AMBIGUOUS, 4, (),
        "no marker fired — review manually rather than assume",
    )


# --- dormancy --------------------------------------------------------------

@dataclass(frozen=True)
class DormantCandidate:
    vacancy_id: str
    submitted: datetime
    days_silent: int
    silence_days: int


def dormant_sweep(
    applications: Sequence[Application],
    correlated_ids: Iterable[str],
    silence_days_for,
    *,
    now: datetime | None = None,
) -> list[DormantCandidate]:
    """Applications with no correlated inbound mail after `silence_days`.

    DORMANT is a **derived state, not a classification.** It is never treated
    as DECLINE and never triggers Template D — silence is an absence of
    information, not a rejection, and employers do go quiet and return.

    `silence_days_for(board_id)` resolves per-board from boards.yaml, falling
    back to the global default. 21 days globally, 30 for public sector.
    """
    now = now or datetime.now(timezone.utc)
    heard_from = set(correlated_ids)
    out: list[DormantCandidate] = []

    for app in applications:
        if app.vacancy_id in heard_from or app.submitted is None:
            continue
        submitted = app.submitted
        if submitted.tzinfo is None:
            submitted = submitted.replace(tzinfo=timezone.utc)
        elapsed = (now - submitted).days
        limit = silence_days_for(app.vacancy_id.split(":")[0])
        if elapsed >= limit:
            out.append(DormantCandidate(app.vacancy_id, submitted, elapsed, limit))

    return out
