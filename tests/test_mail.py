"""Response loop — correlation, classification precedence, dormancy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vanguard.mail import (
    ACK_MARKERS,
    DECLINE_MARKERS,
    PROGRESS_MARKERS,
    Application,
    Correlation,
    Message,
    State,
    classify,
    correlate,
    dormant_sweep,
)

NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


def msg(body: str, subject: str = "", sender: str = "hr@justice.gov.uk") -> Message:
    return Message("m1", sender, subject, body, NOW)


@pytest.fixture
def apps() -> list[Application]:
    return [
        Application("civil_service_jobs:abc123", "Ministry of Justice",
                    "Senior Data Engineer", reference="19568",
                    employer_domain="justice.gov.uk",
                    submitted=NOW - timedelta(days=10)),
        Application("adzuna:xyz789", "Acme Analytics", "Data Scientist",
                    reference="AC-4412", employer_domain="acme.com",
                    submitted=NOW - timedelta(days=40)),
    ]


# --- THE rule: decline outranks progress ----------------------------------

def test_soft_rejection_is_decline_not_progress() -> None:
    """Rejections open warmly. Checking PROGRESS first would misread them."""
    result = classify(msg(
        "Thank you for your interest. We were very impressed and would like to "
        "keep your details on file. Unfortunately you have not been successful."
    ))
    assert result.state is State.DECLINE and result.rule == 1


def test_decline_wins_when_both_phrases_present() -> None:
    result = classify(msg(
        "We would like to invite you to consider future roles. However, on this "
        "occasion your application will not be progressing."
    ))
    assert result.state is State.DECLINE
    assert "outranks" in result.note


@pytest.mark.parametrize("marker", DECLINE_MARKERS)
def test_every_decline_marker_fires(marker: str) -> None:
    assert classify(msg(f"We regret that {marker} at this time.")).state is State.DECLINE


@pytest.mark.parametrize("marker", PROGRESS_MARKERS)
def test_every_progress_marker_fires(marker: str) -> None:
    assert classify(msg(f"Following review we {marker} next week.")).state is State.PROGRESS


@pytest.mark.parametrize("marker", ACK_MARKERS)
def test_every_ack_marker_fires(marker: str) -> None:
    assert classify(msg(f"This confirms {marker}.")).state is State.ACK


# --- matching discipline ---------------------------------------------------

@pytest.mark.parametrize(
    "body",
    ["We will recall your details should a role arise.",
     "You were called by our team.",
     "Expect a callback shortly."],
)
def test_substring_matching_is_prohibited(body: str) -> None:
    """The original design matched 'Call', firing on recall/called/callback."""
    assert classify(msg(body)).state is not State.PROGRESS


def test_unknown_message_is_ambiguous_not_forced() -> None:
    result = classify(msg("Please see the attached document regarding your file."))
    assert result.state is State.AMBIGUOUS and result.rule == 4
    assert "review manually" in result.note


def test_ack_carrying_a_question_is_query() -> None:
    result = classify(msg(
        "Thank you for applying. Could you confirm your right to work status?"
    ))
    assert result.state is State.QUERY


def test_classification_records_which_markers_fired() -> None:
    result = classify(msg("Unfortunately you have not been successful."))
    assert result.markers and "not been successful" in result.markers


# --- correlation runs first ------------------------------------------------

def test_reference_correlation_is_preferred(apps) -> None:
    result = correlate(msg("Regarding vacancy 19568.", sender="x@unknown.com"), apps)
    assert result.method is Correlation.REFERENCE
    assert result.application.vacancy_id == "civil_service_jobs:abc123"


def test_sender_domain_correlation(apps) -> None:
    result = correlate(msg("An update on your application.",
                           sender="recruit@justice.gov.uk"), apps)
    assert result.method is Correlation.SENDER_DOMAIN


def test_subdomain_matches_employer_domain(apps) -> None:
    result = correlate(msg("Update.", sender="no-reply@mail.justice.gov.uk"), apps)
    assert result.method is Correlation.SENDER_DOMAIN


def test_fuzzy_needs_both_employer_and_title(apps) -> None:
    """Title alone would match every open application in the same field."""
    assert not correlate(msg("Update", subject="Data Scientist role",
                             sender="x@nowhere.com"), apps).correlated
    assert correlate(msg("Update", subject="Acme Analytics - Data Scientist",
                         sender="x@nowhere.com"), apps).correlated


def test_uncorrelated_is_not_a_classification(apps) -> None:
    result = correlate(msg("Newsletter", sender="marketing@random.com"), apps)
    assert not result.correlated and result.method is Correlation.NONE


def test_no_applications_means_no_correlation() -> None:
    assert not correlate(msg("Anything"), []).correlated


# --- template invitation is advisory only ---------------------------------

def test_progress_invites_template_e() -> None:
    assert classify(msg("We would like to invite you to interview.")) \
        .state.invites_template == "E"


def test_decline_invites_template_d() -> None:
    assert classify(msg("You have not been successful.")) \
        .state.invites_template == "D"


@pytest.mark.parametrize("state", [State.ACK, State.ADMIN, State.AMBIGUOUS])
def test_neutral_states_invite_nothing(state: State) -> None:
    assert state.invites_template == ""


# --- dormancy --------------------------------------------------------------

def silence(board: str) -> int:
    return 30 if board in ("civil_service_jobs", "nhs_jobs") else 21


def test_dormant_uses_per_board_silence_days(apps) -> None:
    result = dormant_sweep(apps, [], silence, now=NOW)
    ids = {c.vacancy_id for c in result}
    assert "adzuna:xyz789" in ids          # 40 days, limit 21
    assert "civil_service_jobs:abc123" not in ids   # 10 days, limit 30


def test_correlated_applications_are_not_dormant(apps) -> None:
    result = dormant_sweep(apps, ["adzuna:xyz789"], silence, now=NOW)
    assert result == []


def test_dormant_reports_the_limit_applied(apps) -> None:
    candidate = dormant_sweep(apps, [], silence, now=NOW)[0]
    assert candidate.silence_days == 21 and candidate.days_silent == 40


def test_unsubmitted_applications_are_skipped() -> None:
    app = Application("b:1", "E", "T", submitted=None)
    assert dormant_sweep([app], [], silence, now=NOW) == []


def test_dormant_is_not_decline() -> None:
    """A derived state. Silence is an absence of information."""
    assert not hasattr(State, "DORMANT")
