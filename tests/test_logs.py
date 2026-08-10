"""Logging — two stores, hybrid rotation, archival retention."""
from __future__ import annotations

import gzip
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vanguard.logs import (
    LOG_SCHEMA,
    LogConfig,
    RunLog,
    archive_old_records,
    compress_old_files,
    configure,
)


@pytest.fixture
def config(tmp_path: Path) -> LogConfig:
    return LogConfig(enabled=True, directory=tmp_path / "logs")


# --- the switch -----------------------------------------------------------

def test_enabled_by_default() -> None:
    """Recommended on: a log that is off when you need it is worthless."""
    assert LogConfig().enabled


def test_config_reads_from_registry_defaults() -> None:
    config = LogConfig.from_registry({"logging": {
        "enabled": False, "level": "DEBUG", "rotate_hours": 12,
        "retain_days": 7, "archive_after_days": 90,
    }})
    assert not config.enabled and config.level == "DEBUG"
    assert config.rotate_hours == 12 and config.archive_after_days == 90


def test_absent_block_uses_recommended_defaults() -> None:
    config = LogConfig.from_registry({})
    assert config.enabled and config.rotate_hours == 24


def test_disabled_writes_nothing(tmp_path: Path) -> None:
    off = LogConfig(enabled=False, directory=tmp_path / "logs")
    configure(off)
    with RunLog("run", db_path=tmp_path / "v.db", config=off) as run:
        run.error("should not be recorded")
    assert not (tmp_path / "logs").exists()


# --- two stores, different content ----------------------------------------

def test_run_is_recorded_in_the_database(config: LogConfig, tmp_path: Path) -> None:
    configure(config)
    with RunLog("run", db_path=tmp_path / "v.db", config=config) as run:
        run.count(collected=45, kept=42, scored=31)

    conn = sqlite3.connect(str(tmp_path / "v.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM runs").fetchone()
    assert row["command"] == "run" and row["outcome"] == "OK"
    assert row["collected"] == 45 and row["scored"] == 31
    assert row["duration_s"] is not None


def test_swallowed_errors_are_recorded(config: LogConfig, tmp_path: Path) -> None:
    """collect() and hydrate_many() catch exceptions to keep a run going.
    Without this the reason is lost with the terminal."""
    configure(config)
    with RunLog("run", db_path=tmp_path / "v.db", config=config) as run:
        run.error("HTTP 401 from Adzuna", source="ingest", board_id="adzuna")

    conn = sqlite3.connect(str(tmp_path / "v.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM events WHERE level='ERROR'").fetchone()
    assert row["board_id"] == "adzuna" and "401" in row["message"]


def test_error_count_reaches_the_run_record(config: LogConfig, tmp_path: Path) -> None:
    configure(config)
    with RunLog("run", db_path=tmp_path / "v.db", config=config) as run:
        run.error("one")
        run.error("two")

    conn = sqlite3.connect(str(tmp_path / "v.db"))
    assert conn.execute("SELECT errors FROM runs").fetchone()[0] == 2


def test_file_receives_the_verbose_record(config: LogConfig, tmp_path: Path) -> None:
    configure(config)
    with RunLog("run", db_path=tmp_path / "v.db", config=config) as run:
        run.info("hydrating 31 vacancies", source="ingest")

    text = (config.directory / "vanguard.log").read_text(encoding="utf-8")
    assert "run start" in text and "hydrating 31" in text and "run end" in text


def test_aborted_run_is_still_recorded(config: LogConfig, tmp_path: Path) -> None:
    """An aborted run is exactly the one worth having a record of."""
    configure(config)
    with pytest.raises(ValueError):
        with RunLog("run", db_path=tmp_path / "v.db", config=config):
            raise ValueError("boom")

    conn = sqlite3.connect(str(tmp_path / "v.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM runs").fetchone()
    assert row["outcome"] == "ERROR" and row["errors"] == 1


def test_logging_failure_never_breaks_a_run(tmp_path: Path) -> None:
    """A log that cannot be written must not stop the pipeline."""
    unwritable = LogConfig(enabled=True, directory=tmp_path / "logs")
    configure(unwritable)
    with RunLog("run", db_path=tmp_path / "nonexistent" / "v.db",
                config=unwritable) as run:
        run.error("still fine")


# --- hybrid rotation ------------------------------------------------------

def test_rotation_is_time_led_with_a_size_backstop() -> None:
    """Time-led because runs are daily; the size cap stops a runaway loop
    filling the disk between midnights."""
    from vanguard.logs import HybridRotatingHandler

    assert issubclass(HybridRotatingHandler,
                      __import__("logging.handlers", fromlist=["x"]).TimedRotatingFileHandler)


def test_size_cap_forces_a_rollover(tmp_path: Path) -> None:
    import logging

    from vanguard.logs import HybridRotatingHandler

    handler = HybridRotatingHandler(tmp_path / "v.log", max_bytes=200)
    handler.setFormatter(logging.Formatter("%(message)s"))
    record = logging.LogRecord("t", logging.INFO, "", 0, "x" * 300, None, None)
    handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "first", None, None))
    assert handler.shouldRollover(record) == 1
    handler.close()


def test_no_size_cap_means_time_only(tmp_path: Path) -> None:
    import logging

    from vanguard.logs import HybridRotatingHandler

    handler = HybridRotatingHandler(tmp_path / "v.log", max_bytes=0)
    handler.setFormatter(logging.Formatter("%(message)s"))
    record = logging.LogRecord("t", logging.INFO, "", 0, "x" * 10_000, None, None)
    assert handler.shouldRollover(record) == 0
    handler.close()


# --- retention: archive, never delete -------------------------------------

def test_old_records_are_archived_not_deleted(tmp_path: Path) -> None:
    """Deleting run history destroys the record of how the system behaved."""
    db = tmp_path / "v.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(LOG_SCHEMA)
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
    conn.execute("INSERT INTO runs (command, started_at) VALUES (?,?)", ("run", old))
    conn.execute("INSERT INTO events (at, level, message) VALUES (?,?,?)",
                 (old, "ERROR", "ancient failure"))
    conn.commit()
    conn.close()

    moved = archive_old_records(db, older_than_days=180)
    assert moved["runs"] == 1 and moved["events"] == 1

    working = sqlite3.connect(str(db))
    assert working.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0

    archive = sqlite3.connect(str(tmp_path / "archive.db"))
    assert archive.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert archive.execute(
        "SELECT message FROM events").fetchone()[0] == "ancient failure"


def test_recent_records_are_left_alone(tmp_path: Path) -> None:
    db = tmp_path / "v.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(LOG_SCHEMA)
    conn.execute("INSERT INTO runs (command, started_at) VALUES (?,?)",
                 ("run", datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    conn.close()

    assert archive_old_records(db, older_than_days=180)["runs"] == 0
    assert sqlite3.connect(str(db)).execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_archiving_a_missing_database_is_safe(tmp_path: Path) -> None:
    assert archive_old_records(tmp_path / "absent.db") == {"runs": 0, "events": 0}


def test_old_log_files_are_compressed_not_removed(tmp_path: Path) -> None:
    """A gzipped log is about a tenth the size and still greppable."""
    directory = tmp_path / "logs"
    directory.mkdir()
    old = directory / "vanguard.log.2026-07-01"
    old.write_text("historic detail\n" * 100, encoding="utf-8")
    ancient = time.time() - 60 * 86400
    import os
    os.utime(old, (ancient, ancient))

    assert compress_old_files(directory, older_than_days=30) == 1
    assert not old.exists()
    archive = directory / "vanguard.log.2026-07-01.gz"
    assert archive.is_file()
    with gzip.open(archive, "rt") as handle:
        assert "historic detail" in handle.read()


def test_recent_files_are_not_compressed(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "vanguard.log.2026-08-09").write_text("today", encoding="utf-8")
    assert compress_old_files(directory, older_than_days=30) == 0


def test_already_compressed_files_are_skipped(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    path = directory / "vanguard.log.2026-01-01.gz"
    path.write_bytes(b"\x1f\x8b")
    import os
    old = time.time() - 90 * 86400
    os.utime(path, (old, old))
    assert compress_old_files(directory, older_than_days=30) == 0
