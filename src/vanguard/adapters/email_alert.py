"""
Email alert adapter — Tier 2, generic.

Serves any board that publishes alert emails but no jobseeker API: Civil
Service Jobs, Totaljobs, CV-Library, Monster UK.

Civil Service Jobs is the case that motivated it. There is no public API; the
portal serves a bot-detection interstitial and sets meta-robots noindex, so
automated collection is explicitly discouraged. Alert emails are the sanctioned
route — the operator configures a saved search once, and the publisher pushes
matches to a monitored mailbox.

Two constraints, both enforced here:

  * `portal_url` is operator-facing. It is used to configure the saved search
    and for manual paste. It is NEVER fetched by the pipeline.
  * Vacancy links inside an alert point at public advert pages. Content behind
    authentication is never fetched.

Parsing is offline: this adapter consumes message bodies handed to it. Mailbox
connection is M6's concern, and the same monitored mailbox carries both alert
emails and recruiter responses.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable

from vanguard.adapters.base import (
    AdapterStatus,
    BoardAdapter,
    IngestionError,
    Query,
    RawVacancy,
    TermsViolation,
    Vacancy,
)

__all__ = ["EmailAlertAdapter", "AlertItem"]

_URL = re.compile(r"https?://[^\s<>\"')]+")
_HTML_TAG = re.compile(r"<[^>]+>")
_ENTITY = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ", "&#39;": "'", "&quot;": '"'}

# "Senior Data Engineer - Ministry of Justice - London"
_TITLE_EMPLOYER = re.compile(
    r"^(?P<title>[^|\n]{6,90}?)\s+[-–|]\s+(?P<employer>[^|\n]{2,60}?)"
    r"(?:\s+[-–|]\s+(?P<location>[^|\n]{2,50}))?\s*$"
)
_SALARY = re.compile(r"£[\d,]+(?:\s*[-–]\s*£?[\d,]+)?(?:\s*per\s+\w+)?", re.I)


class AlertItem:
    """One vacancy extracted from an alert email body."""

    __slots__ = ("title", "employer", "location", "salary_band", "url", "snippet")

    def __init__(self, title: str, employer: str = "", location: str = "",
                 salary_band: str = "", url: str = "", snippet: str = "") -> None:
        self.title = title
        self.employer = employer
        self.location = location
        self.salary_band = salary_band
        self.url = url
        self.snippet = snippet

    def __repr__(self) -> str:
        return f"AlertItem({self.title!r}, {self.employer!r})"


class EmailAlertAdapter(BoardAdapter):
    """Consumes publisher alert emails. Never fetches the portal."""

    def fetch(self, query: Query) -> list[RawVacancy]:
        raise TermsViolation(
            f"board {self.board_id!r} is Tier 2 (feed) via email alert. The portal is "
            "never fetched by the pipeline. Use ingest_message() with an alert body."
        )

    # -- ingestion ---------------------------------------------------------

    def ingest_message(self, body: str, *, sender: str = "", subject: str = "") -> list[RawVacancy]:
        """Parse one alert email into raw vacancy records."""
        if not body or not body.strip():
            raise IngestionError("alert message body is empty")

        expected = self.entry.ingress.get("sender", "")
        if expected and sender and not _sender_matches(sender, expected):
            raise IngestionError(
                f"{self.board_id}: message from {sender!r} does not match configured "
                f"sender pattern {expected!r} — refusing to ingest"
            )

        return [
            RawVacancy(self.board_id, {
                "title": item.title,
                "employer": item.employer,
                "location": item.location,
                "salary_band": item.salary_band,
                "url": item.url,
                "snippet": item.snippet,
                "subject": subject,
            })
            for item in parse_alert(body)
        ]

    def normalise(self, raw: RawVacancy) -> Vacancy:
        p = raw.payload
        title = p.get("title", "")
        snippet = p.get("snippet", "") or title

        digest = hashlib.sha256(
            f"{p.get('url','')}|{title}|{p.get('employer','')}".encode()
        ).hexdigest()[:16]

        return Vacancy(
            id=f"{self.board_id}:{digest}",
            board_id=self.board_id,
            employer=p.get("employer", "") or "(not stated)",
            title=title,
            description=snippet,
            location=p.get("location", ""),
            salary_band=p.get("salary_band", ""),
            url=p.get("url", ""),
            fetched_at=raw.fetched_at,
        )

    def health_check(self) -> AdapterStatus:
        folder = self.entry.ingress.get("mailbox_folder", "")
        sender = self.entry.ingress.get("sender", "")
        if not folder or not sender:
            return AdapterStatus(
                self.board_id, False,
                "ingress incomplete: mailbox_folder and sender must both be configured",
            )
        return AdapterStatus(
            self.board_id, True,
            f"alert ingress configured: {folder} from {sender}. Portal never fetched.",
        )


# ---------------------------------------------------------------------------

def parse_alert(body: str) -> list[AlertItem]:
    """Extract vacancy items from an alert email body.

    Handles plain text and simple HTML. Deliberately tolerant: alert formats
    vary between publishers and change without notice, so a partially parsed
    item is better than a dropped one. A vacancy with a URL but no clean title
    still reaches the review queue.
    """
    text = _strip_html(body)
    lines = [ln.strip() for ln in text.split("\n")]

    items: list[AlertItem] = []
    pending: AlertItem | None = None

    for line in lines:
        if not line:
            continue

        url_match = _URL.search(line)
        if url_match and pending is not None and not pending.url:
            pending.url = url_match.group(0)
            continue

        m = _TITLE_EMPLOYER.match(line)
        if m and not _is_boilerplate(line) and not _is_metadata_line(line):
            if pending is not None:
                items.append(pending)
            salary = _SALARY.search(line)
            pending = AlertItem(
                title=m.group("title").strip(),
                employer=(m.group("employer") or "").strip(),
                location=(m.group("location") or "").strip(),
                salary_band=salary.group(0) if salary else "",
                url=url_match.group(0) if url_match else "",
                snippet=line,
            )
            continue

        if pending is not None:
            if not pending.salary_band:
                salary = _SALARY.search(line)
                if salary:
                    pending.salary_band = salary.group(0)
            if len(pending.snippet) < 600:
                pending.snippet = f"{pending.snippet}\n{line}"

    if pending is not None:
        items.append(pending)

    return [i for i in items if i.title]


_BOILERPLATE = (
    "unsubscribe", "view in browser", "privacy policy", "manage your alerts",
    "you are receiving", "do not reply", "terms and conditions",
)


def _is_boilerplate(line: str) -> bool:
    low = line.lower()
    return any(b in low for b in _BOILERPLATE)


def _is_metadata_line(line: str) -> bool:
    """Reject lines that are a salary, date or reference rather than a title.

    '£42,914 - £53,081 per annum' matches the title-employer pattern because it
    carries a dash separator. Salary belongs to the vacancy above it, not to a
    new one.
    """
    stripped = line.strip()
    if stripped.startswith(("£", "$", "€")):
        return True
    salary = _SALARY.search(stripped)
    if salary and len(salary.group(0)) > len(stripped) * 0.5:
        return True
    if re.match(r"^(?:closing date|posted|reference|vacancy (?:no|number)|grade|salary)\b",
                stripped, re.I):
        return True
    return False


def _strip_html(body: str) -> str:
    if "<" not in body:
        return body
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", body, flags=re.I)
    text = _HTML_TAG.sub(" ", text)
    for entity, char in _ENTITY.items():
        text = text.replace(entity, char)
    return re.sub(r"[ \t]{2,}", " ", text)


def _sender_matches(sender: str, pattern: str) -> bool:
    """Glob match on the sender domain. '*.example.gov.uk' style."""
    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    return re.search(regex, sender, re.I) is not None
