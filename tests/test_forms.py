"""Form schemas, derived from the commands."""
from __future__ import annotations

import click
import pytest

from vanguard.cli import main
from vanguard.forms import FORMS, HINTS, Field, form_for


# --- derived, not hand-written ---------------------------------------------

def test_a_form_is_built_from_the_command() -> None:
    """Hand-writing a form per command is the drift problem again: add an
    option to `search` and the form does not know.

    Click already declares every option's type, choices, default and help.
    This reads them, so a new option appears the moment it exists.
    """
    form = form_for("search")
    assert form is not None

    declared = {p.name for p in main.commands["search"].params
                if p.name and p.name != "help"}
    in_form = {f.name for f in form.fields}

    assert in_form <= declared, "the form invented a field the command lacks"
    assert "keywords" in in_form
    assert "window" in in_form


def test_choices_come_from_the_command() -> None:
    """`--within` takes eight values. Nobody should have to remember them,
    and nobody should have to restate them here."""
    window = next(f for f in form_for("search").fields if f.name == "window")
    assert window.kind == "choice"
    assert "6h" in window.choices and "1w" in window.choices
    assert window.default == "24h"


def test_defaults_come_from_the_command() -> None:
    sort = next(f for f in form_for("search").fields if f.name == "sort")
    assert sort.default == "date"


def test_plumbing_is_left_out() -> None:
    """`--db`, `--cv`, `--boards` are on almost every command and nobody
    fills them in from a form."""
    for command in FORMS:
        names = {f.name for f in form_for(command).fields}
        assert not (names & {"db", "cv", "aliases", "boards", "boards_path"}), (
            f"{command} offers plumbing")


def test_an_unknown_command_has_no_form() -> None:
    assert form_for("nonesuch") is None


def test_a_command_without_hints_still_gets_a_form() -> None:
    """A rough form beats none: every option, in declaration order, labelled
    from its identifier."""
    form = form_for("stats")
    assert form is not None
    assert form.title


# --- building the command line ---------------------------------------------

def test_a_filled_form_produces_a_valid_command_line() -> None:
    form = form_for("search")
    line = form.command_line({
        "keywords": "data scientist",
        "location": "Bristol",
        "window": "6h",
        "remote": "remote",
        "experience": "senior",
    })
    assert line[0] == "search"
    assert "data" in line and "scientist" in line
    assert "--within" in line and "6h" in line
    assert "--level" in line and "senior" in line


def test_the_command_line_actually_runs() -> None:
    """The point of deriving the schema: what the form builds must be
    something the CLI accepts."""
    from click.testing import CliRunner

    form = form_for("search")
    line = form.command_line({"keywords": "data scientist", "window": "24h"})

    result = CliRunner().invoke(main, line)
    assert result.exit_code == 0, result.output


def test_an_empty_field_contributes_nothing() -> None:
    """A bare `--location ""` is not the same as omitting it, and several
    commands treat the two differently."""
    line = form_for("search").command_line({"keywords": "x", "location": ""})
    assert "--location" not in line


def test_positional_arguments_come_first() -> None:
    """Where the CLI expects them."""
    line = form_for("search").command_line({
        "keywords": "data scientist", "location": "Bristol"})
    assert line.index("data") < line.index("--location")


def test_a_flag_is_only_passed_when_set() -> None:
    field = Field(name="x", label="X", kind="flag", option="--dry-run")
    assert field.as_arguments("") == []
    assert field.as_arguments("no") == []
    assert field.as_arguments("yes") == ["--dry-run"]


# --- validation -------------------------------------------------------------

def test_required_fields_are_reported_before_running() -> None:
    """An error while the operator is still looking at the form beats one
    after the command has been dispatched."""
    form = form_for("search")
    assert form.missing({}) == ["Keywords"]
    assert form.missing({"keywords": "data scientist"}) == []


def test_whitespace_is_not_a_value() -> None:
    assert form_for("search").missing({"keywords": "   "}) == ["Keywords"]


@pytest.mark.parametrize("command", list(FORMS))
def test_every_hinted_command_exists(command: str) -> None:
    assert command in main.commands


@pytest.mark.parametrize("command", list(FORMS))
def test_hinted_fields_exist_on_the_command(command: str) -> None:
    """A hint naming a field the command does not have would order or label
    nothing, silently."""
    hints = HINTS[command]
    declared = {p.name for p in main.commands[command].params if p.name}

    for name in hints.get("order", []):
        assert name in declared, f"{command}: no field {name!r}"
    for name in hints.get("labels", {}):
        assert name in declared, f"{command}: no field {name!r} to label"
    for name in hints.get("required", []):
        assert name in declared, f"{command}: no field {name!r} to require"


@pytest.mark.parametrize("command", list(FORMS))
def test_every_field_is_labelled_and_drawable(command: str) -> None:
    for item in form_for(command).fields:
        assert item.label, f"{command}/{item.name} has no label"
        assert item.kind in ("text", "choice", "flag", "path"), (
            f"{command}/{item.name}: {item.kind} cannot be drawn")
        if item.kind == "choice":
            assert item.choices, f"{command}/{item.name} is a choice of nothing"
