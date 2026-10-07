"""Unread mail count over IMAP. Read-only: EXAMINE, STATUS and a header-only PEEK; mail is never marked as read.

Accounts: plain IMAP (password) or Google / Microsoft over IMAP with the XOAUTH2 SASL mechanism (see keeper/oauth.py).
"""
from __future__ import annotations

import email.parser
import email.policy
import imaplib
import re
import socket
import ssl


class MailError(Exception):
    """The message is always one of REASONS, so it never carries credentials or server text."""
    REASONS = ("authentication failed", "cannot connect", "timeout", "protocol error",
               "authorization expired (reconnect)", "not signed in")

    def __init__(self, reason):
        super().__init__(reason if reason in self.REASONS else "protocol error")


PROVIDERS = ("imap", "google", "microsoft")
DEFAULT_HOSTS = {"google": "imap.gmail.com", "microsoft": "outlook.office365.com"}
# An OAuth bearer token is only sent to these hosts unless the account sets allow_custom_host.
PINNED_HOSTS = {"google": {"imap.gmail.com"}, "microsoft": {"outlook.office365.com", "outlook.office.com"}}
MAX_ACCOUNTS = 10
LEGACY_KEYS = ("host", "port", "user", "password", "mailbox", "show_subject")
ACCOUNT_DEFAULTS = {"id": "", "name": "", "provider": "imap", "enabled": True, "host": "", "port": 993, "user": "", "password": "",
                    "mailbox": "INBOX", "show_subject": False, "client_id": "", "client_secret": "", "tenant": "common",
                    "refresh_token": "", "redirect_uri": "", "allow_custom_host": False}


def new_account(**values):
    """A fresh account dict with a short random id."""
    import uuid
    return {**ACCOUNT_DEFAULTS, "id": uuid.uuid4().hex[:8], **values}


def migrate_conf(conf):
    """integrations.mail in the current shape {enabled, accounts: [...]}; the old flat keys become accounts[0]
    (id "main", enabled carried over) and are dropped. Pure: never mutates `conf`; anything that is not a dict passes through."""
    if not isinstance(conf, dict):
        return conf
    legacy = {k: conf[k] for k in LEGACY_KEYS if k in conf}
    accounts = conf.get("accounts")
    if accounts is None:
        accounts = []
        if any(legacy.get(k) for k in ("host", "user", "password")):
            user = legacy.get("user") if isinstance(legacy.get("user"), str) else ""
            accounts = [{**ACCOUNT_DEFAULTS, **legacy, "id": "main", "name": user[:40] or "Mail", "provider": "imap",
                         "enabled": conf.get("enabled", False)}]
    elif isinstance(accounts, list):
        accounts = [{**ACCOUNT_DEFAULTS, **a} if isinstance(a, dict) else a for a in accounts]
    return {**{k: v for k, v in conf.items() if k not in LEGACY_KEYS}, "accounts": accounts}


def _connect(host, port, timeout, context):
    if port == 143:
        return imaplib.IMAP4(host, port, timeout=timeout)
    return imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=timeout)


def _clean(text, limit=80):
    return "".join(c if c.isprintable() else " " for c in str(text)).strip()[:limit]


def _quote(mailbox):
    if not mailbox.isascii() or not mailbox.isprintable():
        raise MailError("protocol error")
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _subject(connection, message_id):
    status, data = connection.fetch(message_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
    if status != "OK":
        raise MailError("protocol error")
    for part in data:
        if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], (bytes, bytearray)):
            try:
                value = email.parser.BytesHeaderParser(policy=email.policy.default).parsebytes(bytes(part[1])[:4096]).get("Subject", "")
                return _clean(value) or None
            except Exception:
                return None
    return None


def host_allowed(conf):
    """False when an OAuth account points at a host outside its provider's pinned set without allow_custom_host."""
    pinned = PINNED_HOSTS.get(conf.get("provider", "imap"))
    host = conf.get("host") or DEFAULT_HOSTS.get(conf.get("provider", ""), "")
    return pinned is None or conf.get("allow_custom_host") is True or str(host).strip().lower() in pinned


def xoauth2(user, token):
    if "\x01" in user:
        raise MailError("protocol error")
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def fetch_unread(conf, timeout=10, connector=_connect, token_provider=None):
    """Return {"unread": int, "subject": str | None} for one account dict.

    `connector(host, port, timeout, ssl_context)` is injectable for tests. Google/Microsoft accounts authenticate with
    XOAUTH2 using `token_provider()` (a fresh access token, or it raises MailError); the password is never used for them."""
    provider = conf.get("provider", "imap")
    oauth = provider in DEFAULT_HOSTS
    host = conf.get("host") or DEFAULT_HOSTS.get(provider, "")
    user, password = conf.get("user", ""), conf.get("password", "")
    if not host or not user or (not oauth and not password):
        raise MailError("authentication failed")
    port = int(conf.get("port") or 993)
    if oauth and not host_allowed(conf):
        raise MailError("protocol error")  # never send the bearer token to an unexpected server
    if oauth and (port == 143 or token_provider is None):
        raise MailError("protocol error" if token_provider else "not signed in")  # a bearer token never travels in clear text
    connection = None
    stage = "connect"
    try:
        context = ssl.create_default_context()
        if oauth:
            token = token_provider()  # may raise MailError ("not signed in", "authorization expired (reconnect)", ...)
        connection = connector(host, port, timeout, context)
        if port == 143:
            # The password is only sent after STARTTLS succeeded.
            connection.starttls(ssl_context=context)
        stage = "login"
        if oauth:
            connection.authenticate("XOAUTH2", lambda _: xoauth2(user, token))
        else:
            connection.login(user, password)
        stage = "query"
        mailbox = _quote(conf.get("mailbox") or "INBOX")
        status, _ = connection.select(mailbox, readonly=True)  # sends EXAMINE
        if status != "OK":
            raise MailError("protocol error")
        status, data = connection.status(mailbox, "(UNSEEN)")
        match = re.search(rb"UNSEEN\s+(\d+)", b" ".join(x for x in data if isinstance(x, bytes))) if status == "OK" else None
        if not match:
            raise MailError("protocol error")
        unread = int(match.group(1))
        subject = None
        if unread and conf.get("show_subject"):
            status, data = connection.search(None, "UNSEEN")
            ids = data[0].split() if status == "OK" and data and isinstance(data[0], bytes) else []
            if ids:
                subject = _subject(connection, ids[-1])
        return {"unread": unread, "subject": subject}
    except MailError:
        raise
    except (socket.timeout, TimeoutError):
        raise MailError("timeout") from None
    except imaplib.IMAP4.error:
        if oauth and stage == "login" and hasattr(token_provider, "invalidate"):
            token_provider.invalidate()  # the server refused the token: fetch a new one on the next sample
        raise MailError("authentication failed" if stage == "login" else "protocol error") from None
    except OSError:
        raise MailError("cannot connect") from None
    except Exception:
        raise MailError("protocol error") from None
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass
