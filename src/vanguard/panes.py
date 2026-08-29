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
from collections.abc import Sequence
from dataclasses import dataclass, field

__all__ = ["Pane", "PANES", "MENU", "ACTIONS", "render", "render_command",
           "record_detail", "pane_named", "INTERACTIVE", "AFTER",
           "queue_rows"]


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


#: The menu, in the order it is shown.
#:
#: Nine views were reachable only by knowing their command name, which is the
#: problem a pane view exists to solve. A menu is not decoration here.
MENU: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Queue",     "what is waiting to be reviewed",
     ("review", "--status", "PENDING", "--limit", "30")),
    ("Flagged",   "what could not be measured",
     ("review", "--status", "FLAGGED", "--limit", "30")),
    ("Dispatched", "applications sent",
     ("review", "--status", "DISPATCHED", "--limit", "30")),
    ("Replies",   "what employers sent back",
     ("responses", "--limit", "30")),
    ("Interviews", "active processes and their rounds",
     ("interviews",)),
    ("Progress",  "how far applications get",
     ("funnel",)),
    ("Gaps",      "coverage and recurring gaps",
     ("stats",)),
    ("Boards",    "which sources are read",
     ("boards",)),
    ("Awaiting",  "discovered, needing their advert text",
     ("discover", "--list")),
)

#: The INPUT region. Four things an operator actually starts with.
#:
#: The first version had no input region at all — `status` sat where the
#: sketch said INPUT, which removed the one section that gave the layout a
#: purpose.
ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("r", "run",    "fetch and score from the enabled boards"),
    ("s", "search", "build search links to open in a browser"),
    ("p", "paste",  "add one advert by hand"),
    ("o", "poll",   "read the mailbox for replies"),
)


def record_detail(vacancy_id: str, *, db: str = "", width: int = 80) -> str:
    """One vacancy, in full: what it scored, and what it did not match.

    The RESULT region of the sketch. A list of queue rows says a vacancy
    scored 0.62; this says which seven terms it missed, which is the part
    that decides whether to apply.

    Built from the store rather than from a command, because no command
    shows exactly this — and a pane that has to run three commands and
    stitch them together would be doing the work it is meant to delegate.
    """
    from vanguard.store import Store

    if not vacancy_id:
        return "(select a row to see its record)"

    try:
        store = Store(db) if db else Store()
        vacancy = store.vacancy(vacancy_id)
    except Exception as exc:
        return f"(could not read {vacancy_id}: {exc})"

    if vacancy is None:
        return f"(no record for {vacancy_id})"

    lines = [
        f"{vacancy['employer'] or '(unknown)'}  ·  {vacancy['title'] or ''}",
    ]
    if vacancy["location"] or vacancy["salary_band"]:
        lines.append("  ".join(
            x for x in (vacancy["location"], vacancy["salary_band"]) if x))

    score = store.latest_score(vacancy_id)
    if score is None:
        lines += ["", "not scored"]
    else:
        coverage = score["coverage"]
        matched, total = score["terms_matched"], score["terms_total"]
        lines += [
            "",
            f"coverage {coverage:.2f}   {matched} of {total} terms"
            if coverage is not None else "coverage not measured",
        ]

    gaps = [g for g in store.gaps_for(vacancy_id) if g["outcome"] != "HIT"]
    if gaps:
        unmet = [g["term"] for g in gaps][:14]
        lines += ["", "unmet:"]
        for line in _wrap_terms(unmet, width - 4):
            lines.append(f"  {line}")

        excluded = [g for g in gaps if g["exclusion"]]
        if excluded:
            lines += ["", f"{len(excluded)} blocked by the alias table — "
                          "no CV edit permitted"]

    if vacancy["url"]:
        lines += ["", vacancy["url"]]

    return "\n".join(lines)


def _wrap_terms(terms: list[str], width: int) -> list[str]:
    """Terms packed onto as few lines as fit, comma-separated.

    A requirement term is not always a word. Extraction produces whole
    competency phrases — "working with data users to understand and translate
    their needs into technical requirements" — and one of those is wider than
    any pane. Each is clipped to fit before packing, so a long phrase costs a
    line rather than the layout.
    """
    limit = max(20, width)
    clipped = [t if len(t) <= limit else t[:limit - 1].rstrip() + "…"
               for t in terms]

    out: list[str] = []
    current = ""
    for term in clipped:
        candidate = f"{current}, {term}" if current else term
        if len(candidate) > limit:
            if current:
                out.append(current)
            current = term
        else:
            current = candidate
    if current:
        out.append(current)
    return out


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


#: Commands that do not work captured into a pane.
#:
#: `run` streams progress for minutes; `session` and `resolve` ask questions;
#: `poll` does both. Capturing their output means the operator sees nothing
#: until it finishes, and a prompt they cannot answer hangs the pane.
#:
#: Named rather than discovered, because the failure is silent — a hung pane
#: looks like a slow one.
INTERACTIVE: frozenset[str] = frozenset({
    "run", "session", "resolve", "poll", "interview", "adverts", "discover",
    "evidence", "dispatch", "apply",
})

#: What to show in the pane once one of those returns.
#:
#: Their own output goes to the terminal and is gone. Each leaves a record
#: somewhere, and this names where — otherwise the operator runs something,
#: comes back, and cannot tell what it did.
AFTER: dict[str, tuple[str, ...]] = {
    "run": ("logs", "--limit", "3"),
    "poll": ("responses", "--limit", "20"),
    "session": ("todo",),
    "adverts": ("review", "--status", "PENDING", "--limit", "20"),
    "discover": ("discover", "--list"),
    "dispatch": ("review", "--status", "DISPATCHED", "--limit", "20"),
    "apply": ("todo",),
    "resolve": ("review", "--status", "FLAGGED", "--limit", "20"),
    "evidence": ("stats",),
    "interview": ("interviews",),
}


def render_command(words: Sequence[str], *, db: str = "",
                   width: int = 80) -> str:
    """Run an arbitrary command and return what it printed.

    The command bar behind `:` in the pane view. Anything the CLI accepts
    works, including options — it IS the CLI, invoked in-process.

    A command that needs a terminal is refused with the reason rather than
    hanging the pane on a prompt nobody can see.
    """
    from click.testing import CliRunner

    from vanguard.cli import main

    if not words:
        return "(nothing to run)"

    name = words[0]
    if name not in main.commands:
        close = [c for c in main.commands if c.startswith(name[:3])]
        suggestion = f"  did you mean: {', '.join(sorted(close)[:4])}" if close else ""
        return f"no command {name!r}\n{suggestion}"

    if name in INTERACTIVE:
        # The pane view runs these in a suspended terminal rather than
        # capturing them. This message is only reached when `render_command`
        # is called outside the pane view.
        return (f"`{name}` streams output or asks questions, so it needs a "
                f"terminal.\n\n    vanguard {' '.join(words)}\n")

    args = ["--width", str(max(40, width)), *words]
    if db and _accepts_db(name) and "--db" not in words:
        args += ["--db", db]

    try:
        result = CliRunner().invoke(main, args, catch_exceptions=True)
        text = (result.output or "").rstrip()
        if result.exception is not None and not text.strip():
            text = f"({name} failed: {result.exception})"
        return text or "(no output)"
    except Exception as exc:                       # pragma: no cover - defensive
        return f"({name} could not run: {exc})"


def queue_rows(status: str = "PENDING", *, db: str = "",
               limit: int = 60) -> list[tuple[str, str]]:
    """`(vacancy_id, label)` for a selectable list.

    The queue as DATA rather than as formatted output, because a pane the
    cursor moves through needs to know which row is which. Everything else
    still goes through the commands.
    """
    from vanguard.store import Store

    try:
        store = Store(db) if db else Store()
        rows = store.list_queue(status, limit=limit, order="date")
    except Exception:
        return []

    out: list[tuple[str, str]] = []
    for row in rows:
        coverage = row["coverage"] if "coverage" in row.keys() else None
        shown = f"{coverage:.2f}" if isinstance(coverage, float) else "  —  "
        employer = (row["employer"] or "")[:22]
        title = (row["title"] or "")[:26]
        out.append((row["vacancy_id"], f"{shown}  {employer:<22}  {title}"))
    return out


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
