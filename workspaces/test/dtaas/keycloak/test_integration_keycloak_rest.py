"""Integration tests for configure_keycloak_rest.py against a real Keycloak."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import unittest
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REQUIRED_MAPPERS = {"profile", "groups", "groups_owner", "sub_legacy"}


def find_free_port() -> int:
    """Return a free TCP port allocated by the host OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(
    url: str,
    method: str = "GET",
    token: str | None = None,
    data: dict[str, Any] | None = None,
    content_type: str = "application/json",
) -> Any:
    headers: dict[str, str] = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    if data is not None:
        if content_type == "application/x-www-form-urlencoded":
            body = urlencode(data).encode("utf-8")
        else:
            body = json.dumps(data).encode("utf-8")

    request = Request(url, method=method, headers=headers, data=body)
    with urlopen(request) as response:  # noqa: S310 - integration test target is controlled
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def admin_token(base_url: str, username: str, password: str) -> str:
    response = http_json(
        f"{base_url}/realms/master/protocol/openid-connect/token",
        method="POST",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        },
        content_type="application/x-www-form-urlencoded",
    )
    token = response.get("access_token", "")
    if not token:
        raise RuntimeError("Failed to retrieve admin token for integration setup")
    return token


def create_realm(base_url: str, token: str, realm: str) -> None:
    http_json(
        f"{base_url}/admin/realms",
        method="POST",
        token=token,
        data={"realm": realm, "enabled": True},
    )


def create_client(base_url: str, token: str, realm: str, client_id: str) -> str:
    http_json(
        f"{base_url}/admin/realms/{realm}/clients",
        method="POST",
        token=token,
        data={
            "clientId": client_id,
            "protocol": "openid-connect",
            "enabled": True,
            "publicClient": True,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": True,
            "redirectUris": ["*"],
        },
    )
    clients = http_json(
        f"{base_url}/admin/realms/{realm}/clients?clientId={client_id}", token=token
    )
    return clients[0]["id"]


def create_user(base_url: str, token: str, realm: str, username: str) -> str:
    http_json(
        f"{base_url}/admin/realms/{realm}/users",
        method="POST",
        token=token,
        data={
            "username": username,
            "enabled": True,
            "attributes": {"department": ["eng"]},
        },
    )
    users = http_json(
        f"{base_url}/admin/realms/{realm}/users?username={username}", token=token
    )
    return users[0]["id"]


def resolve_client_uuid(base_url: str, token: str, realm: str, client_id: str) -> str:
    """Resolve internal client UUID from public clientId."""
    queried = http_json(
        f"{base_url}/admin/realms/{realm}/clients?clientId={client_id}", token=token
    )
    if queried:
        return queried[0]["id"]

    clients = http_json(
        f"{base_url}/admin/realms/{realm}/clients?max=500", token=token
    )
    for client in clients:
        if client.get("clientId") == client_id:
            return client["id"]
    raise RuntimeError(f"Could not resolve client UUID for clientId '{client_id}'")


def create_admin_service_account_client(
    base_url: str, token: str, client_id: str
) -> tuple[str, str]:
    http_json(
        f"{base_url}/admin/realms/master/clients",
        method="POST",
        token=token,
        data={
            "clientId": client_id,
            "protocol": "openid-connect",
            "enabled": True,
            "publicClient": False,
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
        },
    )

    clients = http_json(
        f"{base_url}/admin/realms/master/clients?clientId={client_id}", token=token
    )
    client_uuid = clients[0]["id"]

    secret_payload = http_json(
        f"{base_url}/admin/realms/master/clients/{client_uuid}/client-secret",
        token=token,
    )
    client_secret = secret_payload["value"]

    service_account_user = http_json(
        f"{base_url}/admin/realms/master/clients/{client_uuid}/service-account-user",
        token=token,
    )
    service_account_user_id = service_account_user["id"]

    realm_mgmt_id = resolve_client_uuid(base_url, token, "master", "realm-management")

    roles_to_assign: list[dict[str, Any]] = []
    for role_name in [
        "manage-clients",
        "view-clients",
        "manage-users",
        "view-users",
        "manage-realm",
    ]:
        role = http_json(
            f"{base_url}/admin/realms/master/clients/{realm_mgmt_id}/roles/{role_name}",
            token=token,
        )
        roles_to_assign.append(
            {"id": role["id"], "name": role["name"], "clientRole": True}
        )

    http_json(
        f"{base_url}/admin/realms/master/users/{service_account_user_id}"
        f"/role-mappings/clients/{realm_mgmt_id}",
        method="POST",
        token=token,
        data=roles_to_assign,
    )

    return client_id, client_secret


@unittest.skipUnless(
    os.getenv("RUN_KEYCLOAK_INTEGRATION") == "1",
    "Set RUN_KEYCLOAK_INTEGRATION=1 to run real Keycloak integration tests.",
)
class KeycloakIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.admin_user = "admin"
        cls.admin_password = "admin"
        cls.container_name = f"keycloak-int-{uuid.uuid4().hex[:8]}"
        configured_port = os.getenv("KEYCLOAK_INTEGRATION_PORT", "")
        cls.port = int(configured_port) if configured_port else find_free_port()
        cls.base_url = f"http://localhost:{cls.port}"
        cls.realm = f"dtaas-int-{uuid.uuid4().hex[:6]}"
        cls.target_client_id = f"dtaas-workspace-{uuid.uuid4().hex[:6]}"
        cls.admin_client_id = f"dtaas-admin-automation-{uuid.uuid4().hex[:6]}"
        cls.username = f"alice-{uuid.uuid4().hex[:4]}"
        cls.startup_timeout = int(os.getenv("KEYCLOAK_INTEGRATION_TIMEOUT", "300"))

        cls.start_container()
        try:
            cls.wait_until_ready()

            token = admin_token(cls.base_url, cls.admin_user, cls.admin_password)
            create_realm(cls.base_url, token, cls.realm)
            create_client(cls.base_url, token, cls.realm, cls.target_client_id)
            create_user(cls.base_url, token, cls.realm, cls.username)
            _, cls.admin_client_secret = create_admin_service_account_client(
                cls.base_url, token, cls.admin_client_id
            )
        except Exception:
            cls.cleanup_container()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.cleanup_container()

    @classmethod
    def cleanup_container(cls) -> None:
        subprocess.run(
            ["docker", "rm", "-f", cls.container_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def start_container(cls) -> None:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                cls.container_name,
                "-p",
                f"{cls.port}:8080",
                "-e",
                f"KC_BOOTSTRAP_ADMIN_USERNAME={cls.admin_user}",
                "-e",
                f"KC_BOOTSTRAP_ADMIN_PASSWORD={cls.admin_password}",
                "quay.io/keycloak/keycloak:26.0.7",
                "start-dev",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start Keycloak container: {result.stderr}")

    @classmethod
    def wait_until_ready(cls) -> None:
        deadline = time.time() + cls.startup_timeout
        while time.time() < deadline:
            if not cls.container_running():
                logs = cls.container_logs_tail()
                raise RuntimeError(
                    "Keycloak container exited before becoming ready.\n"
                    f"Recent logs:\n{logs}"
                )
            try:
                with urlopen(f"{cls.base_url}/health/ready", timeout=5):
                    return
            except (HTTPError, URLError, ConnectionResetError, TimeoutError, OSError):
                try:
                    with urlopen(f"{cls.base_url}/realms/master", timeout=5):
                        return
                except (HTTPError, URLError, ConnectionResetError, TimeoutError, OSError):
                    time.sleep(3)
        logs = cls.container_logs_tail()
        raise RuntimeError(
            f"Keycloak did not become ready in {cls.startup_timeout}s.\n"
            f"Recent logs:\n{logs}"
        )

    @classmethod
    def container_running(cls) -> bool:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", cls.container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    @classmethod
    def container_logs_tail(cls) -> str:
        result = subprocess.run(
            ["docker", "logs", "--tail", "80", cls.container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout or result.stderr or "<no logs available>"

    def test_script_configures_claims_via_service_account(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "KEYCLOAK_BASE_URL": self.base_url,
                "KEYCLOAK_CONTEXT_PATH": "/",
                "KEYCLOAK_REALM": self.realm,
                "KEYCLOAK_CLIENT_ID": self.target_client_id,
                "KEYCLOAK_ADMIN_CLIENT_ID": self.admin_client_id,
                "KEYCLOAK_ADMIN_CLIENT_SECRET": self.admin_client_secret,
                "PROFILE_BASE_URL": "https://localhost/gitlab",
            }
        )

        result = subprocess.run(
            ["py", "workspaces/test/dtaas/keycloak/configure_keycloak_rest.py"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        token = admin_token(self.base_url, self.admin_user, self.admin_password)

        scopes = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/client-scopes"
            "?q=dtaas-shared",
            token=token,
        )
        scope = next((item for item in scopes if item.get("name") == "dtaas-shared"), None)
        self.assertIsNotNone(scope)
        scope_id = scope["id"]

        mappers = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/client-scopes/{scope_id}"
            "/protocol-mappers/models",
            token=token,
        )
        names = {mapper["name"] for mapper in mappers}
        self.assertTrue(REQUIRED_MAPPERS.issubset(names))

        clients = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/clients"
            f"?clientId={self.target_client_id}",
            token=token,
        )
        client_uuid = clients[0]["id"]

        defaults = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/clients/{client_uuid}"
            "/default-client-scopes",
            token=token,
        )
        self.assertIn(scope_id, {item["id"] for item in defaults})

        users = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/users?username={self.username}",
            token=token,
        )
        user_id = users[0]["id"]
        user_details = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}", token=token
        )
        attributes = user_details.get("attributes", {})
        self.assertEqual(attributes.get("department"), ["eng"])
        self.assertEqual(
            attributes.get("profile"), [f"https://localhost/gitlab/{self.username}"]
        )


if __name__ == "__main__":
    unittest.main()
