"""Mailbox polling — providers, derivation, read-only guarantee."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vanguard.mail import classify
from vanguard.mailbox import (
    GmailProvider,
    ImapProvider,
    MailboxConfig,
    MailboxError,
    build_provider,
    contact_address_from_cv,
    parse_message,
)

ROOT = Path(__file__).parent.parent

DECLINE = b"""From: Recruitment <recruit@justice.gov.uk>
Subject: Senior Data Engineer 19568
Date: Wed, 12 Aug 2026 10:15:00 +0000
Content-Type: text/plain

Thank you for your application. We were very impressed. Unfortunately you
have not been successful on this occasion.
"""


class FakeImap:
    """Stands in for imaplib.IMAP4_SSL. Records what was asked of it."""

    def __init__(self, messages: list[bytes] | None = None) -> None:
        self.messages = messages or [DECLINE]
        self.calls: list[str] = []
        self.readonly: bool | None = None

    def select(self, folder, readonly=True):
        self.calls.append(f"select:{folder}")
        self.readonly = readonly
        return "OK", [b"1"]

    def search(self, charset, criterion):
        self.calls.append(f"search:{criterion}")
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.messages)))]

    def fetch(self, identifier, spec):
        self.calls.append(f"fetch:{identifier.decode()}")
        index = int(identifier) - 1
        return "OK", [(b"1 (RFC822)", self.messages[index])]

    def logout(self):
        self.calls.append("logout")


# --- the address follows the CV -------------------------------------------

def test_address_is_derived_from_the_cv() -> None:
    """An employer replies to whatever address the CV gave them. Configuring
    it separately lets the two drift, and the symptom is replies that never
    correlate."""
    assert "@" in contact_address_from_cv(ROOT / "data" / "canonical_cv.md")


def test_missing_cv_yields_no_address() -> None:
    assert contact_address_from_cv(Path("/nonexistent/cv.md")) == ""


def test_only_the_header_is_scanned(tmp_path: Path) -> None:
    """A referee's address or an employer domain deeper in the CV must not be
    mistaken for the operator's own."""
    cv = tmp_path / "cv.md"
    cv.write_text("# Name\n\nmine@example.com\n" + "\n" * 40 + "referee@elsewhere.com\n")
    assert contact_address_from_cv(cv) == "mine@example.com"


# --- host inference -------------------------------------------------------

@pytest.mark.parametrize(
    "address, host",
    [
        ("x@gmail.com", "imap.gmail.com"),
        ("x@outlook.com", "outlook.office365.com"),
        ("x@yahoo.co.uk", "imap.mail.yahoo.com"),
        ("x@icloud.com", "imap.mail.me.com"),
    ],
)
def test_common_hosts_are_inferred(address: str, host: str, monkeypatch) -> None:
    for name in ("VANGUARD_MAIL_HOST", "VANGUARD_MAIL_USER"):
        monkeypatch.delitem(os.environ, name, raising=False)
    assert MailboxConfig.from_env(address).host == host


def test_unknown_domain_must_be_configured(monkeypatch) -> None:
    for name in ("VANGUARD_MAIL_HOST", "VANGUARD_MAIL_USER"):
        monkeypatch.delitem(os.environ, name, raising=False)
    assert MailboxConfig.from_env("x@company.co.uk").host == ""


# --- configuration --------------------------------------------------------

def test_unconfigured_imap_names_what_is_missing() -> None:
    ok, detail = ImapProvider(MailboxConfig(address="a@b.com")).health_check()
    assert not ok and "password" in detail


def test_unconfigured_gmail_names_what_is_missing() -> None:
    ok, detail = GmailProvider(
        MailboxConfig(address="a@b.com", provider="gmail")).health_check()
    assert not ok and "token" in detail.lower()


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(MailboxError, match="unknown mail provider"):
        build_provider(MailboxConfig(address="a@b.com", provider="carrier-pigeon"))


def test_both_providers_are_available() -> None:
    """Several CVs use several addresses across providers, so one is not
    enough."""
    assert isinstance(build_provider(MailboxConfig(address="a@b.com",
                                                   provider="imap")), ImapProvider)
    assert isinstance(build_provider(MailboxConfig(address="a@b.com",
                                                   provider="gmail")), GmailProvider)


# --- read-only ------------------------------------------------------------

def test_mailbox_is_opened_read_only_by_default() -> None:
    """A tool that mutates the operator's mailbox without being asked is a
    tool that loses trust."""
    fake = FakeImap()
    ImapProvider(MailboxConfig(address="a@b.com", host="h", username="u",
                               password="p"), connection=fake).fetch()
    assert fake.readonly is True


def test_mark_seen_is_opt_in() -> None:
    fake = FakeImap()
    ImapProvider(MailboxConfig(address="a@b.com", host="h", username="u",
                               password="p", mark_seen=True),
                 connection=fake).fetch()
    assert fake.readonly is False


def test_nothing_is_deleted_or_sent() -> None:
    fake = FakeImap()
    ImapProvider(MailboxConfig(address="a@b.com", host="h", username="u",
                               password="p"), connection=fake).fetch()
    assert not any(c.startswith(("store", "delete", "append", "expunge"))
                   for c in fake.calls)


# --- fetching -------------------------------------------------------------

def test_messages_are_fetched_and_parsed() -> None:
    fake = FakeImap()
    messages = ImapProvider(MailboxConfig(address="a@b.com", host="h",
                                          username="u", password="p"),
                            connection=fake).fetch()
    assert len(messages) == 1
    assert messages[0].sender == "recruit@justice.gov.uk"
    assert "19568" in messages[0].subject


def test_fetched_messages_classify() -> None:
    """The point of polling: a real reply reaching the classifier."""
    fake = FakeImap()
    message = ImapProvider(MailboxConfig(address="a@b.com", host="h",
                                         username="u", password="p"),
                           connection=fake).fetch()[0]
    from vanguard.mail import State

    assert classify(message).state is State.DECLINE


def test_since_is_applied_to_the_search() -> None:
    fake = FakeImap()
    ImapProvider(MailboxConfig(address="a@b.com", host="h", username="u",
                               password="p"), connection=fake).fetch(
        since=datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert any("01-Aug-2026" in c for c in fake.calls)


def test_limit_is_respected() -> None:
    fake = FakeImap([DECLINE] * 10)
    messages = ImapProvider(MailboxConfig(address="a@b.com", host="h",
                                          username="u", password="p"),
                            connection=fake).fetch(limit=3)
    assert len(messages) == 3


# --- parsing --------------------------------------------------------------

def test_malformed_mail_is_skipped_not_fatal() -> None:
    assert parse_message(b"\xff\xfe not a message") is None


def test_empty_body_is_skipped() -> None:
    assert parse_message(b"From: a@b.com\nSubject: x\n\n") is None


def test_multipart_prefers_plain_text() -> None:
    raw = (b"From: a@b.com\nSubject: x\n"
           b'Content-Type: multipart/alternative; boundary="B"\n\n'
           b"--B\nContent-Type: text/plain\n\nplain version\n"
           b"--B\nContent-Type: text/html\n\n<p>html version</p>\n--B--\n")
    parsed = parse_message(raw)
    assert parsed is not None and "plain version" in parsed.body


def test_html_only_mail_is_flattened() -> None:
    raw = (b"From: a@b.com\nSubject: x\nContent-Type: text/html\n\n"
           b"<p>You have not been successful.</p>")
    parsed = parse_message(raw)
    assert parsed is not None and "not been successful" in parsed.body


def test_date_header_is_used() -> None:
    parsed = parse_message(DECLINE)
    assert parsed is not None and parsed.received.year == 2026
