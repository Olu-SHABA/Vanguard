"""
Diagnostics — why an advert produced what it did.

Three things are captured, per the operator's specification:

    1. WHY something was rejected      refusal reason, in the parser's terms
    2. WHAT was gathered per advert    headings found, blocks, terms extracted
    3. AUDIT of pipeline decisions     rank filter, hydration, expiry, scoring

The purpose is not troubleshooting alone. `classify_heading()` matches a fixed
phrase list, and on the first live run 14 of 31 adverts had headings it did not
recognise — so extraction refused and the vacancies went unscored. Nothing
recorded what those headings actually said.

Capturing them turns the largest open item (D-03) from invention into
measurement: the phrase list can be widened from the headings real adverts
use, rather than from headings I guessed at.

Every field here is an observation. Nothing is inferred, and an absent value
is recorded as absent rather than defaulted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Sequence

__all__ = [
    "Decision",
    "RefusalReason",
    "AdvertDiagnostic",
    "diagnose_advert",
]


class RefusalReason(str, Enum):
    """Why extraction produced nothing. Empty when it produced something."""

    NONE = ""
    NO_REQUIREMENT_HEADING = "no_requirement_heading"
    NO_HEADINGS_AT_ALL = "no_headings_at_all"
    EMPTY_REQUIREMENT_SECTION = "empty_requirement_section"
    NOT_HTML_NO_SECTIONS = "not_html_no_sections"

    @property
    def explanation(self) -> str:
        return {
            "": "",
            "no_requirement_heading": (
                "advert has headings, but none matched the requirement phrase "
                "list — widen classify_heading() or review manually"
            ),
            "no_headings_at_all": (
                "no heading structure found; the advert may be continuous prose"
            ),
            "empty_requirement_section": (
                "a requirement heading was recognised but carried no content"
            ),
            "not_html_no_sections": (
                "plain-text advert with no recognised section headings"
            ),
        }[self.value]


class Decision(str, Enum):
    """A point where the pipeline chose to keep, drop or degrade a vacancy."""

    INGESTED = "ingested"
    DROPPED_EXPIRED = "dropped_expired"
    DROPPED_DUPLICATE = "dropped_duplicate"
    DROPPED_BELOW_RANK_FLOOR = "dropped_below_rank_floor"
    HYDRATED = "hydrated"
    HYDRATION_FAILED = "hydration_failed"
    HYDRATION_NOT_ATTEMPTED = "hydration_not_attempted"
    SCORED = "scored"
    SCORE_UNRELIABLE = "score_unreliable"
    EXTRACTION_REFUSED = "extraction_refused"


@dataclass
class AdvertDiagnostic:
    """Everything observed while parsing one advert."""

    vacancy_id: str
    board_id: str = ""
    is_html: bool = False
    description_chars: int = 0
    partial: bool = False

    # what was gathered
    headings: list[str] = field(default_factory=list)
    heading_kinds: dict[str, str] = field(default_factory=dict)
    block_count: int = 0
    bullet_count: int = 0
    requirement_bullets: int = 0

    # why it produced what it did
    terms_extracted: int = 0
    refusal: RefusalReason = RefusalReason.NONE
    decisions: list[str] = field(default_factory=list)

    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def unrecognised_headings(self) -> list[str]:
        """Headings that classified as UNKNOWN. The input to widening the list."""
        return [h for h in self.headings if self.heading_kinds.get(h) == "unknown"]

    @property
    def recognised_requirement_headings(self) -> list[str]:
        return [h for h in self.headings if self.heading_kinds.get(h) == "requirement"]

    @property
    def refused(self) -> bool:
        return self.refusal is not RefusalReason.NONE

    def record(self, decision: Decision, note: str = "") -> None:
        self.decisions.append(f"{decision.value}:{note}" if note else decision.value)

    def as_row(self) -> tuple:
        return (
            self.vacancy_id, self.board_id, int(self.is_html),
            self.description_chars, int(self.partial),
            json.dumps(self.headings), json.dumps(self.heading_kinds),
            self.block_count, self.bullet_count, self.requirement_bullets,
            self.terms_extracted, self.refusal.value,
            json.dumps(self.decisions), self.recorded_at,
        )

    def summary(self) -> str:
        if self.refused:
            return (
                f"REFUSED ({self.refusal.value}) — {len(self.headings)} heading(s), "
                f"{self.bullet_count} bullet(s), none under a requirement heading"
            )
        return (
            f"{self.terms_extracted} term(s) from {self.requirement_bullets} "
            f"requirement bullet(s) across {self.block_count} block(s)"
        )


def diagnose_advert(
    vacancy_id: str,
    description: str,
    *,
    board_id: str = "",
    partial: bool = False,
    terms_extracted: int = 0,
    job_title: str = "",
) -> AdvertDiagnostic:
    """Observe how an advert parses. Never changes behaviour, only records it."""
    from vanguard.extract import looks_like_html
    from vanguard.structure import SectionKind, parse_advert

    diagnostic = AdvertDiagnostic(
        vacancy_id=vacancy_id,
        board_id=board_id,
        is_html=looks_like_html(description),
        description_chars=len(description or ""),
        partial=partial,
        terms_extracted=terms_extracted,
    )

    if not diagnostic.is_html:
        if terms_extracted == 0:
            diagnostic.refusal = RefusalReason.NOT_HTML_NO_SECTIONS
        return diagnostic

    structure = parse_advert(description, job_title=job_title)
    named = [b for b in structure.blocks if b.heading]

    diagnostic.block_count = len(structure.blocks)
    diagnostic.headings = [b.heading for b in named]
    diagnostic.heading_kinds = {b.heading: b.kind.value for b in named}
    diagnostic.bullet_count = sum(len(b.bullets) for b in structure.blocks)
    diagnostic.requirement_bullets = len(structure.requirement_bullets)

    if terms_extracted:
        return diagnostic

    if not named:
        diagnostic.refusal = RefusalReason.NO_HEADINGS_AT_ALL
    elif any(b.kind is SectionKind.REQUIREMENT for b in named):
        diagnostic.refusal = RefusalReason.EMPTY_REQUIREMENT_SECTION
    else:
        diagnostic.refusal = RefusalReason.NO_REQUIREMENT_HEADING

    diagnostic.record(Decision.EXTRACTION_REFUSED, diagnostic.refusal.value)
    return diagnostic
