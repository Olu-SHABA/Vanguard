"""
Persistence layer — SQLite.

Five tables per BUILD_PLAN §5.1. `transitions` is the audit trail: every state
change is appended, never overwritten, so the history of a vacancy is
reconstructible from the row sequence alone.

**Instrument from day one.** Every scoring run writes coverage, rank score and
the full itemised gap list, from the first vacancy. The 0.94 threshold cannot
be recalibrated without that data and it cannot be reconstructed later — a
gap list discarded at scoring time is gone. This is the single most important
property of this module.

Single writer by design. The autonomous run writes and exits; the interactive
session reads and acts. Concurrent writers are out of scope, and WAL mode plus
a busy timeout is sufficient for the one case where they briefly overlap.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from vanguard.adapters.base import Vacancy
from vanguard.coverage import CoverageReport, Outcome
from vanguard.gaps import GapReport

__all__ = ["Store", "StoreError", "SCHEMA", "utcnow"]


class StoreError(RuntimeError):
    """A persistence operation failed."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
  id           TEXT PRIMARY KEY,
  board_id     TEXT NOT NULL,
  employer     TEXT NOT NULL,
  title        TEXT NOT NULL,
  location     TEXT,
  salary_band  TEXT,
  url          TEXT,
  description  TEXT NOT NULL,
  posted       TIMESTAMP,
  fetched_at   TIMESTAMP NOT NULL,
  dedup_key    TEXT NOT NULL,
  reference    TEXT NOT NULL DEFAULT '',
  partial      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_vacancies_dedup ON vacancies(dedup_key);
CREATE INDEX IF NOT EXISTS ix_vacancies_board ON vacancies(board_id);

CREATE TABLE IF NOT EXISTS scores (
  vacancy_id     TEXT NOT NULL REFERENCES vacancies(id),
  coverage       REAL NOT NULL,
  rank_score     REAL,
  ceiling        REAL NOT NULL,
  terms_total    INTEGER NOT NULL,
  terms_matched  INTEGER NOT NULL,
  soft_hits      INTEGER NOT NULL DEFAULT 0,
  embedder       TEXT NOT NULL DEFAULT 'none',
  computed_at    TIMESTAMP NOT NULL,
  PRIMARY KEY (vacancy_id, computed_at)
);

-- Every unmatched term, itemised. Discarding this makes recalibration
-- impossible, so it is written on every run without exception.
CREATE TABLE IF NOT EXISTS gaps (
  vacancy_id   TEXT NOT NULL REFERENCES vacancies(id),
  term         TEXT NOT NULL,
  gap_type     INTEGER,
  outcome      TEXT NOT NULL,
  stage        INTEGER NOT NULL,
  score        REAL,
  source_role  TEXT,
  evidence     TEXT,
  exclusion    TEXT,
  confirmed    INTEGER NOT NULL DEFAULT 0,
  recorded_at  TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_gaps_vacancy ON gaps(vacancy_id);
CREATE INDEX IF NOT EXISTS ix_gaps_term ON gaps(term);

CREATE TABLE IF NOT EXISTS queue (
  vacancy_id       TEXT PRIMARY KEY REFERENCES vacancies(id),
  status           TEXT NOT NULL,
  submission_type  TEXT,
  flags            TEXT,
  artefacts        TEXT,
  note             TEXT,
  created_at       TIMESTAMP NOT NULL,
  updated_at       TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_queue_status ON queue(status);

-- Append-only. Never updated, never deleted.
CREATE TABLE IF NOT EXISTS transitions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  vacancy_id  TEXT NOT NULL,
  from_state  TEXT,
  to_state    TEXT NOT NULL,
  at          TIMESTAMP NOT NULL,
  note        TEXT
);
CREATE INDEX IF NOT EXISTS ix_transitions_vacancy ON transitions(vacancy_id);
"""


@dataclass
class Store:
    """SQLite access layer. Open per operation; not held across a run."""

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=30.0)
        except (OSError, sqlite3.Error) as exc:
            raise StoreError(f"could not open store at {self.path}: {exc}") from exc

        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise StoreError(f"database operation failed: {exc}") from exc
        finally:
            conn.close()

    # Columns added after the first release. `CREATE TABLE IF NOT EXISTS` does
    # not alter an existing table, so a database created before a column was
    # introduced silently lacks it and every insert fails at runtime.
    MIGRATIONS: tuple[tuple[str, str, str], ...] = (
        ("vacancies", "reference", "TEXT NOT NULL DEFAULT ''"),
        ("vacancies", "partial", "INTEGER NOT NULL DEFAULT 0"),
    )

    def initialise(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns missing from an older database. Idempotent."""
        for table, column, ddl in self.MIGRATIONS:
            existing = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
            }
            if not existing:
                continue          # table absent; the schema script will create it
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # -- vacancies ---------------------------------------------------------

    def upsert_vacancy(self, vacancy: Vacancy) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO vacancies
                   (id, board_id, employer, title, location, salary_band, url,
                    description, posted, fetched_at, dedup_key, reference, partial)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     description = excluded.description,
                     fetched_at  = excluded.fetched_at""",
                (
                    vacancy.id, vacancy.board_id, vacancy.employer, vacancy.title,
                    vacancy.location, vacancy.salary_band, vacancy.url,
                    vacancy.description,
                    vacancy.posted.isoformat() if vacancy.posted else None,
                    vacancy.fetched_at.isoformat(), vacancy.dedup_key,
                    vacancy.reference,
                    1 if vacancy.description_is_partial else 0,
                ),
            )

    def vacancy(self, vacancy_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM vacancies WHERE id = ?", (vacancy_id,)
            ).fetchone()

    def count_vacancies(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM vacancies").fetchone()["n"]

    # -- scoring -----------------------------------------------------------

    def record_score(
        self,
        vacancy_id: str,
        report: CoverageReport,
        rank_score: float | None = None,
        *,
        embedder: str = "none",
        gaps: GapReport | None = None,
    ) -> None:
        """Write coverage, rank and the full gap list. Called on every run.

        `embedder` records which model produced the numbers. A LexicalEmbedder
        result is degraded and must be distinguishable in the log from a real
        one, or recalibration will mix them.
        """
        now = utcnow()
        typed = {g.term.lower(): g for g in (gaps.gaps if gaps else ())}

        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO scores
                   (vacancy_id, coverage, rank_score, ceiling, terms_total,
                    terms_matched, soft_hits, embedder, computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (vacancy_id, report.coverage, rank_score, report.ceiling,
                 report.total, report.matched, len(report.soft_hits), embedder, now),
            )

            conn.execute("DELETE FROM gaps WHERE vacancy_id = ?", (vacancy_id,))
            rows = []
            for res in report.resolutions:
                term = (res.requirement.canonical or res.requirement.text)
                gap = typed.get(term.lower())
                rows.append((
                    vacancy_id, term,
                    int(gap.gap_type) if gap else None,
                    res.outcome.value, res.stage, res.score,
                    (gap.source_role if gap else "") or res.source_role,
                    res.evidence, res.exclusion_reason,
                    1 if (gap and gap.confirmed) else 0, now,
                ))
            conn.executemany(
                """INSERT INTO gaps
                   (vacancy_id, term, gap_type, outcome, stage, score,
                    source_role, evidence, exclusion, confirmed, recorded_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )

    def gaps_for(self, vacancy_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM gaps WHERE vacancy_id = ? ORDER BY outcome, term",
                (vacancy_id,),
            ).fetchall()

    def latest_score(self, vacancy_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM scores WHERE vacancy_id = ? "
                "ORDER BY computed_at DESC LIMIT 1",
                (vacancy_id,),
            ).fetchone()

    def unmet_term_frequency(self, limit: int = 20) -> list[sqlite3.Row]:
        """Which requirements recur as unmet. Standing skills gaps, not noise."""
        with self.connect() as conn:
            return conn.execute(
                """SELECT term, COUNT(*) AS n FROM gaps
                   WHERE outcome = 'GAP' GROUP BY term
                   ORDER BY n DESC, term LIMIT ?""",
                (limit,),
            ).fetchall()

    def coverage_distribution(self) -> list[sqlite3.Row]:
        """Every logged coverage value. The input to threshold recalibration."""
        with self.connect() as conn:
            return conn.execute(
                "SELECT vacancy_id, coverage, ceiling, rank_score, embedder, "
                "computed_at FROM scores ORDER BY computed_at"
            ).fetchall()

    # -- queue -------------------------------------------------------------

    def create_queue_record(
        self,
        vacancy_id: str,
        status: str,
        *,
        submission_type: str = "",
        flags: dict[str, Any] | None = None,
        artefacts: Sequence[str] = (),
        note: str = "",
    ) -> None:
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO queue
                   (vacancy_id, status, submission_type, flags, artefacts,
                    note, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(vacancy_id) DO UPDATE SET
                     status = excluded.status,
                     submission_type = excluded.submission_type,
                     flags = excluded.flags,
                     artefacts = excluded.artefacts,
                     note = excluded.note,
                     updated_at = excluded.updated_at""",
                (vacancy_id, status, submission_type, json.dumps(flags or {}),
                 json.dumps(list(artefacts)), note, now, now),
            )
            conn.execute(
                "INSERT INTO transitions (vacancy_id, from_state, to_state, at, note) "
                "VALUES (?,?,?,?,?)",
                (vacancy_id, None, status, now, note or "created"),
            )

    def set_status(self, vacancy_id: str, new_status: str, note: str = "") -> None:
        """Update status and append a transition. Both, or neither."""
        now = utcnow()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT status FROM queue WHERE vacancy_id = ?", (vacancy_id,)
            ).fetchone()
            if row is None:
                raise StoreError(f"no queue record for {vacancy_id!r}")
            conn.execute(
                "UPDATE queue SET status = ?, updated_at = ? WHERE vacancy_id = ?",
                (new_status, now, vacancy_id),
            )
            conn.execute(
                "INSERT INTO transitions (vacancy_id, from_state, to_state, at, note) "
                "VALUES (?,?,?,?,?)",
                (vacancy_id, row["status"], new_status, now, note),
            )

    def queue_record(self, vacancy_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM queue WHERE vacancy_id = ?", (vacancy_id,)
            ).fetchone()

    def list_queue(self, status: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        """Queue records ordered by rank score, strongest first."""
        sql = """SELECT q.*, v.employer, v.title, v.url, v.board_id,
                        s.coverage, s.rank_score, s.ceiling
                 FROM queue q
                 JOIN vacancies v ON v.id = q.vacancy_id
                 LEFT JOIN scores s ON s.vacancy_id = q.vacancy_id"""
        params: list[Any] = []
        if status:
            sql += " WHERE q.status = ?"
            params.append(status)
        sql += " ORDER BY s.rank_score DESC NULLS LAST, s.coverage DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def transitions_for(self, vacancy_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM transitions WHERE vacancy_id = ? ORDER BY id",
                (vacancy_id,),
            ).fetchall()

    def counts_by_status(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM queue GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}
