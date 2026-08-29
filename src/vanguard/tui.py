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
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import Footer, Header, Static

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
            Binding("f", "full", "Full screen"),
            Binding("tab", "focus_next", "Next pane", show=False),
        ]

        def __init__(self, db_path: str) -> None:
            super().__init__()
            self.db_path = db_path
            self.boxes: list[PaneBox] = []

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
                "  every pane runs a command — press f to enlarge one, "
                "q to drop back to the shell",
                id="hint")
            yield Footer()

        def action_refresh(self) -> None:
            for box in self.boxes:
                box.refresh_content()

        def action_full(self) -> None:
            """Enlarge the focused pane.

            A pane is always smaller than the output it can be asked to show,
            and long output — an advert, a rejection email — wants room.
            """
            focused = self.focused
            box = focused if isinstance(focused, PaneBox) else None
            if box is None:
                box = next((b for b in self.boxes if b.has_focus_within), None)
            if box is None:
                return

            for other in self.boxes:
                other.display = other is box or box is None
            box.refresh_content()

        def action_quit(self) -> None:
            self.exit()

    VanguardApp(db).run()
