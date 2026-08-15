"""
Advert folder manifest.

A watched folder holding pasted job adverts, and a manifest binding each file
to its employer and vacancy URL.

## What this enforces, and what it cannot

Nothing here prevents a file being dragged into the folder. No such hook
exists without a filesystem driver or a resident watcher, and neither belongs
in this project.

What it does enforce: **a file with no valid manifest entry is never
ingested.** It is reported as a violation and skipped. The folder may be
polluted; the pipeline will not act on it.

## Structure

The manifest is keyed by filename, which is a sound primary key because a
directory cannot hold two files with the same name.

    adverts/
    ├── manifest.yaml
    ├── acme-ml-engineer.txt
    └── moj-data-engineer.txt

    manifest.yaml:
      acme-ml-engineer.txt:
        employer: Acme Analytics
        url: https://www.linkedin.com/jobs/view/1234567890/
        added_at: 2026-08-12T10:00:00+00:00

Employer and URL live in the manifest, not in the advert text — the operator
should not have to edit a pasted advert to record its provenance.

## Lifetime

An entry is valid only while its file exists. `reconcile()` removes entries
whose file has gone, so the manifest cannot accumulate references to files
that are no longer there.

Reconciliation is not destructive of adverts: it removes manifest ENTRIES, never
files. An advert present without an entry is reported, not deleted — deleting
the operator's data because a record is missing would be the wrong failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

__all__ = [
    "AdvertEntry",
    "AdvertManifest",
    "ValidationError",
    "Violation",
    "MANIFEST_NAME",
]

MANIFEST_NAME = "manifest.yaml"

#: Filenames that must not enter the manifest.
_UNSAFE_NAME = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_RESERVED = frozenset({
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
})
_ALLOWED_SUFFIXES = frozenset({".txt", ".md", ".html", ".htm"})

_URL = re.compile(r"^https?://[^\s<>\"']+\.[^\s<>\"']+$", re.I)

MIN_EMPLOYER_CHARS = 2
MAX_EMPLOYER_CHARS = 120


class ValidationError(ValueError):
    """A proposed entry does not satisfy the schema."""


@dataclass(frozen=True)
class Violation:
    """A file or entry that breaks a rule. Reported, never acted on."""

    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.rule} — {self.detail}"


@dataclass
class AdvertEntry:
    """One advert file and its provenance.

    `filename` is the primary key. A directory cannot hold two files with the
    same name, so uniqueness is guaranteed by the filesystem rather than by
    anything this module has to police.
    """

    filename: str
    employer: str
    url: str
    added_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    board: str = "linkedin"
    note: str = ""

    def __post_init__(self) -> None:
        validate_filename(self.filename)
        validate_employer(self.employer)
        validate_url(self.url)

    def as_dict(self) -> dict[str, str]:
        return {
            "employer": self.employer,
            "url": self.url,
            "added_at": self.added_at,
            "board": self.board,
            **({"note": self.note} if self.note else {}),
        }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def validate_filename(name: str) -> None:
    """The primary key. Must be a plain filename, safe, and a text format."""
    if not name or not name.strip():
        raise ValidationError("filename is empty")
    if name != name.strip():
        raise ValidationError(f"filename {name!r} has leading or trailing whitespace")
    if "/" in name or "\\" in name:
        raise ValidationError(
            f"filename {name!r} contains a path separator — entries are keyed by "
            "filename alone, not by path"
        )
    if _UNSAFE_NAME.search(name):
        raise ValidationError(f"filename {name!r} contains characters unsafe on Windows")
    if Path(name).stem.lower() in _RESERVED:
        raise ValidationError(f"filename {name!r} is a reserved device name on Windows")
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValidationError(
            f"filename {name!r} has suffix {suffix or '(none)'}; permitted: "
            f"{', '.join(sorted(_ALLOWED_SUFFIXES))}"
        )
    if suffix == ".txt" and name.lower().endswith(".txt.txt"):
        raise ValidationError(
            f"filename {name!r} ends in .txt.txt — Notepad appends an extension "
            "when the save type is not set to All Files"
        )


def validate_employer(employer: str) -> None:
    """Required. Parsing it from advert prose is unreliable, hence the field."""
    text = (employer or "").strip()
    if not text:
        raise ValidationError("employer is required")
    if len(text) < MIN_EMPLOYER_CHARS:
        raise ValidationError(f"employer {text!r} is too short")
    if len(text) > MAX_EMPLOYER_CHARS:
        raise ValidationError(f"employer is longer than {MAX_EMPLOYER_CHARS} characters")
    if text.lower() in ("unknown", "n/a", "na", "tbc", "-", "?"):
        raise ValidationError(
            f"employer {text!r} is a placeholder. Name the employer or omit the advert"
        )


def validate_url(url: str) -> None:
    """Required. Without it the advert cannot be found again from the record."""
    text = (url or "").strip()
    if not text:
        raise ValidationError("vacancy url is required")
    if not _URL.match(text):
        raise ValidationError(
            f"url {text!r} is not a valid http(s) address"
        )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class AdvertManifest:
    """The folder and its manifest, kept consistent with each other."""

    directory: Path

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)

    @property
    def path(self) -> Path:
        return self.directory / MANIFEST_NAME

    # -- storage -----------------------------------------------------------

    def load(self) -> dict[str, AdvertEntry]:
        """Read the manifest. Invalid entries are skipped, not raised on —
        `check()` reports them, so one bad row cannot block the whole folder."""
        import yaml

        if not self.path.is_file():
            return {}
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise ValidationError(f"manifest is not valid YAML: {exc}") from exc

        out: dict[str, AdvertEntry] = {}
        for filename, fields in (raw or {}).items():
            if not isinstance(fields, dict):
                continue
            try:
                out[filename] = AdvertEntry(
                    filename=filename,
                    employer=str(fields.get("employer", "")),
                    url=str(fields.get("url", "")),
                    added_at=str(fields.get("added_at", "")) or _now(),
                    board=str(fields.get("board", "linkedin")),
                    note=str(fields.get("note", "")),
                )
            except ValidationError:
                continue
        return out

    def save(self, entries: dict[str, AdvertEntry]) -> None:
        import yaml

        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {name: entry.as_dict() for name, entry in sorted(entries.items())}
        header = (
            "# Advert manifest. Keyed by filename — a directory cannot hold two\n"
            "# files with the same name, so the key is unique by construction.\n"
            "#\n"
            "# An entry is valid only while its file exists. `vanguard adverts\n"
            "# check` removes entries whose file has gone. It never deletes an\n"
            "# advert: a file without an entry is REPORTED, not removed.\n"
            "#\n"
            "# Managed by `vanguard adverts`. Hand edits are read, but the\n"
            "# schema is enforced on every load.\n\n"
        )
        self.path.write_text(header + yaml.safe_dump(payload, sort_keys=True,
                                                     allow_unicode=True),
                             encoding="utf-8")

    # -- operations --------------------------------------------------------

    def advert_files(self) -> list[Path]:
        """Every candidate advert in the folder. The manifest is not one."""
        if not self.directory.is_dir():
            return []
        return sorted(
            p for p in self.directory.iterdir()
            if p.is_file() and p.name != MANIFEST_NAME
            and p.suffix.lower() in _ALLOWED_SUFFIXES
        )

    def add(self, filename: str, employer: str, url: str, *,
            board: str = "linkedin", note: str = "") -> AdvertEntry:
        """Register a file. Raises unless the file exists and the schema holds."""
        entry = AdvertEntry(filename=filename, employer=employer, url=url,
                            board=board, note=note)
        if not (self.directory / filename).is_file():
            raise ValidationError(
                f"{filename!r} is not in {self.directory} — the entry would "
                "reference a file that does not exist"
            )
        entries = self.load()
        entries[filename] = entry
        self.save(entries)
        return entry

    def remove(self, filename: str) -> bool:
        entries = self.load()
        if filename not in entries:
            return False
        del entries[filename]
        self.save(entries)
        return True

    def reconcile(self) -> tuple[list[str], list[Violation]]:
        """Drop entries whose file has gone; report files with no entry.

        Returns (removed entry names, violations). Never deletes a file —
        removing the operator's data because a record is missing would be the
        wrong failure.
        """
        entries = self.load()
        present = {p.name for p in self.advert_files()}

        orphaned = [name for name in entries if name not in present]
        for name in orphaned:
            del entries[name]
        if orphaned:
            self.save(entries)

        violations = [
            Violation(name, "unregistered",
                      "present in the folder with no manifest entry — will not "
                      "be ingested. Register it with `vanguard adverts add`")
            for name in sorted(present - set(entries))
        ]
        return orphaned, violations

    def check(self) -> list[Violation]:
        """Every rule breach in the folder, without changing anything."""
        violations: list[Violation] = []

        if not self.directory.is_dir():
            return [Violation(str(self.directory), "missing",
                              "advert folder does not exist")]

        import yaml
        raw: dict = {}
        if self.path.is_file():
            try:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                return [Violation(MANIFEST_NAME, "unreadable", str(exc))]

        for filename, fields in (raw or {}).items():
            if not isinstance(fields, dict):
                violations.append(Violation(str(filename), "malformed",
                                            "entry is not a mapping"))
                continue
            for validator, value, rule in (
                (validate_filename, filename, "filename"),
                (validate_employer, fields.get("employer", ""), "employer"),
                (validate_url, fields.get("url", ""), "url"),
            ):
                try:
                    validator(str(value))
                except ValidationError as exc:
                    violations.append(Violation(str(filename), rule, str(exc)))

            if not (self.directory / str(filename)).is_file():
                violations.append(Violation(str(filename), "orphaned entry",
                                            "manifest entry with no file present"))

        registered = set(raw or {})
        for path in self.advert_files():
            if path.name not in registered:
                violations.append(Violation(
                    path.name, "unregistered",
                    "present in the folder with no manifest entry — will not be "
                    "ingested"))
            elif path.stat().st_size == 0:
                violations.append(Violation(path.name, "empty",
                                            "file has no content"))

        return violations

    def ingestible(self) -> Iterator[tuple[Path, AdvertEntry]]:
        """Files that satisfy every rule. Anything else is skipped."""
        entries = self.load()
        for path in self.advert_files():
            entry = entries.get(path.name)
            if entry is None or path.stat().st_size == 0:
                continue
            yield path, entry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
