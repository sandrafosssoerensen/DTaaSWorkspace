#!/usr/bin/env python3
"""Configure DTaaS Keycloak shared scope and mappers via Admin REST API.

This module mirrors the shell-based REST script behavior using Python only.
"""
# pylint: disable=duplicate-code

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MAPPERS: list[dict[str, Any]] = [
    {
        "name": "profile",
        "consentText": "DTaaS custom mapper for profile claim",
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
    }
]

PAGE_SIZE = 200


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuration settings loaded from environment variables."""

    keycloak_base_url: str = "http://localhost"
    keycloak_context_path: str = "/auth"
    keycloak_realm: str = "dtaas"
    keycloak_client_id: str = "dtaas-workspace"
    keycloak_use_shared_scope: bool = True
    keycloak_shared_scope_name: str = "dtaas-shared"
    keycloak_user_profiles: list[str] | None = None
    keycloak_admin_client_id: str = ""
    keycloak_admin_client_secret: str = ""
    keycloak_admin: str = "admin"
    keycloak_admin_password: str = "admin"
    profile_base_url: str = ""


def parse_bool_env(name: str, default: bool = False) -> bool:
    """Parse environment booleans with common true/false string forms."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(
        f"Invalid boolean value for {name}: '{raw}'. Use true/false."
    )


def parse_user_profiles_env(name: str) -> list[str] | None:
    """Parse optional JSON list of usernames from environment."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON value for {name}. Expected array of usernames."
        ) from exc

    if not isinstance(loaded, list):
        raise RuntimeError(f"Invalid value for {name}. Expected JSON array.")

    usernames = [str(item).strip() for item in loaded if str(item).strip()]
    return usernames or None


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
        if self.settings.keycloak_use_shared_scope:
            scope_id = self.get_or_create_scope_id(token)
            for mapper in MAPPERS:
                self.ensure_mapper(token, scope_id, mapper)
            self.ensure_scope_assigned(token, client_uuid, scope_id)
        else:
            for mapper in MAPPERS:
                self.ensure_mapper_on_client(token, client_uuid, mapper)

        self.ensure_user_profile_mappers(token)
        self.update_user_profiles(token)

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
        for client in clients:
            if client.get("clientId") == client_id and client.get("id"):
                return client["id"]

        first = 0
        while True:
            clients = self._request_json(
                f"{self.admin_url}/{self.settings.keycloak_realm}/clients"
                f"?first={first}&max={PAGE_SIZE}",
                token=token,
            )
            if not clients:
                break

            for client in clients:
                if client.get("clientId") == client_id and client.get("id"):
                    return client["id"]

            if len(clients) < PAGE_SIZE:
                break
            first += PAGE_SIZE

        raise RuntimeError(f"Client not found: {client_id}")

    def get_or_create_scope_id(self, token: str) -> str:
        """Resolve shared scope ID, creating the scope when missing."""
        scope_name = self.settings.keycloak_shared_scope_name
        scopes = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes?q={scope_name}",
            token=token,
        )
        for scope in scopes:
            if scope.get("name") == scope_name and scope.get("id"):
                return scope["id"]

        self._request_empty(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes",
            method="POST",
            json_data={
                "name": scope_name,
                "protocol": "openid-connect",
                "description": "DTaaS shared custom mappers (profile claim; optional groups)",
            },
            token=token,
        )

        scopes = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes?q={scope_name}",
            token=token,
        )
        for scope in scopes:
            if scope.get("name") == scope_name and scope.get("id"):
                return scope["id"]

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
        """Upsert mapper by name directly on a target client."""
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

    def ensure_user_profile_mappers(self, token: str) -> None:
        """Ensure user-profile metadata exists for attributes mapped from user model."""
        endpoint = f"{self.admin_url}/{self.settings.keycloak_realm}/users/profile"
        profile = self._request_json(endpoint, token=token)
        attributes = profile.get("attributes", [])

        expected = {
            "profile": "Profile URL",
        }

        by_name = {attr.get("name"): attr for attr in attributes if attr.get("name")}
        for attr_name, display_name in expected.items():
            if attr_name in by_name:
                attr = by_name[attr_name]
                attr["displayName"] = display_name
                attr["permissions"] = {"view": ["admin"], "edit": ["admin"]}
                attr["multivalued"] = False
                attr.pop("required", None)
            else:
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

    def update_user_profiles(self, token: str) -> None:
        """Merge and update each user's profile attribute URL."""
        target_usernames = set(self.settings.keycloak_user_profiles or [])
        use_filter = bool(target_usernames)
        first = 0
        while True:
            query = urlencode({"first": first, "max": PAGE_SIZE})
            users = self._request_json(
                f"{self.admin_url}/{self.settings.keycloak_realm}/users?{query}",
                token=token,
            )
            if not users:
                break

            for user in users:
                user_id = user.get("id", "")
                username = user.get("username", "")
                if not user_id or not username:
                    continue
                if use_filter and username not in target_usernames:
                    continue

                user_details = self._request_json(
                    f"{self.admin_url}/{self.settings.keycloak_realm}/users/{user_id}",
                    token=token,
                )
                existing_attributes = user_details.get("attributes", {})
                merged_attributes = dict(existing_attributes)
                merged_attributes["profile"] = [
                    f"{self.settings.profile_base_url.rstrip('/')}/{username}"
                ]

                payload = dict(user_details)
                payload["attributes"] = merged_attributes
                self._request_empty(
                    f"{self.admin_url}/{self.settings.keycloak_realm}/users/{user_id}",
                    method="PUT",
                    json_data=payload,
                    token=token,
                )

            if len(users) < PAGE_SIZE:
                break
            first += PAGE_SIZE

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
            with urlopen(request, timeout=30) as response:
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
            raise RuntimeError(f"HTTP {exc.code} from {url}: {error_body}") from exc

    def _request_empty(
        self,
        url: str,
        method: str,
        token: str,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        """Execute a request where only success status is relevant."""
        data = None
        if json_data is not None:
            data = json.dumps(json_data).encode("utf-8")

        self._request_json(
            url,
            method=method,
            data=data,
            content_type="application/json",
            token=token,
        )


def load_dotenv_file(env_file: str) -> None:
    """Load KEY=VALUE pairs from a dotenv file into process environment."""
    path = Path(env_file)
    if not path.is_file():
        raise RuntimeError(f"Env file not found: {env_file}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]

        os.environ[key] = value


def resolve_default_env_file() -> str | None:
    """Resolve a default dotenv path when available."""
    cwd_env = Path(".env")
    if cwd_env.is_file():
        return str(cwd_env)

    script_default = Path(__file__).resolve().parent.parent / "config" / ".env"
    if script_default.is_file():
        return str(script_default)

    return None


def settings_from_env() -> Settings:
    """Build settings using environment variables with script defaults."""
    return Settings(
        keycloak_base_url=os.getenv("KEYCLOAK_BASE_URL", "http://localhost"),
        keycloak_context_path=os.getenv("KEYCLOAK_CONTEXT_PATH", "/auth"),
        keycloak_realm=os.getenv("KEYCLOAK_REALM", "dtaas"),
        keycloak_client_id=os.getenv("KEYCLOAK_CLIENT_ID", "dtaas-workspace"),
        keycloak_use_shared_scope=parse_bool_env("KEYCLOAK_USE_SHARED_SCOPE", True),
        keycloak_shared_scope_name=os.getenv("KEYCLOAK_SHARED_SCOPE_NAME", "dtaas-shared"),
        keycloak_user_profiles=parse_user_profiles_env("KEYCLOAK_USER_PROFILES"),
        keycloak_admin_client_id=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", ""),
        keycloak_admin_client_secret=os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", ""),
        keycloak_admin=os.getenv("KEYCLOAK_ADMIN", "admin"),
        keycloak_admin_password=os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin"),
        profile_base_url=os.getenv(
            "KEYCLOAK_PROFILE_BASE_URL",
            os.getenv("PROFILE_BASE_URL", os.getenv("KEYCLOAK_BASE_URL", "http://localhost")),
        ),
    )


def main() -> int:
    """Entry point for command-line execution."""
    try:
        parser = argparse.ArgumentParser(
            description="Configure Keycloak shared scope mappers for DTaaS"
        )
        parser.add_argument(
            "--env-file",
            default="",
            help="Path to .env file containing KEYCLOAK_* settings",
        )
        args = parser.parse_args()

        env_file = args.env_file or resolve_default_env_file()
        if env_file:
            load_dotenv_file(env_file)

        configurator = KeycloakRestConfigurator(settings_from_env())
        configurator.run()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Keycloak shared scope and mappers configured successfully (REST API).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
