"""Injection constraints — enforced in code, not by convention."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.coverage import Outcome, Resolution, load_aliases
from vanguard.cv import load
from vanguard.extract import Requirement
from vanguard.gaps import Gap, GapType
from vanguard.submission import detect
from vanguard.templates import (
    Achievement,
    InjectionError,
    render_cover_letter,
    render_essay,
    render_success_profile,
    verify_figures,
)

ROOT = Path(__file__).parent.parent
ADVERT = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def cv():
    return load(ROOT / "data" / "canonical_cv.md")


def ach(text: str, evidence: str = "achieving 99.99% network uptime") -> Achievement:
    return Achievement(text, "Avanti Communications, Oct 2024 – Jul 2025", evidence)


def type3(term: str) -> Gap:
    r = Requirement(term, "tool", "essential", True, canonical=term)
    return Gap(
        resolution=Resolution(r, Outcome.GAP, 0),
        gap_type=GapType.NOT_EVIDENCED,
        rationale="not evidenced",
    )


# --- the defect this project began with -----------------------------------

def test_invented_figure_is_blocked(cv) -> None:
    """A 92% improvement absent from the CV must not reach outbound text."""
    bad = ach("Compressed reporting pipelines by up to 92%")
    with pytest.raises(InjectionError, match=r"92%"):
        render_cover_letter(
            job_title="X", company="Y", applicant_name="Z", contact="c",
            achievements=[ach("Sustained 99.99% uptime"), ach("Sustained 99.99% uptime"), bad],
            cv=cv,
        )


def test_supported_figure_passes(cv) -> None:
    assert verify_figures("Sustained 99.99% network uptime", cv) == []


def test_unsupported_figure_detected(cv) -> None:
    assert "92%" in verify_figures("improved by 92% overall", cv)


def test_small_integers_are_not_claims(cv) -> None:
    """'Three points from my background' is prose, not a metric."""
    assert verify_figures("three points and 3 examples", cv) == []


# --- achievement contract -------------------------------------------------

def test_achievement_requires_source_role() -> None:
    with pytest.raises(InjectionError, match="no source role"):
        Achievement("claim", "", "evidence")


def test_achievement_requires_cv_evidence() -> None:
    with pytest.raises(InjectionError, match="no CV evidence"):
        Achievement("claim", "MTN, 2018-2024", "")


def test_achievement_rejects_empty_text() -> None:
    with pytest.raises(InjectionError, match="empty"):
        Achievement("  ", "MTN", "evidence")


def test_evidence_absent_from_cv_is_blocked(cv) -> None:
    fake = Achievement("Led the Mars programme", "NASA, 2030", "commanded the Mars ascent vehicle")
    with pytest.raises(InjectionError, match="absent from the canonical CV"):
        render_cover_letter(job_title="X", company="Y", applicant_name="Z", contact="c",
                            achievements=[fake, fake, fake], cv=cv)


# --- Type 3 never reaches an artefact -------------------------------------

def test_type_3_term_blocked_from_cover_letter(cv) -> None:
    a = ach("Built CI/CD pipelines for the team")
    with pytest.raises(InjectionError, match="Type 3 gap"):
        render_cover_letter(job_title="X", company="Y", applicant_name="Z", contact="c",
                            achievements=[a, a, a], cv=cv, gaps=[type3("CI/CD")])


def test_type_3_criterion_reported_before_drafting(cv) -> None:
    spec = detect(ADVERT.read_text(encoding="utf-8"))
    with pytest.raises(InjectionError, match="Report to the operator"):
        render_success_profile(
            job_title="Senior Data Engineer", company="MoJ", spec=spec,
            paragraphs=["a"] * len(spec.assessed_criteria), cv=cv, gaps=[type3("pytest")],
        )


# --- Template B -----------------------------------------------------------

def test_cover_letter_requires_exactly_three(cv) -> None:
    a = ach("Sustained 99.99% uptime")
    with pytest.raises(InjectionError, match="exactly 3"):
        render_cover_letter(job_title="X", company="Y", applicant_name="Z", contact="c",
                            achievements=[a, a], cv=cv)


def test_cover_letter_renders(cv) -> None:
    a = ach("Sustained 99.99% network uptime")
    out = render_cover_letter(job_title="Data Engineer", company="MoJ",
                              applicant_name="A", contact="a@b.c",
                              achievements=[a, a, a], cv=cv)
    bullets = [ln for ln in out.split("\n") if ln.startswith("* ")]
    assert "Data Engineer" in out and "MoJ" in out and len(bullets) == 3


# --- Template F -----------------------------------------------------------

def test_success_profile_paragraph_count_enforced(cv) -> None:
    spec = detect(ADVERT.read_text(encoding="utf-8"))
    with pytest.raises(InjectionError, match="one paragraph per criterion"):
        render_success_profile(job_title="X", company="Y", spec=spec,
                               paragraphs=["only one"], cv=cv)


def test_success_profile_word_limit_enforced(cv) -> None:
    spec = detect(ADVERT.read_text(encoding="utf-8"))
    long = " ".join(["word"] * 400)
    with pytest.raises(InjectionError, match="portal truncates"):
        render_success_profile(job_title="X", company="Y", spec=spec,
                               paragraphs=[long] * len(spec.assessed_criteria), cv=cv)


def test_success_profile_renders_within_budget(cv) -> None:
    spec = detect(ADVERT.read_text(encoding="utf-8"))
    para = " ".join(["word"] * 150)
    out = render_success_profile(job_title="Senior Data Engineer", company="MoJ",
                                 spec=spec, paragraphs=[para] * 4, cv=cv, vacancy_ref="19568")
    assert "19568" in out and "750" in out and "Anonymisation required:** Y" in out


def test_wrong_type_rejected_by_template_f(cv) -> None:
    spec = detect("Send us your CV please.")
    with pytest.raises(InjectionError, match="requires SUCCESS_PROFILE"):
        render_success_profile(job_title="X", company="Y", spec=spec, paragraphs=[], cv=cv)


# --- Template C -----------------------------------------------------------

def test_essay_renders_with_supported_metrics(cv) -> None:
    a = ach("sustaining 99.99% network uptime across Cisco, Juniper and satellite hub environments")
    out = render_essay(job_title="Data Engineer", company="MoJ", achievements=[a], cv=cv)
    assert "99.99%" in out and "MoJ" in out


def test_essay_blocks_unsupported_metric(cv) -> None:
    bad = ach("compressing reporting pipelines by up to 92%")
    with pytest.raises(InjectionError):
        render_essay(job_title="X", company="Y", achievements=[bad], cv=cv)
