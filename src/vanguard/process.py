"""
Interview process tracking — Route 5, multi-round.

The existing model handles one message, one classification. An interview
process is several rounds over weeks: a first-stage screen, a technical
exercise, a panel, then an outcome.

Without a record spanning them, each message is classified in isolation and
nothing knows that the fourth is the third round of the same process — nor
when to stop monitoring.

## What a process is

Opened by the first PROGRESS correlated to a dispatched application. Every
subsequent correlated message is attached to it. It ends only on a terminal
state:

    OFFER      the process succeeded
    DECLINE    the process ended unsuccessfully
    WITHDRAWN  the operator closed it

**Nothing else terminates it.** Not silence, not an ADMIN message, not an
AMBIGUOUS one. Dormancy is a derived state and never a conclusion — employers
go quiet between rounds and return.

## Rounds

A round is opened by a PROGRESS message. ADMIN and QUERY messages attach to
the current round rather than opening a new one: scheduling logistics for an
interview are part of that interview, not a further stage.

This matters for the interview simulation. Template E has three phases — CV
claims, a case study, an executive behavioural test — and which phase to
rehearse depends on which round is next.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Sequence

from vanguard.mail import State

__all__ = [
    "ProcessState",
    "Round",
    "InterviewProcess",
    "ProcessStore",
    "PROCESS_SCHEMA",
    "suggested_phase",
]

PROCESS_SCHEMA = """
-- One interview process per application. Opened by the first PROGRESS.
CREATE TABLE IF NOT EXISTS interviews (
  vacancy_id   TEXT PRIMARY KEY,
  state        TEXT NOT NULL,
  opened_at    TIMESTAMP NOT NULL,
  closed_at    TIMESTAMP,
  outcome_note TEXT
);

-- One row per round. ADMIN and QUERY messages attach to the current round
-- rather than opening a new one — scheduling an interview is part of that
-- interview, not a further stage.
CREATE TABLE IF NOT EXISTS interview_rounds (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  vacancy_id  TEXT NOT NULL,
  number      INTEGER NOT NULL,
  opened_at   TIMESTAMP NOT NULL,
  state       TEXT,
  subject     TEXT,
  sender      TEXT,
  note        TEXT
);
CREATE INDEX IF NOT EXISTS ix_rounds_vacancy ON interview_rounds(vacancy_id);

-- Every message attached to a process, in order.
CREATE TABLE IF NOT EXISTS interview_messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  vacancy_id  TEXT NOT NULL,
  round_number INTEGER,
  at          TIMESTAMP NOT NULL,
  state       TEXT NOT NULL,
  sender      TEXT,
  subject     TEXT
);
CREATE INDEX IF NOT EXISTS ix_imessages_vacancy ON interview_messages(vacancy_id);
"""


class ProcessState(str, Enum):
    """Where an interview process stands.

    Only OFFER, DECLINE and WITHDRAWN are terminal. Monitoring stops on those
    and on nothing else — silence is an absence of information, not an
    outcome.
    """

    ACTIVE = "ACTIVE"
    OFFER = "OFFER"
    DECLINE = "DECLINE"
    WITHDRAWN = "WITHDRAWN"

    @property
    def terminal(self) -> bool:
        return self is not ProcessState.ACTIVE


#: Message states that open a new round. Everything else attaches to the
#: current one.
_OPENS_A_ROUND = frozenset({State.PROGRESS})

#: Message states that end the process, and what they end it as.
_TERMINAL = {
    State.OFFER: ProcessState.OFFER,
    State.DECLINE: ProcessState.DECLINE,
}


@dataclass
class Round:
    number: int
    opened_at: str
    state: str = ""
    subject: str = ""
    sender: str = ""
    note: str = ""


@dataclass
class InterviewProcess:
    vacancy_id: str
    state: ProcessState = ProcessState.ACTIVE
    opened_at: str = ""
    closed_at: str = ""
    outcome_note: str = ""
    rounds: list[Round] = field(default_factory=list)
    message_count: int = 0

    @property
    def current_round(self) -> int:
        return self.rounds[-1].number if self.rounds else 0

    @property
    def active(self) -> bool:
        return self.state is ProcessState.ACTIVE

    def summary(self) -> str:
        if self.state is ProcessState.ACTIVE:
            return f"round {self.current_round}, {self.message_count} message(s)"
        return f"{self.state.value} after {self.current_round} round(s)"


def suggested_phase(round_number: int) -> int:
    """Which Template E phase to rehearse before a given round.

    Phase 1 verifies CV claims, 2 is a runtime case study, 3 an executive
    behavioural test. Real processes rarely exceed three stages, so a fourth
    round rehearses phase 3 again rather than inventing a phase 4.
    """
    return max(1, min(3, round_number))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ProcessStore:
    """Reads and writes interview processes. Never fails a mail run."""

    path: str

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.executescript(PROCESS_SCHEMA)
        return conn

    # -- reading -----------------------------------------------------------

    def get(self, vacancy_id: str) -> InterviewProcess | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM interviews WHERE vacancy_id = ?", (vacancy_id,)
            ).fetchone()
            if row is None:
                return None

            rounds = [
                Round(number=r["number"], opened_at=r["opened_at"],
                      state=r["state"] or "", subject=r["subject"] or "",
                      sender=r["sender"] or "", note=r["note"] or "")
                for r in conn.execute(
                    "SELECT * FROM interview_rounds WHERE vacancy_id = ? "
                    "ORDER BY number", (vacancy_id,))
            ]
            count = conn.execute(
                "SELECT COUNT(*) FROM interview_messages WHERE vacancy_id = ?",
                (vacancy_id,),
            ).fetchone()[0]

            return InterviewProcess(
                vacancy_id=vacancy_id,
                state=ProcessState(row["state"]),
                opened_at=row["opened_at"],
                closed_at=row["closed_at"] or "",
                outcome_note=row["outcome_note"] or "",
                rounds=rounds,
                message_count=count,
            )
        finally:
            conn.close()

    def active(self) -> list[InterviewProcess]:
        """Processes still running. These are what monitoring is for."""
        conn = self._connect()
        try:
            ids = [r["vacancy_id"] for r in conn.execute(
                "SELECT vacancy_id FROM interviews WHERE state = ? "
                "ORDER BY opened_at", (ProcessState.ACTIVE.value,))]
        finally:
            conn.close()
        return [p for p in (self.get(i) for i in ids) if p is not None]

    def all(self) -> list[InterviewProcess]:
        conn = self._connect()
        try:
            ids = [r["vacancy_id"] for r in conn.execute(
                "SELECT vacancy_id FROM interviews ORDER BY opened_at DESC")]
        finally:
            conn.close()
        return [p for p in (self.get(i) for i in ids) if p is not None]

    # -- writing -----------------------------------------------------------

    def record(self, vacancy_id: str, state: State, *, subject: str = "",
               sender: str = "") -> InterviewProcess | None:
        """Attach a classified message. Opens a process on the first PROGRESS.

        Returns the process, or None when the message neither opens nor
        belongs to one — an ACK on an application that never progressed is
        not an interview.
        """
        existing = self.get(vacancy_id)

        if existing is None:
            if state not in _OPENS_A_ROUND:
                return None
            self._open(vacancy_id, subject=subject, sender=sender)
            return self.get(vacancy_id)

        if existing.state.terminal:
            # A message after a terminal state is recorded but changes
            # nothing. A rejection does not reopen because a mailing list
            # mentions the company afterwards.
            self._attach_message(vacancy_id, existing.current_round, state,
                                 sender, subject)
            return existing

        conn = self._connect()
        try:
            if state in _OPENS_A_ROUND:
                number = existing.current_round + 1
                conn.execute(
                    "INSERT INTO interview_rounds (vacancy_id, number, opened_at,"
                    " state, subject, sender) VALUES (?,?,?,?,?,?)",
                    (vacancy_id, number, _now(), state.value, subject, sender),
                )
            else:
                number = existing.current_round

            conn.execute(
                "INSERT INTO interview_messages (vacancy_id, round_number, at,"
                " state, sender, subject) VALUES (?,?,?,?,?,?)",
                (vacancy_id, number, _now(), state.value, sender, subject),
            )

            terminal = _TERMINAL.get(state)
            if terminal is not None:
                conn.execute(
                    "UPDATE interviews SET state = ?, closed_at = ?,"
                    " outcome_note = ? WHERE vacancy_id = ?",
                    (terminal.value, _now(),
                     f"closed by a {state.value} message", vacancy_id),
                )
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            conn.close()

        return self.get(vacancy_id)

    def _open(self, vacancy_id: str, *, subject: str = "", sender: str = "") -> None:
        conn = self._connect()
        try:
            now = _now()
            conn.execute(
                "INSERT OR IGNORE INTO interviews (vacancy_id, state, opened_at)"
                " VALUES (?,?,?)", (vacancy_id, ProcessState.ACTIVE.value, now))
            conn.execute(
                "INSERT INTO interview_rounds (vacancy_id, number, opened_at,"
                " state, subject, sender) VALUES (?,?,?,?,?,?)",
                (vacancy_id, 1, now, State.PROGRESS.value, subject, sender))
            conn.execute(
                "INSERT INTO interview_messages (vacancy_id, round_number, at,"
                " state, sender, subject) VALUES (?,?,?,?,?,?)",
                (vacancy_id, 1, now, State.PROGRESS.value, sender, subject))
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    def _attach_message(self, vacancy_id: str, round_number: int, state: State,
                        sender: str, subject: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO interview_messages (vacancy_id, round_number, at,"
                " state, sender, subject) VALUES (?,?,?,?,?,?)",
                (vacancy_id, round_number, _now(), state.value, sender, subject))
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    def withdraw(self, vacancy_id: str, reason: str) -> bool:
        """Operator closure. The third terminal state, and the only one the
        operator sets."""
        if self.get(vacancy_id) is None:
            return False
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE interviews SET state = ?, closed_at = ?, outcome_note = ?"
                " WHERE vacancy_id = ?",
                (ProcessState.WITHDRAWN.value, _now(), reason, vacancy_id))
            conn.commit()
        finally:
            conn.close()
        return True
