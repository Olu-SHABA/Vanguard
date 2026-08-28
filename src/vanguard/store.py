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

__all__ = ["Store", "StoreError", "SCHEMA", "utcnow", "OPERATOR_SET"]


class StoreError(RuntimeError):
    """A persistence operation failed."""


#: States a human chose. A scheduled run must not overwrite them.
OPERATOR_SET = frozenset({"APPROVED", "REJECTED", "DISPATCHED"})


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
  partial      INTEGER NOT NULL DEFAULT 0,
  closes       TEXT
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

-- Parser observations. Not troubleshooting alone: the unrecognised headings
-- recorded here are the evidence for widening classify_heading(), which is
-- currently the binding constraint on how many adverts can be scored at all.
-- One row per classified inbound message.
--
-- Added 19 Aug 2026: classifications were written to the archive as files
-- and to the interview process, but nothing was queryable. The operator
-- could not ask "what has been rejected?", which is exactly what
-- `vanguard feedback` needs to know.
CREATE TABLE IF NOT EXISTS responses (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  vacancy_id  TEXT NOT NULL,
  message_key TEXT NOT NULL DEFAULT '',
  message_id  TEXT NOT NULL DEFAULT '',
  tokens      TEXT NOT NULL DEFAULT '',
  state       TEXT NOT NULL,
  sender      TEXT,
  subject     TEXT,
  received_at TIMESTAMP,
  recorded_at TIMESTAMP NOT NULL,
  method      TEXT,
  body        TEXT NOT NULL DEFAULT ''
);

-- The unique index on (vacancy_id, message_id) is created in
-- `_deduplicate_responses`, after existing duplicates are collapsed: it
-- cannot be created while they exist, and a database written before this
-- change has them.
CREATE INDEX IF NOT EXISTS ix_responses_vacancy ON responses(vacancy_id);
CREATE INDEX IF NOT EXISTS ix_responses_state ON responses(state);

CREATE TABLE IF NOT EXISTS diagnostics (
  vacancy_id          TEXT NOT NULL,
  board_id            TEXT,
  is_html             INTEGER NOT NULL DEFAULT 0,
  description_chars   INTEGER NOT NULL DEFAULT 0,
  partial             INTEGER NOT NULL DEFAULT 0,
  headings            TEXT,
  heading_kinds       TEXT,
  block_count         INTEGER NOT NULL DEFAULT 0,
  bullet_count        INTEGER NOT NULL DEFAULT 0,
  requirement_bullets INTEGER NOT NULL DEFAULT 0,
  terms_extracted     INTEGER NOT NULL DEFAULT 0,
  refusal             TEXT,
  decisions           TEXT,
  recorded_at         TIMESTAMP NOT NULL,
  PRIMARY KEY (vacancy_id, recorded_at)
);
CREATE INDEX IF NOT EXISTS ix_diagnostics_refusal ON diagnostics(refusal);
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
        ("vacancies", "closes", "TEXT"),
        ("responses", "message_id", "TEXT NOT NULL DEFAULT ''"),
        ("responses", "message_key", "TEXT NOT NULL DEFAULT ''"),
        ("responses", "body", "TEXT NOT NULL DEFAULT ''"),
        ("responses", "tokens", "TEXT NOT NULL DEFAULT ''"),
    )

    def initialise(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            self._deduplicate_responses(conn)

    def _deduplicate_responses(self, conn: sqlite3.Connection) -> None:
        """Collapse rows recorded before responses were keyed on a message id.

        Polling twice recorded everything twice. The unique index cannot be
        created while duplicates exist, so they are collapsed first — keeping
        the earliest row, which carries the true `recorded_at`.
        """
        # The column must exist before it can be keyed on. `_migrate` adds it
        # to an older database, but this runs on paths where the table was
        # only just created, so check rather than assume.
        try:
            columns = {row[1] for row in
                       conn.execute("PRAGMA table_info(responses)")}
        except sqlite3.Error:
            return
        if "message_key" not in columns:
            return

        # Once the index exists, the collapse has already happened and the
        # data is kept correct by the ON CONFLICT clause on every write.
        # Re-running a DROP INDEX, UPDATE, DELETE and CREATE INDEX on every
        # command invocation was pure waste — and `initialise()` runs on
        # every command.
        try:
            done = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index'"
                " AND name = 'ux_responses_key'").fetchone()
            if done:
                return
        except sqlite3.Error:
            return

        try:
            # An index on the old key blocks collapsing rows keyed the other
            # way. Drop it before recomputing.
            conn.execute("DROP INDEX IF EXISTS ux_responses_message")

            conn.execute(
                """UPDATE responses SET message_key =
                     COALESCE(vacancy_id,'') || '|' || COALESCE(sender,'')
                     || '|' || COALESCE(subject,'') || '|'
                     || COALESCE(received_at,'')"""
            )
            conn.execute(
                """DELETE FROM responses WHERE id NOT IN (
                     SELECT MIN(id) FROM responses GROUP BY message_key)"""
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_responses_key"
                " ON responses(message_key)"
            )
        except sqlite3.Error:
            pass

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
                    description, posted, fetched_at, dedup_key, reference, partial, closes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    str(vacancy.closes) if vacancy.closes else None,
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

    # -- diagnostics -------------------------------------------------------

    def record_diagnostic(self, diagnostic) -> None:
        """Persist one advert's parse observations. Never fails a run."""
        try:
            with self.connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO diagnostics
                       (vacancy_id, board_id, is_html, description_chars, partial,
                        headings, heading_kinds, block_count, bullet_count,
                        requirement_bullets, terms_extracted, refusal, decisions,
                        recorded_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    diagnostic.as_row(),
                )
        except StoreError:
            pass      # diagnostics are observational; losing one is not fatal

    def unrecognised_headings(self, limit: int = 30) -> list[sqlite3.Row]:
        """Headings that classified as UNKNOWN, most frequent first.

        The direct input to widening `classify_heading()`. Each row is a
        heading real adverts use that the parser does not yet understand.
        """
        import json as _json

        with self.connect() as conn:
            rows = conn.execute(
                """SELECT headings, heading_kinds FROM diagnostics d
                    WHERE heading_kinds IS NOT NULL
                      AND d.recorded_at = (
                          SELECT MAX(recorded_at) FROM diagnostics d2
                           WHERE d2.vacancy_id = d.vacancy_id)"""
            ).fetchall()

        counts: dict[str, int] = {}
        for row in rows:
            try:
                kinds = _json.loads(row["heading_kinds"] or "{}")
            except ValueError:
                continue
            for heading, kind in kinds.items():
                if heading == "__eligibility__":
                    continue
                if kind == "unknown" and heading.strip():
                    counts[heading.strip()] = counts.get(heading.strip(), 0) + 1

        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"heading": h, "n": n} for h, n in ordered[:limit]]

    def refusal_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT refusal, COUNT(*) AS n FROM diagnostics d
                    WHERE refusal IS NOT NULL AND refusal != ''
                      AND d.recorded_at = (
                          SELECT MAX(recorded_at) FROM diagnostics d2
                           WHERE d2.vacancy_id = d.vacancy_id)
                    GROUP BY refusal"""
            ).fetchall()
        return {r["refusal"]: r["n"] for r in rows}

    def diagnostic_for(self, vacancy_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM diagnostics WHERE vacancy_id = ? "
                "ORDER BY recorded_at DESC LIMIT 1",
                (vacancy_id,),
            ).fetchone()

    def eligibility_gates(self, limit: int = 30) -> list[sqlite3.Row]:
        """Vacancies stating a condition on whether the operator may apply.

        Surfaced, never scored. Only the operator knows their own status.
        """
        import json as _json

        with self.connect() as conn:
            rows = conn.execute(
                """SELECT d.vacancy_id, v.title, v.employer, d.heading_kinds
                     FROM diagnostics d
                     JOIN vacancies v ON v.id = d.vacancy_id
                    WHERE d.recorded_at = (
                          SELECT MAX(recorded_at) FROM diagnostics d2
                           WHERE d2.vacancy_id = d.vacancy_id)
                    LIMIT 500"""
            ).fetchall()

        out = []
        for row in rows:
            try:
                notes = (_json.loads(row["heading_kinds"] or "{}")
                         ).get("__eligibility__") or []
            except ValueError:
                continue
            if notes:
                out.append({"vacancy_id": row["vacancy_id"], "title": row["title"],
                            "employer": row["employer"], "notes": notes})
        return out[:limit]

    def storage_footprint(self) -> dict[str, object]:
        """Row counts and file size. Visible so growth can be MEASURED.

        At 75 vacancies a day the database is the only thing that grows
        without bound — the advert manifest and CSV template are bounded by
        what is currently in the folder. Reporting it here means the decision
        to archive or index is made on numbers rather than on a guess.
        """
        counts: dict[str, int] = {}
        with self.connect() as conn:
            for table in ("vacancies", "scores", "gaps", "queue",
                          "transitions", "diagnostics"):
                try:
                    counts[table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    counts[table] = 0

        size = self.path.stat().st_size if self.path.is_file() else 0
        vacancies = counts.get("vacancies", 0)
        return {
            "counts": counts,
            "bytes": size,
            "rows": sum(counts.values()),
            "bytes_per_vacancy": (size / vacancies) if vacancies else 0,
        }

    @staticmethod
    def _response_key(vacancy_id: str, sender: str, subject: str,
                      received_at: str) -> str:
        return (f"{vacancy_id}|{sender}|{subject}|{received_at}")[:400]

    def record_response(self, vacancy_id: str, state: str, *, sender: str = "",
                        subject: str = "", received_at: str = "",
                        method: str = "", message_id: str = "",
                        body: str = "", tokens: Sequence[str] = ()) -> bool:
        """Record that a classified message arrived for an application.

        Kept even after a terminal state: a rejection followed by an
        administrative message is worth being able to see.

        The body is retained because AMBIGUOUS exists precisely so a human
        reads the message — and until now the system could say one had
        arrived without being able to show it. The archive holds a copy only
        where the vacancy was dispatched, which most are not.

        Truncated: a reply is a few hundred words, and quoted threads and
        marketing footers add megabytes without adding information.
        """
        from datetime import datetime, timezone

        # The key is the NATURAL one — who sent it, about what, and when —
        # not the mailbox's id.
        #
        # Keying on the id created two schemes: rows written before the id
        # was captured carried a synthetic key, rows written after carried
        # the real one, and the same message survived under both. The natural
        # key is stable across that change and across a mailbox that supplies
        # no id at all.
        #
        # `message_id` is still stored, for tracing a record back to the
        # message it came from.
        key = self._response_key(vacancy_id, sender, subject, received_at)

        with self.connect() as conn:
            # Asked before writing, because ON CONFLICT counts an update as a
            # changed row and `rowcount` then cannot distinguish a new message
            # from one that merely gained a body.
            is_new = conn.execute(
                "SELECT COUNT(*) FROM responses WHERE message_key = ?", (key,)
            ).fetchone()[0] == 0

            # ON CONFLICT rather than OR IGNORE: a message recorded before
            # bodies were kept must be able to fill one in on a later poll.
            # Ignoring the row meant it never could, which defeated the point
            # of retaining bodies at all for every message already recorded.
            #
            # Only a MISSING body is filled. A body already stored is left
            # alone, so a re-poll cannot overwrite what was first received.
            cursor = conn.execute(
                "INSERT INTO responses (vacancy_id, message_key, state,"
                " sender, subject, received_at, recorded_at, method, message_id,"
                " body, tokens) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(message_key) DO UPDATE SET"
                "   body = CASE WHEN responses.body = '' THEN excluded.body"
                "               ELSE responses.body END,"
                "   message_id = CASE WHEN responses.message_id = ''"
                "               THEN excluded.message_id"
                "               ELSE responses.message_id END,"
                "   tokens = CASE WHEN responses.tokens = ''"
                "               THEN excluded.tokens ELSE responses.tokens END,"
                # A DECISIVE classification replaces a PROVISIONAL one.
                #
                # Restricting this to AMBIGUOUS was too narrow: Faculty's
                # rejection was stored ACK, and every later poll classified it
                # DECLINE correctly and threw the result away. An
                # acknowledgement is a holding state — it means nothing was
                # decided yet — so a later reading that finds a decision
                # should win.
                #
                # A decisive state is never replaced. DECLINE must not become
                # ACK because a threshold moved.
                "   state = CASE WHEN responses.state IN"
                "               ('AMBIGUOUS', 'ACK', 'ADMIN')"
                "               AND excluded.state NOT IN"
                "               ('AMBIGUOUS', 'ACK', 'ADMIN')"
                "               THEN excluded.state ELSE responses.state END",
                (vacancy_id, key, state, sender, subject, received_at,
                 datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 method, message_id, (body or "")[:8000],
                 " ".join(tokens)),
            )
            return is_new

    def responses(self, state: str = "", limit: int = 200) -> list[sqlite3.Row]:
        """Classified messages, most recent first."""
        query = ("SELECT r.*, v.employer, v.title FROM responses r"
                 " LEFT JOIN vacancies v ON v.id = r.vacancy_id")
        params: tuple = ()
        if state:
            query += " WHERE r.state = ?"
            params = (state.upper(),)
        query += " ORDER BY r.recorded_at DESC LIMIT ?"

        with self.connect() as conn:
            return conn.execute(query, (*params, limit)).fetchall()

    def vacancies_awaiting_text(self, limit: int = 500) -> list[sqlite3.Row]:
        """Discovered vacancies with no advert stored.

        An empty description is what marks a record as awaiting text: a board
        that cannot supply a scoreable advert stores none at all, rather than
        a truncated one that would score as though it were complete.
        """
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM vacancies WHERE COALESCE(TRIM(description), '') = ''"
                " ORDER BY employer, title LIMIT ?", (limit,)
            ).fetchall()

    def known_threads(self) -> dict[str, str]:
        """Message ids and subject roots already correlated, to the vacancy.

        Feeds the thread correlation stage: a reply to any of these belongs
        to the same application.
        """
        import re as _re

        out: dict[str, str] = {}
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT vacancy_id, message_id, subject, tokens FROM responses"
            ).fetchall()

        for row in rows:
            if row["message_id"]:
                out[row["message_id"]] = row["vacancy_id"]
            # An ATS routing token identifies an application outright. Every
            # message about it carries the same token, whatever the subject.
            for token in (row["tokens"] or "").split():
                out[f"token:{token}"] = row["vacancy_id"]
            subject = _re.sub(r"^\s*(re|fw|fwd|aw|sv)\s*(\[\d+\])?\s*:\s*",
                              "", (row["subject"] or "").strip(), flags=_re.I)
            subject = _re.sub(r"\s+", " ", subject).strip().lower()
            if len(subject) > 12:
                out[f"subject:{subject}"] = row["vacancy_id"]
        return out

    def reclassify(self, classify_fn, *, force: bool = False
                   ) -> tuple[int, int]:
        """Re-run classification over stored bodies.

        Returns `(changed, total)`. Needs no mailbox: the bodies are already
        held, so a classifier improved after the fact can be applied to
        everything already received.

        `force` also rewrites DECIDED states. Without it a record written
        wrongly as DECLINE or OFFER by an earlier classifier is permanent —
        which is exactly what happened: seven acknowledgements were frozen as
        decisions that the current classifier gets right.

        Off by default, because overwriting a decision the operator has acted
        on is not something to do silently.
        """
        rows = self.responses(limit=5000)
        changed = 0

        with self.connect() as conn:
            for row in rows:
                if not (row["body"] or "").strip():
                    continue
                new_state = classify_fn(row)
                if not new_state or new_state == row["state"]:
                    continue
                if not force:
                    # A provisional state gives way to a decisive one, and a
                    # decisive one is never overwritten.
                    if row["state"] not in ("AMBIGUOUS", "ACK", "ADMIN"):
                        continue
                    if new_state in ("AMBIGUOUS", "ACK", "ADMIN"):
                        continue
                conn.execute("UPDATE responses SET state = ? WHERE id = ?",
                             (new_state, row["id"]))
                changed += 1
            conn.commit()

        return changed, len(rows)

    def latest_response(self, vacancy_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM responses WHERE vacancy_id = ?"
                " ORDER BY recorded_at DESC LIMIT 1", (vacancy_id,)
            ).fetchone()

    def parse_health(self) -> dict[str, int]:
        """How many adverts parse, refuse, or were never HTML.

        Counted over the LATEST diagnostic per vacancy. `diagnostics` holds one
        row per advert per run, so mixing `COUNT(DISTINCT vacancy_id)` for the
        denominator with a plain `SUM` for the numerator produced 176 scored
        out of 33 parsed — 533%, and a negative refusal count.

        The same defect as B-21 in `list_queue()`, repeated here.
        """
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN terms_extracted > 0 THEN 1 ELSE 0 END) AS scored,
                          SUM(CASE WHEN is_html = 1 THEN 1 ELSE 0 END) AS html
                     FROM diagnostics d
                    WHERE d.recorded_at = (
                          SELECT MAX(recorded_at) FROM diagnostics d2
                           WHERE d2.vacancy_id = d.vacancy_id)"""
            ).fetchone()
        return {
            "total": row["total"] or 0,
            "scored": row["scored"] or 0,
            "html": row["html"] or 0,
        }

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
        """Which requirements recur as unmet. Standing skills gaps, not noise.

        Counts DISTINCT vacancies. `record_score` replaces a vacancy's gap
        rows on each run, so this is already one set per vacancy — but the
        count is stated explicitly so a future change cannot inflate it.
        """
        with self.connect() as conn:
            return conn.execute(
                """SELECT term, COUNT(DISTINCT vacancy_id) AS n FROM gaps
                   WHERE outcome = 'GAP' GROUP BY term
                   ORDER BY n DESC, term LIMIT ?""",
                (limit,),
            ).fetchall()

    def score_history(self, vacancy_id: str) -> list[sqlite3.Row]:
        """Every score this vacancy has received, oldest first.

        Retained deliberately: seeing 0.333 -> 0.636 -> 1.000 across runs is
        how you tell whether a change to extraction helped.
        """
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM scores WHERE vacancy_id = ? ORDER BY computed_at",
                (vacancy_id,),
            ).fetchall()

    def coverage_distribution(self, latest_only: bool = True,
                              reliable_only: bool = True) -> list[sqlite3.Row]:
        """Logged coverage values. The input to threshold recalibration.

        `reliable_only` excludes scores computed from fewer than
        MIN_TERMS_FOR_CONFIDENCE requirements, or from partial advert text.
        Those are recorded as 0.000 or 1.000 depending on whether the single
        extracted term happened to match — neither figure measures fit.

        Including them made the median 0.000 across 553 vacancies and put 65
        records at or above 0.94, none of which was a genuine match.
        Recalibrating the gate on that distribution would set it from
        unmeasured scores.

        `latest_only` counts each vacancy once. Passing False returns the full
        history, which mixes scores produced by different extraction logic.
        """
        from vanguard.coverage import MIN_TERMS_FOR_CONFIDENCE

        if not latest_only:
            return self._all_scores()

        reliability = ""
        if reliable_only:
            reliability = (f" AND s.terms_total >= {int(MIN_TERMS_FOR_CONFIDENCE)}"
                           " AND COALESCE(v.partial, 0) = 0")

        with self.connect() as conn:
            return conn.execute(
                f"""SELECT s.vacancy_id, s.coverage, s.ceiling, s.rank_score,
                           s.embedder, s.computed_at, s.terms_total
                      FROM scores s
                      JOIN vacancies v ON v.id = s.vacancy_id
                     WHERE s.computed_at = (
                           SELECT MAX(computed_at) FROM scores s2
                            WHERE s2.vacancy_id = s.vacancy_id){reliability}
                     ORDER BY s.computed_at"""
            ).fetchall()

    def unmeasured_count(self) -> int:
        """Vacancies whose latest score was not measurable."""
        from vanguard.coverage import MIN_TERMS_FOR_CONFIDENCE

        with self.connect() as conn:
            row = conn.execute(
                f"""SELECT COUNT(*) FROM scores s
                      JOIN vacancies v ON v.id = s.vacancy_id
                     WHERE s.computed_at = (
                           SELECT MAX(computed_at) FROM scores s2
                            WHERE s2.vacancy_id = s.vacancy_id)
                       AND (s.terms_total < {int(MIN_TERMS_FOR_CONFIDENCE)}
                            OR COALESCE(v.partial, 0) = 1)"""
            ).fetchone()
        return row[0] if row else 0

    def _all_scores(self) -> list[sqlite3.Row]:
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
            existing = conn.execute(
                "SELECT status FROM queue WHERE vacancy_id = ?", (vacancy_id,)
            ).fetchone()
            previous = existing["status"] if existing else None

            if previous in OPERATOR_SET:
                # The operator decided this. Re-scoring may refresh the
                # numbers, but a decision is not something a scheduled run
                # gets to undo — an application dispatched at 22:15 came back
                # as PENDING after the next run at 22:22.
                conn.execute(
                    """UPDATE queue SET submission_type = ?, flags = ?,
                              artefacts = ?, updated_at = ?
                        WHERE vacancy_id = ?""",
                    (submission_type, json.dumps(flags or {}),
                     json.dumps(list(artefacts)), now, vacancy_id),
                )
                return

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

            # Only record a transition when the state actually CHANGED. A run
            # that re-scores a vacancy and reaches the same conclusion is not
            # a state change, and 24 identical "- -> PENDING" lines make the
            # audit trail unreadable.
            if previous != status:
                conn.execute(
                    "INSERT INTO transitions (vacancy_id, from_state, to_state,"
                    " at, note) VALUES (?,?,?,?,?)",
                    (vacancy_id, previous, status, now,
                     note or ("created" if previous is None else "re-scored")),
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

    def list_queue(self, status: str | None = None, limit: int = 50,
                   order: str = "rank") -> list[sqlite3.Row]:
        """Queue records, ordered as asked.

        `rank` is right for PENDING — strongest first is what you review. It
        is meaningless for FLAGGED, which is flagged BECAUSE the score could
        not be measured, so those came back in effectively arbitrary order.

        `date` orders by when the vacancy was first seen, newest first. That
        is the order an operator works a backlog in, and the sensible default
        for anything unscored.
        """
        # `scores` holds one row PER RUN by design — that history is the input
        # to threshold recalibration. Joining it naively multiplied each queue
        # record by its number of scoring runs: two vacancies rendered as
        # twenty rows after ten runs.
        sql = """SELECT q.*, v.employer, v.title, v.url, v.board_id,
                        s.coverage, s.rank_score, s.ceiling, s.embedder,
                        s.computed_at, s.terms_total, s.terms_matched,
                        v.partial
                 FROM queue q
                 JOIN vacancies v ON v.id = q.vacancy_id
                 LEFT JOIN scores s
                        ON s.vacancy_id = q.vacancy_id
                       AND s.computed_at = (
                             SELECT MAX(computed_at) FROM scores s2
                              WHERE s2.vacancy_id = q.vacancy_id)"""
        params: list[Any] = []
        if status:
            sql += " WHERE q.status = ?"
            params.append(status)
        orderings = {
            "rank": ("s.rank_score DESC NULLS LAST, s.coverage DESC, "
                     "q.updated_at DESC"),
            "date": "q.updated_at DESC, v.employer",
            "coverage": "s.coverage DESC NULLS LAST, q.updated_at DESC",
            "employer": "v.employer, v.title",
            "title": "v.title, v.employer",
        }
        sql += " ORDER BY " + orderings.get(order, orderings["rank"])

        # `limit=0` means everything. A silent cap of fifty on a queue of five
        # hundred showed a tenth of it with no indication, which made the
        # backlog impossible to work through.
        if limit:
            sql += " LIMIT ?"
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
