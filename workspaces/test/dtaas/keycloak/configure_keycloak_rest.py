#!/usr/bin/env python3
"""Configure DTaaS Keycloak shared scope and mappers via Admin REST API.

This module mirrors the shell-based REST script behavior using Python only.
"""

# Only using Python's standard library
from __future__ import annotations
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# A list of dictionaries. Each dictionary is a Keycloak mapper definition that will be sent as-is to the Keycloak
# API as JSON.
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
    {
        "name": "groups",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-group-membership-mapper",
        "consentRequired": False,
        "config": {
            "full.path": "false",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "claim.name": "groups",
            "userinfo.token.claim": "true",
            "multivalued": "true",
        },
    },
    {
        "name": "groups_owner",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-group-membership-mapper",
        "consentRequired": False,
        "config": {
            "full.path": "false",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "claim.name": "https://gitlab.org/claims/groups/owner",
            "userinfo.token.claim": "true",
            "multivalued": "true",
        },
    },
    {
        "name": "sub_legacy",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "consentRequired": False,
        "config": {
            "user.attribute": "sub_legacy",
            "claim.name": "sub_legacy",
            "jsonType.label": "String",
            "id.token.claim": "false",
            "access.token.claim": "false",
            "userinfo.token.claim": "true",
        },
    },
]


@dataclass(frozen=True)
class Settings:
    keycloak_base_url: str = "http://localhost"
    keycloak_context_path: str = "/auth"
    keycloak_realm: str = "dtaas"
    keycloak_client_id: str = "dtaas-workspace"
    keycloak_shared_scope_name: str = "dtaas-shared"
    keycloak_admin_client_id: str = ""
    keycloak_admin_client_secret: str = ""
    keycloak_admin: str = "admin"
    keycloak_admin_password: str = "admin"
    profile_base_url: str = "https://localhost/gitlab"


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
        token = self.get_access_token()
        client_uuid = self.get_client_uuid(token)
        scope_id = self.get_or_create_scope_id(token)

        for mapper in MAPPERS:
            self.ensure_mapper(token, scope_id, mapper)

        self.ensure_user_profile_attribute(token, "profile", "Profile URL")
        self.ensure_user_profile_attribute(token, "sub_legacy", "Legacy Subject")
        self.ensure_scope_assigned(token, client_uuid, scope_id)
        self.update_user_profiles(token)

    def get_access_token(self) -> str:
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
        clients = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients?max=200",
            token=token,
        )
        for client in clients:
            if client.get("clientId") == self.settings.keycloak_client_id:
                client_uuid = client.get("id", "")
                if client_uuid:
                    return client_uuid
        raise RuntimeError(f"Client not found: {self.settings.keycloak_client_id}")

    def get_or_create_scope_id(self, token: str) -> str:
        scope_name = self.settings.keycloak_shared_scope_name
        scopes = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes"
            f"?q={scope_name}",
            token=token,
        )
        for scope in scopes:
            if scope.get("name") == scope_name and scope.get("id"):
                return scope["id"]

        self._request_empty(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes",
            method="POST",
            json_data={"name": scope_name, "protocol": "openid-connect"},
            token=token,
        )

        scopes = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes"
            f"?q={scope_name}",
            token=token,
        )
        for scope in scopes:
            if scope.get("name") == scope_name and scope.get("id"):
                return scope["id"]
        raise RuntimeError(f"Failed to resolve shared scope: {scope_name}")

    def ensure_mapper(self, token: str, scope_id: str, mapper: dict[str, Any]) -> None:
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

    def ensure_user_profile_attribute(
        self, token: str, attr_name: str, display_name: str
    ) -> None:
        endpoint = f"{self.admin_url}/{self.settings.keycloak_realm}/users/profile"
        profile = self._request_json(endpoint, token=token)
        attributes = profile.get("attributes", [])

        found = False
        for attr in attributes:
            if attr.get("name") == attr_name:
                attr["displayName"] = display_name
                attr["permissions"] = {"view": ["admin"], "edit": ["admin"]}
                attr["multivalued"] = False
                attr.pop("required", None)
                found = True
                break

        if not found:
            attributes.append(
                {
                    "name": attr_name,
                    "displayName": display_name,
                    "permissions": {"view": ["admin"], "edit": ["admin"]},
                    "multivalued": False,
                }
            )

        profile["attributes"] = attributes
        self._request_empty(endpoint, method="PUT", json_data=profile, token=token)

    def ensure_scope_assigned(self, token: str, client_uuid: str, scope_id: str) -> None:
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

    def update_user_profiles(self, token: str) -> None:
        if not self.settings.profile_base_url:
            return

        users = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/users?max=200",
            token=token,
        )
        for user in users:
            user_id = user.get("id", "")
            username = user.get("username", "")
            if not user_id or not username:
                continue

            user_details = self._request_json(
                f"{self.admin_url}/{self.settings.keycloak_realm}/users/{user_id}",
                token=token,
            )
            existing_attributes = user_details.get("attributes", {})
            merged_attributes = dict(existing_attributes)
            merged_attributes["profile"] = [
                f"{self.settings.profile_base_url}/{username}"
            ]

            payload = {"attributes": merged_attributes}
            self._request_empty(
                f"{self.admin_url}/{self.settings.keycloak_realm}/users/{user_id}",
                method="PUT",
                json_data=payload,
                token=token,
            )

    def _request_json(
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str = "application/json",
        token: str | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, method=method, headers=headers, data=data)
        with urlopen(request) as response:  # noqa: S310 - explicit admin URL target
            return json.loads(response.read().decode("utf-8"))

    def _request_empty(
        self,
        url: str,
        method: str,
        token: str,
        json_data: dict[str, Any] | None = None,
    ) -> None:
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
        keycloak_shared_scope_name=os.getenv(
            "KEYCLOAK_SHARED_SCOPE_NAME", "dtaas-shared"
        ),
        keycloak_admin_client_id=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", ""),
        keycloak_admin_client_secret=os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", ""),
        keycloak_admin=os.getenv("KEYCLOAK_ADMIN", "admin"),
        keycloak_admin_password=os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin"),
        profile_base_url=os.getenv("PROFILE_BASE_URL", "https://localhost/gitlab"),
    )


def main() -> int:
    """Entry point for command-line execution."""
    try:
        configurator = KeycloakRestConfigurator(settings_from_env())
        configurator.run()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Keycloak shared scope and mappers configured successfully (REST API).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
