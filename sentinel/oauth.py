"""OAuth 2.1 + PKCE for the Swiggy MCP, per /builders/docs/start/authenticate/.

Confirmed spec:
  base            https://mcp.swiggy.com
  register        POST /auth/register   (Dynamic Client Registration, RFC 7591)
  authorize       GET  /auth/authorize
  token           POST /auth/token
  scope           mcp:tools
  redirect_uri    HTTPS required, except http://localhost (exact-match allowlist)
  access token    5 days. Authorization code 120s, single use.
  refresh tokens  NOT issued in v1.0 — re-run the full flow when the token expires.

Because Swiggy supports DCR, no client_id has to be requested from anyone: we
register ourselves on first run and cache the result.

Usage:
    python -m sentinel.oauth          # runs the flow, caches the token
    from sentinel.oauth import get_token; get_token()
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request

BASE = os.getenv("SWIGGY_OAUTH_BASE", "https://mcp.swiggy.com")
REGISTER_URL = f"{BASE}/auth/register"
AUTHORIZE_URL = f"{BASE}/auth/authorize"
TOKEN_URL = f"{BASE}/auth/token"

REDIRECT_URI = os.getenv("SWIGGY_OAUTH_REDIRECT", "http://localhost:8765/auth/callback")
SCOPE = os.getenv("SWIGGY_OAUTH_SCOPE", "mcp:tools")
CLIENT_NAME = os.getenv("SWIGGY_CLIENT_NAME", "Sustenance Sentinel")

# Cache lives outside git (see .gitignore). Holds the DCR client + access token.
CACHE_PATH = os.getenv("SWIGGY_TOKEN_CACHE", ".swiggy_auth.json")


# --- cache -----------------------------------------------------------------
def _load_cache() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict) -> None:
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    try:  # best effort: keep the token file owner-only
        os.chmod(CACHE_PATH, 0o600)
    except OSError:
        pass


def _post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


# --- 1. dynamic client registration ---------------------------------------
def register_client(force: bool = False) -> str:
    """Return a client_id, registering with Swiggy on first use (RFC 7591)."""
    cache = _load_cache()
    if not force and cache.get("client_id"):
        return cache["client_id"]

    reg = _post_json(REGISTER_URL, {
        "client_name": CLIENT_NAME,
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # public client, PKCE is the proof
        "scope": SCOPE,
    })
    cache["client_id"] = reg["client_id"]
    if reg.get("client_secret"):
        cache["client_secret"] = reg["client_secret"]
    _save_cache(cache)
    return cache["client_id"]


# --- 2. PKCE authorization -------------------------------------------------
def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class _Callback(http.server.BaseHTTPRequestHandler):
    received: dict = {}
    done = threading.Event()

    def do_GET(self):  # noqa: N802
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Callback.received = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in _Callback.received
        self.wfile.write(
            b"<h3>Sentinel: authorization complete. You can close this tab.</h3>"
            if ok else b"<h3>Authorization failed. Check the terminal.</h3>"
        )
        _Callback.done.set()

    def log_message(self, *a):
        pass  # keep the console clean


def authorize(client_id: str) -> dict:
    """Run the browser leg and exchange the code for an access token."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    parsed = urllib.parse.urlparse(REDIRECT_URI)
    server = http.server.HTTPServer((parsed.hostname or "localhost", parsed.port or 80),
                                    _Callback)
    _Callback.done.clear()
    threading.Thread(target=server.handle_request, daemon=True).start()

    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    print("Opening the Swiggy login (phone + OTP) in your browser…")
    print("If it does not open, paste this URL:\n  " + url + "\n")
    import webbrowser
    webbrowser.open(url)

    # The auth code is single-use and expires in 120s, so don't wait forever.
    if not _Callback.done.wait(timeout=300):
        raise TimeoutError("No OAuth callback received within 5 minutes.")
    server.server_close()

    got = _Callback.received
    if "code" not in got:
        raise RuntimeError(f"Authorization failed: {got}")
    if got.get("state") != state:
        raise RuntimeError("State mismatch — possible CSRF, aborting.")

    tok = _post_json(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": got["code"],
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
    })

    return _store_token(tok)


def _store_token(tok: dict) -> dict:
    cache = _load_cache()
    cache["access_token"] = tok["access_token"]
    cache["expires_at"] = time.time() + int(tok.get("expires_in", 5 * 24 * 3600))
    cache["scope"] = tok.get("scope", SCOPE)
    # The docs say v1.0 issues no refresh token, but the server's own metadata
    # advertises the refresh_token grant. Keep one if we are given one.
    if tok.get("refresh_token"):
        cache["refresh_token"] = tok["refresh_token"]
    _save_cache(cache)
    return cache


def _try_refresh(cache: dict) -> str | None:
    rt, client_id = cache.get("refresh_token"), cache.get("client_id")
    if not rt or not client_id:
        return None
    try:
        tok = _post_json(TOKEN_URL, {
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": client_id,
        })
        return _store_token(tok)["access_token"]
    except Exception:
        return None  # fall back to the full browser flow


def get_token(interactive: bool = True) -> str | None:
    """Cached access token, refreshing or re-running the flow as needed."""
    env = os.getenv("SWIGGY_MCP_TOKEN", "").strip()
    if env:
        return env

    cache = _load_cache()
    tok, exp = cache.get("access_token"), cache.get("expires_at", 0)
    if tok and time.time() < exp - 60:
        return tok

    refreshed = _try_refresh(cache)
    if refreshed:
        return refreshed

    if not interactive:
        return None
    return authorize(register_client())["access_token"]


if __name__ == "__main__":
    cache = authorize(register_client())
    left = (cache["expires_at"] - time.time()) / 86400
    print(f"\nAuthorized. Token cached in {CACHE_PATH}, valid ~{left:.1f} days.")
    print("No refresh tokens in v1.0 — re-run this when it expires.")
