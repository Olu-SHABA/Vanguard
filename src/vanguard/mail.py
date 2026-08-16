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
    "is_broadcast",
    "looks_like_an_acknowledgement",
    "domain_of",
    "classify",
    "dormant_sweep",
    "DECLINE_MARKERS",
    "OFFER_MARKERS",
    "is_broadcast",
    "looks_like_an_acknowledgement",
    "domain_of",
    "domain_of",
    "PROGRESS_MARKERS",
    "ACK_MARKERS",
]


class State(str, Enum):
    """Classification of one inbound message.

    OFFER was added 12 Aug 2026. Without it a job offer fell through to
    AMBIGUOUS — the single worst message to leave unclassified, and the one
    that terminates an interview process.
    """
    ACK = "ACK"                    # receipt only, no decision conveyed
    PROGRESS = "PROGRESS"          # advancement requested
    DECLINE = "DECLINE"            # closed unsuccessfully
    QUERY = "QUERY"                # employer asks a question needing a human
    ADMIN = "ADMIN"                # scheduling logistics, no decision
    OFFER = "OFFER"
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
    ATS = "ats"                    # applicant-tracking system, on behalf of the employer
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

#: An offer terminates the process. Checked BEFORE progress, because an offer
#: routinely invites a further conversation — "we would like to offer you the
#: position, and would like to arrange a call to discuss" would otherwise read
#: as another interview round.
#:
#: Added 12 Aug 2026. Without it an offer fell through to AMBIGUOUS, which is
#: the single worst message to leave unclassified.
OFFER_MARKERS: tuple[str, ...] = (
    "pleased to offer you",
    "delighted to offer you",
    "happy to offer you",
    "would like to offer you",
    "we are offering you",
    "offer of employment",
    "formal offer",
    "job offer",
    "offer letter",
    "make you an offer",
    "welcome you to the team",
    "welcome to the team",
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


# ---------------------------------------------------------------------------
# Broadcast senders — never a reply to an application
#
# Observed 12 Aug 2026: `jobs-noreply@linkedin.com` advertising a Beatport
# vacancy was correlated to an open Beatport application, because the subject
# contained the employer name and a job title. It was an advert, not a reply.
#
# A broadcast is filtered BEFORE correlation. Attributing an advert to an
# application would file it in that application's archive and, if the wording
# happened to match, classify it as a decline.
# ---------------------------------------------------------------------------

#: Local parts that mark a mass mailing. `no-reply` alone is NOT here: many
#: employers send genuine application acknowledgements from a no-reply
#: address, and an automated receipt is still a reply.
_BROADCAST_LOCAL = (
    "jobs-noreply", "jobalerts-noreply", "notifications-noreply",
    "updates-noreply", "invitations", "donotreply", "do-not-reply",
    "newsletter", "jobalert", "marketing", "promotions",
)

_BROADCAST_DOMAIN = (
    "jobalert.indeed.com", "match.indeed.com", "jobs.cwjobs.co.uk",
    "jobs.totaljobsmail.com", "e.travelodge.co.uk", "builtin.com",
)

#: Subject phrases that mark an advert. Nobody writes these in a reply.
_ADVERT_SUBJECT = (
    "apply now", "new jobs", "jobs in", "job matches", "job alert",
    "jobs matching", "recommended for you", "jobs for you", "new job",
    "recently posted", "you appeared in", "want to connect",
)


def is_broadcast(message: Message) -> bool:
    """A mass mailing, not a reply to an application.

    Checked before correlation. A job board advertising a vacancy at an
    employer is not that employer writing back.
    """
    # An acknowledgement is never a broadcast, whatever the sender looks
    # like. `jobs-noreply@linkedin.com` sends both adverts and "your
    # application was sent to X" — the subject separates them.
    if looks_like_an_acknowledgement(message):
        return False

    sender = (message.sender or "").lower()
    local = sender.split("@", 1)[0]
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""

    if any(marker in local for marker in _BROADCAST_LOCAL):
        return True
    if any(domain.endswith(known) for known in _BROADCAST_DOMAIN):
        return True

    subject = (message.subject or "").lower()
    return any(phrase in subject for phrase in _ADVERT_SUBJECT)


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
    url: str = ""
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
# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _norm(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", (text or "").lower())).strip()


#: Words too common in employer names to identify anyone.
_COMMON_EMPLOYER_WORDS = frozenset({
    "group", "limited", "holdings", "services", "solutions", "technology",
    "technologies", "consulting", "consultancy", "international", "global",
    "systems", "partners", "associates", "company", "corporation",
})

# ---------------------------------------------------------------------------
# Applicant-tracking systems
#
# Observed 12 Aug 2026: four genuine acknowledgements failed to correlate.
#
#   notifications@app.bamboohr.com   "Thank you for applying at Beatport"
#   no-reply@ashbyhq.com             "Thank you for applying to Sardine!"
#   no-reply@ashbyhq.com             "Faculty | Application Confirmation"
#   no-reply@jobs.reed.co.uk         "We've sent your application to Method Resourcing"
#
# An ATS mails on the employer's behalf, so the sender domain is never the
# employer's. The employer name is in the SUBJECT.
#
# This is not the same as a job board advertising a vacancy, though both are
# third parties naming an employer. The difference is intent, and it is
# visible in the subject: an advert invites an application; an
# acknowledgement confirms one already made.
# ---------------------------------------------------------------------------

_ATS_DOMAINS = (
    "bamboohr.com", "ashbyhq.com", "greenhouse.io", "lever.co",
    "workable.com", "smartrecruiters.com", "teamtailor.com", "workday.com",
    "myworkdayjobs.com", "icims.com", "taleo.net", "successfactors.com",
    "jobvite.com", "breezy.hr", "recruitee.com", "pinpointhq.com",
    "applytojob.com", "hire.withgoogle.com", "personio.de", "factorialhr.com",
    "jobs.reed.co.uk", "notifications.linkedin.com",
)

#: Phrases marking an application ALREADY MADE. An advert never says these.
_APPLIED_PHRASES = (
    "thank you for applying", "thanks for applying", "application confirmation",
    "application received", "we have received your application",
    "your application was sent", "we've sent your application",
    "we have sent your application", "application submitted",
    "confirming your application", "your application to", "your application for",
    "application update", "regarding your application", "you applied",
)


def looks_like_an_acknowledgement(message: Message) -> bool:
    """The subject confirms an application already made.

    Distinguishes an ATS acknowledgement from a job board advert, both of
    which are third parties naming an employer.
    """
    subject = (message.subject or "").lower()
    return any(phrase in subject for phrase in _APPLIED_PHRASES)


def _sender_is_an_ats(domain: str) -> bool:
    domain = (domain or "").lower()
    return any(domain == known or domain.endswith("." + known)
               for known in _ATS_DOMAINS)


#: Domains that broker vacancies rather than employ. A message from one names
#: an employer without being from that employer.
_JOB_BOARD_DOMAINS = (
    "linkedin.com", "indeed.com", "reed.co.uk", "totaljobs.com",
    "totaljobsmail.com", "cwjobs.co.uk", "cv-library.co.uk", "monster.co.uk",
    "adzuna.co.uk", "glassdoor.com", "jobsite.co.uk", "builtin.com",
)


def domain_of(url: str) -> str:
    """The employer's domain from a vacancy URL, or empty for a job board.

    A vacancy hosted on the employer's own careers site tells us the domain
    their replies will come from. A vacancy on a job board tells us nothing —
    the board is not the employer.
    """
    if not url:
        return ""
    match = re.match(r"https?://([^/:?#]+)", url.strip(), re.I)
    if not match:
        return ""
    host = match.group(1).lower().removeprefix("www.")
    return "" if _sender_is_a_job_board(host) else host


def _sender_is_a_job_board(domain: str) -> bool:
    """True when the sender brokers vacancies rather than employs.

    Stops the fuzzy stage reading "LinkedIn writing about Beatport" as
    "Beatport writing to you".
    """
    domain = (domain or "").lower()
    return any(domain == known or domain.endswith("." + known)
               for known in _JOB_BOARD_DOMAINS)


def _sender_plausible(app: Application, domain: str) -> bool:
    """Could this sender be the employer, or someone acting for them?

    A subject naming an employer proves nothing about who sent it. Requiring
    some overlap between the sender domain and the employer name stops a job
    board's advert being read as the employer's reply.
    """
    if not domain:
        return False
    if app.employer_domain and domain.endswith(app.employer_domain.lower()):
        return True
    # Recruiters mail on an employer's behalf, so an exact match is too
    # strict. A shared distinctive token is enough.
    employer_tokens = {t for t in _norm(app.employer).split()
                       if len(t) > 3 and t not in _COMMON_EMPLOYER_WORDS}
    domain_text = domain.replace(".", " ").replace("-", " ")
    return any(token in domain_text for token in employer_tokens)


#: Words too common in employer names to identify anyone.
_COMMON_EMPLOYER_WORDS = frozenset({
    "group", "limited", "holdings", "services", "solutions", "technology",
    "technologies", "consulting", "consultancy", "international", "global",
    "systems", "partners", "associates", "company", "corporation",
})


def correlate(
    message: Message, applications: Sequence[Application]
) -> CorrelationResult:
    """Match a message to an open application. Runs BEFORE classification.

    Three stages, in order of confidence. Correlation failure is not a
    classification outcome — an uncorrelated message is queued for review, not
    guessed at.
    """
    # A broadcast is never a reply. Filtered first: a job board advertising a
    # vacancy at an employer must not be attributed to an application at that
    # employer.
    if is_broadcast(message):
        return CorrelationResult(None, Correlation.NONE)

    text_low = message.text.lower()

    # 1. Application reference or vacancy id — highest confidence.
    #
    #    A reference is specific enough to survive the broadcast check: an
    #    applicant-tracking system commonly replies from a no-reply address,
    #    and that is correspondence.
    for app in applications:
        for token in (app.reference, app.vacancy_id.split(":")[-1]):
            if token and len(token) >= 4 and token.lower() in text_low:
                return CorrelationResult(app, Correlation.REFERENCE)

    # 2. Sender domain against the employer domain on the vacancy record.
    #
    #    The domain is taken from the application where set, and otherwise
    #    derived from the vacancy URL. A named recruiter writing from the
    #    employer's own domain is the commonest shape of a real reply, and
    #    without this it reaches stage 3 — which needs the employer name in
    #    the subject, something a recruiter would never write.
    #    Also survives the broadcast check: `no-reply@mail.justice.gov.uk` is
    #    an employer's ATS, not a mass mailing. The DOMAIN carries the signal
    #    here, and it is the employer's own.
    domain = message.sender_domain
    if domain and not _sender_is_a_job_board(domain):
        for app in applications:
            emp_domain = (app.employer_domain or domain_of(app.url)).lower().strip()
            if emp_domain and (domain == emp_domain or domain.endswith("." + emp_domain)):
                return CorrelationResult(app, Correlation.SENDER_DOMAIN)

    # 3. An applicant-tracking system writing on the employer's behalf.
    #
    #    The sender domain is the ATS, never the employer, so stage 2 cannot
    #    match. The employer name is in the subject instead. Requires
    #    applied-language so that an advert from the same domain does not
    #    qualify — "thank you for applying at X" is not "apply now to X".
    if looks_like_an_acknowledgement(message):
        subject_norm = _norm(message.subject)
        body_head = _norm(message.body[:400])
        for app in applications:
            employer = _norm(app.employer)
            if not employer or len(employer) < 3:
                continue
            if employer in subject_norm or employer in body_head:
                return CorrelationResult(app, Correlation.ATS)

    # 4. Employer name AND job title in the subject. Both, not either —
    #    "Data Engineer" alone would match every open data application.
    #
    #    Only when the sender is plausibly the employer. A job board's advert
    #    naming an employer and a title is not correspondence from that
    #    employer, and this stage cannot tell the difference on subject alone.
    #    Broadcasts are excluded HERE rather than earlier. Stages 1 to 3 rest
    #    on a reference or the employer's own domain, both specific enough to
    #    be trusted from a no-reply address. Stage 3 rests only on words in a
    #    subject line, which every job advert also contains.
    if _sender_is_a_job_board(domain) or is_broadcast(message):
        return CorrelationResult(None, Correlation.NONE)

    subject = _norm(message.subject)
    for app in applications:
        employer, title = _norm(app.employer), _norm(app.title)
        if not (employer and title):
            continue
        if (employer in subject and title in subject
                and _sender_plausible(app, domain)):
            return CorrelationResult(app, Correlation.FUZZY)

    return CorrelationResult(None, Correlation.NONE)


# --- classification --------------------------------------------------------

def classify(message: Message) -> Classification:
    """Assign one of seven states. First rule to fire wins.

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

    # RULE 2 — OFFER. Before PROGRESS: an offer often invites a further call,
    # and reading that as another interview round would miss the outcome.
    offers = _matches(low, OFFER_MARKERS)
    if offers:
        return Classification(State.OFFER, 2, tuple(offers),
                              "an offer terminates the interview process")

    # RULE 3 — PROGRESS.
    progress = _matches(low, PROGRESS_MARKERS)
    if progress:
        return Classification(State.PROGRESS, 3, tuple(progress))

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
