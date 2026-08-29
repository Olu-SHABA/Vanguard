"""Pane content — windows onto the commands, not a second implementation."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.adapters.base import Vacancy
from vanguard.cli import main
from vanguard.panes import PANES, pane_named, render
from vanguard.store import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def populated(tmp_path: Path) -> str:
    db = tmp_path / "v.db"
    store = Store(db)
    store.initialise()
    for i in range(6):
        store.upsert_vacancy(Vacancy(
            id=f"reed:{i}", board_id="reed", employer=f"Employer {i}",
            title="Data Scientist", description="d"))
        store.create_queue_record(f"reed:{i}", "PENDING")
        if i > 2:
            store.set_status(f"reed:{i}", "DISPATCHED")
    store.record_response("reed:3", "DECLINE", sender="hr@x.com",
                          subject="Update", received_at="2026-08-20",
                          body="We have decided to proceed with others.")
    return str(db)


# --- the promise this module makes ----------------------------------------

def test_every_pane_names_a_real_command() -> None:
    """A pane whose command does not exist is a pane that will never render,
    and the failure would only appear on screen."""
    for pane in PANES:
        assert pane.command in main.commands, f"{pane.title}: {pane.command}"


def test_no_pane_computes_anything() -> None:
    """The risk in a second interface is not the building — it is the
    drifting. A filter added to `review` and forgotten on the queue pane
    means the two disagree and nobody knows which to trust.

    Asserted structurally: nothing in `panes.py` touches the store.
    """
    import vanguard.panes as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    code = "\n".join(line.split("#")[0] for line in source.splitlines()
                     if not line.strip().startswith("#"))

    for forbidden in ("Store(", "sqlite3", "SELECT ", "build_lifecycle",
                      "classify(", "compute_coverage"):
        assert forbidden not in code, (
            f"{forbidden} in panes.py — a pane must run a command, not "
            "reimplement one")


def test_every_pane_names_its_full_command() -> None:
    """A pane is always smaller than the output it can be asked to show, so
    each must say where to see the whole thing."""
    for pane in PANES:
        assert pane.full.startswith("vanguard "), pane.title
        assert pane.hint, f"{pane.title} does not say what it is for"


def test_pane_keys_are_unique() -> None:
    keys = [p.key for p in PANES]
    assert len(keys) == len(set(keys))


# --- rendering ------------------------------------------------------------

@pytest.mark.parametrize("key", [p.key for p in PANES])
def test_every_pane_renders(populated: str, key: str) -> None:
    pane = pane_named(key)
    assert pane is not None
    text = render(pane, db=populated, width=70)
    assert text.strip()
    assert "could not run" not in text


def test_a_pane_respects_its_width(populated: str) -> None:
    """A pane is narrower than the terminal, and the command has to be told.

    Checked through the THEME rather than by measuring output: `review` pads
    its id column to a full vacancy id whatever the width, so its longest
    line says nothing about whether the width was applied.
    """
    from vanguard import ui

    render(pane_named("s"), db=populated, width=53)
    assert ui.current_theme().width == 53

    render(pane_named("s"), db=populated, width=101)
    assert ui.current_theme().width == 101


def test_a_command_without_db_still_renders(populated: str) -> None:
    """`boards` takes no `--db`, and passing one would fail the whole pane."""
    text = render(pane_named("b"), db=populated, width=70)
    assert "registered" in text


def test_an_empty_store_renders_rather_than_failing(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    Store(db).initialise()
    text = render(pane_named("s"), db=str(db), width=70)
    assert "nothing ingested yet" in text


def test_a_failure_is_shown_not_raised(tmp_path: Path) -> None:
    """A traceback taking down the whole screen because one command had no
    store is worse than one pane reading 'no store yet'."""
    text = render(pane_named("s"), db=str(tmp_path / "nowhere" / "x.db"),
                  width=70)
    assert isinstance(text, str) and text.strip()


def test_rendering_does_not_leak_the_column_setting(populated: str) -> None:
    """`COLUMNS` is how a pane tells a command its width. Left set, it would
    change the width of every later command in the process."""
    import os

    before = os.environ.get("COLUMNS")
    render(pane_named("s"), db=populated, width=55)
    assert os.environ.get("COLUMNS") == before
