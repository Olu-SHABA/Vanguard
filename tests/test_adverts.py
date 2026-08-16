"""Advert folder — schema, reconciliation, batch ingestion."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.adverts import (
    MANIFEST_NAME,
    AdvertEntry,
    AdvertManifest,
    ValidationError,
    validate_employer,
    validate_filename,
    validate_url,
)


@pytest.fixture
def folder(tmp_path: Path) -> AdvertManifest:
    directory = tmp_path / "adverts"
    directory.mkdir()
    return AdvertManifest(directory)


def place(folder: AdvertManifest, name: str, content: str = "Requirements\n- Python\n") -> Path:
    path = folder.directory / name
    path.write_text(content, encoding="utf-8")
    return path


# --- what makes an entry valid --------------------------------------------

def test_a_valid_entry_needs_filename_employer_and_url(folder) -> None:
    place(folder, "job.txt")
    entry = folder.add("job.txt", "Acme Analytics", "https://example.com/job")
    assert entry.employer == "Acme Analytics"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "sub/job.txt", "sub\\job.txt", "job.pdf", "job.docx",
     "job.txt.txt", "CON.txt", "job<1>.txt"],
)
def test_invalid_filenames_are_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_filename(name)


@pytest.mark.parametrize("employer", ["", "  ", "x", "unknown", "N/A", "TBC", "-", "?"])
def test_placeholder_employers_are_refused(employer: str) -> None:
    """If the employer is unknown, the advert should not be in the folder."""
    with pytest.raises(ValidationError):
        validate_employer(employer)


@pytest.mark.parametrize("url", ["", "not-a-url", "ftp://x.com", "example.com",
                                 "javascript:alert(1)"])
def test_invalid_urls_are_refused(url: str) -> None:
    """Without a URL the advert cannot be found again from the record."""
    with pytest.raises(ValidationError):
        validate_url(url)


def test_double_extension_is_caught() -> None:
    """Notepad appends .txt when the save type is not set to All Files."""
    with pytest.raises(ValidationError, match="txt.txt"):
        validate_filename("advert.txt.txt")


def test_entry_for_an_absent_file_is_refused(folder) -> None:
    with pytest.raises(ValidationError, match="not in"):
        folder.add("nothere.txt", "Acme", "https://example.com/job")


# --- the filename is the primary key --------------------------------------

def test_filename_is_the_key(folder) -> None:
    """Sound, because a directory cannot hold two files with the same name."""
    place(folder, "job.txt")
    folder.add("job.txt", "First", "https://example.com/1")
    folder.add("job.txt", "Second", "https://example.com/2")
    entries = folder.load()
    assert len(entries) == 1 and entries["job.txt"].employer == "Second"


# --- lifetime -------------------------------------------------------------

def test_entry_dies_with_its_file(folder) -> None:
    """The reference is valid only while the file is in the folder."""
    path = place(folder, "job.txt")
    folder.add("job.txt", "Acme", "https://example.com/job")
    path.unlink()

    removed, _ = folder.reconcile()
    assert removed == ["job.txt"]
    assert folder.load() == {}


def test_reconcile_never_deletes_an_advert(folder) -> None:
    """Removing the operator's data because a record is missing would be the
    wrong failure."""
    place(folder, "unregistered.txt")
    folder.reconcile()
    assert (folder.directory / "unregistered.txt").is_file()


def test_unregistered_file_is_reported(folder) -> None:
    place(folder, "stray.txt")
    _, violations = folder.reconcile()
    assert any(v.subject == "stray.txt" and v.rule == "unregistered"
               for v in violations)


# --- enforcement at ingest ------------------------------------------------

def test_only_registered_files_are_ingestible(folder) -> None:
    """Nothing can stop a file being dragged in. What is enforced is that an
    unregistered file is never ingested."""
    place(folder, "registered.txt")
    place(folder, "dragged_in.txt")
    folder.add("registered.txt", "Acme", "https://example.com/job")

    names = [path.name for path, _ in folder.ingestible()]
    assert names == ["registered.txt"]


def test_empty_file_is_not_ingestible(folder) -> None:
    place(folder, "empty.txt", content="")
    folder.add.__wrapped__ if False else None
    # Registering an empty file is permitted; ingesting it is not.
    (folder.directory / "empty.txt").write_text("x", encoding="utf-8")
    folder.add("empty.txt", "Acme", "https://example.com/job")
    (folder.directory / "empty.txt").write_text("", encoding="utf-8")
    assert list(folder.ingestible()) == []


def test_the_manifest_is_not_an_advert(folder) -> None:
    place(folder, "job.txt")
    folder.add("job.txt", "Acme", "https://example.com/job")
    assert MANIFEST_NAME not in [p.name for p in folder.advert_files()]


# --- check ----------------------------------------------------------------

def test_check_reports_without_changing_anything(folder) -> None:
    path = place(folder, "job.txt")
    folder.add("job.txt", "Acme", "https://example.com/job")
    path.unlink()

    violations = folder.check()
    assert any(v.rule == "orphaned entry" for v in violations)
    assert "job.txt" in folder.load(), "check must not mutate"


def test_check_on_a_clean_folder_is_silent(folder) -> None:
    place(folder, "job.txt")
    folder.add("job.txt", "Acme", "https://example.com/job")
    assert folder.check() == []


def test_malformed_manifest_is_reported_not_fatal(folder) -> None:
    (folder.directory / MANIFEST_NAME).write_text("not: [valid: yaml",
                                                  encoding="utf-8")
    assert folder.check()


def test_one_bad_entry_does_not_block_the_folder(folder) -> None:
    """A single malformed row must not stop every other advert ingesting."""
    place(folder, "good.txt")
    folder.add("good.txt", "Acme", "https://example.com/job")
    manifest = folder.path.read_text(encoding="utf-8")
    folder.path.write_text(manifest + "\nbad.txt:\n  employer: ''\n  url: nope\n",
                           encoding="utf-8")

    assert [p.name for p, _ in folder.ingestible()] == ["good.txt"]


# ---------------------------------------------------------------------------
# The template must not destroy work in progress
# ---------------------------------------------------------------------------

def test_filled_template_is_not_overwritten(tmp_path: Path) -> None:
    """Filling in seventy rows and re-running --template would blank the lot,
    and the loss is invisible until the columns are noticed empty."""
    from vanguard.cli import _filled_rows

    path = tmp_path / "to_register.csv"
    path.write_text("filename,employer,url,board\n"
                    "job.txt,Acme,https://example.com/1,linkedin\n",
                    encoding="utf-8")
    assert _filled_rows(path) == 1


def test_blank_template_is_disposable(tmp_path: Path) -> None:
    from vanguard.cli import _filled_rows

    path = tmp_path / "to_register.csv"
    path.write_text("filename,employer,url,board\njob.txt,,,linkedin\n",
                    encoding="utf-8")
    assert _filled_rows(path) == 0


def test_unreadable_template_counts_as_empty(tmp_path: Path) -> None:
    from vanguard.cli import _filled_rows

    assert _filled_rows(tmp_path / "absent.csv") == 0
