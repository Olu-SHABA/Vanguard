"""Pane content — windows onto the commands, not a second implementation."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.adapters.base import Vacancy
from vanguard.cli import main
from vanguard.panes import MENU, queue_rows, record_detail
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

def test_the_menu_is_six_stages_then_three() -> None:
    """Six pipeline stages, then three reachable any time. The order is a
    hint, not a path — the operator bounces."""
    from vanguard.panes import MENU

    stages = [name for name, _, _, is_stage in MENU if is_stage]
    support = [name for name, _, _, is_stage in MENU if not is_stage]

    assert stages == ["Find", "Set up", "Assess", "Decide", "Apply", "Track"]
    assert support == ["Analyse", "Accounts", "System"]


def test_review_and_status_have_no_menu_entry() -> None:
    """They are not things to invoke. QUEUE IS `review`; the pane view as a
    whole IS `status`. Two commands turn out to be the interface rather than
    items in it."""
    from vanguard.panes import MENU

    commands = {command for _, _, actions, _ in MENU
                for _key, command, _hint in actions}
    assert "review" not in commands
    assert "status" not in commands


def test_every_action_names_a_real_command() -> None:
    from vanguard.panes import MENU

    for name, hint, actions, _is_stage in MENU:
        assert hint, f"{name} does not say what it is for"
        assert actions, f"{name} offers nothing"
        for key, command, action_hint in actions:
            assert len(key) == 1, f"{name}/{command}: {key!r} is not one key"
            assert command in main.commands, f"{name}: {command}"
            assert action_hint


def test_action_keys_are_unique_within_a_stage() -> None:
    """Across stages they may repeat — that is the point of the strict
    rule."""
    from vanguard.panes import MENU

    for name, _hint, actions, _is_stage in MENU:
        keys = [key for key, _, _ in actions]
        assert len(keys) == len(set(keys)), f"{name} reuses a key"


def test_every_command_is_reachable_from_some_stage() -> None:
    """A command in no stage is a command the menu cannot reach."""
    from vanguard.panes import MENU

    placed = {command for _, _, actions, _ in MENU
              for _key, command, _hint in actions}

    # These are the interface itself, or reached from within another view.
    exempt = {"review", "status", "panes", "todo", "score", "mail", "dormant",
              "adverts", "board", "interview", "reclassify", "resolve",
              "responses", "search", "sql", "discover", "feedback"}

    missing = sorted(set(main.commands) - placed - exempt)
    assert not missing, f"no stage offers {missing}"


# --- the strict key rule ---------------------------------------------------

def test_a_key_belongs_to_one_stage() -> None:
    """`r` runs on Find and does NOTHING on Track.

    The alternative — reserving a couple of keys globally so `run` and `poll`
    are always one keystroke — means a key does different things depending on
    where you are. Pressing `r` on Decide meaning `reject` would start a run.
    """
    from vanguard.panes import action_for_key

    assert action_for_key("Find", "r") == "run"
    assert action_for_key("Track", "r") == ""
    assert action_for_key("Track", "m") == "poll"
    assert action_for_key("Find", "m") == ""


def test_an_unknown_stage_offers_nothing() -> None:
    from vanguard.panes import action_for_key, actions_for

    assert actions_for("Nonesuch") == ()
    assert action_for_key("Nonesuch", "r") == ""


def test_the_dangerous_keys_run_through_their_command() -> None:
    """`approve`, `reject` and `dispatch` are in INTERACTIVE, so a keystroke
    suspends the panes and runs the command — with the confirmation the
    operator would see at the CLI. No keystroke silently changes a state."""
    from vanguard.panes import INTERACTIVE, action_for_key

    for stage, key in (("Decide", "a"), ("Decide", "x"), ("Apply", "z")):
        command = action_for_key(stage, key)
        assert command, f"{stage}/{key} maps to nothing"
        assert command in INTERACTIVE, (
            f"{command} would run captured, without its confirmation")


# --- the queue shows every state -------------------------------------------

def test_the_queue_shows_every_state(populated: str) -> None:
    """Filtering it by the selected stage would be convenient and wrong:
    deciding whether something is worth applying to needs the overview."""
    from vanguard.panes import queue_rows

    everything = queue_rows("", db=populated)
    pending = queue_rows("PENDING", db=populated)
    assert len(everything) > len(pending)


def test_a_row_carries_its_state(populated: str) -> None:
    """QUEUE mixes states, so a FLAGGED record must be distinguishable from
    an unscored PENDING one."""
    from vanguard.panes import queue_rows

    labels = [label for _id, label in queue_rows("", db=populated)]
    assert any("PENDING" in label for label in labels)
    assert any("DISPATCHED" in label for label in labels)


# --- the console -----------------------------------------------------------

def test_the_console_grows_only_when_used() -> None:
    """Always visible so nobody has to discover it exists — the first version
    hid a command bar behind a keybinding that never fired, leaving nothing
    on screen to diagnose. And small when idle, so it does not cost a third
    of a short terminal while empty."""
    from vanguard.tui import CONSOLE_IDLE, CONSOLE_OPEN, console_height

    assert console_height(False) == CONSOLE_IDLE
    assert console_height(True) == CONSOLE_OPEN
    assert CONSOLE_OPEN > CONSOLE_IDLE
    assert CONSOLE_IDLE >= 3, "too short to show a prompt and a line"


def test_queue_rows_are_addressable(populated: str) -> None:
    """A list a cursor moves through needs to know which row is which."""
    from vanguard.panes import queue_rows

    rows = queue_rows("PENDING", db=populated)
    assert rows
    for vacancy_id, label in rows:
        assert vacancy_id.startswith("reed:")
        assert label.strip()


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


# ---------------------------------------------------------------------------
# The regions are labelled, and the menu is grouped
#
# The console had no border title while every other region had one, and the
# menu drew nine identical rows — `is_stage` was read and then discarded, so
# nothing showed that the first six are a sequence and the last three are
# not.
# ---------------------------------------------------------------------------

def test_the_two_groups_partition_the_menu() -> None:
    """Every entry is in exactly one group. A menu entry in neither would be
    invisible; in both, selectable twice."""
    from vanguard.panes import MENU

    stages = [e for e in MENU if e[3]]
    support = [e for e in MENU if not e[3]]

    assert len(stages) + len(support) == len(MENU)
    assert {e[0] for e in stages} & {e[0] for e in support} == set()




# ---------------------------------------------------------------------------
# What the blank screen cost
#
# Two cosmetic changes — a border title on the console, and splitting the menu
# into two lists with a rule between them — left `vanguard panes` displaying
# NOTHING. No error, no partial layout, nothing to diagnose from.
#
# Rolled back on 23 Aug 2026. The grouping is not worth a layout that does not
# render, and the two groups are shown by a leading marker instead.
#
# The lesson is not about Textual. It is that a change to a layer the build
# environment cannot execute must be small enough to attribute — two changes
# in one edit, and neither could be ruled out.
# ---------------------------------------------------------------------------

def test_the_menu_is_one_list() -> None:
    """Splitting it into two ListViews with a rule between them rendered
    nothing. The groups are shown by a marker on the row instead."""
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    compose = source[source.index("def compose("):source.index("def on_mount(")]

    assert compose.count("ListView(") == 1, (
        "the menu is one list — two rendered nothing")
    assert "self.support" not in source


def test_the_console_is_an_inline_container() -> None:
    """A pre-built widget used as a context manager rendered nothing."""
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert 'with Vertical(id="console")' in source
    assert "with self.console:" not in source


def test_the_menu_marks_its_two_groups() -> None:
    """The grouping survives the rollback, as a marker rather than a rule."""
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "is_stage else" in source, (
        "is_stage is read and discarded again — nothing distinguishes the "
        "six pipeline stages from the three support groups")


# ---------------------------------------------------------------------------
# The console and the stage keys
#
# Three faults with one cause. The console was four rows: two for its border,
# one for the hint, leaving one — and a Textual Input needs three. So the
# operator typed into a widget that was never drawn.
#
# And a key fired its command bare. `search` wants keywords, `paste` a file,
# `discover` a board — only `run` happened to work without any, which is why
# only `run` appeared to.
# ---------------------------------------------------------------------------

def test_the_console_fits_an_input() -> None:
    """Border, hint and a three-row Input. Four rows squeezed the Input out
    of the layout entirely."""
    from vanguard.tui import CONSOLE_IDLE

    assert CONSOLE_IDLE >= 7, (
        f"{CONSOLE_IDLE} rows: 2 border + 1 hint + 3 Input needs 6 minimum, "
        "and one spare line makes it usable")


def test_the_input_has_room_in_the_css() -> None:
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    css = source[source.index('CSS = """'):source.index('"""', source.index('CSS = """') + 10)]
    bar = css.split("#bar")[1].split("}")[0]
    assert "height: 3" in bar, "an Input needs three rows — border, text, border"


def test_the_return_prompt_is_only_for_failures() -> None:
    """It existed so output could be read before the panes covered it, and
    the console now shows what the command did. One keystroke buying
    nothing — except where the command failed, since an error nobody sees is
    worse than a pause."""
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    run = source[source.index("def run_in_terminal("):source.index("# -- enlarging")]

    assert "if failed:" in run
    assert run.index("if failed:") < run.index("[Enter] to return")


# ---------------------------------------------------------------------------
# A key opens a form
#
# Firing the command bare failed — `search` wants keywords, `paste` a file,
# `discover` a board. Prefilling the console fixed that and still left the
# operator typing syntax, and an option nobody looks up is an option nobody
# uses.
# ---------------------------------------------------------------------------

def test_a_key_opens_a_form() -> None:
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    on_key = source[source.index("def on_key("):source.index("def on_list_view_highlighted(")]

    assert "_open_form" in on_key
    assert "self.bar.value = command" not in on_key, (
        "a key opens a form; it no longer prefills the console")


def test_every_stage_action_has_a_form() -> None:
    """A key that opens nothing is worse than a key that does nothing."""
    from vanguard.forms import form_for
    from vanguard.panes import MENU

    for name, _hint, actions, _is_stage in MENU:
        for _key, command, _action_hint in actions:
            assert form_for(command) is not None, f"{name}/{command}"


def test_form_widgets_are_removed_not_hidden() -> None:
    """A hidden input still takes Tab and still holds a value, so the next
    form would open with the last one's answers underneath it."""
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    close = source[source.index("def _close_form("):source.index("def _open_form(")]

    assert ".remove()" in close
    assert "display = False" not in close


def test_escape_closes_a_form_before_restoring() -> None:
    """Escape is what people press to get out of the thing in front of them,
    which is the form, not the layout."""
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    cancel = source[source.index("def action_cancel("):source.index("def action_restore(")]

    assert "_close_form" in cancel
    assert cancel.index("_close_form") < cancel.index("action_restore")


def test_needs_argument_is_gone() -> None:
    """It restated what each command needs. The schema reads that from the
    command, so restating it could only drift."""
    from pathlib import Path

    import vanguard.tui as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "NEEDS_ARGUMENT: dict" not in source
