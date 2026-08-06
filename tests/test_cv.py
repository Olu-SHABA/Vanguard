"""Canonical CV loader — round-trip fidelity and edit guards."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.cv import CVError, Edit, EditError, load, parse, save, to_markdown

CV_PATH = Path(__file__).parent.parent / "data" / "canonical_cv.md"


@pytest.fixture
def cv():
    return load(CV_PATH)


# --- the hard requirement -------------------------------------------------

def test_round_trip_is_exact(cv) -> None:
    """to_markdown(load(p)) == p.read_text(). The diff artefact depends on it."""
    assert to_markdown(cv) == CV_PATH.read_text(encoding="utf-8")


def test_round_trip_survives_an_edit(cv) -> None:
    role = cv.roles()[0]
    edited = cv.apply(Edit(role.id, role.bullets[0], "Replacement bullet.", role.source_role, 1))
    assert "Replacement bullet." in to_markdown(edited)
    assert to_markdown(edited).count("\n### ") == to_markdown(cv).count("\n### ")


# --- structure ------------------------------------------------------------

def test_all_roles_parsed(cv) -> None:
    assert len(cv.roles()) == 7


def test_every_bullet_captured(cv) -> None:
    assert len(cv.all_bullets()) == 38


def test_role_carries_employer_and_dates(cv) -> None:
    role = cv.section("PROFESSIONAL EXPERIENCE/NOC Engineer")
    assert role.employer and "Avanti" in role.employer
    assert role.dates == "October 2024 – July 2025"


def test_source_role_citation_is_complete(cv) -> None:
    for role in cv.roles():
        citation = role.source_role
        assert role.title in citation and "," in citation


def test_projects_are_separate_from_roles(cv) -> None:
    assert len(cv.projects()) == 1
    assert cv.projects()[0].id.startswith("PROJECTS/")


def test_unknown_section_raises(cv) -> None:
    with pytest.raises(KeyError):
        cv.section("PROFESSIONAL EXPERIENCE/Astronaut")


# --- edit guards ----------------------------------------------------------

def test_edit_without_source_role_rejected() -> None:
    with pytest.raises(EditError, match="source role"):
        Edit("s", "a", "b", "", 1)


def test_edit_with_blank_source_role_rejected() -> None:
    with pytest.raises(EditError, match="source role"):
        Edit("s", "a", "b", "   ", 1)


@pytest.mark.parametrize("gap_type", [0, 3, 4])
def test_only_type_1_and_2_edits_permitted(gap_type: int) -> None:
    """Type 3 gaps permit no CV edit. Enforced at the data layer."""
    with pytest.raises(EditError, match="Type 1 and Type 2"):
        Edit("s", "a", "b", "MTN, 2018-2024", gap_type)


def test_no_op_edit_rejected() -> None:
    with pytest.raises(EditError, match="no-op"):
        Edit("s", "same", "same", "MTN", 1)


def test_edit_on_stale_text_rejected(cv) -> None:
    role = cv.roles()[0]
    with pytest.raises(EditError, match="not found"):
        cv.apply(Edit(role.id, "text that is not in the CV", "x", role.source_role, 1))


def test_apply_does_not_mutate_original(cv) -> None:
    role = cv.roles()[0]
    before = to_markdown(cv)
    cv.apply(Edit(role.id, role.bullets[0], "Changed.", role.source_role, 1))
    assert to_markdown(cv) == before


def test_edits_are_recorded(cv) -> None:
    role = cv.roles()[0]
    edited = cv.apply(Edit(role.id, role.bullets[0], "Changed.", role.source_role, 2))
    assert len(edited.edits) == 1
    assert edited.edits[0].gap_type == 2
    assert role.source_role in edited.diff_summary()[0]


# --- errors ---------------------------------------------------------------

def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CVError, match="not found"):
        load(tmp_path / "absent.md")


def test_document_without_sections_raises() -> None:
    with pytest.raises(CVError, match="no '## ' sections"):
        parse("just some prose with no headings at all")


def test_save_writes_derived_copy(cv, tmp_path: Path) -> None:
    out = save(cv, tmp_path / "sub" / "optimized_cv.md")
    assert out.read_text(encoding="utf-8") == to_markdown(cv)
