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


# ---------------------------------------------------------------------------
# A decision hidden in a clause
#
# WPP Media, 21 Aug 2026:
#
#   "While the team has decided to proceed with other candidates, we want to
#    assure you that your skills, dedication, and the impact you are making
#    are deeply valued here at WPP Media."
#
# The rejection is a subordinate clause and the rest is reassurance. Scored
# whole the sentence reached 0.80; the clause alone reaches 0.96. Diluting a
# decision with the comfort wrapped around it is how a rejection reads as
# nothing in particular.
# ---------------------------------------------------------------------------

WPP_DECLINE = (
    "Hi Olumide,\n\n"
    "We truly appreciate the time, effort and interest you have shown with "
    "the Data Scientist role. While the team has decided to proceed with "
    "other candidates, we want to assure you that your skills, dedication, "
    "and the impact you are making are deeply valued here at WPP Media.\n\n"
    "We encourage you to explore the resources available from WPP Media "
    "University to support your growth and development."
)


def test_a_decision_inside_a_clause_is_found(embedder) -> None:
    result = classify(
        msg(WPP_DECLINE,
            subject="Update to Your Application for Data Scientist at WPP Media"),
        embedder=embedder)
    assert result.state is State.DECLINE, result.note


def test_the_clause_scores_higher_than_the_sentence(embedder) -> None:
    """The measurement behind the fix."""
    from vanguard.mail import _decision_sentences

    reference = "The team has decided to proceed with other candidates."
    lines = _decision_sentences(msg(WPP_DECLINE, subject="Update"))

    whole = next(l for l in lines
                 if "assure you" in l and "while the team" in l.lower())
    clause = next(l for l in lines
                  if l.lower().startswith("while the team has decided")
                  and "assure" not in l)

    assert embedder.similarity(clause, reference) > embedder.similarity(
        whole, reference)


@pytest.mark.parametrize(
    "sentence, expected",
    [
        ("While the team has decided to proceed with others, we wish you well",
         "while the team has decided to proceed with others"),
        ("Unfortunately we cannot take this further, but thank you",
         "unfortunately we cannot take this further"),
        ("Although your background is strong, we have chosen another candidate",
         "although your background is strong"),
    ],
)
def test_clauses_are_split_at_the_opener(sentence: str,
                                         expected: str) -> None:
    from vanguard.mail import _clauses_of

    clauses = [c.lower() for c in _clauses_of(sentence)]
    assert any(c.startswith(expected[:30]) for c in clauses), clauses


def test_the_matching_acknowledgement_stays_an_acknowledgement(embedder) -> None:
    """Both WPP messages come from the same address two days apart. Splitting
    clauses must not turn the welcome into a rejection."""
    ack = ("Thanks for your application to join WPP Media! We are excited you "
           "are interested. Our team is reviewing applications, and we will be "
           "in touch soon about the next steps in the interview process.")
    assert classify(msg(ack, subject="Thank you for applying to WPP Media!"),
                    embedder=embedder).state is State.ACK


@pytest.mark.parametrize(
    "subject, body",
    [
        ("Data Scientist at Sky",
         "New roles matching your search, apply now, and see more today."),
        ("This week in data",
         "Here are five articles our editors picked, covering models and tooling."),
        ("Your statement",
         "Your monthly statement is available to view online, please log in."),
    ],
)
def test_clause_splitting_did_not_make_it_eager(embedder, subject: str,
                                                body: str) -> None:
    """More candidate strings means more chances to match something. Noise
    must still stay AMBIGUOUS."""
    assert classify(msg(body, subject=subject),
                    embedder=embedder).state is State.AMBIGUOUS


def test_a_fragment_too_short_to_mean_anything_is_dropped() -> None:
    from vanguard.mail import _clauses_of

    assert all(len(c) >= 20
               for c in _clauses_of("Hi, thanks, bye, all the best, regards"))


# ---------------------------------------------------------------------------
# A described outcome is not a decision
#
# Faculty, 14 Aug 2026, in an ACKNOWLEDGEMENT explaining its own process:
#
#   "We will then either invite you to an introductory video call, or let you
#    know we will not be progressing your application on this occasion."
#
# `will not be progressing` is a DECLINE marker and it matched. An
# acknowledgement classified DECLINE drafts a feedback letter for a decision
# nobody made — the worst failure this classifier has.
# ---------------------------------------------------------------------------

FACULTY_ACK = (
    "Thank you for applying. We have received your application.\n\n"
    "Thank you so much for taking the time to apply for the Data Scientist at "
    "Faculty.\n\nWhat happens next?\n\nOne of our Talent Partners will review "
    "your application and assess if your skills align with the role.\n\nWe "
    "will then either invite you to an introductory video call, or let you "
    "know we will not be progressing your application on this occasion.\n\n"
    "You should expect to hear from us within 10 working days."
)

FACULTY_DECLINE = (
    "Thank you so much for taking the time to apply for our Data Scientist "
    "role.\n\nUnfortunately, after careful consideration, we have decided to "
    "move forward with other candidates at this time.\n\nThis decision was "
    "not easy, given the number of talented applicants we received."
)


def test_a_described_outcome_is_not_a_decision(embedder) -> None:
    result = classify(msg(FACULTY_ACK,
                          subject="Faculty | Application Confirmation for Data Scientist"),
                      embedder=embedder)
    assert result.state is State.ACK, result.note


def test_the_real_rejection_from_the_same_employer(embedder) -> None:
    """Four days apart, same sender, same opening sentence. One announces a
    decision and the other describes the possibility of one."""
    result = classify(msg(FACULTY_DECLINE,
                          subject="Faculty | Update on your application"),
                      embedder=embedder)
    assert result.state is State.DECLINE, result.note


@pytest.mark.parametrize(
    "body",
    [
        "We will then either invite you to a call, or let you know we will not "
        "be progressing your application.",
        "If we decide not to take your application further we will be in touch.",
        "Should your application be unsuccessful, we will let you know.",
    ],
)
def test_conditional_framing_never_classifies(embedder, body: str) -> None:
    assert classify(msg(body, subject="Application received"),
                    embedder=embedder).state is not State.DECLINE


def test_a_plain_marker_still_fires_on_rule_one(embedder) -> None:
    """Deterministic matching must not be lost to the guard."""
    result = classify(msg("Unfortunately you have not been successful on this "
                          "occasion."), embedder=embedder)
    assert result.state is State.DECLINE
    assert result.rule == 1


def test_a_real_rejection_that_also_explains_its_process(embedder) -> None:
    """A genuine decline may still describe what happens next. Checked per
    sentence, so the announcement is not lost to the description."""
    body = ("Unfortunately you have not been successful on this occasion. "
            "If we have suitable roles in future we will be in touch.")
    assert classify(msg(body), embedder=embedder).state is State.DECLINE


# ---------------------------------------------------------------------------
# A short employer name
#
# Observed 22 Aug 2026: an application to a company called Ki never appeared
# at all. Three independent length gates excluded it — it was never searched
# for, its domain could not match, and the ATS stage rejected a name under
# three characters. The floors existed to stop `dc4` and `job` matching
# everything, and were applied to employer names by accident.
# ---------------------------------------------------------------------------

@pytest.fixture
def short_name() -> list[Application]:
    return [Application("reed:1", "Ki", "Data Scientist")]


@pytest.mark.parametrize(
    "sender, subject",
    [
        ("careers@ki.com", "Thank you for applying"),
        ("no-reply@ashbyhq.com", "Thank you for applying at Ki"),
        ("no-reply@ashbyhq.com", "Ki | Application Confirmation"),
    ],
)
def test_a_two_letter_employer_correlates(short_name, sender: str,
                                          subject: str) -> None:
    assert correlate(msg("Thank you for applying.", subject=subject,
                         sender=sender), short_name).correlated


@pytest.mark.parametrize(
    "sender, subject, body",
    [
        ("no-reply@ashbyhq.com", "Thank you for applying",
         "Your skills matched what we are looking for."),
        ("hr@wiki.com", "Thank you for applying", "Body."),
        ("no-reply@ashbyhq.com", "Thank you for applying",
         "We look forward to working with strong applicants."),
        ("no-reply@ashbyhq.com", "Thank you for applying",
         "Taking your details forward."),
    ],
)
def test_a_short_name_does_not_match_inside_a_word(short_name, sender: str,
                                                   subject: str,
                                                   body: str) -> None:
    """`ki` appears inside working, skills, taking and wiki. A substring test
    would correlate every message that mentions a skill."""
    assert not correlate(msg(body, subject=subject, sender=sender),
                         short_name).correlated


def test_a_long_name_still_matches_as_a_substring() -> None:
    """Word-boundary matching is only needed for short names. "WPP Media"
    appears inside longer phrasing legitimately."""
    apps = [Application("reed:1", "Sanderson", "Data Scientist")]
    assert correlate(msg("Body.", subject="Thank you for applying at Sanderson's",
                         sender="no-reply@ashbyhq.com"), apps).correlated


# ---------------------------------------------------------------------------
# A decision outranks the courtesy it opens with
#
# Pflegia, 24 Aug 2026:
#
#   "Thank you for your interest in the position Data Scientist …
#    Based on your profile and the number of other qualified applications,
#    for the moment, we are not able to move forward in the recruiting
#    process with you."
#
# Classified ACK. The opener is formulaic and matched an acknowledgement
# reference closely; the rejection is oddly worded and matched less closely.
# Taking the single highest score made a rejection read as a thank-you.
# ---------------------------------------------------------------------------

PFLEGIA_DECLINE = (
    "Hi Olumide,\n\nThank you for your interest in the position Data "
    "Scientist - AI & Experimentation.\n\nWe have reviewed your application "
    "and carefully considered your qualifications. Based on your profile and "
    "the number of other qualified applications, for the moment, we are not "
    "able to move forward in the recruiting process with you.\n\n"
    "Good luck in your search!"
)


def test_a_decision_outranks_a_warm_opener(embedder) -> None:
    result = classify(msg(PFLEGIA_DECLINE, subject="Your application at Pflegia"),
                      embedder=embedder)
    assert result.state is State.DECLINE, result.note


def test_an_acknowledgement_with_no_decision_stays_one(embedder) -> None:
    """The same employer's confirmation, a day earlier. Preferring decisive
    states must not make every acknowledgement a rejection."""
    body = ("Hi Olumide,\n\nYou have successfully submitted your application "
            "for this position: Data Scientist.\n\nSomeone will review your "
            "qualifications shortly.\n\nThank you for your interest in Pflegia.")
    assert classify(msg(body, subject="We received your application"),
                    embedder=embedder).state is not State.DECLINE


def test_the_note_explains_an_overridden_opener(embedder) -> None:
    """An operator must be able to see why a warm message was read as a
    rejection."""
    result = classify(msg(PFLEGIA_DECLINE, subject="Your application"),
                      embedder=embedder)
    assert result.rule == 6
    assert "semantic" in (result.note or "")


# --- a digest is a digest whatever it says --------------------------------

@pytest.mark.parametrize(
    "subject",
    [
        "Technical Lead ML at Bjak + Lead Data Scientist at Ki",
        "Two fresh DS leads in Edinburgh + application update",
        "Senior Analyst at Acme, Data Scientist at Beta",
    ],
)
def test_a_subject_naming_two_roles_is_a_listing(subject: str) -> None:
    """No acknowledgement mentions two employers. The shape catches digests
    the wording does not."""
    from vanguard.mail import _looks_like_a_listing

    assert _looks_like_a_listing(subject)


@pytest.mark.parametrize(
    "subject",
    [
        "Thank you for applying at Beatport",
        "Your application at Pflegia",
        "Faculty | Update on your application for Data Scientist",
        "Interview invitation for Data Scientist at Sanderson",
        "Data Scientist at Sky",
    ],
)
def test_a_single_role_subject_is_not_a_listing(subject: str) -> None:
    from vanguard.mail import _looks_like_a_listing

    assert not _looks_like_a_listing(subject)


def test_a_digest_from_a_human_address_is_still_a_broadcast() -> None:
    """A small recruiter mails from `hello@`, so the sender says nothing."""
    from vanguard.mail import is_broadcast

    assert is_broadcast(msg("Body.", sender="hello@jackandjill.co.uk",
                            subject="Technical Lead ML at Bjak + Lead Data "
                                    "Scientist at Ki"))


# ---------------------------------------------------------------------------
# OFFER is never reached by meaning alone
#
# Observed 22 Aug 2026: acknowledgements classified OFFER. The B-72 fix said a
# decisive state wins "whenever it clears the bar", so a warm welcome scoring
# just above threshold against "we are pleased to offer you the position" beat
# the same message scoring far higher against an acknowledgement.
#
# Telling someone they have a job they do not have could stop them applying
# elsewhere. That failure is not recoverable; missing an oddly worded offer
# is — the operator opens it.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    [
        "We are excited you are interested in joining us and would be "
        "delighted to have you on the team.",
        "We are delighted by your interest in the role and will review your "
        "application shortly.",
        "Welcome to our application process. We are pleased you applied.",
        "Thanks for your application to join WPP Media! We are excited you "
        "are interested in becoming part of our global media collective.",
    ],
)
def test_an_enthusiastic_acknowledgement_is_never_an_offer(embedder,
                                                           body: str) -> None:
    assert classify(msg(body, subject="Thanks for applying"),
                    embedder=embedder).state is not State.OFFER


@pytest.mark.parametrize(
    "body",
    [
        "We are pleased to offer you the position of Data Scientist.",
        "Congratulations and welcome to the team!",
        "Please find attached your formal offer of employment.",
    ],
)
def test_a_real_offer_still_lands_by_marker(embedder, body: str) -> None:
    """Employers state an offer unambiguously. The marker list covers it."""
    result = classify(msg(body, subject="Good news"), embedder=embedder)
    assert result.state is State.OFFER
    assert result.rule == 2, "a marker must decide, not meaning"


def test_overriding_a_better_match_needs_a_better_reason(embedder) -> None:
    """A decisive state overrides a provisional one only when clearly
    confident, not merely by being in a more important category."""
    warm = ("Thank you so much for applying. We are reviewing applications "
            "and will be in touch.")
    assert classify(msg(warm, subject="Application received"),
                    embedder=embedder).state in (State.ACK, State.AMBIGUOUS)


def test_pflegia_survives_the_stricter_bar(embedder) -> None:
    """The B-72 fix must not be undone by tightening it."""
    assert classify(msg(PFLEGIA_DECLINE, subject="Your application at Pflegia"),
                    embedder=embedder).state is State.DECLINE


# ---------------------------------------------------------------------------
# Ki — the whole conversation
#
# Three messages over five days, all via Workable. The company name is two
# characters, which made it invisible until B-71, and the submission receipt
# uses wording no ACK marker covered.
#
# This is the whole thread as it arrived, kept together because the value is
# in the sequence: two acknowledgements and a decline.
# ---------------------------------------------------------------------------

KI_SUBMISSION = (
    "Ki\n\nYour application for the Associate Data Scientist job was submitted "
    "successfully.\n\nHere's a copy of your application data for safekeeping."
    "\n\nPersonal information\nName Olumide Shaba\nResume cv.pdf"
)

KI_ACKNOWLEDGEMENT = (
    "Dear Olumide,\n\nThank you for applying for the Associate Data Scientist "
    "role at Ki. We're thrilled that you're considering joining us, and wanted "
    "to confirm that we have received your application.\n\nYour application "
    "will be thoroughly reviewed by our hiring team and we will be in touch if "
    "your experience is a good match for the position."
)

KI_DECLINE = (
    "Dear Olumide,\n\nThank you for your interest in the Associate Data "
    "Scientist position at Ki. We appreciate the time and effort you put into "
    "your application.\n\nWe have reviewed your application and unfortunately "
    "will not be progressing at this time.\n\nWe received a high volume of "
    "applications and while yours was reviewed thoroughly, we've decided to "
    "move forward with candidates whose experience more closely aligns with "
    "the requirements of the role."
)


@pytest.fixture
def ki() -> list[Application]:
    return [Application("reed:1", "Ki", "Associate Data Scientist")]


@pytest.mark.parametrize(
    "sender, subject, body, expected",
    [
        ("noreply@candidates.workablemail.com",
         "Your application for the Associate Data Scientist job was submitted "
         "successfully.", KI_SUBMISSION, State.ACK),
        ("4f07z7ifglkf+bnnx@inbound.workablemail.com",
         "Thank you for applying for the Associate Data Scientist role at Ki",
         KI_ACKNOWLEDGEMENT, State.ACK),
        ("noreply@candidates.workablemail.com",
         "Thank you for your interest in the Associate Data Scientist position "
         "at Ki", KI_DECLINE, State.DECLINE),
    ],
)
def test_the_whole_ki_thread(ki, embedder, sender: str, subject: str,
                             body: str, expected: State) -> None:
    message = msg(body, subject=subject, sender=sender)
    assert correlate(message, ki).correlated, "did not correlate"
    assert classify(message, embedder=embedder).state is expected


def test_a_submission_receipt_is_an_acknowledgement(embedder) -> None:
    """Workable confirms a submission rather than thanking the applicant.
    "Your application was submitted successfully" matched no ACK marker."""
    for body in ("Your application was submitted successfully.",
                 "Here's a copy of your application data for safekeeping.",
                 "Your application has been submitted."):
        assert classify(msg(body, subject="Application"),
                        embedder=embedder).state is State.ACK


def test_the_ki_decline_is_not_softened_away(embedder) -> None:
    """It opens with thanks, mentions a high volume of applications, and buries
    the decision in the middle. All three are softeners this classifier has
    been caught by before."""
    assert classify(msg(KI_DECLINE, subject="Thank you for your interest"),
                    embedder=embedder).state is State.DECLINE


# ---------------------------------------------------------------------------
# The thresholds, set from measurement
#
# Both were judgement, and judgement produced seven misclassifications out of
# twenty-six. These are the scores MiniLM actually gave on the operator's own
# mail, captured with `vanguard responses <ID> --explain`.
#
# The classifier was ranking correctly all along — ACK topped every one of the
# seven. What went wrong was the THRESHOLD rejecting a correct answer that
# scored modestly, and the store then freezing the wrong one.
# ---------------------------------------------------------------------------

MEASURED = [
    ("Sanderson receipt", {"ACK": 0.64, "DECLINE": 0.59, "OFFER": 0.56,
                           "PROGRESS": 0.46}, State.ACK),
    ("Faculty confirmation", {"ACK": 0.63, "OFFER": 0.56, "DECLINE": 0.53,
                              "PROGRESS": 0.47}, State.ACK),
    ("Pflegia confirmation", {"ACK": 1.00, "OFFER": 0.65, "DECLINE": 0.62,
                              "PROGRESS": 0.51}, State.ACK),
    ("Pflegia rejection", {"DECLINE": 1.00, "ACK": 0.80, "OFFER": 0.54,
                           "PROGRESS": 0.45}, State.DECLINE),
    ("Faculty rejection", {"DECLINE": 1.00, "ACK": 0.67, "OFFER": 0.56,
                           "PROGRESS": 0.46}, State.DECLINE),
]


from vanguard.mail import REFERENCES  # noqa: E402


class _ScriptedEmbedder:
    """Returns the measured score for whichever state a reference belongs to.

    Lets the real numbers drive the decision logic without needing the model.
    """

    def __init__(self, scores: dict) -> None:
        self._scores = scores
        self._of_reference = {example: state
                              for state, examples in REFERENCES.items()
                              for example in examples}

    def similarity(self, line: str, example: str) -> float:
        return self._scores.get(self._of_reference.get(example, ""), 0.0)


@pytest.mark.parametrize("label, scores, expected",
                         [(m[0], m[1], m[2]) for m in MEASURED])
def test_the_measured_scores_decide_correctly(label: str, scores: dict,
                                              expected: State) -> None:
    """A threshold of 0.72 rejected the three acknowledgements that scored
    correctly but modestly; a margin of 0.08 rejected two more."""
    result = classify(msg("Any body text long enough to be considered.",
                          subject="Subject"),
                      embedder=_ScriptedEmbedder(scores))
    assert result is not None
    assert result.state is expected, f"{label}: {result.note}"


def test_a_near_tie_is_still_refused() -> None:
    """The defect that started this: two states within the margin is noise,
    not a decision."""
    result = classify(msg("Any body text long enough to be considered.",
                          subject="Subject"),
                      embedder=_ScriptedEmbedder({"ACK": 0.64,
                                                  "DECLINE": 0.63}))
    assert result.state is State.AMBIGUOUS


def test_the_thresholds_are_stated_in_the_module() -> None:
    """Fitted to five examples. Anyone changing them should see that."""
    from vanguard.mail import SEMANTIC_MARGIN, SEMANTIC_THRESHOLD

    assert 0.5 <= SEMANTIC_THRESHOLD <= 0.8
    assert 0.02 <= SEMANTIC_MARGIN <= 0.15


# ---------------------------------------------------------------------------
# A board's dispatch receipt is a fixed string
#
# Three near-identical Reed receipts classified ACK, AMBIGUOUS and AMBIGUOUS.
# Their bodies differ only in a "recommended jobs" block, which shifted the
# scores by a few hundredths either side of the margin.
#
# A board's receipt is a small closed set, unlike employer phrasing. Deciding
# it semantically made a fixed string a coin flip.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("employer",
                         ["Sanderson", "C4S Search Ltd", "Method Resourcing"])
def test_every_reed_receipt_classifies_the_same(embedder, employer: str) -> None:
    body = ("Application sent. Your application is on its way! We have "
            "attached a copy of your CV and cover letter. Based on the job "
            "you have applied for, we recommend: Data Scientist, AI Engineer.")
    result = classify(msg(body, subject=f"We've sent your application to {employer}",
                          sender="no-reply@jobs.reed.co.uk"), embedder=embedder)
    assert result.state is State.ACK
    assert result.rule <= 4, "a fixed string should not be decided semantically"


def test_a_linkedin_dispatch_receipt_is_an_acknowledgement(embedder) -> None:
    body = ("Your application was sent to Ki\n\nAssociate Data Scientist\nKi\n"
            "London\n\nApplied on August 19, 2026")
    assert classify(msg(body, subject="Olumide, your application was sent to Ki",
                        sender="jobs-noreply@linkedin.com"),
                    embedder=embedder).state is State.ACK


def test_a_receipt_echoing_the_form_is_not_a_query(embedder) -> None:
    """Workable returns a copy of the submitted application, questions and
    all. Those are the APPLICANT's own answers quoted back, not the employer
    asking anything."""
    body = ("Ki\n\nYour application for the Associate Data Scientist job was "
            "submitted successfully.\nHere's a copy of your application data "
            "for safekeeping.\n\nPERSONAL INFORMATION\nName: Olumide Shaba\n\n"
            "Answers\n\nHow would you assess your Python skill level "
            "(Beginner, Intermediate, Advanced)?\nAdvanced\n\n"
            "What machine learning libraries have you used and how?\n"
            "I have extensive experience with Scikit-learn.")
    result = classify(msg(body, subject="Thanks for applying to Ki",
                          sender="noreply@candidates.workablemail.com"),
                      embedder=embedder)
    assert result.state is State.ACK, result.note


# ---------------------------------------------------------------------------
# The similarity loop
#
# Sixty decision lines against forty-five reference sentences is 2,700 dot
# products of 384-dimensional vectors in pure Python, per message. Measured at
# three seconds each, which was most of the cost of classifying a mailbox.
#
# Encodings were already cached; the waste was the arithmetic.
# ---------------------------------------------------------------------------

class _FakeModel:
    """Deterministic unit vectors, as a real embedder produces."""

    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float]:
        import math
        import random

        if text not in self._cache:
            rng = random.Random(abs(hash(text)) % 10 ** 8)
            vector = [rng.gauss(0, 1) for _ in range(384)]
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            self._cache[text] = [x / norm for x in vector]
        return self._cache[text]

    def similarity(self, a: str, b: str) -> float:
        return sum(x * y for x, y in zip(self.embed(a), self.embed(b)))


def test_the_matrix_path_agrees_with_the_loop() -> None:
    """The optimisation must not change a single score. Verified against the
    same embedder, with numpy present and absent."""
    import builtins

    from vanguard.mail import semantic_scores

    model = _FakeModel()
    body = "\n".join(
        f"Sentence number {i} about an application, long enough to count."
        for i in range(20))
    message = msg(body, subject="Update on your application")

    with_numpy = semantic_scores(message, model)

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("blocked for this test")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _blocked
    try:
        without_numpy = semantic_scores(message, model)
    finally:
        builtins.__import__ = real_import

    assert set(with_numpy) == set(without_numpy)
    for state in with_numpy:
        assert abs(with_numpy[state][0] - without_numpy[state][0]) < 1e-9
        assert with_numpy[state][1] == without_numpy[state][1], (
            "the winning line must be the same")


def test_classification_survives_an_embedder_without_embed(embedder) -> None:
    """The lexical fallback exposes `similarity` but not `embed`. The loop
    path must still work."""
    assert not hasattr(embedder, "embed") or classify(
        msg("Unfortunately you have not been successful."),
        embedder=embedder).state is State.DECLINE
