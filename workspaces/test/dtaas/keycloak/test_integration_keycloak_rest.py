"""Integration tests for configure_keycloak_rest.py against a real Keycloak."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import base64
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REQUIRED_MAPPERS = {"profile"}


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
    """Execute an HTTP request and parse JSON response payload."""
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
    try:
        # noqa: S310 - integration test target is controlled
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        with exc:
            error_body = exc.read().decode("utf-8")
        raise RuntimeError(
            f"HTTP {exc.code} from {url}: {error_body}"
        ) from exc


def admin_token(base_url: str, username: str, password: str) -> str:
    """Request admin token for the temporary Keycloak instance."""
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
    """Create the test realm used by the integration flow."""
    http_json(
        f"{base_url}/admin/realms",
        method="POST",
        token=token,
        data={"realm": realm, "enabled": True},
    )


def create_client(base_url: str, token: str, realm: str, client_id: str) -> str:
    """Create target client and return the internal Keycloak UUID."""
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


def create_user(
    base_url: str,
    token: str,
    realm: str,
    username: str,
    attributes: dict[str, list[str]] | None = None,
) -> str:
    """Create a test user."""
    payload: dict[str, Any] = {
        "username": username,
        "email": f"{username}@test.local",
        "firstName": "Test",
        "lastName": "User",
        "enabled": True,
        "emailVerified": True,
        "requiredActions": [],
    }
    if attributes:
        payload["attributes"] = attributes

    http_json(
        f"{base_url}/admin/realms/{realm}/users",
        method="POST",
        token=token,
        data=payload,
    )
    users = http_json(
        f"{base_url}/admin/realms/{realm}/users?username={username}", token=token
    )
    return users[0]["id"]


def set_user_password(
    base_url: str, token: str, realm: str, user_id: str, password: str
) -> None:
    """Set non-temporary password for the test user."""
    http_json(
        f"{base_url}/admin/realms/{realm}/users/{user_id}/reset-password",
        method="PUT",
        token=token,
        data={"type": "password", "value": password, "temporary": False},
    )


def ensure_group(base_url: str, token: str, realm: str, group_name: str) -> str:
    """Ensure a group exists and return its id."""
    existing = http_json(
        f"{base_url}/admin/realms/{realm}/groups?search={group_name}", token=token
    )
    for group in existing:
        if group.get("name") == group_name and group.get("id"):
            return group["id"]

    http_json(
        f"{base_url}/admin/realms/{realm}/groups",
        method="POST",
        token=token,
        data={"name": group_name},
    )
    created = http_json(
        f"{base_url}/admin/realms/{realm}/groups?search={group_name}", token=token
    )
    for group in created:
        if group.get("name") == group_name and group.get("id"):
            return group["id"]
    raise RuntimeError(f"Could not resolve group id for '{group_name}'")


def add_user_to_group(
    base_url: str, token: str, realm: str, user_id: str, group_id: str
) -> None:
    """Add user to group for groups claim assertions."""
    http_json(
        f"{base_url}/admin/realms/{realm}/users/{user_id}/groups/{group_id}",
        method="PUT",
        token=token,
    )


def user_token(
    base_url: str, realm: str, client_id: str, username: str, password: str
) -> str:
    """Request user access token using direct access grant in integration env."""
    response = http_json(
        f"{base_url}/realms/{realm}/protocol/openid-connect/token",
        method="POST",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
            "scope": "openid profile",
        },
        content_type="application/x-www-form-urlencoded",
    )
    token = response.get("access_token", "")
    if not token:
        raise RuntimeError("Failed to retrieve user access token")
    return token


def userinfo(base_url: str, realm: str, access_token: str) -> dict[str, Any]:
    """Fetch userinfo claims for the provided access token."""
    payload = http_json(
        f"{base_url}/realms/{realm}/protocol/openid-connect/userinfo",
        token=access_token,
    )
    return payload if isinstance(payload, dict) else {}


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


def resolve_admin_roles_client(
    base_url: str, token: str, realm: str = "master"
) -> tuple[str, str]:
    """Resolve the admin-roles client across Keycloak version differences."""
    clients = http_json(
        f"{base_url}/admin/realms/{realm}/clients?max=500", token=token
    )
    for candidate in ["realm-management", "master-realm"]:
        for client in clients:
            if client.get("clientId") == candidate and client.get("id"):
                return candidate, client["id"]

    visible = sorted(
        str(client.get("clientId", "")) for client in clients if client.get("clientId")
    )
    preview = ", ".join(visible[:25]) if visible else "<none>"
    raise RuntimeError(
        "Could not resolve admin roles client in master realm. "
        f"Expected one of ['realm-management', 'master-realm']. Visible: {preview}"
    )


def wait_for_admin_roles_client(
    base_url: str, token: str, realm: str = "master", timeout: int = 60
) -> None:
    """Wait for admin roles client to become available in Keycloak."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            resolve_admin_roles_client(base_url, token, realm)
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(1)

    if last_error:
        raise RuntimeError(f"{last_error} after waiting {timeout}s") from last_error
    raise RuntimeError(f"Timeout waiting for admin roles client in realm '{realm}'")


def wait_for_client_availability(
    base_url: str, token: str, realm: str, client_id: str, timeout: int = 60
) -> None:
    """Wait for a client to be available in Keycloak (e.g., realm-management)."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            resolve_client_uuid(base_url, token, realm, client_id)
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(1)
    visible_clients: list[str] = []
    try:
        clients = http_json(
            f"{base_url}/admin/realms/{realm}/clients?max=200", token=token
        )
        visible_clients = [
            str(client.get("clientId", ""))
            for client in clients
            if client.get("clientId")
        ]
    except RuntimeError:
        visible_clients = []

    visible_clients.sort()
    preview = ", ".join(visible_clients[:25]) if visible_clients else "<none>"
    if last_error:
        raise RuntimeError(
            f"{last_error} after waiting {timeout}s. "
            f"Visible clients in realm '{realm}': {preview}"
        ) from last_error
    raise RuntimeError(
        f"Timeout waiting for client '{client_id}' in realm '{realm}'"
    )


def create_admin_service_account_client(
    base_url: str, token: str, client_id: str
) -> tuple[str, str]:
    """Create service-account admin client and grant required realm roles."""
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

    _, realm_mgmt_id = resolve_admin_roles_client(base_url, token, "master")

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

    # Keycloak 26 requires master realm role mapping for cross-realm admin actions.
    admin_realm_role = http_json(
        f"{base_url}/admin/realms/master/roles/admin",
        token=token,
    )
    http_json(
        f"{base_url}/admin/realms/master/users/{service_account_user_id}"
        "/role-mappings/realm",
        method="POST",
        token=token,
        data=[
            {
                "id": admin_realm_role["id"],
                "name": admin_realm_role["name"],
            }
        ],
    )

    return client_id, client_secret


@unittest.skipUnless(
    os.getenv("RUN_KEYCLOAK_INTEGRATION") == "1",
    "Set RUN_KEYCLOAK_INTEGRATION=1 to run real Keycloak integration tests.",
)
class KeycloakIntegrationTests(unittest.TestCase):
    """Run end-to-end claims configuration against real Keycloak container."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create and bootstrap the temporary Keycloak test environment."""
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
        cls.group_name = "dtaas-users"
        cls.startup_timeout = int(os.getenv("KEYCLOAK_INTEGRATION_TIMEOUT", "300"))

        cls.start_container()
        try:
            cls.wait_until_ready()

            token = admin_token(cls.base_url, cls.admin_user, cls.admin_password)
            # Ensure built-in master realm admin roles client is available before proceeding
            client_wait_timeout = int(
                os.getenv("KEYCLOAK_CLIENT_AVAILABILITY_TIMEOUT", "180")
            )
            wait_for_admin_roles_client(
                cls.base_url,
                token,
                "master",
                timeout=client_wait_timeout,
            )
            create_realm(cls.base_url, token, cls.realm)
            create_client(cls.base_url, token, cls.realm, cls.target_client_id)
            user_id = create_user(
                cls.base_url,
                token,
                cls.realm,
                cls.username,
                attributes={"profile": [f"https://localhost/{cls.username}"]},
            )
            set_user_password(
                cls.base_url, token, cls.realm, user_id, cls.user_password,
            )
            clean_user_id = create_user(
                cls.base_url, token, cls.realm, cls.clean_username,
            )
            set_user_password(
                cls.base_url, token, cls.realm, clean_user_id, cls.clean_user_password,
            )
            _, cls.admin_client_secret = create_admin_service_account_client(
                cls.base_url, token, cls.admin_client_id
            )
        except Exception:
            cls.cleanup_container()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        """Always cleanup the temporary Keycloak container."""
        cls.cleanup_container()

    @classmethod
    def cleanup_container(cls) -> None:
        """Best-effort removal of integration-test container."""
        subprocess.run(
            ["docker", "rm", "-f", cls.container_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def start_container(cls) -> None:
        """Start Keycloak container in dev mode for integration testing."""
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
        """Wait for Keycloak readiness endpoint with diagnostics on timeout."""
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
            except HTTPError as exc:
                exc.close()
            except (URLError, ConnectionResetError, TimeoutError, OSError):
                pass
            else:
                return
            try:
                with urlopen(f"{cls.base_url}/realms/master", timeout=5):
                    return
            except HTTPError as exc:
                exc.close()
            except (URLError, ConnectionResetError, TimeoutError, OSError):
                pass
            time.sleep(3)
        logs = cls.container_logs_tail()
        raise RuntimeError(
            f"Keycloak did not become ready in {cls.startup_timeout}s.\n"
            f"Recent logs:\n{logs}"
        )

    @classmethod
    def container_running(cls) -> bool:
        """Check whether integration-test container is still running."""
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", cls.container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    @classmethod
    def container_logs_tail(cls) -> str:
        """Return the most recent container logs for debugging output."""
        result = subprocess.run(
            ["docker", "logs", "--tail", "80", cls.container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout or result.stderr or "<no logs available>"

    def test_script_configures_claims_via_service_account(self) -> None:
        """Validate end-to-end claims setup via service-account auth path.

        Two users are exercised, one with a pre-seeded profile attribute.
        """
        # pylint: disable=too-many-locals
        env_content = (
            f"KEYCLOAK_BASE_URL={self.base_url}\n"
            f"KEYCLOAK_CONTEXT_PATH=/\n"
            f"KEYCLOAK_REALM={self.realm}\n"
            f"KEYCLOAK_CLIENT_ID={self.target_client_id}\n"
            f"KEYCLOAK_ADMIN_CLIENT_ID={self.admin_client_id}\n"
            f"KEYCLOAK_ADMIN_CLIENT_SECRET={self.admin_client_secret}\n"
            f"KEYCLOAK_PROFILE_BASE_URL=https://localhost\n"
            f"KEYCLOAK_USER_PROFILES=[\"test_user_1\"]\n"
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False, encoding="utf-8"
        ) as f:
            f.write(env_content)
            env_file = f.name

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "workspaces/test/dtaas/keycloak/configure_keycloak_rest.py",
                    "--env-file",
                    env_file,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
        finally:
            os.unlink(env_file)

        token = admin_token(self.base_url, self.admin_user, self.admin_password)

        clients = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/clients"
            f"?clientId={self.target_client_id}",
            token=token,
        )
        client_uuid = clients[0]["id"]

        mappers = http_json(
            f"{self.base_url}/admin/realms/{self.realm}/clients/{client_uuid}"
            "/protocol-mappers/models",
            token=token,
        )
        names = {mapper["name"] for mapper in mappers}
        self.assertTrue(REQUIRED_MAPPERS.issubset(names))

        access_token = user_token(
            self.base_url,
            self.realm,
            self.target_client_id,
            self.username,
            self.user_password,
        )
        token_payload = access_token.split(".")[1]
        token_payload += "=" * ((4 - len(token_payload) % 4) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(token_payload).decode("utf-8"))

        self.assertEqual(decoded.get("preferred_username"), self.username)

        user_info = userinfo(self.base_url, self.realm, access_token)
        self.assertEqual(
            user_info.get("profile"), f"https://localhost/{self.username}"
        )
        self.assertEqual(user_info.get("preferred_username"), self.username)


if __name__ == "__main__":
    unittest.main()
