"""Login-relay: authorization code relay for DTaaS workspace authentication.

Flow:
  1. Oathkeeper redirects unauthenticated browser requests here with
     ?return_to=<original-path>.
  2. /login-relay stores a CSRF nonce + return_to in a short-lived cookie
     and redirects the browser to the OIDC provider's authorization endpoint.
  3. The provider redirects back to /login-relay/callback with an auth code.
  4. /login-relay/callback verifies the CSRF nonce, exchanges the code for
     tokens, sets the dtaas_access_token cookie, and redirects to the
     original destination.

Architecture:
  Traefik → Oathkeeper proxy:4455 → workspace containers
                     ↓ no token + browser
             /login-relay?return_to=/user1 → OIDC → /login-relay/callback
                     → sets dtaas_access_token cookie → /user1
"""
import logging
from urllib.parse import quote

from fastapi import Cookie, FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from _config import KEYCLOAK_CLIENT_ID, SERVER_DNS
from _helpers import (
    _active_username, _auth_url_public, _build_auth_params,
    _check_cross_user_redirect, _fetch_tokens, _generate_state, _public_realm_url,
    _safe_return_to, _set_access_token_cookie, _set_short_cookie,
    _validate_id_token, _verify_state,
)

app = FastAPI()


class _AuthzExtra(BaseModel):
    """Typed claims forwarded by Oathkeeper's remote_json authorizer."""

    username: str = ""
    preferred_username: str = ""


class _AuthzSubject(BaseModel):
    extra: _AuthzExtra = Field(default_factory=_AuthzExtra)


class _AuthzBody(BaseModel):
    """Payload sent by Oathkeeper's remote_json authorizer."""

    subject: _AuthzSubject = Field(default_factory=_AuthzSubject)


@app.get("/workspace-redirecttree/{path:path}")
async def workspace_redirect(
    path: str,
    dtaas_access_token: str = Cookie(default=""),
) -> RedirectResponse:
    """Redirect to the authenticated user's Jupyter tree path.

    The SPA constructs iframes as REACT_APP_URL + userName + LIBLINK + "tree/{dir}".
    With an empty GitLab userName, the generated URL is
    /workspace-redirecttree/{dir} (LIBLINK="workspace-redirect", no separator).
    This endpoint reads preferred_username from the cookie and redirects to
    /{username}/tree/{path} so all users share one static client.js.
    """
    encoded_path = quote(path, safe="/")
    username = _active_username(dtaas_access_token)
    if not username:
        return RedirectResponse(
            url=f"/login-relay?return_to=/workspace-redirecttree/{encoded_path}",
            status_code=302,
        )
    return RedirectResponse(url=f"/{username}/tree/{encoded_path}", status_code=302)


@app.post("/authz/workspace/{path_prefix}", status_code=200)
async def authorize_workspace(path_prefix: str, body: _AuthzBody) -> Response:
    """Verify via remote_json RBAC that token's username matches the path prefix."""
    username = body.subject.extra.username or body.subject.extra.preferred_username
    logging.debug("authz/workspace/%s — username=%r", path_prefix, username)
    if not username or username != path_prefix:
        raise HTTPException(status_code=403, detail="Forbidden - wrong user")
    return Response(status_code=200)


@app.get("/login-relay")
async def login(
    return_to: str = "/",
    dtaas_access_token: str = Cookie(default=""),
) -> RedirectResponse:
    """Initiate authorization code flow, preserving the original destination."""
    safe_destination = _safe_return_to(return_to)
    _check_cross_user_redirect(dtaas_access_token, safe_destination)
    nonce, oauth_state = _generate_state(safe_destination)
    response = RedirectResponse(
        url=f"{_auth_url_public()}?{_build_auth_params(nonce)}",
        status_code=302,
    )
    _set_short_cookie(response, "oauth_state", oauth_state)
    return response


@app.get("/health")
async def health() -> Response:
    """Return 200 OK for liveness probes."""
    return Response(status_code=200)


@app.get("/logout")
@app.get("/login-relay/logout")
async def logout() -> RedirectResponse:
    """Clear the dtaas_access_token cookie and end the OIDC session."""
    logout_url = (
        f"{_public_realm_url()}/logout"
        f"?client_id={KEYCLOAK_CLIENT_ID}"
        f"&post_logout_redirect_uri=https://{SERVER_DNS}/"
    )
    response = RedirectResponse(url=logout_url, status_code=302)
    response.delete_cookie(key="dtaas_access_token", path="/")
    return response


@app.get("/login-relay/callback")
async def callback(
    code: str = "",
    state: str = "",
    oauth_state: str = Cookie(default=""),
) -> RedirectResponse:
    """Exchange auth code for tokens and redirect back to the original path."""
    if not oauth_state:
        raise HTTPException(status_code=400, detail="Missing OAuth state cookie.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorisation code.")
    return_to = _verify_state(oauth_state, state)
    access_token, id_token, expires_in = await _fetch_tokens(code)
    if id_token:
        await _validate_id_token(id_token)
    response = RedirectResponse(url=return_to, status_code=302)
    _set_access_token_cookie(response, access_token, expires_in)
    response.delete_cookie("oauth_state", path="/login-relay")
    return response
