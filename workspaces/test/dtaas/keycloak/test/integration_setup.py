"""Higher-level integration setup helpers for Keycloak tests."""

from __future__ import annotations

import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .integration_helpers import (
    http_json,
    resolve_admin_roles_client,
    resolve_client_uuid,
)


def wait_until_ready(base_url: str, container_name: str, timeout: int, checker: Any) -> None:
    """Wait for Keycloak readiness endpoint with diagnostics on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not checker.running(container_name):
            logs = checker.logs(container_name)
            raise RuntimeError("Keycloak container exited before becoming ready.\n" f"Recent logs:\n{logs}")
        if _ready(base_url):
            return
        time.sleep(3)
    logs = checker.logs(container_name)
    raise RuntimeError(f"Keycloak did not become ready in {timeout}s.\nRecent logs:\n{logs}")


def _ready(base_url: str) -> bool:
    """Probe known Keycloak readiness endpoints."""
    return _probe(f"{base_url}/health/ready") or _probe(f"{base_url}/realms/master")


def _probe(url: str) -> bool:
    """Return true when a URL can be opened successfully."""
    try:
        with urlopen(url, timeout=5):
            return True
    except HTTPError as exc:
        exc.close()
    except (URLError, ConnectionResetError, TimeoutError, OSError):
        pass
    return False


def wait_for_admin_roles_client(
    base_url: str,
    token: str,
    realm: str = "master",
    timeout: int = 60,
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
    base_url: str,
    token: str,
    realm: str,
    client_id: str,
    timeout: int = 60,
) -> None:
    """Wait for a client to be available in Keycloak."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            resolve_client_uuid(base_url, token, realm, client_id)
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(1)
    preview = _visible_clients_preview(base_url, token, realm)
    if last_error:
        raise RuntimeError(
            f"{last_error} after waiting {timeout}s. "
            f"Visible clients in realm '{realm}': {preview}"
        ) from last_error
    raise RuntimeError(f"Timeout waiting for client '{client_id}' in realm '{realm}'")


def _visible_clients_preview(base_url: str, token: str, realm: str) -> str:
    """Build a short preview of visible realm clients for diagnostics."""
    try:
        clients = http_json(f"{base_url}/admin/realms/{realm}/clients?max=200", token=token)
    except RuntimeError:
        return "<none>"
    visible = [str(c.get("clientId", "")) for c in clients if c.get("clientId")]
    visible.sort()
    return ", ".join(visible[:25]) if visible else "<none>"


def create_admin_service_account_client(
    base_url: str,
    token: str,
    client_id: str,
) -> tuple[str, str]:
    """Create service-account admin client and grant required roles."""
    client_uuid = _create_admin_client(base_url, token, client_id)
    secret = _client_secret(base_url, token, client_uuid)
    user_id = _service_account_user_id(base_url, token, client_uuid)
    realm_mgmt_id = resolve_admin_roles_client(base_url, token, "master")[1]
    _assign_management_roles(base_url, token, user_id, realm_mgmt_id)
    _assign_master_admin_role(base_url, token, user_id)
    return client_id, secret


def _create_admin_client(base_url: str, token: str, client_id: str) -> str:
    """Create admin automation client and return its UUID."""
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
    clients = http_json(f"{base_url}/admin/realms/master/clients?clientId={client_id}", token=token)
    return clients[0]["id"]


def _client_secret(base_url: str, token: str, client_uuid: str) -> str:
    """Fetch the generated secret for a client UUID."""
    payload = http_json(
        f"{base_url}/admin/realms/master/clients/{client_uuid}/client-secret",
        token=token,
    )
    return payload["value"]


def _service_account_user_id(base_url: str, token: str, client_uuid: str) -> str:
    """Resolve service-account user id for a client UUID."""
    payload = http_json(
        f"{base_url}/admin/realms/master/clients/{client_uuid}/service-account-user",
        token=token,
    )
    return payload["id"]


def _assign_management_roles(
    base_url: str,
    token: str,
    service_user_id: str,
    realm_mgmt_id: str,
) -> None:
    """Assign required client roles in realm-management."""
    roles_to_assign = _roles_to_assign(base_url, token, realm_mgmt_id)
    http_json(
        f"{base_url}/admin/realms/master/users/{service_user_id}/role-mappings/clients/{realm_mgmt_id}",
        method="POST",
        token=token,
        data=roles_to_assign,
    )


def _roles_to_assign(base_url: str, token: str, realm_mgmt_id: str) -> list[dict[str, Any]]:
    """Build the list of role representations for service-account grants."""
    roles: list[dict[str, Any]] = []
    for role_name in ["manage-clients", "view-clients", "manage-users", "view-users", "manage-realm"]:
        role = http_json(
            f"{base_url}/admin/realms/master/clients/{realm_mgmt_id}/roles/{role_name}",
            token=token,
        )
        roles.append({"id": role["id"], "name": role["name"], "clientRole": True})
    return roles


def _assign_master_admin_role(base_url: str, token: str, service_user_id: str) -> None:
    """Assign master realm admin role for cross-realm admin actions."""
    admin_realm_role = http_json(f"{base_url}/admin/realms/master/roles/admin", token=token)
    http_json(
        f"{base_url}/admin/realms/master/users/{service_user_id}/role-mappings/realm",
        method="POST",
        token=token,
        data=[{"id": admin_realm_role["id"], "name": admin_realm_role["name"]}],
    )
