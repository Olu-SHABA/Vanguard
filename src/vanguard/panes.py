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

__all__ = ["MENU", "render_command", "record_detail", "queue_rows",
           "INTERACTIVE", "AFTER", "actions_for", "action_for_key",
           "stage_named"]


# REMOVED 23 Aug 2026: the `PANES` tuple.
#
# It listed nine fixed regions, each bound to a command, from the version
# that had no menu. `MENU` supersedes it: the regions are now fixed and the
# CONTENT changes with the selected stage, which is the opposite arrangement.
#
# `Pane`, `render` and `pane_named` went with it. Nothing referenced them
# once the layout was rebuilt.

#: The menu: six pipeline stages, then three reachable any time.
#:
#: `(name, hint, actions, is_stage)` where `actions` are the keys INPUT
#: offers on that stage.
#:
#: **A key belongs to the stage that owns it, and nowhere else.** `r` runs on
#: Find and does nothing on Track. The alternative — reserving `r` and `o`
#: globally — means a key does different things depending on where you are,
#: and pressing `r` on Decide meaning `reject` would start a run.
#:
#: `review` and `status` are absent, and deliberately: they are not things to
#: invoke. QUEUE **is** `review`, and the pane view as a whole **is**
#: `status`. Two of the commands turn out to be the interface rather than
#: items in it.
MENU: tuple[tuple[str, str, tuple[tuple[str, str, str], ...], bool], ...] = (
    ("Find", "get vacancies in", (
        ("r", "run", "fetch and score from the enabled boards"),
        ("s", "search", "build search links to open in a browser"),
        ("p", "paste", "add one advert by hand"),
        ("d", "discover", "list vacancies without scoring them"),
    ), True),
    ("Set up", "boards and health", (
        ("b", "boards", "the registry and its health"),
        ("g", "diagnose", "why adverts failed to parse"),
    ), True),
    ("Assess", "fix what could not be measured", (
        ("v", "resolve", "work through FLAGGED records"),
        ("c", "rescore", "re-score against the current CV"),
        ("e", "evidence", "recover unstated experience from a repository"),
    ), True),
    ("Decide", "worth applying to?", (
        ("n", "session", "walk the queue, one at a time"),
        ("a", "approve", "approve the selected record"),
        ("x", "reject", "reject the selected record"),
        ("o", "override", "force a state, with a reason"),
    ), True),
    ("Apply", "write it and send it", (
        ("w", "draft", "a cover letter for the selected record"),
        ("y", "apply", "what this application needs, and where"),
        ("z", "dispatch", "archive it as sent"),
    ), True),
    ("Track", "what came back", (
        ("m", "poll", "read the mailbox for replies"),
        ("k", "responses", "what employers sent back"),
        ("f", "feedback", "draft a feedback request after a decline"),
        ("i", "interviews", "active processes and their rounds"),
    ), True),
    ("Analyse", "how is this going", (
        ("t", "stats", "coverage distribution and recurring gaps"),
        ("u", "funnel", "how far applications get"),
        ("q", "sql", "query the store, read-only"),
    ), False),
    ("Accounts", "where you hold accounts", (
        ("j", "registrations", "board and employer accounts"),
    ), False),
    ("System", "logs and housekeeping", (
        ("l", "logs", "what every run did"),
        ("h", "archive", "move old records out"),
    ), False),
)


def stage_named(name: str):
    return next((entry for entry in MENU if entry[0] == name), None)


def actions_for(name: str) -> tuple[tuple[str, str, str], ...]:
    """The keys INPUT offers on this stage. Empty for an unknown name."""
    entry = stage_named(name)
    return entry[2] if entry else ()


def action_for_key(stage: str, key: str) -> str:
    """The command a key runs ON THIS STAGE, or nothing.

    The strict rule, in one function. A key that belongs to another stage
    returns nothing rather than that stage's command.
    """
    for candidate, command, _hint in actions_for(stage):
        if candidate == key:
            return command
    return ""


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
    # These CHANGE STATE and confirm before they do.
    #
    # Captured into a pane, the confirmation is invisible and unanswerable —
    # so a keystroke would either hang, or worse, act without the operator
    # seeing what they were agreeing to. Running them in a suspended terminal
    # means the confirmation an operator would see at the CLI is the one they
    # see here.
    "approve", "reject", "override", "feedback", "draft", "rescore",
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
    "approve": ("todo",),
    "reject": ("review", "--status", "REJECTED", "--limit", "20"),
    "override": ("logs", "--limit", "3"),
    "rescore": ("review", "--limit", "30"),
    "draft": ("todo",),
    "feedback": ("responses", "--status", "DECLINE"),
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


def queue_rows(status: str = "", *, db: str = "",
               limit: int = 200) -> list[tuple[str, str]]:
    """`(vacancy_id, label)` for a selectable list.

    The queue as DATA rather than as formatted output, because a pane the
    cursor moves through needs to know which row is which. Everything else
    still goes through the commands.

    An empty `status` means EVERY state, which is what the QUEUE region
    shows. Filtering it by the selected stage would be convenient and wrong:
    deciding whether something is worth applying to needs the overview, not a
    slice of it.
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
        employer = (row["employer"] or "")[:20]
        state = (row["status"] or "")[:11]
        # The state is on the row because QUEUE mixes them. Without it a
        # FLAGGED record is indistinguishable from an unscored PENDING one.
        out.append((row["vacancy_id"],
                    f"{shown}  {employer:<20}  {state}"))
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
