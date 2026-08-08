"""
Render chain: canonical Markdown CV -> HTML -> PDF.

Two profiles:

  STANDARD    full document, all identifying detail retained
  ANONYMISED  name, address, email, telephone and all portfolio URLs
              suppressed. Employer names, dates, titles, achievements and
              metrics retained — those are career history, not identity.

Design note — why suppression happens in the Markdown, not the CSS
------------------------------------------------------------------
`display:none` hides an element visually but leaves the text in the PDF's
text layer. A sift panel copying text out of the document recovers it. So
identifying content is removed BEFORE rendering, and the rendered output is
then scanned to prove it is gone.

Verification is separate from suppression on purpose: `verify_text` is a pure
function over a string, so the leak-detection logic is testable without
producing a PDF at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "AnonProfile",
    "protect_compounds",
    "Leak",
    "RenderError",
    "AnonymisationError",
    "anonymise",
    "verify_text",
    "verify_pdf",
    "render",
    "render_anonymised",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RenderError(RuntimeError):
    """Rendering failed. Never raised for a leak — see AnonymisationError."""


class AnonymisationError(RuntimeError):
    """Identifying content survived into a document that must not carry it.

    Carries the offending spans so the caller can report exactly what leaked
    rather than only that something did.
    """

    def __init__(self, leaks: list[Leak], path: Path | None = None) -> None:
        self.leaks = leaks
        self.path = path
        detail = "; ".join(f"{lk.field}={lk.matched!r}" for lk in leaks)
        where = f" in {path}" if path else ""
        super().__init__(f"anonymisation failed{where}: {detail}")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Leak:
    """One piece of identifying content found where it should not be."""

    field: str
    matched: str
    context: str


@dataclass(frozen=True)
class AnonProfile:
    """Identifying values to suppress and then scan for.

    `handles` covers portfolio and repository identifiers. These matter
    independently of the name: a handle derived from the applicant's name is
    identifying even after the name itself is removed.
    """

    surname: str
    forenames: tuple[str, ...] = ()
    email: str = ""
    phone: str = ""
    handles: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()

    @property
    def email_local_part(self) -> str:
        return self.email.split("@", 1)[0] if "@" in self.email else self.email

    @property
    def phone_digits(self) -> str:
        return re.sub(r"\D", "", self.phone)

    def scan_terms(self) -> list[tuple[str, str]]:
        """(field name, literal) pairs to search for in rendered output.

        Phone is handled separately — digits must be compared after stripping
        punctuation, since a renderer may reformat the separators.
        """
        terms: list[tuple[str, str]] = [("surname", self.surname)]
        terms += [("forename", f) for f in self.forenames]
        if self.email:
            terms.append(("email", self.email))
            terms.append(("email_local_part", self.email_local_part))
        terms += [("handle", h) for h in self.handles]
        terms += [("location", loc) for loc in self.locations]
        return [(k, v) for k, v in terms if v and len(v) >= 3]


# Profile for this project's canonical CV. Derived from data/canonical_cv.md.
CANONICAL_PROFILE = AnonProfile(
    surname="Shaba",
    forenames=("Olumide", "Babashola"),
    email="olushaba79@gmail.com",
    phone="+44-(0)-744-403-2866",
    handles=("Olu-SHABA",),
    locations=("Stirling",),
)


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

_URL = re.compile(r"https?://\S+")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(\s*<?https?://[^)]*>?\s*\)")


def anonymise(markdown_text: str, profile: AnonProfile) -> str:
    """Remove identifying content from Markdown before rendering.

    Strategy:
      1. Drop the H1 title line — on this CV it is the applicant's name.
      2. Drop the contact line that follows it.
      3. Strip every URL and Markdown link, anywhere in the document.
      4. Redact any residual occurrence of a profile literal.

    Employer names, dates, titles, achievements and metrics are untouched.
    """
    lines = markdown_text.splitlines()
    out: list[str] = []
    dropped_title = False

    for line in lines:
        stripped = line.strip()

        # 1. H1 title — the name
        if not dropped_title and stripped.startswith("# ") and not stripped.startswith("##"):
            dropped_title = True
            continue

        # 2. Contact line — pipe-separated, carrying email / phone / URL
        if _is_contact_line(stripped, profile):
            continue

        out.append(line)

    text = "\n".join(out)

    # 3. URLs anywhere else (e.g. the Projects section)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)

    # 4. Residual literals
    for _field, literal in profile.scan_terms():
        text = re.sub(re.escape(literal), "[redacted]", text, flags=re.IGNORECASE)

    # Tidy artefacts left by removal
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.lstrip("\n")


def _is_contact_line(line: str, profile: AnonProfile) -> bool:
    """A contact line carries at least two identifying signals."""
    if not line or line.startswith("#"):
        return False
    signals = 0
    low = line.lower()
    if profile.email and profile.email.lower() in low:
        signals += 1
    if profile.phone_digits and _digits(line).find(profile.phone_digits[-9:]) >= 0:
        signals += 1
    if _URL.search(line):
        signals += 1
    if any(loc.lower() in low for loc in profile.locations):
        signals += 1
    return signals >= 2


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_text(text: str, profile: AnonProfile) -> list[Leak]:
    """Return every identifying span found in `text`. Empty list means clean.

    Pure function — no filesystem, no PDF library. This is where the
    leak-detection logic lives so it can be tested directly.
    """
    leaks: list[Leak] = []
    # Normalise the non-breaking hyphen so a scan is not defeated by rendering.
    low = text.lower().replace(NB_HYPHEN, "-")

    for field_name, literal in profile.scan_terms():
        idx = low.find(literal.lower())
        if idx >= 0:
            leaks.append(Leak(field_name, literal, _context(text, idx, len(literal))))

    digits = _digits(text)
    tail = profile.phone_digits[-9:] if len(profile.phone_digits) >= 9 else profile.phone_digits
    if tail and tail in digits:
        leaks.append(Leak("phone", profile.phone, "digit sequence present after punctuation strip"))

    match = _URL.search(text)
    if match:
        leaks.append(Leak("url", match.group(0), _context(text, match.start(), len(match.group(0)))))

    return leaks


def _context(text: str, start: int, length: int, window: int = 30) -> str:
    lo = max(0, start - window)
    hi = min(len(text), start + length + window)
    return text[lo:hi].replace("\n", " ").strip()


def verify_pdf(pdf_path: Path, profile: AnonProfile) -> list[Leak]:
    """Extract the PDF text layer and scan it. Empty list means clean.

    Scans the text layer specifically — visual absence is not sufficient,
    because hidden text remains copyable.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RenderError("pypdf required for PDF verification: pip install pypdf") from exc

    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise RenderError(f"not a file: {pdf_path}")

    try:
        reader = PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise RenderError(f"could not read text layer from {pdf_path}: {exc}") from exc

    return verify_text(text, profile)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_MD_EXTENSIONS = ["tables", "attr_list", "sane_lists"]

NB_HYPHEN = "\u2011"  # NON-BREAKING HYPHEN

# A compound word: letters, a hyphen, letters. Excludes en/em dashes used as
# punctuation, and date ranges.
_COMPOUND = re.compile(r"(?<=[A-Za-z])-(?=[A-Za-z])")


def protect_compounds(text: str) -> str:
    """Replace hyphens inside compound words with U+2011 non-breaking hyphen.

    A compound broken across a line loses its hyphen in the PDF text layer:
    'cloud-based' extracts as 'cloudbased', 'real-time' as 'realtime'. The page
    looks correct; the text layer does not.

    That matters more here than typography. ATS parse the text layer, and so
    does this project's own coverage engine — a requirement for 'real-time'
    would score as a miss against a CV that visibly contains it.

    U+2011 renders identically to a hyphen and forbids a break at that point.
    """
    return _COMPOUND.sub(NB_HYPHEN, text)


def markdown_to_html(markdown_text: str, title: str = "") -> str:
    """Convert Markdown to a standalone HTML document."""
    try:
        import markdown as md
    except ImportError as exc:  # pragma: no cover
        raise RenderError("markdown required: pip install markdown") from exc

    body = md.markdown(protect_compounds(markdown_text), extensions=_MD_EXTENSIONS)
    return (
        "<!DOCTYPE html>\n<html lang='en'><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body>\n{body}\n</body></html>\n"
    )


def render(
    md_path: Path | str,
    css_path: Path | str,
    out_path: Path | str,
    *,
    title: str = "",
) -> Path:
    """Render a Markdown file to PDF. Returns the output path.

    Raises RenderError on any failure. Never calls sys.exit — this is library
    code and must be safe to import into a scheduler or test runner.
    """
    md_path, css_path, out_path = Path(md_path), Path(css_path), Path(out_path)

    if not md_path.is_file():
        raise RenderError(f"markdown source not found: {md_path}")
    if not css_path.is_file():
        raise RenderError(f"stylesheet not found: {css_path}")

    try:
        from weasyprint import CSS, HTML
    except ImportError as exc:  # pragma: no cover
        raise RenderError("weasyprint required: pip install weasyprint") from exc

    html = markdown_to_html(md_path.read_text(encoding="utf-8"), title=title)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=html, base_url=str(md_path.parent)).write_pdf(
            str(out_path), stylesheets=[CSS(filename=str(css_path))]
        )
    except PermissionError as exc:
        # Overwhelmingly the cause on Windows: the previous render is still open
        # in a PDF viewer, which holds an exclusive lock on the file.
        raise RenderError(
            f"could not write {out_path}: permission denied. The file is most "
            "likely open in a PDF viewer — close it and re-run. If not, check "
            "write permissions on the output directory."
        ) from exc
    except OSError as exc:
        raise RenderError(f"could not write {out_path}: {exc}") from exc
    except Exception as exc:
        raise RenderError(f"PDF generation failed for {md_path}: {exc}") from exc

    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RenderError(f"render produced no output at {out_path}")

    return out_path


def render_anonymised(
    md_path: Path | str,
    css_path: Path | str,
    out_path: Path | str,
    profile: AnonProfile = CANONICAL_PROFILE,
    *,
    keep_intermediate: Path | str | None = None,
) -> Path:
    """Render an anonymised PDF, then verify it. Raises if anything leaked.

    The artefact is written before verification so the offending file can be
    inspected, but a failed scan raises — the caller must not treat a
    returned path as validated unless no exception was raised.
    """
    md_path, out_path = Path(md_path), Path(out_path)

    if not md_path.is_file():
        raise RenderError(f"markdown source not found: {md_path}")

    suppressed = anonymise(md_path.read_text(encoding="utf-8"), profile)

    residual = verify_text(suppressed, profile)
    if residual:
        raise AnonymisationError(residual, md_path)

    tmp = Path(keep_intermediate) if keep_intermediate else out_path.with_suffix(".anon.md")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(suppressed, encoding="utf-8")

    try:
        render(tmp, css_path, out_path, title="Curriculum Vitae")
        leaks = verify_pdf(out_path, profile)
        if leaks:
            raise AnonymisationError(leaks, out_path)
    finally:
        if keep_intermediate is None:
            tmp.unlink(missing_ok=True)

    return out_path
