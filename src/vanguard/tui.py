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
        #top { height: 55%; }
        #bottom { height: 45%; }
        PaneBox {
            border: round $primary;
            padding: 0 1;
            width: 1fr;
        }
        PaneBox:focus-within { border: round $accent; }
        #hint { height: 1; color: $text-muted; padding: 0 1; }
        """

        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("r", "refresh", "Refresh"),
            Binding("f", "full", "Enlarge / restore"),
            Binding("escape", "restore", "Restore", show=False),
            Binding("colon", "command", "Run a command"),
            Binding("exclamation_mark", "shell", "Drop to shell"),
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

            yield Static(
                "  f enlarge · : run a command · ! drop to the shell · q quit",
                id="hint")

            # Hidden until `:`. A command bar rather than a menu, because the
            # commands are the interface — a menu would be a second one.
            self.bar = Input(placeholder="vanguard …", id="bar")
            self.bar.display = False
            yield self.bar

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
            self._set_hint("  f or Esc to restore · : run a command · "
                           f"! shell · full: {box.pane.full}")

        def action_restore(self) -> None:
            """Back to the grid. Bound to Escape as well as `f`, because
            Escape is what people press when a screen has swallowed them."""
            if self.enlarged is None:
                return
            for box in self.boxes:
                box.display = True
                box.refresh_content()
            self.enlarged = None
            self._set_hint("  f enlarge · : run a command · "
                           "! drop to the shell · q quit")

        def _set_hint(self, text: str) -> None:
            try:
                self.query_one("#hint", Static).update(text)
            except Exception:                      # pragma: no cover - defensive
                pass

        # -- running commands -----------------------------------------------

        def action_command(self) -> None:
            """Type a command and see it in the focused pane.

            For anything that PRINTS — `review`, `responses`, `sql`, `funnel`.
            Output is captured, so a command that takes a minute or asks a
            question is the wrong tool here; that is what `!` is for.
            """
            box = self._focused_box() or (self.boxes[0] if self.boxes else None)
            if box is None:
                return
            self.bar.display = True
            self.bar.value = ""
            self.bar.placeholder = f"vanguard …   (shown in {box.pane.title})"
            self.bar.focus()

        def on_input_submitted(self, event) -> None:
            typed = (event.value or "").strip()
            self.bar.display = False

            box = self._focused_box() or (self.boxes[0] if self.boxes else None)
            if not typed or box is None:
                return

            # `vanguard` is optional — nobody types the program name twice.
            words = typed.split()
            if words and words[0] == "vanguard":
                words = words[1:]
            if not words:
                return

            box.show_command(words, self.db_path)

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
