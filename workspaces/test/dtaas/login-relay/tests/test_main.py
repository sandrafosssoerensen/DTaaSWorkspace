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
    def test_valid_token_returns_claims(self):
        claims = {"sub": "abc", "preferred_username": "user1", "exp": 9999999999}
        assert _decode_jwt_claims(_make_jwt(claims)) == claims

    def test_malformed_returns_empty(self):
        assert _decode_jwt_claims("not.a.jwt") == {}

    def test_too_few_parts_returns_empty(self):
        assert _decode_jwt_claims("onlyone") == {}

    def test_invalid_base64_returns_empty(self):
        assert _decode_jwt_claims("a.!!!.c") == {}


class TestIsRoutable:
    def test_root(self):
        assert _is_routable("/") is True

    def test_empty(self):
        assert _is_routable("") is True

    def test_workspace_exact(self):
        assert _is_routable("/user1") is True

    def test_workspace_subpath(self):
        assert _is_routable("/user1/tools/vscode") is True

    def test_spa_library(self):
        assert _is_routable("/library") is True

    def test_spa_subpath(self):
        assert _is_routable("/digitaltwins/mydt") is True

    def test_unknown_path_returns_false(self):
        assert _is_routable("/user3") is False

    def test_partial_prefix_not_matched(self):
        # /user1extra must NOT match the /user1 prefix
        assert _is_routable("/user1extra") is False


class TestSafeReturnTo:
    def test_root_passthrough(self):
        assert _safe_return_to("/") == "/"

    def test_empty_becomes_root(self):
        assert _safe_return_to("") == "/"

    def test_known_workspace_preserved(self):
        assert _safe_return_to("/user1/lab") == "/user1/lab"

    def test_unknown_workspace_normalised_to_root(self):
        assert _safe_return_to("/user3/lab") == "/"

    def test_spa_path_preserved(self):
        assert _safe_return_to("/library") == "/library"

    def test_query_string_preserved(self):
        assert _safe_return_to("/user1/lab?foo=bar") == "/user1/lab?foo=bar"

    def test_cross_origin_blocked(self):
        assert _safe_return_to("https://evil.com/path") == "/"

    def test_same_origin_absolute_extracts_path(self):
        # Oathkeeper passes http:// URLs; SERVER_DNS check uses netloc only
        assert _safe_return_to("http://test.example.com/user1/lab") == "/user1/lab"

    def test_relative_path_gets_leading_slash(self):
        assert _safe_return_to("user1/lab") == "/user1/lab"


# ---------------------------------------------------------------------------
# /authz/workspace/<user>
# ---------------------------------------------------------------------------

class TestAuthzWorkspace:
    def test_matching_username_returns_200(self):
        resp = client.post(
            "/authz/workspace/user1",
            json={"subject": {"extra": {"username": "user1"}}},
        )
        assert resp.status_code == 200

    def test_preferred_username_fallback_returns_200(self):
        resp = client.post(
            "/authz/workspace/user1",
            json={"subject": {"extra": {"preferred_username": "user1"}}},
        )
        assert resp.status_code == 200

    def test_wrong_user_returns_403(self):
        resp = client.post(
            "/authz/workspace/user2",
            json={"subject": {"extra": {"username": "user1"}}},
        )
        assert resp.status_code == 403

    def test_empty_username_returns_403(self):
        resp = client.post(
            "/authz/workspace/user1",
            json={"subject": {"extra": {}}},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200(self):
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# /logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_redirects_to_keycloak(self):
        resp = client.get("/logout")
        assert resp.status_code == 302
        assert "logout" in resp.headers["location"]

    def test_clears_access_token_cookie(self):
        resp = client.get("/logout")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "dtaas_access_token" in set_cookie
        assert "max-age=0" in set_cookie.lower()


# ---------------------------------------------------------------------------
# GET /login-relay  (initiate login)
# ---------------------------------------------------------------------------

class TestLogin:
    def test_redirects_to_keycloak_auth(self):
        resp = client.get("/login-relay")
        assert resp.status_code == 302
        assert "auth/realms" in resp.headers["location"]

    def test_sets_oauth_state_cookie(self):
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
    def test_missing_state_cookie_returns_400(self):
        resp = client.get("/login-relay/callback?code=abc&state=xyz")
        assert resp.status_code == 400

    def test_missing_code_returns_400(self):
        nonce = "testnonce"
        return_to_b64 = base64.urlsafe_b64encode(b"/user1/lab").decode()
        c = TestClient(app, follow_redirects=False, cookies={"oauth_state": f"{nonce}:{return_to_b64}"})
        assert c.get(f"/login-relay/callback?state={nonce}").status_code == 400

    def test_state_mismatch_returns_400(self):
        return_to_b64 = base64.urlsafe_b64encode(b"/user1/lab").decode()
        c = TestClient(app, follow_redirects=False, cookies={"oauth_state": f"correct:{return_to_b64}"})
        assert c.get("/login-relay/callback?code=abc&state=wrong").status_code == 400

    def test_success_sets_cookie_and_redirects(self):
        nonce = "testnonce123"
        return_to_b64 = base64.urlsafe_b64encode(b"/user1/lab").decode()
        c = TestClient(app, follow_redirects=False, cookies={"oauth_state": f"{nonce}:{return_to_b64}"})

        with patch("main._fetch_access_token", new=AsyncMock(return_value="fake-token")):
            resp = c.get(f"/login-relay/callback?code=authcode&state={nonce}")

        assert resp.status_code == 302
        assert resp.headers["location"] == "/user1/lab"
        assert "dtaas_access_token" in resp.headers.get("set-cookie", "")

    def test_unknown_return_to_falls_back_to_root(self):
        nonce = "testnonce456"
        return_to_b64 = base64.urlsafe_b64encode(b"/user3/lab").decode()
        c = TestClient(app, follow_redirects=False, cookies={"oauth_state": f"{nonce}:{return_to_b64}"})

        with patch("main._fetch_access_token", new=AsyncMock(return_value="fake-token")):
            resp = c.get(f"/login-relay/callback?code=authcode&state={nonce}")

        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
