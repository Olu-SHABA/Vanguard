"""
Submission-type detection.

Directive §3. Classify the required submission format before drafting.
Markers are matched whole-phrase against advert text, case-insensitive,
word-boundary anchored. Bare-substring matching is prohibited.

    STANDARD_CV      default when no other type fires      -> Template B
    NARRATIVE_ESSAY  "statement of suitability", etc.      -> Template C
    SUCCESS_PROFILE  "Success Profiles", "Personal
                     Statement" + word limit, "Behaviours" -> Template F

Four flags, set independently of type:

    ANONYMISE          anonymised CV / anonymous shortlisting
    WORD_LIMIT         extracted by regex. Stated-but-unparseable -> FLAGGED
    ASSESSED_CRITERIA  the explicit list the statement must address, verbatim
    LEAD_CRITERION     pre-sift or merit-order tie-break criterion

A SUCCESS_PROFILE submission requires the CV **and** the statement. It is not
an essay-instead-of-CV route.

Never assume a word limit. Where a limit is stated and cannot be parsed,
`status = FLAGGED` and the operator resolves it — a truncated statement loses
its final paragraph, and the panel never sees it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "SubmissionType",
    "SubmissionSpec",
    "detect",
]


class SubmissionType(str, Enum):
    STANDARD_CV = "STANDARD_CV"
    NARRATIVE_ESSAY = "NARRATIVE_ESSAY"
    SUCCESS_PROFILE = "SUCCESS_PROFILE"

    @property
    def template(self) -> str:
        return {"STANDARD_CV": "B", "NARRATIVE_ESSAY": "C", "SUCCESS_PROFILE": "F"}[self.value]


# --- markers ---------------------------------------------------------------

_SUCCESS_PROFILE_MARKERS = (
    "success profiles",
    "success profile",
    "personal statement",
    "behaviours",
)

_ESSAY_MARKERS = (
    "statement of suitability",
    "supporting statement",
    "attachments are not accepted",
    "we do not accept attachments",
    "cvs are not accepted",
)

_ANONYMISE_MARKERS = (
    "anonymised cv",
    "anonymized cv",
    "anonymous shortlisting",
    "anonymised shortlisting",
    "do not include your name",
    "without your name",
    "name-blind",
)

_LEAD_MARKERS = (
    "pre-sift",
    "presift",
    "primary lead criterion",
    "lead criterion",
    "in the event that two or more candidates",
    "merit order",
)

# "no more than 750 words" | "750 word limit" | "maximum of 750 words"
_WORD_LIMIT_PATTERNS = (
    re.compile(r"no more than\s+(\d{2,5})\s+words", re.I),
    re.compile(r"(\d{2,5})\s+word limit", re.I),
    re.compile(r"maximum of\s+(\d{2,5})\s+words", re.I),
    re.compile(r"within\s+(\d{2,5})\s+words", re.I),
    re.compile(r"up to\s+(\d{2,5})\s+words", re.I),
)

# A limit is *stated* but the number is not parseable (spelled out, or vague)
_WORD_LIMIT_STATED = re.compile(
    r"word limit|word count|no more than\s+\w+\s+words|maximum of\s+\w+\s+words", re.I
)

_BULLET = re.compile(r"^\s*(?:[-*\u2022\u25cf]|\d+[.)])\s+(?P<text>.+?)\s*$")

# Behaviours named in the Civil Service framework
_BEHAVIOURS = (
    "changing and improving",
    "communicating and influencing",
    "delivering at pace",
    "developing self and others",
    "leadership",
    "making effective decisions",
    "managing a quality service",
    "seeing the big picture",
    "working together",
)


def _has(text_low: str, marker: str) -> bool:
    """Whole-phrase, word-boundary anchored. Never bare substring."""
    return re.search(rf"(?<![\w-]){re.escape(marker)}(?![\w-])", text_low) is not None


@dataclass
class SubmissionSpec:
    """Everything the drafting layer needs to choose and fill a template."""

    submission_type: SubmissionType
    anonymise: bool = False
    word_limit: int | None = None
    word_limit_stated_unparseable: bool = False
    assessed_criteria: tuple[str, ...] = ()
    lead_criterion: str = ""
    behaviours: tuple[str, ...] = ()
    markers_fired: tuple[str, ...] = ()

    @property
    def template(self) -> str:
        return self.submission_type.template

    @property
    def flagged(self) -> bool:
        """Ambiguity the operator must resolve before drafting."""
        return self.word_limit_stated_unparseable

    @property
    def flag_reason(self) -> str:
        if self.word_limit_stated_unparseable:
            return "advert states a word limit that could not be parsed — never assumed"
        return ""

    @property
    def requires_cv_and_statement(self) -> bool:
        return self.submission_type is SubmissionType.SUCCESS_PROFILE

    @property
    def words_per_criterion(self) -> int | None:
        """Budget per assessed criterion, per Template F."""
        if self.word_limit and self.assessed_criteria:
            return self.word_limit // len(self.assessed_criteria)
        return None

    def summary(self) -> str:
        bits = [f"{self.submission_type.value} -> Template {self.template}"]
        if self.anonymise:
            bits.append("ANONYMISE")
        if self.word_limit:
            bits.append(f"WORD_LIMIT={self.word_limit}")
        if self.word_limit_stated_unparseable:
            bits.append("WORD_LIMIT=FLAGGED")
        if self.assessed_criteria:
            bits.append(f"{len(self.assessed_criteria)} assessed criteria")
        if self.lead_criterion:
            bits.append("LEAD_CRITERION set")
        if self.behaviours:
            bits.append(f"behaviours: {len(self.behaviours)}")
        return "  |  ".join(bits)


# ---------------------------------------------------------------------------

def detect(advert_text: str) -> SubmissionSpec:
    """Classify submission format and extract the four independent flags."""
    low = advert_text.lower()
    fired: list[str] = []

    # --- type -------------------------------------------------------------
    sp_hits = [m for m in _SUCCESS_PROFILE_MARKERS if _has(low, m)]
    essay_hits = [m for m in _ESSAY_MARKERS if _has(low, m)]

    word_limit, unparseable = _word_limit(advert_text)

    # "Personal Statement" alone is weak; with a word limit or Behaviours it
    # is decisive. "Success Profiles" is decisive on its own.
    strong_sp = (
        _has(low, "success profiles")
        or _has(low, "success profile")
        or (_has(low, "personal statement") and word_limit is not None)
        or (_has(low, "behaviours") and _named_behaviours(low))
    )

    if strong_sp:
        stype = SubmissionType.SUCCESS_PROFILE
        fired += sp_hits
    elif essay_hits:
        stype = SubmissionType.NARRATIVE_ESSAY
        fired += essay_hits
    else:
        stype = SubmissionType.STANDARD_CV

    # --- flags ------------------------------------------------------------
    anon_hits = [m for m in _ANONYMISE_MARKERS if _has(low, m)]
    fired += anon_hits

    lead_hits = [m for m in _LEAD_MARKERS if _has(low, m)]
    fired += lead_hits

    criteria = _assessed_criteria(advert_text)
    lead = _lead_criterion(advert_text) if lead_hits else ""
    behaviours = _named_behaviours(low)

    return SubmissionSpec(
        submission_type=stype,
        anonymise=bool(anon_hits),
        word_limit=word_limit,
        word_limit_stated_unparseable=unparseable,
        assessed_criteria=criteria,
        lead_criterion=lead,
        behaviours=behaviours,
        markers_fired=tuple(dict.fromkeys(fired)),
    )


def _word_limit(text: str) -> tuple[int | None, bool]:
    """Return (limit, stated_but_unparseable). Never assumes a value."""
    for pattern in _WORD_LIMIT_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                value = int(m.group(1))
            except ValueError:
                continue
            if 20 <= value <= 20000:
                return value, False
    return (None, bool(_WORD_LIMIT_STATED.search(text)))


def _named_behaviours(text_low: str) -> tuple[str, ...]:
    return tuple(b.title() for b in _BEHAVIOURS if _has(text_low, b))


def _assessed_criteria(text: str) -> tuple[str, ...]:
    """Extract the criterion list a statement must address, verbatim.

    Anchored on the sentence introducing it — 'address the following criteria',
    'using a separate paragraph for each' — then the bullets beneath.
    """
    # Ordered by precedence. Statement-stage anchors are checked before
    # interview-stage ones: `assessed_criteria` is what the WRITTEN statement
    # must address, not what a later panel scores. On the MoJ advert both
    # exist, and taking the first match in document order picks the wrong list.
    anchor_groups = (
        (  # statement stage — authoritative
            "specifically address the following",
            "address the following criteria",
            "separate paragraph for each",
        ),
        (  # interview stage — fallback only
            "assessed against the following",
            "sift criteria",
        ),
    )
    lines = text.split("\n")
    low = [ln.lower() for ln in lines]

    for anchors in anchor_groups:
        start = next((i + 1 for i, ln in enumerate(low) if any(a in ln for a in anchors)), None)
        if start is None:
            continue
        found = _bullets_after(lines, start)
        if found:
            return found
    return ()


def _bullets_after(lines: list[str], start: int) -> tuple[str, ...]:
    """Collect the bullet block following `start`, tolerating blank lines."""
    out: list[str] = []
    blanks = 0
    for ln in lines[start:]:
        if not ln.strip():
            blanks += 1
            if blanks > 3 and out:
                break
            continue
        m = _BULLET.match(ln)
        if m:
            blanks = 0
            body = m.group("text").strip()
            if len(body) >= 12:
                out.append(body)
        elif out:
            break
    return tuple(out)


def _lead_criterion(text: str) -> str:
    """The criterion named for pre-sift or merit-order tie-break, verbatim."""
    patterns = (
        re.compile(r"pre-?sift based on\s+(?P<c>.+?)\s+will be conducted", re.I | re.S),
        re.compile(r"pre-?sift based on\s+(?P<c>.+?)(?:\.|\n\n)", re.I | re.S),
        re.compile(
            r"identical interview scores,\s*(?P<c>.+?)\s+will be applied", re.I | re.S
        ),
    )
    for p in patterns:
        m = p.search(text)
        if m:
            return re.sub(r"\s+", " ", m.group("c")).strip()
    return ""
