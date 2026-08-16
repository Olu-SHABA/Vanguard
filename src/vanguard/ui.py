"""
Terminal presentation.

Built on the standard library. No dependency, and — more importantly — the
output is a string this module produces, so it can be asserted on in tests
rather than eyeballed. The CSS in `render/` was written blind and needed three
rounds of correction; this is not.

Accessibility is designed in, not bolted on:

  * **Colour is never the only signal.** Every status carries a symbol AND a
    word. A red PENDING and a green PENDING read identically in monochrome.
  * **NO_COLOR is honoured.** The de-facto standard (no-color.org) — any value
    disables colour entirely.
  * **Plain mode** strips all decoration for screen readers, logs and pipes.
    Auto-detected when output is not a terminal.
  * **ASCII mode** for terminals without reliable Unicode. Box characters and
    symbols degrade to ASCII rather than showing replacement glyphs.
  * **High contrast** drops dim and italic, which are unreadable on many
    terminal themes and invisible to some users.
  * Width is detected, with a floor. Nothing assumes 80 or 100 columns.

Environment:

    NO_COLOR=1              disable colour
    VANGUARD_PLAIN=1        no decoration at all
    VANGUARD_ASCII=1        ASCII box drawing and symbols
    VANGUARD_CONTRAST=high  drop dim and italic
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

__all__ = [
    "Theme",
    "Column",
    "Tone",
    "table",
    "panel",
    "rule",
    "badge",
    "bar",
    "field_list",
    "wrap",
    "clip",
    "terminal_width",
    "current_theme",
    "set_theme",
]

MIN_WIDTH = 50
FALLBACK_WIDTH = 100


# ---------------------------------------------------------------------------
# Tone — semantic, not a colour name
# ---------------------------------------------------------------------------

class Tone(str, Enum):
    """What a piece of output MEANS. Colour is derived; meaning is not.

    Naming these by intent rather than by colour is what makes monochrome and
    high-contrast modes work without a second code path.
    """

    GOOD = "good"          # ready, passed, healthy
    WARN = "warn"          # needs attention, unresolved
    BAD = "bad"            # blocked, failed, terminal
    MUTED = "muted"        # secondary detail
    INFO = "info"          # neutral emphasis
    PLAIN = "plain"


_ANSI = {
    Tone.GOOD: "\033[32m",
    Tone.WARN: "\033[33m",
    Tone.BAD: "\033[31m",
    Tone.MUTED: "\033[90m",
    Tone.INFO: "\033[36m",
    Tone.PLAIN: "",
}
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

# Symbols carry the meaning when colour is unavailable. Every one has an
# ASCII fallback — a terminal without Unicode should show a usable character,
# not a replacement box.
_SYMBOLS = {
    Tone.GOOD: ("\u25cf", "*"),      # filled circle
    Tone.WARN: ("\u25d0", "!"),      # half-filled
    Tone.BAD: ("\u25cb", "x"),       # hollow
    Tone.MUTED: ("\u00b7", "."),
    Tone.INFO: ("\u25b8", ">"),
    Tone.PLAIN: (" ", " "),
}

_BOX = {
    "h": ("\u2500", "-"),
    "v": ("\u2502", "|"),
    "tl": ("\u250c", "+"), "tr": ("\u2510", "+"),
    "bl": ("\u2514", "+"), "br": ("\u2518", "+"),
    "lt": ("\u251c", "+"), "rt": ("\u2524", "+"),
}


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Theme:
    """Resolved presentation settings. Immutable; build a new one to change."""

    colour: bool = True
    unicode: bool = True
    decorated: bool = True     # boxes, rules, padding
    high_contrast: bool = False
    width: int = FALLBACK_WIDTH

    @classmethod
    def detect(cls, *, stream=None) -> Theme:
        """Resolve from environment and terminal capability.

        Order matters: an explicit environment variable always beats
        auto-detection, so a user who sets NO_COLOR gets no colour even on a
        capable terminal.
        """
        stream = stream or sys.stdout
        is_tty = bool(getattr(stream, "isatty", lambda: False)())

        plain = _flag("VANGUARD_PLAIN")
        no_colour = "NO_COLOR" in os.environ or _flag("VANGUARD_NO_COLOR")
        ascii_only = _flag("VANGUARD_ASCII")
        contrast = os.environ.get("VANGUARD_CONTRAST", "").lower() == "high"

        # Not a terminal — piped, redirected, or read by a screen reader that
        # prefers plain text. Decoration is noise there.
        if not is_tty:
            plain = plain or True
            no_colour = True

        # TERM=dumb is an explicit declaration of no capability.
        if os.environ.get("TERM", "").lower() == "dumb":
            no_colour = True
            ascii_only = True

        # Windows does not set TERM, so an unset value says nothing. What
        # matters is whether the stream can ENCODE the characters — a cp1252
        # console raises on "\u25cf" rather than degrading. Ask directly.
        if not ascii_only and not _can_encode(stream, "\u25cf\u2500\u2588\u2026"):
            ascii_only = True

        # Plain mode targets screen readers and log files. Unicode box glyphs
        # and ellipses are read aloud as their character names, so plain
        # implies ASCII.
        return cls(
            colour=not (no_colour or plain),
            unicode=not (ascii_only or plain),
            decorated=not plain,
            high_contrast=contrast,
            width=terminal_width(stream),
        )

    # -- primitives --------------------------------------------------------

    def paint(self, text: str, tone: Tone = Tone.PLAIN, *, bold: bool = False,
              dim: bool = False) -> str:
        # Plain mode emits NO escape sequences at all. A screen reader or a
        # log file should receive text, not terminal control codes — bold
        # included.
        if not self.decorated:
            return text
        if not self.colour and not bold:
            return text
        prefix = ""
        if self.colour:
            prefix += _ANSI.get(tone, "")
        if bold:
            prefix += _BOLD
        # Dim is unreadable on many themes and invisible to some users.
        if dim and not self.high_contrast and self.colour:
            prefix += _DIM
        return f"{prefix}{text}{_RESET}" if prefix else text

    def symbol(self, tone: Tone) -> str:
        unicode_char, ascii_char = _SYMBOLS.get(tone, (" ", " "))
        return unicode_char if self.unicode else ascii_char

    def box(self, key: str) -> str:
        unicode_char, ascii_char = _BOX[key]
        return unicode_char if self.unicode else ascii_char


def _can_encode(stream, sample: str) -> bool:
    """Can this stream represent these characters?

    More reliable than inferring from TERM: it is the actual constraint, and
    it works identically on Windows, Linux and in a pipe.
    """
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        sample.encode(encoding)
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


_THEME: Theme | None = None


def current_theme() -> Theme:
    global _THEME
    if _THEME is None:
        _THEME = Theme.detect()
    return _THEME


def set_theme(theme: Theme | None) -> None:
    """Override the detected theme. Pass None to re-detect."""
    global _THEME
    _THEME = theme


# ---------------------------------------------------------------------------
# Width and text
# ---------------------------------------------------------------------------

def terminal_width(stream=None) -> int:
    try:
        columns = shutil.get_terminal_size(fallback=(FALLBACK_WIDTH, 24)).columns
    except Exception:
        columns = FALLBACK_WIDTH
    return max(MIN_WIDTH, columns - 1)


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_len(text: str) -> int:
    """Length excluding escape sequences. Alignment depends on this."""
    return len(_ANSI_RE.sub("", text))


def clip(text: str, width: int) -> str:
    """Truncate at a word boundary, marked. Never mid-word.

    ANSI-aware. A pre-painted cell carries escape sequences that are not
    visible characters; counting them cut inside an escape and emitted a
    broken sequence that corrupted everything after it on the line.
    """
    text = " ".join(str(text or "").split())
    if visible_len(text) <= width:
        return text
    if _ANSI_RE.search(text):
        # Never cut a painted string. The caller sized the column from the
        # visible length, so an overlong painted cell is a layout error, not
        # something to truncate blindly.
        return text
    # The ellipsis is one character in Unicode and three in ASCII. Reserving
    # one for both overflowed the column by two in ASCII mode.
    ellipsis = "\u2026" if current_theme().unicode else "..."
    if width <= len(ellipsis):
        return ellipsis[:width] if width > 0 else ""

    cut = text[: width - len(ellipsis)]
    space = cut.rfind(" ")
    if space > width * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:") + ellipsis


def wrap(text: str, width: int) -> list[str]:
    body = " ".join(str(text or "").split())
    if not body:
        return []
    return textwrap.wrap(body, width=max(20, width)) or [""]


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

@dataclass
class Column:
    """One table column. `weight` distributes leftover width proportionally.

    `protected` columns are never truncated. An identifier that has been cut
    short cannot be copied into the next command, which makes the row useless
    — the whole point of showing it is that it can be acted on.
    """

    header: str
    weight: float = 1.0
    minimum: int = 6
    align: str = "left"
    tone: Tone = Tone.PLAIN
    protected: bool = False


def table(
    columns: Sequence[Column],
    rows: Iterable[Sequence[str]],
    *,
    theme: Theme | None = None,
    indent: str = "  ",
) -> str:
    """Aligned columns sized to the terminal.

    Column widths are computed from content and weight rather than fixed, so
    a narrow window degrades by shrinking columns instead of wrapping into an
    unreadable mess.
    """
    theme = theme or current_theme()
    rows = [[str(cell) for cell in row] for row in rows]
    if not rows:
        return ""

    available = theme.width - len(indent) - 2 * (len(columns) - 1)
    natural = [
        max(len(col.header), *(visible_len(r[i]) for r in rows)) if rows else len(col.header)
        for i, col in enumerate(columns)
    ]

    if sum(natural) <= available:
        widths = natural
    else:
        # Protected columns take their full width first. A clipped identifier
        # cannot be pasted into the next command, so shrinking it defeats the
        # purpose of printing the row at all.
        protected_width = sum(want for col, want in zip(columns, natural)
                              if col.protected)
        flexible = [(i, col, want) for i, (col, want)
                    in enumerate(zip(columns, natural)) if not col.protected]

        remaining = available - protected_width
        total_weight = sum(col.weight for _, col, _ in flexible) or 1
        spare = remaining - sum(col.minimum for _, col, _ in flexible)

        widths = list(natural)
        for index, col, want in flexible:
            share = int(max(0, spare) * (col.weight / total_weight))
            widths[index] = max(col.minimum, min(want, col.minimum + share))

    lines = []
    header = indent + "  ".join(
        _align(clip(col.header, w), w, col.align) for col, w in zip(columns, widths)
    )
    lines.append(theme.paint(header, Tone.MUTED, bold=True))

    for row in rows:
        cells = []
        for col, width, value in zip(columns, widths, row):
            text = _align(clip(value, width), width, col.align)
            cells.append(theme.paint(text, col.tone) if col.tone is not Tone.PLAIN else text)
        lines.append(indent + "  ".join(cells).rstrip())

    return "\n".join(lines)


def _align(text: str, width: int, align: str) -> str:
    pad = width - visible_len(text)
    if pad <= 0:
        return text
    if align == "right":
        return " " * pad + text
    if align == "center":
        left = pad // 2
        return " " * left + text + " " * (pad - left)
    return text + " " * pad


def panel(title: str, body: str, *, tone: Tone = Tone.PLAIN,
          theme: Theme | None = None) -> str:
    """A titled block. Degrades to a heading and indent in plain mode."""
    theme = theme or current_theme()
    lines = body.rstrip().split("\n")

    if not theme.decorated:
        return "\n".join([f"{title}:", *(f"  {line}" for line in lines)])

    inner = theme.width - 4
    heading = clip(title, inner)
    h = theme.box("h")

    top = theme.paint(
        f"{theme.box('tl')}{h} {heading} {h * max(0, inner - len(heading) - 1)}"
        f"{theme.box('tr')}", tone)
    bottom = theme.paint(f"{theme.box('bl')}{h * (inner + 2)}{theme.box('br')}", tone)
    v = theme.paint(theme.box("v"), tone)

    out = [top]
    for line in lines:
        for piece in (wrap(line, inner) or [""]):
            out.append(f"{v} {piece.ljust(inner)} {v}")
    out.append(bottom)
    return "\n".join(out)


def rule(label: str = "", *, theme: Theme | None = None) -> str:
    theme = theme or current_theme()
    if not theme.decorated:
        return label
    h = theme.box("h")
    if not label:
        return theme.paint(h * theme.width, Tone.MUTED)
    text = f"{h}{h} {label} "
    return theme.paint(text + h * max(0, theme.width - len(text)), Tone.MUTED)


def badge(label: str, tone: Tone, *, theme: Theme | None = None,
          width: int = 0) -> str:
    """A status marker. ALWAYS symbol plus word — never colour alone.

    This is the core accessibility guarantee: the output is unambiguous in
    monochrome, in a screen reader, and to anyone who cannot distinguish red
    from green.
    """
    theme = theme or current_theme()
    text = f"{theme.symbol(tone)} {label}"
    if width:
        text = text.ljust(width)
    return theme.paint(text, tone, bold=tone in (Tone.GOOD, Tone.BAD))


def bar(value: float, total: float, *, width: int = 20,
        tone: Tone = Tone.INFO, theme: Theme | None = None) -> str:
    """A proportion bar with the numbers beside it.

    The figures are the information; the bar is a convenience. Anyone reading
    this through a screen reader gets the ratio either way.
    """
    theme = theme or current_theme()
    fraction = 0.0 if total <= 0 else max(0.0, min(1.0, value / total))
    filled = int(round(fraction * width))

    if theme.unicode:
        drawn = "\u2588" * filled + "\u2591" * (width - filled)
    else:
        drawn = "#" * filled + "-" * (width - filled)

    return f"{theme.paint(drawn, tone)} {value:g}/{total:g} ({fraction * 100:.0f}%)"


def field_list(pairs: Sequence[tuple[str, str]], *, theme: Theme | None = None,
               indent: str = "") -> str:
    """Aligned label/value pairs. Wraps long values rather than clipping."""
    theme = theme or current_theme()
    pairs = [(k, v) for k, v in pairs if v not in (None, "")]
    if not pairs:
        return ""

    label_width = max(len(k) for k, _ in pairs)
    body_width = theme.width - label_width - len(indent) - 3

    lines = []
    for label, value in pairs:
        wrapped = wrap(str(value), body_width) or [""]
        lines.append(
            f"{indent}{theme.paint(label.ljust(label_width), Tone.MUTED)}  {wrapped[0]}"
        )
        for extra in wrapped[1:]:
            lines.append(f"{indent}{' ' * label_width}  {extra}")
    return "\n".join(lines)
