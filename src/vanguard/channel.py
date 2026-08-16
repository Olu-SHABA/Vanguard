"""
Application channel — Phase 2 C.

A PENDING record says a vacancy is worth applying to. It says nothing about
*how*, and until now neither did the system: the operator was told a role was
a good match and left to work out whether they had an account, whether the
board would want a built profile, and whether the link went to the employer's
own system.

## Brink of autonomous, not autonomous

The system establishes what kind of application this is, what is needed, and
whether the operator is already registered. **The operator does the clicking.**

Automated form-filling across arbitrary employer ATS systems is out of scope
and stays there. Different templates, labels, anchors and frameworks make it
unreliable, and unreliable is unacceptable when the artefact is a job
application. A form filled wrongly on the operator's behalf is worse than no
help at all.

## Registration is asserted, never detected

Nothing logs in to check. The system asks once per board or portal and
remembers.

Detection would need credentials for dozens of employer portals — a single
file that, if leaked, opens every account. Repeated automated logins across
many portals is also the pattern security systems flag as credential
stuffing, and most ATS terms prohibit automated access.

The operator knows whether they are registered. It is one question, once.

## Two scopes

Boards are a small fixed set. Employer portals are unbounded and grow with
every application, which is why they are keyed by hostname rather than
enumerated.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Sequence

__all__ = [
    "Channel",
    "ChannelGuess",
    "Registration",
    "RegistrationStore",
    "REGISTRATION_SCHEMA",
    "classify_channel",
    "host_of",
]

REGISTRATION_SCHEMA = """
-- Whether the operator holds an account, and whether a profile is built.
-- Asserted by the operator, never detected: nothing logs in to check.
CREATE TABLE IF NOT EXISTS registrations (
  scope         TEXT NOT NULL,          -- 'board' | 'employer'
  key           TEXT NOT NULL,          -- board id, or ATS hostname
  registered    INTEGER NOT NULL DEFAULT 0,
  profile_built INTEGER NOT NULL DEFAULT 0,
  url           TEXT,
  note          TEXT,
  noted_at      TIMESTAMP NOT NULL,
  PRIMARY KEY (scope, key)
);

-- Answers to questions that recur across applications. A recall aid, never
-- a form-filler: the operator still types them into the employer's form.
CREATE TABLE IF NOT EXISTS answers (
  question_key TEXT PRIMARY KEY,
  question     TEXT NOT NULL,
  answer       TEXT NOT NULL,
  updated_at   TIMESTAMP NOT NULL
);
"""


class Channel(str, Enum):
    """How a vacancy is applied to."""

    BOARD_DIRECT = "BOARD_DIRECT"      # apply on the board, upload a CV
    BOARD_PROFILE = "BOARD_PROFILE"    # board applies from a built profile
    EMPLOYER_ATS = "EMPLOYER_ATS"      # redirects to the employer's own system
    UNKNOWN = "UNKNOWN"                # not classifiable; operator decides once

    @property
    def needs_account(self) -> bool:
        return self is not Channel.UNKNOWN

    @property
    def needs_profile(self) -> bool:
        return self is Channel.BOARD_PROFILE


#: Boards whose application flow is known. `profile` marks a board that
#: applies from a built profile rather than an uploaded CV.
_KNOWN_BOARDS: dict[str, tuple[Channel, str]] = {
    "reed.co.uk": (Channel.BOARD_DIRECT, "https://www.reed.co.uk/account/signin"),
    "adzuna.co.uk": (Channel.EMPLOYER_ATS, ""),      # aggregator; always redirects
    "indeed.com": (Channel.BOARD_PROFILE, "https://secure.indeed.com/account/login"),
    "linkedin.com": (Channel.BOARD_PROFILE,
                     "https://www.linkedin.com/login"),
    "totaljobs.com": (Channel.BOARD_DIRECT, "https://www.totaljobs.com/login"),
    "cwjobs.co.uk": (Channel.BOARD_DIRECT, "https://www.cwjobs.co.uk/login"),
    "cv-library.co.uk": (Channel.BOARD_DIRECT, "https://www.cv-library.co.uk/login"),
    "civilservicejobs.service.gov.uk": (
        Channel.BOARD_PROFILE,
        "https://www.civilservicejobs.service.gov.uk/csr/index.cgi"),
    "jobs.nhs.uk": (Channel.BOARD_PROFILE, "https://www.jobs.nhs.uk/candidate"),
    "findajob.dwp.gov.uk": (Channel.BOARD_DIRECT,
                            "https://findajob.dwp.gov.uk/sign-in"),
    "glassdoor.com": (Channel.EMPLOYER_ATS, ""),
    "otta.com": (Channel.BOARD_PROFILE, "https://app.otta.com"),
}

#: Hosts that are applicant-tracking systems. A vacancy URL on one of these
#: means the employer runs its own portal and will want its own account.
_ATS_HOSTS = (
    "greenhouse.io", "lever.co", "workday.com", "myworkdayjobs.com",
    "ashbyhq.com", "bamboohr.com", "workable.com", "smartrecruiters.com",
    "teamtailor.com", "icims.com", "taleo.net", "successfactors.com",
    "jobvite.com", "breezy.hr", "recruitee.com", "pinpointhq.com",
    "applytojob.com", "personio.de", "factorialhr.com", "eploy.co.uk",
    "oraclecloud.com", "brassring.com", "avature.net", "jobtrain.co.uk",
    "networxrecruitment.com", "tribepad.com",
)

#: Advert phrasing that says the application happens elsewhere, whatever the
#: URL suggests.
_REDIRECT_MARKERS = (
    "apply on the company", "apply via our website", "apply on our website",
    "apply directly", "visit our careers", "our careers site",
    "our careers page", "applications through our", "apply at",
    "external application", "you will be redirected",
)


def host_of(url: str) -> str:
    """The hostname from a URL, without `www.`. Empty when there is none."""
    match = re.match(r"^[a-z][a-z0-9+.-]*://([^/:?#]+)", (url or "").strip(), re.I)
    if not match:
        return ""
    return match.group(1).lower().removeprefix("www.")


@dataclass
class ChannelGuess:
    """What kind of application this is, and why.

    The reason is reported. A classification without one cannot be argued
    with, and the operator is the one who has to act on it.
    """

    channel: Channel
    reason: str
    host: str = ""
    registration_url: str = ""

    @property
    def certain(self) -> bool:
        return self.channel is not Channel.UNKNOWN


def classify_channel(url: str, advert: str = "", *,
                     board_id: str = "") -> ChannelGuess:
    """Work out how this vacancy is applied to.

    The URL decides where it can. Advert phrasing overrides a board URL when
    it says the application happens elsewhere — a Reed listing that says
    "apply on the company website" is an EMPLOYER_ATS application whatever
    the link looks like.
    """
    host = host_of(url)

    if host:
        for ats in _ATS_HOSTS:
            if host == ats or host.endswith("." + ats):
                return ChannelGuess(
                    Channel.EMPLOYER_ATS,
                    f"{host} is an applicant-tracking system",
                    host=host)

    low = (advert or "").lower()
    redirect = next((m for m in _REDIRECT_MARKERS if m in low), "")

    if host:
        for known, (channel, sign_in) in _KNOWN_BOARDS.items():
            if host == known or host.endswith("." + known):
                if redirect and channel is not Channel.EMPLOYER_ATS:
                    return ChannelGuess(
                        Channel.EMPLOYER_ATS,
                        f"listed on {known}, but the advert says "
                        f"\u201c{redirect}\u201d",
                        host=host)
                return ChannelGuess(
                    channel, f"{known} is a known board", host=known,
                    registration_url=sign_in)

        # An unknown host that is not a board is most likely the employer's
        # own careers site.
        return ChannelGuess(
            Channel.EMPLOYER_ATS,
            f"{host} is not a known board — likely the employer's own site",
            host=host)

    if redirect:
        return ChannelGuess(
            Channel.EMPLOYER_ATS,
            f"no URL, but the advert says \u201c{redirect}\u201d")

    if board_id:
        return ChannelGuess(
            Channel.UNKNOWN,
            f"no URL recorded; classify once for {board_id}")

    return ChannelGuess(Channel.UNKNOWN, "no URL and no board recorded")


# ---------------------------------------------------------------------------
# Registration state
# ---------------------------------------------------------------------------

@dataclass
class Registration:
    scope: str
    key: str
    registered: bool = False
    profile_built: bool = False
    url: str = ""
    note: str = ""
    noted_at: str = ""

    def describe(self) -> str:
        if not self.registered:
            return "not registered"
        return "registered, profile built" if self.profile_built else "registered"


@dataclass
class RegistrationStore:
    """Where the operator has accounts. Asserted, never detected."""

    path: str

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.executescript(REGISTRATION_SCHEMA)
        return conn

    def get(self, scope: str, key: str) -> Registration | None:
        if not key:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM registrations WHERE scope = ? AND key = ?",
                (scope, key.lower()),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return Registration(
            scope=row["scope"], key=row["key"],
            registered=bool(row["registered"]),
            profile_built=bool(row["profile_built"]),
            url=row["url"] or "", note=row["note"] or "",
            noted_at=row["noted_at"],
        )

    def set(self, scope: str, key: str, *, registered: bool = True,
            profile_built: bool = False, url: str = "",
            note: str = "") -> Registration:
        record = Registration(
            scope=scope, key=key.lower(), registered=registered,
            profile_built=profile_built, url=url, note=note,
            noted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO registrations
                   (scope, key, registered, profile_built, url, note, noted_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(scope, key) DO UPDATE SET
                     registered = excluded.registered,
                     profile_built = excluded.profile_built,
                     url = COALESCE(NULLIF(excluded.url, ''), registrations.url),
                     note = excluded.note,
                     noted_at = excluded.noted_at""",
                (record.scope, record.key, int(record.registered),
                 int(record.profile_built), record.url, record.note,
                 record.noted_at),
            )
            conn.commit()
        finally:
            conn.close()
        return record

    def all(self) -> list[Registration]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM registrations ORDER BY scope, key").fetchall()
        finally:
            conn.close()
        return [
            Registration(
                scope=r["scope"], key=r["key"], registered=bool(r["registered"]),
                profile_built=bool(r["profile_built"]), url=r["url"] or "",
                note=r["note"] or "", noted_at=r["noted_at"])
            for r in rows
        ]

    # -- recurring answers -------------------------------------------------

    def remember_answer(self, question: str, answer: str) -> None:
        """Record an answer to a question that recurs across applications.

        A recall aid. The operator still types it into the employer's form —
        nothing is filled in on their behalf.
        """
        key = _normalise_question(question)
        if not key or not answer.strip():
            return
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO answers (question_key, question, answer, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(question_key) DO UPDATE SET
                     answer = excluded.answer,
                     question = excluded.question,
                     updated_at = excluded.updated_at""",
                (key, question.strip(), answer.strip(),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            conn.commit()
        finally:
            conn.close()

    def answers(self) -> list[tuple[str, str]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT question, answer FROM answers ORDER BY question"
            ).fetchall()
        finally:
            conn.close()
        return [(r["question"], r["answer"]) for r in rows]

    def find_answer(self, question: str) -> str:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT answer FROM answers WHERE question_key = ?",
                (_normalise_question(question),),
            ).fetchone()
        finally:
            conn.close()
        return row["answer"] if row else ""


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _normalise_question(question: str) -> str:
    """A key that survives rewording. "What is your notice period?" and
    "Notice period" should not be two entries."""
    text = _WS.sub(" ", _PUNCT.sub(" ", (question or "").lower())).strip()
    filler = {"what", "is", "your", "the", "please", "state", "confirm",
              "do", "you", "have", "a", "an", "are", "how", "much", "many",
              "would", "could", "of", "for", "to", "in", "on", "and"}
    words = [w for w in text.split() if w not in filler]
    return " ".join(words[:6])
