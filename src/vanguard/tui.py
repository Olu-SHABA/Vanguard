"""
The pane view — a window onto the commands, not a replacement for them.

Four regions on one screen: what needs doing, where the queue is, what came
back, and how far applications get. Quitting drops you back to a normal
prompt with everything intact.

## What this module does NOT do

It computes nothing. Every pane runs the command it corresponds to and shows
what comes back — see `panes.py` for why. This file is layout and key
bindings.

## Read-only, for now

Approving from the keyboard is better and roughly doubles the work, because
every action needs a confirmation and a way to undo a mis-key. Worth adding
once the panes have been used and it is clear which actions are actually
reached for.

Every pane names the command behind it, so acting means one keystroke to the
shell rather than a menu that does not exist yet.

## Textual is optional

It is not a base dependency. Without it, `vanguard panes` says how to install
it and exits — the CLI is unaffected, which is the point of keeping both.
"""

from __future__ import annotations

from pathlib import Path

from vanguard.panes import PANES, Pane, pane_named, render

__all__ = ["run_app", "TEXTUAL_MISSING"]

TEXTUAL_MISSING = (
    "the pane view needs Textual:\n\n"
    "    pip install textual\n\n"
    "every command works without it — the panes are an extra way in, "
    "not a replacement"
)


def run_app(db: str) -> None:
    """Start the pane view. Raises `ImportError` when Textual is absent."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import Footer, Header, Input, Static

    class PaneBox(VerticalScroll):
        """One region. Scrolls, because a pane is always smaller than the
        output it can be asked to show."""

        def __init__(self, pane: Pane, db_path: str) -> None:
            super().__init__()
            self.pane = pane
            self.db_path = db_path
            self.border_title = pane.title
            self.body = Static("loading…")

        def compose(self) -> ComposeResult:
            yield self.body

        def on_mount(self) -> None:
            self.refresh_content()

        def refresh_content(self) -> None:
            width = max(40, self.size.width - 4) if self.size.width else 76
            self.body.update(render(self.pane, db=self.db_path, width=width))

        def show_command(self, words: list[str], db_path: str) -> None:
            """Show an arbitrary command's output in this pane.

            The pane keeps its own identity — a refresh puts its own command
            back — so a query does not permanently repurpose a region.
            """
            from vanguard.panes import render_command

            width = max(40, self.size.width - 4) if self.size.width else 76
            self.border_title = f"{self.pane.title}  ·  {' '.join(words)}"
            self.body.update(render_command(words, db=db_path, width=width))

    class VanguardApp(App):
        CSS = """
        Screen { layout: vertical; }
        #top { height: 1fr; }
        #bottom { height: 1fr; }
        PaneBox {
            border: round $primary;
            padding: 0 1;
            width: 1fr;
        }
        PaneBox:focus-within { border: round $accent; }
        #bar { dock: bottom; border: tall $accent; height: 3; }
        #hint { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
        """

        # Plain keys with no modifier. `:` and `!` need Shift and are
        # reported differently by different terminals, and a binding that
        # silently does not fire is worse than a duller key — the operator
        # pressed `:`, saw nothing happen, and had no way to tell whether the
        # feature existed.
        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit"),
            Binding("ctrl+r", "refresh", "Refresh"),
            Binding("f2", "full", "Enlarge / restore"),
            Binding("escape", "restore", "Restore", show=False),
            Binding("f3", "shell", "Shell"),
            Binding("f5", "refresh", "Refresh", show=False),
            Binding("tab", "focus_next", "Next pane", show=False),
        ]

        def __init__(self, db_path: str) -> None:
            super().__init__()
            self.db_path = db_path
            self.boxes: list[PaneBox] = []
            #: Which pane is enlarged, or None. Held so `f` can TOGGLE —
            #: the first version hid every other pane and had no way back.
            self.enlarged: PaneBox | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)

            # The sketch: input and result above, what-needs-doing and
            # progress below. `status` stands in for the input pane until
            # the panes can act.
            top = [pane_named("s"), pane_named("t")]
            bottom = [pane_named("q"), pane_named("r"), pane_named("p")]

            with Horizontal(id="top"):
                for pane in top:
                    box = PaneBox(pane, self.db_path)
                    self.boxes.append(box)
                    yield box

            with Horizontal(id="bottom"):
                for pane in bottom:
                    box = PaneBox(pane, self.db_path)
                    self.boxes.append(box)
                    yield box

            # ALWAYS VISIBLE, deliberately.
            #
            # The first version hid it behind `:`. That binding did not fire,
            # and because the bar was hidden there was nothing to show the
            # operator the feature existed at all — they pressed a key,
            # nothing happened, and no diagnosis was possible from the
            # screen.
            #
            # A bar you can see cannot fail that way. Click it or Tab to it.
            self.bar = Input(
                placeholder="type a command here and press Enter — "
                            "e.g. review --status DISPATCHED",
                id="bar")
            yield self.bar

            yield Static(
                "  F2 enlarge · F3 shell · Ctrl+R refresh · Ctrl+Q quit",
                id="hint")
            yield Footer()

        def action_refresh(self) -> None:
            for box in self.boxes:
                box.refresh_content()

        # -- enlarging ------------------------------------------------------

        def _focused_box(self) -> PaneBox | None:
            focused = self.focused
            if isinstance(focused, PaneBox):
                return focused
            return next((b for b in self.boxes if b.has_focus_within), None)

        def action_full(self) -> None:
            """Toggle the focused pane between full screen and the grid.

            A TOGGLE, not a one-way trip. The first version hid every other
            pane with no way back, which made `f` a mistake you could not
            undo without quitting.
            """
            if self.enlarged is not None:
                self.action_restore()
                return

            box = self._focused_box()
            if box is None:
                return

            for other in self.boxes:
                other.display = other is box
            self.enlarged = box
            box.refresh_content()
            self._set_hint(f"  F2 or Esc to restore · full: {box.pane.full}")

        def action_restore(self) -> None:
            """Back to the grid. Bound to Escape as well as `f`, because
            Escape is what people press when a screen has swallowed them."""
            if self.enlarged is None:
                return
            for box in self.boxes:
                box.display = True
                box.refresh_content()
            self.enlarged = None
            self._set_hint("  F2 enlarge · F3 shell · Ctrl+R refresh · "
                           "Ctrl+Q quit")

        def on_key(self, event) -> None:
            """A fallback for the shifted keys.

            `:` and `!` are natural and were the first choice. Whether a
            terminal reports them as `colon` and `exclamation_mark` varies,
            and a binding that does not fire leaves no trace on screen. So
            they are handled here by CHARACTER, which is reported
            consistently, and the function keys remain as the documented
            route.
            """
            character = getattr(event, "character", None)
            if character == ":" and not self.bar.has_focus:
                self.bar.focus()
                event.prevent_default()
            elif character == "!" and not self.bar.has_focus:
                self.action_shell()
                event.prevent_default()

        def _set_hint(self, text: str) -> None:
            try:
                self.query_one("#hint", Static).update(text)
            except Exception:                      # pragma: no cover - defensive
                pass

        # -- running commands -----------------------------------------------

        def on_input_submitted(self, event) -> None:
            typed = (event.value or "").strip()
            self.bar.value = ""

            # Where output goes. The focused pane if one is focused —
            # otherwise the largest, because the bar itself holds focus while
            # typing and "nowhere" is not a useful answer.
            box = self._focused_box()
            if box is None:
                box = self.enlarged or (self.boxes[0] if self.boxes else None)
            if not typed or box is None:
                return

            # `vanguard` is optional — nobody types the program name twice.
            words = typed.split()
            if words and words[0] == "vanguard":
                words = words[1:]
            if not words:
                return

            # A command that streams or asks is RUN, not refused.
            #
            # Refusing was the first design and it was the wrong call: the
            # operator typed `run`, which is the single most useful thing to
            # type, and got told to press another key and type it again.
            # Suspending and running it is what they meant.
            from vanguard.panes import INTERACTIVE

            if words[0] in INTERACTIVE:
                self.run_in_terminal(words)
                return

            box.show_command(words, self.db_path)

        def run_in_terminal(self, words: list[str]) -> None:
            """Suspend the panes and run a command for real.

            For anything that streams progress or asks a question. Output
            goes to the terminal as it happens, which is the whole point —
            captured into a pane the operator would see nothing until it
            finished.
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

            # Every pane re-reads the store, so new records appear.
            self.action_refresh()

            # And the focused pane shows what the command DID.
            #
            # Without this the output scrolled past and was gone: the run
            # said what it had fetched and scored, the panes came back
            # looking much as before, and there was no way to see what had
            # happened. The run table holds the record — this surfaces it.
            box = self._focused_box() or (self.boxes[0] if self.boxes else None)
            if box is not None:
                from vanguard.panes import AFTER

                after = AFTER.get(words[0])
                if after:
                    box.show_command(list(after), self.db_path)

        def action_shell(self) -> None:
            """Drop to the real terminal, then come back.

            `vanguard run` streams progress for minutes; `vanguard session`
            asks questions. Neither works captured into a pane, and pretending
            otherwise would give a worse version of something the shell
            already does well.
            """
            with self.suspend():
                print("\nBack to the shell. Type `exit` to return to the panes.\n")
                import os
                import subprocess

                shell = os.environ.get("COMSPEC") or os.environ.get(
                    "SHELL", "/bin/sh")
                try:
                    subprocess.call([shell])
                except Exception as exc:
                    print(f"could not start a shell: {exc}")

            self.action_refresh()

        def action_quit(self) -> None:
            self.exit()

    VanguardApp(db).run()
