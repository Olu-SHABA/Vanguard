"""Application channel — how a vacancy is applied to, and where."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.channel import (
    Channel,
    RegistrationStore,
    classify_channel,
    host_of,
)


@pytest.fixture
def registrations(tmp_path: Path) -> RegistrationStore:
    return RegistrationStore(str(tmp_path / "v.db"))


# --- classification -------------------------------------------------------

@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.reed.co.uk/jobs/x/1", Channel.BOARD_DIRECT),
        ("https://www.linkedin.com/jobs/view/1", Channel.BOARD_PROFILE),
        ("https://www.civilservicejobs.service.gov.uk/csr/x", Channel.BOARD_PROFILE),
        ("https://www.jobs.nhs.uk/candidate/x", Channel.BOARD_PROFILE),
        ("https://boards.greenhouse.io/acme/jobs/1", Channel.EMPLOYER_ATS),
        ("https://acme.bamboohr.com/careers/12", Channel.EMPLOYER_ATS),
        ("https://jobs.lever.co/acme/1", Channel.EMPLOYER_ATS),
        ("https://acme.wd3.myworkdayjobs.com/x", Channel.EMPLOYER_ATS),
    ],
)
def test_known_hosts_classify(url: str, expected: Channel) -> None:
    assert classify_channel(url).channel is expected


def test_an_unknown_host_is_the_employers_own_site() -> None:
    guess = classify_channel("https://careers.sanderson.com/jobs/1")
    assert guess.channel is Channel.EMPLOYER_ATS
    assert "not a known board" in guess.reason


def test_advert_phrasing_overrides_a_board_url() -> None:
    """A Reed listing that says "apply on the company website" is an
    EMPLOYER_ATS application whatever the link looks like."""
    guess = classify_channel("https://www.reed.co.uk/jobs/x/1",
                             "To apply, please visit our careers page.")
    assert guess.channel is Channel.EMPLOYER_ATS
    assert "reed.co.uk" in guess.reason


def test_an_ats_url_is_not_overridden() -> None:
    """A Greenhouse URL is already the employer's system. Advert phrasing
    cannot make it something else."""
    guess = classify_channel("https://boards.greenhouse.io/acme/jobs/1",
                             "Apply on the company website.")
    assert guess.channel is Channel.EMPLOYER_ATS


def test_no_url_and_no_signal_is_unknown() -> None:
    """Guessing would send the operator to the wrong place. UNKNOWN asks."""
    guess = classify_channel("", "", board_id="reed")
    assert guess.channel is Channel.UNKNOWN
    assert not guess.certain


def test_advert_phrasing_alone_can_decide() -> None:
    guess = classify_channel("", "Please apply on the company website.")
    assert guess.channel is Channel.EMPLOYER_ATS


def test_every_guess_states_a_reason() -> None:
    """A classification the operator cannot argue with is one they cannot
    act on."""
    for url in ("https://www.reed.co.uk/x", "https://unknown.example/x", ""):
        assert classify_channel(url, board_id="reed").reason


@pytest.mark.parametrize(
    "url, host",
    [
        ("https://www.reed.co.uk/jobs/x", "reed.co.uk"),
        ("https://boards.greenhouse.io/a", "boards.greenhouse.io"),
        ("http://Example.COM/x", "example.com"),
        ("not a url", ""),
        ("", ""),
    ],
)
def test_host_parsing(url: str, host: str) -> None:
    assert host_of(url) == host


def test_profile_boards_are_marked() -> None:
    """LinkedIn applies from a built profile, not an uploaded CV. Telling the
    operator to have a PDF ready would be wrong."""
    assert classify_channel("https://www.linkedin.com/jobs/view/1"
                            ).channel.needs_profile
    assert not classify_channel("https://www.reed.co.uk/jobs/x/1"
                                ).channel.needs_profile


# --- registration ---------------------------------------------------------

def test_registration_is_asserted_not_detected(registrations) -> None:
    """Nothing logs in to check. Detection would need credentials for dozens
    of portals — one file that, if leaked, opens every account."""
    assert registrations.get("board", "reed.co.uk") is None

    registrations.set("board", "reed.co.uk")
    record = registrations.get("board", "reed.co.uk")
    assert record is not None and record.registered


def test_the_two_scopes_are_separate(registrations) -> None:
    """Boards are a small fixed set; employer portals are unbounded."""
    registrations.set("board", "reed.co.uk")
    registrations.set("employer", "careers.acme.com")

    assert registrations.get("board", "careers.acme.com") is None
    assert len(registrations.all()) == 2


def test_a_profile_is_recorded_separately(registrations) -> None:
    registrations.set("board", "linkedin.com", profile_built=True)
    record = registrations.get("board", "linkedin.com")
    assert record.registered and record.profile_built
    assert "profile built" in record.describe()


def test_not_registered_can_be_recorded(registrations) -> None:
    """Knowing you are NOT registered somewhere is worth recording — it stops
    the question being asked again."""
    registrations.set("board", "monster.co.uk", registered=False)
    record = registrations.get("board", "monster.co.uk")
    assert record is not None and not record.registered


def test_keys_are_case_insensitive(registrations) -> None:
    registrations.set("employer", "Careers.ACME.com")
    assert registrations.get("employer", "careers.acme.com") is not None


def test_updating_preserves_a_known_url(registrations) -> None:
    registrations.set("board", "reed.co.uk", url="https://reed.co.uk/signin")
    registrations.set("board", "reed.co.uk", profile_built=True)
    assert registrations.get("board", "reed.co.uk").url


# --- recurring answers ----------------------------------------------------

def test_an_answer_is_recalled(registrations) -> None:
    registrations.remember_answer("What is your notice period?", "1 month")
    assert registrations.find_answer("What is your notice period?") == "1 month"


def test_rewording_finds_the_same_answer(registrations) -> None:
    """"What is your notice period?" and "Notice period" should not be two
    entries."""
    registrations.remember_answer("What is your notice period?", "1 month")
    assert registrations.find_answer("Notice period") == "1 month"
    assert registrations.find_answer("Please state your notice period") == "1 month"


def test_an_empty_answer_is_not_recorded(registrations) -> None:
    registrations.remember_answer("Question?", "   ")
    assert registrations.answers() == []


def test_answers_are_a_recall_aid_not_a_form_filler(registrations) -> None:
    """Nothing in this module submits anything. The operator types it in."""
    import vanguard.channel as channel

    source = Path(channel.__file__).read_text(encoding="utf-8")
    for forbidden in ("requests.post", "urllib.request.urlopen", "webbrowser",
                      "selenium", "playwright"):
        assert forbidden not in source, f"{forbidden} has no business here"
