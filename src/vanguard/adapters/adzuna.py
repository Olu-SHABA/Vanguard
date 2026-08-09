"""
Adzuna adapter — Tier 1, dedup master.

Self-service credentials: register at the developer portal for an app_id and
app_key, both passed as query parameters on every request. Country is set in
the path (/gb/), with parameters for keywords, location, salary floor and
contract type.

Adzuna aggregates from many boards, which recovers partial coverage of sources
that have no API of their own — hence priority 1 and its role as the dedup
master. Find a Job (DWP) is substantially the same corpus: the platform was
built in partnership with Adzuna and its search runs on Adzuna technology, so
polling both without deduplication double-counts.

The HTTP client is injected. Nothing here reaches the network in a test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from vanguard.adapters.base import (
    AdapterStatus,
    BoardAdapter,
    IngestionError,
    Query,
    RawVacancy,
    Vacancy,
)

__all__ = ["AdzunaAPIAdapter", "HttpClient"]

_BASE = "https://api.adzuna.com/v1/api/jobs"
PAGE_SIZE = 50  # Adzuna hard maximum per page


class HttpClient(Protocol):
    """Minimal surface. `httpx.Client` satisfies this."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any: ...


class AdzunaAPIAdapter(BoardAdapter):
    def __init__(self, entry, client: HttpClient | None = None) -> None:
        super().__init__(entry)
        self._client = client

    # -- client ------------------------------------------------------------

    def _http(self) -> HttpClient:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise IngestionError("httpx required: pip install httpx") from exc
            self._client = httpx.Client(timeout=30.0, follow_redirects=True)
        return self._client

    def _credentials(self) -> tuple[str, str]:
        app_id = self.entry.auth.get("app_id", "")
        app_key = self.entry.auth.get("app_key", "")
        if not app_id or not app_key:
            raise IngestionError(
                f"{self.board_id}: ADZUNA_APP_ID and ADZUNA_APP_KEY must be set "
                "in the environment. Credentials never live in boards.yaml."
            )
        return app_id, app_key

    # -- fetch -------------------------------------------------------------

    def fetch(self, query: Query) -> list[RawVacancy]:
        self.entry.assert_fetchable()
        app_id, app_key = self._credentials()

        cfg = self.entry.query or {}
        country = str(cfg.get("country", query.country) or "gb").lower()
        keywords = tuple(cfg.get("what") or query.keywords or ())
        where = str(cfg.get("where", query.location) or "")
        max_age = int(cfg.get("max_days_old", query.max_days_old))

        out: list[RawVacancy] = []
        self.truncations.clear()
        page_size = min(query.max_results, PAGE_SIZE)

        for term in keywords or ("",):
            collected = 0
            for page in range(1, query.max_pages + 1):
                params = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "results_per_page": page_size,
                    "max_days_old": max_age,
                    "content-type": "application/json",
                }
                if term:
                    params["what"] = term
                if where:
                    params["where"] = where

                self.limiter.acquire()
                payload = self._request(f"{_BASE}/{country}/search/{page}", params)
                results = payload.get("results", []) or []

                for item in results:
                    out.append(RawVacancy(self.board_id, item))
                collected += len(results)

                # A short page means the board has no more for this term.
                if len(results) < page_size:
                    break
                if collected >= query.max_results:
                    self._note_truncation(
                        term, collected,
                        f"reached max_results={query.max_results}; "
                        f"board reported {payload.get('count', 'unknown')} total",
                    )
                    break
            else:
                self._note_truncation(
                    term, collected,
                    f"reached max_pages={query.max_pages}; more results remain",
                )

        return out

    def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """One call, honouring 429 and Retry-After with exponential backoff."""
        for attempt in range(3):
            response = self._http().get(url, params=params)
            status = getattr(response, "status_code", 200)

            if status == 429:
                retry_after = None
                headers = getattr(response, "headers", {}) or {}
                if "Retry-After" in headers:
                    try:
                        retry_after = float(headers["Retry-After"])
                    except (TypeError, ValueError):
                        retry_after = None
                self.limiter.penalise(retry_after)
                continue

            if status >= 400:
                raise IngestionError(f"{self.board_id}: HTTP {status} from {url}")

            self.limiter.reset()
            try:
                return response.json()
            except Exception as exc:
                raise IngestionError(f"{self.board_id}: malformed JSON response") from exc

        raise IngestionError(f"{self.board_id}: rate limited after 3 attempts")

    # -- normalise ---------------------------------------------------------

    def normalise(self, raw: RawVacancy) -> Vacancy:
        p = raw.payload
        company = (p.get("company") or {}).get("display_name", "")
        location = (p.get("location") or {}).get("display_name", "")

        lo, hi = p.get("salary_min"), p.get("salary_max")
        band = ""
        if lo and hi:
            band = f"{int(lo):,} - {int(hi):,}"
        elif lo or hi:
            band = f"{int(lo or hi):,}"

        return Vacancy(
            id=f"{self.board_id}:{p.get('id', '')}",
            board_id=self.board_id,
            employer=company,
            title=p.get("title", ""),
            description=p.get("description", ""),
            location=location,
            salary_band=band,
            url=p.get("redirect_url", ""),
            posted=_parse_dt(p.get("created")),
            fetched_at=raw.fetched_at,
            # Adzuna truncates the search description and marks it with an
            # ellipsis. There is no detail endpoint on the free tier, so the
            # flag records unreliability rather than enabling a fix.
            description_is_partial=_looks_truncated(p.get("description", "")),
        )

    def health_check(self) -> AdapterStatus:
        try:
            self.entry.assert_fetchable()
            self._credentials()
        except Exception as exc:
            return AdapterStatus(self.board_id, False, str(exc))
        return AdapterStatus(self.board_id, True, "credentials present, tier 1 api_official")


def _looks_truncated(text: str) -> bool:
    """Adzuna marks a cut description with a trailing ellipsis."""
    stripped = (text or "").rstrip()
    return stripped.endswith(("…", "...")) or len(stripped) < 400


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
