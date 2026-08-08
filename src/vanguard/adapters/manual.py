"""
Manual entry adapter — Tier 3.

Built first, and permanent architecture rather than a stopgap. LinkedIn's User
Agreement prohibits automated collection, and it is likely the densest source
of relevant senior roles. Manual entry with full downstream processing is the
correct answer, not a compromise.

Tier 3 does not mean the board is skipped. It means one step is hand-fed:
scoring, gap classification, refactoring and drafting all run identically on a
pasted vacancy.

`fetch()` deliberately raises. There is no automated path.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from vanguard.adapters.base import (
    AdapterStatus,
    BoardAdapter,
    IngestionError,
    Query,
    RawVacancy,
    TermsViolation,
    Vacancy,
)

__all__ = ["ManualEntryAdapter"]

_EMPLOYER_HINTS = (
    re.compile(r"^\s*(?:employer|company|organisation|organization)\s*:\s*(?P<v>.+)$", re.I | re.M),
    re.compile(r"^\s*(?:at|with)\s+(?P<v>[A-Z][\w&.\- ]{2,60})\s*$", re.M),
)
_TITLE_HINTS = (
    re.compile(r"^\s*(?:job title|position|role|vacancy)\s*:\s*(?P<v>.+)$", re.I | re.M),
)
_LOCATION_HINTS = (
    re.compile(r"^\s*location\s*:\s*(?P<v>.+)$", re.I | re.M),
)
_SALARY_HINTS = (
    re.compile(r"^\s*salary\s*:\s*(?P<v>.+)$", re.I | re.M),
    re.compile(r"(?P<v>£[\d,]+(?:\s*[-–]\s*£?[\d,]+)?)", re.M),
)


class ManualEntryAdapter(BoardAdapter):
    """Operator pastes URL or text. No network access, ever."""

    def fetch(self, query: Query) -> list[RawVacancy]:
        raise TermsViolation(
            f"board {self.board_id!r} is Tier 3 (manual). Automated collection is "
            "prohibited by its terms. Use submit() with pasted text."
        )

    def submit(
        self,
        text: str,
        *,
        url: str = "",
        employer: str = "",
        title: str = "",
        location: str = "",
        salary_band: str = "",
    ) -> Vacancy:
        """Ingest a pasted vacancy. Explicit fields override anything parsed."""
        if not text or not text.strip():
            raise IngestionError("pasted vacancy text is empty")

        employer = employer or _first(text, _EMPLOYER_HINTS)
        title = title or _first(text, _TITLE_HINTS) or _first_heading(text)
        location = location or _first(text, _LOCATION_HINTS)
        salary_band = salary_band or _first(text, _SALARY_HINTS)

        if not title:
            raise IngestionError(
                "could not determine job title from pasted text — pass title= explicitly"
            )

        digest = hashlib.sha256(f"{url}|{title}|{employer}|{text[:400]}".encode()).hexdigest()[:16]

        return Vacancy(
            id=f"{self.board_id}:{digest}",
            board_id=self.board_id,
            employer=employer or "(not stated)",
            title=title,
            description=text.strip(),
            location=location,
            salary_band=salary_band,
            url=url,
            fetched_at=datetime.now(timezone.utc),
        )

    def normalise(self, raw: RawVacancy) -> Vacancy:
        payload = raw.payload
        return self.submit(
            payload.get("text", ""),
            url=payload.get("url", ""),
            employer=payload.get("employer", ""),
            title=payload.get("title", ""),
            location=payload.get("location", ""),
            salary_band=payload.get("salary_band", ""),
        )

    def health_check(self) -> AdapterStatus:
        return AdapterStatus(
            self.board_id, True,
            "manual adapter — no endpoint. Operator paste is the ingress.",
        )


def _first(text: str, patterns) -> str:
    for p in patterns:
        m = p.search(text)
        if m:
            return re.sub(r"\s+", " ", m.group("v")).strip()
    return ""


def _first_heading(text: str) -> str:
    """First non-empty line, if it reads like a title rather than prose."""
    for line in text.split("\n"):
        s = line.strip().lstrip("# ").strip()
        if 3 <= len(s) <= 90 and not s.endswith((".", ":", "!", "?")):
            return s
    return ""
