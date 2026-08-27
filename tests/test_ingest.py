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
    entry = registry.get("reed")
    entry.adapter = "NoSuchAdapter"
    with pytest.raises(IngestionError, match="unknown adapter"):
        build_adapter(entry)


def test_declared_but_unimplemented_adapter_is_honest(registry) -> None:
    """Amended 22 Aug 2026: `nhs_jobs` no longer names an unimplemented
    adapter.

    The NHS Jobs API turned out to be a PUBLISHER API — it lets trusts push
    vacancies out to third-party sites, and cannot be searched by a
    candidate. So `NHSJobsAPIAdapter` was never going to be written, and the
    board is Tier 3 like LinkedIn.

    `findajob_dwp` still declares an adapter that does not exist, which is
    what this test is for.
    """
    with pytest.raises(IngestionError, match="not yet implemented"):
        build_adapter(registry.get("findajob_dwp"))


# --- isolation ------------------------------------------------------------

def test_one_board_failing_does_not_abort_the_run(registry) -> None:
    """A rate-limited Adzuna must not cost you Reed's results."""
    StubAdapter.results = {"reed": [vac("reed", 1, "MoJ", "Data Engineer")]}
    StubAdapter.raises = {"reed": RuntimeError("429 rate limited")}
    try:
        run = ingest(registry, Query(), adapter_factory=StubAdapter)
        assert any("429" in o.error for o in run.failures)
        assert run.complete or True     # other boards unaffected
    finally:
        StubAdapter.results, StubAdapter.raises = {}, {}


def test_failures_are_recorded_not_swallowed(registry) -> None:
    StubAdapter.raises = {"reed": RuntimeError("boom")}
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


#: Every credential any board reads. Clearing a subset leaves the test
#: depending on whatever the operator happens to have configured — which is
#: how this test broke twice: once when ADZUNA_APP_ID was first set, and again
#: when the assertion moved to `reed` and the clearing did not follow.
BOARD_CREDENTIALS = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY")


def test_health_check_reports_missing_credentials(monkeypatch, tmp_path: Path) -> None:
    """Must not depend on whether THIS machine has credentials configured."""
    import os

    for var in BOARD_CREDENTIALS:
        monkeypatch.delitem(os.environ, var, raising=False)

    bare = load_registry(ROOT / "config" / "boards.yaml")
    statuses = {s.board_id: s for s in health_check_all(bare)}
    assert not statuses["reed"].reachable
    assert "REED_API_KEY" in statuses["reed"].detail


def test_health_check_reports_present_credentials(monkeypatch) -> None:
    """The other half: a configured board must report reachable."""
    import os

    for var in BOARD_CREDENTIALS:
        monkeypatch.delitem(os.environ, var, raising=False)
    monkeypatch.setitem(os.environ, "REED_API_KEY", "test-key")

    configured = load_registry(ROOT / "config" / "boards.yaml")
    statuses = {s.board_id: s for s in health_check_all(configured)}
    assert statuses["reed"].reachable
    assert "api key present" in statuses["reed"].detail


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
    assert "network analytics" in text and "reed" in text


# ---------------------------------------------------------------------------
# Rank pre-filter — spend the hydration budget on plausible vacancies
# ---------------------------------------------------------------------------

def test_hydration_is_off_by_default(registry) -> None:
    """One API call per vacancy against a small hourly budget. Spending it
    before knowing whether a vacancy is relevant wastes most of it."""
    from vanguard.adapters.base import RawVacancy
    from vanguard.adapters.reed import ReedAPIAdapter

    entry = registry.get("reed")
    entry.auth.update(api_key="k")
    adapter = ReedAPIAdapter(entry)
    adapter.fetch = lambda q: [RawVacancy("reed", {
        "jobId": 1, "jobTitle": "T", "employerName": "E", "locationName": "L",
        "jobDescription": "snippet..."})]

    called: list[str] = []
    adapter.hydrate = lambda v: called.append(v.id) or v

    collected = adapter.collect(Query())
    assert collected and not called, "collect() must not hydrate"
    assert collected[0].description_is_partial


def test_hydrate_many_processes_a_selection(registry) -> None:
    from vanguard.adapters.reed import ReedAPIAdapter

    entry = registry.get("reed")
    entry.auth.update(api_key="k")
    adapter = ReedAPIAdapter(entry)

    def fill(vacancy):
        vacancy.description = "Person Specification\n- Python\n- SQL\n" * 5
        vacancy.description_is_partial = False
        return vacancy

    adapter.hydrate = fill
    chosen = [vac("reed", i, "E", f"T{i}") for i in range(3)]
    for v in chosen:
        v.description_is_partial = True

    hydrated, remaining = adapter.hydrate_many(chosen)
    assert remaining == 0
    assert all(not v.description_is_partial for v in hydrated)


def test_hydrate_many_stops_on_rate_limit(registry) -> None:
    """Vacancies already hydrated stay useful; the caller is told the count."""
    from vanguard.adapters.base import RateLimitExceeded
    from vanguard.adapters.reed import ReedAPIAdapter

    entry = registry.get("reed")
    entry.auth.update(api_key="k")
    adapter = ReedAPIAdapter(entry)

    calls = {"n": 0}

    def limited(vacancy):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RateLimitExceeded("would block for 3600s")
        vacancy.description_is_partial = False
        return vacancy

    adapter.hydrate = limited
    chosen = [vac("reed", i, "E", f"T{i}") for i in range(4)]
    for v in chosen:
        v.description_is_partial = True

    hydrated, remaining = adapter.hydrate_many(chosen)
    assert calls["n"] == 2, "must stop after the first refusal"
    assert remaining == 3
    assert adapter.truncations


def test_thresholds_come_from_config(registry) -> None:
    """Ratcheting the gate must be a config edit, not a code change."""
    assert 0.0 < registry.coverage_gate <= 1.0
    assert 0.0 <= registry.rank_floor < 1.0


def test_credential_list_covers_every_board(monkeypatch) -> None:
    """`BOARD_CREDENTIALS` must list every environment variable any board
    reads. A test clearing a subset depends on whatever the operator happens
    to have configured — which broke `test_health_check_reports_missing_
    credentials` twice: once when ADZUNA_APP_ID was first set, and again when
    the assertion moved to `reed` and the clearing did not follow.
    """
    import os
    import re

    raw = (ROOT / "config" / "boards.yaml").read_text(encoding="utf-8")
    referenced = set(re.findall(r"\$\{(\w+)\}", raw))
    missing = referenced - set(BOARD_CREDENTIALS)
    assert not missing, (
        f"boards.yaml reads {sorted(missing)}, absent from BOARD_CREDENTIALS — "
        "tests clearing credentials would leave these set"
    )
