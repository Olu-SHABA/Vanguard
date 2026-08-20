"""
Mailbox polling — Route 5 ingress.

`vanguard mail` reads one message from a file. This connects to a mailbox and
fetches them.

## Two providers, one interface

The operator maintains several CVs with different contact addresses, so the
system must handle several mailboxes across different providers. `MailProvider`
is the seam; `ImapProvider` and `GmailProvider` implement it.

    IMAP     any provider, app password in .env. Simplest
    Gmail    OAuth, no stored password. Needs a Google Cloud project

## The address follows the CV

An employer replies to whatever address the CV gave them. Configuring the
monitored address separately lets the two drift, so it is DERIVED from the CV
in use and only overridden deliberately.

## Read-only by default

The pipeline never sends, never replies, never deletes. It marks messages seen
only when told to, and even that is optional — a mailbox is the operator's,
and a tool that mutates it without being asked is a tool that loses trust.

## Credentials

From the environment, never from a tracked file. Same rule as the boards.

    VANGUARD_MAIL_HOST      imap.gmail.com
    VANGUARD_MAIL_USER      olushaba79@gmail.com
    VANGUARD_MAIL_PASSWORD  app password, not the account password
    VANGUARD_GMAIL_TOKEN    path to an OAuth token file
"""

from __future__ import annotations

import email
import email.policy
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Sequence

from vanguard.mail import Message

__all__ = [
    "FetchStrategy",
    "choose_strategy",
    "MailboxError",
    "MailboxConfig",
    "MailProvider",
    "ImapProvider",
    "GmailProvider",
    "build_provider",
    "contact_address_from_cv",
]


class MailboxError(RuntimeError):
    """The mailbox could not be reached or read."""


class FetchStrategy(str, Enum):
    """How to narrow the mailbox before correlating.

    **TARGETED** searches for the employers and references of open
    applications. Precise while there are few of them: most of the inbox is
    irrelevant and the query removes it.

    **WINDOW** fetches everything in the date range and correlates in memory.
    The query is fixed length — `after:date category:primary` — so it is
    immune to the limits targeted search runs into: IMAP command length,
    Gmail's own query limits, and the diminishing return of filtering when
    almost everything in the window is already relevant.

    The trade inverts with volume. At 7 applications a search is a real
    filter; at 500 it is a thousand-term query that narrows almost nothing.
    """

    TARGETED = "targeted"
    WINDOW = "window"
    AUTO = "auto"


#: Open applications at which AUTO switches to WINDOW.
#:
#: **ESTIMATE, not measured.** Reasoning: 40 applications is roughly 80 search
#: terms, still a comfortably short query. What the number should be depends
#: on how much non-application mail arrives in the monitored tab, which is
#: unknown until the system has run at volume. Revisit with real data.
DEFAULT_WINDOW_THRESHOLD = 40


def choose_strategy(requested: FetchStrategy, open_applications: int,
                    threshold: int = DEFAULT_WINDOW_THRESHOLD
                    ) -> tuple[FetchStrategy, str]:
    """Resolve AUTO, and say why. Returns (strategy, reason).

    The reason is reported on every run. Without it a silent switch would be
    invisible, and a change in behaviour with no stated cause is the failure
    mode this project keeps finding.
    """
    if requested is FetchStrategy.TARGETED:
        return FetchStrategy.TARGETED, "forced by --strategy"
    if requested is FetchStrategy.WINDOW:
        return FetchStrategy.WINDOW, "forced by --strategy"

    if open_applications >= threshold:
        return FetchStrategy.WINDOW, (
            f"{open_applications} open applications at or above the "
            f"threshold of {threshold} — a search would be long and would "
            "narrow little"
        )
    return FetchStrategy.TARGETED, (
        f"{open_applications} open application(s), below the threshold of "
        f"{threshold}"
    )


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def contact_address_from_cv(cv_path: Path | str) -> str:
    """The address employers will reply to, read from the CV in use.

    Derived rather than configured. A separately-configured address drifts
    from the CV, and the first symptom is replies that never correlate.
    """
    path = Path(cv_path)
    if not path.is_file():
        return ""
    # The contact line is in the header; do not scan the whole document, or a
    # referee's address or an employer's domain could be picked up.
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20])
    match = _EMAIL.search(head)
    return match.group(0) if match else ""


@dataclass
class MailboxConfig:
    """One mailbox. Several may be configured — one per CV in use."""

    address: str
    provider: str = "imap"            # imap | gmail
    host: str = ""
    port: int = 993
    folder: str = "INBOX"
    username: str = ""
    password: str = ""
    token_path: str = ""
    since_days: int = 30
    mark_seen: bool = False
    label: str = ""                   # which CV this address belongs to
    category: str = "primary"         # gmail tab: primary | all
    search: str = ""                  # extra Gmail search terms

    @property
    def configured(self) -> bool:
        if self.provider == "gmail":
            return bool(self.token_path)
        return bool(self.host and self.username and self.password)

    @property
    def missing(self) -> list[str]:
        if self.provider == "gmail":
            return [] if self.token_path else ["token_path"]
        return [name for name, value in
                (("host", self.host), ("username", self.username),
                 ("password", self.password)) if not value]

    @classmethod
    def from_env(cls, address: str = "", *, provider: str = "imap",
                 prefix: str = "VANGUARD_MAIL") -> MailboxConfig:
        """Read one mailbox from the environment.

        `prefix` allows several mailboxes: VANGUARD_MAIL_*, VANGUARD_MAIL2_*.
        """
        def get(name: str, default: str = "") -> str:
            return os.environ.get(f"{prefix}_{name}", default).strip()

        username = get("USER") or address
        host = get("HOST") or _default_host(username)
        return cls(
            category=(get("CATEGORY", "primary") or "primary").lower(),
            search=get("SEARCH"),
            address=address or username,
            provider=(get("PROVIDER") or provider).lower(),
            host=host,
            port=int(get("PORT", "993") or 993),
            folder=get("FOLDER", "INBOX") or "INBOX",
            username=username,
            password=get("PASSWORD"),
            token_path=get("TOKEN"),
            since_days=int(get("SINCE_DAYS", "30") or 30),
            mark_seen=get("MARK_SEEN", "").lower() in ("1", "true", "yes"),
        )


_KNOWN_HOSTS = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "yahoo.co.uk": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
    "aol.com": "imap.aol.com",
}


def _default_host(address: str) -> str:
    """Infer the IMAP host from the address. Saves configuring the obvious."""
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    return _KNOWN_HOSTS.get(domain, "")


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class MailProvider(ABC):
    """A mailbox Vanguard can read. Read-only unless told otherwise."""

    def __init__(self, config: MailboxConfig) -> None:
        self.config = config

    @abstractmethod
    def fetch(self, *, since: datetime | None = None, limit: int = 100,
              extra_terms: Sequence[str] = ()) -> list[Message]:
        """Messages received since `since`. Never sends, replies or deletes.

        `extra_terms` narrows the search where the provider supports it —
        searching for known employers and references is more reliable than
        reading the most recent N and correlating afterwards.
        """

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Can this mailbox be reached with the credentials given?"""

    def default_since(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=self.config.since_days)


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------

class ImapProvider(MailProvider):
    """Any IMAP mailbox. An app password, never the account password.

    Gmail and most providers refuse plain account passwords over IMAP once
    two-factor authentication is on, and an app password can be revoked
    without changing the account.
    """

    def __init__(self, config: MailboxConfig, connection=None) -> None:
        super().__init__(config)
        self._connection = connection      # injected in tests

    def _connect(self):
        if self._connection is not None:
            return self._connection
        if not self.config.configured:
            raise MailboxError(
                f"mailbox {self.config.address or '(unset)'} is not configured: "
                f"missing {', '.join(self.config.missing)}. Set VANGUARD_MAIL_* "
                "in .env — an app password, not the account password"
            )
        try:
            import imaplib
        except ImportError as exc:  # pragma: no cover
            raise MailboxError("imaplib unavailable") from exc

        try:
            connection = imaplib.IMAP4_SSL(self.config.host, self.config.port)
            connection.login(self.config.username, self.config.password)
        except Exception as exc:
            raise MailboxError(
                f"could not connect to {self.config.host}: {exc}"
            ) from exc
        self._connection = connection
        return connection

    def _gmail_query(self, since: datetime) -> str | None:
        """Gmail search terms, or None when this is not a Gmail mailbox.

        Gmail's Primary / Promotions / Social tabs are NOT IMAP folders —
        `INBOX` returns all of them. A recent-N fetch is therefore dominated
        by promotional mail, and a genuine employer reply can fall outside
        the window entirely. Gmail exposes the tabs to IMAP through
        `X-GM-RAW`, which accepts its own search syntax.
        """
        if "gmail" not in (self.config.host or "").lower():
            return None

        terms = [f"after:{since.strftime('%Y/%m/%d')}"]
        if self.config.category and self.config.category != "all":
            terms.append(f"category:{self.config.category}")
        if self.config.search:
            terms.append(self.config.search)
        return " ".join(terms)

    @staticmethod
    def _gmail_search(connection, query: str):
        """Issue X-GM-RAW with the query as an IMAP literal.

        The query contains double quotes around multi-word employer names, so
        wrapping the whole thing in quotes again produces nested quotes and
        `BAD Could not parse command`. A literal carries a byte count and
        needs no quoting at all.
        """
        encoded = query.encode("utf-8")
        literal = f"{{{len(encoded)}}}".encode()
        tag = connection._new_tag()
        connection.send(b"%s SEARCH X-GM-RAW %s\r\n" % (tag, literal))

        # The server replies with a continuation before accepting the payload.
        while True:
            line = connection._get_line()
            if line.startswith(b"+"):
                break
            if line.startswith(tag):
                return "NO", None

        connection.send(encoded + b"\r\n")
        typ, data = connection._command_complete("SEARCH", tag)
        return connection._untagged_response(typ, data, "SEARCH")

    def fetch(self, *, since: datetime | None = None,
              limit: int = 100, extra_terms: Sequence[str] = ()) -> list[Message]:
        connection = self._connect()
        since = since or self.default_since()

        try:
            connection.select(self.config.folder, readonly=not self.config.mark_seen)

            gmail_query = self._gmail_query(since)
            status, data = "NO", None

            if gmail_query:
                if extra_terms:
                    gmail_query = f"{gmail_query} {{{' '.join(extra_terms)}}}"
                try:
                    status, data = self._gmail_search(connection, gmail_query)
                except Exception:
                    status = "NO"
                if status != "OK":
                    # Not every Gmail-hosted account accepts X-GM-RAW, and a
                    # malformed query must degrade to reading the window
                    # rather than returning nothing.
                    gmail_query = None

            if status != "OK":
                criterion = f'(SINCE "{since.strftime("%d-%b-%Y")}")'
                status, data = connection.search(None, criterion)

            if status != "OK":
                raise MailboxError(f"search failed on {self.config.folder}")

            identifiers = (data[0].split() if data and data[0] else [])[-limit:]
            out: list[Message] = []
            for identifier in identifiers:
                status, payload = connection.fetch(identifier, "(RFC822)")
                if status != "OK" or not payload:
                    continue
                raw = next((part[1] for part in payload
                            if isinstance(part, tuple) and len(part) > 1), None)
                if raw is None:
                    continue
                parsed = parse_message(raw)
                if parsed is not None:
                    out.append(parsed)
            return out
        except MailboxError:
            raise
        except Exception as exc:
            raise MailboxError(f"reading {self.config.folder} failed: {exc}") from exc

    def health_check(self) -> tuple[bool, str]:
        if not self.config.configured:
            return False, f"not configured: missing {', '.join(self.config.missing)}"
        try:
            self._connect()
        except MailboxError as exc:
            return False, str(exc)
        return True, f"connected to {self.config.host} as {self.config.username}"

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.logout()
            except Exception:
                pass
            self._connection = None


# ---------------------------------------------------------------------------
# Gmail API
# ---------------------------------------------------------------------------

class GmailProvider(MailProvider):
    """Gmail via OAuth. No stored password, at the cost of setup.

    Requires a Google Cloud project with the Gmail API enabled and an OAuth
    client. Scope is `gmail.readonly` — the pipeline cannot send or delete
    even if something later asks it to.
    """

    SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)

    def __init__(self, config: MailboxConfig, service=None) -> None:
        super().__init__(config)
        self._service = service

    def _build(self):
        if self._service is not None:
            return self._service
        if not self.config.token_path:
            raise MailboxError(
                "gmail provider needs VANGUARD_MAIL_TOKEN — a path to an OAuth "
                "token file. See COMMANDS.md for the setup"
            )
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise MailboxError(
                "gmail provider requires google-api-python-client and "
                "google-auth: pip install -e \".[gmail]\""
            ) from exc

        token = Path(self.config.token_path)
        if not token.is_file():
            raise MailboxError(f"OAuth token not found at {token}")

        try:
            credentials = Credentials.from_authorized_user_file(
                str(token), list(self.SCOPES))
            self._service = build("gmail", "v1", credentials=credentials,
                                  cache_discovery=False)
        except Exception as exc:
            raise MailboxError(f"gmail authentication failed: {exc}") from exc
        return self._service

    def fetch(self, *, since: datetime | None = None, limit: int = 100,
              extra_terms: Sequence[str] = ()) -> list[Message]:
        import base64

        service = self._build()
        since = since or self.default_since()

        terms = [f"after:{since.strftime('%Y/%m/%d')}"]
        if self.config.category and self.config.category != "all":
            terms.append(f"category:{self.config.category}")
        if self.config.search:
            terms.append(self.config.search)
        if extra_terms:
            terms.append("{" + " ".join(extra_terms) + "}")
        query = " ".join(terms)

        try:
            listing = service.users().messages().list(
                userId="me", q=query, maxResults=limit).execute()
            out: list[Message] = []
            for stub in listing.get("messages", []):
                payload = service.users().messages().get(
                    userId="me", id=stub["id"], format="raw").execute()
                raw = base64.urlsafe_b64decode(payload["raw"])
                parsed = parse_message(raw)
                if parsed is not None:
                    out.append(parsed)
            return out
        except MailboxError:
            raise
        except Exception as exc:
            raise MailboxError(f"gmail fetch failed: {exc}") from exc

    def health_check(self) -> tuple[bool, str]:
        if not self.config.token_path:
            return False, "not configured: missing token_path"
        try:
            service = self._build()
            profile = service.users().getProfile(userId="me").execute()
        except MailboxError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"gmail unreachable: {exc}"
        return True, f"connected as {profile.get('emailAddress', 'unknown')}"


# ---------------------------------------------------------------------------

def build_provider(config: MailboxConfig, **kwargs) -> MailProvider:
    providers = {"imap": ImapProvider, "gmail": GmailProvider}
    if config.provider not in providers:
        raise MailboxError(
            f"unknown mail provider {config.provider!r}; expected "
            f"{' or '.join(sorted(providers))}"
        )
    return providers[config.provider](config, **kwargs)


def parse_message(raw: bytes) -> Message | None:
    """RFC822 bytes to a Message. Malformed mail is skipped, never fatal."""
    try:
        parsed = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return None

    body = _body_of(parsed)
    if not body.strip():
        return None

    # `message_from_bytes` is tolerant: arbitrary bytes parse into a message
    # with a body and no headers. Such a thing cannot correlate to an
    # application and should not enter the pipeline pretending to be mail.
    if not (parsed.get("From") or parsed.get("Message-ID") or parsed.get("Subject")):
        return None

    received = datetime.now(timezone.utc)
    date_header = parsed.get("Date")
    if date_header:
        try:
            received = email.utils.parsedate_to_datetime(date_header)
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    sender = str(parsed.get("From", ""))
    address = _EMAIL.search(sender)

    return Message(
        message_id=str(parsed.get("Message-ID", "")) or f"<{id(parsed)}>",
        sender=address.group(0) if address else sender,
        subject=str(parsed.get("Subject", "")),
        body=body,
        received=received,
        # Threading. A reply to a message already correlated is the strongest
        # signal available, and it costs two headers to keep.
        in_reply_to=str(parsed.get("In-Reply-To", "")),
        references=str(parsed.get("References", "")),
        # Carries a per-application identifier on ATS mail.
        reply_to=str(parsed.get("Reply-To", "")),
    )


def _body_of(parsed) -> str:
    """Plain text preferred; HTML flattened when that is all there is."""
    if parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_content()
                except Exception:
                    continue
        for part in parsed.walk():
            if part.get_content_type() == "text/html":
                try:
                    from vanguard.extract import html_to_text
                    return html_to_text(part.get_content())
                except Exception:
                    continue
        return ""

    try:
        content = parsed.get_content()
    except Exception:
        return ""
    if parsed.get_content_type() == "text/html":
        from vanguard.extract import html_to_text
        return html_to_text(content)
    return content
