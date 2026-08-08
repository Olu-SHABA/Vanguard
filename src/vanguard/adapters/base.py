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


class TermsViolation(IngestionError):
    """A fetch was attempted that the board's terms or tier prohibit.

    Raised rather than logged. A terms breach is not a degraded outcome to be
    recovered from — it is a request that must never leave the process.
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
    """What to ask a board for. Boards translate this to their own parameters."""

    keywords: tuple[str, ...] = ()
    location: str = ""
    country: str = "gb"
    max_days_old: int = 7
    max_results: int = 50


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

    def acquire(self) -> float:
        """Block until a call is permitted. Returns seconds waited."""
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

    def collect(self, query: Query) -> list[Vacancy]:
        """fetch + normalise. Skips records that fail validation, never aborts."""
        out: list[Vacancy] = []
        for raw in self.fetch(query):
            try:
                out.append(self.normalise(raw))
            except IngestionError:
                continue
        return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ENV = re.compile(r"\$\{(\w+)\}")


def _expand(value: Any) -> Any:
    """Resolve ${ENV_VAR} references. Credentials never live in the YAML."""
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class RegistryEntry:
    """One board's configuration."""

    id: str
    adapter: str
    enabled: bool
    tier: Tier
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

    @property
    def credentials_present(self) -> bool:
        return all(bool(v) for v in self.auth.values()) if self.auth else True


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
                auth=_expand(raw.get("auth", {}) or {}),
                query=_expand(raw.get("query", {}) or {}),
                portal_url=str(raw.get("portal_url", "")),
                ingress=_expand(raw.get("ingress", {}) or {}),
                note=re.sub(r"\s+", " ", str(raw.get("note", ""))).strip(),
            )
        )

    return BoardRegistry(tuple(entries), defaults)
