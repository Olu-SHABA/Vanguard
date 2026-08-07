"""Submission-type detection and the four independent flags."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.submission import SubmissionType, detect

ADVERT = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def spec():
    return detect(ADVERT.read_text(encoding="utf-8"))


# --- type -----------------------------------------------------------------

def test_moj_advert_is_success_profile(spec) -> None:
    assert spec.submission_type is SubmissionType.SUCCESS_PROFILE
    assert spec.template == "F"


def test_success_profile_needs_cv_and_statement(spec) -> None:
    """Not an essay-instead-of-CV route."""
    assert spec.requires_cv_and_statement


def test_default_is_standard_cv() -> None:
    s = detect("We are hiring a data scientist. Please send your CV.")
    assert s.submission_type is SubmissionType.STANDARD_CV and s.template == "B"


def test_narrative_essay_detected() -> None:
    s = detect("Please provide a statement of suitability. Attachments are not accepted.")
    assert s.submission_type is SubmissionType.NARRATIVE_ESSAY and s.template == "C"


def test_personal_statement_alone_is_not_decisive() -> None:
    """Weak marker: needs a word limit or Behaviours to fire SUCCESS_PROFILE."""
    s = detect("Include a personal statement with your application.")
    assert s.submission_type is not SubmissionType.SUCCESS_PROFILE


def test_personal_statement_plus_word_limit_is_decisive() -> None:
    s = detect("Include a Personal Statement of no more than 500 words.")
    assert s.submission_type is SubmissionType.SUCCESS_PROFILE


# --- flags ----------------------------------------------------------------

def test_anonymise_flag(spec) -> None:
    assert spec.anonymise


@pytest.mark.parametrize(
    "phrase",
    ["an anonymised CV is required", "we operate anonymous shortlisting",
     "do not include your name on any document"],
)
def test_anonymise_markers(phrase: str) -> None:
    assert detect(phrase).anonymise


def test_word_limit_extracted(spec) -> None:
    assert spec.word_limit == 750


@pytest.mark.parametrize(
    "phrase, expected",
    [("no more than 750 words", 750), ("500 word limit", 500),
     ("maximum of 1000 words", 1000), ("within 250 words", 250)],
)
def test_word_limit_patterns(phrase: str, expected: int) -> None:
    assert detect(phrase).word_limit == expected


def test_unparseable_word_limit_flags_never_assumes() -> None:
    """A truncated statement loses its final paragraph. Never guess."""
    s = detect("Your statement must respect the stated word limit.")
    assert s.word_limit is None
    assert s.word_limit_stated_unparseable and s.flagged


def test_absent_word_limit_does_not_flag() -> None:
    s = detect("Send us your CV and a short covering note.")
    assert s.word_limit is None and not s.flagged


def test_assessed_criteria_are_the_sift_criteria_not_interview(spec) -> None:
    """Both lists exist in the advert. The statement addresses the sift list."""
    assert len(spec.assessed_criteria) == 4
    joined = " ".join(spec.assessed_criteria).lower()
    assert "python and sql" in joined
    assert "changing and improving" not in joined


def test_word_budget_per_criterion(spec) -> None:
    assert spec.words_per_criterion == 187


def test_lead_criterion_extracted(spec) -> None:
    assert "python and sql" in spec.lead_criterion.lower()


def test_behaviours_named_separately(spec) -> None:
    assert len(spec.behaviours) == 2


# --- matching discipline --------------------------------------------------

def test_substring_matching_prohibited() -> None:
    """'behaviours' must not fire on 'behavioural science'."""
    s = detect("We study behavioural economics in our research team.")
    assert s.submission_type is SubmissionType.STANDARD_CV


def test_empty_advert_is_standard_cv() -> None:
    assert detect("").submission_type is SubmissionType.STANDARD_CV
