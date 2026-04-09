"""Unit tests for the Python Keycloak REST configurator."""
# pylint: disable=duplicate-code

from __future__ import annotations

from urllib.parse import parse_qs
import unittest

try:
    from workspaces.test.dtaas.keycloak.configure_keycloak_rest import (
        KeycloakRestConfigurator,
        MAPPERS,
        Settings,
        normalize_path,
    )
except ImportError:
    from configure_keycloak_rest import (
        KeycloakRestConfigurator,
        MAPPERS,
        Settings,
        normalize_path,
    )


class FakeConfigurator(KeycloakRestConfigurator):
    """Test double that records writes and returns canned API responses."""

    def __init__(self) -> None:
        super().__init__(Settings(keycloak_shared_scope_name="test-shared"))
        self.responses: dict[str, list[object]] = {}
        self.calls: list[tuple[str, str, object | None]] = []

    def push(self, url: str, payload: object) -> None:
        """Queue a canned response for the given URL."""
        self.responses.setdefault(url, []).append(payload)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _request_json(  # type: ignore[override]
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str = "application/json",
        token: str | None = None,
    ) -> object:
        """Record the call and return the next queued response."""
        self.calls.append((method, url, data))
        queue = self.responses.get(url, [])
        if queue:
            return queue.pop(0)
        return []


class NormalizePathTests(unittest.TestCase):
    """Tests for the normalize_path helper."""

    def test_normalize_path_root_and_empty(self) -> None:
        """Root paths and empty strings should normalize to empty."""
        self.assertEqual(normalize_path(""), "")
        self.assertEqual(normalize_path("/"), "")

    def test_normalize_path_trailing_slash(self) -> None:
        """Trailing slashes should be stripped; non-slash paths stay unchanged."""
        self.assertEqual(normalize_path("/auth/"), "/auth")
        self.assertEqual(normalize_path("/auth"), "/auth")


class ConfiguratorBehaviorTests(unittest.TestCase):
    """Behavioural unit tests for KeycloakRestConfigurator via FakeConfigurator."""

    def setUp(self) -> None:
        self.config = FakeConfigurator()
        self.realm = self.config.settings.keycloak_realm
        self.admin_url = self.config.admin_url

    def test_get_or_create_scope_id_reuses_existing(self) -> None:
        """Existing scope is reused without creating a new one."""
        name = self.config.settings.keycloak_shared_scope_name
        url = f"{self.admin_url}/{self.realm}/client-scopes?q={name}"
        self.config.push(url, [{"name": name, "id": "scope-1"}])

        scope_id = self.config.get_or_create_scope_id("token")

        self.assertEqual(scope_id, "scope-1")
        created_scope = any(
            call[0] == "POST" and call[1].endswith("/client-scopes")
            for call in self.config.calls
        )
        self.assertFalse(created_scope)

    def test_get_or_create_scope_id_creates_when_missing(self) -> None:
        """Scope is created via POST when not already present."""
        name = self.config.settings.keycloak_shared_scope_name
        query_url = f"{self.admin_url}/{self.realm}/client-scopes?q={name}"
        create_url = f"{self.admin_url}/{self.realm}/client-scopes"

        self.config.push(query_url, [])
        self.config.push(create_url, {})
        self.config.push(query_url, [{"name": name, "id": "scope-2"}])

        scope_id = self.config.get_or_create_scope_id("token")

        self.assertEqual(scope_id, "scope-2")
        created_scope = any(
            call[0] == "POST" and call[1] == create_url
            for call in self.config.calls
        )
        self.assertTrue(created_scope)

    def test_ensure_mapper_replaces_existing_mapper(self) -> None:
        """Existing mapper is updated in-place rather than created again."""
        endpoint = (
            f"{self.admin_url}/{self.realm}/client-scopes/scope-1"
            "/protocol-mappers/models"
        )
        self.config.push(endpoint, [{"name": "profile", "id": "mapper-1"}])
        self.config.push(f"{endpoint}/mapper-1", {})

        self.config.ensure_mapper("token", "scope-1", {"name": "profile"})

        updated_mapper = any(
            call[0] == "PUT" and call[1] == f"{endpoint}/mapper-1"
            for call in self.config.calls
        )
        created_mapper = any(
            call[0] == "POST" and call[1] == endpoint
            for call in self.config.calls
        )
        self.assertTrue(updated_mapper)
        self.assertFalse(created_mapper)

    def test_mapper_definitions_include_expected_claim_contract(self) -> None:
        """Validate claim names and emission targets used by mapper definitions."""
        by_name = {mapper["name"]: mapper for mapper in MAPPERS}

        self.assertIn("profile", by_name)
        self.assertEqual(set(by_name), {"profile"})

        profile_cfg = by_name["profile"]["config"]
        self.assertEqual(profile_cfg.get("claim.name"), "profile")
        self.assertEqual(profile_cfg.get("access.token.claim"), "false")
        self.assertEqual(profile_cfg.get("userinfo.token.claim"), "true")

    def test_get_access_token_uses_client_credentials_if_configured(self) -> None:
        """Client credentials grant is used when client ID and secret are set."""
        configured = FakeConfigurator()
        configured.settings = Settings(
            keycloak_admin_client_id="admin-client",
            keycloak_admin_client_secret="admin-secret",
        )
        configured.server_url = (
            f"{configured.settings.keycloak_base_url}"
            f"{normalize_path(configured.settings.keycloak_context_path)}"
        )

        token_url = (
            f"{configured.server_url}/realms/master/protocol/openid-connect/token"
        )
        configured.push(token_url, {"access_token": "tok"})

        token = configured.get_access_token()

        self.assertEqual(token, "tok")
        post_call = next(call for call in configured.calls if call[1] == token_url)
        encoded = post_call[2].decode("utf-8")
        parsed = parse_qs(encoded)
        self.assertEqual(parsed.get("grant_type"), ["client_credentials"])
        self.assertEqual(parsed.get("client_id"), ["admin-client"])
        self.assertEqual(parsed.get("client_secret"), ["admin-secret"])

    def test_ensure_scope_assigned_is_noop_if_already_assigned(self) -> None:
        """Scope assignment is skipped if the scope is already present."""
        url = (
            f"{self.admin_url}/{self.realm}/clients/client-1/default-client-scopes"
        )
        self.config.push(url, [{"id": "scope-1"}])

        self.config.ensure_scope_assigned("token", "client-1", "scope-1")

        put_calls = [call for call in self.config.calls if call[0] == "PUT"]
        self.assertEqual(put_calls, [])

    def test_ensure_mapper_on_client_creates_new_mapper(self) -> None:
        """Mapper is created directly on the client when none exists."""
        endpoint = (
            f"{self.admin_url}/{self.realm}/clients/client-1"
            "/protocol-mappers/models"
        )
        self.config.push(endpoint, [])

        self.config.ensure_mapper_on_client("token", "client-1", {"name": "profile"})

        post_call = any(
            call[0] == "POST" and call[1] == endpoint
            for call in self.config.calls
        )
        self.assertTrue(post_call)

    def test_ensure_mapper_on_client_updates_existing_mapper(self) -> None:
        """Existing client mapper is updated in-place rather than duplicated."""
        endpoint = (
            f"{self.admin_url}/{self.realm}/clients/client-1"
            "/protocol-mappers/models"
        )
        self.config.push(endpoint, [{"name": "profile", "id": "mapper-2"}])
        self.config.push(f"{endpoint}/mapper-2", {})

        self.config.ensure_mapper_on_client("token", "client-1", {"name": "profile"})

        put_call = any(
            call[0] == "PUT" and call[1] == f"{endpoint}/mapper-2"
            for call in self.config.calls
        )
        created = any(
            call[0] == "POST" and call[1] == endpoint
            for call in self.config.calls
        )
        self.assertTrue(put_call)
        self.assertFalse(created)

if __name__ == "__main__":
    unittest.main()
