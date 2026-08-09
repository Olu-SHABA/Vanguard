"""Board adapters — tiers, terms enforcement, normalisation, rate limiting."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

import pytest

from vanguard.adapters.adzuna import AdzunaAPIAdapter
from vanguard.adapters.base import (
    IngestionError,
    Query,
    RateLimiter,
    RawVacancy,
    Tier,
    TermsViolation,
    Vacancy,
    dedup_key,
    deduplicate,
    load_registry,
)
from vanguard.adapters.email_alert import EmailAlertAdapter, parse_alert
from vanguard.adapters.manual import ManualEntryAdapter
from vanguard.adapters.reed import ReedAPIAdapter

ROOT = Path(__file__).parent.parent


@pytest.fixture
def registry():
    return load_registry(ROOT / "config" / "boards.yaml")


@pytest.fixture
def adzuna_entry(registry):
    """An Adzuna entry configured as an API board.

    The real registry demotes Adzuna to manual on capability grounds — it
    caps descriptions at 500 characters. `AdzunaAPIAdapter` remains valid
    code, so adapter-level behaviour (pagination, truncation, auth) is tested
    against a synthetic API entry rather than the demoted registry one.
    """
    from dataclasses import replace as _replace

    entry = registry.get("adzuna")
    return _replace(entry, tier=Tier.API_OFFICIAL, supplies_full_text=True,
                    adapter="AdzunaAPIAdapter",
                    auth=dict(entry.auth), query=dict(entry.query))


@pytest.fixture
def bare_registry(monkeypatch):
    """Registry loaded with NO credentials in the environment.

    Several tests assert on the unconfigured state. Reading the ambient
    environment made them pass only on a machine without credentials — they
    failed the moment the operator configured the boards, which is exactly
    when the suite most needs to be trustworthy.
    """
    for name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY"):
        monkeypatch.delitem(os.environ, name, raising=False)
    return load_registry(ROOT / "config" / "boards.yaml")


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload, self.status_code = payload, status
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response):
        self._response, self.calls = response, []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self._response


# --- registry -------------------------------------------------------------

def test_registry_loads_all_boards(registry) -> None:
    assert len(registry) == 10


def test_enabled_and_automatable_split(registry) -> None:
    assert len(registry.enabled) == 4
    # Only Reed remains automatable: Adzuna and Civil Service were demoted on
    # capability grounds, LinkedIn on terms.
    assert len(registry.automatable) == 1
    assert len(registry.manual) == 3


def test_priority_map_complete(registry) -> None:
    assert registry.priority_map["adzuna"] == 1


def test_per_board_silence_days(registry) -> None:
    assert registry.silence_days_for("civil_service_jobs") == 30
    assert registry.silence_days_for("nhs_jobs") == 30
    assert registry.silence_days_for("adzuna") == 21


def test_unknown_board_falls_back_to_global_silence(registry) -> None:
    assert registry.silence_days_for("nonexistent") == 21


def test_credentials_come_from_environment(bare_registry) -> None:
    """${ADZUNA_APP_ID} resolves from env, never from the YAML."""
    assert bare_registry.get("adzuna").auth["app_id"] == ""


def test_duplicate_board_id_rejected(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text("boards:\n  - id: x\n    tier: manual\n  - id: x\n    tier: manual\n")
    with pytest.raises(IngestionError, match="duplicate board id"):
        load_registry(p)


def test_unknown_tier_rejected(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text("boards:\n  - id: x\n    tier: scrape_anyway\n")
    with pytest.raises(IngestionError, match="unknown tier"):
        load_registry(p)


# --- terms enforcement ----------------------------------------------------

def test_disabled_board_is_never_contacted(registry) -> None:
    with pytest.raises(TermsViolation, match="disabled"):
        registry.get("totaljobs").assert_fetchable()


def test_tier_3_fetch_prohibited(registry) -> None:
    """LinkedIn's User Agreement prohibits automated collection."""
    with pytest.raises(TermsViolation, match="prohibited by its terms"):
        ManualEntryAdapter(registry.get("linkedin")).fetch(Query())


def test_email_alert_never_fetches_the_portal(registry) -> None:
    """Civil Service Jobs serves a bot interstitial. Alerts are the route."""
    with pytest.raises(TermsViolation, match="never fetched"):
        EmailAlertAdapter(registry.get("civil_service_jobs")).fetch(Query())


def test_portal_url_is_operator_facing_only(registry) -> None:
    entry = registry.get("civil_service_jobs")
    assert entry.portal_url.startswith("https://")
    assert "NEVER fetched" in entry.note or "never fetched" in entry.note.lower()


# --- manual adapter -------------------------------------------------------

def test_manual_submit_parses_pasted_advert(registry) -> None:
    a = ManualEntryAdapter(registry.get("linkedin"))
    text = ROOT / "tests" / "fixtures" / "moj_senior_data_engineer.txt"
    v = a.submit(text.read_text(encoding="utf-8"), employer="Ministry of Justice")
    assert v.title == "Senior Data Engineer" and v.board_id == "linkedin"


def test_manual_submit_requires_text(registry) -> None:
    with pytest.raises(IngestionError, match="empty"):
        ManualEntryAdapter(registry.get("linkedin")).submit("   ")


def test_manual_health_check_is_honest(registry) -> None:
    s = ManualEntryAdapter(registry.get("linkedin")).health_check()
    assert s.reachable and "no endpoint" in s.detail


# --- adzuna ---------------------------------------------------------------

def test_adzuna_missing_credentials_raises(adzuna_entry, monkeypatch) -> None:
    for name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delitem(os.environ, name, raising=False)
    adzuna_entry.auth.update(app_id="", app_key="")
    with pytest.raises(IngestionError, match="ADZUNA_APP_ID"):
        AdzunaAPIAdapter(adzuna_entry).fetch(Query())


def test_adzuna_normalises_payload(registry) -> None:
    a = AdzunaAPIAdapter(registry.get("adzuna"))
    v = a.normalise(RawVacancy("adzuna", {
        "id": "123", "title": "Senior Data Engineer",
        "description": "Python and SQL required.",
        "company": {"display_name": "MoJ"}, "location": {"display_name": "London"},
        "salary_min": 49325, "salary_max": 53081,
        "redirect_url": "https://x", "created": "2026-08-01T09:00:00Z",
    }))
    assert v.employer == "MoJ" and v.salary_band == "49,325 - 53,081"
    assert v.posted and v.posted.year == 2026


def test_vacancy_without_description_rejected() -> None:
    """Nothing to extract requirements from."""
    with pytest.raises(IngestionError, match="no description"):
        Vacancy(id="x", board_id="b", employer="e", title="t", description="")


def test_collect_skips_bad_records_without_aborting(registry) -> None:
    a = AdzunaAPIAdapter(registry.get("adzuna"))
    a.fetch = lambda q: [
        RawVacancy("adzuna", {"id": "1", "title": "Good", "description": "Python."}),
        RawVacancy("adzuna", {"id": "2", "title": "Bad", "description": ""}),
    ]
    assert len(a.collect(Query())) == 1


# --- reed -----------------------------------------------------------------

def test_reed_missing_key_raises(bare_registry) -> None:
    with pytest.raises(IngestionError, match="REED_API_KEY"):
        ReedAPIAdapter(bare_registry.get("reed")).fetch(Query())


def test_reed_normalises_payload(registry) -> None:
    v = ReedAPIAdapter(registry.get("reed")).normalise(RawVacancy("reed", {
        "jobId": 55, "jobTitle": "Data Engineer", "employerName": "Acme",
        "jobDescription": "SQL and Python.", "locationName": "Leeds",
        "minimumSalary": 40000, "maximumSalary": 50000, "date": "01/08/2026",
    }))
    assert v.id == "reed:55" and v.salary_band == "40,000 - 50,000"


# --- email alert ----------------------------------------------------------

ALERT = """Your Civil Service Jobs alert

Senior Data Engineer - Ministry of Justice - National
£42,914 - £53,081 per annum
Closing date: 10/08/2026
https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=19568

Data Scientist - Department for Work and Pensions - Leeds
£45,000
https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=19999

Unsubscribe from these alerts
"""


def test_alert_parses_two_vacancies() -> None:
    assert len(parse_alert(ALERT)) == 2


def test_salary_line_is_not_a_vacancy() -> None:
    """'£42,914 - £53,081 per annum' carries a dash and looks like title-employer."""
    assert all(not i.title.startswith("£") for i in parse_alert(ALERT))


def test_salary_attaches_to_preceding_vacancy() -> None:
    items = parse_alert(ALERT)
    assert "42,914" in items[0].salary_band


def test_boilerplate_ignored() -> None:
    assert all("unsubscribe" not in i.title.lower() for i in parse_alert(ALERT))


def test_sender_mismatch_refused(registry) -> None:
    a = EmailAlertAdapter(registry.get("civil_service_jobs"))
    with pytest.raises(IngestionError, match="does not match configured sender"):
        a.ingest_message(ALERT, sender="spam@elsewhere.com")


def test_sender_glob_matches(registry) -> None:
    a = EmailAlertAdapter(registry.get("civil_service_jobs"))
    assert len(a.ingest_message(ALERT, sender="alerts.civilservicejobs.service.gov.uk")) == 2


def test_html_alert_parsed(registry) -> None:
    html = "<p>Data Engineer - Acme Ltd - London</p><p>https://example.com/1</p>"
    assert parse_alert(html)[0].title == "Data Engineer"


# --- rate limiting --------------------------------------------------------

def test_limiter_permits_up_to_the_cap() -> None:
    slept: list[float] = []
    now = [0.0]
    rl = RateLimiter(3, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                     clock=lambda: now[0])
    for _ in range(3):
        rl.acquire()
    assert slept == []


def test_limiter_permits_a_second_window() -> None:
    """Once the window rolls over, calls flow again without waiting."""
    slept: list[float] = []
    now = [0.0]
    rl = RateLimiter(2, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                     clock=lambda: now[0])
    rl.acquire()
    rl.acquire()
    now[0] = 3601.0          # first window fully expired
    rl.acquire()
    assert slept == [], "no wait should be needed once the window has rolled"


def test_backoff_is_exponential() -> None:
    rl = RateLimiter(60, sleep=lambda s: None, clock=lambda: 0.0)
    first, second = rl.penalise(), rl.penalise()
    assert second > first


def test_retry_after_is_honoured() -> None:
    rl = RateLimiter(60, sleep=lambda s: None, clock=lambda: 0.0)
    assert rl.penalise(retry_after=42.0) == 42.0


def test_backoff_has_a_ceiling() -> None:
    rl = RateLimiter(60, max_backoff=10.0, sleep=lambda s: None, clock=lambda: 0.0)
    for _ in range(20):
        delay = rl.penalise()
    assert delay <= 10.0


def test_limiter_rejects_zero_rate() -> None:
    with pytest.raises(ValueError, match="positive"):
        RateLimiter(0)


# --- deduplication --------------------------------------------------------

def vac(board, i, employer, title, location="London", salary=""):
    return Vacancy(id=f"{board}:{i}", board_id=board, employer=employer, title=title,
                   description="Python and SQL.", location=location, salary_band=salary)


def test_company_suffix_normalised() -> None:
    assert dedup_key("MoJ Ltd", "Data Engineer", "London", "") == \
           dedup_key("MoJ", "Data Engineer", "London", "")


def test_seniority_normalised() -> None:
    assert dedup_key("MoJ", "Senior Data Engineer", "London", "") == \
           dedup_key("MoJ", "Lead Data Engineer", "London", "")


def test_lowest_priority_integer_wins() -> None:
    r = deduplicate([vac("reed", 1, "MoJ", "Data Engineer"),
                     vac("adzuna", 1, "MoJ Ltd", "Senior Data Engineer")],
                    {"adzuna": 1, "reed": 2})
    assert len(r.kept) == 1 and r.kept[0].board_id == "adzuna"


def test_duplicates_are_logged_not_discarded() -> None:
    """Overlap between sources must stay measurable."""
    r = deduplicate([vac("adzuna", 1, "MoJ", "Data Engineer"),
                     vac("reed", 1, "MoJ Ltd", "Senior Data Engineer")],
                    {"adzuna": 1, "reed": 2})
    assert len(r.duplicates) == 1 and r.overlap_by_board == {"reed": 1}


def test_distinct_vacancies_both_kept() -> None:
    r = deduplicate([vac("adzuna", 1, "MoJ", "Data Engineer"),
                     vac("adzuna", 2, "DWP", "Data Scientist")], {"adzuna": 1})
    assert len(r.kept) == 2


def test_salary_band_distinguishes_postings() -> None:
    r = deduplicate([vac("adzuna", 1, "MoJ", "Data Engineer", salary="40,000"),
                     vac("adzuna", 2, "MoJ", "Data Engineer", salary="60,000")], {"adzuna": 1})
    assert len(r.kept) == 2


# ---------------------------------------------------------------------------
# B-11 / B-12 — pagination, and truncation must never be silent
# ---------------------------------------------------------------------------

class PagingClient:
    """Returns full pages until `total` is exhausted, PER KEYWORD.

    The pool must be per keyword, not shared. A shared pool drains on the
    first search term and every later one comes back short, which reads as a
    pagination bug in the adapter when it is a defect in the double.
    """

    def __init__(self, page_size: int, total: int, key: str = "results",
                 count_key: str = "count") -> None:
        self.page_size, self.total = page_size, total
        self.key, self.count_key = key, count_key
        self.served: dict[str, int] = {}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None):
        params = params or {}
        self.calls.append((url, params))
        term = params.get("what") or params.get("keywords") or ""
        used = self.served.get(term, 0)
        take = params.get("results_per_page") or params.get("resultsToTake") or self.page_size
        n = max(0, min(take, self.total - used))
        self.served[term] = used + n
        payload = {
            self.count_key: self.total,
            self.key: [
                {"id": str(i), "jobId": i, "title": "T", "jobTitle": "T",
                 "description": "Python.", "jobDescription": "Python.",
                 "company": {"display_name": "C"}, "employerName": "C",
                 "location": {"display_name": "L"}, "locationName": "L"}
                for i in range(n)
            ],
        }
        return FakeResponse(payload)


def _with_creds(entry, **auth):
    entry.auth.update(auth)
    return entry


def test_adzuna_paginates_beyond_the_first_page(adzuna_entry) -> None:
    """B-11: page 1 was hardcoded. Everything beyond 50 was silently lost.

    Note the keyword count. boards.yaml declares three `what` terms and board
    config currently overrides the caller's query — that is B-01, deferred to
    design proposal D-01 rather than patched. So a per-keyword ceiling of 200
    yields 200 x 3 results across 4 pages x 3 keywords.
    """
    from vanguard.adapters.adzuna import AdzunaAPIAdapter

    entry = _with_creds(adzuna_entry, app_id="x", app_key="y")
    keywords = len(entry.query.get("what") or [""])

    client = PagingClient(50, 500)
    adapter = AdzunaAPIAdapter(entry, client=client)
    results = adapter.fetch(Query(max_results=200))

    assert len(results) == 200 * keywords
    assert len(client.calls) == 4 * keywords


def test_adzuna_records_truncation(adzuna_entry) -> None:
    """B-12: the run is a sample, not a census. Say so."""
    from vanguard.adapters.adzuna import AdzunaAPIAdapter

    adapter = AdzunaAPIAdapter(
        _with_creds(adzuna_entry, app_id="x", app_key="y"),
        client=PagingClient(50, 5000),
    )
    adapter.fetch(Query(keywords=("data scientist",), max_results=100))
    assert adapter.truncations
    assert "5000" in adapter.truncations[0].reason


def test_short_page_ends_without_truncation(adzuna_entry) -> None:
    """A board with nothing more to give is not a truncation."""
    from vanguard.adapters.adzuna import AdzunaAPIAdapter

    entry = _with_creds(adzuna_entry, app_id="x", app_key="y")
    keywords = len(entry.query.get("what") or [""])

    adapter = AdzunaAPIAdapter(entry, client=PagingClient(50, 12))
    results = adapter.fetch(Query(max_results=200))

    assert len(results) == 12 * keywords
    assert not adapter.truncations


def test_max_pages_is_a_hard_stop(adzuna_entry) -> None:
    """A broad query must not run away."""
    from vanguard.adapters.adzuna import AdzunaAPIAdapter

    entry = _with_creds(adzuna_entry, app_id="x", app_key="y")
    keywords = len(entry.query.get("what") or [""])

    client = PagingClient(50, 10_000)
    adapter = AdzunaAPIAdapter(entry, client=client)
    adapter.fetch(Query(max_results=100_000, max_pages=3))

    assert len(client.calls) == 3 * keywords
    assert "max_pages" in adapter.truncations[0].reason


def test_board_config_overrides_caller_keywords(adzuna_entry) -> None:
    """Documents B-01 rather than asserting it is correct.

    A caller-supplied job title is currently ignored when boards.yaml declares
    `what`. Deferred to D-01 (adaptive query configuration) by operator ruling;
    inert until the CLI exposes --title. This test makes any change to the
    behaviour deliberate rather than accidental.
    """
    from vanguard.adapters.adzuna import AdzunaAPIAdapter

    entry = _with_creds(adzuna_entry, app_id="x", app_key="y")
    client = PagingClient(50, 10)
    adapter = AdzunaAPIAdapter(entry, client=client)
    adapter.fetch(Query(keywords=("quantum basket weaving",), max_results=50))

    sent = [c[1].get("what") for c in client.calls]
    assert "quantum basket weaving" not in sent
    assert sent == list(entry.query["what"])


def test_reed_paginates_with_offset(registry) -> None:
    from vanguard.adapters.reed import ReedAPIAdapter

    entry = _with_creds(registry.get("reed"), api_key="k")
    keywords = len(entry.query.get("what") or [""])

    client = PagingClient(100, 250, count_key="totalResults")
    adapter = ReedAPIAdapter(entry, client=client)
    results = adapter.fetch(Query(max_results=250))

    assert len(results) == 250 * keywords
    # Offsets restart per keyword: 0,100,200 for each search term.
    assert [c[1].get("resultsToSkip") for c in client.calls] == [0, 100, 200] * keywords


def test_reed_rate_limit_records_truncation(registry) -> None:
    from vanguard.adapters.reed import ReedAPIAdapter

    class Limited:
        def get(self, url, params=None):
            return FakeResponse({}, status=429)

    adapter = ReedAPIAdapter(_with_creds(registry.get("reed"), api_key="k"),
                             client=Limited())
    adapter.fetch(Query(keywords=("x",)))
    assert adapter.truncations and "rate limited" in adapter.truncations[0].reason


@pytest.mark.parametrize(
    "value, expected",
    [("{{ TARGET_LOCATION }}", True), ("{{TOKEN}}", True), ("  {{ X }}  ", True),
     ("UK", False), ("Stirling", False), ("", False), ("{{ unclosed", False)],
)
def test_placeholder_detection(value: str, expected: bool) -> None:
    """C-01: a literal `{{ TOKEN }}` sent as a query value returns nothing,
    which reads as an empty result set rather than a configuration error."""
    from vanguard.adapters.base import is_placeholder

    assert is_placeholder(value) is expected


def test_placeholder_is_blanked_on_load(tmp_path: Path) -> None:
    """Behaviour, not config content — boards.yaml values are expected to change."""
    p = tmp_path / "b.yaml"
    p.write_text(
        "boards:\n  - id: x\n    tier: manual\n"
        "    query:\n      where: \"{{ TARGET_LOCATION }}\"\n      what: [\"real value\"]\n"
    )
    entry = load_registry(p).get("x")
    assert entry.query["where"] == ""
    assert entry.query["what"] == ["real value"]


def test_real_location_survives_load(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text("boards:\n  - id: x\n    tier: manual\n    query:\n      where: \"UK\"\n")
    assert load_registry(p).get("x").query["where"] == "UK"


def test_missing_credentials_are_named(bare_registry) -> None:
    assert bare_registry.get("reed").missing_credentials == ["api_key"]


def test_every_enabled_api_board_declares_keywords(registry) -> None:
    """Reed had no `what` list, so it sent no keywords parameter and returned
    the entire 87,000-vacancy index. An enabled API board without keywords is
    a configuration defect, not a wildcard search."""
    for entry in registry.enabled:
        if entry.tier is not Tier.API_OFFICIAL:
            continue
        assert entry.query.get("what"), (
            f"board {entry.id!r} is an enabled API board with no `what` keywords — "
            "it would search the whole index"
        )


# ---------------------------------------------------------------------------
# B-04 — hydration: search snippets must be replaced with the full advert
# ---------------------------------------------------------------------------

def test_reed_marks_search_results_partial(registry) -> None:
    from vanguard.adapters.reed import ReedAPIAdapter

    v = ReedAPIAdapter(registry.get("reed")).normalise(RawVacancy("reed", {
        "jobId": 1, "jobTitle": "Data Scientist", "employerName": "Acme",
        "jobDescription": "Short snippet about data...", "locationName": "London",
    }))
    assert v.description_is_partial


def test_reed_hydrate_replaces_the_snippet(registry) -> None:
    full = "Person Specification\n- Python and SQL\n- data wrangling\n" * 6

    class DetailClient:
        def get(self, url, params=None):
            return FakeResponse({"jobDescription": full})

    adapter = ReedAPIAdapter(_with_creds(registry.get("reed"), api_key="k"),
                             client=DetailClient())
    v = adapter.normalise(RawVacancy("reed", {
        "jobId": 42, "jobTitle": "T", "employerName": "E",
        "jobDescription": "snippet...", "locationName": "L",
    }))
    hydrated = adapter.hydrate(v)
    assert not hydrated.description_is_partial
    assert len(hydrated.description) > 100


def test_hydration_failure_keeps_the_snippet(registry) -> None:
    """A failed detail call must not lose the vacancy — the flag stays set."""
    class Broken:
        def get(self, url, params=None):
            raise RuntimeError("network down")

    adapter = ReedAPIAdapter(_with_creds(registry.get("reed"), api_key="k"),
                             client=Broken())
    adapter.fetch = lambda q: [RawVacancy("reed", {
        "jobId": 1, "jobTitle": "T", "employerName": "E",
        "jobDescription": "snippet...", "locationName": "L"})]

    collected = adapter.collect(Query())
    assert len(collected) == 1
    assert collected[0].description_is_partial


def test_hydrate_does_not_shorten(registry) -> None:
    """A detail response shorter than the snippet is not an improvement."""
    class Shorter:
        def get(self, url, params=None):
            return FakeResponse({"jobDescription": "x"})

    adapter = ReedAPIAdapter(_with_creds(registry.get("reed"), api_key="k"),
                             client=Shorter())
    v = adapter.normalise(RawVacancy("reed", {
        "jobId": 1, "jobTitle": "T", "employerName": "E",
        "jobDescription": "a considerably longer snippet than the reply",
        "locationName": "L"}))
    assert "longer snippet" in adapter.hydrate(v).description


def test_adzuna_flags_truncated_descriptions(registry) -> None:
    from vanguard.adapters.adzuna import AdzunaAPIAdapter

    adapter = AdzunaAPIAdapter(registry.get("adzuna"))
    truncated = adapter.normalise(RawVacancy("adzuna", {
        "id": "1", "title": "T", "description": "We are seeking a data scientist…",
        "company": {"display_name": "C"}, "location": {"display_name": "L"}}))
    assert truncated.description_is_partial

    full = adapter.normalise(RawVacancy("adzuna", {
        "id": "2", "title": "T", "description": "Person Specification. " * 40,
        "company": {"display_name": "C"}, "location": {"display_name": "L"}}))
    assert not full.description_is_partial


def test_limiter_refuses_to_block_indefinitely() -> None:
    """A limiter that sleeps for an hour is indistinguishable from a hang.

    Hydration makes one detail call per vacancy. At 300 vacancies against
    60/hour, the run would appear frozen for hours with no output.
    """
    from vanguard.adapters.base import RateLimitExceeded

    now = [0.0]
    rl = RateLimiter(2, sleep=lambda s: now.__setitem__(0, now[0] + s),
                     clock=lambda: now[0])
    rl.MAX_SINGLE_WAIT = 10.0
    rl.acquire()
    rl.acquire()
    with pytest.raises(RateLimitExceeded, match="reduce max_results"):
        rl.acquire()


def test_limiter_still_waits_for_short_delays() -> None:
    """A wait inside the cap is served, not refused."""
    slept: list[float] = []
    now = [0.0]
    rl = RateLimiter(2, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                     clock=lambda: now[0])
    rl.acquire()
    rl.acquire()
    now[0] = 3000.0          # 600s left in the window — inside the 900s cap
    rl.acquire()
    assert slept and 0 < slept[0] <= rl.MAX_SINGLE_WAIT


# ---------------------------------------------------------------------------
# Capability gate — a board that cannot be assessed must not be automated
# ---------------------------------------------------------------------------

def test_board_without_full_text_cannot_be_fetched(tmp_path: Path) -> None:
    """Adzuna caps descriptions at exactly 500 characters with no detail
    endpoint. Scoring a two-sentence summary produced C=1.000 for a Service
    Centre Team Manager."""
    from vanguard.adapters.base import InsufficientForAssessment

    p = tmp_path / "b.yaml"
    p.write_text(
        "boards:\n  - id: x\n    tier: manual\n    enabled: true\n"
        "    supplies_full_text: false\n"
    )
    entry = load_registry(p).get("x")
    assert not entry.assessable
    with pytest.raises((InsufficientForAssessment, TermsViolation)):
        entry.assert_fetchable()


def test_automated_board_without_full_text_is_rejected_at_load(tmp_path: Path) -> None:
    """The contradiction must be caught in config, not discovered after a run."""
    from vanguard.adapters.base import InsufficientForAssessment

    p = tmp_path / "b.yaml"
    p.write_text(
        "boards:\n  - id: x\n    tier: api_official\n    enabled: true\n"
        "    supplies_full_text: false\n"
    )
    with pytest.raises(InsufficientForAssessment, match="must not be automated"):
        load_registry(p)


def test_adzuna_is_demoted_to_manual(registry) -> None:
    """Capability, not terms. Adzuna is legal to poll and useless to score."""
    entry = registry.get("adzuna")
    assert entry.tier is Tier.MANUAL
    assert not entry.supplies_full_text


def test_reed_remains_assessable(registry) -> None:
    """Reed has a detail endpoint, so it can still be automated."""
    entry = registry.get("reed")
    assert entry.tier is Tier.API_OFFICIAL
    assert entry.supplies_full_text


def test_every_automatable_board_supplies_full_text(registry) -> None:
    for entry in registry.automatable:
        assert entry.assessable, f"{entry.id} is automated but cannot be assessed"


def test_unhydrated_vacancies_are_reported(registry) -> None:
    """The first version swallowed RateLimitExceeded and left 240 of 300
    vacancies scored on snippets with no indication anything went wrong."""
    from vanguard.adapters.base import RateLimitExceeded
    from vanguard.adapters.reed import ReedAPIAdapter

    adapter = ReedAPIAdapter(_with_creds(registry.get("reed"), api_key="k"))
    adapter.fetch = lambda q: [
        RawVacancy("reed", {"jobId": i, "jobTitle": f"T{i}", "employerName": "E",
                            "jobDescription": "snippet...", "locationName": "L"})
        for i in range(3)
    ]

    def refuse(vacancy):
        raise RateLimitExceeded("would block for 3600s")

    adapter.hydrate = refuse
    collected = adapter.collect(Query())

    assert len(collected) == 3
    assert all(v.description_is_partial for v in collected)
    assert adapter.truncations, "silent partial scoring must be reported"
    assert "could not be hydrated" in adapter.truncations[0].reason
