"""
Canonical CV loader, editor and serialiser.

`canonical_cv.md` is the single source of truth for all employment history,
metrics and dated claims. This module parses it into an addressable structure,
applies bounded edits, and writes it back.

Round-trip fidelity is a hard requirement:

    to_markdown(load(path)) == path.read_text()

Without it the per-vacancy diff in /Pipeline_Archive/ is meaningless, and the
refactoring record in Template A cannot be verified. `test_cv.py` asserts it
against the real document.

Every edit carries the source role it was justified by. An edit without one is
invalid and cannot be persisted — enforced here rather than by convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterator

__all__ = [
    "CVSection",
    "CanonicalCV",
    "Edit",
    "CVError",
    "EditError",
    "load",
    "to_markdown",
]


class CVError(RuntimeError):
    """The canonical CV could not be parsed or serialised."""


class EditError(ValueError):
    """An edit was rejected. Carries why."""


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

_H2 = re.compile(r"^## +(?P<title>.+?)\s*$")
_H3 = re.compile(r"^### +(?P<title>.+?)\s*$")
_BULLET = re.compile(r"^- +(?P<text>.+?)\s*$")
# "**Employer — Location** | Sept 2018 – Sept 2024"
_ROLE_META = re.compile(r"^\*\*(?P<employer>.+?)\*\*\s*\|\s*(?P<dates>.+?)\s*$")


@dataclass
class CVSection:
    """One addressable block of the CV.

    `level` 2 is a top-level section (PROFESSIONAL EXPERIENCE); level 3 is a
    role or project within it. `raw` preserves every line verbatim, which is
    what makes round-tripping exact — bullets are a parsed *view* over it.
    """

    level: int
    title: str
    raw: list[str] = field(default_factory=list)
    parent: str | None = None

    @property
    def id(self) -> str:
        """Stable address, e.g. 'PROFESSIONAL EXPERIENCE/NOC Engineer'."""
        return f"{self.parent}/{self.title}" if self.parent else self.title

    @property
    def employer(self) -> str | None:
        for line in self.raw:
            m = _ROLE_META.match(line.strip())
            if m:
                return m.group("employer").strip()
        return None

    @property
    def dates(self) -> str | None:
        for line in self.raw:
            m = _ROLE_META.match(line.strip())
            if m:
                return m.group("dates").strip()
        return None

    @property
    def source_role(self) -> str:
        """Citation string for the refactoring record."""
        if self.employer and self.dates:
            return f"{self.title} — {self.employer}, {self.dates}"
        return self.title

    @property
    def bullets(self) -> list[str]:
        return [m.group("text") for line in self.raw if (m := _BULLET.match(line))]

    def text(self) -> str:
        return "\n".join(self.raw)


@dataclass
class Edit:
    """A single recorded change. `source_role` is mandatory and non-empty."""

    section_id: str
    before: str
    after: str
    source_role: str
    gap_type: int

    def __post_init__(self) -> None:
        if not self.source_role or not self.source_role.strip():
            raise EditError("edit without a source role citation is invalid")
        if self.gap_type not in (1, 2):
            raise EditError(f"only Type 1 and Type 2 edits are permitted, got {self.gap_type}")
        if self.before == self.after:
            raise EditError("edit is a no-op")


@dataclass
class CanonicalCV:
    """Parsed CV. Immutable in spirit — `apply` returns a new instance."""

    preamble: list[str]
    sections: list[CVSection]
    edits: tuple[Edit, ...] = ()

    # -- access ------------------------------------------------------------

    def __iter__(self) -> Iterator[CVSection]:
        return iter(self.sections)

    def section(self, section_id: str) -> CVSection:
        for s in self.sections:
            if s.id == section_id:
                return s
        raise KeyError(f"no such section: {section_id}")

    def roles(self) -> list[CVSection]:
        """Level-3 sections under PROFESSIONAL EXPERIENCE."""
        return [s for s in self.sections if s.level == 3 and s.parent == "PROFESSIONAL EXPERIENCE"]

    def projects(self) -> list[CVSection]:
        return [s for s in self.sections if s.level == 3 and s.parent == "PROJECTS"]

    def full_text(self) -> str:
        """Everything, for term matching. Includes preamble and all sections."""
        return "\n".join(self.preamble + [s.text() for s in self.sections])

    def all_bullets(self) -> list[tuple[CVSection, str]]:
        return [(s, b) for s in self.sections for b in s.bullets]

    # -- mutation ----------------------------------------------------------

    def apply(self, edit: Edit) -> CanonicalCV:
        """Return a new CV with `edit` applied. Raises if it does not match.

        Type 3 gaps never reach here — `Edit.__post_init__` rejects them.
        """
        target = self.section(edit.section_id)
        if edit.before not in target.text():
            raise EditError(
                f"`before` text not found in {edit.section_id!r}; "
                "the CV may have changed since the edit was proposed"
            )

        new_sections = []
        for s in self.sections:
            if s.id == edit.section_id:
                joined = s.text().replace(edit.before, edit.after, 1)
                new_sections.append(replace(s, raw=joined.split("\n")))
            else:
                new_sections.append(s)

        return CanonicalCV(self.preamble, new_sections, self.edits + (edit,))

    def diff_summary(self) -> list[str]:
        return [
            f"[Type {e.gap_type}] {e.section_id} :: {e.source_role}\n"
            f"  - {e.before}\n  + {e.after}"
            for e in self.edits
        ]


# ---------------------------------------------------------------------------
# Parse / serialise
# ---------------------------------------------------------------------------

def load(path: Path | str) -> CanonicalCV:
    """Parse `canonical_cv.md`. Raises CVError on anything unreadable."""
    path = Path(path)
    if not path.is_file():
        raise CVError(f"canonical CV not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CVError(f"could not read {path}: {exc}") from exc
    return parse(text)


def parse(text: str) -> CanonicalCV:
    """Split Markdown into sections, preserving every line verbatim."""
    lines = text.split("\n")
    preamble: list[str] = []
    sections: list[CVSection] = []
    current: CVSection | None = None
    parent: str | None = None

    for line in lines:
        h2, h3 = _H2.match(line), _H3.match(line)
        if h2:
            current = CVSection(2, h2.group("title").strip(), [line])
            parent = current.title
            sections.append(current)
        elif h3:
            current = CVSection(3, h3.group("title").strip(), [line], parent=parent)
            sections.append(current)
        elif current is None:
            preamble.append(line)
        else:
            current.raw.append(line)

    if not sections:
        raise CVError("no '## ' sections found — is this a canonical CV?")

    return CanonicalCV(preamble, sections)


def to_markdown(cv: CanonicalCV) -> str:
    """Serialise back to Markdown. Must round-trip exactly."""
    parts = list(cv.preamble)
    for s in cv.sections:
        parts.extend(s.raw)
    return "\n".join(parts)


def save(cv: CanonicalCV, path: Path | str) -> Path:
    """Write a derived CV. Never call this on the canonical path."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(to_markdown(cv), encoding="utf-8")
    except OSError as exc:
        raise CVError(f"could not write {path}: {exc}") from exc
    return path
