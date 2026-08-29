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


#: The only two functions permitted to read the store directly.
#:
#: `record_detail` and `queue_rows` exist because no command produces a
#: cursor-addressable list or a single record in the shape a pane needs, and
#: a pane running three commands and stitching the output together would be
#: doing the work it is meant to delegate.
#:
#: Named, so a THIRD is a deliberate decision rather than a drift.
_MAY_READ_THE_STORE = ("record_detail", "queue_rows")


def test_no_pane_reimplements_a_command() -> None:
    """The risk in a second interface is not the building — it is the
    drifting. A filter added to `review` and forgotten on the queue pane
    means the two disagree and nobody knows which to trust.

    Two functions read the store, by name. Everything else delegates, and
    nothing anywhere reimplements SCORING or CLASSIFICATION, which is where
    a divergence would actually matter.
    """
    import vanguard.panes as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    code = "\n".join(line.split("#")[0] for line in source.splitlines()
                     if not line.strip().startswith("#"))

    # Never, anywhere. A pane that classified a message or computed coverage
    # could disagree with the pipeline about the thing that matters.
    for forbidden in ("sqlite3", "SELECT ", "build_lifecycle", "classify(",
                      "compute_coverage", "resolve_term"):
        assert forbidden not in code, (
            f"{forbidden} in panes.py — a pane must run a command, not "
            "reimplement one")

    # Store access only inside the two named functions.
    #
    # Checked on IMPORTS, not on the text `Store`: `ctx=Store()` is Python's
    # own AST marker for assigning to a name, and matching it flagged a
    # string-wrapping helper that has never touched a database.
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name in _MAY_READ_THE_STORE:
            continue

        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom):
                assert "store" not in (inner.module or ""), (
                    f"{node.name} imports the store. Only "
                    f"{', '.join(_MAY_READ_THE_STORE)} may — a third is a "
                    "decision, not a drift")


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


# ---------------------------------------------------------------------------
# The redesign
#
# The first version was a viewer: five panes of command output, a hidden
# command bar, and no menu — so nine views were reachable only by knowing
# their command name, which is the problem a pane view exists to solve.
#
# And the region the sketch labelled INPUT held `status`. The one section
# that gave the layout a purpose was missing.
# ---------------------------------------------------------------------------

def test_the_menu_covers_the_views() -> None:
    """Nine views reachable by name, not by memory."""
    from vanguard.panes import MENU

    names = [name for name, _, _ in MENU]
    assert len(names) == len(set(names))
    for expected in ("Queue", "Flagged", "Replies", "Progress"):
        assert expected in names


def test_every_menu_entry_names_a_real_command() -> None:
    from vanguard.panes import MENU

    for name, hint, words in MENU:
        assert words and words[0] in main.commands, name
        assert hint, f"{name} does not say what it shows"


def test_the_input_region_has_actions() -> None:
    """The sketch's INPUT region. Four things an operator starts with."""
    from vanguard.panes import ACTIONS

    names = {name for _, name, _ in ACTIONS}
    assert {"run", "search", "paste", "poll"} <= names
    for key, name, hint in ACTIONS:
        assert len(key) == 1, f"{name}: {key!r} is not a single key"
        assert name in main.commands, name
        assert hint


def test_action_keys_are_unique() -> None:
    from vanguard.panes import ACTIONS

    keys = [key for key, _, _ in ACTIONS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    "words, status",
    [
        (("review", "--status", "PENDING", "--limit", "30"), "PENDING"),
        (("review", "--status", "FLAGGED"), "FLAGGED"),
        (("review",), "PENDING"),
        (("funnel",), ""),
        (("responses", "--limit", "30"), ""),
        ((), ""),
    ],
)
def test_selectable_views_are_identified(words, status: str) -> None:
    """A view over the queue drives the record pane. A funnel has nothing to
    select."""
    from vanguard.tui import status_of

    assert status_of(words) == status


# --- the record that follows the cursor ------------------------------------

def test_queue_rows_are_addressable(populated: str) -> None:
    """A list a cursor moves through needs to know which row is which."""
    from vanguard.panes import queue_rows

    rows = queue_rows("PENDING", db=populated)
    assert rows
    for vacancy_id, label in rows:
        assert vacancy_id.startswith("reed:")
        assert label.strip()


def test_a_record_shows_more_than_the_row(populated: str) -> None:
    """The point of the redesign. A row says a vacancy scored 0.62; the
    record says which terms it missed, which is what decides whether to
    apply."""
    from vanguard.panes import queue_rows, record_detail

    vacancy_id, _label = queue_rows("PENDING", db=populated)[0]
    text = record_detail(vacancy_id, db=populated, width=60)
    assert "Employer" in text


def test_a_record_fits_its_pane(populated: str) -> None:
    """Requirement terms are not always words — extraction produces whole
    competency phrases, and one of those is wider than any pane."""
    from vanguard.panes import queue_rows, record_detail

    vacancy_id, _label = queue_rows("PENDING", db=populated)[0]
    for width in (44, 60, 100):
        text = record_detail(vacancy_id, db=populated, width=width)
        assert max(len(line) for line in text.splitlines()) <= width


def test_no_selection_says_so(populated: str) -> None:
    from vanguard.panes import record_detail

    assert "select a row" in record_detail("", db=populated, width=60)


def test_an_unknown_record_is_reported(populated: str) -> None:
    from vanguard.panes import record_detail

    assert "no record" in record_detail("reed:nothere", db=populated, width=60)


def test_a_broken_store_does_not_raise(tmp_path: Path) -> None:
    """A traceback taking down the screen because one pane could not read is
    worse than one pane saying so."""
    from vanguard.panes import queue_rows, record_detail

    nowhere = str(tmp_path / "nothing" / "x.db")
    assert queue_rows("PENDING", db=nowhere) == []
    assert record_detail("reed:1", db=nowhere, width=60)
