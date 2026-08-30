"""
Form schemas, derived from the commands.

INPUT was a label. It said a key existed and left the operator to type the
syntax into a console — so `search` meant remembering that six hours is
`--within 6h`, and an option nobody looks up is an option nobody uses.

A form fixes that: every option visible, its default already chosen, and
validation before anything runs.

## Derived, not hand-written

The obvious approach is to write a form per command. It is also the drift
problem again — add an option to `search` and the form does not know.

Click already declares every option's type, choices, default and help. This
reads them. A new option appears in the form the moment it exists, and one
removed disappears, because there is nothing to keep in step.

## What it cannot derive

Two things, held in `HINTS` below:

  * whether a field matters enough to show first — click knows a command has
    eight options, not that two of them are the ones anyone sets;
  * a human label. `job_type` is a Python identifier; "Contract type" is what
    a person reads.

Both are presentation. Neither changes what the command accepts, so neither
can make the form disagree with the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Field", "Form", "form_for", "FORMS", "HINTS"]


@dataclass(frozen=True)
class Field:
    """One thing to fill in.

    `kind` is what to draw: `text`, `choice`, `flag`, or `path`.
    """

    name: str
    label: str
    kind: str
    default: str = ""
    choices: tuple[str, ...] = ()
    help: str = ""
    required: bool = False
    multiple: bool = False
    #: The option as the CLI spells it — `--within`. Empty for a positional
    #: argument, which is appended bare.
    option: str = ""

    def as_arguments(self, value: str) -> list[str]:
        """This field's contribution to a command line.

        An empty value contributes NOTHING, rather than an empty string: a
        bare `--location ""` is not the same as omitting it, and several
        commands treat the two differently.
        """
        value = (value or "").strip()
        if not value:
            return []
        if self.kind == "flag":
            return [self.option] if value.lower() in ("y", "yes", "true", "on") else []
        if not self.option:
            return value.split()
        return [self.option, value]


@dataclass(frozen=True)
class Form:
    """A command and the fields it takes."""

    command: str
    title: str
    fields: tuple[Field, ...] = ()
    note: str = ""

    def command_line(self, values: dict[str, str]) -> list[str]:
        """The command and its arguments, ready to run.

        Positional arguments come first, in declaration order, because that
        is where the CLI expects them.
        """
        positional: list[str] = []
        options: list[str] = []
        for item in self.fields:
            part = item.as_arguments(values.get(item.name, ""))
            (positional if not item.option else options).extend(part)
        return [self.command, *positional, *options]

    def missing(self, values: dict[str, str]) -> list[str]:
        """Required fields left empty, by label.

        Checked before running rather than after, so an error arrives while
        the operator is still looking at the form.
        """
        return [item.label for item in self.fields
                if item.required and not (values.get(item.name) or "").strip()]


#: Presentation only: which fields lead, and what to call them.
#:
#: Click knows a command has eight options. It does not know that two of them
#: are the ones anyone sets, or that `job_type` reads better as "Contract
#: type". Neither changes what the command accepts.
HINTS: dict[str, dict] = {
    "search": {
        "title": "Search a board",
        "order": ["keywords", "location", "window", "remote", "experience",
                  "job_type", "board_ids", "sort"],
        "required": ["keywords"],
        "labels": {
            "keywords": "Keywords",
            "location": "Location",
            "window": "Posted within",
            "remote": "Arrangement",
            "experience": "Seniority",
            "job_type": "Contract type",
            "board_ids": "Boards",
            "sort": "Order by",
        },
        "note": "Builds links to open in a browser. Nothing is fetched.",
    },
    "paste": {
        "title": "Add one advert by hand",
        "order": ["path", "url", "employer", "title", "board", "vacancy_id"],
        "required": ["path"],
        "labels": {
            "path": "Advert file",
            "url": "Vacancy URL",
            "employer": "Employer",
            "title": "Job title",
            "board": "Attribute to",
            "vacancy_id": "Fill in a discovered record",
        },
        "note": "Employer and title are read from the advert where it says them.",
    },
    "discover": {
        "title": "List vacancies without scoring them",
        "order": ["only_boards", "title", "location", "list_only"],
        "labels": {
            "only_boards": "Boards",
            "title": "Keywords",
            "location": "Location",
            "list_only": "Show what is awaiting text",
        },
        "note": "Records employer, title and URL. You paste the advert.",
    },
    "run": {
        "title": "Fetch and score",
        "order": ["only_boards", "skip_boards", "title", "location", "no_model"],
        "labels": {
            "only_boards": "Only these boards",
            "skip_boards": "Skip these boards",
            "title": "Override keywords",
            "location": "Override location",
            "no_model": "Lexical fallback only",
        },
    },
    "poll": {
        "title": "Read the mailbox",
        "order": ["since_days", "category", "strategy_name", "show_uncorrelated"],
        "labels": {
            "since_days": "Look back (days)",
            "category": "Gmail tab",
            "strategy_name": "Search strategy",
            "show_uncorrelated": "Show unmatched mail",
        },
    },
    "review": {
        "title": "Look at the queue",
        "order": ["status", "order", "limit"],
        "labels": {
            "status": "State",
            "order": "Order by",
            "limit": "How many (0 for all)",
        },
    },
}

#: Options every command carries that nobody fills in from a form.
_PLUMBING = frozenset({
    "db", "boards", "boards_path", "cv", "aliases", "archive_root",
    "help", "width", "no_colour", "no_color", "theme",
})


def form_for(command: str) -> Form | None:
    """Build a form from the command's own declared options.

    Returns None where the command is unknown. A command with no hints still
    produces a form — every option, in declaration order, labelled from its
    identifier — because a rough form beats none.
    """
    import click

    from vanguard.cli import main

    target = main.commands.get(command)
    if target is None:
        return None

    hints = HINTS.get(command, {})
    labels = hints.get("labels", {})
    required = set(hints.get("required", []))
    order = hints.get("order", [])

    found: dict[str, Field] = {}

    for param in target.params:
        name = param.name
        if not name or name in _PLUMBING:
            continue

        option = ""
        if isinstance(param, click.Option):
            option = param.opts[0]
            if option in ("--help",):
                continue

        choices = tuple(getattr(param.type, "choices", ()) or ())
        is_flag = bool(getattr(param, "is_flag", False))

        default = param.default
        if default is None or repr(default).startswith("Sentinel"):
            default = ""

        found[name] = Field(
            name=name,
            label=labels.get(name) or name.replace("_", " ").capitalize(),
            kind="flag" if is_flag else ("choice" if choices else (
                "path" if "file" in name or name == "path" else "text")),
            default="" if is_flag else str(default),
            choices=choices,
            help=(param.help or "") if isinstance(param, click.Option) else "",
            required=name in required,
            multiple=bool(getattr(param, "multiple", False)),
            option=option,
        )

    # Hinted fields first, in the order given; anything else after, so a new
    # option appears without needing a hint.
    ordered = [found[n] for n in order if n in found]
    ordered += [f for n, f in found.items() if n not in order]

    return Form(
        command=command,
        title=hints.get("title") or f"vanguard {command}",
        fields=tuple(ordered),
        note=hints.get("note", ""),
    )


#: Commands INPUT offers a form for.
FORMS: tuple[str, ...] = tuple(HINTS)
