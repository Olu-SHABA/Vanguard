"""Cover letter drafting — framed to the vacancy, bounded by the CV."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.coverage import compute_coverage, load_aliases
from vanguard.cv import load
from vanguard.extract import extract
from vanguard.letter import (
    DraftError,
    _condense,
    _frameable,
    _subject_of,
    draft_cover_letter,
    plan_letter,
)

ROOT = Path(__file__).parent.parent


@pytest.fixture
def cv():
    return load(ROOT / "data" / "canonical_cv.md")


@pytest.fixture
def report(cv):
    advert = (ROOT / "tests" / "fixtures" / "moj_senior_data_engineer.txt"
              ).read_text(encoding="utf-8")
    return compute_coverage(extract(advert), cv,
                            load_aliases(ROOT / "config" / "alias_table.yaml"))


def _letter(report, cv, **kwargs):
    return draft_cover_letter(
        report, cv,
        job_title=kwargs.pop("job_title", "Senior Data Engineer"),
        company=kwargs.pop("company", "Ministry of Justice"),
        applicant_name="Shaba Olumide Babashola",
        contact="olushaba79@gmail.com", **kwargs)


# --- the constraint -------------------------------------------------------

def test_every_bullet_traces_to_the_cv(report, cv) -> None:
    """The whole basis of the letter being trustworthy."""
    _, plan = _letter(report, cv)
    cv_text = cv.full_text().lower()
    for achievement in plan.achievements:
        assert achievement.cv_evidence.lower()[:60] in cv_text


def test_every_bullet_cites_a_source(report, cv) -> None:
    _, plan = _letter(report, cv)
    assert all(a.source_role.strip() for a in plan.achievements)


def test_unmet_requirements_never_appear(report, cv) -> None:
    """A cover letter is not the place to enumerate what you cannot do — and
    claiming one would be the failure this system exists to prevent."""
    letter, plan = _letter(report, cv)
    low = letter.lower()
    for term in plan.unmet_notable:
        assert term.lower() not in low


def test_a_letter_needs_three_supported_bullets(cv) -> None:
    """Padding to length with claims the CV does not carry is exactly what
    must not happen."""
    thin = compute_coverage(extract("Essential\n- Kubernetes\n- Terraform\n"),
                            cv, load_aliases(ROOT / "config" / "alias_table.yaml"))
    with pytest.raises(DraftError):
        _letter(thin, cv)


# --- responsive framing ---------------------------------------------------

def test_the_opening_names_what_the_role_asks_for(report, cv) -> None:
    """The template's opening was fixed text — the same two paragraphs on
    every application, with only the bullets varying."""
    letter, plan = _letter(report, cv)
    assert plan.framed
    for term in plan.frame_terms:
        assert term.lower() in letter.lower()


def test_frame_terms_are_matched_not_missing(report, cv) -> None:
    """Claiming a role centres on something the CV cannot demonstrate would
    invite the one question that cannot be answered."""
    _, plan = _letter(report, cv)
    matched = {(r.requirement.canonical or r.requirement.text or "").lower()
               for r in report.hits}
    assert all(term.lower() in matched for term in plan.frame_terms)


def test_the_opening_reflects_the_vacancy(report, cv) -> None:
    """The template's opening was fixed text. It now names what this role
    asks for, so two vacancies cannot produce the same first paragraph unless
    they ask for the same things."""
    letter, plan = _letter(report, cv)
    opening = letter.split("\n\n")[2]

    assert "Ministry of Justice" in opening
    assert "Senior Data Engineer" in opening
    assert any(term.lower() in opening.lower() for term in plan.frame_terms)


@pytest.mark.parametrize(
    "term, ok",
    [
        ("Python", True),
        ("ETL", True),
        ("data visualisation", True),
        ("teamwork", False),
        ("communication", False),
        ("designing and maintaining technical documentation", False),
    ],
)
def test_what_can_frame_a_letter(term: str, ok: bool) -> None:
    """"The role calls for teamwork" says nothing. A responsibility phrase is
    not a skill and reads as padding."""
    assert _frameable(term) is ok


# --- readability ----------------------------------------------------------

def test_a_long_cv_bullet_is_condensed(report, cv) -> None:
    """CV bullets are written to be scanned in context. A letter has three of
    them and no context."""
    letter, _ = _letter(report, cv)
    for line in letter.splitlines():
        if line.startswith("* "):
            assert len(line) < 260, f"bullet too long: {line[:60]}"


def test_condensing_never_adds_anything() -> None:
    """The letter may say less than the CV. It must never say more."""
    full = ("Designed and deployed a vectorized engine in Python, automating a "
            "manual cycle that consumed 60-90 minutes per run; reduced execution "
            "to under 2 seconds on datasets exceeding 800,000 rows. Implemented "
            "input validation and null-handling logic throughout the pipeline.")
    short = _condense(full)
    assert len(short) <= len(full)
    assert short.rstrip(".") in full or full.startswith(short.rstrip("."))


def test_the_same_point_is_not_made_twice(report, cv) -> None:
    """The reporting engine appears as an MTN achievement and again as a
    standalone project. Both are true; citing both makes one point twice."""
    _, plan = _letter(report, cv)
    subjects = [_subject_of(a.cv_evidence) for a in plan.achievements]
    assert len(subjects) == len(set(subjects))


def test_skills_lines_are_not_achievements(report, cv) -> None:
    """"Programming Languages: Python, JavaScript" answers many requirements
    and says nothing."""
    _, plan = _letter(report, cv)
    for achievement in plan.achievements:
        assert not achievement.cv_evidence.startswith("**Programming")
        assert "Collaborative Tools" not in achievement.cv_evidence


def test_the_plan_explains_itself(report, cv) -> None:
    """An achievement selected for reasons nobody can inspect is one nobody
    should trust."""
    _, plan = _letter(report, cv)
    explanation = plan.explain()
    assert any("framed on" in line for line in explanation)
    assert sum(1 for line in explanation if line.startswith("cites")) == 3
