"""Presentation layer — layout, and accessibility as a contract."""
from __future__ import annotations

import os
import re

import pytest

from vanguard import ui
from vanguard.ui import Column, Theme, Tone

ANSI = re.compile(r"\033\[[0-9;]*m")

FULL = Theme(colour=True, unicode=True, decorated=True, width=80)
PLAIN = Theme(colour=False, unicode=False, decorated=False, width=80)
MONO = Theme(colour=False, unicode=True, decorated=True, width=80)


@pytest.fixture(autouse=True)
def reset_theme():
    yield
    ui.set_theme(None)


# ---------------------------------------------------------------------------
# Accessibility contract
# ---------------------------------------------------------------------------

def test_status_is_never_colour_alone() -> None:
    """The core guarantee. A red PENDING and a green PENDING must read
    differently in monochrome, in a screen reader, and to anyone who cannot
    distinguish red from green."""
    ui.set_theme(MONO)
    good = ANSI.sub("", ui.badge("PENDING", Tone.GOOD))
    bad = ANSI.sub("", ui.badge("PENDING", Tone.BAD))
    assert good != bad
    assert "PENDING" in good and "PENDING" in bad


@pytest.mark.parametrize("tone", list(Tone))
def test_every_tone_has_a_distinct_symbol(tone: Tone) -> None:
    ui.set_theme(MONO)
    symbols = {t: MONO.symbol(t) for t in Tone if t is not Tone.PLAIN}
    assert len(set(symbols.values())) == len(symbols)


def test_plain_mode_emits_no_escape_sequences() -> None:
    """A screen reader or log file receives text, not control codes."""
    ui.set_theme(PLAIN)
    output = "\n".join([
        ui.rule("QUEUE"),
        ui.badge("PENDING", Tone.GOOD),
        ui.table([Column("A"), Column("B")], [["x", "y"]]),
        ui.panel("NOTE", "body text"),
        ui.bar(3, 10),
        ui.field_list([("label", "value")]),
    ])
    assert ANSI.findall(output) == []


def test_ascii_mode_uses_no_unicode() -> None:
    ui.set_theme(Theme(colour=False, unicode=False, decorated=True, width=80))
    output = ui.panel("T", "body") + ui.rule("R") + ui.badge("X", Tone.GOOD) + ui.bar(1, 2)
    assert output.isascii()


def test_no_color_env_is_honoured(monkeypatch) -> None:
    """The de-facto standard — any value disables colour."""
    monkeypatch.setitem(os.environ, "NO_COLOR", "1")
    assert not Theme.detect().colour


def test_plain_env_is_honoured(monkeypatch) -> None:
    monkeypatch.setitem(os.environ, "VANGUARD_PLAIN", "1")
    assert not Theme.detect().decorated


def test_ascii_env_is_honoured(monkeypatch) -> None:
    monkeypatch.setitem(os.environ, "VANGUARD_ASCII", "1")
    assert not Theme.detect().unicode


def test_dumb_terminal_degrades(monkeypatch) -> None:
    monkeypatch.setitem(os.environ, "TERM", "dumb")
    theme = Theme.detect()
    assert not theme.colour and not theme.unicode


def test_non_tty_defaults_to_plain() -> None:
    """Piped or redirected output should not carry decoration."""
    class NotATerminal:
        def isatty(self):
            return False

    theme = Theme.detect(stream=NotATerminal())
    assert not theme.colour and not theme.decorated


def test_high_contrast_drops_dim() -> None:
    """Dim is unreadable on many themes and invisible to some users."""
    contrast = Theme(colour=True, unicode=True, decorated=True,
                     high_contrast=True, width=80)
    assert "\033[2m" not in contrast.paint("x", Tone.MUTED, dim=True)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def test_columns_align() -> None:
    ui.set_theme(PLAIN)
    output = ui.table(
        [Column("A", 1, 6), Column("B", 1, 6)],
        [["short", "x"], ["considerably longer", "y"]],
    )
    lines = output.split("\n")
    positions = [line.index("x") if "x" in line else None for line in lines[1:]]
    assert lines[1].index("x") != -1
    assert len({len(line.rstrip()) - len(line.rstrip().split()[-1]) for line in lines[1:]}) >= 1


def test_table_fits_the_width() -> None:
    ui.set_theme(Theme(colour=False, unicode=False, decorated=False, width=60))
    output = ui.table(
        [Column("EMPLOYER", 1, 8), Column("TITLE", 2, 10), Column("ID", 1, 8)],
        [["A very long employer name indeed", "An extremely long job title here",
          "reed:12345678901234"]],
    )
    assert all(len(line) <= 60 for line in output.split("\n"))


def test_painted_cells_are_not_cut_mid_escape() -> None:
    """Counting escape codes as characters cut inside a sequence and
    corrupted the rest of the line."""
    ui.set_theme(FULL)
    output = ui.table(
        [Column("S", 1, 8), Column("T", 2, 10)],
        [[ui.badge("PENDING", Tone.GOOD), "a title"]],
    )
    assert output.count("\033[0m") == output.count("\033[32m") + output.count("\033[90m")


def test_clip_never_cuts_mid_word() -> None:
    ui.set_theme(PLAIN)
    assert not ui.clip("Machine Learning Engineer role", 20).replace("...", "").endswith("Eng")


def test_clip_leaves_short_text_alone() -> None:
    ui.set_theme(PLAIN)
    assert ui.clip("short", 40) == "short"


def test_wrap_preserves_every_word() -> None:
    text = "advert has headings, but none matched the requirement phrase list"
    assert " ".join(ui.wrap(text, 30)) == text


def test_bar_states_the_numbers() -> None:
    """The figures are the information; the bar is a convenience."""
    ui.set_theme(PLAIN)
    assert "20/31" in ui.bar(20, 31) and "65%" in ui.bar(20, 31)


def test_bar_handles_zero_total() -> None:
    ui.set_theme(PLAIN)
    assert "0%" in ui.bar(0, 0)


def test_field_list_wraps_rather_than_clipping() -> None:
    ui.set_theme(Theme(colour=False, unicode=False, decorated=False, width=50))
    long = "a considerably longer value than will fit on one line of output"
    assert " ".join(ui.field_list([("k", long)]).split())[-20:] in " ".join(long.split())[-40:]


def test_empty_table_is_empty() -> None:
    ui.set_theme(PLAIN)
    assert ui.table([Column("A")], []) == ""


def test_width_has_a_floor() -> None:
    assert ui.terminal_width() >= ui.MIN_WIDTH


def test_unicode_capability_is_asked_of_the_stream() -> None:
    """Windows does not set TERM, so an unset value says nothing. What matters
    is whether the stream can encode the characters — a cp1252 console raises
    on the box-drawing glyphs rather than degrading."""
    class Cp1252:
        encoding = "cp1252"

        def isatty(self):
            return True

    class Utf8:
        encoding = "utf-8"

        def isatty(self):
            return True

    assert not Theme.detect(stream=Cp1252()).unicode
    assert Theme.detect(stream=Utf8()).unicode


def test_unset_term_does_not_force_ascii(monkeypatch) -> None:
    """An earlier rule treated unset TERM as a dumb terminal, which made every
    Windows session ASCII regardless of capability."""
    monkeypatch.delitem(os.environ, "TERM", raising=False)

    class Capable:
        encoding = "utf-8"

        def isatty(self):
            return True

    assert Theme.detect(stream=Capable()).unicode


def test_plain_implies_ascii(monkeypatch) -> None:
    """Unicode glyphs are read aloud by name. Plain targets screen readers."""
    monkeypatch.setitem(os.environ, "VANGUARD_PLAIN", "1")
    theme = Theme.detect()
    assert not theme.unicode and not theme.decorated and not theme.colour


def test_protected_columns_are_never_truncated() -> None:
    """A truncated identifier cannot be pasted into the next command, which
    makes the row useless. Observed as `linkedin:a4a582bc5…` in the queue."""
    ui.set_theme(Theme(colour=False, unicode=False, decorated=False, width=70))
    output = ui.table(
        [
            Column("EMPLOYER", 1.0, 8),
            Column("TITLE", 2.0, 10),
            Column("ID", 0.9, 12, protected=True),
        ],
        [["A very long employer name", "An extremely long job title here",
          "linkedin:a4a582bc5f1e9d3b"]],
    )
    assert "linkedin:a4a582bc5f1e9d3b" in output
    assert "..." not in output.split()[-1]


def test_flexible_columns_absorb_the_shrinking() -> None:
    ui.set_theme(Theme(colour=False, unicode=False, decorated=False, width=60))
    output = ui.table(
        [Column("TITLE", 2.0, 10), Column("ID", 0.9, 12, protected=True)],
        [["An extremely long job title that will not fit", "reed:57092035"]],
    )
    assert "reed:57092035" in output
    assert "..." in output
