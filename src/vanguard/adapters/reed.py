"""
Reed adapter — Tier 1.

Self-service API key, passed as HTTP Basic auth with the key as username and
an empty password. The jobseeker search endpoint returns job id, employer,
title, description, location and salary range.

Reed's search response carries a truncated description. `fetch_detail()`
retrieves the full text for a single job, which matters because requirement
extraction against a truncated advert produces a short, misleading term list.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from vanguard.adapters.base import (
    AdapterStatus,
    BoardAdapter,
    IngestionError,
    Query,
    RawVacancy,
    Vacancy,
)
from vanguard.adapters.adzuna import HttpClient

__all__ = ["ReedAPIAdapter"]

_SEARCH = "https://www.reed.co.uk/api/1.0/search"
_DETAIL = "https://www.reed.co.uk/api/1.0/jobs"
PAGE_SIZE = 100  # Reed maximum per request


class ReedAPIAdapter(BoardAdapter):
    def __init__(self, entry, client: HttpClient | None = None) -> None:
        super().__init__(entry)
        self._client = client

    def _http(self) -> HttpClient:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise IngestionError("httpx required: pip install httpx") from exc
            key = self._api_key()
            token = base64.b64encode(f"{key}:".encode()).decode()
            self._client = httpx.Client(
                timeout=30.0, headers={"Authorization": f"Basic {token}"}
            )
        return self._client

    def _api_key(self) -> str:
        key = self.entry.auth.get("api_key", "")
        if not key:
            raise IngestionError(
                f"{self.board_id}: REED_API_KEY must be set in the environment"
            )
        return key

    def fetch(self, query: Query) -> list[RawVacancy]:
        self.entry.assert_fetchable()
        self._api_key()

        cfg = self.entry.query or {}
        keywords = tuple(cfg.get("what") or query.keywords or ())
        where = str(cfg.get("where", query.location) or "")

        out: list[RawVacancy] = []
        self.truncations.clear()
        page_size = min(query.max_results, PAGE_SIZE)

        for term in keywords or ("",):
            collected = 0
            for page in range(query.max_pages):
                params: dict[str, Any] = {
                    "resultsToTake": page_size,
                    "resultsToSkip": page * page_size,
                }
                if term:
                    params["keywords"] = term
                if where:
                    params["locationName"] = where

                self.limiter.acquire()
                response = self._http().get(_SEARCH, params=params)
                status = getattr(response, "status_code", 200)

                if status == 429:
                    self.limiter.penalise()
                    self._note_truncation(term, collected, "rate limited by board")
                    break
                if status >= 400:
                    raise IngestionError(f"{self.board_id}: HTTP {status} from search")

                self.limiter.reset()
                try:
                    payload = response.json()
                except Exception as exc:
                    raise IngestionError(f"{self.board_id}: malformed JSON") from exc

                results = payload.get("results", []) or []
                for item in results:
                    out.append(RawVacancy(self.board_id, item))
                collected += len(results)

                if len(results) < page_size:
                    break
                if collected >= query.max_results:
                    self._note_truncation(
                        term, collected,
                        f"reached max_results={query.max_results}; "
                        f"board reported {payload.get('totalResults', 'unknown')} total",
                    )
                    break
            else:
                self._note_truncation(
                    term, collected,
                    f"reached max_pages={query.max_pages}; more results remain",
                )

        return out

    def fetch_detail(self, job_id: int | str) -> dict[str, Any]:
        """Full description for one job. Search results are truncated."""
        self.entry.assert_fetchable()
        self.limiter.acquire()
        response = self._http().get(f"{_DETAIL}/{job_id}")
        if getattr(response, "status_code", 200) >= 400:
            raise IngestionError(f"{self.board_id}: HTTP error fetching job {job_id}")
        return response.json()

    def normalise(self, raw: RawVacancy) -> Vacancy:
        p = raw.payload
        lo, hi = p.get("minimumSalary"), p.get("maximumSalary")
        band = ""
        if lo and hi:
            band = f"{int(lo):,} - {int(hi):,}"
        elif lo or hi:
            band = f"{int(lo or hi):,}"

        return Vacancy(
            id=f"{self.board_id}:{p.get('jobId', '')}",
            board_id=self.board_id,
            employer=p.get("employerName", ""),
            title=p.get("jobTitle", ""),
            description=p.get("jobDescription", ""),
            location=p.get("locationName", ""),
            salary_band=band,
            url=p.get("jobUrl", ""),
            posted=_parse_date(p.get("date")),
            fetched_at=raw.fetched_at,
        )

    def health_check(self) -> AdapterStatus:
        try:
            self.entry.assert_fetchable()
            self._api_key()
        except Exception as exc:
            return AdapterStatus(self.board_id, False, str(exc))
        return AdapterStatus(self.board_id, True, "api key present, tier 1 api_official")


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None
