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
    THREAD = "thread"              # a reply to a message already correlated
    REFERENCE = "reference"        # application reference or vacancy id
    SENDER_DOMAIN = "sender_domain"
    ATS = "ats"                    # applicant-tracking system, on behalf of the employer
    FUZZY = "fuzzy"                # employer + title in subject
    AMBIGUOUS = "ambiguous"        # several applications matched equally well
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
    # Workable's standard receipt, and the wording ATS vendors use when
    # confirming a submission rather than thanking an applicant. "Your
    # application was submitted successfully" is an acknowledgement and
    # matched nothing.
    "submitted successfully",
    "successfully submitted",
    "application was submitted",
    "application has been submitted",
    "copy of your application",
    "we received your application",
    # Board DISPATCH receipts. Reed and LinkedIn confirm they have forwarded
    # an application, in fixed wording, and a board's receipt is a small
    # closed set — unlike employer phrasing, which is unbounded.
    #
    # These were being decided semantically, and three near-identical Reed
    # receipts classified ACK, AMBIGUOUS and AMBIGUOUS because their
    # "recommended jobs" blocks shifted the scores by a few hundredths. A
    # fixed string should not be a coin flip.
    "we've sent your application",
    "we have sent your application",
    "your application was sent",
    "application sent",
    "your application is on its way",
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


def _decisive_matches(text: str, markers: Iterable[str]) -> list[str]:
    """Markers found in a sentence that ANNOUNCES rather than describes.

    Faculty's acknowledgement explained its own process:

        "We will then either invite you to an introductory video call, or let
         you know we will not be progressing your application on this
         occasion."

    `will not be progressing` is a DECLINE marker and it matched. The
    sentence is a description of a possible outcome, not a decision — and an
    acknowledgement classified DECLINE drafts a feedback letter for a
    decision nobody made.

    So a marker only counts where the sentence carrying it is not
    conditional. Checked per sentence rather than per message, because a real
    rejection may still explain its process further down.
    """
    found: list[str] = []
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]

    for marker in markers:
        for sentence in sentences:
            low = sentence.lower()
            if _phrase(low, marker) and not _is_conditional(sentence):
                found.append(marker)
                break

    return found


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
    # A subject advertising roles is a broadcast whoever sent it. A small
    # recruiter mails from `hello@`, not from `jobalerts-noreply@`, and the
    # sender says nothing — "Two fresh DS leads in Edinburgh" is marketing
    # from any address.
    if _looks_like_a_listing(message.subject):
        return True

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
    #: Defaults to now: `vanguard mail` reads a message from a file, where
    #: there is no Date header to parse.
    received: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    #: Threading headers. A reply to a message already correlated is almost
    #: certainly about the same application — the strongest signal available,
    #: and the one the system was discarding. Humans reply in threads; only
    #: machines send standalone acknowledgements.
    in_reply_to: str = ""
    references: str = ""
    #: `Reply-To`, which an ATS uses to carry a per-application identifier:
    #:
    #:     dc4+job+4e1f51283c7290391212f9eb552404910f3514d0+124894@app.bamboohr.com
    #:
    #: `124894` is the vacancy and the hex string the application. Every
    #: message about that application carries it, whatever the subject says —
    #: which makes it a stronger link than any phrase list, and one that does
    #: not depend on how a human worded their reply.
    reply_to: str = ""

    @property
    def thread_parents(self) -> tuple[str, ...]:
        """Every message id this one claims to answer, newest first."""
        ids: list[str] = []
        for header in (self.in_reply_to, self.references):
            ids.extend(re.findall(r"<[^>]+>", header or ""))
        seen: set[str] = set()
        out = []
        for message_id in reversed(ids):
            if message_id not in seen:
                seen.add(message_id)
                out.append(message_id)
        return tuple(out)

    @property
    def routing_tokens(self) -> tuple[str, ...]:
        """Identifiers an ATS embeds in `Reply-To`, and the sender address.

        Vendor-agnostic by shape rather than by pattern. Every ATS puts a
        per-application identifier in the reply address, and they differ:

            BambooHR    dc4+job+<40 hex>+124894@app.bamboohr.com
            Lever       <uuid>@hire.lever.co
            Greenhouse  no-reply+<24 hex>@greenhouse.io
            Ashby       no-reply+<24 mixed-case>@ashbyhq.com
            Workday     reply-2847193@myworkdayjobs.com

        Splitting on every separator shredded Lever's UUID into five short
        pieces, and a hex-only rule missed Ashby's mixed-case tokens
        entirely. So UUIDs are matched whole before anything is split, and
        the alphanumeric rule accepts any case at a higher length.

        The bar is what could plausibly identify one application. Common
        words are excluded outright: `careers`, `noreply` and `bewerbung`
        are long enough to pass a length test and would match everything.
        """
        found: set[str] = set()

        for header in (self.reply_to, self.sender):
            local = (header or "").split("@", 1)[0]
            if not local:
                continue

            # UUIDs first — splitting on `-` would destroy them.
            for uuid in re.findall(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                    r"[0-9a-f]{4}-[0-9a-f]{12}", local, re.I):
                found.add(uuid.lower())

            candidates = [local] + re.split(r"[+._\-]", local)
            for part in candidates:
                part = part.strip()
                if _is_routing_token(part):
                    found.add(part.lower())

        return tuple(sorted(found))

    @property
    def subject_root(self) -> str:
        """The subject with reply and forward prefixes stripped.

        A human replying often keeps the subject and nothing else the
        correlator can use.
        """
        subject = (self.subject or "").strip()
        while True:
            stripped = re.sub(r"^\s*(re|fw|fwd|aw|sv)\s*(\[\d+\])?\s*:\s*",
                              "", subject, flags=re.I)
            if stripped == subject:
                return subject.strip()
            subject = stripped

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
    """Which application a message belongs to, or why that is not decidable.

    `candidates` is populated when several applications matched equally well
    — two live applications at the same employer, and a reply carrying nothing
    to tell them apart. Picking the first would attach an interview
    invitation, or a rejection, to the wrong vacancy.
    """

    application: Application | None
    method: Correlation
    candidates: tuple[Application, ...] = ()

    @property
    def correlated(self) -> bool:
        return self.application is not None

    @property
    def ambiguous(self) -> bool:
        return self.method is Correlation.AMBIGUOUS

    def describe(self) -> str:
        if self.ambiguous:
            names = ", ".join(a.vacancy_id for a in self.candidates)
            return f"matched {len(self.candidates)} applications: {names}"
        if self.correlated:
            return f"{self.application.vacancy_id} via {self.method.value}"
        return "no application matched"
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
    # Added 20 Aug 2026. A Beatport reply reading "Thank you for your interest
    # in Beatport" matched nothing: the ATS stage requires an applied-phrase,
    # and this list only knew "applying" and "application". Employers write
    # "interest" as often, and it is the standard opener for a rejection.
    "thank you for your interest", "thanks for your interest",
    "for your interest in", "your recent application",
    "further to your application", "following your application",
    "with regard to your application", "about your application",
    "status of your application", "update on your application",
    "we reviewed your application", "reviewed your application",
    "considered your application", "after careful consideration",
)


#: A subject carrying an applied-phrase ALONGSIDE listing language is a
#: newsletter with an update tacked on, not an acknowledgement.
#:
#: Observed 20 Aug 2026: "Two fresh DS leads in Edinburgh + application
#: update" was exempted from the broadcast filter by "application update",
#: correlated on the sender domain, classified PROGRESS, and reached round
#: five of an interview process that never existed.
_LISTING_MARKERS = (
    " leads", "fresh ", "new roles", "new jobs", "opportunities",
    "vacancies", "roles in", "jobs in", "hiring now", "this week",
    "newsletter", "digest", "round-up", "roundup", "top picks",
    "recommended for you", "jobs for you",
)


#: Words long enough to pass a length test that identify nothing. Without
#: these, `careers` and `bewerbung` would correlate every message an employer
#: ever sent.
_NOT_A_TOKEN = frozenset({
    "careers", "carriere", "recruiting", "recruitment", "recruiter",
    "noreply", "no-reply", "donotreply", "notification", "notifications",
    "bewerbung", "application", "applications", "candidate", "candidates",
    "jobalerts", "jobalert", "talent", "hiring", "response", "responses",
    "postmaster", "mailer-daemon", "customerservice", "support",
})


def _is_routing_token(part: str) -> bool:
    """Could this identify one application?

    Judged on shape, so a vendor Vanguard has never seen still works.
    """
    if not part or part.lower() in _NOT_A_TOKEN:
        return False

    if part.isdigit():
        return len(part) >= 5

    if re.fullmatch(r"[0-9a-f]+", part, re.I):
        return len(part) >= 16

    # Mixed case or mixed alphanumeric. A higher bar, because unlike hex
    # there is no structure to lean on — and it must contain a digit, or
    # long ordinary words would qualify.
    if re.fullmatch(r"[0-9a-z]+", part, re.I):
        return len(part) >= 20 and any(c.isdigit() for c in part)

    return False


def _looks_like_a_listing(subject: str) -> bool:
    """Is this subject advertising roles?

    Markers catch the obvious wording. The SHAPE catches the rest: a subject
    naming two or more roles — "Technical Lead ML at Bjak + Lead Data
    Scientist at Ki" — is a digest whatever words it uses, and no
    acknowledgement mentions two employers.
    """
    low = (subject or "").lower()
    if any(marker in low for marker in _LISTING_MARKERS):
        return True

    # Two or more " at <employer>" fragments, or a "+" joining two roles.
    if low.count(" at ") >= 2:
        return True
    if "+" in low and low.count(" at ") >= 1:
        return True
    return False


def looks_like_an_acknowledgement(message: Message) -> bool:
    """The subject confirms an application already made.

    Distinguishes an ATS acknowledgement from a job board advert, both of
    which are third parties naming an employer.

    A subject doing BOTH — advertising roles and mentioning an application —
    is a newsletter. The exemption exists for genuine acknowledgements, and a
    marketing mail that happens to contain "application update" is not one.
    """
    subject = (message.subject or "").lower()
    if not any(phrase in subject for phrase in _APPLIED_PHRASES):
        return False
    return not _looks_like_a_listing(subject)


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


def _one_of(matches: list[Application], method: Correlation
            ) -> CorrelationResult | None:
    """Resolve a stage's matches into a result, or None to try the next stage.

    One match decides. Several is AMBIGUOUS and is surfaced rather than
    guessed: two live applications at the same employer, and a reply with
    nothing to tell them apart, would otherwise attach an interview
    invitation — or a rejection — to the wrong vacancy.

    Identical vacancy ids are collapsed first, so the same application
    appearing twice is not mistaken for two.
    """
    unique = {app.vacancy_id: app for app in matches}
    if not unique:
        return None
    if len(unique) == 1:
        return CorrelationResult(next(iter(unique.values())), method)
    return CorrelationResult(None, Correlation.AMBIGUOUS,
                             tuple(unique.values()))


def _employer_in(employer: str, text: str) -> bool:
    """Is this employer named here, as a word?

    A substring test is wrong for short names — `ki` appears inside `working`,
    `skills` and `taking`. A word-boundary match lets a two-character company
    be found without matching every message that mentions a skill.
    """
    if not employer or not text:
        return False
    if len(employer) >= 5:
        return employer in text
    return re.search(rf"(?<![a-z0-9]){re.escape(employer)}(?![a-z0-9])",
                     text) is not None


def _domain_resembles_employer(domain: str, employer: str) -> bool:
    """Does this sender domain plausibly belong to this employer?

    Compares distinctive tokens, so `sanderson.com` matches "Sanderson" and
    `mail.justice.gov.uk` matches "Ministry of Justice". Words too common to
    identify anyone are excluded, so `services.com` does not match every
    employer with "Services" in its name.

    A token must be at least four characters. Shorter ones collide too often
    — "AI" or "IBM" would match domains belonging to neither.
    """
    if not domain or not employer:
        return False

    tokens = {t for t in _norm(employer).split()
              if len(t) >= 4 and t not in _COMMON_EMPLOYER_WORDS}

    # A short name has no four-character token and was excluded entirely.
    # Fall back to the whole name, matched at a boundary in the host, so
    # `ki.com` matches Ki without `ki` matching `wiki.com`.
    if not tokens:
        whole = _norm(employer).replace(" ", "")
        if len(whole) < 2 or whole in _COMMON_EMPLOYER_WORDS:
            return False
        host = (domain or "").lower()
        return any(part == whole for part in re.split(r"[.\-]", host))

    if not tokens:
        return False

    host = domain.lower().rsplit(".", 2)[0].replace("-", "").replace(".", "")
    return any(token in host for token in tokens)


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
    message: Message, applications: Sequence[Application], *,
    known_threads: dict[str, str] | None = None,
) -> CorrelationResult:
    """Match a message to an open application. Runs BEFORE classification.

    Three stages, in order of confidence. Correlation failure is not a
    classification outcome — an uncorrelated message is queued for review, not
    guessed at.
    """
    pending: CorrelationResult | None = None

    # 0a. A routing token an ATS put in `Reply-To`.
    #
    # The strongest link available and the one the header states outright:
    # `job+<hash>+124894@app.bamboohr.com` identifies an application
    # exactly, whatever the subject says. Everything below is inference from
    # wording; this is not.
    if known_threads:
        by_id = {app.vacancy_id: app for app in applications}
        for token in message.routing_tokens:
            vacancy_id = known_threads.get(f"token:{token}")
            if vacancy_id and vacancy_id in by_id:
                return CorrelationResult(by_id[vacancy_id], Correlation.THREAD)

    # 0b. A reply to a message already correlated.
    #
    # The strongest signal available, and the one the system was discarding.
    # Humans reply in threads; only machines send standalone acknowledgements,
    # so every later stage was tuned for machines and a human's "Re: next
    # steps" from a personal address matched nothing.
    #
    # `known_threads` maps a seen message id — or a seen subject root — to the
    # vacancy it correlated to.
    if known_threads:
        by_id = {app.vacancy_id: app for app in applications}
        for parent in message.thread_parents:
            vacancy_id = known_threads.get(parent)
            if vacancy_id and vacancy_id in by_id:
                return CorrelationResult(by_id[vacancy_id], Correlation.THREAD)

        root = _norm(message.subject_root)
        if root and len(root) > 12:
            vacancy_id = known_threads.get(f"subject:{root}")
            if vacancy_id and vacancy_id in by_id:
                return CorrelationResult(by_id[vacancy_id], Correlation.THREAD)

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
        by_domain = [
            app for app in applications
            if (emp := (app.employer_domain or domain_of(app.url)).lower().strip())
            and (domain == emp or domain.endswith("." + emp))
        ]
        decided = _one_of(by_domain, Correlation.SENDER_DOMAIN)
        if decided is not None and not decided.ambiguous:
            return decided
        pending = decided or pending

        # No configured domain — which is the norm, because a vacancy sourced
        # from a job board yields none. `domain_of()` correctly returns empty
        # for reed.co.uk: Reed is not the employer.
        #
        # So compare the sender domain against the employer NAME. Without
        # this, `hr@sanderson.com` did not correlate to an application at
        # Sanderson, and since most vacancies come from boards, most genuine
        # employer replies failed to correlate at all.
        by_name = [app for app in applications
                   if _domain_resembles_employer(domain, app.employer)]
        decided = _one_of(by_name, Correlation.SENDER_DOMAIN)
        if decided is not None and not decided.ambiguous:
            return decided
        pending = decided or pending

    # 3. An applicant-tracking system writing on the employer's behalf.
    #
    #    The sender domain is the ATS, never the employer, so stage 2 cannot
    #    match. The employer name is in the subject instead. Requires
    #    applied-language so that an advert from the same domain does not
    #    qualify — "thank you for applying at X" is not "apply now to X".
    if looks_like_an_acknowledgement(message):
        subject_norm = _norm(message.subject)
        body_head = _norm(message.body[:400])
        named = [
            app for app in applications
            # Two characters is a real company name. The floor existed to
            # stop noise matching, and a WORD-BOUNDARY match does that job
            # without excluding anyone.
            if (employer := _norm(app.employer)) and len(employer) >= 2
            and (_employer_in(employer, subject_norm)
                 or _employer_in(employer, body_head))
        ]
        decided = _one_of(named, Correlation.ATS)
        if decided is not None and not decided.ambiguous:
            return decided
        pending = decided or pending

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
    matched = [
        app for app in applications
        if (pair := (_norm(app.employer), _norm(app.title))) and all(pair)
        and pair[0] in subject and pair[1] in subject
        and _sender_plausible(app, domain)
    ]
    # Where one title contains another — "Machine Learning Engineer" inside
    # "MLE- Machine Learning Engineer" — both match, and the longer is the
    # more specific. Preferring it resolves the pair rather than reporting an
    # ambiguity the subject actually settles.
    if len(matched) > 1:
        longest = max(len(_norm(app.title)) for app in matched)
        specific = [app for app in matched if len(_norm(app.title)) == longest]
        if len(specific) == 1:
            matched = specific

    decided = _one_of(matched, Correlation.FUZZY)
    if decided is not None and not decided.ambiguous:
        return decided
    pending = decided or pending

    # A stage that matched several is reported as ambiguous only if no later,
    # more specific stage could decide it. The sender domain identifies the
    # employer; the subject may still identify which vacancy.
    if pending is not None:
        return pending

    return CorrelationResult(None, Correlation.NONE)


# --- classification --------------------------------------------------------

#: Reference sentences per state, for semantic classification.
#:
#: A phrase list is a treadmill: every employer's wording is a new defect, and
#: "the team has decided to proceed with other candidates" — unmistakably a
#: rejection — matched nothing in a list of five markers.
#:
#: These are not markers. They are EXAMPLES of what each state sounds like,
#: compared by meaning rather than by substring, so a wording nobody
#: anticipated still lands in the right place.
REFERENCES: dict[str, tuple[str, ...]] = {
    "DECLINE": (
        "Unfortunately you have not been successful on this occasion.",
        "The team has decided to proceed with other candidates.",
        "We will not be taking your application any further.",
        "We have chosen to move forward with applicants whose experience is a"
        " closer match.",
        "On this occasion we are unable to offer you an interview.",
        "On this occasion we are unable to take your application further.",
        "We regret to inform you that your application was unsuccessful.",
        "After reviewing your application we have decided not to progress it.",
        "We have decided to move forward with other candidates at this time.",
        "After careful consideration we are moving forward with other applicants.",
        "We are not able to move forward in the recruiting process with you.",
        "We are unable to progress your application at this stage.",
        "The position has been filled by another candidate.",
    ),
    "PROGRESS": (
        "We would like to invite you to an interview.",
        "We would like to arrange a call to discuss the role further.",
        "Please complete the attached technical assessment.",
        "The team would like to meet you for the next stage.",
        "Are you available for a conversation this week?",
        "We would like to move you forward to the next round.",
        "Please book a time using the link below to speak with the team.",
    ),
    "OFFER": (
        "We are pleased to offer you the position.",
        "We would like to offer you the role and have attached the details.",
        "Congratulations, the team would like to welcome you aboard.",
        "Please find enclosed your formal offer of employment.",
    ),
    "ACK": (
        "Thank you for applying. We have received your application.",
        "This is confirmation that your application has been submitted.",
        "We have received your details and will be in touch.",
        "Your application is now with the hiring team for review.",
        "You have successfully submitted your application for this position.",
        "Someone will review your qualifications shortly.",
        "Your application was submitted successfully.",
        "Here is a copy of your application data for safekeeping.",
    ),
    "QUERY": (
        "Could you confirm your notice period and salary expectations?",
        "We need a few more details before we can proceed.",
        "Please send us a copy of your right to work documentation.",
    ),
    "ADMIN": (
        "Your interview has been rescheduled to Thursday.",
        "Here is the joining link for your call.",
        "Please use the portal below to upload your documents.",
    ),
}

#: How close a message must sit to a reference before the meaning decides.
#:
#: **AUTHORED, not measured.** Below this the message is left AMBIGUOUS, which
#: asks the operator to read it — the right failure. Above it, a state is
#: assigned on similarity alone, and a wrong DECLINE drafts a feedback letter
#: for a rejection nobody sent.
SEMANTIC_THRESHOLD = 0.60

#: How far ahead of the next state a match must be before it decides.
#:
#: Sentence embeddings measure TOPIC far more than polarity. "We've sent your
#: application to Sanderson" and "We will not be taking your application any
#: further" are both about an application, share structure, and score close
#: together. A raw threshold cannot separate them; a MARGIN can — if two
#: states score within this of each other, the message is not clearly either.
#:
#: Set from MEASUREMENT on 22 Aug 2026, against the operator's own mail with
#: MiniLM. Both numbers were judgement before that, and judgement produced
#: seven misclassifications out of twenty-six.
#:
#:   Sanderson receipt       ACK 0.64, DECLINE 0.59   gap 0.05
#:   Faculty confirmation    ACK 0.63, OFFER   0.56   gap 0.07
#:   Pflegia confirmation    ACK 1.00, OFFER   0.65   gap 0.35
#:   Pflegia rejection   DECLINE 1.00, ACK     0.80   gap 0.20
#:   Faculty rejection   DECLINE 1.00, ACK     0.67   gap 0.33
#:
#: A threshold of 0.72 rejected the three acknowledgements that scored
#: correctly but modestly; a margin of 0.08 rejected two more. 0.60 and 0.04
#: admit all five and still leave the near-ties that caused the original
#: defect below the bar.
#:
#: **Fitted to five examples.** Revisit as more classified mail accumulates —
#: `vanguard responses <ID> --explain` prints the numbers.
SEMANTIC_MARGIN = 0.04


def semantic_scores(message: Message, embedder) -> dict[str, tuple[float, str]]:
    """Best score per state, with the line that produced it.

    Exposed so the thresholds can be set from MEASUREMENT rather than
    judgement. Both were authored, and seven of twenty-six real messages were
    misclassified before anyone looked at the numbers.
    """
    best: dict[str, tuple[float, str]] = {}
    if embedder is None:
        return best

    for line in _decision_sentences(message):
        for state, examples in REFERENCES.items():
            for example in examples:
                try:
                    score = embedder.similarity(line, example)
                except Exception:
                    return {}
                if score > best.get(state, (0.0, ""))[0]:
                    best[state] = (score, line)
    return best


def classify_semantically(message: Message, embedder,
                          threshold: float = SEMANTIC_THRESHOLD
                          ) -> Classification | None:
    """Classify by meaning, where no marker fired.

    Compares the message's decision-bearing sentences against reference
    examples of each state. Returns None when nothing is close enough —
    AMBIGUOUS is the correct answer to a message that says nothing clear.

    Runs on the LOCAL embedder. Mail is at least as personal as the CV, and
    the ruling that keeps embeddings off an API applies here with more force.
    """
    if embedder is None:
        return None

    # Best score PER STATE, not one best overall.
    #
    # A courtesy opener beats a decision on raw similarity: "Thank you for
    # your interest in the position" matches an ACK reference closely because
    # openers are formulaic, while "we are not able to move forward in the
    # recruiting process with you" matches DECLINE less closely because it is
    # oddly worded. Taking the single highest score classified Pflegia's
    # rejection as an acknowledgement.
    best: dict[str, tuple[float, str]] = {}

    for line in _decision_sentences(message):
        for state, examples in REFERENCES.items():
            for example in examples:
                try:
                    score = embedder.similarity(line, example)
                except Exception:
                    return None
                if score > best.get(state, (0.0, ""))[0]:
                    best[state] = (score, line)

    # A DECISIVE state overrides a provisional one only when it is CLEARLY
    # confident, not merely above the same bar.
    #
    # Written as "whenever it clears the threshold", this turned
    # acknowledgements into offers: a warm welcome scoring 0.56 against "we
    # are pleased to offer you the position" beat the same message scoring
    # 0.85 against an acknowledgement. Overriding a better match needs a
    # better reason than being in a more important category.
    #
    # OFFER carries its own bar. Telling someone they have a job they do not
    # have is the worst output this classifier can produce.
    override = threshold + 0.10   # 0.70 with the measured threshold
    bars = {"DECLINE": override, "PROGRESS": override, "QUERY": override}

    decisive = {state: value for state, value in best.items()
                if state in bars and value[0] >= bars[state]}

    pool = decisive or {state: value for state, value in best.items()
                        if value[0] >= threshold}

    # OFFER is never reached by meaning alone.
    #
    # An offer is the one outcome employers state unambiguously — "pleased to
    # offer", "formal offer", "welcome to the team" — and the marker list
    # covers it. A false OFFER tells someone they have a job they do not
    # have, which could stop them applying elsewhere. An offer worded so
    # unusually that no marker fires reads as PROGRESS or AMBIGUOUS instead,
    # and the operator opens it. That failure is recoverable; the other is
    # not.
    pool.pop("OFFER", None)

    if not pool:
        return None

    state = max(pool, key=lambda name: pool[name][0])
    score, line = pool[state]

    # A near-tie is not a decision.
    #
    # Embeddings rank topic above polarity, so the runner-up matters as much
    # as the winner. Where two states score within SEMANTIC_MARGIN, the
    # message is not clearly either and AMBIGUOUS is the honest answer — it
    # asks the operator to read it, which costs a minute. A wrong DECLINE
    # drafts a feedback letter for a rejection nobody sent.
    rivals = sorted((value[0] for name, value in best.items() if name != state),
                    reverse=True)
    if rivals and (score - rivals[0]) < SEMANTIC_MARGIN:
        return None

    note = (f"semantic match at {score:.2f}"
            + (f", next {rivals[0]:.2f}" if rivals else "")
            + " — no marker fired")

    return Classification(State(state), 6, (line[:90],), note)


#: Words that begin a clause carrying the decision, where the rest of the
#: sentence softens it. Observed 21 Aug 2026: WPP Media wrote
#:
#:   "While the team has decided to proceed with other candidates, we want to
#:    assure you that your skills, dedication, and the impact you are making
#:    are deeply valued here at WPP Media."
#:
#: The rejection is a subordinate clause and the rest is reassurance. Scored
#: whole it reached 0.80; the clause alone reaches 0.96. Diluting a decision
#: with the comfort wrapped around it is exactly how a rejection reads as
#: nothing in particular.
#: Phrasing that describes what MIGHT happen rather than what has. Faculty's
#: acknowledgement explained its own process:
#:
#:   "We will then either invite you to an introductory video call, or let you
#:    know we will not be progressing your application on this occasion."
#:
#: The second half reads as a rejection and is a description of one. An
#: acknowledgement classified DECLINE drafts a feedback letter for a decision
#: nobody made — the worst failure this classifier has.
_CONDITIONAL = (
    "either", " or let you know", "will then", "we will then", "we'll then",
    "if we ", "if your application", "should your application",
    "should we ", "in the event",
)


def _is_conditional(line: str) -> bool:
    """Does this describe a possible outcome rather than announce one?"""
    low = (line or "").lower()
    return any(marker in low for marker in _CONDITIONAL)


_CLAUSE_OPENERS = (
    "while", "although", "though", "however", "unfortunately", "regrettably",
    "sadly", "whilst", "but", "that said", "having said",
)


def _decision_sentences(message: Message) -> list[str]:
    """Sentences and clauses worth classifying on.

    A signature block, a legal footer and an unsubscribe line carry no
    decision and drag every similarity toward nothing.

    Long sentences are ALSO offered as clauses. A rejection is routinely
    written as a subordinate clause with reassurance attached, and scoring
    the sentence whole averages the decision away.
    """
    text = f"{message.subject}\n{message.body}"
    lines: list[str] = []

    for raw in re.split(r"(?<=[.!?])\s+|\n+", text):
        line = raw.strip()
        if len(line) < 20 or len(line) > 400:
            continue

        low = line.lower()
        if any(marker in low for marker in (
                "unsubscribe", "privacy policy", "confidential",
                "registered in england", "this email and any attachments",
                "do not reply", "view this email")):
            continue

        # A sentence explaining what MIGHT happen is not a decision, and
        # neither is any clause taken out of it.
        if _is_conditional(line):
            continue

        lines.append(line[:300])

        # And its clauses, where the sentence is long enough for a decision
        # to hide inside one.
        if len(line) > 90:
            lines.extend(c for c in _clauses_of(line) if not _is_conditional(c))

    # Deduplicate while keeping order — a short sentence is its own clause.
    seen: set[str] = set()
    unique = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique[:60]


def _clauses_of(sentence: str) -> list[str]:
    """Clauses that could carry a decision on their own.

    Split on commas and semicolons. A fragment is kept only if it opens with
    a word that introduces a decision, or is long enough to stand alone —
    "we want to assure you that your skills" is neither.
    """
    out: list[str] = []
    parts = [p.strip() for p in re.split(r"[;,]\s+", sentence) if p.strip()]

    for index, part in enumerate(parts):
        if len(part) < 20:
            continue
        first = part.split()[0].lower().strip(".,") if part.split() else ""
        if index == 0 or first in _CLAUSE_OPENERS or len(part) >= 40:
            out.append(part[:300])

    return out


def classify(message: Message, embedder=None) -> Classification:
    """Assign one of seven states. First rule to fire wins.

    DECLINE is checked before PROGRESS. A decline phrase always wins over a
    progress phrase in the same message.
    """
    low = message.text.lower()

    # RULE 1 — DECLINE. First, and it outranks everything.
    declines = _decisive_matches(message.text, DECLINE_MARKERS)
    if declines:
        progress = _decisive_matches(message.text, PROGRESS_MARKERS)
        note = (
            "decline outranks progress phrasing in the same message"
            if progress else ""
        )
        return Classification(State.DECLINE, 1, tuple(declines), note)

    # RULE 2 — OFFER. Before PROGRESS: an offer often invites a further call,
    # and reading that as another interview round would miss the outcome.
    offers = _decisive_matches(message.text, OFFER_MARKERS)
    if offers:
        return Classification(State.OFFER, 2, tuple(offers),
                              "an offer terminates the interview process")

    # RULE 3 — PROGRESS.
    progress = _decisive_matches(message.text, PROGRESS_MARKERS)
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
    # RULE 5 — meaning, where no marker fired.
    #
    # A phrase list is a treadmill. "The team has decided to proceed with
    # other candidates" is unmistakably a rejection and matched none of the
    # five DECLINE markers. Rules stay first because they are deterministic
    # and explainable; this catches the wording nobody anticipated.
    semantic = classify_semantically(message, embedder)
    if semantic is not None:
        return semantic

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
