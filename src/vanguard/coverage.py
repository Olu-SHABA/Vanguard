"""
Coverage engine — the gating metric.

    C = |matched terms| / |R|

Per-term resolution, in strict order:

    1. Exact or lemma match against CV text     -> HIT
    2. Curated alias table lookup               -> HIT
    3. MiniLM per-term cosine >= 0.75           -> SOFT_HIT (flagged)
    -  no match                                 -> GAP (itemised, retained)

Deterministic stages run first so a failure is always explainable. Stage 3
catches equivalences the alias table has not yet learned, but flags rather
than passing silently.

Tier C enforcement is the critical behaviour in this module. An alias entry
marked Tier C is an exclusion: the term is tempting but not equivalent, and
the operator has ruled it unevidenced. A Tier C match returns GAP with the
exclusion reason attached and MUST NOT fall through to stage 3, where an
embedding could rescue it. That fall-through is precisely how a Type 3 gap
becomes a false HIT, which is the failure the whole gate exists to prevent.

The embedding model is injected, not imported. Coverage is fully testable
without torch, and the deterministic stages carry the audit duty anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, Sequence

from vanguard.cv import CanonicalCV
from vanguard.extract import Requirement

__all__ = [
    "Resolution",
    "Outcome",
    "AliasTable",
    "CoverageReport",
    "Embedder",
    "load_aliases",
    "resolve_term",
    "compute_coverage",
    "SOFT_HIT_THRESHOLD",
]

SOFT_HIT_THRESHOLD = 0.75  # authored estimate — requires tuning against real data


class Outcome(str, Enum):
    HIT = "HIT"
    SOFT_HIT = "SOFT_HIT"
    GAP = "GAP"


class Embedder(Protocol):
    """Anything that turns strings into vectors and scores similarity.

    Injected so the deterministic stages are testable without torch. The real
    implementation is `vanguard.rank.SentenceTransformerEmbedder`.
    """

    def similarity(self, a: str, b: str) -> float: ...


@dataclass(frozen=True)
class Resolution:
    """How one requirement resolved, and on what basis."""

    requirement: Requirement
    outcome: Outcome
    stage: int                      # 1 exact/lemma, 2 alias, 3 embedding, 0 none
    evidence: str = ""              # CV span or alias cv_evidence
    source_role: str = ""
    alias_canonical: str = ""
    score: float | None = None
    exclusion_reason: str = ""      # populated only for Tier C blocks

    @property
    def counts_as_matched(self) -> bool:
        return self.outcome in (Outcome.HIT, Outcome.SOFT_HIT)

    @property
    def is_excluded(self) -> bool:
        return bool(self.exclusion_reason)

    def __str__(self) -> str:
        head = f"{self.outcome.value:<8} s{self.stage} {self.requirement.canonical or self.requirement.text[:48]}"
        if self.is_excluded:
            return f"{head}  [Tier C: {self.alias_canonical}]"
        if self.score is not None:
            return f"{head}  ({self.score:.2f})"
        return head


# ---------------------------------------------------------------------------
# Alias table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AliasEntry:
    canonical: str
    tier: str
    aliases: tuple[str, ...]
    cv_evidence: str = ""
    source_role: str = ""
    reason: str = ""
    note: str = ""

    @property
    def excluded(self) -> bool:
        return self.tier.upper() == "C"


@dataclass
class AliasTable:
    entries: tuple[AliasEntry, ...]
    version: str = ""

    def __len__(self) -> int:
        return len(self.entries)

    def lookup(self, term: str) -> AliasEntry | None:
        """Whole-phrase, case-insensitive. Longest alias wins on overlap."""
        low = term.strip().lower()
        best: tuple[int, AliasEntry] | None = None
        for entry in self.entries:
            for alias in entry.aliases:
                a = alias.lower()
                if a == low or re.search(rf"(?<![\w/-]){re.escape(a)}(?![\w-])", low):
                    if best is None or len(a) > best[0]:
                        best = (len(a), entry)
        return best[1] if best else None

    @property
    def excluded_terms(self) -> list[str]:
        return [a for e in self.entries if e.excluded for a in e.aliases]


def load_aliases(path: Path | str) -> AliasTable:
    """Parse alias_table.yaml. Rejects Tier A/B entries lacking CV evidence."""
    import yaml

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"alias table not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: list[AliasEntry] = []

    for raw in data.get("aliases", []):
        tier = str(raw.get("tier", "")).upper()
        entry = AliasEntry(
            canonical=raw.get("canonical", ""),
            tier=tier,
            aliases=tuple(raw.get("aliases", ())),
            cv_evidence=_flatten(raw.get("cv_evidence", "")),
            source_role=_flatten(raw.get("source_role", "")),
            reason=_flatten(raw.get("reason", "")),
            note=_flatten(raw.get("note", "")),
        )
        if tier in ("A", "B") and not entry.cv_evidence:
            raise ValueError(
                f"alias entry {entry.canonical!r} is Tier {tier} with no cv_evidence. "
                "An alias without CV evidence converts a Type 3 gap into a false HIT."
            )
        entries.append(entry)

    return AliasTable(tuple(entries), version=str(data.get("version", "")))


def _flatten(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


# ---------------------------------------------------------------------------
# Stage 1 — exact / lemma
# ---------------------------------------------------------------------------

_PLURAL = re.compile(r"(?:ies|es|s)$")


def _lemma_variants(term: str) -> list[str]:
    """Cheap morphological variants. Avoids a spaCy dependency at this stage.

    Covers the cases that matter for technology and competency terms:
    plurals, -ing/-ed forms, and British/American -ise/-ize spelling.
    """
    t = term.strip().lower()
    out = {t}
    if _PLURAL.search(t):
        out.add(_PLURAL.sub("", t))
        out.add(_PLURAL.sub("y", t))
    else:
        out.update({t + "s", t + "es"})
    if t.endswith("ing"):
        out.update({t[:-3], t[:-3] + "e"})
    if t.endswith("ed"):
        out.update({t[:-2], t[:-1]})
    if "ise" in t:
        out.add(t.replace("ise", "ize"))
    if "ize" in t:
        out.add(t.replace("ize", "ise"))
    if "isation" in t:
        out.add(t.replace("isation", "ization"))
    if "ization" in t:
        out.add(t.replace("ization", "isation"))
    return sorted(v for v in out if len(v) >= 3)


def _find_in_cv(term: str, cv_text_low: str) -> str | None:
    """Return the matched span with context, or None. Word-boundary anchored."""
    for variant in _lemma_variants(term):
        m = re.search(rf"(?<![\w/-]){re.escape(variant)}(?![\w-])", cv_text_low)
        if m:
            lo, hi = max(0, m.start() - 45), min(len(cv_text_low), m.end() + 45)
            return cv_text_low[lo:hi].replace("\n", " ").strip()
    return None


# ---------------------------------------------------------------------------
# Per-term resolution
# ---------------------------------------------------------------------------

def resolve_term(
    req: Requirement,
    cv: CanonicalCV,
    aliases: AliasTable,
    embedder: Embedder | None = None,
    *,
    threshold: float = SOFT_HIT_THRESHOLD,
) -> Resolution:
    """Resolve one requirement to HIT, SOFT_HIT or GAP.

    Order is load-bearing. Tier C is checked BEFORE stage 1 as well as at
    stage 2, because an excluded term may also appear literally in the CV —
    'cloud computing' sits in a catch-all line and must not satisfy 'AWS'.
    """
    term = req.canonical or req.text
    cv_low = cv.full_text().lower()

    # Candidate strings: the trimmed phrase, then the full advert bullet.
    # B-07: matching only the trimmed phrase loses clauses that carry the
    # evidence — "communicating with stakeholders, and translating user needs"
    # trims to the first clause, but the second is what the alias table knows.
    candidates = getattr(req, "match_texts", (term,))

    # Tier C — exclusion, checked first and terminal. Checked across ALL
    # candidates: an exclusion must not be evaded by trimming.
    entry = None
    for candidate in candidates:
        found = aliases.lookup(candidate)
        if found and found.excluded:
            return Resolution(
                requirement=req,
                outcome=Outcome.GAP,
                stage=2,
                alias_canonical=found.canonical,
                exclusion_reason=found.reason or "excluded by alias table Tier C",
            )
        if found and entry is None:
            entry = found

    # Stage 1 — exact / lemma.
    span = _find_in_cv(term, cv_low)
    if span:
        return Resolution(req, Outcome.HIT, 1, evidence=span)

    # Stage 2 — alias table (Tier A / B).
    if entry:
        return Resolution(
            req,
            Outcome.HIT,
            2,
            evidence=entry.cv_evidence,
            source_role=entry.source_role,
            alias_canonical=entry.canonical,
        )

    # Stage 3 — embedding fallback, flagged.
    if embedder is not None:
        best_score, best_span = 0.0, ""
        for section, bullet in cv.all_bullets():
            score = embedder.similarity(term, bullet)
            if score > best_score:
                best_score, best_span = score, bullet
        if best_score >= threshold:
            return Resolution(
                req,
                Outcome.SOFT_HIT,
                3,
                evidence=best_span,
                score=round(best_score, 3),
            )
        return Resolution(req, Outcome.GAP, 3, score=round(best_score, 3))

    return Resolution(req, Outcome.GAP, 0)


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

@dataclass
class CoverageReport:
    """Result of scoring one vacancy. Every term is accounted for."""

    resolutions: tuple[Resolution, ...]
    threshold: float = 0.94

    @property
    def total(self) -> int:
        return len(self.resolutions)

    @property
    def matched(self) -> int:
        return sum(1 for r in self.resolutions if r.counts_as_matched)

    @property
    def coverage(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def hits(self) -> list[Resolution]:
        return [r for r in self.resolutions if r.outcome is Outcome.HIT]

    @property
    def soft_hits(self) -> list[Resolution]:
        return [r for r in self.resolutions if r.outcome is Outcome.SOFT_HIT]

    @property
    def gaps(self) -> list[Resolution]:
        return [r for r in self.resolutions if r.outcome is Outcome.GAP]

    @property
    def excluded_gaps(self) -> list[Resolution]:
        """Gaps blocked by a Tier C exclusion — never resolvable by editing."""
        return [r for r in self.gaps if r.is_excluded]

    @property
    def passes(self) -> bool:
        return self.coverage >= self.threshold

    @property
    def ceiling(self) -> float:
        """Maximum attainable coverage if every excluded gap stays unmet.

        Directive §3: if the ceiling is below threshold, exit UNREACHABLE
        immediately rather than burning refactor passes on a vacancy the
        operator is not qualified for.
        """
        if not self.total:
            return 0.0
        return (self.total - len(self.excluded_gaps)) / self.total

    @property
    def reachable(self) -> bool:
        return self.ceiling >= self.threshold

    def summary(self) -> str:
        return (
            f"C = {self.coverage:.3f}  ({self.matched}/{self.total})   "
            f"ceiling {self.ceiling:.3f}   "
            f"{'PASS' if self.passes else ('REFACTOR' if self.reachable else 'UNREACHABLE')}"
        )


def compute_coverage(
    requirements: Sequence[Requirement],
    cv: CanonicalCV,
    aliases: AliasTable,
    embedder: Embedder | None = None,
    *,
    threshold: float = 0.94,
    soft_hit_threshold: float = SOFT_HIT_THRESHOLD,
) -> CoverageReport:
    """Score every requirement. Never drops a term — |resolutions| == |R|."""
    resolutions = tuple(
        resolve_term(r, cv, aliases, embedder, threshold=soft_hit_threshold)
        for r in requirements
    )
    return CoverageReport(resolutions, threshold=threshold)
