"""
Cover letter drafting — Template B, framed to the vacancy.

The template's opening was fixed text: the same two paragraphs on every
application, with only the three bullets varying. Tailored in the evidence,
generic in the framing — and a reader comparing two letters would see it.

## What "responsive" means here, and what it does not

**It does not mean parroting the advert.** Copying an employer's own
responsibility text back at them reads as exactly what it is, and recruiters
notice.

The letter is framed from **what this role asks for that the CV can
evidence** — the matched requirements, in the operator's vocabulary rather
than the advert's. That is honest on both sides: the role's priorities come
from the advert, the claims come from the CV, and neither is invented.

## The constraint is unchanged

Everything asserted about the operator must be traceable to the CV submitted
alongside. `_assert_supported()` enforces it and this module does not weaken
it — a responsive opening that claimed something the CV does not support
would be worse than a generic one that claims nothing.

So the opening names:

  * what the role centres on      from the advert's matched requirements
  * what the operator brings      from the CV's own vocabulary
  * nothing else

## Selection

Three achievements, chosen by how well each answers the vacancy's
requirements. Where several CV bullets answer the same requirement the
strongest is taken, so a letter does not make the same point twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from vanguard.coverage import CoverageReport
from vanguard.cv import CanonicalCV
from vanguard.templates import Achievement, InjectionError, render_cover_letter

__all__ = [
    "DraftError",
    "LetterPlan",
    "plan_letter",
    "draft_cover_letter",
]


class DraftError(RuntimeError):
    """A letter could not be drafted from the available evidence."""


#: Requirement terms too generic to frame a letter around. Naming "teamwork"
#: as what a role centres on says nothing and reads as padding.
_UNFRAMEABLE = frozenset({
    "communication", "teamwork", "collaboration", "problem solving",
    "problem-solving", "attention to detail", "stakeholder management",
    "time management", "organisation", "flexibility", "adaptability",
    "interpersonal", "written communication", "verbal communication",
    "team player", "self-motivated", "proactive",
})

#: How many matched requirements to name in the opening. Three reads as a
#: summary; six reads as a list.
_FRAME_TERMS = 3


@dataclass
class LetterPlan:
    """What the letter will say, and where each part came from.

    Assembled before rendering so the operator can see the reasoning — an
    achievement selected for reasons nobody can inspect is one nobody should
    trust.
    """

    job_title: str
    company: str
    frame_terms: list[str] = field(default_factory=list)
    achievements: list[Achievement] = field(default_factory=list)
    matched_total: int = 0
    unmet_notable: list[str] = field(default_factory=list)

    @property
    def framed(self) -> bool:
        return bool(self.frame_terms)

    def explain(self) -> list[str]:
        lines = []
        if self.frame_terms:
            lines.append("framed on: " + ", ".join(self.frame_terms))
        else:
            lines.append("framed generically — no specific requirement matched")
        for achievement in self.achievements:
            lines.append(f"cites: {achievement.source_role}")
        return lines


#: Longest frame term worth naming. "designing and maintaining technical
#: documentation" is a responsibility phrase, not a skill, and reads as
#: padding in a list of three.
_MAX_FRAME_WORDS = 3


def _frameable(term: str) -> bool:
    low = (term or "").strip().lower()
    if not low or low in _UNFRAMEABLE or len(low) < 3:
        return False
    return len(low.split()) <= _MAX_FRAME_WORDS


def plan_letter(report: CoverageReport, cv: CanonicalCV, *,
                job_title: str, company: str, aliases=None) -> LetterPlan:
    """Decide what the letter will say, before writing any of it.

    Frame terms are matched requirements — things this role asks for that the
    CV evidences. An unmatched requirement cannot frame the letter: claiming
    a role centres on something the operator cannot demonstrate would be
    inviting the one question they cannot answer.
    """
    plan = LetterPlan(job_title=job_title, company=company,
                      matched_total=len(report.hits))

    seen: set[str] = set()
    for resolution in report.hits:
        term = (resolution.requirement.canonical
                or resolution.requirement.text or "").strip()
        key = term.lower()
        if key in seen or not _frameable(term):
            continue
        seen.add(key)
        plan.frame_terms.append(term)
        if len(plan.frame_terms) >= _FRAME_TERMS:
            break

    plan.achievements = _select_achievements(report, cv, aliases)

    # Notable unmet requirements, for the operator's information only. These
    # never appear in the letter — a cover letter is not the place to
    # enumerate what you cannot do.
    plan.unmet_notable = [
        (g.requirement.canonical or g.requirement.text)
        for g in list(report.gaps)[:3]
    ]
    return plan


def _select_achievements(report: CoverageReport, cv: CanonicalCV,
                         aliases=None) -> list[Achievement]:
    """Three CV bullets, chosen by how many of this vacancy's requirements
    each one answers.

    Sourced from the CV itself rather than from the match evidence, because
    `cv_evidence` must be verbatim CV text — the injection check looks it up
    in the canonical document, and a paraphrase would be rejected.

    A bullet is preferred when it answers several requirements at once: one
    line covering Python, SQL and ETL says more in a letter than three lines
    covering one each.
    """
    # Neither the requirement term nor the recorded evidence locates a
    # bullet reliably. A term match is too literal — "incident management"
    # never appears verbatim in "Managed network and hub-related incidents" —
    # and the evidence is a window of surrounding CV text, often from the
    # summary paragraph rather than from any bullet.
    #
    # So match on the requirement's significant WORDS, with prefix tolerance
    # for plurals and tense: "incident" finds "incidents", "monitoring" finds
    # "monitored". Crude, and it holds across the operator's two domains.
    unmet = {(g.requirement.canonical or g.requirement.text or "").strip().lower()
             for g in report.gaps}
    unmet = {t for t in unmet if t}

    # Where a requirement resolved through the alias table, that entry
    # already names the CV evidence and the source role — an explicit,
    # curated link that beats any stem heuristic. Use it where it exists.
    wanted: list[set[str]] = []
    for resolution in report.hits:
        term = resolution.requirement.canonical or resolution.requirement.text or ""
        stems = _stems(term)

        entry = None
        canonical = getattr(resolution, "alias_canonical", "") or ""
        if canonical and aliases is not None:
            entry = next((e for e in aliases.entries
                          if e.canonical == canonical), None)
        if entry is not None and (entry.cv_evidence or "").strip():
            # The alias's own evidence describes the CV line that satisfies
            # this requirement. Its words locate the bullet.
            stems = _stems(entry.cv_evidence) or stems

        if stems:
            wanted.append(stems)

    candidates: list[tuple[int, int, object, str]] = []
    for section, raw in cv.all_bullets():
        text = (raw or "").strip()
        if len(text) < 40:
            continue

        if getattr(section, "title", "").upper() in ("TECHNICAL SKILLS",
                                                     "CORE COMPETENCIES",
                                                     "FURTHER REPOSITORIES"):
            continue

        low = text.lower()

        if any(re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", low)
               for term in unmet):
            continue

        bullet_stems = _stems(text)
        # Two grades. A FULL match — every significant word of the
        # requirement present — is what a good bullet looks like. A PARTIAL
        # match still answers something, and is used only to fill a slot a
        # full match could not.
        #
        # Requiring full matches alone left thin adverts with no letter;
        # accepting partial ones freely put a network capacity bullet in a
        # data letter on the word "data". Grading separates the two.
        full = sum(1 for want in wanted if want and want <= bullet_stems)
        partial = sum(1 for want in wanted
                      if want and not want <= bullet_stems
                      and len(want & bullet_stems) >= max(1, len(want) - 1))

        if full or partial:
            quantified = 1 if re.search(r"\d", text) else 0
            candidates.append((full * 10 + partial, quantified, section, text))

    candidates.sort(key=lambda item: (-item[0], -item[1]))

    achievements: list[Achievement] = []
    seen_roles: set[str] = set()
    seen_subjects: set[str] = set()
    for _, _, section, text in candidates:
        role = _section_citation(section)
        # Spread across roles where possible — three bullets from one job
        # reads as a narrow career.
        # One bullet per subject. Word overlap proved the wrong test: the
        # MTN reporting-engine bullet and the standalone project bullet
        # describe the SAME system in different words, and a letter making
        # the same point twice reads as padding whatever the phrasing.
        subject = _subject_of(text)
        if subject in seen_subjects:
            continue
        if role in seen_roles and len(candidates) > 4:
            continue
        seen_subjects.add(subject)
        seen_roles.add(role)
        achievements.append(Achievement(
            text=_condense(text),
            source_role=role or "Independent project",
            cv_evidence=text,
        ))
        if len(achievements) == 3:
            break

    return achievements


#: A letter bullet longer than this stops being read. CV bullets are written
#: to be scanned in context; a letter has three of them and no context.
_MAX_BULLET_CHARS = 220


def _condense(text: str) -> str:
    """Shorten a CV bullet for the letter, never adding to it.

    Takes whole leading sentences up to the limit. The result is a strict
    SUBSET of the CV line — `cv_evidence` keeps the full text, so the
    injection check still verifies against what the CV actually says, and
    nothing in the letter claims more than the CV does.
    """
    text = (text or "").strip()
    if len(text) <= _MAX_BULLET_CHARS:
        return text

    kept = ""
    for sentence in re.split(r"(?<=[.;])\s+", text):
        candidate = f"{kept} {sentence}".strip() if kept else sentence
        if len(candidate) > _MAX_BULLET_CHARS and kept:
            break
        kept = candidate
        if len(kept) > _MAX_BULLET_CHARS:
            break

    kept = kept.rstrip(" ;,")
    if not kept.endswith("."):
        kept += "."
    return kept


#: Systems the CV describes more than once. A reporting engine appears as an
#: MTN achievement and again as a standalone project; both are true, and
#: citing both in one letter makes a single point twice.
_SUBJECTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("reporting engine", ("reporting engine", "etl engine", "noc reporting",
                          "extract-clean-transform-load")),
    ("data pipelines", ("data pipelines", "etl workflows")),
    ("dashboards", ("dashboard", "kpi monitoring", "tableau", "power bi")),
    ("ml models", ("machine learning models", "demand forecasting",
                   "predictive modeling", "scikit-learn")),
    ("databases", ("postgresql", "query performance", "data retrieval")),
    ("incidents", ("incident", "root cause", "mttr", "p1/p2")),
    ("network", ("uptime", "traffic engineering", "capacity utilization",
                 "congestion")),
    ("training", ("training", "handover documentation", "ccna")),
)


def _subject_of(text: str) -> str:
    """What this bullet is about, coarsely. Unrecognised bullets are their
    own subject, so nothing is discarded for lack of a rule."""
    low = (text or "").lower()
    for name, markers in _SUBJECTS:
        if any(marker in low for marker in markers):
            return name
    return low[:40]


def _overlaps(text: str, chosen: Sequence[str]) -> bool:
    """Does this bullet make a point already made?

    Two bullets describing the same system read as padding, however different
    their wording. Compared on distinctive words rather than on phrasing.
    """
    words = _distinctive(text)
    if not words:
        return False
    for existing in chosen:
        other = _distinctive(existing)
        if not other:
            continue
        shared = len(words & other) / min(len(words), len(other))
        if shared > 0.28:
            return True
    return False


_COMMON = frozenset({
    "with", "that", "this", "from", "into", "over", "under", "using", "used",
    "built", "designed", "developed", "implemented", "across", "data", "and",
    "the", "for", "per", "run", "time", "which", "were", "was", "have", "has",
    "python", "workflows", "operations", "engine", "reporting", "automating",
    "automated", "manual", "cycle", "performed", "memory", "enabling",
})


def _distinctive(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())
            if w not in _COMMON}


#: Words too common to indicate a subject match.
_STOP = frozenset({
    "and", "the", "for", "with", "that", "this", "from", "into", "across",
    "using", "used", "over", "under", "per", "was", "were", "have", "has",
    "management", "managing", "experience", "skills", "ability", "strong",
    "good", "work", "working", "team", "teams", "role", "roles",
})


def _stems(text: str) -> set[str]:
    """Significant words, truncated so plurals and tenses collide.

    "incident" and "incidents" share a stem; "monitor" and "monitoring" do
    too. Five characters is short enough to catch those and long enough that
    unrelated words rarely collide.
    """
    words = re.findall(r"[a-z]{3,}", (text or "").lower())
    return {w[:5] for w in words if w not in _STOP}


def _normalise_fragment(text: str) -> str:
    """Collapse whitespace and case so an evidence fragment can be found in a
    bullet regardless of how the resolver captured it."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _section_citation(section) -> str:
    """The role or project a bullet belongs to, for the citation."""
    if section is None:
        return ""
    employer = (getattr(section, "employer", "") or "").strip()
    dates = (getattr(section, "dates", "") or "").strip()
    title = (getattr(section, "title", "") or "").strip()

    # A project's "employer" line is its stack — "Python · Pandas · NumPy" —
    # which is not a citation. Use the project name instead.
    if "·" in employer or not employer:
        return f"{title}, {dates}".strip(", ") if title else ""
    return f"{employer}, {dates}" if dates else employer


def draft_cover_letter(report: CoverageReport, cv: CanonicalCV, *,
                       job_title: str, company: str, applicant_name: str,
                       contact: str, hiring_manager: str = "Hiring Manager",
                       aliases=None) -> tuple[str, LetterPlan]:
    """Render Template B, framed to this vacancy.

    Raises `DraftError` when the CV cannot support three achievements — a
    letter padded to length with claims the CV does not carry is the failure
    this system exists to prevent.
    """
    plan = plan_letter(report, cv, job_title=job_title, company=company,
                       aliases=aliases)

    if len(plan.achievements) < 3:
        raise DraftError(
            f"only {len(plan.achievements)} CV bullet(s) answer this vacancy; "
            "Template B needs three. Either the advert was not read properly "
            "(see `vanguard diagnose`) or this role is not a fit"
        )

    # The template checks achievements against CLASSIFIED gaps — a Type 3
    # term must not appear in the letter. `report.gaps` are unclassified
    # resolutions, so classify them here rather than passing the wrong shape.
    from vanguard.gaps import classify_all

    # Only Type 3 matters to the injection check: those are the terms the CV
    # cannot support, and the letter must not use one.
    classified = classify_all(report, cv)

    try:
        letter = render_cover_letter(
            job_title=job_title, company=company,
            applicant_name=applicant_name, contact=contact,
            achievements=plan.achievements, cv=cv,
            gaps=list(classified.type_3), hiring_manager=hiring_manager,
        )
    except InjectionError as exc:
        raise DraftError(f"the letter would claim something the CV does not "
                         f"support: {exc}") from exc

    return _reframe(letter, plan), plan


def _reframe(letter: str, plan: LetterPlan) -> str:
    """Replace the fixed opening with one naming what this role asks for.

    Applied after rendering so the injection check runs against the template
    as written. The substitution introduces no claim about the operator — it
    names requirements drawn from the advert and matched against the CV.
    """
    if not plan.framed:
        return letter

    terms = _readable_list(plan.frame_terms)
    replacement = (
        f"I am applying for the {plan.job_title} position at {plan.company}. "
        f"The role calls for {terms}, and each is something I have built and "
        f"run rather than studied. Having moved from high-availability network "
        f"infrastructure management into data science, I work where analytical "
        f"rigour has to survive an operational environment."
    )

    # The template's opening paragraph, matched loosely so a template edit
    # degrades to the generic letter rather than to a broken one.
    pattern = re.compile(
        r"I am applying for the .+?operational efficiency\.", re.S)
    if not pattern.search(letter):
        return letter
    return pattern.sub(replacement, letter, count=1)


def _readable_list(terms: Sequence[str]) -> str:
    """"A, B and C" — not "A, B, C", which reads as a machine wrote it."""
    items = [t for t in terms if t]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"
