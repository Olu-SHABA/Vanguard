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


# ---------------------------------------------------------------------------
# Running a command from a pane
#
# Two mechanisms, because `vanguard review` and `vanguard run` want different
# things. One prints and finishes; the other streams for minutes and asks
# questions. Capturing the second into a pane shows nothing until it ends,
# and a prompt nobody can see hangs it.
# ---------------------------------------------------------------------------

def test_a_printing_command_runs_in_a_pane(populated: str) -> None:
    from vanguard.panes import render_command

    text = render_command(
        ["sql", "SELECT status, COUNT(*) FROM queue GROUP BY status"],
        db=populated, width=60)
    assert "PENDING" in text


def test_a_command_needing_a_terminal_is_not_captured(populated: str) -> None:
    """A hung pane looks like a slow one.

    The pane view SUSPENDS and runs these for real — refusing was the first
    design and it was wrong, because `run` is the single most useful thing to
    type and being told to press another key and type it again is not help.
    This message is only reached outside the pane view.
    """
    from vanguard.panes import INTERACTIVE, render_command

    for name in sorted(INTERACTIVE):
        text = render_command([name], db=populated, width=60)
        assert "needs a terminal" in text, name
        assert f"vanguard {name}" in text


def test_every_interactive_command_exists() -> None:
    """A name in the list that is not a command would refuse something that
    was never there, and let the real one hang."""
    from vanguard.panes import INTERACTIVE

    for name in INTERACTIVE:
        assert name in main.commands, name


def test_the_streaming_commands_are_all_listed() -> None:
    """`run`, `poll` and `session` are the ones that hang a pane. Named
    explicitly so a new streaming command is a deliberate omission rather
    than an oversight."""
    from vanguard.panes import INTERACTIVE

    for name in ("run", "poll", "session"):
        assert name in INTERACTIVE


def test_a_typo_suggests_rather_than_failing(populated: str) -> None:
    from vanguard.panes import render_command

    text = render_command(["revew"], db=populated, width=60)
    assert "no command" in text
    assert "review" in text


def test_options_are_passed_through(populated: str) -> None:
    """The command bar IS the CLI. Anything the CLI accepts works."""
    from vanguard.panes import render_command

    text = render_command(["review", "--status", "DISPATCHED"],
                          db=populated, width=70)
    assert "DISPATCHED" in text


def test_an_explicit_db_is_not_overridden(tmp_path: Path,
                                          populated: str) -> None:
    """Typing `--db` yourself must win over the pane view's."""
    from vanguard.panes import render_command

    other = tmp_path / "other.db"
    Store(other).initialise()

    text = render_command(["review", "--db", str(other)],
                          db=populated, width=70)
    assert "no records" in text, (
        "the typed --db must win — otherwise it would read the pane's store")


def test_nothing_typed_is_handled(populated: str) -> None:
    from vanguard.panes import render_command

    assert render_command([], db=populated, width=60)


# ---------------------------------------------------------------------------
# After a suspended command
#
# `run` streams to the terminal, and when the panes come back that output is
# gone. The operator ran something, returned, and could not tell what it had
# done — the panes looked much as before.
#
# Every one of these leaves a record. This is where each is found.
# ---------------------------------------------------------------------------

def test_every_interactive_command_has_a_follow_up() -> None:
    """A command with nowhere to look afterwards leaves the operator with
    nothing, which is the defect this fixes."""
    from vanguard.panes import AFTER, INTERACTIVE

    missing = sorted(INTERACTIVE - set(AFTER))
    assert not missing, f"no follow-up view for {missing}"


def test_every_follow_up_names_a_real_command() -> None:
    from vanguard.panes import AFTER

    for name, words in AFTER.items():
        assert words, name
        assert words[0] in main.commands, f"{name} -> {words[0]}"


def test_no_follow_up_is_itself_interactive() -> None:
    """A follow-up that streams would suspend the panes again, immediately."""
    from vanguard.panes import AFTER, INTERACTIVE

    for name, words in AFTER.items():
        if name == words[0]:
            continue          # `discover --list` is the read-only form
        assert words[0] not in INTERACTIVE, f"{name} -> {words[0]}"


@pytest.mark.parametrize("name", ["run", "poll", "session"])
def test_the_follow_up_renders(populated: str, name: str) -> None:
    from vanguard.panes import AFTER, render_command

    text = render_command(list(AFTER[name]), db=populated, width=70)
    assert text.strip()
    assert "could not run" not in text


def test_a_run_is_followed_by_its_record(populated: str) -> None:
    """`run` says what it fetched and scored, then that scrolls away. The run
    table holds it."""
    from vanguard.panes import AFTER

    assert AFTER["run"][0] == "logs"
