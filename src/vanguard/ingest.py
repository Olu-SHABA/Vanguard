"""
Ingestion orchestration — Route 1.

Drives the whole ingestion stage from `boards.yaml`. The pipeline never names
a board: it iterates the registry, instantiates the declared adapter, and
collects. Adding a source is one adapter class plus one YAML block.

Order of operations:

    1. Resolve enabled, automatable boards from the registry
    2. Collect from each, in tier preference order
    3. Deduplicate across all sources before scoring
    4. Return kept vacancies plus a measurable overlap record

Failure of one board never aborts the run. An adapter that raises is recorded
and the run continues — a rate-limited Adzuna must not cost you Reed's results.

Disabled boards are never contacted. Tier 3 boards are never fetched. Both are
enforced in `RegistryEntry.assert_fetchable()` and asserted again here, because
the guard that matters is the one closest to the network call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence

from vanguard.adapters.base import (
    AdapterStatus,
    BoardAdapter,
    BoardRegistry,
    DedupResult,
    IngestionError,
    Query,
    RegistryEntry,
    TermsViolation,
    Truncation,
    Vacancy,
    deduplicate,
)

__all__ = ["ADAPTERS", "IngestionRun", "BoardOutcome", "build_adapter", "ingest", "health_check_all"]


def _adapter_registry() -> dict[str, type[BoardAdapter]]:
    """Imported lazily so a missing optional dependency cannot break import."""
    from vanguard.adapters.adzuna import AdzunaAPIAdapter
    from vanguard.adapters.email_alert import EmailAlertAdapter
    from vanguard.adapters.manual import ManualEntryAdapter
    from vanguard.adapters.reed import ReedAPIAdapter

    return {
        "AdzunaAPIAdapter": AdzunaAPIAdapter,
        "ReedAPIAdapter": ReedAPIAdapter,
        "ManualEntryAdapter": ManualEntryAdapter,
        "EmailAlertAdapter": EmailAlertAdapter,
        # Registered but not yet implemented — declared so the registry can
        # reference them and health_check reports honestly rather than crashing.
        "NHSJobsAPIAdapter": None,
        "FindAJobAdapter": None,
    }


ADAPTERS = _adapter_registry


def build_adapter(entry: RegistryEntry, **kwargs) -> BoardAdapter:
    """Instantiate the adapter a registry entry declares."""
    table = _adapter_registry()
    if entry.adapter not in table:
        raise IngestionError(
            f"board {entry.id!r} declares unknown adapter {entry.adapter!r}. "
            "Add the class and register it before enabling the board."
        )
    cls = table[entry.adapter]
    if cls is None:
        raise IngestionError(
            f"adapter {entry.adapter!r} for board {entry.id!r} is declared but not "
            "yet implemented — see BUILD_PLAN deferred items"
        )
    return cls(entry, **kwargs)


@dataclass
class BoardOutcome:
    """What one board contributed, or why it contributed nothing."""

    board_id: str
    tier: str
    collected: int = 0
    error: str = ""
    skipped: str = ""
    truncations: tuple[Truncation, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.error and not self.skipped

    @property
    def truncated(self) -> bool:
        """More results existed than were collected."""
        return bool(self.truncations)

    def __str__(self) -> str:
        if self.skipped:
            return f"{self.board_id}: skipped — {self.skipped}"
        if self.error:
            return f"{self.board_id}: ERROR — {self.error}"
        line = f"{self.board_id}: {self.collected} vacancies"
        if self.truncated:
            line += f"  [TRUNCATED x{len(self.truncations)}]"
        return line


@dataclass
class IngestionRun:
    """Result of one ingestion pass across the registry."""

    vacancies: tuple[Vacancy, ...]
    dedup: DedupResult
    outcomes: tuple[BoardOutcome, ...]
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def collected(self) -> int:
        return sum(o.collected for o in self.outcomes)

    @property
    def kept(self) -> int:
        return len(self.dedup.kept)

    @property
    def duplicates(self) -> int:
        return len(self.dedup.duplicates)

    @property
    def failures(self) -> list[BoardOutcome]:
        return [o for o in self.outcomes if o.error]

    @property
    def truncations(self) -> list[Truncation]:
        """Every point where a board had more than was collected."""
        return [t for o in self.outcomes for t in o.truncations]

    @property
    def complete(self) -> bool:
        """False when any board was truncated. The run is a sample, not a census."""
        return not self.truncations

    def summary(self) -> str:
        lines = [
            f"collected {self.collected}  ->  kept {self.kept}  "
            f"({self.duplicates} duplicate{'s' if self.duplicates != 1 else ''} logged)"
        ]
        lines += [f"  {o}" for o in self.outcomes]
        if self.truncations:
            lines.append(
                f"  INCOMPLETE — {len(self.truncations)} truncation(s); "
                "more vacancies existed than were collected:"
            )
            lines += [f"    {t}" for t in self.truncations]
        if self.dedup.overlap_by_board:
            overlap = ", ".join(
                f"{b}:{n}" for b, n in sorted(self.dedup.overlap_by_board.items())
            )
            lines.append(f"  overlap dropped by board — {overlap}")
        return "\n".join(lines)


def ingest(
    registry: BoardRegistry,
    query: Query,
    *,
    adapter_factory: Callable[[RegistryEntry], BoardAdapter] = build_adapter,
    extra: Iterable[Vacancy] = (),
) -> IngestionRun:
    """Collect from every enabled, automatable board, then deduplicate.

    `extra` carries vacancies obtained outside the automated path — manual
    LinkedIn pastes, ingested alert emails. They participate in deduplication
    on equal terms, and their board priority applies as normal.
    """
    outcomes: list[BoardOutcome] = []
    harvested: list[Vacancy] = list(extra)

    ordered = sorted(registry.entries, key=lambda e: (e.tier.preference, e.priority))

    for entry in ordered:
        if not entry.enabled:
            outcomes.append(BoardOutcome(entry.id, entry.tier.value, skipped="disabled"))
            continue
        if not entry.tier.automatable:
            outcomes.append(
                BoardOutcome(entry.id, entry.tier.value, skipped="tier 3 — operator paste only")
            )
            continue

        try:
            adapter = adapter_factory(entry)
            entry.assert_fetchable()
            found = adapter.collect(query)
            harvested.extend(found)
            outcomes.append(BoardOutcome(
                entry.id, entry.tier.value, collected=len(found),
                truncations=tuple(getattr(adapter, "truncations", ())),
            ))
        except TermsViolation as exc:
            outcomes.append(BoardOutcome(entry.id, entry.tier.value, skipped=str(exc)))
        except Exception as exc:
            # One board failing must not cost the others their results.
            outcomes.append(BoardOutcome(entry.id, entry.tier.value, error=str(exc)))

    result = deduplicate(harvested, registry.priority_map)
    return IngestionRun(tuple(result.kept), result, tuple(outcomes))


def health_check_all(
    registry: BoardRegistry,
    *,
    adapter_factory: Callable[[RegistryEntry], BoardAdapter] = build_adapter,
) -> list[AdapterStatus]:
    """Per-adapter status. Terms are re-verified before enabling a board."""
    out: list[AdapterStatus] = []
    for entry in registry:
        try:
            out.append(adapter_factory(entry).health_check())
        except Exception as exc:
            out.append(AdapterStatus(entry.id, False, str(exc)))
    return out
