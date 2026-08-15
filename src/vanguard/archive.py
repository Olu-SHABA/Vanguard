"""
Application archive — Route 4 persistence.

Directive §5. On dispatch, the exact artefacts submitted are written to disk so
the application can be reconstructed months later.

    /Pipeline_Archive/
    └── Ministry_of_Justice/
        └── 20260812T1015_reed-57092035/
            ├── 20260812T1015_Job_Specs.txt
            ├── 20260812T1015_Optimized_CV.md
            ├── 20260812T1015_Optimized_CV.pdf
            ├── 20260812T1015_Cover_Letter.pdf
            ├── 20260812T1015_Answers.json
            └── manifest.json

**Written at dispatch, not at approval.** The directive says "upon approval",
but approval means eligible for dispatch — not submitted. Archiving there
would create folders for applications never sent, and the archive would stop
being a record of what was submitted.

**A per-vacancy subfolder, not a flat employer folder.** The directive's layout
collides when the same employer is applied to twice: two files with the same
timestamp prefix and no way to tell which application either belongs to.

## Why it matters

An interview happens six weeks after dispatch. The advert has been taken down,
the CV has been edited since, and the panel is asking about a bullet. Without
this, there is no way to know what was actually sent.

The archive is also the only place the submitted CV and the job description sit
together, which is what makes a claim traceable after the fact.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "ArchiveError",
    "ArchivedApplication",
    "Archive",
    "ARCHIVE_ROOT",
]

ARCHIVE_ROOT = Path("Pipeline_Archive")

_UNSAFE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_WS = re.compile(r"\s+")
_RESERVED = frozenset({
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
})
MAX_SEGMENT = 60


class ArchiveError(RuntimeError):
    """The application could not be archived."""


def safe_segment(text: str, *, fallback: str = "unknown") -> str:
    """A folder name that is safe on Windows and readable by a human.

    Employer names carry commas, slashes, ampersands and trailing 'Ltd.' —
    'A&O Shearman (UK) LLP' must not become a path traversal or a reserved
    device name.
    """
    cleaned = _WS.sub(" ", _UNSAFE.sub(" ", str(text or ""))).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned:
        return fallback
    cleaned = _WS.sub("_", cleaned)[:MAX_SEGMENT].rstrip("_.")
    if cleaned.lower() in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned or fallback


def _stamp(when: datetime | None = None) -> str:
    return (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M")


@dataclass
class ArchivedApplication:
    """What was written, and where."""

    vacancy_id: str
    employer: str
    title: str
    directory: Path
    files: dict[str, Path] = field(default_factory=dict)
    archived_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def complete(self) -> bool:
        """The job description and the CV are the minimum useful record."""
        return "job_specs" in self.files and any(
            k.startswith("cv") for k in self.files
        )

    def summary(self) -> str:
        return f"{len(self.files)} file(s) in {self.directory}"


@dataclass
class Archive:
    """Writes and reads the application archive."""

    root: Path = ARCHIVE_ROOT

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    def folder_for(self, employer: str, vacancy_id: str,
                   when: datetime | None = None) -> Path:
        """`<root>/<Employer>/<stamp>_<vacancy-id>/`.

        The vacancy id is in the leaf so a second application to the same
        employer cannot overwrite the first.
        """
        leaf = f"{_stamp(when)}_{safe_segment(vacancy_id, fallback='vacancy')}"
        return self.root / safe_segment(employer, fallback="unknown_employer") / leaf

    # -- writing -----------------------------------------------------------

    def write(
        self,
        *,
        vacancy_id: str,
        employer: str,
        title: str,
        job_description: str,
        cv_markdown: str = "",
        cv_pdf: Path | None = None,
        cover_letter: Path | None = None,
        cover_letter_text: str = "",
        answers: dict | None = None,
        metadata: dict | None = None,
        when: datetime | None = None,
    ) -> ArchivedApplication:
        """Write one application. Raises only if nothing could be written.

        A missing cover letter or PDF is normal — not every submission has
        one. A missing job description is not: without it the archive cannot
        show what was applied for.
        """
        if not (job_description or "").strip():
            raise ArchiveError(
                f"{vacancy_id}: no job description to archive. The advert text "
                "is the one thing this record cannot be reconstructed without"
            )

        directory = self.folder_for(employer, vacancy_id, when)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArchiveError(f"could not create {directory}: {exc}") from exc

        stamp = _stamp(when)
        written: dict[str, Path] = {}

        def _text(name: str, key: str, content: str) -> None:
            if not content.strip():
                return
            path = directory / f"{stamp}_{name}"
            try:
                path.write_text(content, encoding="utf-8")
                written[key] = path
            except OSError:
                pass

        def _copy(name: str, key: str, source: Path | None) -> None:
            if source is None or not Path(source).is_file():
                return
            path = directory / f"{stamp}_{name}"
            try:
                shutil.copy2(source, path)
                written[key] = path
            except OSError:
                pass

        _text("Job_Specs.txt", "job_specs", job_description)
        _text("Optimized_CV.md", "cv_markdown", cv_markdown)
        _copy("Optimized_CV.pdf", "cv_pdf", cv_pdf)
        _copy("Cover_Letter.pdf", "cover_letter_pdf", cover_letter)
        _text("Cover_Letter.txt", "cover_letter_text", cover_letter_text)

        if answers:
            _text("Answers.json", "answers", json.dumps(answers, indent=2))

        record = ArchivedApplication(
            vacancy_id=vacancy_id, employer=employer, title=title,
            directory=directory, files=written,
        )

        manifest = {
            "vacancy_id": vacancy_id,
            "employer": employer,
            "title": title,
            "archived_at": record.archived_at,
            "files": {k: p.name for k, p in written.items()},
            **(metadata or {}),
        }
        try:
            (directory / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8")
        except OSError:
            pass

        return record

    # -- reading -----------------------------------------------------------

    def applications(self) -> list[ArchivedApplication]:
        """Every archived application, newest first."""
        if not self.root.is_dir():
            return []

        out: list[ArchivedApplication] = []
        for manifest_path in self.root.glob("*/*/manifest.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            directory = manifest_path.parent
            out.append(ArchivedApplication(
                vacancy_id=data.get("vacancy_id", ""),
                employer=data.get("employer", ""),
                title=data.get("title", ""),
                directory=directory,
                files={k: directory / v for k, v in (data.get("files") or {}).items()},
                archived_at=data.get("archived_at", ""),
            ))
        return sorted(out, key=lambda a: a.archived_at, reverse=True)

    def for_vacancy(self, vacancy_id: str) -> list[ArchivedApplication]:
        return [a for a in self.applications() if a.vacancy_id == vacancy_id]

    def add_message(self, vacancy_id: str, body: str, *,
                    subject: str = "", sender: str = "",
                    kind: str = "message") -> Path | None:
        """Append correspondence to the most recent archive for a vacancy.

        Acknowledgements, interview invitations and rejections belong with the
        application they concern, not in a mailbox.
        """
        applications = self.for_vacancy(vacancy_id)
        if not applications:
            return None

        directory = applications[0].directory
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = directory / f"{stamp}_{safe_segment(kind, fallback='message')}.txt"
        header = f"From: {sender}\nSubject: {subject}\nReceived: {stamp}\n\n"
        try:
            path.write_text(header + body, encoding="utf-8")
            return path
        except OSError:
            return None
