"""OAuth 2.1 + PKCE helper for the Swiggy MCP (dev / localhost).

Per the builder docs, auth is OAuth 2.1 with PKCE and `http://localhost` is an
allowed redirect for development; the browser step is a phone + OTP login. Most
agent frameworks (Anthropic native MCP connector, OpenAI Agents SDK) automate
this — paste the authorize URL into the framework config and it handles the rest.

This module is the manual fallback: it runs the PKCE dance and returns a bearer
token you can drop into SWIGGY_MCP_TOKEN. Confirm the authorize/token endpoints
against https://mcp.swiggy.com/builders/docs/start/authenticate/ before use.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser

# Confirm these two against the authenticate docs page; overridable via env.
AUTHORIZE_URL = os.getenv("SWIGGY_OAUTH_AUTHORIZE", "https://mcp.swiggy.com/oauth/authorize")
TOKEN_URL = os.getenv("SWIGGY_OAUTH_TOKEN", "https://mcp.swiggy.com/oauth/token")
CLIENT_ID = os.getenv("SWIGGY_OAUTH_CLIENT_ID", "")
REDIRECT_URI = os.getenv("SWIGGY_OAUTH_REDIRECT", "http://localhost:8000/auth/callback")
SCOPE = os.getenv("SWIGGY_OAUTH_SCOPE", "food")


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self):  # noqa: N802
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _CallbackHandler.code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Auth complete. You can close this tab.")

    def log_message(self, *a):  # silence
        pass


def fetch_token() -> str:
    """Run the PKCE flow and return a bearer access token."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    port = urllib.parse.urlparse(REDIRECT_URI).port or 8000
    server = http.server.HTTPServer(("localhost", port), _CallbackHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    webbrowser.open(AUTHORIZE_URL + "?" + urllib.parse.urlencode(params))
    print("Complete phone + OTP login in the browser…")
    while _CallbackHandler.code is None:
        pass  # handle_request blocks until one callback; loop is a safety net
    code = _CallbackHandler.code

    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    import json
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["access_token"]


if __name__ == "__main__":
    token = fetch_token()
    print("\nSWIGGY_MCP_TOKEN=" + token)
