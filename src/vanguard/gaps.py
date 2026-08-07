"""
Gap classification — Type 1 / 2 / 3.

Directive §3. Every unmatched requirement is typed before any text is written.

    TYPE 1  Evidenced, unstated.   Demonstrable from CV history but absent in
                                   wording. Action: add, citing the source role.
    TYPE 2  Evidenced, differently named. Present under domain-native
                                   terminology. Action: re-word, log the alias.
    TYPE 3  Not evidenced.         No basis in employment history.
                                   Action: NO CV EDIT PERMITTED. Record as unmet.

The classifier proposes; the operator confirms.
---------------------------------------------------
Type 3 is decidable in code — no alias, no CV evidence, no soft hit. But
distinguishing "evidenced but unstated" from "not evidenced" requires knowing
what the applicant actually did, and only they know that. So a proposed Type 1
or Type 2 is `confirmed = False` and sets `status = FLAGGED` until the operator
rules on it. An unconfirmed proposal can never reach the refactor engine.

This is the layer where fabrication would enter if it entered anywhere. The
guard is structural, not advisory: `Gap.to_edit()` raises unless the gap is
confirmed, is Type 1 or 2, and carries a source role.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Sequence

from vanguard.coverage import CoverageReport, Outcome, Resolution
from vanguard.cv import CanonicalCV, CVSection, Edit

__all__ = ["GapType", "Gap", "GapReport", "classify", "classify_all"]


class GapType(IntEnum):
    EVIDENCED_UNSTATED = 1
    EVIDENCED_RENAMED = 2
    NOT_EVIDENCED = 3

    @property
    def label(self) -> str:
        return {
            1: "Evidenced, unstated",
            2: "Evidenced, differently named",
            3: "Not evidenced",
        }[int(self)]

    @property
    def permits_edit(self) -> bool:
        return int(self) in (1, 2)


class GapError(ValueError):
    """A gap was used in a way the taxonomy forbids."""


@dataclass(frozen=True)
class Gap:
    """One unmatched requirement, typed.

    `confirmed` is False for every machine proposal. Only the operator sets it.
    """

    resolution: Resolution
    gap_type: GapType
    rationale: str
    candidate_section: str = ""     # CVSection.id the evidence would attach to
    source_role: str = ""
    proposed_before: str = ""
    proposed_after: str = ""
    confirmed: bool = False

    @property
    def term(self) -> str:
        r = self.resolution.requirement
        return r.canonical or r.text

    @property
    def blocked_by_exclusion(self) -> bool:
        """Tier C. Not merely unevidenced — ruled non-equivalent by the operator."""
        return self.resolution.is_excluded

    def confirm(self, *, section_id: str = "", source_role: str = "",
                before: str = "", after: str = "") -> Gap:
        """Operator ruling. Type 3 can never be confirmed into an edit."""
        if not self.gap_type.permits_edit:
            raise GapError(
                f"Type {int(self.gap_type)} gap {self.term!r} permits no CV edit. "
                "Record as unmet."
            )
        return replace(
            self,
            confirmed=True,
            candidate_section=section_id or self.candidate_section,
            source_role=source_role or self.source_role,
            proposed_before=before or self.proposed_before,
            proposed_after=after or self.proposed_after,
        )

    def to_edit(self) -> Edit:
        """Convert to an applicable edit. Raises on every unsafe path."""
        if not self.gap_type.permits_edit:
            raise GapError(f"Type 3 gap {self.term!r}: NO CV EDIT PERMITTED")
        if not self.confirmed:
            raise GapError(
                f"gap {self.term!r} is an unconfirmed machine proposal; "
                "operator confirmation required before editing the CV"
            )
        if not self.source_role.strip():
            raise GapError(f"gap {self.term!r} has no source role citation")
        if not self.proposed_before or not self.proposed_after:
            raise GapError(f"gap {self.term!r} has no proposed edit text")
        return Edit(
            section_id=self.candidate_section,
            before=self.proposed_before,
            after=self.proposed_after,
            source_role=self.source_role,
            gap_type=int(self.gap_type),
        )

    def __str__(self) -> str:
        mark = "confirmed" if self.confirmed else "proposed"
        excl = " [Tier C]" if self.blocked_by_exclusion else ""
        return f"Type {int(self.gap_type)} ({mark}){excl}  {self.term} — {self.rationale}"


@dataclass
class GapReport:
    gaps: tuple[Gap, ...]

    def of_type(self, t: GapType | int) -> list[Gap]:
        return [g for g in self.gaps if int(g.gap_type) == int(t)]

    @property
    def type_1(self) -> list[Gap]:
        return self.of_type(1)

    @property
    def type_2(self) -> list[Gap]:
        return self.of_type(2)

    @property
    def type_3(self) -> list[Gap]:
        return self.of_type(3)

    @property
    def editable(self) -> list[Gap]:
        return [g for g in self.gaps if g.gap_type.permits_edit]

    @property
    def confirmed(self) -> list[Gap]:
        return [g for g in self.gaps if g.confirmed and g.gap_type.permits_edit]

    @property
    def unconfirmed(self) -> list[Gap]:
        return [g for g in self.editable if not g.confirmed]

    @property
    def requires_operator(self) -> bool:
        """Any unconfirmed Type 1/2 proposal sets status = FLAGGED."""
        return bool(self.unconfirmed)

    def summary(self) -> str:
        return (
            f"gaps: {len(self.gaps)}  "
            f"[T1 {len(self.type_1)} / T2 {len(self.type_2)} / T3 {len(self.type_3)}]  "
            f"{len(self.confirmed)} confirmed, {len(self.unconfirmed)} awaiting operator"
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# A term the CV touches at this strength is plausibly evidenced but unstated.
_TYPE_1_MIN_SCORE = 0.45


def classify(gap: Resolution, cv: CanonicalCV) -> Gap:
    """Propose a type for one unmatched requirement. Never confirms.

    Decision order:
      1. Tier C exclusion            -> Type 3, terminal. Operator already ruled.
      2. Stage-3 score above floor   -> Type 1 proposal, with candidate section
      3. Anything else               -> Type 3 proposal
    """
    if gap.is_excluded:
        return Gap(
            resolution=gap,
            gap_type=GapType.NOT_EVIDENCED,
            rationale=f"alias table Tier C ({gap.alias_canonical}): {gap.exclusion_reason}",
        )

    if gap.score is not None and gap.score >= _TYPE_1_MIN_SCORE:
        section = _best_section(gap, cv)
        return Gap(
            resolution=gap,
            gap_type=GapType.EVIDENCED_UNSTATED,
            rationale=(
                f"nearest CV evidence scores {gap.score:.2f} — may be evidenced "
                "but unstated. Operator confirmation required."
            ),
            candidate_section=section.id if section else "",
            source_role=section.source_role if section else "",
        )

    score = f" (best match {gap.score:.2f})" if gap.score is not None else ""
    return Gap(
        resolution=gap,
        gap_type=GapType.NOT_EVIDENCED,
        rationale=f"no exact match, no alias, no soft hit{score}",
    )


def _best_section(gap: Resolution, cv: CanonicalCV) -> CVSection | None:
    """Section whose text contains the evidence span stage 3 matched."""
    if not gap.evidence:
        return None
    needle = gap.evidence.strip().lower()[:60]
    for section in cv:
        if needle and needle in section.text().lower():
            return section
    return None


def classify_all(report: CoverageReport, cv: CanonicalCV) -> GapReport:
    """Classify every gap in a coverage report. Soft hits are not gaps.

    A SOFT_HIT already counts as matched. It is flagged for review in the
    coverage report, not re-litigated here.
    """
    return GapReport(tuple(classify(r, cv) for r in report.gaps))
