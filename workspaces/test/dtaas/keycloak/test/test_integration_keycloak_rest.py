"""Integration tests for Keycloak REST configurator against a real Keycloak."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid

from .container_helpers import (
    container_logs_tail,
    container_running,
    docker_run_keycloak,
    remove_container,
)
from .integration_helpers import (
    admin_token,
    create_client,
    create_realm,
    create_user,
    find_free_port,
    http_json,
    set_user_password,
    user_token,
    userinfo,
)
from .integration_setup import (
    create_admin_service_account_client,
    wait_for_admin_roles_client,
    wait_for_client_availability,
    wait_until_ready,
)

REQUIRED_MAPPERS = {"profile"}


class _ContainerChecker:
    """Adapter for container state and logs used by readiness checks."""

    @staticmethod
    def running(container_name: str) -> bool:
        """Return whether a container is running."""
        return container_running(container_name)

    @staticmethod
    def logs(container_name: str) -> str:
        """Return a short logs tail for a container."""
        return container_logs_tail(container_name)


@unittest.skipUnless(
    os.getenv("RUN_KEYCLOAK_INTEGRATION") == "1",
    "Set RUN_KEYCLOAK_INTEGRATION=1 to run real Keycloak integration tests.",
)
class KeycloakIntegrationTests(unittest.TestCase):
    """Run end-to-end claims configuration against real Keycloak container."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create and bootstrap the temporary Keycloak test environment."""
        cls._build_runtime_settings()
        cls._start_and_prepare_keycloak()

    @classmethod
    def _build_runtime_settings(cls) -> None:
        """Initialize deterministic per-run identifiers and timeout values."""
        cls.admin_user = f"admin-{uuid.uuid4().hex[:8]}"
        cls.admin_password = uuid.uuid4().hex
        cls.container_name = f"keycloak-int-{uuid.uuid4().hex[:8]}"
        configured_port = os.getenv("KEYCLOAK_INTEGRATION_PORT", "")
        cls.port = int(configured_port) if configured_port else find_free_port()
        cls.base_url = f"http://localhost:{cls.port}"
        cls.realm = f"dtaas-int-{uuid.uuid4().hex[:6]}"
        cls.target_client_id = f"dtaas-workspace-{uuid.uuid4().hex[:6]}"
        cls.admin_client_id = f"dtaas-admin-automation-{uuid.uuid4().hex[:6]}"
        cls.username = f"alice-{uuid.uuid4().hex[:4]}"
        cls.user_password = uuid.uuid4().hex
        cls.clean_username = f"bob-{uuid.uuid4().hex[:4]}"
        cls.clean_user_password = uuid.uuid4().hex
        cls.startup_timeout = int(os.getenv("KEYCLOAK_INTEGRATION_TIMEOUT", "300"))

    @classmethod
    def _start_and_prepare_keycloak(cls) -> None:
        """Start container and seed realm, client, users, and admin service client."""
        docker_run_keycloak(cls.container_name, cls.port, cls.admin_user, cls.admin_password)
        try:
            cls._seed_keycloak_data()
        except Exception:
            cls.cleanup_container()
            raise

    @classmethod
    def _seed_keycloak_data(cls) -> None:
        """Create realm/client/users and grant service-account roles."""
        wait_until_ready(cls.base_url, cls.container_name, cls.startup_timeout, _ContainerChecker)
        token = admin_token(cls.base_url, cls.admin_user, cls.admin_password)
        wait_timeout = int(os.getenv("KEYCLOAK_CLIENT_AVAILABILITY_TIMEOUT", "180"))
        wait_for_admin_roles_client(cls.base_url, token, "master", timeout=wait_timeout)
        create_realm(cls.base_url, token, cls.realm)
        create_client(cls.base_url, token, cls.realm, cls.target_client_id)
        cls._seed_users(token)
        _, cls.admin_client_secret = create_admin_service_account_client(
            cls.base_url, token, cls.admin_client_id
        )

    @classmethod
    def _seed_users(cls, token: str) -> None:
        """Create one mapped and one clean user for profile update checks."""
        mapped_user_id = create_user(
            cls.base_url,
            token,
            cls.realm,
            cls.username,
            attributes={"profile": [f"https://localhost/{cls.username}"]},
        )
        set_user_password(cls.base_url, token, cls.realm, mapped_user_id, cls.user_password)
        clean_user_id = create_user(cls.base_url, token, cls.realm, cls.clean_username)
        set_user_password(
            cls.base_url,
            token,
            cls.realm,
            clean_user_id,
            cls.clean_user_password,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        """Always cleanup the temporary Keycloak container."""
        cls.cleanup_container()

    @classmethod
    def cleanup_container(cls) -> None:
        """Best-effort removal of integration-test container."""
        remove_container(cls.container_name)

    def test_script_configures_claims_via_service_account(self) -> None:
        """Validate end-to-end claims setup via service-account auth path."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", encoding="utf-8"
        ) as fh:
            fh.write(self._env_content())
            fh.flush()
            self._run_configuration_script(fh.name)

        token = admin_token(self.base_url, self.admin_user, self.admin_password)
        wait_for_client_availability(
            self.base_url,
            token,
            self.realm,
            self.target_client_id,
            timeout=60,
        )
        self._assert_mapper_presence(token)
        self._assert_userinfo_profile_claim()

    def _env_content(self) -> str:
        """Build the env file content consumed by the CLI script."""
        return (
            f"KEYCLOAK_BASE_URL={self.base_url}\n"
            f"KEYCLOAK_CONTEXT_PATH=/\n"
            f"KEYCLOAK_REALM={self.realm}\n"
            f"KEYCLOAK_MAPPER_CLIENT_ID={self.target_client_id}\n"
            f"KEYCLOAK_ADMIN_CLIENT_ID={self.admin_client_id}\n"
            f"KEYCLOAK_ADMIN_CLIENT_SECRET={self.admin_client_secret}\n"
            f"KEYCLOAK_PROFILE_BASE_URL=https://localhost\n"
            f"KEYCLOAK_USER_PROFILES=[\"{self.username}\"]\n"
        )

    def _run_configuration_script(self, env_file: str) -> None:
        """Execute configurator module with generated env file."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "workspaces.test.dtaas.keycloak.src.keycloak_rest",
                "--env-file",
                env_file,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def _assert_mapper_presence(self, token: str) -> None:
        """Verify required mappers exist on client or assigned shared scope."""
        clients = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/clients?clientId={self.target_client_id}",
            token=token,
        )
        client_uuid = clients[0]["id"]
        client_mappers = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/clients/{client_uuid}/protocol-mappers/models",
            token=token,
        )
        client_mapper_names = {mapper["name"] for mapper in client_mappers}
        if REQUIRED_MAPPERS.issubset(client_mapper_names):
            return

        default_scopes = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/clients/{client_uuid}/default-client-scopes",
            token=token,
        )
        for scope in default_scopes:
            scope_id = scope.get("id")
            if not scope_id:
                continue
            scope_mappers = http_json(
                f"{self.base_url}/admin/realms/{self.realm}/client-scopes/{scope_id}/protocol-mappers/models",
                token=token,
            )
            scope_mapper_names = {mapper["name"] for mapper in scope_mappers}
            if REQUIRED_MAPPERS.issubset(scope_mapper_names):
                return

        self.fail(
            "Required mappers missing from client and assigned default scopes. "
            f"client={sorted(client_mapper_names)}"
        )

    def _assert_userinfo_profile_claim(self) -> None:
        """Validate profile claim for mapped user via token and userinfo endpoint."""
        access_token = user_token(
            self.base_url,
            self.realm,
            self.target_client_id,
            self.username,
            self.user_password,
        )
        payload = self._decode_token_payload(access_token)
        self.assertEqual(payload.get("preferred_username"), self.username)

        user_info = userinfo(self.base_url, self.realm, access_token)
        self.assertEqual(user_info.get("profile"), f"https://localhost/{self.username}")
        self.assertEqual(user_info.get("preferred_username"), self.username)

    def _decode_token_payload(self, access_token: str) -> dict[str, str]:
        """Decode JWT payload section for basic claim assertions."""
        token_payload = access_token.split(".")[1]
        token_payload += "=" * ((4 - len(token_payload) % 4) % 4)
        raw = base64.urlsafe_b64decode(token_payload).decode("utf-8")
        return json.loads(raw)


if __name__ == "__main__":
    unittest.main()
