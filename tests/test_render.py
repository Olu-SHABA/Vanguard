"""
Render chain tests.

Split into three groups:

  pure       anonymise() and verify_text() — no filesystem, no PDF library
  filesystem render() error paths — no PDF produced
  pdf        end-to-end, marked `needs_pdf`, skipped without weasyprint/pypdf

The pure group carries the anonymisation contract. It must pass in any
environment, because a leak is the one failure with consequences outside the
program.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from vanguard.render import (
    CANONICAL_PROFILE,
    AnonProfile,
    AnonymisationError,
    RenderError,
    anonymise,
    markdown_to_html,
    render,
    verify_text,
)

CV = Path(__file__).parent.parent / "data" / "canonical_cv.md"
CSS_STD = Path(__file__).parent.parent / "render" / "standard.css"
CSS_ANON = Path(__file__).parent.parent / "render" / "anonymised.css"

def _available(*modules: str) -> bool:
    return all(importlib.util.find_spec(m) is not None for m in modules)


needs_pdf = pytest.mark.skipif(
    not _available("weasyprint", "pypdf"),
    reason="weasyprint and pypdf required",
)


@pytest.fixture
def cv_text() -> str:
    return CV.read_text(encoding="utf-8")


@pytest.fixture
def anon(cv_text: str) -> str:
    return anonymise(cv_text, CANONICAL_PROFILE)


# ---------------------------------------------------------------------------
# The contract: nothing identifying survives
# ---------------------------------------------------------------------------

def test_anonymised_output_is_clean(anon: str) -> None:
    assert verify_text(anon, CANONICAL_PROFILE) == []


def test_original_fails_verification(cv_text: str) -> None:
    """Control. If this passes, the scanner is not working."""
    leaks = verify_text(cv_text, CANONICAL_PROFILE)
    assert leaks, "scanner found nothing in an un-anonymised CV"
    assert {lk.field for lk in leaks} >= {"surname", "email", "url"}


@pytest.mark.parametrize(
    "term",
    ["Shaba", "Olumide", "Babashola", "olushaba79", "Olu-SHABA", "Stirling", "github.com"],
)
def test_identifying_term_absent(anon: str, term: str) -> None:
    assert term.lower() not in anon.lower()


def test_phone_digits_absent_even_reformatted(anon: str) -> None:
    """Punctuation varies between renderers; the digit run must not survive."""
    digits = "".join(c for c in anon if c.isdigit())
    assert "744403286" not in digits


def test_injected_surname_is_caught(anon: str) -> None:
    """The scan must fail when a leak is deliberately introduced."""
    tampered = anon.replace("## PROFESSIONAL SUMMARY", "## PROFESSIONAL SUMMARY\n\nShaba")
    leaks = verify_text(tampered, CANONICAL_PROFILE)
    assert any(lk.field == "surname" for lk in leaks)


def test_injected_url_is_caught(anon: str) -> None:
    leaks = verify_text(anon + "\n\nhttps://github.com/someone\n", CANONICAL_PROFILE)
    assert any(lk.field == "url" for lk in leaks)


def test_leak_reports_context(cv_text: str) -> None:
    """A leak must say what and where, not merely that one occurred."""
    leak = next(lk for lk in verify_text(cv_text, CANONICAL_PROFILE) if lk.field == "surname")
    assert leak.matched and leak.context


# ---------------------------------------------------------------------------
# The other half: career history must survive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "retained",
    [
        "MTN Communications", "Avanti", "Amdari", "VGC Communications",
        "99.99%", "800,000", "October 2025", "September 2018",
        "B.Sc. Civil Engineering", "Obafemi Awolowo",
        "PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "PROJECTS",
    ],
)
def test_career_content_retained(anon: str, retained: str) -> None:
    assert retained in anon


def test_bullet_count_unchanged(cv_text: str, anon: str) -> None:
    """Anonymisation removes header lines only — no experience is lost."""
    assert anon.count("\n- ") == cv_text.count("\n- ")


def test_role_headings_unchanged(cv_text: str, anon: str) -> None:
    assert anon.count("\n### ") == cv_text.count("\n### ")


# ---------------------------------------------------------------------------
# Profile behaviour
# ---------------------------------------------------------------------------

def test_short_terms_are_not_scanned() -> None:
    """Two-character terms would match everywhere. They are excluded."""
    profile = AnonProfile(surname="Li", forenames=("Al",))
    assert profile.scan_terms() == []


def test_email_local_part_derived() -> None:
    assert AnonProfile(surname="X", email="a.b@c.com").email_local_part == "a.b"


def test_phone_digits_stripped() -> None:
    assert AnonProfile(surname="X", phone="+44-(0)-744").phone_digits == "440744"


def test_anonymise_is_idempotent(anon: str) -> None:
    assert anonymise(anon, CANONICAL_PROFILE) == anon


# ---------------------------------------------------------------------------
# HTML conversion
# ---------------------------------------------------------------------------

def test_markdown_tables_convert(cv_text: str) -> None:
    """Core Competencies is a table; without the extension it renders as text."""
    assert "<table>" in markdown_to_html(cv_text)


def test_html_is_standalone(cv_text: str) -> None:
    html = markdown_to_html(cv_text)
    assert html.startswith("<!DOCTYPE html>")
    assert "charset='utf-8'" in html


# ---------------------------------------------------------------------------
# Error paths — library code must raise, never exit
# ---------------------------------------------------------------------------

def test_missing_markdown_raises(tmp_path: Path) -> None:
    with pytest.raises(RenderError, match="markdown source not found"):
        render(tmp_path / "nope.md", CSS_STD, tmp_path / "out.pdf")


def test_missing_css_raises(tmp_path: Path) -> None:
    src = tmp_path / "cv.md"
    src.write_text("# Test")
    with pytest.raises(RenderError, match="stylesheet not found"):
        render(src, tmp_path / "nope.css", tmp_path / "out.pdf")


def test_anonymisation_error_carries_leaks() -> None:
    from vanguard.render import Leak

    err = AnonymisationError([Leak("surname", "Shaba", "...")], Path("x.pdf"))
    assert err.leaks[0].matched == "Shaba"
    assert "surname" in str(err)


# ---------------------------------------------------------------------------
# End-to-end — requires weasyprint and pypdf
# ---------------------------------------------------------------------------

@needs_pdf
def test_standard_render_produces_pdf(tmp_path: Path) -> None:
    out = render(CV, CSS_STD, tmp_path / "cv.pdf", title="CV")
    assert out.is_file() and out.stat().st_size > 1000


@needs_pdf
def test_anonymised_render_passes_verification(tmp_path: Path) -> None:
    from vanguard.render import render_anonymised

    out = render_anonymised(CV, CSS_ANON, tmp_path / "anon.pdf")
    assert out.is_file()


@needs_pdf
def test_standard_pdf_fails_anonymisation_scan(tmp_path: Path) -> None:
    """The standard profile must NOT pass — proves the scan reads the text layer."""
    from vanguard.render import verify_pdf

    out = render(CV, CSS_STD, tmp_path / "cv.pdf")
    assert verify_pdf(out, CANONICAL_PROFILE), "scan passed a CV that contains the name"
