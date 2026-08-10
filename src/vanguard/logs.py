"""
Logging — operational record, in two stores that hold different things.

**Database.** Structured, queryable, bounded. One row per run, one per error.
Answers questions: how often has Adzuna returned 401 this month, how long does
a run take, which board fails most. A year of daily runs is a few thousand
rows.

**File.** Verbose, chronological, rotating. Every API call, every swallowed
exception, every rate-limit wait — the detail wanted when something broke at
06:00 and is being read at 09:00.

The split matters because the two grow differently. The database is bounded by
what is worth querying; the file is bounded by rotation.

## Rotation — hybrid, time-led

A new file at each 24-hour boundary, because runs are daily and "yesterday's
run is in yesterday's file" is how the file will actually be read. A size cap
runs alongside as a backstop, so a pathological day cannot fill the disk.

## Retention — archive, never delete

Nothing is removed automatically. Old database rows move to `archive.db`; old
log files are gzipped in place. Deleting the record of how the system behaved
destroys the evidence for the next question, which is usually one nobody
anticipated.

## Switch

`boards.yaml` under `defaults`, so it is configuration rather than code:

    logging:
      enabled: true          # recommended
      level: INFO
      directory: logs
      rotate_hours: 24
      max_bytes: 10485760    # backstop against a pathological day
      retain_days: 30        # then gzipped, not deleted
      archive_after_days: 180
"""

from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import os
import shutil
import sqlite3
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "LogConfig",
    "RunLog",
    "configure",
    "get_logger",
    "LOG_SCHEMA",
    "archive_old_records",
    "compress_old_files",
]

LOGGER_NAME = "vanguard"

LOG_SCHEMA = """
-- One row per pipeline run. Bounded by how often the operator runs it.
CREATE TABLE IF NOT EXISTS runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  command      TEXT NOT NULL,
  started_at   TIMESTAMP NOT NULL,
  finished_at  TIMESTAMP,
  duration_s   REAL,
  outcome      TEXT,
  collected    INTEGER DEFAULT 0,
  kept         INTEGER DEFAULT 0,
  scored       INTEGER DEFAULT 0,
  errors       INTEGER DEFAULT 0,
  detail       TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_started ON runs(started_at);

-- Errors that would otherwise be swallowed. `collect()` and `hydrate_many()`
-- catch exceptions to keep a run going; without this the reason is lost.
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      INTEGER,
  at          TIMESTAMP NOT NULL,
  level       TEXT NOT NULL,
  source      TEXT,
  board_id    TEXT,
  vacancy_id  TEXT,
  message     TEXT NOT NULL,
  detail      TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS ix_events_level ON events(level);
CREATE INDEX IF NOT EXISTS ix_events_at ON events(at);
"""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LogConfig:
    """Resolved logging settings. Defaults are the recommended values."""

    enabled: bool = True
    level: str = "INFO"
    directory: Path = Path("logs")
    rotate_hours: int = 24
    max_bytes: int = 10 * 1024 * 1024
    retain_days: int = 30
    archive_after_days: int = 180
    to_database: bool = True
    to_file: bool = True

    @classmethod
    def from_registry(cls, defaults: dict[str, Any] | None) -> LogConfig:
        block = (defaults or {}).get("logging") or {}
        return cls(
            enabled=bool(block.get("enabled", True)),
            level=str(block.get("level", "INFO")).upper(),
            directory=Path(block.get("directory", "logs")),
            rotate_hours=int(block.get("rotate_hours", 24)),
            max_bytes=int(block.get("max_bytes", 10 * 1024 * 1024)),
            retain_days=int(block.get("retain_days", 30)),
            archive_after_days=int(block.get("archive_after_days", 180)),
            to_database=bool(block.get("to_database", True)),
            to_file=bool(block.get("to_file", True)),
        )


# ---------------------------------------------------------------------------
# Hybrid rotation
# ---------------------------------------------------------------------------

class HybridRotatingHandler(logging.handlers.TimedRotatingFileHandler):
    """Rotates on a time boundary OR a size cap, whichever comes first.

    Time-led because runs are daily and the file will be read as "yesterday's
    run is in yesterday's file". The size cap is a backstop: a runaway loop
    should not be able to fill the disk between midnights.
    """

    def __init__(self, filename, *, when: str = "midnight", interval: int = 1,
                 backup_count: int = 0, max_bytes: int = 0, encoding: str = "utf-8"):
        super().__init__(filename, when=when, interval=interval,
                         backupCount=backup_count, encoding=encoding, utc=True)
        self.max_bytes = max_bytes

    def shouldRollover(self, record) -> int:  # noqa: N802 - stdlib name
        if super().shouldRollover(record):
            return 1
        if self.max_bytes > 0 and self.stream is not None:
            self.stream.seek(0, 2)
            if self.stream.tell() + len(self.format(record)) >= self.max_bytes:
                return 1
        return 0


_CONFIGURED: LogConfig | None = None


def configure(config: LogConfig, *, db_path: Path | None = None) -> logging.Logger:
    """Set up file logging. Idempotent — safe to call per command."""
    global _CONFIGURED

    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if not config.enabled:
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        _CONFIGURED = config
        return logger

    logger.setLevel(getattr(logging, config.level, logging.INFO))
    logger.propagate = False

    if config.to_file:
        try:
            config.directory.mkdir(parents=True, exist_ok=True)
            handler = HybridRotatingHandler(
                config.directory / "vanguard.log",
                when="midnight",
                interval=max(1, config.rotate_hours) // 24 or 1,
                backup_count=0,          # nothing is deleted; see compress_old_files
                max_bytes=config.max_bytes,
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s  %(levelname)-8s %(name)s  %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            ))
            logger.addHandler(handler)
        except OSError:
            # A log that cannot be written must not stop the run.
            logger.addHandler(logging.NullHandler())

    _CONFIGURED = config
    return logger


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------

@dataclass
class RunLog:
    """One pipeline run, written to both stores.

    Used as a context manager so the finish record is written even when the
    run raises — an aborted run is exactly the one worth having a record of.
    """

    command: str
    db_path: Path | None = None
    config: LogConfig = field(default_factory=LogConfig)
    run_id: int | None = None
    started: float = field(default_factory=time.monotonic)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    counts: dict[str, int] = field(default_factory=dict)
    error_count: int = 0

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> RunLog:
        get_logger().info("run start: %s", self.command)
        if self.config.enabled and self.config.to_database and self.db_path:
            self.run_id = self._insert_run()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration = time.monotonic() - self.started
        outcome = "ERROR" if exc_type else "OK"
        if exc_type:
            self.error(f"run aborted: {exc}", source=self.command,
                       detail="".join(traceback.format_exception(exc_type, exc, tb)))
        get_logger().info("run end: %s (%s, %.1fs) %s",
                          self.command, outcome, duration, self.counts or "")
        self._finish(outcome, duration)
        return False      # never swallow

    # -- recording ---------------------------------------------------------

    def count(self, **kwargs: int) -> None:
        self.counts.update(kwargs)

    def info(self, message: str, **fields: Any) -> None:
        self._event("INFO", message, fields)

    def warn(self, message: str, **fields: Any) -> None:
        self._event("WARNING", message, fields)

    def error(self, message: str, *, detail: str = "", **fields: Any) -> None:
        """Record a failure that the pipeline is deliberately continuing past.

        `collect()` and `hydrate_many()` catch exceptions so one bad vacancy
        does not abort a run. Without this the reason is lost entirely.
        """
        self.error_count += 1
        self._event("ERROR", message, fields, detail=detail)

    def _event(self, level: str, message: str, fields: dict[str, Any],
               detail: str = "") -> None:
        logger = get_logger()
        extra = " ".join(f"{k}={v}" for k, v in fields.items() if v)
        logger.log(getattr(logging, level, logging.INFO),
                   f"{message} {extra}".strip())

        if not (self.config.enabled and self.config.to_database and self.db_path):
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO events (run_id, at, level, source, board_id,"
                    " vacancy_id, message, detail) VALUES (?,?,?,?,?,?,?,?)",
                    (self.run_id,
                     datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     level, fields.get("source", self.command),
                     fields.get("board_id"), fields.get("vacancy_id"),
                     message, detail or (json.dumps(fields) if fields else None)),
                )
        except sqlite3.Error:
            pass      # logging must never fail a run

    # -- storage -----------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        try:
            conn.executescript(LOG_SCHEMA)
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _insert_run(self) -> int | None:
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO runs (command, started_at) VALUES (?,?)",
                    (self.command, self.started_at),
                )
                return cursor.lastrowid
        except sqlite3.Error:
            return None

    def _finish(self, outcome: str, duration: float) -> None:
        if self.run_id is None:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    """UPDATE runs SET finished_at=?, duration_s=?, outcome=?,
                              collected=?, kept=?, scored=?, errors=?, detail=?
                        WHERE id=?""",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     round(duration, 2), outcome,
                     self.counts.get("collected", 0), self.counts.get("kept", 0),
                     self.counts.get("scored", 0), self.error_count,
                     json.dumps(self.counts) if self.counts else None,
                     self.run_id),
                )
        except sqlite3.Error:
            pass


# ---------------------------------------------------------------------------
# Retention — archive and compress, never delete
# ---------------------------------------------------------------------------

def archive_old_records(db_path: Path, *, older_than_days: int = 180,
                        archive_path: Path | None = None) -> dict[str, int]:
    """Move old rows to `archive.db`. Nothing is deleted.

    Deleting run history destroys the record of how the system behaved over
    time, and the next question is usually one nobody anticipated. The working
    database stays small; the history stays available.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return {"runs": 0, "events": 0}

    archive_path = archive_path or db_path.with_name("archive.db")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)
              ).isoformat(timespec="seconds")
    moved = {"runs": 0, "events": 0}

    source = sqlite3.connect(str(db_path), timeout=15.0)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(str(archive_path), timeout=15.0)
    try:
        source.executescript(LOG_SCHEMA)
        target.executescript(LOG_SCHEMA)

        for table, column in (("runs", "started_at"), ("events", "at")):
            rows = source.execute(
                f"SELECT * FROM {table} WHERE {column} < ?", (cutoff,)
            ).fetchall()
            if not rows:
                continue
            columns = rows[0].keys()
            placeholders = ",".join("?" * len(columns))
            target.executemany(
                f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) "
                f"VALUES ({placeholders})",
                [tuple(r[c] for c in columns) for r in rows],
            )
            target.commit()
            # Only after the archive is committed.
            source.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
            source.commit()
            moved[table] = len(rows)
    except sqlite3.Error:
        pass
    finally:
        source.close()
        target.close()

    return moved


def compress_old_files(directory: Path, *, older_than_days: int = 30) -> int:
    """Gzip rotated logs older than the window. Not deleted — a gzipped log is
    about a tenth the size and still readable with `zgrep`."""
    directory = Path(directory)
    if not directory.is_dir():
        return 0

    cutoff = time.time() - older_than_days * 86400
    compressed = 0
    for path in directory.glob("vanguard.log.*"):
        if path.suffix == ".gz" or path.stat().st_mtime > cutoff:
            continue
        try:
            with path.open("rb") as raw, gzip.open(f"{path}.gz", "wb") as archive:
                shutil.copyfileobj(raw, archive)
            path.unlink()
            compressed += 1
        except OSError:
            continue
    return compressed
