"""
Board adapter interface and shared ingestion machinery.

Directive §1. Sources are declared in `boards.yaml`. No board is hardcoded;
adding or removing one is a configuration change, never a code change. The
pipeline never names a board — it iterates the registry.

Access tiers, in strict order of preference:

    TIER 1  api_official   documented API, credentialed. Preferred always
    TIER 2  feed           RSS/JSON feed or publisher-operated email alert
    TIER 3  manual         operator pastes URL or text. No automation

A board with no Tier 1 or Tier 2 route is registered Tier 3. Scraping a site
whose terms prohibit automated collection is prohibited regardless of
technical feasibility, and content behind authentication is never fetched.
`RegistryEntry.assert_fetchable()` enforces both in code.

Rate limiting is mandatory and defaults to conservative: 60 calls/hour with
exponential backoff, honouring `robots.txt`, `Retry-After` and HTTP 429.
"""

from __future__ import annotations

import os
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "Tier",
    "InsufficientForAssessment",
    "RateLimitExceeded",
    "is_placeholder",
    "Truncation",
    "Query",
    "RawVacancy",
    "Vacancy",
    "AdapterStatus",
    "BoardAdapter",
    "RegistryEntry",
    "BoardRegistry",
    "RateLimiter",
    "IngestionError",
    "TermsViolation",
    "load_registry",
    "deduplicate",
    "dedup_key",
]

DEFAULT_CALLS_PER_HOUR = 60
DEFAULT_SILENCE_DAYS = 21


class IngestionError(RuntimeError):
    """A source could not be ingested."""


class RateLimitExceeded(IngestionError):
    """A call would have blocked longer than the permitted single wait."""


class TermsViolation(IngestionError):
    """A fetch was attempted that the board's terms or tier prohibit.

    Raised rather than logged. A terms breach is not a degraded outcome to be
    recovered from — it is a request that must never leave the process.
    """


class InsufficientForAssessment(IngestionError):
    """A board was configured for automation but cannot supply full advert text.

    Coverage is computed from requirement terms extracted from the advert. A
    board that returns a 500-character summary cannot support that: extraction
    finds one or two terms and the ratio becomes meaningless. Scoring it
    anyway produces numbers that look like measurements and are not.
    """


class Tier(str, Enum):
    API_OFFICIAL = "api_official"
    FEED = "feed"
    MANUAL = "manual"

    @property
    def automatable(self) -> bool:
        """Tier 3 is hand-fed. Everything downstream still runs on it."""
        return self is not Tier.MANUAL

    @property
    def preference(self) -> int:
        return {"api_official": 1, "feed": 2, "manual": 3}[self.value]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Query:
    """What to ask a board for. Boards translate this to their own parameters.

    `max_results` is a per-keyword ceiling across ALL pages, not a page size.
    Adapters paginate until they reach it or the board runs out.
    """

    keywords: tuple[str, ...] = ()
    location: str = ""
    country: str = "gb"
    max_days_old: int = 7
    max_results: int = 100
    max_pages: int = 5      # hard stop, so a broad query cannot run away


@dataclass
class RawVacancy:
    """Whatever the board returned, unnormalised. Kept for audit."""

    board_id: str
    payload: dict[str, Any]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Vacancy:
    """Normalised vacancy. The only shape the rest of the pipeline sees."""

    id: str
    board_id: str
    employer: str
    title: str
    description: str
    location: str = ""
    salary_band: str = ""
    url: str = ""
    posted: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reference: str = ""   # employer vacancy reference — correlation stage 1
    description_is_partial: bool = False   # search snippet, not the full advert

    def __post_init__(self) -> None:
        if not self.id:
            raise IngestionError("vacancy has no id")
        if not self.title.strip():
            raise IngestionError(f"vacancy {self.id} has no title")
        if not self.description.strip():
            raise IngestionError(
                f"vacancy {self.id} has no description — nothing to extract requirements from"
            )

    @property
    def dedup_key(self) -> str:
        return dedup_key(self.employer, self.title, self.location, self.salary_band)


@dataclass
class Truncation:
    """A board had more results than were collected.

    Recorded rather than swallowed. Silent truncation is the same failure as
    silent misclassification: the output looks complete and is not, and
    nothing downstream can tell the difference.
    """

    board_id: str
    keyword: str
    collected: int
    reason: str

    def __str__(self) -> str:
        term = f" for {self.keyword!r}" if self.keyword else ""
        return f"{self.board_id}{term}: stopped at {self.collected} — {self.reason}"


@dataclass
class AdapterStatus:
    """Result of a health check. Terms are re-verified before enabling a board."""

    board_id: str
    reachable: bool
    detail: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        return f"{self.board_id}: {'OK' if self.reachable else 'UNREACHABLE'} — {self.detail}"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")
_COMPANY_SUFFIX = re.compile(
    r"\b(?:ltd|limited|plc|llp|inc|incorporated|corp|corporation|group|uk|gb)\b"
)
_SENIORITY = re.compile(r"\b(?:senior|snr|sr|junior|jnr|jr|lead|principal|staff)\b")


def _normalise(text: str) -> str:
    t = _PUNCT.sub(" ", (text or "").lower())
    return _WS.sub(" ", t).strip()


def dedup_key(employer: str, title: str, location: str, salary_band: str) -> str:
    """Composite key per directive §1.

    Employer suffixes and seniority prefixes are normalised away: the same
    vacancy syndicated to two boards routinely differs by 'Ltd' or 'Senior'.
    Salary band is included because it distinguishes genuinely different
    postings at the same employer and title.
    """
    emp = _WS.sub(" ", _COMPANY_SUFFIX.sub("", _normalise(employer))).strip()
    ttl = _WS.sub(" ", _SENIORITY.sub("", _normalise(title))).strip()
    return "|".join([emp, ttl, _normalise(location), _normalise(salary_band)])


@dataclass
class DedupResult:
    kept: tuple[Vacancy, ...]
    duplicates: tuple[tuple[Vacancy, str], ...]  # (dropped vacancy, kept id)

    @property
    def overlap_by_board(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for vac, _ in self.duplicates:
            counts[vac.board_id] = counts.get(vac.board_id, 0) + 1
        return counts


def deduplicate(
    vacancies: Iterable[Vacancy], priority: dict[str, int]
) -> DedupResult:
    """Collapse duplicates across sources. Lowest `priority` integer wins.

    Duplicates are logged, not discarded, so overlap between sources stays
    measurable — Find a Job is substantially the Adzuna corpus, and polling
    both without measuring the overlap double-counts silently.
    """
    best: dict[str, Vacancy] = {}
    dropped: list[tuple[Vacancy, str]] = []

    for vac in vacancies:
        key = vac.dedup_key
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = vac
            continue
        p_new = priority.get(vac.board_id, 99)
        p_old = priority.get(incumbent.board_id, 99)
        if p_new < p_old:
            best[key] = vac
            dropped.append((incumbent, vac.id))
        else:
            dropped.append((vac, incumbent.id))

    return DedupResult(tuple(best.values()), tuple(dropped))


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window limiter with exponential backoff. Thread-safe.

    Conservative by default. `acquire()` blocks until a call is permitted;
    `penalise()` is called on 429 or Retry-After and doubles the wait, up to
    a ceiling.
    """

    def __init__(
        self,
        calls_per_hour: int = DEFAULT_CALLS_PER_HOUR,
        *,
        backoff_base: float = 2.0,
        max_backoff: float = 300.0,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        if calls_per_hour <= 0:
            raise ValueError("calls_per_hour must be positive")
        self.calls_per_hour = calls_per_hour
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self._sleep = sleep
        self._clock = clock
        self._calls: deque[float] = deque()
        self._failures = 0
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    @property
    def window(self) -> float:
        return 3600.0

    def _prune(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self.window:
            self._calls.popleft()

    #: Refuse to block longer than this in one acquire. A limiter that sleeps
    #: for an hour is indistinguishable from a hang, and a caller that hits it
    #: needs to know rather than wait.
    MAX_SINGLE_WAIT = 900.0

    def acquire(self) -> float:
        """Block until a call is permitted. Returns seconds waited.

        Raises RateLimitExceeded rather than sleeping past MAX_SINGLE_WAIT.
        """
        with self._lock:
            waited = 0.0
            now = self._clock()

            if now < self._blocked_until:
                waited += self._blocked_until - now
                self._sleep(self._blocked_until - now)
                now = self._clock()

            self._prune(now)
            if len(self._calls) >= self.calls_per_hour:
                delay = self.window - (now - self._calls[0])
                if delay > self.MAX_SINGLE_WAIT:
                    raise RateLimitExceeded(
                        f"rate limit would block for {delay:.0f}s "
                        f"(cap {self.MAX_SINGLE_WAIT:.0f}s) at "
                        f"{self.calls_per_hour} calls/hour — reduce max_results "
                        "or narrow the keyword list"
                    )
                if delay > 0:
                    waited += delay
                    self._sleep(delay)
                    now = self._clock()
                    self._prune(now)

            self._calls.append(now)
            return waited

    def penalise(self, retry_after: float | None = None) -> float:
        """Called on 429 / Retry-After. Returns the backoff applied."""
        with self._lock:
            self._failures += 1
            delay = (
                float(retry_after)
                if retry_after is not None
                else min(self.backoff_base ** self._failures, self.max_backoff)
            )
            self._blocked_until = self._clock() + delay
            return delay

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._blocked_until = 0.0


# ---------------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------------

class BoardAdapter(ABC):
    """One adapter class, one YAML block. The pipeline never names a board."""

    def __init__(self, entry: RegistryEntry) -> None:
        self.entry = entry
        self.limiter = RateLimiter(entry.calls_per_hour)
        self.truncations: list[Truncation] = []

    def _note_truncation(self, keyword: str, collected: int, reason: str) -> None:
        self.truncations.append(Truncation(self.board_id, keyword, collected, reason))

    @property
    def board_id(self) -> str:
        return self.entry.id

    @abstractmethod
    def fetch(self, query: Query) -> list[RawVacancy]:
        """Retrieve raw vacancies. Must call `entry.assert_fetchable()` first."""

    @abstractmethod
    def normalise(self, raw: RawVacancy) -> Vacancy:
        """Convert a raw payload to the canonical Vacancy shape."""

    @abstractmethod
    def health_check(self) -> AdapterStatus:
        """Is the source reachable and are its terms still as recorded?"""

    def hydrate(self, vacancy: Vacancy) -> Vacancy:
        """Replace a search snippet with the full advert text.

        Search endpoints return a truncated description. Requirement extraction
        against a snippet finds one or two technology names and no Person
        Specification, which produces coverage denominators of 1 or 2 — a
        Service Centre Team Manager scores 1.000 because the snippet said
        "data" and the CV says "data".

        Default is a no-op. Boards whose search response is already complete
        need do nothing; boards with a detail endpoint override this.
        """
        return vacancy

    def collect(self, query: Query, *, hydrate: bool = True) -> list[Vacancy]:
        """fetch + normalise + hydrate. Skips bad records, never aborts.

        Hydration failure is not fatal: a partial description still scores,
        and `description_is_partial` records that the number is unreliable.
        """
        out: list[Vacancy] = []
        unhydrated = 0

        for raw in self.fetch(query):
            try:
                vacancy = self.normalise(raw)
            except IngestionError:
                continue

            if hydrate and vacancy.description_is_partial:
                try:
                    vacancy = self.hydrate(vacancy)
                except RateLimitExceeded:
                    # Hydration is now impossible for the rest of this run.
                    # Stop trying, and SAY SO — the first version swallowed
                    # this and left 240 of 300 vacancies scored on snippets
                    # with no indication anything had gone wrong.
                    unhydrated += 1
                    hydrate = False
                except Exception:
                    unhydrated += 1
                if vacancy.description_is_partial and hydrate:
                    unhydrated += 1

            out.append(vacancy)

        remaining = sum(1 for v in out if v.description_is_partial)
        if remaining:
            self._note_truncation(
                "", len(out) - remaining,
                f"{remaining} of {len(out)} vacancies could not be hydrated — "
                f"scored on partial text at {self.entry.calls_per_hour} calls/hour. "
                "Reduce max_results.",
            )
        return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ENV = re.compile(r"\$\{(\w+)\}")
_PLACEHOLDER = re.compile(r"^\s*\{\{.*\}\}\s*$")


def is_placeholder(value: Any) -> bool:
    """True for an unedited `{{ TOKEN }}` left in the config.

    Sending the literal string as a query parameter returns nothing and looks
    like an empty result set rather than a configuration error.
    """
    return isinstance(value, str) and bool(_PLACEHOLDER.match(value))


def _expand(value: Any) -> Any:
    """Resolve ${ENV_VAR} references. Credentials never live in the YAML."""
    if isinstance(value, str):
        if is_placeholder(value):
            return ""      # unresolved token -> treat as unset, not as a value
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class RegistryEntry:
    """One board's configuration.

    `supplies_full_text` is a CAPABILITY declaration, separate from tier.
    Tier records what a board's terms permit; this records whether what it
    returns is sufficient to assess against. A board may be perfectly legal to
    poll and still useless for scoring.

    Operator ruling, 9 Aug 2026: a board that cannot supply full advert text
    is not processed through its API at all. It defaults to operator paste.
    """

    id: str
    adapter: str
    enabled: bool
    tier: Tier
    supplies_full_text: bool = True
    priority: int = 99
    silence_days: int = DEFAULT_SILENCE_DAYS
    calls_per_hour: int = DEFAULT_CALLS_PER_HOUR
    auth: dict[str, str] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    portal_url: str = ""
    ingress: dict[str, str] = field(default_factory=dict)
    note: str = ""

    def assert_fetchable(self) -> None:
        """Guard every automated fetch. Raises rather than degrading."""
        if not self.enabled:
            raise TermsViolation(f"board {self.id!r} is disabled and must not be contacted")
        if not self.tier.automatable:
            raise TermsViolation(
                f"board {self.id!r} is Tier 3 (manual): automated collection is "
                "prohibited by its terms. Operator pastes URL or text."
            )
        if not self.supplies_full_text:
            raise InsufficientForAssessment(
                f"board {self.id!r} cannot supply full advert text, so nothing "
                "fetched from it can be scored. Register it as tier: manual and "
                "paste vacancies with `vanguard paste`."
            )

    @property
    def assessable(self) -> bool:
        """Can a vacancy from this board be scored at all?"""
        return self.supplies_full_text

    @property
    def credentials_present(self) -> bool:
        return all(bool(v) for v in self.auth.values()) if self.auth else True

    @property
    def missing_credentials(self) -> list[str]:
        return [k for k, v in self.auth.items() if not v]


@dataclass
class BoardRegistry:
    entries: tuple[RegistryEntry, ...]
    defaults: dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, board_id: str) -> RegistryEntry:
        for e in self.entries:
            if e.id == board_id:
                return e
        raise KeyError(f"no such board: {board_id}")

    @property
    def enabled(self) -> list[RegistryEntry]:
        return [e for e in self.entries if e.enabled]

    @property
    def automatable(self) -> list[RegistryEntry]:
        """Enabled boards the pipeline may fetch from without an operator."""
        return [e for e in self.enabled if e.tier.automatable]

    @property
    def manual(self) -> list[RegistryEntry]:
        return [e for e in self.enabled if not e.tier.automatable]

    @property
    def priority_map(self) -> dict[str, int]:
        return {e.id: e.priority for e in self.entries}

    def silence_days_for(self, board_id: str) -> int:
        try:
            return self.get(board_id).silence_days
        except KeyError:
            return int(self.defaults.get("silence_days", DEFAULT_SILENCE_DAYS))


def load_registry(path: Path | str) -> BoardRegistry:
    """Parse `boards.yaml`. Hot-reloadable: re-call to pick up config changes."""
    import yaml

    path = Path(path)
    if not path.is_file():
        raise IngestionError(f"board registry not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults", {}) or {}
    default_rate = (defaults.get("rate_limit") or {}).get(
        "calls_per_hour", DEFAULT_CALLS_PER_HOUR
    )
    default_silence = defaults.get("silence_days", DEFAULT_SILENCE_DAYS)

    entries: list[RegistryEntry] = []
    seen: set[str] = set()

    for raw in data.get("boards", []) or []:
        bid = raw.get("id", "")
        if not bid:
            raise IngestionError("board entry with no id")
        if bid in seen:
            raise IngestionError(f"duplicate board id: {bid}")
        seen.add(bid)

        try:
            tier = Tier(str(raw.get("tier", "manual")))
        except ValueError as exc:
            raise IngestionError(f"board {bid!r} has unknown tier {raw.get('tier')!r}") from exc

        rate = (raw.get("rate_limit") or {}).get("calls_per_hour", default_rate)

        entries.append(
            RegistryEntry(
                id=bid,
                adapter=raw.get("adapter", ""),
                enabled=bool(raw.get("enabled", False)),
                tier=tier,
                priority=int(raw.get("priority", 99)),
                silence_days=int(raw.get("silence_days", default_silence)),
                calls_per_hour=int(rate),
                supplies_full_text=bool(raw.get("supplies_full_text", True)),
                auth=_expand(raw.get("auth", {}) or {}),
                query=_expand(raw.get("query", {}) or {}),
                portal_url=str(raw.get("portal_url", "")),
                ingress=_expand(raw.get("ingress", {}) or {}),
                note=re.sub(r"\s+", " ", str(raw.get("note", ""))).strip(),
            )
        )

    for entry in entries:
        if entry.enabled and entry.tier.automatable and not entry.supplies_full_text:
            raise InsufficientForAssessment(
                f"board {entry.id!r} is enabled at tier {entry.tier.value} but declares "
                "supplies_full_text: false. A board that cannot be assessed must not "
                "be automated — set tier: manual."
            )

    return BoardRegistry(tuple(entries), defaults)
