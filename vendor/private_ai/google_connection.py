"""Built-in Google connector. Fixed destinations, no redirects, no token logging.

Credentials are owned by the encrypted vault, never by the model/tool arguments.
This module does not load third-party plugins or execute model-provided code.
"""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, build_opener, ProxyHandler

from .network import NoRedirect

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REVOKE = "https://oauth2.googleapis.com/revoke"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
FREEBUSY = "https://www.googleapis.com/calendar/v3/freeBusy"
USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
SCOPES = {
    "mail_read": "https://www.googleapis.com/auth/gmail.readonly",
    "calendar_read": "https://www.googleapis.com/auth/calendar.freebusy",
    "mail_send": "https://www.googleapis.com/auth/gmail.send",
}


class ConnectorError(Exception):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


class GoogleTransport:
    def request(self, url, *, token="", data=None, form=False):
        # Callers construct paths; no model-supplied hosts, URLs or credentials.
        if not (url in (TOKEN, REVOKE, FREEBUSY, USERINFO) or url.startswith(GMAIL + "/")):
            raise ConnectorError("Connector destination is not allowed")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        body = None
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
            body = (urlencode(data) if form else json.dumps(data)).encode()
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(Request(url, data=body, headers=headers), timeout=30) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ConnectorError("Google result is too large for this tool. Narrow the request.")
                return json.loads(raw) if raw.strip() else {}
        except HTTPError as error:
            if url == TOKEN and error.code in (400, 401):
                # Inspect only the standard code; never echo provider bodies.
                try:
                    failure = json.loads(error.read(8192)).get("error")
                except (ValueError, OSError, AttributeError):
                    failure = None
                if failure == "invalid_grant":
                    raise ConnectorError("Google sign-in has expired. Choose Reconnect Gmail to continue.", "reauth_required") from None
                if failure in ("invalid_client", "unauthorized_client"):
                    raise ConnectorError("This build's Google app registration needs fixing. Ask the app owner to update it.", "app_setup") from None
            if error.code in (401, 403):
                raise ConnectorError("Google did not allow this request. Check the connected permissions; the app owner may need to enable the Google API.") from None
            raise ConnectorError(f"Google request failed (HTTP {error.code}). It was not retried.") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ConnectorError("Google could not be reached or returned an invalid result. Nothing was retried.") from None


def token_record(value, requested, previous=None):
    if not isinstance(value, dict) or not isinstance(value.get("access_token"), str) or not value["access_token"]:
        raise ConnectorError("Google did not return an access token. Reconnect Google.")
    if value.get("token_type", "").lower() != "bearer":
        raise ConnectorError("Unsupported Google token type")
    scopes = set(value.get("scope", " ".join(requested)).split())
    if not set(requested).issubset(scopes):
        raise ConnectorError("Some requested Google permissions were declined. Reconnect with the required permissions.")
    try:
        lifetime = int(value.get("expires_in", 0))
    except (ValueError, TypeError):
        lifetime = 0
    if lifetime <= 0:
        raise ConnectorError("Google returned an invalid token lifetime")
    refresh = value.get("refresh_token") or (previous or {}).get("refresh_token", "")
    if not isinstance(refresh, str) or not refresh:
        raise ConnectorError("Google did not grant offline access. Reconnect and approve access again.")
    return {"access_token": value["access_token"], "refresh_token": refresh,
            "expires_at": time.time() + lifetime, "scopes": sorted(scopes)}


class OAuthSession:
    """One-use PKCE callback on a temporary loopback port; ten minute lifetime."""
    def __init__(self, config, scopes, transport, finish):
        self.state = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(64)
        self.expires = time.monotonic() + 600
        self.cancelled = threading.Event()
        self.consumed = False
        self.status = "waiting"
        self.error = ""
        owner = self

        class Callback(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                params = parse_qs(parsed.query)
                valid = (self.headers.get("Host") == owner.host and parsed.path == "/oauth/callback"
                         and len(params.get("state", [])) == 1
                         and secrets.compare_digest(params["state"][0], owner.state)
                         and not owner.cancelled.is_set() and time.monotonic() < owner.expires
                         and not owner.consumed)
                if not valid:
                    self.respond(400, "This sign-in link is invalid or expired. Return to Airlock Chat and reconnect.")
                    return
                owner.consumed = True
                try:
                    if "error" in params or len(params.get("code", [])) != 1:
                        raise ConnectorError("Google sign-in was cancelled or did not return an authorization code.")
                    raw = transport.request(TOKEN, form=True, data={
                        "client_id": config["client_id"], "client_secret": config["client_secret"],
                        "code": params["code"][0], "code_verifier": owner.verifier,
                        "redirect_uri": owner.redirect, "grant_type": "authorization_code"})
                    tokens = token_record(raw, scopes, config.get("tokens"))
                    finish(tokens)
                    owner.status = "connected"
                    self.respond(200, "Google is connected. Close this tab and return to Airlock.")
                except ConnectorError as error:
                    owner.status, owner.error = "error", str(error)
                    self.respond(400, "Google connection was not saved. Return to Airlock Chat for details.")
                except Exception:
                    owner.status, owner.error = "error", "Connection could not be saved. Unlock the vault and reconnect."
                    self.respond(400, "Connection could not be saved. Return to Airlock Chat and reconnect.")

            def respond(self, status, message):
                body = message.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Callback)
        self.server.timeout = .5
        self.host = "127.0.0.1:" + str(self.server.server_port)
        self.redirect = "http://" + self.host + "/oauth/callback"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")
        self.url = AUTH + "?" + urlencode({"client_id": config["client_id"], "redirect_uri": self.redirect,
            "response_type": "code", "scope": " ".join(scopes), "state": self.state,
            "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline",
            "prompt": "consent", "include_granted_scopes": "false"})
        self.thread = threading.Thread(target=self._listen, daemon=True)

    def start(self):
        self.thread.start()

    def _listen(self):
        try:
            while not self.cancelled.is_set() and not self.consumed and time.monotonic() < self.expires:
                self.server.handle_request()
            if self.status == "waiting":
                self.status, self.error = "error", "Sign-in expired or was cancelled. Connect Google again."
        finally:
            self.verifier = ""
            self.server.server_close()

    def cancel(self):
        self.cancelled.set()
