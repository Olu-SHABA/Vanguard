"""Ingestion orchestration — registry-driven collection, isolation, dedup."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.adapters.base import (
    AdapterStatus,
    BoardAdapter,
    IngestionError,
    Query,
    RawVacancy,
    Vacancy,
    load_registry,
)
from vanguard.ingest import build_adapter, health_check_all, ingest

ROOT = Path(__file__).parent.parent


@pytest.fixture
def registry():
    return load_registry(ROOT / "config" / "boards.yaml")


def vac(board, i, employer, title, location="London"):
    return Vacancy(id=f"{board}:{i}", board_id=board, employer=employer, title=title,
                   description="Python and SQL required.", location=location)


class StubAdapter(BoardAdapter):
    """Returns a fixed set. Never touches the network."""

    results: dict[str, list[Vacancy]] = {}
    raises: dict[str, Exception] = {}

    def fetch(self, query):
        self.entry.assert_fetchable()
        if self.board_id in self.raises:
            raise self.raises[self.board_id]
        return [RawVacancy(self.board_id, {"v": v}) for v in self.results.get(self.board_id, [])]

    def normalise(self, raw):
        return raw.payload["v"]

    def health_check(self):
        return AdapterStatus(self.board_id, True, "stub")


# --- registry-driven ------------------------------------------------------

def test_disabled_boards_are_never_contacted(registry) -> None:
    contacted: list[str] = []

    class Recording(StubAdapter):
        def fetch(self, query):
            contacted.append(self.board_id)
            return super().fetch(query)

    ingest(registry, Query(), adapter_factory=Recording)
    assert "totaljobs" not in contacted and "nhs_jobs" not in contacted


def test_tier_3_never_fetched(registry) -> None:
    run = ingest(registry, Query(), adapter_factory=StubAdapter)
    linkedin = next(o for o in run.outcomes if o.board_id == "linkedin")
    assert "operator paste only" in linkedin.skipped


def test_every_board_gets_an_outcome(registry) -> None:
    run = ingest(registry, Query(), adapter_factory=StubAdapter)
    assert len(run.outcomes) == len(registry)


def test_unknown_adapter_named_clearly(registry) -> None:
    entry = registry.get("adzuna")
    entry.adapter = "NoSuchAdapter"
    with pytest.raises(IngestionError, match="unknown adapter"):
        build_adapter(entry)


def test_declared_but_unimplemented_adapter_is_honest(registry) -> None:
    with pytest.raises(IngestionError, match="not yet implemented"):
        build_adapter(registry.get("nhs_jobs"))


# --- isolation ------------------------------------------------------------

def test_one_board_failing_does_not_abort_the_run(registry) -> None:
    """A rate-limited Adzuna must not cost you Reed's results."""
    StubAdapter.results = {"reed": [vac("reed", 1, "MoJ", "Data Engineer")]}
    StubAdapter.raises = {"adzuna": RuntimeError("429 rate limited")}
    try:
        run = ingest(registry, Query(), adapter_factory=StubAdapter)
        assert run.kept == 1
        assert any("429" in o.error for o in run.failures)
    finally:
        StubAdapter.results, StubAdapter.raises = {}, {}


def test_failures_are_recorded_not_swallowed(registry) -> None:
    StubAdapter.raises = {"adzuna": RuntimeError("boom")}
    try:
        run = ingest(registry, Query(), adapter_factory=StubAdapter)
        assert len(run.failures) == 1 and "boom" in run.failures[0].error
    finally:
        StubAdapter.raises = {}


# --- dedup across sources -------------------------------------------------

def test_same_vacancy_from_three_boards_collapses(registry) -> None:
    extra = [
        vac("adzuna", 1, "Ministry of Justice Ltd", "Senior Data Engineer"),
        vac("reed", 1, "Ministry of Justice", "Data Engineer"),
        vac("civil_service_jobs", 1, "Ministry of Justice PLC", "Lead Data Engineer"),
    ]
    run = ingest(registry, Query(), adapter_factory=StubAdapter, extra=extra)
    assert run.kept == 1
    assert run.vacancies[0].board_id == "adzuna", "priority 1 must win"
    assert run.duplicates == 2


def test_overlap_is_measurable_per_board(registry) -> None:
    """Find a Job is substantially the Adzuna corpus. Overlap must be visible."""
    extra = [
        vac("adzuna", 1, "MoJ", "Data Engineer"),
        vac("reed", 1, "MoJ", "Data Engineer"),
    ]
    run = ingest(registry, Query(), adapter_factory=StubAdapter, extra=extra)
    assert run.dedup.overlap_by_board == {"reed": 1}


def test_manual_entries_participate_in_dedup(registry) -> None:
    extra = [
        vac("linkedin", 1, "MoJ", "Data Engineer"),
        vac("adzuna", 1, "MoJ Ltd", "Senior Data Engineer"),
    ]
    run = ingest(registry, Query(), adapter_factory=StubAdapter, extra=extra)
    assert run.kept == 1 and run.vacancies[0].board_id == "adzuna"


def test_distinct_vacancies_survive(registry) -> None:
    extra = [vac("adzuna", 1, "MoJ", "Data Engineer"),
             vac("linkedin", 1, "Acme", "Data Scientist")]
    run = ingest(registry, Query(), adapter_factory=StubAdapter, extra=extra)
    assert run.kept == 2


# --- reporting ------------------------------------------------------------

def test_summary_reports_collected_and_kept(registry) -> None:
    extra = [vac("adzuna", 1, "MoJ", "Data Engineer"),
             vac("reed", 1, "MoJ Ltd", "Senior Data Engineer")]
    s = ingest(registry, Query(), adapter_factory=StubAdapter, extra=extra).summary()
    assert "kept 1" in s and "duplicate" in s


def test_health_check_covers_every_board(registry) -> None:
    assert len(health_check_all(registry)) == len(registry)


def test_health_check_reports_missing_credentials(registry) -> None:
    statuses = {s.board_id: s for s in health_check_all(registry)}
    assert not statuses["adzuna"].reachable
    assert "ADZUNA_APP_ID" in statuses["adzuna"].detail


def test_health_check_never_raises(registry) -> None:
    for s in health_check_all(registry):
        assert isinstance(s.reachable, bool)


# ---------------------------------------------------------------------------
# B-12 — an incomplete run must declare itself
# ---------------------------------------------------------------------------

def test_run_reports_incompleteness(registry) -> None:
    from vanguard.adapters.base import Truncation

    class Truncating(StubAdapter):
        def fetch(self, query):
            self.entry.assert_fetchable()
            self._note_truncation("data scientist", 50, "reached max_results=50")
            return []

    run = ingest(registry, Query(), adapter_factory=Truncating)
    assert not run.complete
    assert run.truncations
    assert "INCOMPLETE" in run.summary()


def test_complete_run_says_nothing_about_truncation(registry) -> None:
    run = ingest(registry, Query(), adapter_factory=StubAdapter)
    assert run.complete
    assert "INCOMPLETE" not in run.summary()


def test_truncation_names_the_board_and_keyword(registry) -> None:
    class Truncating(StubAdapter):
        def fetch(self, query):
            self.entry.assert_fetchable()
            self._note_truncation("network analytics", 100, "reached max_pages=5")
            return []

    run = ingest(registry, Query(), adapter_factory=Truncating)
    text = " ".join(str(t) for t in run.truncations)
    assert "network analytics" in text and "adzuna" in text
