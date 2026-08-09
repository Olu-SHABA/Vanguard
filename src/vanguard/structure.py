"""
Advert structure parsing.

Job boards return HTML. The previous approach flattened it with regexes, which
destroyed the one thing that matters: **the binding between a heading and the
list beneath it.**

Reed markup looks like this — headings are inline `<strong>` followed by line
breaks, not `<h3>` or `<p>`:

    <strong>What you will do </strong><br /><br />
    <ul><li>Lead the preparation of financial information...</li></ul>
    <strong>What we offer</strong><br /><br />
    <ul><li>25 days holiday</li></ul>

Flattened, both lists are identical bullet runs. The parser counted holiday
entitlement as a requirement, inflated |R| to 38, and produced C=0.026 with a
ceiling of 1.000 — the system believing an AI Marketing Operations Manager
role was fully attainable by rewording the CV.

Sections are therefore parsed AND classified. Only requirement-bearing
sections contribute to coverage.

Uses `html.parser` from the standard library. No new dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from html.parser import HTMLParser

__all__ = [
    "SectionKind",
    "Block",
    "AdvertStructure",
    "parse_advert",
    "is_probable_heading",
    "classify_heading",
]


class SectionKind(str, Enum):
    REQUIREMENT = "requirement"      # what the applicant must have
    RESPONSIBILITY = "responsibility"  # what the job involves
    BENEFIT = "benefit"              # what the employer offers
    PROCESS = "process"              # how to apply, closing dates
    COMPANY = "company"              # about us, culture
    UNKNOWN = "unknown"

    @property
    def carries_requirements(self) -> bool:
        """Only these contribute to coverage.

        Responsibilities are deliberately excluded. "Lead the preparation of
        financial statements" describes the job, not a qualification the
        applicant must already hold, and counting it as one is what drove
        coverage to 0.026 on adverts with long duty lists.
        """
        return self is SectionKind.REQUIREMENT


# Ordered by specificity — the first match wins, so narrow phrases precede
# broad ones. "what you will do" must be tested before a bare "you will".
_HEADING_RULES: tuple[tuple[SectionKind, tuple[str, ...]], ...] = (
    (SectionKind.BENEFIT, (
        "what we offer", "what you will get", "what's in it for you",
        "whats in it for you", "benefits", "package", "reward", "perks",
        "salary and benefits", "why join", "what we give you",
    )),
    (SectionKind.PROCESS, (
        "how to apply", "application process", "next steps", "closing date",
        "how we hire", "the process", "recruitment process", "to apply",
        "interview process", "selection process", "equal opportunit",
        "diversity", "privacy", "gdpr",
    )),
    (SectionKind.RESPONSIBILITY, (
        "what you will do", "what you'll do", "what youll do",
        "key responsibilities", "responsibilities", "the role", "role overview",
        "duties", "day to day", "day-to-day", "your role", "the opportunity",
        "job description", "main tasks", "accountabilities", "what the role",
        "purpose of the role", "role purpose",
    )),
    (SectionKind.REQUIREMENT, (
        "what you will need", "what you'll need", "what youll need",
        "what you will have", "what you'll have", "what youll have",
        "what we are looking for", "what we're looking for",
        "person specification", "essential criteria", "essential skills",
        "essential experience", "essential", "desirable", "requirements",
        "required skills", "skills and experience", "experience required",
        "about you", "you will have", "you'll have", "your experience",
        "qualifications", "key skills", "core skills", "technical skills",
        "candidate profile", "the ideal candidate", "ideal candidate",
        "who you are", "we are looking for", "you should have",
        "knowledge and experience", "capabilities",
    )),
    (SectionKind.COMPANY, (
        "about us", "about the company", "who we are", "our culture",
        "our values", "the company", "company overview", "our team",
    )),
)

_WS = re.compile(r"\s+")
_NBSP = "\u00a0"


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "").replace(_NBSP, " ")).strip()


def classify_heading(heading: str) -> SectionKind:
    """Map a heading to a section kind. Unrecognised headings are UNKNOWN.

    UNKNOWN is not treated as a requirement section. An advert whose headings
    are all unrecognised yields no requirements and is reported unreliable,
    which is the honest outcome — better than counting its benefits.
    """
    low = _norm(heading).lower().rstrip(":?. ")
    if not low:
        return SectionKind.UNKNOWN
    for kind, phrases in _HEADING_RULES:
        for phrase in phrases:
            if phrase in low:
                return kind
    return SectionKind.UNKNOWN


@dataclass
class Block:
    """One heading and the content beneath it."""

    heading: str = ""
    kind: SectionKind = SectionKind.UNKNOWN
    bullets: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.bullets and not self.paragraphs

    def text(self) -> str:
        return "\n".join([*self.paragraphs, *(f"- {b}" for b in self.bullets)])


@dataclass
class AdvertStructure:
    """A parsed advert: ordered blocks plus flat text for fallback use."""

    blocks: list[Block]
    plain_text: str

    def of_kind(self, *kinds: SectionKind) -> list[Block]:
        return [b for b in self.blocks if b.kind in kinds]

    @property
    def requirement_bullets(self) -> list[str]:
        """Bullets under requirement headings only."""
        return [b for block in self.blocks if block.kind.carries_requirements
                for b in block.bullets]

    @property
    def requirement_text(self) -> str:
        return "\n".join(b.text() for b in self.of_kind(SectionKind.REQUIREMENT))

    @property
    def has_requirement_section(self) -> bool:
        return any(b.kind.carries_requirements and not b.is_empty for b in self.blocks)

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for block in self.blocks:
            counts[block.kind.value] = counts.get(block.kind.value, 0) + 1
        return "  ".join(f"{k}:{v}" for k, v in sorted(counts.items()))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_EMPHASIS_TAGS = {"strong", "b"}
_BREAK_TAGS = {"br", "p", "div", "tr", "li", "ul", "ol", "table"}
_SKIP_CONTENT = {"script", "style"}

# An inline <strong> only counts as a heading if it is short and stands alone.
MAX_HEADING_CHARS = 90
MIN_HEADING_CHARS = 4

# Diagnostics from the first live run showed the detector firing on job
# titles, field labels, recruiter names and bare punctuation — `,` appeared
# three times. A false heading starts a new block and orphans the content
# that belonged to the real one, which is how `empty_requirement_section`
# arises. These reject the observed classes.

# "Location:", "Daily Rate:", "Databases:" — a label introducing a value,
# not a section. Two words or fewer ending in a colon.
_FIELD_LABEL = re.compile(r"^\s*\w+(?:\s+\w+)?\s*:\s*$")

# Bare punctuation or a single symbol.
_PUNCT_ONLY = re.compile(r"^[\W_]+$")

# "Alexander Booth - Talent Acquisition Specialist"
_RECRUITER = re.compile(
    r"\b(?:talent acquisition|recruitment consultant|recruiter|hiring manager|"
    r"resourcing)\b", re.I)

# "3-month initial contract", "6 month initial"
_CONTRACT_TERM = re.compile(r"^\d+[\s-]*(?:month|week|year|day)s?\b", re.I)

# Shouted boilerplate: mostly capitals, sentence length.
_SHOUTED = re.compile(r"^[^a-z]{25,}$")


def is_probable_heading(text: str, *, job_title: str = "") -> bool:
    """Reject runs that look like emphasis, labels or boilerplate.

    A false positive is not harmless: it opens a new block, so the bullets
    that belonged to the previous heading are attributed to the wrong section
    or lost entirely.
    """
    candidate = _norm(text)
    if not candidate or len(candidate) < MIN_HEADING_CHARS:
        return False
    if len(candidate) > MAX_HEADING_CHARS:
        return False
    if _PUNCT_ONLY.match(candidate):
        return False
    if _FIELD_LABEL.match(candidate):
        return False
    if _CONTRACT_TERM.match(candidate):
        return False
    if _RECRUITER.search(candidate):
        return False
    if _SHOUTED.match(candidate):
        return False
    # A run matching the job title is the advert's own title, repeated.
    if job_title and _norm(job_title).lower() == candidate.lower():
        return False
    # A single word is usually a label — but not when it is a known section
    # name. "Essential", "Requirements", "Benefits" and "Responsibilities"
    # are all single words and all legitimate headings.
    if len(candidate.split()) < 2:
        return classify_heading(candidate) is not SectionKind.UNKNOWN
    return True


class _AdvertParser(HTMLParser):
    """Walks the document, binding each list to the heading above it."""

    def __init__(self, job_title: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.job_title = job_title
        self.blocks: list[Block] = [Block()]
        self._buffer: list[str] = []
        self._emphasis_depth = 0
        self._emphasis_text: list[str] = []
        self._in_list_item = False
        self._skip_depth = 0
        self._plain: list[str] = []

    # -- helpers -----------------------------------------------------------

    @property
    def _current(self) -> Block:
        return self.blocks[-1]

    def _flush(self) -> None:
        text = _norm("".join(self._buffer))
        self._buffer.clear()
        if not text:
            return
        if self._in_list_item:
            self._current.bullets.append(text)
        else:
            self._current.paragraphs.append(text)

    def _start_block(self, heading: str) -> None:
        self._flush()
        if self._current.is_empty and not self._current.heading:
            self.blocks.pop()
        block = Block(heading=heading, kind=classify_heading(heading))
        self.blocks.append(block)

    # -- HTMLParser interface ----------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            self._flush()
            self._emphasis_depth += 1
            self._emphasis_text = []
        elif tag in _EMPHASIS_TAGS:
            self._flush()
            self._emphasis_depth += 1
            self._emphasis_text = []
        elif tag == "li":
            self._flush()
            self._in_list_item = True
        elif tag in _BREAK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS or tag in _EMPHASIS_TAGS:
            candidate = _norm("".join(self._emphasis_text))
            self._emphasis_depth = max(0, self._emphasis_depth - 1)
            self._emphasis_text = []
            if not candidate:
                return
            # A short emphasised run that is not inside a bullet is a heading.
            # Inline <strong> mid-sentence is not — it is emphasis.
            if (
                tag in _HEADING_TAGS
                or (not self._in_list_item and not self._buffer
                    and is_probable_heading(candidate, job_title=self.job_title))
            ):
                self._start_block(candidate)
            else:
                self._buffer.append(candidate + " ")
            self._plain.append(candidate)
            return
        if tag == "li":
            self._flush()
            self._in_list_item = False
        elif tag in _BREAK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br" and not self._skip_depth:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._emphasis_depth:
            self._emphasis_text.append(data)
        else:
            self._buffer.append(data)
        self._plain.append(data)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def parse_advert(body: str, *, job_title: str = "") -> AdvertStructure:
    """Parse advert HTML into classified blocks.

    `job_title` lets the parser reject a repeated title as a heading — Reed
    adverts commonly restate the role in bold before the body.

    Plain text input is returned as a single UNKNOWN block, so callers can
    treat structured and unstructured adverts uniformly.
    """
    if not body or not body.strip():
        return AdvertStructure([], "")

    parser = _AdvertParser(job_title=job_title)
    try:
        parser.feed(body)
        parser.close()
    except Exception:
        # Malformed markup must not lose the advert. Fall back to flat text.
        flat = _norm(re.sub(r"<[^>]+>", " ", body))
        return AdvertStructure([Block(paragraphs=[flat])], flat)

    blocks = [b for b in parser.blocks if not (b.is_empty and not b.heading)]
    plain = _norm(" ".join(parser._plain))
    return AdvertStructure(blocks, plain)
