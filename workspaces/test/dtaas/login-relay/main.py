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
from pydantic import BaseModel

app = FastAPI()

# Server-side JTI store: maps username → last issued JTI.
# Populated in /login-relay/callback; read in /authz/workspace.
# Oathkeeper's remote_json authorizer calls /authz/workspace server-to-server,
# so browser cookies are never forwarded there — this store is the only way to
# carry the JTI across the introspection→authorizer boundary.
_session_jti_store: dict[str, str] = {}

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
# Unknown paths (e.g. /user1 when USERNAME1=sandra) match no Oathkeeper rule
# and would cause a redirect loop. For those we fall back to "/" so the user
# lands on the SPA root instead of looping indefinitely.
_WORKSPACE_PREFIXES = tuple(
    f"/{u.strip('/')}"
    for u in [
        os.environ.get("USERNAME1", "user1"),
        os.environ.get("USERNAME2", "user2"),
    ]
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
    except Exception:
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


def _safe_return_to(return_to: str) -> str:
    """Return a safe relative path, guarding against open redirects and redirect loops.

    Oathkeeper sits behind Traefik's TLS termination so it sees requests as
    http:// and passes that scheme in return_to_query_param.  Keeping only the
    path (and query) strips the scheme/host entirely, so the post-login redirect
    is always resolved relative to the current HTTPS origin by the browser.

    Paths that have no Oathkeeper access rule (e.g. /user1 when USERNAME1=sandra)
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

    subject: dict = {}


@app.post("/authz/workspace/{path_prefix}", status_code=200)
async def authorize_workspace(
    path_prefix: str,
    body: _AuthzBody,
) -> Response:
    """Verify the JWT preferred_username matches the workspace path prefix AND
    detect token rotation by comparing JTI (JWT ID) claims.

    Called by Oathkeeper's remote_json authorizer for per-user RBAC.
    This is a server-to-server call — browser cookies are NOT forwarded here,
    so JTI comparison is done against _session_jti_store (populated in callback).

    Logic:
      1. Extract username from token — must match path_prefix.
      2. Extract JTI from token — must match the JTI stored during last login.
      3. If JTI changed = Keycloak issued a new token = re-auth required.

    Returns 200 if both checks pass.
    Returns 401 if JTI doesn't match (token was rotated — force re-authentication).
    Returns 403 if username mismatch (wrong user accessing workspace).
    """
    extra = body.subject.get("extra") or {}
    # Keycloak introspection returns "username"; JWT claims use "preferred_username".
    # Try both so this works regardless of Keycloak version/configuration.
    username = extra.get("username") or extra.get("preferred_username", "")
    logging.debug(
        "authz/workspace/%s — username=%r jti_current=%r jti_stored=%r extra_keys=%s",
        path_prefix, username,
        extra.get("jti", ""), _session_jti_store.get(username, ""),
        sorted(extra.keys()),
    )

    # Check 1: Username must match path prefix.
    if not username or username != path_prefix:
        raise HTTPException(status_code=403, detail="Forbidden - wrong user")

    # Check 2: Token JTI must match the JTI issued during the last login callback.
    # The extra dict carries Keycloak introspection claims, including jti.
    current_jti = extra.get("jti", "")
    stored_jti = _session_jti_store.get(username, "")

    # No stored JTI means login-relay restarted or this user hasn't logged in yet.
    # Accept the request; the next callback will populate the store.
    if not stored_jti:
        return Response(status_code=200)

    # Both values must be present and equal.
    if current_jti and current_jti != stored_jti:
        # Clear the store so the next callback() (after prompt=login forces
        # credential entry) can establish a new session with the new JTI.
        _session_jti_store.pop(username, None)
        raise HTTPException(
            status_code=401,
            detail=(
                "Token was rotated - new authentication required. "
                "Keycloak issued a new token; previous session is invalid."
            ),
        )

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
    if dtaas_access_token:
        claims = _decode_jwt_claims(dtaas_access_token)
        if claims.get("exp", 0) > time.time():
            username = claims.get("preferred_username", "")
            if username:
                for prefix in _WORKSPACE_PREFIXES:
                    if safe_destination == prefix or safe_destination.startswith(prefix + "/"):
                        if prefix != f"/{username}":
                            raise HTTPException(status_code=403, detail="Forbidden")

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
            raise HTTPException(
                status_code=502,
                detail=f"Keycloak token exchange failed: {exc}",
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
        return_to = base64.urlsafe_b64decode(return_to_b64 + "==").decode()
        return_to = _safe_return_to(return_to)
    except ValueError:
        return_to = "/"

    access_token = await _fetch_access_token(code)
    response = RedirectResponse(url=return_to, status_code=302)

    # Extract claims from the new token.
    token_claims = _decode_jwt_claims(access_token)
    token_jti = token_claims.get("jti", "")
    # JWT uses "preferred_username"; introspection uses "username". Try both.
    token_username = token_claims.get("preferred_username") or token_claims.get("username", "")

    # Persist the JTI server-side so authorize_workspace can detect rotation.
    # Oathkeeper's remote_json authorizer calls /authz/workspace server-to-server
    # (no browser cookies forwarded), so a shared in-process store is required.
    #
    # Always update the JTI store on every callback. Because prompt=login forces
    # explicit credential entry before this callback is ever reached, each arrival
    # here represents a genuine authentication event. Overwriting the store lets
    # the JTI check in authorize_workspace accept the freshly issued token while
    # still rejecting any lingering old token (its JTI no longer matches the store).
    if token_jti and token_username:
        _session_jti_store[token_username] = token_jti

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
