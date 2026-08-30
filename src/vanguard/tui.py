"""
The pane view — a menu of stages, four regions, and a console.

## The layout

    +- MENU ----+- INPUT (the selected stage's keys) --------+
    | > Find    |  [r] run  [s] search  [p] paste            |
    |   Set up  +------------------------+-------------------+
    |   Assess  |  QUEUE - all states    |  PROGRESS         |
    |   Decide  |  0.62 Sanderson PEND   |  20 dispatched    |
    |   Apply   |  0.58 Acme      PEND   |  none past CV     |
    |   Track   +------------------------+-------------------+
    |  ---      |  RESULT - the row under the cursor         |
    |   Analyse |  coverage 0.62, unmet: Azure, Docker...    |
    |   Accounts+--------------------------------------------+
    |   System  |  CONSOLE - grows when it has output        |
    +-----------+--------------------------------------------+

**Order matters.** Do something, see what you got, look at one of them.
RESULT sits BELOW the queue because it is downstream of it — the cursor
produces the record, so cause reads above effect, and the two are adjacent
when arrowing down a list.

## The strict key rule

A key belongs to the stage that owns it and nowhere else. `r` runs on Find
and does nothing on Track.

The alternative — reserving a couple of keys globally so `run` and `poll` are
always one keystroke — means a key does different things depending on where
you are. Pressing `r` on Decide meaning `reject` would start a run instead.
Anything is reachable from the console regardless.

## The console

Always visible, two rows when idle, growing when it has output and collapsing
on `cls`.

Output appears **where you typed it**. The previous version typed at the
bottom and answered in RESULT, so a query destroyed whatever record was being
read — and a shell that answers somewhere else is not a shell.

## Read-only, still

`approve`, `reject` and `dispatch` appear in INPUT and run through the
command, in a suspended terminal, with the command's own confirmation. No
keystroke silently changes a state: the confirmation an operator would see at
the CLI is the confirmation they see here.

## `review` and `status` have no menu entry

They are not things to invoke. QUEUE **is** `review`; the pane view as a
whole **is** `status`. Two commands turn out to be the interface rather than
items in it.
"""

from __future__ import annotations

from vanguard.forms import Form, form_for
from vanguard.panes import (
    AFTER,
    INTERACTIVE,
    MENU,
    action_for_key,
    actions_for,
    queue_rows,
    record_detail,
    render_command,
)

__all__ = ["run_app", "TEXTUAL_MISSING", "console_height"]

TEXTUAL_MISSING = (
    "the pane view needs Textual:\n\n"
    "    pip install textual\n\n"
    "every command works without it — the panes are an extra way in, "
    "not a replacement"
)

#: Console height in rows: idle, and once it has output.
#:
#: Hybrid rather than either extreme. Always visible, so nobody has to
#: discover that a command bar exists — the first version hid one behind a
#: keybinding that never fired, leaving nothing on screen to diagnose. And
#: growing only when used, so it does not cost a third of a short terminal
#: while empty.
#: A Textual `Input` occupies THREE rows — a border, the text, a border. At
#: four rows total the console had two usable, the hint took one, and the
#: Input was squeezed out: the operator typed into a widget that was not
#: drawn.
CONSOLE_IDLE = 8
CONSOLE_OPEN = 18


def console_height(has_output: bool) -> int:
    return CONSOLE_OPEN if has_output else CONSOLE_IDLE


# REMOVED 23 Aug 2026: `NEEDS_ARGUMENT`.
#
# It listed which commands could not be fired bare and what they still
# needed, so a key could prefill the console with a hint. The form
# supersedes it: the schema is derived from the command, so what a command
# needs is read from the command rather than restated here.


def run_app(db: str) -> None:
    """Start the pane view. Raises `ImportError` when Textual is absent."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import (
        Checkbox, Footer, Header, Input, ListItem, ListView, Select, Static,
    )

    class VanguardApp(App):
        TITLE = "Vanguard"

        CSS = """
        Screen { layout: horizontal; }
        #menu { width: 20; border-right: solid $primary; }
        #right { width: 1fr; }
        #input { height: 5; border: round $primary; padding: 0 1; }
        #input Input, #input Select { margin: 0 0 1 0; }
        .form-note { color: $text-muted; }
        #upper { height: 1fr; }
        #queue { width: 3fr; border: round $primary; padding: 0 1; }
        #progress { width: 2fr; border: round $primary; padding: 0 1; }
        #result { height: 1fr; border: round $primary; padding: 0 1; }
        #console { height: 8; border: round $accent; padding: 0 1; }
        #console.open { height: 18; }
        #console-body { height: 1fr; }
        #queue:focus-within, #result:focus-within { border: round $accent; }
        /* Three rows, which is what an Input needs. Docked so it stays
           visible however much output is above it. */
        #bar { dock: bottom; height: 3; }
        """

        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit"),
            Binding("ctrl+r", "refresh", "Refresh"),
            Binding("f1", "help", "Help"),
            Binding("f2", "full", "Enlarge"),
            Binding("f3", "shell", "Shell"),
            Binding("escape", "cancel", "Cancel", show=False),
        ]

        def __init__(self, db_path: str) -> None:
            super().__init__()
            self.db_path = db_path
            self.stage = MENU[0][0]
            self.rows = []
            self.enlarged = None
            self.console_lines = []

        # -- layout ---------------------------------------------------------

        def compose(self) -> ComposeResult:
            yield Header()

            with Vertical(id="menu"):
                # ROLLED BACK 23 Aug 2026. Splitting this into two ListViews
                # with a rule between them left the whole screen blank, and
                # the grouping is not worth a layout that does not render.
                #
                # The two groups are shown by the leading marker instead: a
                # stage is prefixed, a support group is not.
                self.menu = ListView(*[
                    ListItem(Static(f" {'·' if is_stage else ' '} {name}"))
                    for name, _hint, _actions, is_stage in MENU])
                yield self.menu

            with Vertical(id="right"):
                self.input = Vertical(id="input")
                self.input.border_title = "INPUT"
                yield self.input

                with Horizontal(id="upper"):
                    self.queue = VerticalScroll(id="queue")
                    self.queue.border_title = "QUEUE"
                    yield self.queue

                    self.progress = VerticalScroll(id="progress")
                    self.progress.border_title = "PROGRESS"
                    yield self.progress

                self.result = VerticalScroll(id="result")
                self.result.border_title = "RESULT"
                yield self.result

                # An inline `with Vertical(...)`, not a pre-built widget used
                # as a context manager. The latter rendered nothing.
                with Vertical(id="console"):
                    self.console_body = Static(
                        "type a command below — `cls` clears this",
                        id="console-body")
                    yield self.console_body
                    self.bar = Input(placeholder="> ", id="bar")
                    yield self.bar

            yield Footer()

        def on_mount(self) -> None:
            # INPUT holds either the stage's key list, or a form. Both are
            # mounted here rather than in `compose`, because a widget swapped
            # in later has to be mounted the same way as one swapped in at
            # the start — two paths for the same thing is how they diverge.
            self.keys_label = Static("")
            self.input.mount(self.keys_label)
            self.form_fields: dict[str, object] = {}
            self.form: Form | None = None

            self.list_view = ListView()
            self.queue.mount(self.list_view)

            self.progress_body = Static("loading…")
            self.progress.mount(self.progress_body)

            self.result_body = Static("(select a row)")
            self.result.mount(self.result_body)

            self._show_stage(self.stage)
            self.action_refresh()

        # -- content --------------------------------------------------------

        def _pane_width(self, widget) -> int:
            size = getattr(widget, "size", None)
            return max(40, (size.width - 4) if size and size.width else 70)

        def _show_stage(self, name: str) -> None:
            """INPUT shows this stage's keys, and only this stage's."""
            self.stage = name
            self._close_form()
            self.input.border_title = f"INPUT  ·  {name}"
            keys = "   ".join(f"[{key}] {command}"
                              for key, command, _hint in actions_for(name))
            self.keys_label.update(keys or "(no actions on this stage)")

        # -- forms ----------------------------------------------------------

        def _close_form(self) -> None:
            """Back to the key list.

            Every form widget is removed rather than hidden. A hidden input
            still takes Tab and still holds a value, so the next form would
            open with the last one's answers underneath it.
            """
            for widget in list(self.form_fields.values()):
                try:
                    widget.remove()
                except Exception:
                    pass
            self.form_fields = {}
            self.form = None
            self.keys_label.display = True
            self.input.styles.height = 5

        def _open_form(self, command: str) -> None:
            """Draw the command's fields into INPUT.

            The schema is derived from the command itself, so this draws
            whatever the command declares — a new option appears without any
            change here.
            """
            form = form_for(command)
            if form is None:
                self._echo(f"no form for {command}")
                return

            self._close_form()
            self.form = form
            self.keys_label.display = False
            self.input.border_title = f"INPUT  ·  {form.title}"

            # Room for the fields, the note, and the Enter line.
            self.input.styles.height = min(20, len(form.fields) + 6)

            if form.note:
                note = Static(f"  {form.note}", classes="form-note")
                self.input.mount(note)
                self.form_fields["__note__"] = note

            for item in form.fields:
                if item.kind == "choice":
                    widget = Select(
                        [(choice, choice) for choice in item.choices],
                        value=item.default or Select.BLANK,
                        prompt=item.label,
                        id=f"f-{item.name}")
                elif item.kind == "flag":
                    widget = Checkbox(item.label, id=f"f-{item.name}")
                else:
                    widget = Input(
                        value=item.default,
                        placeholder=f"{item.label}"
                                    + (" (required)" if item.required else ""),
                        id=f"f-{item.name}")
                self.input.mount(widget)
                self.form_fields[item.name] = widget

            run_line = Static(
                "  Enter runs it · Esc cancels", classes="form-note")
            self.input.mount(run_line)
            self.form_fields["__run__"] = run_line

            first = next((w for n, w in self.form_fields.items()
                          if not n.startswith("__")), None)
            if first is not None:
                first.focus()

        def on_select_changed(self, event) -> None:
            """A choice does not submit.

            Changing a dropdown is not the same as saying "go" — the operator
            may set four fields before running anything.
            """
            event.stop()

        def _form_values(self) -> dict:
            values = {}
            for name, widget in self.form_fields.items():
                if name.startswith("__"):
                    continue
                value = getattr(widget, "value", "")
                if value is None or repr(value) == "Select.BLANK":
                    value = ""
                if isinstance(value, bool):
                    value = "yes" if value else ""
                values[name] = str(value)
            return values

        def _submit_form(self) -> None:
            """Validate, then run.

            Missing fields are reported by LABEL and before anything runs, so
            the error arrives while the operator is still looking at the
            form.
            """
            if self.form is None:
                return

            values = self._form_values()
            missing = self.form.missing(values)
            if missing:
                self._echo(f"needs: {', '.join(missing)}")
                return

            words = self.form.command_line(values)
            self._close_form()
            self._show_stage(self.stage)
            self._echo(f"> {' '.join(words)}")

            if words[0] in INTERACTIVE:
                self.run_in_terminal(words)
            else:
                self._echo(render_command(
                    words, db=self.db_path,
                    width=self._pane_width(self.query_one("#console"))))

        def action_refresh(self) -> None:
            """QUEUE always shows EVERY state.

            Filtering it by stage would be convenient and wrong: deciding
            whether something is worth applying to needs the overview, not a
            slice of it.
            """
            self.rows = queue_rows("", db=self.db_path)
            self.queue.border_title = f"QUEUE  ·  all states  ·  {len(self.rows)}"

            self.list_view.clear()
            for _vacancy_id, label in self.rows:
                self.list_view.append(ListItem(Static(label)))
            if self.rows:
                self.list_view.index = 0
                self._show_record(0)
            else:
                self.result_body.update("(nothing ingested yet)")

            self.progress_body.update(
                render_command(["funnel"], db=self.db_path,
                               width=self._pane_width(self.progress)))

        def _show_record(self, index: int) -> None:
            if not (0 <= index < len(self.rows)):
                return
            vacancy_id, _label = self.rows[index]
            self.result.border_title = f"RESULT  ·  {vacancy_id}"
            self.result_body.update(
                record_detail(vacancy_id, db=self.db_path,
                              width=self._pane_width(self.result)))

        # -- the console ----------------------------------------------------

        def _echo(self, text: str) -> None:
            """Append to the console and grow it.

            Output belongs where it was typed. Sending it to RESULT destroyed
            whatever record was being read, and a shell that answers
            somewhere else is not a shell.
            """
            self.console_lines.append(text)
            self.console_lines = self.console_lines[-200:]
            self.console_body.update("\n".join(self.console_lines))
            self.query_one("#console").add_class("open")

        def _clear_console(self) -> None:
            self.console_lines = []
            self.console_body.update("type a command below — `cls` clears this")
            self.query_one("#console").remove_class("open")

        def on_input_submitted(self, event) -> None:
            # Enter inside a form submits the FORM, not the console.
            if self.form is not None and event.input is not self.bar:
                self._submit_form()
                return

            typed = (event.value or "").strip()
            self.bar.value = ""
            if not typed:
                return

            if typed.lower() in ("cls", "clear"):
                self._clear_console()
                return

            words = typed.split()
            if words[0] == "vanguard":
                words = words[1:]
            if not words:
                return

            self._echo(f"> {typed}")

            if words[0] in INTERACTIVE:
                self.run_in_terminal(words)
                return

            self._echo(render_command(
                words, db=self.db_path,
                width=self._pane_width(self.query_one("#console"))))

        def on_key(self, event) -> None:
            """Stage keys, ignored while the console has focus.

            Typing `r` inside a command must not launch a run, so the check
            is on focus rather than on the key.
            """
            if getattr(self.bar, "has_focus", False):
                return
            character = getattr(event, "character", None)
            if not character:
                return

            command = action_for_key(self.stage, character)
            if not command:
                return

            event.prevent_default()

            # A FORM, not a prefilled string.
            #
            # Firing the command bare failed: `search` wants keywords,
            # `paste` a file, `discover` a board. Prefilling the console
            # fixed that but still left the operator typing syntax — and an
            # option nobody looks up is an option nobody uses.
            #
            # The form shows every option the command declares, with its
            # default already chosen, and validates before anything runs.
            self._open_form(command)

        def on_list_view_highlighted(self, event) -> None:
            index = event.list_view.index or 0
            if event.list_view is self.menu:
                if 0 <= index < len(MENU):
                    self._show_stage(MENU[index][0])
            elif event.list_view is self.list_view:
                self._show_record(index)

        # -- running --------------------------------------------------------

        def run_in_terminal(self, words) -> None:
            """Suspend and run for real.

            Anything that streams progress or asks a question — including
            `approve` and `dispatch`, so the confirmation an operator would
            see at the CLI is the one they see here. No keystroke silently
            changes a state.
            """
            import subprocess
            import sys

            failed = False
            with self.suspend():
                print()
                try:
                    code = subprocess.call(
                        [sys.executable, "-m", "vanguard.cli", *words])
                    failed = code != 0
                except Exception as exc:
                    print(f"could not run: {exc}")
                    failed = True

                if failed:
                    # An error the operator never sees is worse than a pause.
                    try:
                        input("\n[Enter] to return to the panes ")
                    except (EOFError, KeyboardInterrupt):
                        pass

                # No "press Enter" any more. It existed so the output could be
                # read before the panes covered it, and the console now shows
                # what the command did — so the prompt was one keystroke
                # buying nothing.
                #
                # Kept only where the command FAILED, because an error the
                # operator never sees is worse than a pause.

            self.action_refresh()

            after = AFTER.get(words[0])
            if after:
                self._echo(f"> {' '.join(after)}")
                self._echo(render_command(
                    list(after), db=self.db_path,
                    width=self._pane_width(self.query_one("#console"))))

        # -- enlarging ------------------------------------------------------

        def action_full(self) -> None:
            targets = (self.input, self.queue, self.progress, self.result)
            if self.enlarged is not None:
                self.action_restore()
                return
            box = next((t for t in targets
                        if getattr(t, "has_focus_within", False)), self.result)
            for other in targets:
                other.display = other is box
            self.enlarged = box

        def action_cancel(self) -> None:
            """Escape closes a form first, then restores an enlarged pane."""
            if self.form is not None:
                self._close_form()
                self._show_stage(self.stage)
                return
            self.action_restore()

        def action_restore(self) -> None:
            if self.enlarged is None:
                return
            for widget in (self.input, self.queue, self.progress, self.result):
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
            self._echo("KEYS BELONG TO THE STAGE YOU SELECTED")
            for name, hint, actions, _is_stage in MENU:
                keys = "  ".join(f"[{k}] {c}" for k, c, _ in actions)
                self._echo(f"  {name:<10} {keys}")
            self._echo("")
            self._echo("  F2 enlarge · F3 shell · Ctrl+R refresh · "
                       "Ctrl+Q quit · cls clears this")

        def action_quit(self) -> None:
            self.exit()

    VanguardApp(db).run()
