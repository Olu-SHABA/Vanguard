"""
The pane view — menu, four regions, and a record that follows the cursor.

## What the first version got wrong

It was a viewer. Five panes of command output, a hidden command bar, and no
menu — so nine views were reachable only by knowing their command name, which
is the problem a pane view exists to solve.

Worse, the region the sketch labelled INPUT held `status` instead. The one
section that gave the layout a purpose was missing.

## The four regions

    +- MENU ----+- INPUT ---------------------------------+
    | > Queue   |  [r]un  [s]earch  [p]aste  [o] poll     |
    |   Replies +-----------------------------------------+
    |   Progress|  RESULT - the record under the cursor   |
    |   Gaps    |  coverage, unmet terms, the link        |
    |           +------------------+----------------------+
    |           |  NEEDS DOING     |  PROGRESS            |
    |           |  the list        |  funnel              |
    +-----------+------------------+----------------------+

**RESULT follows the cursor.** Move through the list and the record appears
above it — the one thing a page of command output cannot do.

## Still read-only

Approving from the keyboard is the obvious next step and is deliberately not
here. Both defects the operator found were in the layout layer, which cannot
be tested from this sandbox: Textual is not installable here, so every line
below is written but unrun.

Adding a keystroke that dispatches an application to a UI whose focus
behaviour is unverified is how a mis-key becomes a wrong submission. Actions
land once the frame has been used and the focus behaviour is known.

## Everything else still runs through the commands

`panes.py` holds two exceptions, both deliberate: `record_detail` and
`queue_rows` read the store, because no command produces a
cursor-addressable list or a single record in this shape. Everything else
delegates.
"""

from __future__ import annotations

from vanguard.panes import (
    ACTIONS,
    AFTER,
    INTERACTIVE,
    MENU,
    queue_rows,
    record_detail,
    render_command,
)

__all__ = ["run_app", "TEXTUAL_MISSING", "status_of"]

TEXTUAL_MISSING = (
    "the pane view needs Textual:\n\n"
    "    pip install textual\n\n"
    "every command works without it — the panes are an extra way in, "
    "not a replacement"
)


def status_of(words) -> str:
    """The queue status a menu entry shows, or nothing.

    A view over the queue is SELECTABLE and drives the record pane. A funnel
    has nothing to select.
    """
    words = tuple(words)
    if not words or words[0] != "review":
        return ""
    for index, word in enumerate(words):
        if word == "--status" and index + 1 < len(words):
            return words[index + 1]
    return "PENDING"


def run_app(db: str) -> None:
    """Start the pane view. Raises `ImportError` when Textual is absent."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import (
        Footer, Header, Input, ListItem, ListView, Static,
    )

    class VanguardApp(App):
        TITLE = "Vanguard"

        CSS = """
        Screen { layout: horizontal; }
        #menu { width: 18; border-right: solid $primary; }
        #right { width: 1fr; }
        #input { height: 5; border: round $primary; padding: 0 1; }
        #result { height: 1fr; border: round $primary; padding: 0 1; }
        #lower { height: 1fr; }
        #list { width: 1fr; border: round $primary; padding: 0 1; }
        #progress { width: 1fr; border: round $primary; padding: 0 1; }
        #list:focus-within, #result:focus-within { border: round $accent; }
        #bar { dock: bottom; border: tall $accent; height: 3; }
        """

        # Function keys and Ctrl combinations only.
        #
        # A plain letter is swallowed the moment the command bar has focus,
        # and `:` and `!` are reported differently by different terminals — a
        # binding that silently does not fire leaves nothing on screen to
        # diagnose, which is what happened.
        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit"),
            Binding("ctrl+r", "refresh", "Refresh"),
            Binding("f1", "help", "Help"),
            Binding("f2", "full", "Enlarge"),
            Binding("f3", "shell", "Shell"),
            Binding("escape", "restore", "Restore", show=False),
        ]

        def __init__(self, db_path: str) -> None:
            super().__init__()
            self.db_path = db_path
            self.view = MENU[0]
            self.rows = []
            self.enlarged = None

        # -- layout ---------------------------------------------------------

        def compose(self) -> ComposeResult:
            yield Header()

            with Vertical(id="menu"):
                yield Static(" VIEW")
                self.menu = ListView(
                    *[ListItem(Static(f" {name}")) for name, _, _ in MENU])
                yield self.menu

            with Vertical(id="right"):
                self.input = Static(self._input_text(), id="input")
                self.input.border_title = "INPUT"
                yield self.input

                self.result = VerticalScroll(id="result")
                self.result.border_title = "RESULT"
                yield self.result

                with Horizontal(id="lower"):
                    self.listing = VerticalScroll(id="list")
                    self.listing.border_title = MENU[0][0].upper()
                    yield self.listing

                    self.progress = VerticalScroll(id="progress")
                    self.progress.border_title = "PROGRESS"
                    yield self.progress

            self.bar = Input(
                placeholder="type a command and press Enter — "
                            "e.g. review --status DISPATCHED, or run",
                id="bar")
            yield self.bar
            yield Footer()

        def on_mount(self) -> None:
            self.result_body = Static("(select a row)")
            self.result.mount(self.result_body)

            self.list_view = ListView()
            self.listing.mount(self.list_view)

            self.progress_body = Static("loading…")
            self.progress.mount(self.progress_body)

            self.action_refresh()

        # -- content --------------------------------------------------------

        def _input_text(self) -> str:
            actions = "   ".join(f"[{key}] {name}" for key, name, _ in ACTIONS)
            return (f"{actions}\n\n"
                    "type any command in the bar below — F1 for help")

        def _pane_width(self, widget) -> int:
            size = getattr(widget, "size", None)
            return max(40, (size.width - 4) if size and size.width else 70)

        def action_refresh(self) -> None:
            self._load_view(self.view)
            self.progress_body.update(
                render_command(["funnel"], db=self.db_path,
                               width=self._pane_width(self.progress)))

        def _load_view(self, entry) -> None:
            name, _hint, words = entry
            self.view = entry
            self.listing.border_title = name.upper()

            status = status_of(words)
            if status:
                self.rows = queue_rows(status, db=self.db_path)
                self.list_view.clear()
                for _vacancy_id, label in self.rows:
                    self.list_view.append(ListItem(Static(label)))
                if self.rows:
                    self.list_view.index = 0
                    self._show_record(0)
                else:
                    self.result_body.update(f"(nothing with status {status})")
            else:
                self.rows = []
                self.list_view.clear()
                self.result_body.update(
                    render_command(list(words), db=self.db_path,
                                   width=self._pane_width(self.result)))

        def _show_record(self, index: int) -> None:
            if not (0 <= index < len(self.rows)):
                return
            vacancy_id, _label = self.rows[index]
            self.result.border_title = f"RESULT  ·  {vacancy_id}"
            self.result_body.update(
                record_detail(vacancy_id, db=self.db_path,
                              width=self._pane_width(self.result)))

        # -- events ---------------------------------------------------------

        def on_list_view_highlighted(self, event) -> None:
            """The cursor moved. This is the point of the redesign: a row
            says a vacancy scored 0.62; the record says which seven terms it
            missed, which is what decides whether to apply."""
            if event.list_view is self.menu:
                index = event.list_view.index or 0
                if 0 <= index < len(MENU):
                    self._load_view(MENU[index])
            elif event.list_view is self.list_view:
                self._show_record(event.list_view.index or 0)

        def on_input_submitted(self, event) -> None:
            typed = (event.value or "").strip()
            self.bar.value = ""
            if not typed:
                return

            words = typed.split()
            if words[0] == "vanguard":
                words = words[1:]
            if not words:
                return

            if words[0] in INTERACTIVE:
                self.run_in_terminal(words)
                return

            self.result.border_title = f"RESULT  ·  {' '.join(words)}"
            self.result_body.update(
                render_command(words, db=self.db_path,
                               width=self._pane_width(self.result)))

        def on_key(self, event) -> None:
            """Single-key actions, ignored while the bar has focus.

            `r` for run is natural, and typing `r` inside a command must not
            launch one — so the check is on focus rather than on the key.
            """
            if getattr(self.bar, "has_focus", False):
                return
            character = getattr(event, "character", None)
            for key, name, _hint in ACTIONS:
                if character == key:
                    self.run_in_terminal([name])
                    event.prevent_default()
                    return

        # -- running --------------------------------------------------------

        def run_in_terminal(self, words) -> None:
            """Suspend and run for real.

            Captured into a pane the operator sees nothing until it finishes,
            and a prompt they cannot answer hangs it.
            """
            import subprocess
            import sys

            with self.suspend():
                print()
                try:
                    subprocess.call(
                        [sys.executable, "-m", "vanguard.cli", *words])
                except Exception as exc:
                    print(f"could not run: {exc}")
                try:
                    input("\n[Enter] to return to the panes ")
                except (EOFError, KeyboardInterrupt):
                    pass

            self.action_refresh()

            # And show what it DID. Without this the output scrolled past and
            # was gone: the panes came back looking much as before.
            after = AFTER.get(words[0])
            if after:
                self.result.border_title = f"RESULT  ·  after {words[0]}"
                self.result_body.update(
                    render_command(list(after), db=self.db_path,
                                   width=self._pane_width(self.result)))

        # -- enlarging ------------------------------------------------------

        def action_full(self) -> None:
            """Toggle. Not a one-way trip — the first version hid every other
            pane with no way back."""
            targets = (self.input, self.result, self.listing, self.progress)
            if self.enlarged is not None:
                self.action_restore()
                return

            box = next((t for t in targets
                        if getattr(t, "has_focus_within", False)), self.result)
            for other in targets:
                other.display = other is box
            self.enlarged = box

        def action_restore(self) -> None:
            if self.enlarged is None:
                return
            for widget in (self.input, self.result, self.listing,
                           self.progress):
                widget.display = True
            self.enlarged = None

        def action_shell(self) -> None:
            import os
            import subprocess

            with self.suspend():
                print("\nType `exit` to return to the panes.\n")
                shell = os.environ.get("COMSPEC") or os.environ.get(
                    "SHELL", "/bin/sh")
                try:
                    subprocess.call([shell])
                except Exception as exc:
                    print(f"could not start a shell: {exc}")
            self.action_refresh()

        def action_help(self) -> None:
            lines = ["KEYS", ""]
            lines += [f"  [{key}]  {name:<8} {hint}"
                      for key, name, hint in ACTIONS]
            lines += [
                "",
                "  F2      enlarge the focused pane, again to restore",
                "  F3      drop to a shell, `exit` to come back",
                "  Ctrl+R  refresh",
                "  Ctrl+Q  quit",
                "  Tab     move between the menu, the list and the bar",
                "",
                "The bar takes any command. Anything that streams or asks —",
                "run, poll, session — suspends the panes and runs for real.",
            ]
            self.result.border_title = "RESULT  ·  help"
            self.result_body.update("\n".join(lines))

        def action_quit(self) -> None:
            self.exit()

    VanguardApp(db).run()
