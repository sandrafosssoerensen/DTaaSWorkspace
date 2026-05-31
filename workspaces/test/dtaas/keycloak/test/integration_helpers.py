"""Integration helper utilities for Keycloak REST tests."""

from __future__ import annotations

import json
import socket
import ssl
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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
    request = Request(
        url,
        method=method,
        headers=_headers(content_type, token),
        data=_body(data, content_type),
    )
    try:
        ctx = ssl.create_default_context()
        with urlopen(request, timeout=30, context=ctx) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}: {_error_body(exc)}") from exc


def _headers(content_type: str, token: str | None) -> dict[str, str]:
    """Build HTTP headers with optional bearer token."""
    headers: dict[str, str] = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _body(data: dict[str, Any] | None, content_type: str) -> bytes | None:
    """Encode payload for form or JSON content types."""
    if data is None:
        return None
    if content_type == "application/x-www-form-urlencoded":
        return urlencode(data).encode("utf-8")
    return json.dumps(data).encode("utf-8")


def _error_body(exc: HTTPError) -> str:
    """Read and return HTTP error payload text."""
    with exc:
        return exc.read().decode("utf-8")


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
            "redirectUris": ["http://localhost:8080/callback"],
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
    """Create a test user and return its id."""
    payload = _user_payload(username, attributes)
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


def _user_payload(
    username: str,
    attributes: dict[str, list[str]] | None,
) -> dict[str, Any]:
    """Build default test user payload with optional attributes."""
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
    return payload


def set_user_password(
    base_url: str,
    token: str,
    realm: str,
    user_id: str,
    password: str,
) -> None:
    """Set non-temporary password for the test user."""
    http_json(
        f"{base_url}/admin/realms/{realm}/users/{user_id}/reset-password",
        method="PUT",
        token=token,
        data={"type": "password", "value": password, "temporary": False},
    )


def resolve_client_uuid(base_url: str, token: str, realm: str, client_id: str) -> str:
    """Resolve internal client UUID from public clientId."""
    queried = http_json(
        f"{base_url}/admin/realms/{realm}/clients?clientId={client_id}", token=token
    )
    if queried:
        return queried[0]["id"]
    clients = http_json(f"{base_url}/admin/realms/{realm}/clients?max=500", token=token)
    for client in clients:
        if client.get("clientId") == client_id:
            return client["id"]
    raise RuntimeError(f"Could not resolve client UUID for clientId '{client_id}'")


def resolve_admin_roles_client(
    base_url: str,
    token: str,
    realm: str = "master",
) -> tuple[str, str]:
    """Resolve the admin-roles client across Keycloak version differences."""
    clients = http_json(f"{base_url}/admin/realms/{realm}/clients?max=500", token=token)
    for candidate in ["realm-management", "master-realm"]:
        for client in clients:
            if client.get("clientId") == candidate and client.get("id"):
                return candidate, client["id"]
    visible = sorted(str(c.get("clientId", "")) for c in clients if c.get("clientId"))
    preview = ", ".join(visible[:25]) if visible else "<none>"
    raise RuntimeError(
        "Could not resolve admin roles client in master realm. "
        f"Expected one of ['realm-management', 'master-realm']. Visible: {preview}"
    )


def user_token(
    base_url: str,
    realm: str,
    client_id: str,
    username: str,
    password: str,
) -> str:
    """Request user access token using direct access grant."""
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