"""Tests for login-relay security logic and API endpoints."""
# conftest.py force-sets env vars before this module is imported, so main.py
# picks up the test values when it runs its module-level initialisation.
import base64
import json
import time
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from main import app, _decode_jwt_claims, _is_routable, _safe_return_to

client = TestClient(app, follow_redirects=False)


def _make_jwt(claims: dict) -> str:
    """Build a fake (unsigned) JWT for testing claim extraction."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestDecodeJwtClaims:
    """Tests for the _decode_jwt_claims helper."""

    def test_valid_token_returns_claims(self):
        """Valid JWT yields the embedded claims dict."""
        claims = {"sub": "abc", "preferred_username": "user1", "exp": 9999999999}
        assert _decode_jwt_claims(_make_jwt(claims)) == claims

    def test_malformed_returns_empty(self):
        """Token with invalid base64 payload returns empty dict."""
        assert _decode_jwt_claims("not.a.jwt") == {}

    def test_too_few_parts_returns_empty(self):
        """Token with fewer than three dot-separated parts returns empty dict."""
        assert _decode_jwt_claims("onlyone") == {}

    def test_invalid_base64_returns_empty(self):
        """Token whose payload segment is not valid base64 returns empty dict."""
        assert _decode_jwt_claims("a.!!!.c") == {}


class TestIsRoutable:
    """Tests for the _is_routable path-validation helper."""

    def test_root(self):
        """Root path is always routable."""
        assert _is_routable("/") is True

    def test_empty(self):
        """Empty string is treated as root and is routable."""
        assert _is_routable("") is True

    def test_workspace_exact(self):
        """Exact workspace prefix without trailing slash is routable."""
        assert _is_routable("/user1") is True

    def test_workspace_subpath(self):
        """Sub-path beneath a known workspace prefix is routable."""
        assert _is_routable("/user1/tools/vscode") is True

    def test_spa_library(self):
        """SPA library path is routable."""
        assert _is_routable("/library") is True

    def test_spa_subpath(self):
        """Nested SPA path is routable."""
        assert _is_routable("/digitaltwins/mydt") is True

    def test_unknown_path_returns_false(self):
        """Path under an unknown workspace prefix is not routable."""
        assert _is_routable("/user3") is False

    def test_partial_prefix_not_matched(self):
        """Partial prefix match must not be accepted as routable."""
        # /user1extra must NOT match the /user1 prefix
        assert _is_routable("/user1extra") is False


class TestSafeReturnTo:
    """Tests for the _safe_return_to URL-sanitisation helper."""

    def test_root_passthrough(self):
        """Root path passes through unchanged."""
        assert _safe_return_to("/") == "/"

    def test_empty_becomes_root(self):
        """Empty string is normalised to root."""
        assert _safe_return_to("") == "/"

    def test_known_workspace_preserved(self):
        """Known workspace path is preserved as-is."""
        assert _safe_return_to("/user1/lab") == "/user1/lab"

    def test_unknown_workspace_normalised_to_root(self):
        """Path under unknown workspace is normalised to root."""
        assert _safe_return_to("/user3/lab") == "/"

    def test_spa_path_preserved(self):
        """SPA path is preserved as-is."""
        assert _safe_return_to("/library") == "/library"

    def test_query_string_preserved(self):
        """Query string is kept when the path is valid."""
        assert _safe_return_to("/user1/lab?foo=bar") == "/user1/lab?foo=bar"

    def test_cross_origin_blocked(self):
        """Absolute URL to a different origin is blocked and returns root."""
        assert _safe_return_to("https://evil.com/path") == "/"

    def test_same_origin_absolute_extracts_path(self):
        """Absolute URL on the same origin is reduced to its path component."""
        # Oathkeeper passes http:// URLs; SERVER_DNS check uses netloc only
        assert _safe_return_to("http://test.example.com/user1/lab") == "/user1/lab"

    def test_relative_path_gets_leading_slash(self):
        """Relative path without leading slash gets one prepended."""
        assert _safe_return_to("user1/lab") == "/user1/lab"


# ---------------------------------------------------------------------------
# /authz/workspace/<user>
# ---------------------------------------------------------------------------

class TestAuthzWorkspace:
    """Tests for the /authz/workspace/<user> authorisation endpoint."""

    def test_matching_username_returns_200(self):
        """Request whose username matches the path segment returns 200."""
        resp = client.post(
            "/authz/workspace/user1",
            json={"subject": {"extra": {"username": "user1"}}},
        )
        assert resp.status_code == 200

    def test_preferred_username_fallback_returns_200(self):
        """preferred_username claim is accepted as a fallback identifier."""
        resp = client.post(
            "/authz/workspace/user1",
            json={"subject": {"extra": {"preferred_username": "user1"}}},
        )
        assert resp.status_code == 200

    def test_wrong_user_returns_403(self):
        """Request whose username does not match the path segment returns 403."""
        resp = client.post(
            "/authz/workspace/user2",
            json={"subject": {"extra": {"username": "user1"}}},
        )
        assert resp.status_code == 403

    def test_empty_username_returns_403(self):
        """Request with no username claim returns 403."""
        resp = client.post(
            "/authz/workspace/user1",
            json={"subject": {"extra": {}}},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    """Tests for the /health endpoint."""

    def test_returns_200(self):
        """Health endpoint returns HTTP 200."""
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# /logout
# ---------------------------------------------------------------------------

class TestLogout:
    """Tests for the /logout endpoint."""

    def test_redirects_to_keycloak(self):
        """Logout redirects to the Keycloak logout URL."""
        resp = client.get("/logout")
        assert resp.status_code == 302
        assert "logout" in resp.headers["location"]

    def test_clears_access_token_cookie(self):
        """Logout response expires the dtaas_access_token cookie."""
        resp = client.get("/logout")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "dtaas_access_token" in set_cookie
        assert "max-age=0" in set_cookie.lower()


# ---------------------------------------------------------------------------
# GET /login-relay  (initiate login)
# ---------------------------------------------------------------------------

class TestLogin:
    """Tests for the GET /login-relay login-initiation endpoint."""

    def test_redirects_to_keycloak_auth(self):
        """Login endpoint redirects to the Keycloak authorisation URL."""
        resp = client.get("/login-relay")
        assert resp.status_code == 302
        assert "auth/realms" in resp.headers["location"]

    def test_sets_oauth_state_cookie(self):
        """Login endpoint sets the oauth_state cookie for CSRF protection."""
        resp = client.get("/login-relay")
        assert "oauth_state" in resp.headers.get("set-cookie", "")

    def test_cross_user_redirect_returns_403(self):
        """A valid user1 token redirected to /user2 must get 403, not a new login."""
        future = int(time.time()) + 3600
        token = _make_jwt({"preferred_username": "user1", "exp": future})
        c = TestClient(app, follow_redirects=False, cookies={"dtaas_access_token": token})
        assert c.get("/login-relay?return_to=/user2/lab").status_code == 403

    def test_expired_token_does_not_block_login(self):
        """An expired token for user1 must not trigger 403 — allow re-login."""
        past = int(time.time()) - 1
        token = _make_jwt({"preferred_username": "user1", "exp": past})
        c = TestClient(app, follow_redirects=False, cookies={"dtaas_access_token": token})
        # Expired token: cross-user check is skipped, normal login redirect fires
        assert c.get("/login-relay?return_to=/user2/lab").status_code == 302


# ---------------------------------------------------------------------------
# GET /login-relay/callback
# ---------------------------------------------------------------------------

class TestCallback:
    """Tests for the GET /login-relay/callback OAuth2 callback endpoint."""

    def test_missing_state_cookie_returns_400(self):
        """Callback without an oauth_state cookie returns 400."""
        resp = client.get("/login-relay/callback?code=abc&state=xyz")
        assert resp.status_code == 400

    def test_missing_code_returns_400(self):
        """Callback without an authorisation code returns 400."""
        nonce = "testnonce"
        return_to_b64 = base64.urlsafe_b64encode(b"/user1/lab").decode()
        c = TestClient(
            app, follow_redirects=False, cookies={"oauth_state": f"{nonce}:{return_to_b64}"}
        )
        assert c.get(f"/login-relay/callback?state={nonce}").status_code == 400

    def test_state_mismatch_returns_400(self):
        """Callback with a mismatched state parameter returns 400."""
        return_to_b64 = base64.urlsafe_b64encode(b"/user1/lab").decode()
        c = TestClient(
            app, follow_redirects=False, cookies={"oauth_state": f"correct:{return_to_b64}"}
        )
        assert c.get("/login-relay/callback?code=abc&state=wrong").status_code == 400

    def test_success_sets_cookie_and_redirects(self):
        """Successful callback sets the access-token cookie and redirects."""
        nonce = "testnonce123"
        return_to_b64 = base64.urlsafe_b64encode(b"/user1/lab").decode()
        c = TestClient(
            app, follow_redirects=False, cookies={"oauth_state": f"{nonce}:{return_to_b64}"}
        )

        with patch("main._fetch_access_token", new=AsyncMock(return_value="fake-token")):
            resp = c.get(f"/login-relay/callback?code=authcode&state={nonce}")

        assert resp.status_code == 302
        assert resp.headers["location"] == "/user1/lab"
        assert "dtaas_access_token" in resp.headers.get("set-cookie", "")

    def test_unknown_return_to_falls_back_to_root(self):
        """Callback with an unknown return_to path redirects to root."""
        nonce = "testnonce456"
        return_to_b64 = base64.urlsafe_b64encode(b"/user3/lab").decode()
        c = TestClient(
            app, follow_redirects=False, cookies={"oauth_state": f"{nonce}:{return_to_b64}"}
        )

        with patch("main._fetch_access_token", new=AsyncMock(return_value="fake-token")):
            resp = c.get(f"/login-relay/callback?code=authcode&state={nonce}")

        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
