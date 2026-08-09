"""
Refactor engine — bounded CV editing.

Directive §3. Coverage is recomputed after Type 1 and Type 2 edits only.

    MAX_REFACTOR_ITER = 2

Three independent exit conditions:

    THRESHOLD_MET   C >= 0.94 after an edit pass
    CEILING         arithmetic proof that Type 3 gaps place 0.94 out of reach
    ITERATION_CAP   two passes completed without reaching threshold

The ceiling check runs FIRST, before any pass. Computing the maximum attainable
coverage with Type 3 gaps excluded costs nothing and avoids burning two passes
on a vacancy the operator is not qualified for. That was an explicit design
point in BUILD_PLAN §3.2.

Every edit records (gap_type, section, source_role, before, after). An edit
without a source role cannot be constructed — `Edit.__post_init__` rejects it —
so the citation requirement is enforced at the data layer rather than by
convention.

The canonical CV is never mutated. Each pass returns a new CanonicalCV; the
original is the source of truth and stays untouched on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from vanguard.coverage import AliasTable, CoverageReport, Embedder, compute_coverage
from vanguard.cv import CanonicalCV, Edit
from vanguard.extract import Requirement
from vanguard.gaps import Gap, GapReport, classify_all

__all__ = [
    "MAX_REFACTOR_ITER",
    "ExitReason",
    "RefactorPass",
    "RefactorResult",
    "refactor",
]

MAX_REFACTOR_ITER = 2


class ExitReason(str, Enum):
    THRESHOLD_MET = "THRESHOLD_MET"
    CEILING_UNREACHABLE = "CEILING_UNREACHABLE"
    ITERATION_CAP = "ITERATION_CAP"
    NO_CONFIRMED_EDITS = "NO_CONFIRMED_EDITS"
    UNRELIABLE_SOURCE = "UNRELIABLE_SOURCE"

    @property
    def status(self) -> str:
        """Queue status this exit maps to (directive §4)."""
        return {
            "THRESHOLD_MET": "PENDING",
            "CEILING_UNREACHABLE": "UNREACHABLE",
            "ITERATION_CAP": "UNREACHABLE",
            "NO_CONFIRMED_EDITS": "FLAGGED",
            "UNRELIABLE_SOURCE": "FLAGGED",
        }[self.value]


@dataclass
class RefactorPass:
    """One iteration. Recorded whether or not it improved coverage."""

    index: int
    edits: tuple[Edit, ...]
    coverage_before: float
    coverage_after: float

    @property
    def delta(self) -> float:
        return self.coverage_after - self.coverage_before

    def __str__(self) -> str:
        return (
            f"pass {self.index}: {len(self.edits)} edit(s)  "
            f"C {self.coverage_before:.3f} -> {self.coverage_after:.3f} "
            f"({self.delta:+.3f})"
        )


@dataclass
class RefactorResult:
    """Outcome of the whole bounded loop."""

    cv: CanonicalCV                 # possibly edited; original untouched
    initial: CoverageReport
    final: CoverageReport
    gaps: GapReport
    passes: tuple[RefactorPass, ...]
    exit_reason: ExitReason

    @property
    def edits(self) -> list[Edit]:
        return [e for p in self.passes for e in p.edits]

    @property
    def status(self) -> str:
        return self.exit_reason.status

    @property
    def unmet(self) -> list[Gap]:
        """Type 3 gaps remaining. Recorded as unmet, never edited away."""
        return self.gaps.type_3

    def diff(self) -> list[str]:
        """Reviewable as a text diff against canonical."""
        return self.cv.diff_summary()

    def summary(self) -> str:
        lines = [
            f"C {self.initial.coverage:.3f} -> {self.final.coverage:.3f}   "
            f"ceiling {self.initial.ceiling:.3f}   exit: {self.exit_reason.value}   "
            f"status: {self.status}",
            self.gaps.summary(),
        ]
        lines += [f"  {p}" for p in self.passes]
        if self.unmet:
            lines.append(f"  unmet (Type 3): {', '.join(g.term for g in self.unmet)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------

def refactor(
    requirements: Sequence[Requirement],
    cv: CanonicalCV,
    aliases: AliasTable,
    embedder: Embedder | None = None,
    *,
    threshold: float = 0.94,
    max_iter: int = MAX_REFACTOR_ITER,
    confirm: bool = False,
    source_is_partial: bool = False,
) -> RefactorResult:
    """Run the bounded refactor loop.

    `confirm` is False by default and must stay that way in the autonomous
    context: only the operator confirms a Type 1 or Type 2 proposal. When no
    confirmed edit exists the loop exits NO_CONFIRMED_EDITS with status
    FLAGGED, which is the correct autonomous outcome — not a failure.

    The `confirm=True` path exists for the interactive session and for tests,
    where the operator has already ruled.
    """
    initial = compute_coverage(requirements, cv, aliases, embedder,
                               threshold=threshold, source_is_partial=source_is_partial)
    gaps = classify_all(initial, cv)

    # Exit 0 — the score cannot be trusted. Refactoring against a snippet
    # would edit the CV to satisfy requirements nobody stated.
    if initial.unreliable:
        return RefactorResult(cv, initial, initial, gaps, (), ExitReason.UNRELIABLE_SOURCE)

    # Exit 1 — already met. No edit needed.
    if initial.passes:
        return RefactorResult(cv, initial, initial, gaps, (), ExitReason.THRESHOLD_MET)

    # Exit 2 — ceiling. Checked before any pass.
    if not initial.reachable:
        return RefactorResult(cv, initial, initial, gaps, (), ExitReason.CEILING_UNREACHABLE)

    working = cv
    current = initial
    passes: list[RefactorPass] = []

    for i in range(1, max_iter + 1):
        candidates = _confirmed_edits(gaps, auto_confirm=confirm)
        if not candidates:
            return RefactorResult(
                working, initial, current, gaps, tuple(passes), ExitReason.NO_CONFIRMED_EDITS
            )

        before = current.coverage
        applied: list[Edit] = []
        for edit in candidates:
            try:
                working = working.apply(edit)
                applied.append(edit)
            except Exception:
                # A stale `before` means the CV moved under us. Skip, do not
                # abort — the remaining edits are still valid.
                continue

        current = compute_coverage(requirements, working, aliases, embedder, threshold=threshold)
        passes.append(RefactorPass(i, tuple(applied), before, current.coverage))

        gaps = classify_all(current, working)

        if current.passes:
            return RefactorResult(
                working, initial, current, gaps, tuple(passes), ExitReason.THRESHOLD_MET
            )
        if not current.reachable:
            return RefactorResult(
                working, initial, current, gaps, tuple(passes), ExitReason.CEILING_UNREACHABLE
            )

    return RefactorResult(
        working, initial, current, gaps, tuple(passes), ExitReason.ITERATION_CAP
    )


def _confirmed_edits(gaps: GapReport, *, auto_confirm: bool) -> list[Edit]:
    """Editable gaps that carry an operator ruling and a usable edit."""
    out: list[Edit] = []
    for gap in gaps.editable:
        candidate = gap
        if auto_confirm and not gap.confirmed and gap.proposed_before and gap.proposed_after:
            candidate = gap.confirm()
        if not candidate.confirmed:
            continue
        try:
            out.append(candidate.to_edit())
        except Exception:
            continue  # incomplete proposal — stays FLAGGED for the operator
    return out
