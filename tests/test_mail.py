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
    """Title alone would match every open application in the same field.

    Amended 12 Aug 2026: employer AND title is necessary but no longer
    sufficient. The sender must also plausibly be the employer — a subject
    naming an employer proves nothing about who sent it, which is how a
    LinkedIn advert was attributed to a Beatport application.
    """
    assert not correlate(msg("Update", subject="Data Scientist role",
                             sender="x@nowhere.com"), apps).correlated
    assert not correlate(msg("Update", subject="Acme Analytics - Data Scientist",
                             sender="x@nowhere.com"), apps).correlated
    assert correlate(msg("Update", subject="Acme Analytics - Data Scientist",
                         sender="hiring@acme.com"), apps).correlated


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


# ---------------------------------------------------------------------------
# Broadcasts are not correspondence
#
# Observed 12 Aug 2026: 300 messages polled, 297 uncorrelated and all
# broadcasts. The three that DID correlate were LinkedIn job adverts —
# jobs-noreply@linkedin.com, "Olumide, apply now to 'Senior…'" — matched to a
# Beatport application because the subject carried the employer name and a
# job title.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sender, subject",
    [
        ("jobs-noreply@linkedin.com", "Olumide, apply now to 'Senior Data Scientist'"),
        ("jobalerts-noreply@linkedin.com", "Data Scientist - Python (Remote) at Hired"),
        ("donotreply@jobalert.indeed.com", "network engineer in Glasgow"),
        ("donotreply@match.indeed.com", "Network Operations Centre Director"),
        ("info@jobs.totaljobsmail.com", '6 new "Network Engineer" jobs in Glasgow'),
        ("info@jobs.cwjobs.co.uk", '7 new "Network Operations Engineer" jobs'),
        ("notifications-noreply@linkedin.com", "You appeared in 3 searches this week"),
        ("invitations@linkedin.com", "I want to connect"),
        ("newsletter@update.just-eat.co.uk", "Your 50% discount's waiting"),
    ],
)
def test_observed_broadcasts_are_recognised(sender: str, subject: str) -> None:
    """Every sender here came from a real poll of the operator's inbox."""
    from vanguard.mail import is_broadcast

    assert is_broadcast(msg("body text", subject=subject, sender=sender))


def test_broadcast_never_correlates(apps) -> None:
    """An advert is not correspondence. Filing one against an application
    would put it in that application's archive, and with the wrong wording
    could classify it as a decision."""
    result = correlate(
        msg("Great opportunities for you.",
            subject="Olumide, apply now to 'Senior Data Engineer' at Ministry of Justice",
            sender="jobs-noreply@linkedin.com"),
        apps,
    )
    assert not result.correlated


def test_a_reference_inside_a_broadcast_does_not_correlate(apps) -> None:
    """Superseded 12 Aug 2026. This previously asserted that a reference
    number survives the broadcast check.

    It does not, and should not. A job board digest can quote a reference in
    a list of vacancies without being a reply — the reference proves the
    vacancy is mentioned, not that the employer wrote. A genuine reply
    carrying a reference comes from the employer or their agency, and
    correlates at stage 1 as before.
    """
    from vanguard.mail import is_broadcast

    digest = msg("Regarding vacancy 19568 and others.",
                 sender="jobs-noreply@linkedin.com", subject="New jobs for you")
    assert is_broadcast(digest)
    assert not correlate(digest, apps).correlated

    genuine = msg("Regarding vacancy 19568.", sender="someone@agency.com",
                  subject="Your application")
    assert correlate(genuine, apps).method is Correlation.REFERENCE


def test_job_board_domain_cannot_match_fuzzily(apps) -> None:
    result = correlate(
        msg("body", subject="Ministry of Justice Senior Data Engineer",
            sender="someone@linkedin.com"),
        apps,
    )
    assert not result.correlated


# --- genuine replies must still get through -------------------------------

def test_named_recruiter_at_the_employer_domain_correlates() -> None:
    """The commonest shape of a real reply. It previously reached stage 3,
    which needs the employer name in the subject — something a recruiter
    would never write."""
    from vanguard.mail import Application

    apps = [Application("reed:1", "Beatport", "Senior Data Scientist",
                        reference="19568",
                        url="https://careers.beatport.com/jobs/123")]
    result = correlate(
        msg("We would like to invite you to interview.",
            subject="Senior Data Scientist - next steps",
            sender="sarah.chen@careers.beatport.com"),
        apps,
    )
    assert result.correlated and result.method is Correlation.SENDER_DOMAIN


def test_reference_still_correlates_from_any_sender(apps) -> None:
    result = correlate(
        msg("Regarding your application.", subject="Vacancy 19568",
            sender="recruitment@justice.gov.uk"),
        apps,
    )
    assert result.correlated and result.method is Correlation.REFERENCE


def test_board_url_yields_no_employer_domain() -> None:
    """A vacancy URL on reed.co.uk says nothing about which domain the
    employer will reply from."""
    from vanguard.mail import domain_of

    assert domain_of("https://www.reed.co.uk/jobs/x/57092035") == ""
    assert domain_of("https://careers.beatport.com/jobs/123") == "careers.beatport.com"


def test_ordinary_personal_mail_is_not_a_broadcast() -> None:
    from vanguard.mail import is_broadcast

    assert not is_broadcast(msg("Are you free Thursday?", subject="Coffee",
                                sender="friend@example.com"))


# ---------------------------------------------------------------------------
# Broadcasts are never replies
#
# Observed on the first live poll, 12 Aug 2026: `jobs-noreply@linkedin.com`
# advertising a Beatport vacancy correlated to an open Beatport application,
# because the subject carried the employer name and a job title. It was an
# advert. Attributing it would have filed a job advert in that application's
# archive, and — had the wording matched — classified it as a decline.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sender, subject",
    [
        ("jobs-noreply@linkedin.com", "Olumide, apply now to 'Senior Data Scientist'"),
        ("jobalerts-noreply@linkedin.com", "Data Scientist - Python (Remote) at Hired"),
        ("donotreply@jobalert.indeed.com", "network engineer in Glasgow: Lead Engineer"),
        ("donotreply@match.indeed.com", "Network Operations Centre Director"),
        ("info@jobs.cwjobs.co.uk", '7 new "Network Operations Engineer" jobs'),
        ("info@jobs.totaljobsmail.com", '6 new "Network Engineer" jobs in Glasgow'),
        ("notifications-noreply@linkedin.com", "You appeared in 3 searches this week"),
        ("invitations@linkedin.com", "I want to connect"),
        ("newsletter@update.just-eat.co.uk", "Your 50% discount's waiting"),
    ],
)
def test_observed_broadcast_senders_are_rejected(sender: str, subject: str) -> None:
    from vanguard.mail import is_broadcast

    assert is_broadcast(msg("body", subject=subject, sender=sender))


@pytest.mark.parametrize(
    "sender",
    ["careers@beatport.com", "recruit@justice.gov.uk", "sarah.chen@acme.co.uk",
     "hr@company.com", "hiring@agency.co.uk"],
)
def test_real_senders_are_not_broadcasts(sender: str) -> None:
    from vanguard.mail import is_broadcast

    assert not is_broadcast(msg("Thank you for your application.",
                                subject="Your application", sender=sender))


def test_advert_is_not_correlated_to_an_application() -> None:
    """The defect exactly as observed."""
    apps = [Application("reed:1", "Beatport", "Senior Data Scientist",
                        reference="19568", employer_domain="beatport.com")]
    advert = msg("Apply now.", sender="jobs-noreply@linkedin.com",
                 subject="Olumide, apply now to 'Senior Data Scientist' at Beatport")
    assert not correlate(advert, apps).correlated


def test_real_reply_still_correlates_by_domain() -> None:
    apps = [Application("reed:1", "Beatport", "Senior Data Scientist",
                        reference="19568", employer_domain="beatport.com")]
    reply = msg("Thank you for your application.", sender="careers@beatport.com",
                subject="Your application")
    assert correlate(reply, apps).method is Correlation.SENDER_DOMAIN


def test_real_reply_still_correlates_by_reference() -> None:
    """Reference beats everything, even from an unknown sender."""
    apps = [Application("reed:1", "Beatport", "Senior Data Scientist",
                        reference="19568", employer_domain="beatport.com")]
    reply = msg("Regarding vacancy 19568.", sender="someone@agency.com",
                subject="Update")
    assert correlate(reply, apps).method is Correlation.REFERENCE


# --- fuzzy matching now requires a plausible sender -----------------------

def test_fuzzy_requires_the_sender_to_plausibly_be_the_employer() -> None:
    """A subject naming an employer proves nothing about who sent it."""
    apps = [Application("reed:1", "Beatport", "Senior Data Scientist")]
    from_elsewhere = msg("See this role.", sender="hello@somewhere-else.com",
                         subject="Beatport Senior Data Scientist")
    assert not correlate(from_elsewhere, apps).correlated


def test_recruiter_acting_for_the_employer_still_matches() -> None:
    """An exact domain match is too strict — recruiters mail on behalf.

    Amended 12 Aug 2026: this now correlates at stage 2 rather than stage 4.
    The domain `beatport-talent.com` carries the employer name, and B-44 made
    stage 2 compare against the name when no domain is configured. Matching
    earlier on a stronger signal is an improvement, so the test asserts the
    outcome rather than which stage produced it.
    """
    apps = [Application("reed:1", "Beatport", "Senior Data Scientist")]
    recruiter = msg("About your application.", sender="hiring@beatport-talent.com",
                    subject="Beatport Senior Data Scientist")
    result = correlate(recruiter, apps)
    assert result.correlated
    assert result.application.vacancy_id == "reed:1"


def test_broadcast_check_precedes_correlation() -> None:
    """Filtered before any matching, so a broadcast cannot reach even the
    reference stage by coincidence."""
    apps = [Application("reed:1", "Beatport", "Senior Data Scientist",
                        reference="19568")]
    advert = msg("Vacancy 19568 and others.", sender="jobs-noreply@linkedin.com",
                 subject="New jobs for you")
    assert not correlate(advert, apps).correlated


# ---------------------------------------------------------------------------
# ATS acknowledgements — observed 12 Aug 2026
#
# Four genuine acknowledgements failed to correlate. An applicant-tracking
# system mails on the employer's behalf, so the sender domain is never the
# employer's; the employer name is in the subject instead.
# ---------------------------------------------------------------------------

@pytest.fixture
def ats_apps() -> list[Application]:
    return [
        Application("reed:1", "Beatport", "Senior Data Scientist", reference="19568"),
        Application("reed:2", "Sardine", "Data Scientist"),
        Application("reed:3", "Faculty", "Data Scientist"),
        Application("reed:4", "Method Resourcing", "Data Engineer"),
        Application("reed:5", "Harnham", "Data Scientist"),
    ]


@pytest.mark.parametrize(
    "sender, subject, employer",
    [
        ("notifications@app.bamboohr.com", "Thank you for applying at Beatport",
         "Beatport"),
        ("no-reply@ashbyhq.com", "Thank you for applying to Sardine!", "Sardine"),
        ("no-reply@ashbyhq.com", "Faculty | Application Confirmation for Data Scientist",
         "Faculty"),
        ("no-reply@jobs.reed.co.uk", "We've sent your application to Method Resourcing",
         "Method Resourcing"),
        ("jobs-noreply@linkedin.com", "Olumide, your application was sent to Harnham",
         "Harnham"),
    ],
)
def test_observed_acknowledgements_correlate(
    ats_apps, sender: str, subject: str, employer: str
) -> None:
    result = correlate(msg("Body.", subject=subject, sender=sender), ats_apps)
    assert result.correlated
    assert result.method is Correlation.ATS
    assert result.application.employer == employer


@pytest.mark.parametrize(
    "subject",
    [
        "Olumide, apply now to 'Senior Data Scientist at Beatport'",
        "Data Scientist at Sardine",
        "New jobs at Faculty",
    ],
)
def test_adverts_naming_the_same_employers_do_not_correlate(
    ats_apps, subject: str
) -> None:
    """An advert and an acknowledgement are both third parties naming an
    employer. The difference is intent, visible in the subject."""
    advert = msg("Body.", subject=subject, sender="jobs-noreply@linkedin.com")
    assert not correlate(advert, ats_apps).correlated


def test_acknowledgement_is_not_a_broadcast() -> None:
    """`jobs-noreply@linkedin.com` sends both adverts and 'your application
    was sent to X'. The sender cannot separate them; the subject can."""
    from vanguard.mail import is_broadcast

    assert not is_broadcast(msg("Body.", sender="jobs-noreply@linkedin.com",
                                subject="Your application was sent to Harnham"))
    assert is_broadcast(msg("Body.", sender="jobs-noreply@linkedin.com",
                            subject="apply now to Senior Data Scientist"))


def test_ats_stage_requires_applied_language(ats_apps) -> None:
    """The employer name alone is not enough — that is stage 4's test, and it
    requires a plausible sender."""
    bare = msg("Body.", subject="Beatport", sender="no-reply@ashbyhq.com")
    assert not correlate(bare, ats_apps).correlated


def test_employer_in_the_body_also_correlates(ats_apps) -> None:
    """Some acknowledgements name the employer only in the body."""
    result = correlate(
        msg("Thank you for applying. Your application to Sardine has been received.",
            subject="Application confirmation", sender="no-reply@ashbyhq.com"),
        ats_apps,
    )
    assert result.method is Correlation.ATS


def test_reference_still_wins_over_ats(ats_apps) -> None:
    """Stage order is unchanged: a reference is the strongest signal."""
    result = correlate(
        msg("Regarding vacancy 19568.", subject="Thank you for applying at Beatport",
            sender="no-reply@ashbyhq.com"),
        ats_apps,
    )
    assert result.method is Correlation.REFERENCE


# ---------------------------------------------------------------------------
# OFFER — added 12 Aug 2026
#
# Without it a job offer fell through to AMBIGUOUS, which is the single worst
# message to leave unclassified and the one that terminates a process.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    [
        "We are pleased to offer you the position of Senior Data Engineer.",
        "We are delighted to offer you the role.",
        "Please find attached your formal offer of employment.",
        "Congratulations, and welcome to the team!",
        "We would like to make you an offer.",
    ],
)
def test_offers_are_classified(body: str) -> None:
    assert classify(msg(body)).state is State.OFFER


def test_offer_outranks_progress_phrasing() -> None:
    """An offer routinely invites a further conversation. Reading that as
    another interview round would miss the outcome entirely."""
    result = classify(msg(
        "We would like to offer you the position, and would like to arrange "
        "a call to discuss the details."))
    assert result.state is State.OFFER


def test_decline_still_outranks_offer_language() -> None:
    """A rejection mentioning that the role was offered to someone else must
    not read as an offer."""
    result = classify(msg(
        "We have made an offer of employment to another candidate, so you "
        "have not been successful on this occasion."))
    assert result.state is State.DECLINE


# ---------------------------------------------------------------------------
# Sender domain against the employer NAME
#
# Found 12 Aug 2026 while testing the interview loop. `hr@sanderson.com` did
# not correlate to an application at Sanderson, because employer_domain is
# derived from the vacancy URL and a Reed URL correctly yields none — Reed is
# not the employer. Since most vacancies come from boards, most genuine
# employer replies failed to correlate at all.
# ---------------------------------------------------------------------------

@pytest.fixture
def board_sourced() -> list[Application]:
    """The normal case: vacancies found on a job board, so no employer domain."""
    from vanguard.mail import domain_of

    return [
        Application("reed:1", "Sanderson", "Machine Learning Engineer",
                    employer_domain=domain_of("https://www.reed.co.uk/jobs/x/1")),
        Application("reed:2", "Ministry of Justice", "Senior Data Engineer"),
    ]


def test_a_board_url_yields_no_employer_domain() -> None:
    from vanguard.mail import domain_of

    assert domain_of("https://www.reed.co.uk/jobs/x/1") == ""
    assert domain_of("https://careers.sanderson.com/jobs/1") == "careers.sanderson.com"


@pytest.mark.parametrize(
    "sender, employer",
    [
        ("hr@sanderson.com", "Sanderson"),
        ("careers@sanderson.com", "Sanderson"),
        ("no-reply@mail.justice.gov.uk", "Ministry of Justice"),
    ],
)
def test_employer_reply_correlates_without_a_configured_domain(
    board_sourced, sender: str, employer: str
) -> None:
    result = correlate(msg("We would like to invite you to interview.",
                           subject="Interview invitation", sender=sender),
                       board_sourced)
    assert result.method is Correlation.SENDER_DOMAIN
    assert result.application.employer == employer


@pytest.mark.parametrize(
    "sender",
    ["hr@totallyunrelated.com", "jobs-noreply@linkedin.com", "hr@services.com"],
)
def test_unrelated_senders_still_do_not_correlate(board_sourced, sender: str) -> None:
    """Words too common to identify anyone must not match every employer."""
    assert not correlate(
        msg("We would like to invite you to interview.",
            subject="Interview invitation", sender=sender),
        board_sourced,
    ).correlated


def test_short_tokens_do_not_match() -> None:
    """Three characters collide too often — 'AI' or 'IBM' would match domains
    belonging to neither."""
    from vanguard.mail import _domain_resembles_employer

    assert not _domain_resembles_employer("aig.com", "AI Group")
    assert _domain_resembles_employer("sanderson.com", "Sanderson")


def test_a_configured_domain_still_wins() -> None:
    """Where the vacancy lives on the employer's own site, that is the
    stronger signal and is checked first."""
    apps = [Application("x:1", "Acme", "Role",
                        employer_domain="careers.acme.co.uk")]
    result = correlate(msg("Body.", subject="Update",
                           sender="hr@careers.acme.co.uk"), apps)
    assert result.method is Correlation.SENDER_DOMAIN


# ---------------------------------------------------------------------------
# Several applications at one employer
#
# Observed 12 Aug 2026: a reply from hr@sanderson.com matched two live
# Sanderson applications and the system picked the first. Attaching an
# interview invitation — or a rejection — to the wrong vacancy is worse than
# leaving it queued.
# ---------------------------------------------------------------------------

@pytest.fixture
def two_at_one_employer() -> list[Application]:
    return [
        Application("reed:57092035", "Sanderson", "Machine Learning Engineer",
                    reference="19568"),
        Application("reed:57205320", "Sanderson", "MLE- Machine Learning Engineer"),
    ]


def test_several_matches_are_reported_not_guessed(two_at_one_employer) -> None:
    result = correlate(
        msg("We would like to invite you to interview.",
            subject="Interview invitation", sender="hr@sanderson.com"),
        two_at_one_employer,
    )
    assert result.ambiguous
    assert not result.correlated
    assert len(result.candidates) == 2


def test_a_reference_resolves_the_ambiguity(two_at_one_employer) -> None:
    """The strongest signal still decides."""
    result = correlate(
        msg("Regarding vacancy 19568.", subject="Update",
            sender="hr@sanderson.com"),
        two_at_one_employer,
    )
    assert result.method is Correlation.REFERENCE
    assert result.application.vacancy_id == "reed:57092035"


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("Sanderson MLE- Machine Learning Engineer", "reed:57205320"),
        ("Sanderson Machine Learning Engineer", "reed:57092035"),
    ],
)
def test_the_title_resolves_where_it_can(two_at_one_employer, subject: str,
                                         expected: str) -> None:
    """One title contains the other. The longer is the more specific, so it
    wins rather than the pair being reported ambiguous."""
    result = correlate(msg("Body.", subject=subject, sender="hr@sanderson.com"),
                       two_at_one_employer)
    assert result.correlated
    assert result.application.vacancy_id == expected


def test_one_application_is_never_ambiguous() -> None:
    apps = [Application("reed:1", "Sanderson", "Machine Learning Engineer")]
    result = correlate(
        msg("We would like to invite you to interview.",
            subject="Interview invitation", sender="hr@sanderson.com"),
        apps,
    )
    assert result.correlated and not result.ambiguous


def test_the_same_application_twice_is_not_two() -> None:
    """Identical vacancy ids collapse before the count is taken."""
    app = Application("reed:1", "Sanderson", "Machine Learning Engineer")
    result = correlate(
        msg("We would like to invite you to interview.",
            subject="Interview invitation", sender="hr@sanderson.com"),
        [app, app],
    )
    assert result.correlated and not result.ambiguous


def test_ambiguous_result_describes_itself(two_at_one_employer) -> None:
    result = correlate(
        msg("Body.", subject="Interview invitation", sender="hr@sanderson.com"),
        two_at_one_employer,
    )
    assert "2 applications" in result.describe()
    assert "reed:57092035" in result.describe()


# ---------------------------------------------------------------------------
# Thread correlation
#
# Observed 20 Aug 2026: Beatport sent an automated acknowledgement and then a
# human reply. The first correlated; the second did not.
#
# Every stage was tuned for machines — a reference, an employer domain, an
# applied-phrase, an employer-plus-title subject. A human writing "Re: next
# steps" from a personal address matched none of them, while replying to a
# message the system had ALREADY correlated.
# ---------------------------------------------------------------------------

@pytest.fixture
def beatport() -> list[Application]:
    return [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist")]


@pytest.fixture
def threads() -> dict[str, str]:
    return {
        "<ack@bamboohr>": "linkedin:a2d5",
        "subject:thank you for applying at beatport": "linkedin:a2d5",
    }


def test_a_reply_correlates_by_threading_header(beatport, threads) -> None:
    reply = msg("Hi Olumide, we would like to talk.", subject="Re: next steps",
                sender="sarah.jones@gmail.com")
    reply.in_reply_to = "<ack@bamboohr>"

    result = correlate(reply, beatport, known_threads=threads)
    assert result.method is Correlation.THREAD
    assert result.application.vacancy_id == "linkedin:a2d5"


def test_a_reply_correlates_by_subject_when_headers_are_absent(beatport,
                                                               threads) -> None:
    """Not every client sets In-Reply-To, and a forwarded message loses it."""
    reply = msg("Body.", subject="Re: Thank you for applying at Beatport",
                sender="sarah@elsewhere.io")
    assert correlate(reply, beatport,
                     known_threads=threads).method is Correlation.THREAD


def test_reply_prefixes_are_stripped_however_stacked() -> None:
    for subject in ("Re: Thanks", "RE: Thanks", "Fwd: Re: Thanks",
                    "RE[2]: Thanks", "  re : Thanks"):
        assert msg("b", subject=subject).subject_root == "Thanks"


def test_references_are_read_when_in_reply_to_is_missing(beatport,
                                                         threads) -> None:
    reply = msg("Body.", subject="Quick question", sender="s@elsewhere.io")
    reply.references = "<root@x> <ack@bamboohr>"
    assert correlate(reply, beatport,
                     known_threads=threads).method is Correlation.THREAD


def test_an_unrelated_message_does_not_correlate(beatport, threads) -> None:
    unrelated = msg("Body.", subject="Quick question", sender="s@elsewhere.io")
    assert not correlate(unrelated, beatport, known_threads=threads).correlated


def test_a_short_subject_cannot_thread(beatport) -> None:
    """"Re: Hi" must not match on subject alone — too many messages share it."""
    threads = {"subject:hi": "linkedin:a2d5"}
    assert not correlate(msg("Body.", subject="Re: Hi", sender="s@x.io"),
                         beatport, known_threads=threads).correlated


def test_threading_is_optional(beatport) -> None:
    """Callers that pass no threads behave exactly as before."""
    assert not correlate(msg("Body.", subject="Re: next steps",
                             sender="s@x.io"), beatport).correlated


# --- a newsletter is not an acknowledgement -------------------------------

@pytest.mark.parametrize(
    "subject, is_ack",
    [
        ("Thank you for applying at Beatport", True),
        ("Your application to Data Scientist at Datatech", True),
        ("Two fresh DS leads in Edinburgh + application update", False),
        ("New jobs for you + your application update", False),
        ("This week's roles + application received", False),
    ],
)
def test_a_newsletter_is_not_an_acknowledgement(subject: str,
                                                is_ack: bool) -> None:
    """"Two fresh DS leads in Edinburgh + application update" was exempted
    from the broadcast filter by "application update", correlated on the
    sender domain, classified PROGRESS, and reached round five of an
    interview process that never existed."""
    from vanguard.mail import looks_like_an_acknowledgement

    assert looks_like_an_acknowledgement(msg("b", subject=subject)) is is_ack


def test_a_recruiter_newsletter_stays_a_broadcast() -> None:
    from vanguard.mail import is_broadcast

    newsletter = msg("Body.", sender="hello@jackandjill.co.uk",
                     subject="Two fresh DS leads in Edinburgh + application update")
    assert is_broadcast(newsletter)


# ---------------------------------------------------------------------------
# "Thank you for your interest"
#
# Observed 20 Aug 2026. A Beatport reply from a named person read "Thank you
# for your interest in Beatport" and correlated to nothing: the ATS stage
# requires an applied-phrase, and the list knew only "applying" and
# "application". Employers write "interest" as often — and it is the standard
# opener for a rejection, which is the worst message to lose.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "subject",
    [
        "Thank you for your interest in Beatport",
        "Thanks for your interest in Beatport",
        "Beatport — update on your application",
        "Further to your application — Beatport",
        "We reviewed your application to Beatport",
        "After careful consideration — Beatport",
    ],
)
def test_an_employer_reply_correlates_however_it_is_worded(subject: str) -> None:
    apps = [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist")]
    result = correlate(
        msg("Body.", subject=subject, sender="notifications@app.bamboohr.com"),
        apps)
    assert result.correlated, f"{subject!r} did not correlate"


def test_applied_language_alone_is_not_enough() -> None:
    """The ATS stage needs the employer name too. "Further to your
    application for Senior Data Scientist" says which ROLE but not which
    COMPANY, and two employers may advertise the same title."""
    apps = [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist"),
            Application("reed:9", "Sagacity", "Senior Data Scientist")]
    result = correlate(
        msg("Body.", subject="Further to your application for Senior Data Scientist",
            sender="notifications@app.bamboohr.com"),
        apps)
    assert not result.correlated or result.ambiguous


def test_the_exact_message_that_was_missed() -> None:
    """Rob Eatwell, Beatport, 18 Aug 2026, via BambooHR."""
    apps = [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist")]
    result = correlate(
        msg("Body.", subject="Thank you for your interest in Beatport",
            sender="notifications@app.bamboohr.com"),
        apps)
    assert result.method is Correlation.ATS
    assert result.application.vacancy_id == "linkedin:a2d5"


def test_widening_the_phrases_did_not_let_adverts_through() -> None:
    """The phrases exist to separate an acknowledgement from an advert.
    Widening them must not blur that."""
    apps = [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist")]
    for subject in ("Data Scientist at Beatport",
                    "Olumide, apply now to 'Senior Data Scientist at Beatport'",
                    "Two fresh DS leads in Edinburgh + application update"):
        assert not correlate(
            msg("Body.", subject=subject,
                sender="jobalerts-noreply@linkedin.com"), apps).correlated, subject


# ---------------------------------------------------------------------------
# ATS routing tokens
#
# The operator noticed what the headers already state:
#
#   Reply-To: dc4+job+4e1f51283c7290391212f9eb552404910f3514d0+124894@app.bamboohr.com
#
# `124894` is the vacancy and the hex string the application. Every message
# about that application carries it, whatever the subject says — which makes
# it a stronger link than any phrase list, and one that does not depend on
# how a human worded their reply.
# ---------------------------------------------------------------------------

BAMBOO_REPLY_TO = ("dc4+job+4e1f51283c7290391212f9eb552404910f3514d0"
                   "+124894@app.bamboohr.com")


def test_routing_tokens_are_extracted() -> None:
    message = msg("Body.", subject="Anything",
                  sender="notifications@app.bamboohr.com")
    message.reply_to = BAMBOO_REPLY_TO
    assert message.routing_tokens == (
        "124894", "4e1f51283c7290391212f9eb552404910f3514d0")


@pytest.mark.parametrize(
    "vendor, reply_to, expected",
    [
        ("Lever", "4e1f5128-7c72-9039-1212-f9eb55240491@hire.lever.co",
         "4e1f5128-7c72-9039-1212-f9eb55240491"),
        ("Greenhouse", "no-reply+7c9f2a1b4e6d8c3a5f7b9e1d@greenhouse.io",
         "7c9f2a1b4e6d8c3a5f7b9e1d"),
        ("Ashby", "no-reply+aB3xK9mP2qR7sT4vW8yZ1nC5@ashbyhq.com",
         "ab3xk9mp2qr7st4vw8yz1nc5"),
        ("Workday", "reply-2847193@myworkdayjobs.com", "2847193"),
        ("SmartRecruiters", "apply+job-88213947@smartrecruiters.com", "88213947"),
        ("Personio", "bewerbung-4f8a2c9e1d7b3a5f@personio.de",
         "4f8a2c9e1d7b3a5f"),
    ],
)
def test_every_vendor_not_just_bamboohr(vendor: str, reply_to: str,
                                        expected: str) -> None:
    """Judged on SHAPE, so a vendor Vanguard has never seen still works.

    Splitting on every separator shredded Lever's UUID into five short
    pieces, and a hex-only rule missed Ashby's mixed-case tokens entirely.
    """
    message = msg("Body.", sender="no-reply@example.com")
    message.reply_to = reply_to
    assert expected in message.routing_tokens, f"{vendor} yielded nothing"


@pytest.mark.parametrize(
    "reply_to",
    [
        "sarah.jones@beatport.com",
        "careers@beatport.com",
        "recruiting@beatport.com",
        "no-reply@ashbyhq.com",
        "bewerbung@personio.de",
        "notifications@app.bamboohr.com",
    ],
)
def test_an_address_identifying_nothing_yields_nothing(reply_to: str) -> None:
    """`careers` and `bewerbung` are long enough to pass a length test and
    would correlate every message an employer ever sent."""
    message = msg("Body.", sender=reply_to)
    message.reply_to = reply_to
    assert message.routing_tokens == ()


def test_a_uuid_survives_being_split() -> None:
    """Splitting on `-` turned one identifier into five useless fragments."""
    message = msg("Body.", sender="x@hire.lever.co")
    message.reply_to = "4e1f5128-7c72-9039-1212-f9eb55240491@hire.lever.co"
    assert message.routing_tokens == ("4e1f5128-7c72-9039-1212-f9eb55240491",)


def test_a_short_token_is_refused() -> None:
    """Twelve hex characters could collide across applications."""
    message = msg("Body.", sender="x@teamtailor.com")
    message.reply_to = "jobs+a1b2c3d4e5f6@teamtailor.com"
    assert message.routing_tokens == ()


def test_generic_parts_are_not_tokens() -> None:
    """`dc4` and `job` appear in every BambooHR address and would match
    everything."""
    message = msg("Body.", sender="hr@acme.com")
    message.reply_to = "dc4+job+careers@acme.com"
    assert message.routing_tokens == ()


def test_an_ordinary_address_yields_no_tokens() -> None:
    message = msg("Body.", sender="sarah.jones@beatport.com")
    message.reply_to = "sarah.jones@beatport.com"
    assert message.routing_tokens == ()


def test_a_token_correlates_a_subject_that_says_nothing() -> None:
    """The point. "A quick note from Rob" has no employer, no title and no
    applied-phrase — every other stage fails, and the header states the
    answer outright."""
    apps = [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist")]
    threads = {"token:124894": "linkedin:a2d5"}

    message = msg("Body.", subject="A quick note from Rob",
                  sender="notifications@app.bamboohr.com")
    message.reply_to = BAMBOO_REPLY_TO

    result = correlate(message, apps, known_threads=threads)
    assert result.method is Correlation.THREAD
    assert result.application.vacancy_id == "linkedin:a2d5"


def test_a_different_application_does_not_match() -> None:
    apps = [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist")]
    threads = {"token:124894": "linkedin:a2d5"}

    message = msg("Body.", subject="A quick note",
                  sender="notifications@app.bamboohr.com")
    message.reply_to = ("dc4+job+aaaa1111bbbb2222cccc3333dddd4444eeee5555"
                        "+999111@app.bamboohr.com")
    assert not correlate(message, apps, known_threads=threads).correlated


def test_a_token_outranks_every_other_stage() -> None:
    """A header that names the application is not inference. Everything below
    it is."""
    apps = [Application("linkedin:a2d5", "Beatport", "Senior Data Scientist"),
            Application("reed:9", "Sagacity", "Data Scientist")]
    threads = {"token:124894": "linkedin:a2d5"}

    # A subject naming the WRONG employer, with the right token.
    message = msg("Body.", subject="Thank you for applying at Sagacity",
                  sender="notifications@app.bamboohr.com")
    message.reply_to = BAMBOO_REPLY_TO

    result = correlate(message, apps, known_threads=threads)
    assert result.application.vacancy_id == "linkedin:a2d5"


# ---------------------------------------------------------------------------
# Meaning, not markers
#
# A phrase list is a treadmill: every employer's wording is a new defect.
# "While the team has decided to proceed with other candidates" — an
# unmistakable rejection — matched none of the five DECLINE markers, and the
# message sat as AMBIGUOUS.
# ---------------------------------------------------------------------------

@pytest.fixture
def embedder():
    from vanguard.rank import LexicalEmbedder

    return LexicalEmbedder()


@pytest.mark.parametrize(
    "body, state",
    [
        ("While the team has decided to proceed with other candidates, we were "
         "impressed by your background.", State.DECLINE),
        ("We have chosen to move forward with applicants whose experience is a "
         "closer match to the role.", State.DECLINE),
        ("On this occasion we are unable to take your application further.",
         State.DECLINE),
        ("The team would like to meet you for the next stage. Are you free on "
         "Thursday?", State.PROGRESS),
        ("We are pleased to offer you the position of Data Scientist.",
         State.OFFER),
    ],
)
def test_wording_no_marker_covers_is_still_understood(embedder, body: str,
                                                      state: State) -> None:
    result = classify(msg(body, subject="Update to your application"),
                      embedder=embedder)
    assert result.state is state, result.note


def test_the_exact_message_that_was_missed(embedder) -> None:
    """WPP Media, 21 Aug 2026."""
    result = classify(
        msg("Thank you for taking the time to apply. While the team has "
            "decided to proceed with other candidates, we were impressed by "
            "your background.",
            subject="Update to Your Application for Data Scientist"),
        embedder=embedder)
    assert result.state is State.DECLINE


@pytest.mark.parametrize(
    "subject, body",
    [
        ("Data Scientist at Sky", "New roles matching your search. Apply now."),
        ("Your statement", "Your monthly statement is now available online."),
        ("This week in data", "Five articles our editors picked for you."),
        ("Hello", "Just checking in about a few things."),
    ],
)
def test_noise_does_not_become_a_decision(embedder, subject: str,
                                          body: str) -> None:
    """A wrong DECLINE drafts a feedback letter for a rejection nobody sent.
    AMBIGUOUS asks the operator to read it, which is the right failure."""
    assert classify(msg(body, subject=subject),
                    embedder=embedder).state is State.AMBIGUOUS


def test_rules_still_win_where_they_fire(embedder) -> None:
    """Deterministic and explainable beats inferred. A marker match names the
    phrase that decided; a semantic match can only give a number."""
    result = classify(msg("Unfortunately you have not been successful."),
                      embedder=embedder)
    assert result.state is State.DECLINE
    assert result.rule == 1, "a marker must decide before meaning does"


def test_a_semantic_decision_says_so(embedder) -> None:
    """An operator must be able to tell a rule from an inference."""
    result = classify(
        msg("The team has decided to proceed with other candidates."),
        embedder=embedder)
    assert result.rule == 6
    assert "semantic" in (result.note or "")


def test_classification_works_without_a_model() -> None:
    """torch is optional. Rules alone must still classify."""
    assert classify(msg("Unfortunately you have not been successful.")
                    ).state is State.DECLINE
    assert classify(msg("Something entirely unclear.")).state is State.AMBIGUOUS


def test_signatures_and_footers_are_not_classified(embedder) -> None:
    """A legal footer carries no decision and drags every similarity toward
    nothing."""
    from vanguard.mail import _decision_sentences

    message = msg("We have decided to proceed with other candidates.\n\n"
                  "This email and any attachments are confidential.\n"
                  "Registered in England and Wales number 123456.\n"
                  "Unsubscribe from these emails.")
    kept = _decision_sentences(message)
    assert any("other candidates" in line for line in kept)
    assert not any("confidential" in line.lower() for line in kept)
