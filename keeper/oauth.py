"""OAuth 2.0 sign-in for the Unread mail widget: Google (Gmail / Workspace) and Microsoft (Outlook / Microsoft 365),
Authorization Code with PKCE, tokens used over IMAP with the XOAUTH2 SASL mechanism. The user registers their OWN app.

Checked against the official docs on 2026-10-06:
  VERIFIED  Google authorize https://accounts.google.com/o/oauth2/v2/auth, token https://oauth2.googleapis.com/token
            (developers.google.com/identity/protocols/oauth2/native-app). PKCE code_verifier 43-128 chars, S256 supported.
            Loopback redirect http://127.0.0.1:PORT (or [::1]) for desktop apps. access_type=offline asks for a refresh
            token; prompt accepts none|consent|select_account (consent re-shows the consent screen).
            Refresh responses normally carry no new refresh token (the first one stays valid).
  VERIFIED  Google refresh tokens: a project whose consent screen is External with publishing status "Testing" gets refresh
            tokens that expire after 7 days (unless only name/email/profile scopes are used); also invalid_grant when the
            user revokes access, the token is unused for 6 months, the password of a Gmail-scope token changes, or the
            account exceeds the live-token limit.
  VERIFIED  Google IMAP XOAUTH2: base64("user=" + user + "\\x01auth=Bearer " + token + "\\x01\\x01"), scope
            https://mail.google.com/ (developers.google.com/workspace/gmail/imap/xoauth2-protocol).
  RECALLED  Google Desktop-type clients must send client_secret at the token endpoint although the docs list it as
            optional ("not applicable to Android/iOS/Chrome clients"); Google does not treat it as confidential for
            installed apps. Requests here send it whenever one is configured.
  VERIFIED  Microsoft authorize/token https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize|token, tenant is
            common | organizations | consumers | a tenant id/domain (learn.microsoft.com ... v2-oauth2-auth-code-flow).
            Public clients (native apps) must NOT send a client secret; PKCE (code_challenge/S256) is used.
            Refresh responses carry a NEW refresh_token when offline_access was requested: replace the old one.
  VERIFIED  Microsoft IMAP scope https://outlook.office.com/IMAP.AccessAsUser.All (+ offline_access for a refresh token);
            same XOAUTH2 string; host outlook.office365.com:993 (learn.microsoft.com ... authenticate-an-imap-pop-smtp-
            application-by-using-oauth). Admin consent may be required for work/school accounts.
  VERIFIED  Microsoft redirect URIs: https, or http for localhost; the port is ignored when matching localhost URIs; the
            IPv6 loopback [::1] is not supported; 127.0.0.1 is preferred but an http 127.0.0.1 URI can only be added through
            the application manifest, not the portal text box; https://login.microsoftonline.com/common/oauth2/nativeclient
            is the recommended value for apps with an embedded browser (used here with the paste-back flow).
  RECALLED  Microsoft: invalid_grant on refresh means the token was revoked/expired/consent withdrawn (reconnect);
            Exchange Online must have IMAP enabled for the mailbox. Microsoft personal accounts (outlook.com) work with
            tenant "common" or "consumers".
No real Google or Microsoft account has been used; the code is exercised with fake sessions and servers only.
"""
from __future__ import annotations

import hmac
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .mail import MailError
from . import spotify
from .spotify import make_pkce_pair, redact

TIMEOUT = 8
TRANSIENT_BACKOFF = 60
PASTE_LIMIT = 2048
TENANT = re.compile(r"(?!\.)[A-Za-z0-9.-]{1,64}")
PROVIDERS = {
    "google": {"authorize": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
               "scope": "https://mail.google.com/", "authorize_extra": {"access_type": "offline", "prompt": "consent"}, "secret": True,
               "label": "Google"},
    "microsoft": {"authorize": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
                  "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                  "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access", "authorize_extra": {}, "secret": False,
                  "label": "Microsoft"},
}


class OAuthError(Exception):
    """Messages are short fixed text; they never include codes, tokens, secrets or response bodies."""


class OAuthAuthError(OAuthError):
    """The provider rejected the grant (4xx): the refresh token is dead and only a new sign-in helps."""


class OAuthRateLimited(OAuthError):
    def __init__(self, retry_after):
        super().__init__("rate limited")
        self.retry_after = retry_after


def _provider(provider):
    if provider not in PROVIDERS:
        raise OAuthError("unknown provider")
    return PROVIDERS[provider]


def _url(template, account):
    tenant = account.get("tenant") or "common"
    if not TENANT.fullmatch(tenant):
        raise OAuthError("invalid tenant")
    return template.format(tenant=tenant)


def build_authorize_url(provider, account, redirect_uri, state, challenge):
    spec = _provider(provider)
    return _url(spec["authorize"], account) + "?" + urlencode({
        "client_id": account.get("client_id", ""), "response_type": "code", "redirect_uri": redirect_uri, "scope": spec["scope"],
        "state": state, "code_challenge_method": "S256", "code_challenge": challenge, **spec["authorize_extra"]})


def _retry_after(response):
    try:
        return max(1, min(3600, int(float(response.headers.get("Retry-After", 30)))))
    except (ValueError, TypeError):
        return 30


def _token_request(session, provider, account, payload, secrets_):
    spec = _provider(provider)
    payload = {**payload, "client_id": account.get("client_id", "")}
    if spec["secret"] and account.get("client_secret"):
        payload["client_secret"] = account["client_secret"]
        secrets_ = (*secrets_, account["client_secret"])
    try:
        response = session.post(_url(spec["token"], account), data=payload, timeout=TIMEOUT,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    except requests.RequestException:
        raise OAuthError("cannot reach the provider") from None
    status = response.status_code
    if status == 429:
        raise OAuthRateLimited(_retry_after(response))
    if status >= 500:
        raise OAuthError(f"provider error (HTTP {status})")
    if status != 200:
        code = ""
        try:
            value = response.json().get("error", "")
            code = value if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,40}", value) else ""
        except (ValueError, AttributeError):
            pass
        raise OAuthAuthError(redact(f"token request failed (HTTP {status}{': ' + code if code else ''})", *secrets_))
    try:
        data = response.json()
        token, expires = data["access_token"], int(data.get("expires_in", 3600))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise OAuthError("unexpected token response") from None
    refresh = data.get("refresh_token")
    return {"access_token": token, "expires_in": expires, "refresh_token": refresh if isinstance(refresh, str) and refresh else None}


def exchange_code(session, provider, account, code, verifier, redirect_uri):
    return _token_request(session, provider, account, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                                       "code_verifier": verifier}, (code, verifier))


def refresh_access_token(session, provider, account, refresh_token):
    """(access_token, expires_in, new_refresh_token_or_None). Google keeps the old refresh token; Microsoft rotates it."""
    data = _token_request(session, provider, account, {"grant_type": "refresh_token", "refresh_token": refresh_token}, (refresh_token,))
    return data["access_token"], data["expires_in"], data["refresh_token"]


class MailTokenSource:
    """Callable returning a valid access token (kept in memory only). Passed to keeper.mail.fetch_unread as `token_provider`.

    The refresh token is handed to `on_refresh_token(account_id, new, old)` when the provider rotates it; that callback is
    a compare-and-swap (it persists only if the stored token still equals `old`)."""

    def __init__(self, account, on_refresh_token=None, session=None, clock=time.monotonic):
        self.account = dict(account)
        self.provider, self.account_id = self.account.get("provider", ""), self.account.get("id", "")
        self.refresh_token = self.initial_token = self.account.get("refresh_token", "")
        self.on_refresh_token, self.session, self.clock = on_refresh_token, session or requests.Session(), clock
        self.access_token, self.expires, self.blocked_until = "", 0.0, 0.0
        self.dead = False  # refresh token rejected; only a rebuilt source (new token) clears it, no retry loop

    def invalidate(self):
        self.access_token = ""

    def __call__(self):
        if not self.refresh_token:
            raise MailError("not signed in")
        if self.dead:
            raise MailError("authorization expired (reconnect)")
        now = self.clock()
        if self.access_token and now < self.expires:
            return self.access_token
        if now < self.blocked_until:
            raise MailError("cannot connect")
        try:
            token, expires, rotated = refresh_access_token(self.session, self.provider, self.account, self.refresh_token)
        except OAuthRateLimited as error:
            self.blocked_until = now + error.retry_after
            raise MailError("cannot connect") from None
        except OAuthAuthError:
            self.access_token, self.dead = "", True
            raise MailError("authorization expired (reconnect)") from None
        except OAuthError:
            self.blocked_until = now + TRANSIENT_BACKOFF
            raise MailError("cannot connect") from None
        self.access_token, self.expires = token, now + max(30, expires - 60)
        if rotated and rotated != self.refresh_token:
            old, self.refresh_token = self.refresh_token, rotated
            if self.on_refresh_token:
                self.on_refresh_token(self.account_id, rotated, old)
        return self.access_token


def _need_refresh(data):
    if not data["refresh_token"]:
        raise OAuthError("the provider returned no refresh token")
    return data["refresh_token"]


def finish_manual(session, provider, account, redirect_uri, verifier, state, pasted):
    """Paste-back flow, step 2: the full redirected address (or its `code=...&state=...` query/fragment) -> refresh token."""
    text = str(pasted or "").strip()
    if not text or len(text) > PASTE_LIMIT:
        raise OAuthError("the pasted address is empty or too long")
    if "://" in text:
        parsed = urlparse(text)
        query = parsed.query or parsed.fragment
    else:
        query = text.split("#", 1)[0].split("?", 1)[-1] if "?" in text else text.lstrip("#")
    params = {k: v[0] for k, v in parse_qs(query).items()}
    if params.get("error"):
        raise OAuthError("sign-in was not authorized")
    got = params.get("state", "")
    if not got or not hmac.compare_digest(got.encode(), state.encode()):
        raise OAuthError("the pasted address does not belong to this sign-in attempt; start again")
    code = params.get("code", "")
    if not code:
        raise OAuthError("the pasted address has no authorization code")
    return _need_refresh(exchange_code(session, provider, account, code, verifier, redirect_uri))


class PendingOAuth:
    """Portal: one table of sign-in attempts (Spotify and mail accounts) keyed by single-use `state`, 5 minutes, bounded.

    An entry holds the PKCE verifier and everything the token exchange needs; it never leaves the process. `take` always
    consumes the state, so a callback or a paste-back can complete an attempt at most once."""
    TTL, LIMIT = 300, 20

    def __init__(self, clock=time.monotonic):
        self.clock, self.items, self.lock = clock, {}, threading.Lock()

    def issue(self, service, mode, redirect_uri, account):
        """`account`: for spotify {"client_id"}; for mail the account dict (provider, client_id, client_secret, tenant, id).
        Returns (state, authorize_url)."""
        verifier, challenge = make_pkce_pair()
        state = secrets.token_urlsafe(24)
        if service == "spotify":
            url = spotify.build_authorize_url(account["client_id"], redirect_uri, state, challenge)
        elif service == "mail":
            url = build_authorize_url(account.get("provider", ""), account, redirect_uri, state, challenge)
        else:
            raise OAuthError("unknown service")
        now = self.clock()
        with self.lock:
            self.items = {k: v for k, v in self.items.items() if v["expires"] > now}
            while len(self.items) >= self.LIMIT:
                self.items.pop(next(iter(self.items)))
            self.items[state] = {"service": service, "mode": mode, "redirect_uri": redirect_uri, "account": dict(account),
                                 "verifier": verifier, "expires": now + self.TTL}
        return state, url

    def take(self, state):
        """The entry dict or None; always consumes the state."""
        with self.lock:
            item = self.items.pop(state, None) if isinstance(state, str) else None
        if item is None or item["expires"] <= self.clock():
            return None
        return item
