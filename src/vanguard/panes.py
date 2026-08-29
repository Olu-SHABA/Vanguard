"""
Pane content — windows onto the commands, not a second implementation.

The risk in adding a second interface is not the building. It is the
DRIFTING: a filter added to `vanguard review` and forgotten on the queue
pane, and six weeks later the two disagree and nobody knows which to trust.

So no pane computes anything. Each one runs the command it corresponds to and
shows what comes back. Adding an option to a command gives the pane that
option for free, because the pane is not doing the work — it is displaying
it.

The cost is that panes look like command output rather than bespoke widgets.
That is the trade: slightly less polished, and unable to be wrong.

## Why this module is separate from the Textual app

Everything here is plain text in, plain text out, so it can be tested without
a terminal, a display, or Textual installed. The app is a shell around it.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field

__all__ = ["Pane", "PANES", "render", "pane_named"]


@dataclass(frozen=True)
class Pane:
    """One region of the screen, and the command behind it."""

    key: str
    title: str
    command: str
    args: tuple[str, ...] = ()
    #: What this pane is for, shown in the menu.
    hint: str = ""
    #: The command to run in a terminal for the full version. Shown so the
    #: operator can drop out to the CLI when a pane is too small — long
    #: output belongs somewhere scrollable and searchable.
    full: str = ""

    def invocation(self) -> str:
        return " ".join(("vanguard", self.command, *self.args))


#: The four regions of the sketch, plus the ones reached from the menu.
#:
#: INPUT is not here: adding a vacancy is an action, and the first version is
#: read-only. The pane names the commands instead.
PANES: tuple[Pane, ...] = (
    Pane("s", "STATUS", "status",
         hint="where everything is",
         full="vanguard status"),
    Pane("q", "QUEUE", "review", ("--status", "PENDING", "--limit", "20"),
         hint="what is waiting to be reviewed",
         full="vanguard review --status PENDING --limit 0"),
    Pane("f", "FLAGGED", "review", ("--status", "FLAGGED", "--limit", "20"),
         hint="what could not be measured",
         full="vanguard review --status FLAGGED --limit 0"),
    Pane("t", "WAITING ON YOU", "todo",
         hint="approved and pending, with next steps",
         full="vanguard todo"),
    Pane("r", "RESPONSES", "responses", ("--limit", "20"),
         hint="what employers sent back",
         full="vanguard responses --limit 0"),
    Pane("i", "INTERVIEWS", "interviews",
         hint="active processes and their rounds",
         full="vanguard interviews"),
    Pane("p", "PROGRESS", "funnel",
         hint="how far applications get, and where they stop",
         full="vanguard funnel --reasons"),
    Pane("g", "GAPS", "stats",
         hint="coverage distribution and recurring gaps",
         full="vanguard stats"),
    Pane("b", "BOARDS", "boards",
         hint="which sources are read, and how",
         full="vanguard boards"),
)


def pane_named(key: str) -> Pane | None:
    return next((p for p in PANES if p.key == key), None)


def render(pane: Pane, *, db: str = "", width: int = 80,
           extra: tuple[str, ...] = ()) -> str:
    """Run the pane's command and return what it printed.

    Failures are returned as text rather than raised. A pane that cannot
    render should say why in its own frame — a traceback taking down the
    whole screen because one command had no database is a worse outcome than
    one pane reading "no store yet".
    """
    from click.testing import CliRunner

    from vanguard.cli import main

    # The width the PANE has, not the terminal's. `--width` is a global
    # option on the group, so it comes before the subcommand.
    args = ["--width", str(max(40, width)), pane.command, *pane.args, *extra]
    if db and _accepts_db(pane.command):
        args += ["--db", db]

    previous = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(max(40, width))

    try:
        result = CliRunner().invoke(main, args, catch_exceptions=True)
        text = result.output or ""
        if result.exception is not None and not text.strip():
            text = f"({pane.command} failed: {result.exception})"
        return text.rstrip() or "(nothing to show)"
    except Exception as exc:                       # pragma: no cover - defensive
        return f"({pane.command} could not run: {exc})"
    finally:
        if previous is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous


def _accepts_db(command: str) -> bool:
    """Does this command take `--db`?

    Asked rather than assumed: passing `--db` to a command that does not take
    it fails the whole pane, and `boards` is one such.
    """
    import click

    from vanguard.cli import main

    target = main.commands.get(command)
    if target is None:
        return False
    return any(isinstance(p, click.Option) and p.opts[0] == "--db"
               for p in target.params)
