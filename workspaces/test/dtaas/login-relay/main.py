"""Login-relay: Keycloak PKCE relay for DTaaS workspace authentication.

Flow:
  1. Oathkeeper's redirect error handler sends unauthenticated browser requests
     here with ?return_to=<original-path> (set via return_to_query_param config).
  2. /login-relay generates PKCE params and a random state nonce, stores the
     verifier + nonce + return_to in a short-lived HttpOnly cookie, and redirects
     the browser to Keycloak's auth endpoint.
  3. Keycloak redirects back to /login-relay/callback with an auth code and state.
  4. /login-relay/callback verifies the state nonce (CSRF check), exchanges the
     code for tokens (server-to-server), sets the dtaas_access_token cookie (read
     by Oathkeeper for JWT validation), and redirects to the original destination.

Architecture:
  Traefik → Oathkeeper proxy:4455 → workspace containers
                     ↓ no JWT + browser
             /login-relay?return_to=/user1 → Keycloak → /login-relay/callback
                     → sets dtaas_access_token cookie → /user1
"""

import base64
import hmac
import os
import urllib.parse

from authlib.common.security import generate_token
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastapi import Cookie, FastAPI, HTTPException
from fastapi.responses import RedirectResponse

app = FastAPI()

# Public Keycloak URL — used for browser redirects (login page).
KEYCLOAK_PUBLIC_URL = os.environ.get("KEYCLOAK_PUBLIC_URL", "https://localhost/auth")
# Internal Keycloak URL — used for server-side token exchange (container-to-container).
KEYCLOAK_INTERNAL_URL = os.environ.get("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080/auth")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "dtaas")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dtaas-workspace")
SERVER_DNS = os.environ["SERVER_DNS"]


def _public_realm_url() -> str:
    return f"{KEYCLOAK_PUBLIC_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"


def _internal_realm_url() -> str:
    return f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect"


def _callback_uri() -> str:
    return f"https://{SERVER_DNS}/login-relay/callback"


def _safe_return_to(return_to: str) -> str:
    """Validate return_to is a relative path on the same origin (open-redirect guard)."""
    parsed = urllib.parse.urlparse(return_to)
    if parsed.scheme or parsed.netloc:
        if parsed.netloc != SERVER_DNS:
            return "/"
    return return_to or "/"



@app.get("/login-relay")
async def login(return_to: str = "/") -> RedirectResponse:
    """Initiate Keycloak PKCE flow, preserving the original destination."""
    safe_destination = _safe_return_to(return_to)

    # Authlib-generated PKCE pair — audited RFC 7636 implementation.
    verifier = generate_token(96)
    challenge = create_s256_code_challenge(verifier)

    # Random state nonce — RFC 6749 §10.12 CSRF protection.
    # The return_to path is stored in the pkce_state cookie, not in the state
    # parameter, so the state value is unpredictable.
    nonce = generate_token(32)
    return_to_b64 = base64.urlsafe_b64encode(safe_destination.encode()).decode()
    pkce_state = f"{nonce}:{return_to_b64}"

    params = urllib.parse.urlencode({
        "client_id": KEYCLOAK_CLIENT_ID,
        "redirect_uri": _callback_uri(),
        "response_type": "code",
        "scope": "openid profile",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": nonce,
    })

    response = RedirectResponse(
        url=f"{_public_realm_url()}/auth?{params}",
        status_code=302,
    )
    _set_short_cookie(response, "pkce_verifier", verifier)
    _set_short_cookie(response, "pkce_state", pkce_state)
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


@app.get("/login-relay/callback")
async def callback(
    code: str = "",
    state: str = "",
    pkce_verifier: str = Cookie(default=""),
    pkce_state: str = Cookie(default=""),
) -> RedirectResponse:
    """Exchange Keycloak auth code for tokens and redirect back to original path."""
    if not pkce_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE verifier cookie.")
    if not pkce_state:
        raise HTTPException(status_code=400, detail="Missing PKCE state cookie.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorisation code.")

    # Split stored nonce and return_to from the pkce_state cookie.
    try:
        nonce, return_to_b64 = pkce_state.split(":", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed PKCE state cookie.") from exc

    # Constant-time comparison — prevents timing attacks on the CSRF nonce.
    if not hmac.compare_digest(state, nonce):
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF attempt.")

    try:
        return_to = base64.urlsafe_b64decode(return_to_b64 + "==").decode()
        return_to = _safe_return_to(return_to)
    except Exception:
        return_to = "/"

    # Authlib AsyncOAuth2Client handles the token POST and response parsing.
    async with AsyncOAuth2Client(
        client_id=KEYCLOAK_CLIENT_ID,
        redirect_uri=_callback_uri(),
    ) as client:
        try:
            token = await client.fetch_token(
                url=f"{_internal_realm_url()}/token",
                grant_type="authorization_code",
                code=code,
                code_verifier=pkce_verifier,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Keycloak token exchange failed: {exc}",
            ) from exc

    access_token = token.get("access_token", "")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in Keycloak response.")

    response = RedirectResponse(url=return_to, status_code=302)
    # max_age=300 — matches the Keycloak default access token lifespan (5 min).
    # Cookie expires with the JWT; Oathkeeper redirects to login-relay on expiry,
    # which silently re-authenticates via the Keycloak SSO session (idle: 30 min).
    response.set_cookie(
        key="dtaas_access_token",
        value=access_token,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.delete_cookie("pkce_verifier")
    response.delete_cookie("pkce_state")
    return response


def _set_short_cookie(response: RedirectResponse, key: str, value: str) -> None:
    """Set a short-lived HttpOnly Secure cookie for the PKCE handshake."""
    response.set_cookie(
        key=key,
        value=value,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
    )
