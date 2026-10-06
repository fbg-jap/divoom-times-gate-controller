"""Unread mail count over IMAP. Read-only: EXAMINE, STATUS and a header-only PEEK; mail is never marked as read."""
from __future__ import annotations

import email.parser
import email.policy
import imaplib
import re
import socket
import ssl


class MailError(Exception):
    """The message is always one of REASONS, so it never carries credentials or server text."""
    REASONS = ("authentication failed", "cannot connect", "timeout", "protocol error")

    def __init__(self, reason):
        super().__init__(reason if reason in self.REASONS else "protocol error")


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


def fetch_unread(conf, timeout=10, connector=_connect):
    """Return {"unread": int, "subject": str | None}. `connector(host, port, timeout, ssl_context)` is injectable for tests."""
    host, user, password = conf.get("host", ""), conf.get("user", ""), conf.get("password", "")
    if not host or not user or not password:
        raise MailError("authentication failed")
    port = int(conf.get("port", 993))
    connection = None
    stage = "connect"
    try:
        context = ssl.create_default_context()
        connection = connector(host, port, timeout, context)
        if port == 143:
            # The password is only sent after STARTTLS succeeded.
            connection.starttls(ssl_context=context)
        stage = "login"
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
