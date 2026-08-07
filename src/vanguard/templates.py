"""
Template rendering — B, C and F.

The injection constraint is enforced **in code, not by convention**:

    A MAPPED_ACHIEVEMENT that does not resolve to a CV line raises rather
    than rendering.

That is the difference between a rule written in a template header and a rule
that cannot be broken. Templates B, C and F all carry the constraint in prose;
this module makes it structural.

Three rules, all raising `InjectionError`:

    1. Every injected achievement must trace to a canonical CV line.
    2. No Type 3 gap may be written into an outbound artefact.
    3. Every figure in the text must appear in the CV it is submitted with.

Rule 3 is the one that catches the failure this project began with: a template
asserting a 92% improvement that existed nowhere in the CV. A number is the
easiest thing to invent and the easiest to check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from vanguard.cv import CanonicalCV
from vanguard.gaps import Gap, GapType
from vanguard.submission import SubmissionSpec, SubmissionType

__all__ = [
    "InjectionError",
    "Achievement",
    "render_cover_letter",
    "render_essay",
    "render_success_profile",
    "render_for",
    "verify_figures",
]


class InjectionError(ValueError):
    """Content was injected that the canonical CV does not support."""


# A figure is any number that makes a claim: percentages, counts, durations.
_FIGURE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:%|k\b|m\b|\+)?", re.I)
_TRIVIAL = frozenset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0"})


@dataclass(frozen=True)
class Achievement:
    """One injected bullet, bound to the CV line that justifies it."""

    text: str
    source_role: str
    cv_evidence: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InjectionError("achievement text is empty")
        if not self.source_role.strip():
            raise InjectionError(f"achievement {self.text[:40]!r} has no source role citation")
        if not self.cv_evidence.strip():
            raise InjectionError(f"achievement {self.text[:40]!r} has no CV evidence")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def verify_figures(text: str, cv: CanonicalCV) -> list[str]:
    """Return figures present in `text` but absent from the CV.

    Bare small integers are ignored — 'three points from my background' is
    prose, not a claim. Percentages, thousands and large counts are claims.
    """
    cv_text = _normalise(cv.full_text())
    cv_digits = re.sub(r"[^\d%.]", "", cv_text)
    offending: list[str] = []

    for raw in _FIGURE.findall(text):
        token = raw.strip()
        bare = token.rstrip("%k m+").strip()
        if not bare or bare in _TRIVIAL:
            continue
        compact = re.sub(r"[^\d%.]", "", token)
        if compact and compact not in cv_digits:
            offending.append(token)

    return sorted(set(offending))


def _assert_supported(
    achievements: Sequence[Achievement],
    cv: CanonicalCV,
    gaps: Sequence[Gap] = (),
) -> None:
    """Rules 1–3. Raises on the first violation, naming it."""
    cv_text = _normalise(cv.full_text())

    unmet = {g.term.lower() for g in gaps if g.gap_type is GapType.NOT_EVIDENCED}

    for a in achievements:
        if _normalise(a.cv_evidence)[:60] not in cv_text:
            raise InjectionError(
                f"achievement cites evidence absent from the canonical CV: "
                f"{a.cv_evidence[:70]!r}"
            )
        for term in unmet:
            if term and re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", a.text.lower()):
                raise InjectionError(
                    f"Type 3 gap {term!r} written into an outbound artefact — "
                    "no CV edit is permitted and no unevidenced claim may be made"
                )
        stray = verify_figures(a.text, cv)
        if stray:
            raise InjectionError(
                f"figure(s) {stray} appear in the artefact but not in the CV "
                "submitted alongside it"
            )


# ---------------------------------------------------------------------------
# Template B — cover letter
# ---------------------------------------------------------------------------

def render_cover_letter(
    *,
    job_title: str,
    company: str,
    applicant_name: str,
    contact: str,
    achievements: Sequence[Achievement],
    cv: CanonicalCV,
    gaps: Sequence[Gap] = (),
    hiring_manager: str = "Hiring Manager",
) -> str:
    """Template B. Exactly three mapped achievements, each CV-traceable."""
    if len(achievements) != 3:
        raise InjectionError(f"Template B takes exactly 3 achievements, got {len(achievements)}")
    _assert_supported(achievements, cv, gaps)

    bullets = "\n".join(f"* {a.text}" for a in achievements)
    return f"""**Subject:** Application for {job_title} - {applicant_name}

Dear {hiring_manager},

I am applying for the {job_title} position at {company}. Having moved from \
high-availability network infrastructure management into data science, I build \
automated data pipelines and analytical frameworks that hold service reliability \
while improving operational efficiency.

Three points from my background map directly to the requirements in your advertisement:

{bullets}

My CV sets out the full record across satellite operations, multi-vendor network \
management, and applied machine learning. I would welcome the chance to discuss how \
that combination fits what your team is building.

Sincerely,

{applicant_name}
{contact}
"""


# ---------------------------------------------------------------------------
# Template C — narrative essay
# ---------------------------------------------------------------------------

def render_essay(
    *,
    job_title: str,
    company: str,
    achievements: Sequence[Achievement],
    cv: CanonicalCV,
    key_challenge: str = "",
    approach: Sequence[str] = (),
    gaps: Sequence[Gap] = (),
) -> str:
    """Template C. Every metric in §3 must trace to a CV line."""
    _assert_supported(achievements, cv, gaps)

    metrics = ", ".join(a.text for a in achievements)
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(approach, 1)) or "1. {{ TECHNICAL_APPROACH }}"
    challenge = key_challenge or "the operational challenge described in your advertisement"

    return f"""# STATEMENT OF QUALIFICATION & STRUCTURAL SUITABILITY

**Target Position:** {job_title}
**Target Enterprise:** {company}

### 1. Executive Synthesis & Core Thesis

Maintaining the systemic reliability of mission-critical systems demands moving away \
from static operations and stepping into high-performance, data-driven frameworks. My \
professional narrative is built on this exact transition — leveraging over two decades \
of engineering rigor in satellite operations and infrastructure planning to build \
robust, automated data science assets. I am applying for the {job_title} position \
because your current operational directives require a senior specialist who can manage \
data complexity while protecting institutional uptime.

### 2. Methodological Alignment & Problem Solving

My approach to the responsibilities outlined in this vacancy is governed by structural \
validation. When tasked with analyzing complex environments, I deploy advanced \
mathematical pipelines, vectorized automation models, and zero-assumption diagnostics \
to isolate root causes and optimize workflows.

For example, when addressing {challenge}, my execution strategy involves:

{steps}

### 3. Quantifiable Value Injection

I do not merely monitor infrastructure; I transform it to secure measurable business \
outcomes. Throughout my career, my interventions have driven clear metrics — including \
{metrics}. I bring this same statistical focus and commitment to absolute objectivity \
to the teams at {company}.

### 4. Strategic Conclusion

My qualification is built on the convergence of engineering depth and data precision. \
I am fully equipped to ingest your current system challenges and output scalable, \
optimized solutions. Thank you for your consideration.
"""


# ---------------------------------------------------------------------------
# Template F — Success Profile
# ---------------------------------------------------------------------------

def render_success_profile(
    *,
    job_title: str,
    company: str,
    spec: SubmissionSpec,
    paragraphs: Sequence[str],
    cv: CanonicalCV,
    gaps: Sequence[Gap] = (),
    vacancy_ref: str = "",
) -> str:
    """Template F. One paragraph per assessed criterion, budget enforced.

    Raises if a criterion is unaddressed, if any criterion is Type 3, or if
    the statement exceeds the advert's word limit. Over-limit statements are
    truncated by the portal, not the panel — the final paragraph disappears.
    """
    if spec.submission_type is not SubmissionType.SUCCESS_PROFILE:
        raise InjectionError(f"Template F requires SUCCESS_PROFILE, got {spec.submission_type.value}")

    criteria = spec.assessed_criteria
    if len(paragraphs) != len(criteria):
        raise InjectionError(
            f"{len(criteria)} assessed criteria but {len(paragraphs)} paragraphs — "
            "one paragraph per criterion, in advert order"
        )

    unmet = {g.term.lower() for g in gaps if g.gap_type is GapType.NOT_EVIDENCED}
    for i, crit in enumerate(criteria, 1):
        for term in unmet:
            if term and re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", crit.lower()):
                raise InjectionError(
                    f"criterion {i} depends on Type 3 gap {term!r}. Report to the "
                    "operator before drafting — the statement is not written around "
                    "an unevidenced criterion."
                )

    body = "\n\n".join(p.strip() for p in paragraphs)
    stray = verify_figures(body, cv)
    if stray:
        raise InjectionError(f"figure(s) {stray} not present in the submitted CV")

    count = len(body.split())
    if spec.word_limit and count > spec.word_limit:
        raise InjectionError(
            f"statement is {count} words against a {spec.word_limit} limit — "
            "the portal truncates, and the final paragraph is the one that disappears"
        )

    budget = spec.words_per_criterion
    lead = f"\n- Lead criterion: {spec.lead_criterion}" if spec.lead_criterion else ""

    mapping = "\n".join(
        f"| {i} | {c} | {len(p.split())} |"
        for i, (c, p) in enumerate(zip(criteria, paragraphs), 1)
    )

    return f"""# SUBMISSION PACKAGE

**Target Position:** {job_title}
**Target Enterprise:** {company}
**Vacancy Reference:** {vacancy_ref or "—"}
**Statement word limit:** {spec.word_limit or "not stated"}
**Anonymisation required:** {"Y" if spec.anonymise else "N"}

## PART 1 — ANONYMISED CV

Rendered from `canonical_cv.md` via the anonymised render profile. Suppressed: \
full name, postal address, email, telephone, all portfolio and repository URLs. \
Retained: employer names, dates, titles, achievements and metrics.

Output: `[Timestamp]_Anonymised_CV.pdf` — blocked unless the anonymisation scan passes.

## PART 2 — PERSONAL STATEMENT

Budget: {budget or "—"} words per criterion (±15%).{lead}

| # | Criterion (verbatim from advert) | Words |
|---|---|---|
{mapping}

{body}

**Word count:** {count} / {spec.word_limit or "—"}
"""


# ---------------------------------------------------------------------------

def render_for(spec: SubmissionSpec, **kwargs) -> str:
    """Dispatch to the template the submission type requires."""
    if spec.submission_type is SubmissionType.SUCCESS_PROFILE:
        return render_success_profile(spec=spec, **kwargs)
    if spec.submission_type is SubmissionType.NARRATIVE_ESSAY:
        return render_essay(**kwargs)
    return render_cover_letter(**kwargs)
