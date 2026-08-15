"""Application archive — what was actually submitted."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanguard.archive import Archive, ArchiveError, safe_segment


@pytest.fixture
def archive(tmp_path: Path) -> Archive:
    return Archive(tmp_path / "Pipeline_Archive")


def write_one(archive: Archive, **overrides) -> object:
    defaults = dict(
        vacancy_id="reed:57092035",
        employer="Ministry of Justice",
        title="Senior Data Engineer",
        job_description="Person Specification\n- Python and SQL\n",
        cv_markdown="# CV\n\n## Experience\n",
    )
    return archive.write(**{**defaults, **overrides})


# --- folder naming --------------------------------------------------------

@pytest.mark.parametrize(
    "employer, expected",
    [
        ("Ministry of Justice", "Ministry_of_Justice"),
        ("Acme / Beta Ltd.", "Acme_Beta_Ltd"),
        ("A&O Shearman (UK) LLP", "A&O_Shearman_(UK)_LLP"),
        ("", "unknown"),
        ("   ", "unknown"),
    ],
)
def test_employer_names_are_made_safe(employer: str, expected: str) -> None:
    """Employer names carry slashes, commas and trailing stops. None may
    become a path traversal."""
    assert safe_segment(employer, fallback="unknown") == expected


def test_reserved_device_names_are_escaped() -> None:
    """CON, PRN, NUL and friends cannot be folder names on Windows."""
    assert safe_segment("CON") != "CON"
    assert safe_segment("PRN").startswith("PRN")


def test_two_applications_to_one_employer_do_not_collide(archive: Archive) -> None:
    """The directive's flat layout collides: two files, same timestamp prefix,
    no way to tell which application either belongs to."""
    first = write_one(archive, vacancy_id="reed:1")
    second = write_one(archive, vacancy_id="reed:2")
    assert first.directory != second.directory
    assert len(archive.applications()) == 2


# --- what is written ------------------------------------------------------

def test_job_description_is_required(archive: Archive) -> None:
    """The one thing the record cannot be reconstructed without."""
    with pytest.raises(ArchiveError, match="no job description"):
        write_one(archive, job_description="")


def test_job_description_and_cv_are_written(archive: Archive) -> None:
    record = write_one(archive)
    assert "job_specs" in record.files and "cv_markdown" in record.files
    assert record.complete


def test_missing_cover_letter_is_not_an_error(archive: Archive) -> None:
    """Not every submission has one."""
    record = write_one(archive)
    assert "cover_letter_pdf" not in record.files
    assert record.complete


def test_pdf_is_copied_when_present(archive: Archive, tmp_path: Path) -> None:
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    record = write_one(archive, cv_pdf=pdf)
    assert record.files["cv_pdf"].read_bytes() == b"%PDF-1.4 fake"


def test_answers_are_archived(archive: Archive) -> None:
    record = write_one(archive, answers={"notice period": "1 month"})
    stored = json.loads(record.files["answers"].read_text(encoding="utf-8"))
    assert stored["notice period"] == "1 month"


def test_manifest_records_the_score(archive: Archive) -> None:
    """An interview six weeks later asks what was claimed. The manifest says."""
    record = write_one(archive, metadata={"coverage": 0.7, "reference": "19568"})
    manifest = json.loads((record.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["coverage"] == 0.7
    assert manifest["reference"] == "19568"
    assert manifest["vacancy_id"] == "reed:57092035"


def test_incomplete_without_a_cv(archive: Archive) -> None:
    record = write_one(archive, cv_markdown="")
    assert not record.complete


# --- reading back ---------------------------------------------------------

def test_applications_are_listed_newest_first(archive: Archive) -> None:
    write_one(archive, vacancy_id="reed:1",
              when=datetime(2026, 8, 1, tzinfo=timezone.utc))
    write_one(archive, vacancy_id="reed:2",
              when=datetime(2026, 8, 10, tzinfo=timezone.utc))
    listed = archive.applications()
    assert len(listed) == 2


def test_lookup_by_vacancy(archive: Archive) -> None:
    write_one(archive, vacancy_id="reed:1")
    write_one(archive, vacancy_id="reed:2")
    assert len(archive.for_vacancy("reed:1")) == 1


def test_empty_archive_reads_cleanly(tmp_path: Path) -> None:
    assert Archive(tmp_path / "absent").applications() == []


# --- correspondence -------------------------------------------------------

def test_messages_are_filed_with_the_application(archive: Archive) -> None:
    """Acknowledgements and rejections belong with the application they
    concern, not in a mailbox."""
    record = write_one(archive)
    path = archive.add_message("reed:57092035", "Thank you for applying.",
                               subject="Application received",
                               sender="hr@justice.gov.uk", kind="acknowledgement")
    assert path is not None and path.parent == record.directory
    text = path.read_text(encoding="utf-8")
    assert "hr@justice.gov.uk" in text and "Thank you for applying" in text


def test_message_for_unknown_vacancy_is_dropped(archive: Archive) -> None:
    assert archive.add_message("reed:nothere", "body") is None
