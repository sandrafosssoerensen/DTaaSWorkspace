"""Login-relay: Keycloak authorization code relay for DTaaS workspace authentication.

Flow:
  1. Oathkeeper's redirect error handler sends unauthenticated browser requests
     here with ?return_to=<original-path> (set via return_to_query_param config).
  2. /login-relay generates a random state nonce, stores the nonce + return_to
     in a short-lived HttpOnly cookie, and redirects the browser to Keycloak's
     authorization endpoint.
  3. Keycloak redirects back to /login-relay/callback with an auth code and state.
  4. /login-relay/callback verifies the state nonce (CSRF check), exchanges the
     code for tokens (server-to-server using the client secret), sets the
     dtaas_access_token cookie (read by Oathkeeper for JWT validation), and
     redirects to the original destination.

Architecture:
  Traefik → Oathkeeper proxy:4455 → workspace containers
                     ↓ no JWT + browser
             /login-relay?return_to=/user1 → Keycloak → /login-relay/callback
                     →y sets dtaas_access_token cookie → /user1
"""

import base64
import binascii
import hmac
import json
import logging
import os
import time
import urllib.parse
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import Cookie, FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

app = FastAPI()

# Public Keycloak URL — used for browser redirects (login page).
KEYCLOAK_PUBLIC_URL = os.environ.get("KEYCLOAK_PUBLIC_URL", "https://localhost/auth")
# Internal Keycloak URL — used for server-side token exchange (container-to-container).
KEYCLOAK_INTERNAL_URL = os.environ.get("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080/auth")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "dtaas")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dtaas-workspace")
KEYCLOAK_CLIENT_SECRET = os.environ["KEYCLOAK_CLIENT_SECRET"]
SERVER_DNS = os.environ["SERVER_DNS"]

# Workspace path prefixes — paths that have an Oathkeeper rule and should be
# preserved in the return_to redirect after Keycloak login.
# Unknown paths match no Oathkeeper rule and would cause a redirect loop.
# For those we fall back to "/" so the user lands on the SPA root instead.
# Configure via WORKSPACE_USERS=user1,user2,user3 (comma-separated).
_WORKSPACE_PREFIXES = tuple(
    f"/{u.strip('/')}"
    for u in os.environ.get("WORKSPACE_USERS", "user1,user2").split(",")
    if u.strip("/")
)
# Known SPA path prefixes — must stay in sync with the dtaas-spa-gateway rule.
_SPA_PREFIXES = (
    "/library", "/digitaltwins", "/preview", "/create",
    "/static", "/env.js", "/favicon.ico", "/manifest.json", "/logo",
)


def _decode_jwt_claims(token: str) -> dict:
    """Extract JWT payload claims without signature verification.

    Used for redirect-loop detection. The authoritative claim check
    (preferred_username == path_prefix) is done by /authz/workspace, which is
    called by Oathkeeper's remote_json authorizer with full JWT validation.

    Returns dict with claims or empty dict on error.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, KeyError, UnicodeDecodeError, binascii.Error):
        return {}


def _is_routable(path: str) -> bool:
    """Return True if path is covered by an Oathkeeper access rule."""
    if path in ("/", ""):
        return True
    for prefix in _WORKSPACE_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    for prefix in _SPA_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _public_realm_url() -> str:
    return f"{KEYCLOAK_PUBLIC_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"


def _internal_realm_url() -> str:
    return f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"


def _callback_uri() -> str:
    return f"https://{SERVER_DNS}/login-relay/callback"


def _check_cross_user_redirect(token: str, destination: str) -> None:
    """Raise 403 if a valid token owner tries to access another user's workspace."""
    if not token:
        return
    claims = _decode_jwt_claims(token)
    if claims.get("exp", 0) <= time.time():
        return
    username = claims.get("preferred_username", "")
    if not username:
        return
    for prefix in _WORKSPACE_PREFIXES:
        if destination == prefix or destination.startswith(prefix + "/"):
            if prefix != f"/{username}":
                raise HTTPException(status_code=403, detail="Forbidden")


def _safe_return_to(return_to: str) -> str:
    """Return a safe relative path, guarding against open redirects and redirect loops.

    Oathkeeper sits behind Traefik's TLS termination so it sees requests as
    http:// and passes that scheme in return_to_query_param.  Keeping only the
    path (and query) strips the scheme/host entirely, so the post-login redirect
    is always resolved relative to the current HTTPS origin by the browser.

    Paths that have no Oathkeeper access rule (e.g. /user1 when not in WORKSPACE_USERS)
    would cause an infinite redirect loop after Keycloak login because Oathkeeper
    returns "no rule matched" and fires the redirect error handler again.  Such
    paths are normalised to "/" so the user lands on the SPA root instead.
    """
    parsed = urllib.parse.urlparse(return_to)
    # Reject cross-origin absolute URLs outright.
    if parsed.netloc and parsed.netloc != SERVER_DNS:
        return "/"
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if not _is_routable(path):
        return "/"
    if parsed.query:
        path += "?" + parsed.query
    return path


class _AuthzBody(BaseModel):
    """Payload sent by Oathkeeper's remote_json authorizer."""

    subject: dict = Field(default_factory=dict)


@app.post("/authz/workspace/{path_prefix}", status_code=200)
async def authorize_workspace(
    path_prefix: str,
    body: _AuthzBody,
) -> Response:
    """Verify the token's username matches the workspace path prefix.

    Called by Oathkeeper's remote_json authorizer for per-user RBAC.

    Returns 200 if the username matches the path prefix.
    Returns 403 if username mismatch (wrong user accessing workspace).
    """
    extra = body.subject.get("extra") or {}
    # Keycloak introspection returns "username"; JWT claims use "preferred_username".
    # Try both so this works regardless of Keycloak version/configuration.
    username = extra.get("username") or extra.get("preferred_username", "")
    logging.debug(
        "authz/workspace/%s — username=%r extra_keys=%s",
        path_prefix, username, sorted(extra.keys()),
    )

    if not username or username != path_prefix:
        raise HTTPException(status_code=403, detail="Forbidden - wrong user")

    return Response(status_code=200)


@app.get("/login-relay")
async def login(
    return_to: str = "/",
    dtaas_access_token: str = Cookie(default=""),
) -> RedirectResponse:
    """Initiate Keycloak authorization code flow, preserving the original destination."""
    safe_destination = _safe_return_to(return_to)

    # Break the Oathkeeper forbidden→redirect→login→forbidden loop.
    # Oathkeeper v26 redirects ALL errors (including forbidden) to login-relay.
    # When a user with a valid token tries to access another user's workspace,
    # Oathkeeper's remote_json authorizer returns 403, which redirects here.
    # Without this check the browser loops until the Traefik rate-limiter fires.
    _check_cross_user_redirect(dtaas_access_token, safe_destination)

    # Random state nonce — RFC 6749 §10.12 CSRF protection.
    nonce = generate_token(32)
    return_to_b64 = base64.urlsafe_b64encode(safe_destination.encode()).decode()
    oauth_state = f"{nonce}:{return_to_b64}"

    params = urllib.parse.urlencode({
        "client_id": KEYCLOAK_CLIENT_ID,
        "redirect_uri": _callback_uri(),
        "response_type": "code",
        "scope": "openid profile",
        "state": nonce,
        # Force Keycloak to show the login form even when a SSO session exists.
        # Both this gateway login and the SPA's own OIDC login require explicit
        # credential entry — SSO silent re-auth is intentionally disabled.
        "prompt": "login",
    })

    response = RedirectResponse(
        url=f"{_public_realm_url()}/auth?{params}",
        status_code=302,
    )
    _set_short_cookie(response, "oauth_state", oauth_state)
    return response


@app.get("/logout")
@app.get("/login-relay/logout")
async def logout() -> RedirectResponse:
    """Clear the dtaas_access_token cookie and end the Keycloak session."""
    keycloak_logout_url = (
        f"{_public_realm_url()}/logout"
        f"?client_id={KEYCLOAK_CLIENT_ID}"
        f"&post_logout_redirect_uri=https://{SERVER_DNS}/"
    )
    response = RedirectResponse(url=keycloak_logout_url, status_code=302)
    response.delete_cookie(key="dtaas_access_token", path="/")
    return response


async def _fetch_access_token(code: str) -> str:
    """Exchange a Keycloak authorization code for an access token."""
    async with AsyncOAuth2Client(
        client_id=KEYCLOAK_CLIENT_ID,
        client_secret=KEYCLOAK_CLIENT_SECRET,
        redirect_uri=_callback_uri(),
    ) as client:
        try:
            token = await client.fetch_token(
                url=f"{_internal_realm_url()}/token",
                grant_type="authorization_code",
                code=code,
            )
        except Exception as exc:
            logging.error("Keycloak token exchange failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="Token exchange failed.",
            ) from exc
    access_token = token.get("access_token", "")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in Keycloak response.")
    return access_token


@app.get("/login-relay/callback")
async def callback(
    code: str = "",
    state: str = "",
    oauth_state: str = Cookie(default=""),
) -> RedirectResponse:
    """Exchange Keycloak auth code for tokens and redirect back to original path."""
    if not oauth_state:
        raise HTTPException(status_code=400, detail="Missing OAuth state cookie.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorisation code.")

    # Split stored nonce and return_to from the oauth_state cookie.
    try:
        nonce, return_to_b64 = oauth_state.split(":", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed OAuth state cookie.") from exc

    # Constant-time comparison — prevents timing attacks on the CSRF nonce.
    if not hmac.compare_digest(state, nonce):
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF attempt.")

    try:
        padding = "=" * (-len(return_to_b64) % 4)
        return_to = base64.urlsafe_b64decode(return_to_b64 + padding).decode()
        return_to = _safe_return_to(return_to)
    except (ValueError, binascii.Error):
        return_to = "/"

    access_token = await _fetch_access_token(code)
    response = RedirectResponse(url=return_to, status_code=302)

    # max_age=300 — matches the Keycloak default access token lifespan (5 min).
    # The cookie expires with the JWT; Oathkeeper will redirect to login after expiry.
    response.set_cookie(
        key="dtaas_access_token",
        value=access_token,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )

    response.delete_cookie("oauth_state")
    return response


def _set_short_cookie(response: RedirectResponse, key: str, value: str) -> None:
    """Set a short-lived HttpOnly Secure cookie for the OAuth state handshake."""
    response.set_cookie(
        key=key,
        value=value,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
    )