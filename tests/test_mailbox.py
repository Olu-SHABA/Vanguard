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


# ---------------------------------------------------------------------------
# Gmail search — X-GM-RAW must be sent as a literal
#
# Observed 12 Aug 2026: the query contains double quotes around multi-word
# employer names. Wrapping it in quotes again produced nested quotes and
# `BAD Could not parse command`, so the poll returned nothing at all.
# ---------------------------------------------------------------------------

class FakeGmailConn:
    """Records the raw bytes sent, so the wire format can be asserted."""

    def __init__(self, accept_literal: bool = True,
                 messages: list[bytes] | None = None) -> None:
        self.accept_literal = accept_literal
        self.messages = messages or [DECLINE]
        self.sent: list[bytes] = []
        self.plain_searches: list[str] = []
        self._tag = 0

    def _new_tag(self):
        self._tag += 1
        return f"AAAA{self._tag}".encode()

    def send(self, payload):
        self.sent.append(payload)

    def _get_line(self):
        return b"+ ready" if self.accept_literal else b"AAAA1 BAD nope"

    def _command_complete(self, command, tag):
        return "OK", [b"1"]

    def _untagged_response(self, typ, data, name):
        return typ, data

    def select(self, folder, readonly=True):
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.plain_searches.append(" ".join(str(c) for c in criteria))
        return "OK", [b"1"]

    def fetch(self, identifier, spec):
        return "OK", [(b"1 (RFC822)", self.messages[0])]

    def logout(self):
        pass


def gmail_config(**overrides) -> MailboxConfig:
    return MailboxConfig(**{
        "address": "x@gmail.com", "host": "imap.gmail.com",
        "username": "u", "password": "p", **overrides,
    })


def test_gmail_query_restricts_to_primary() -> None:
    """Primary is not an IMAP folder. INBOX returns promotions and social too,
    so a recent-N fetch can miss a genuine reply entirely."""
    query = ImapProvider(gmail_config())._gmail_query(
        datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert "category:primary" in query and "after:2026/07/15" in query


def test_category_all_reads_everything() -> None:
    query = ImapProvider(gmail_config(category="all"))._gmail_query(
        datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert "category:" not in query


def test_non_gmail_host_uses_plain_imap() -> None:
    assert ImapProvider(gmail_config(host="outlook.office365.com"))._gmail_query(
        datetime(2026, 7, 15, tzinfo=timezone.utc)) is None


def test_search_is_sent_as_a_literal_not_a_quoted_string() -> None:
    """A quoted string containing quotes is unparseable. A literal carries a
    byte count and needs no quoting."""
    connection = FakeGmailConn()
    ImapProvider(gmail_config(), connection=connection).fetch(
        extra_terms=['"19568"', '"Ministry of Justice"'])

    wire = b"".join(connection.sent).decode()
    assert "X-GM-RAW {" in wire, "query must be sent as a literal"
    assert 'X-GM-RAW "' not in wire, "a quoted string would nest quotes"
    assert "Ministry of Justice" in wire


def test_literal_byte_count_matches_the_query() -> None:
    connection = FakeGmailConn()
    ImapProvider(gmail_config(), connection=connection).fetch(
        extra_terms=['"Beatport"'])

    wire = b"".join(connection.sent).decode()
    declared = int(wire.split("{")[1].split("}")[0])
    payload = wire.split("\r\n", 1)[1].rstrip("\r\n")
    assert declared == len(payload.encode("utf-8"))


def test_refused_literal_falls_back_to_a_plain_search() -> None:
    """Not every Gmail-hosted account accepts X-GM-RAW. Returning nothing
    would be worse than reading the window."""
    connection = FakeGmailConn(accept_literal=False)
    messages = ImapProvider(gmail_config(), connection=connection).fetch(
        extra_terms=['"x"'])

    assert connection.plain_searches, "must fall back to SINCE"
    assert messages, "and still return what it found"


def test_extra_terms_are_grouped_as_an_or() -> None:
    """Gmail treats {a b} as OR. Without the braces a message would have to
    mention every employer at once."""
    connection = FakeGmailConn()
    ImapProvider(gmail_config(), connection=connection).fetch(
        extra_terms=['"A"', '"B"'])

    wire = b"".join(connection.sent).decode()
    assert '{"A" "B"}' in wire
