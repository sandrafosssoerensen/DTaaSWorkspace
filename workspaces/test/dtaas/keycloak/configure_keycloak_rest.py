#!/usr/bin/env python3
"""Configure DTaaS Keycloak shared scope and mappers via Admin REST API."""
# pylint: disable=duplicate-code

# Only using Python's standard library
from __future__ import annotations
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# A list of dictionaries. Each dictionary is a Keycloak mapper definition
# that will be sent as-is to the Keycloak API as JSON.
MAPPERS: list[dict[str, Any]] = [
    {
        "name": "profile",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "consentRequired": False,
        "config": {
            "user.attribute": "profile",
            "claim.name": "profile",
            "jsonType.label": "String",
            "id.token.claim": "false",
            "access.token.claim": "false",
            "userinfo.token.claim": "true",
        },
    },
]

PAGE_SIZE = 200

@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuration settings loaded from environment variables."""

    keycloak_base_url: str = "http://localhost"
    keycloak_context_path: str = "/auth"
    keycloak_realm: str = "dtaas"
    keycloak_client_id: str = "dtaas-workspace"
    keycloak_shared_scope_name: str = ""
    keycloak_admin_client_id: str = ""
    keycloak_admin_client_secret: str = ""
    keycloak_admin: str = "admin"
    keycloak_admin_password: str = "admin"
    use_shared_scope: bool = False


def normalize_path(path: str) -> str:
    """Normalize context path so root resolves to an empty suffix."""
    if path in ("", "/"):
        return ""
    return path[:-1] if path.endswith("/") else path


class KeycloakRestConfigurator:
    """Implements the Keycloak REST configuration workflow."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.server_url = (
            f"{settings.keycloak_base_url}{normalize_path(settings.keycloak_context_path)}"
        )
        self.admin_url = f"{self.server_url}/admin/realms"

    def run(self) -> None:
        """Run the full claims-configuration workflow."""
        token = self.get_access_token()
        client_uuid = self.get_client_uuid(token)

        if self.settings.use_shared_scope:
            if not self.settings.keycloak_shared_scope_name:
                raise RuntimeError(
                    "KEYCLOAK_SHARED_SCOPE_NAME must be set when "
                    "KEYCLOAK_USE_SHARED_SCOPE is enabled"
                )
            scope_id = self.get_or_create_scope_id(token)
            for mapper in MAPPERS:
                self.ensure_mapper(token, scope_id, mapper)
            self.ensure_scope_assigned(token, client_uuid, scope_id)
        else:
            for mapper in MAPPERS:
                self.ensure_mapper_on_client(token, client_uuid, mapper)

    @staticmethod
    def _find_client_uuid(clients: list[dict[str, Any]], client_id: str) -> str:
        """Return matching client UUID from a list response, if present."""
        for client in clients:
            if client.get("clientId") == client_id:
                return client.get("id", "")
        return ""

    def _get_scope_id(self, token: str, scope_name: str) -> str:
        """Lookup shared scope by name and return its id when found."""
        scopes = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes"
            f"?q={scope_name}",
            token=token,
        )
        for scope in scopes:
            if scope.get("name") == scope_name and scope.get("id"):
                return scope["id"]
        return ""

    def get_access_token(self) -> str:
        """Get an admin token using service account or username/password."""
        if self.settings.keycloak_admin_client_id:
            payload = {
                "grant_type": "client_credentials",
                "client_id": self.settings.keycloak_admin_client_id,
                "client_secret": self.settings.keycloak_admin_client_secret,
            }
        else:
            payload = {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self.settings.keycloak_admin,
                "password": self.settings.keycloak_admin_password,
            }
        body = urlencode(payload).encode("utf-8")
        response = self._request_json(
            f"{self.server_url}/realms/master/protocol/openid-connect/token",
            method="POST",
            data=body,
            content_type="application/x-www-form-urlencoded",
            token=None,
        )
        token = response.get("access_token", "")
        if not token:
            raise RuntimeError("Failed to retrieve admin access token")
        return token

    def get_client_uuid(self, token: str) -> str:
        """Resolve the target client UUID from configured clientId."""
        client_id = self.settings.keycloak_client_id
        query = urlencode({"clientId": client_id})
        clients = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients?{query}",
            token=token,
        )

        client_uuid = self._find_client_uuid(clients, client_id)
        if client_uuid:
            return client_uuid

        first = 0
        while True:
            clients = self._request_json(
                f"{self.admin_url}/{self.settings.keycloak_realm}/clients"
                f"?first={first}&max={PAGE_SIZE}",
                token=token,
            )
            if not clients:
                break

            client_uuid = self._find_client_uuid(clients, client_id)
            if client_uuid:
                return client_uuid

            if len(clients) < PAGE_SIZE:
                break
            first += PAGE_SIZE

        raise RuntimeError(f"Client not found: {client_id}")

    def get_or_create_scope_id(self, token: str) -> str:
        """Resolve shared scope ID, creating the scope when missing."""
        scope_name = self.settings.keycloak_shared_scope_name

        scope_id = self._get_scope_id(token, scope_name)
        if scope_id:
            return scope_id

        self._request_empty(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes",
            method="POST",
            json_data={"name": scope_name, "protocol": "openid-connect"},
            token=token,
        )

        scope_id = self._get_scope_id(token, scope_name)
        if scope_id:
            return scope_id

        raise RuntimeError(f"Failed to resolve shared scope: {scope_name}")

    def ensure_mapper(self, token: str, scope_id: str, mapper: dict[str, Any]) -> None:
        """Upsert mapper by name in the shared scope."""
        endpoint = (
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes/{scope_id}"
            "/protocol-mappers/models"
        )
        existing = self._request_json(endpoint, token=token)
        existing_id = ""
        for item in existing:
            if item.get("name") == mapper["name"] and item.get("id"):
                existing_id = item["id"]
                break

        if existing_id:
            updated = dict(mapper)
            updated["id"] = existing_id
            self._request_empty(
                f"{endpoint}/{existing_id}",
                method="PUT",
                json_data=updated,
                token=token,
            )
            return

        self._request_empty(endpoint, method="POST", json_data=mapper, token=token)

    def ensure_mapper_on_client(
        self, token: str, client_uuid: str, mapper: dict[str, Any]
    ) -> None:
        """Upsert mapper by name directly on the client."""
        endpoint = (
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients/{client_uuid}"
            "/protocol-mappers/models"
        )
        existing = self._request_json(endpoint, token=token)
        existing_id = ""
        for item in existing:
            if item.get("name") == mapper["name"] and item.get("id"):
                existing_id = item["id"]
                break

        if existing_id:
            updated = dict(mapper)
            updated["id"] = existing_id
            self._request_empty(
                f"{endpoint}/{existing_id}",
                method="PUT",
                json_data=updated,
                token=token,
            )
            return

        self._request_empty(endpoint, method="POST", json_data=mapper, token=token)

    def ensure_scope_assigned(
        self, token: str, client_uuid: str, scope_id: str
    ) -> None:
        """Ensure shared scope is assigned as a default scope on the client."""
        assigned = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients/{client_uuid}"
            "/default-client-scopes",
            token=token,
        )
        if any(scope.get("id") == scope_id for scope in assigned):
            return

        self._request_empty(
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients/{client_uuid}"
            f"/default-client-scopes/{scope_id}",
            method="PUT",
            token=token,
        )

    def _request_json(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str = "application/json",
        token: str | None = None,
    ) -> Any:
        """Execute an HTTP request and return parsed JSON or empty object."""
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, method=method, headers=headers, data=data)
        try:
            # noqa: S310 - explicit admin URL target
            with urlopen(
                request,
                timeout=30,
            ) as response:
                raw_body = response.read()
                if not raw_body:
                    return {}
                decoded = raw_body.decode("utf-8")
                if not decoded.strip():
                    return {}
                return json.loads(decoded)
        except HTTPError as exc:
            with exc:
                error_body = exc.read().decode("utf-8")
            raise RuntimeError(
                f"HTTP {exc.code} from {url}: {error_body}"
            ) from exc

    def _request_empty(
        self,
        url: str,
        method: str,
        token: str,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        """Execute a request where only success status is relevant."""
        data = None
        content_type = "application/json"
        if json_data is not None:
            data = json.dumps(json_data).encode("utf-8")

        self._request_json(
            url,
            method=method,
            data=data,
            content_type=content_type,
            token=token,
        )


def settings_from_env() -> Settings:
    """Build settings using environment variables with script defaults."""
    return Settings(
        keycloak_base_url=os.getenv("KEYCLOAK_BASE_URL", "http://localhost"),
        keycloak_context_path=os.getenv("KEYCLOAK_CONTEXT_PATH", "/auth"),
        keycloak_realm=os.getenv("KEYCLOAK_REALM", "dtaas"),
        keycloak_client_id=os.getenv("KEYCLOAK_CLIENT_ID", "dtaas-workspace"),
        keycloak_shared_scope_name=os.getenv("KEYCLOAK_SHARED_SCOPE_NAME", ""),
        keycloak_admin_client_id=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", ""),
        keycloak_admin_client_secret=os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", ""),
        keycloak_admin=os.getenv("KEYCLOAK_ADMIN", "admin"),
        keycloak_admin_password=os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin"),
        use_shared_scope=os.getenv("KEYCLOAK_USE_SHARED_SCOPE", "").lower()
        in ("1", "true", "yes"),
    )


def main() -> int:
    """Entry point for command-line execution."""
    try:
        configurator = KeycloakRestConfigurator(settings_from_env())
        configurator.run()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if configurator.settings.use_shared_scope:
        print("Keycloak shared scope and mappers configured successfully (REST API).")
    else:
        print("Keycloak client mappers configured successfully (REST API).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
