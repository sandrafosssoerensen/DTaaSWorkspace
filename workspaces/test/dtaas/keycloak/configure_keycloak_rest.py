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
    },
    {
        # Emits the user's assigned realm roles as a flat 'roles' array in the
        # access token.  OPA reads input.extra.roles to make RBAC decisions.
        # Expected roles: dtaas-admin, dtaas-user, dtaas-viewer.
        "name": "roles",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-realm-role-mapper",
        "consentRequired": False,
        "config": {
            "claim.name": "roles",
            "multivalued": "true",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "userinfo.token.claim": "true",
            "jsonType.label": "String",
        },
    },
]

# Mappers applied directly on the client regardless of shared-scope mode.
# The audience mapper must live on the client itself so that Oathkeeper's
# target_audience check passes for tokens issued to this client.
CLIENT_MAPPERS: list[dict[str, Any]] = [
    {
        "name": "audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            # Use included.custom.audience (a literal string) rather than
            # included.client.audience, which silently does nothing for public
            # clients that are not resource servers.
            "included.custom.audience": "",
            "id.token.claim": "false",
            "access.token.claim": "true",
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
    keycloak_use_shared_scope: bool = True
    keycloak_shared_scope_name: str = "dtaas-shared"
    keycloak_user_profiles: list[str] | None = None
    keycloak_admin_client_id: str = ""
    keycloak_admin_client_secret: str = ""
    keycloak_admin: str = "admin"
    keycloak_admin_password: str = "admin"
    profile_base_url: str = ""
    keycloak_public_client: bool = True
    keycloak_standard_flow_enabled: bool = True
    keycloak_pkce_method: str = "S256"
    keycloak_redirect_uris: list[str] | None = None
    keycloak_web_origins: list[str] | None = None
    keycloak_post_logout_redirect_uris: list[str] | None = None
    keycloak_default_client_scopes: list[str] | None = None
    keycloak_optional_client_scopes: list[str] | None = None
    keycloak_roles: list[str] | None = None
    keycloak_users: list[dict[str, str]] | None = None


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


def parse_users_env(name: str) -> list[dict[str, str]] | None:
    """Parse KEYCLOAK_USERS JSON array of {username, password, role} objects."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON value for {name}. "
            "Expected array of {{username, password, role}} objects."
        ) from exc

    if not isinstance(loaded, list):
        raise RuntimeError(f"Invalid value for {name}. Expected JSON array.")

    users = []
    for item in loaded:
        if not isinstance(item, dict) or "username" not in item or "password" not in item:
            raise RuntimeError(
                f"Each entry in {name} must have at least 'username' and 'password'."
            )
        users.append({
            "username": str(item["username"]).strip(),
            "password": str(item["password"]),
            "role": str(item.get("role", "")).strip(),
            "email": str(item.get("email", "")).strip(),
            "firstName": str(item.get("firstName", "")).strip(),
            "lastName": str(item.get("lastName", "")).strip(),
        })
    return users or None


def parse_csv_env(name: str) -> list[str] | None:
    """Parse comma-separated values from environment into a list."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def normalize_path(path: str) -> str:
    """Normalize context path so root resolves to an empty suffix."""
    if path in ("", "/"):
        return ""
    return path[:-1] if path.endswith("/") else path


class KeycloakRestConfigurator:
    """Implements the Keycloak REST configuration workflow."""

    def __init__(self, settings: Settings, dry_run: bool = False) -> None:
        self.settings = settings
        self.dry_run = dry_run
        self.server_url = (
            f"{settings.keycloak_base_url}{normalize_path(settings.keycloak_context_path)}"
        )
        self.admin_url = f"{self.server_url}/admin/realms"

    def run(self) -> None:
        """Run the full claims-configuration workflow."""
        token = self.get_access_token()
        self.ensure_realm(token)
        self.ensure_client(token)
        client_uuid = self.get_client_uuid(token)
        self.ensure_client_auth_settings(token, client_uuid)
        if self.settings.keycloak_use_shared_scope:
            scope_id = self.get_or_create_scope_id(token)
            for mapper in MAPPERS:
                self.ensure_mapper(token, scope_id, mapper)
            self.ensure_scope_assigned(token, client_uuid, scope_id)
        else:
            for mapper in MAPPERS:
                self.ensure_mapper_on_client(token, client_uuid, mapper)
        self.ensure_client_scopes(token, client_uuid)

        for mapper in self._client_mappers():
            self.ensure_mapper_on_client(token, client_uuid, mapper)

        self.ensure_realm_roles(token)
        self.ensure_users(token)
        self.ensure_user_profile_mappers(token)
        self.update_user_profiles(token)

    def ensure_client_auth_settings(self, token: str, client_uuid: str) -> None:
        """Ensure DTaaS client auth settings (PKCE/public client/URIs) are set."""
        endpoint = f"{self.admin_url}/{self.settings.keycloak_realm}/clients/{client_uuid}"
        client = self._request_json(endpoint, token=token)

        changed = False
        attributes = dict(client.get("attributes", {}))

        if client.get("publicClient") != self.settings.keycloak_public_client:
            client["publicClient"] = self.settings.keycloak_public_client
            changed = True

        if (
            client.get("standardFlowEnabled")
            != self.settings.keycloak_standard_flow_enabled
        ):
            client["standardFlowEnabled"] = self.settings.keycloak_standard_flow_enabled
            changed = True

        if attributes.get("pkce.code.challenge.method") != self.settings.keycloak_pkce_method:
            attributes["pkce.code.challenge.method"] = self.settings.keycloak_pkce_method
            changed = True

        redirect_uris = self.settings.keycloak_redirect_uris
        if redirect_uris is not None and client.get("redirectUris") != redirect_uris:
            client["redirectUris"] = redirect_uris
            changed = True

        web_origins = self.settings.keycloak_web_origins
        if web_origins is not None and client.get("webOrigins") != web_origins:
            client["webOrigins"] = web_origins
            changed = True

        post_logout = self.settings.keycloak_post_logout_redirect_uris
        if post_logout is not None:
            # Keycloak stores this as a single string attribute.
            value = "##".join(post_logout)
            if attributes.get("post.logout.redirect.uris") != value:
                attributes["post.logout.redirect.uris"] = value
                changed = True

        if changed:
            client["attributes"] = attributes
            self._request_empty_or_log(
                endpoint,
                method="PUT",
                token=token,
                json_data=client,
                description="Update client auth settings",
            )

    def ensure_client_scopes(self, token: str, client_uuid: str) -> None:
        """Ensure configured default/optional client scope assignments."""
        default_names = self.settings.keycloak_default_client_scopes
        optional_names = self.settings.keycloak_optional_client_scopes
        if default_names is None and optional_names is None:
            return

        all_scopes_by_name = self._get_scope_name_id_map(token)

        if default_names is not None:
            self._enforce_scope_category(
                token=token,
                client_uuid=client_uuid,
                category="default-client-scopes",
                desired_scope_names=default_names,
                all_scopes_by_name=all_scopes_by_name,
            )

        if optional_names is not None:
            self._enforce_scope_category(
                token=token,
                client_uuid=client_uuid,
                category="optional-client-scopes",
                desired_scope_names=optional_names,
                all_scopes_by_name=all_scopes_by_name,
            )

    def _get_scope_name_id_map(self, token: str) -> dict[str, str]:
        """Return mapping of client-scope name to ID for the target realm."""
        first = 0
        by_name: dict[str, str] = {}
        while True:
            scopes = self._request_json(
                f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes"
                f"?first={first}&max={PAGE_SIZE}",
                token=token,
            )
            if not scopes:
                break

            for scope in scopes:
                name = scope.get("name")
                scope_id = scope.get("id")
                if name and scope_id:
                    by_name[str(name)] = str(scope_id)

            if len(scopes) < PAGE_SIZE:
                break
            first += PAGE_SIZE

        return by_name

    def _enforce_scope_category(
        self,
        token: str,
        client_uuid: str,
        category: str,
        desired_scope_names: list[str],
        all_scopes_by_name: dict[str, str],
    ) -> None:
        """Ensure exactly the desired scopes are assigned in one category."""
        desired_ids: set[str] = set()
        for name in desired_scope_names:
            scope_id = all_scopes_by_name.get(name)
            if not scope_id:
                print(
                    f"Warning: client scope '{name}' not found in realm "
                    f"{self.settings.keycloak_realm} — skipping",
                    file=sys.stderr,
                )
                continue
            desired_ids.add(scope_id)

        endpoint = (
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients/{client_uuid}/"
            f"{category}"
        )
        assigned = self._request_json(endpoint, token=token)
        assigned_ids = {
            str(item.get("id"))
            for item in assigned
            if item.get("id")
        }

        to_add = sorted(desired_ids - assigned_ids)
        to_remove = sorted(assigned_ids - desired_ids)

        for scope_id in to_add:
            self._request_empty_or_log(
                f"{endpoint}/{scope_id}",
                method="PUT",
                token=token,
                description=f"Assign scope '{scope_id}' to {category}",
            )

        for scope_id in to_remove:
            self._request_empty_or_log(
                f"{endpoint}/{scope_id}",
                method="DELETE",
                token=token,
                description=f"Unassign scope '{scope_id}' from {category}",
            )

    def _client_mappers(self) -> list[dict[str, Any]]:
        """Return mappers to apply directly on the client.

        These are applied regardless of shared-scope mode. The audience mapper
        is built dynamically so its included.client.audience always matches
        the configured KEYCLOAK_CLIENT_ID.
        """
        return [
            {
                **mapper,
                "config": {
                    **mapper["config"],
                    "included.custom.audience": self.settings.keycloak_client_id,
                },
            }
            if mapper["protocolMapper"] == "oidc-audience-mapper"
            else mapper
            for mapper in CLIENT_MAPPERS
        ]



    def ensure_users(self, token: str) -> None:
        """Ensure configured users exist in the realm with their assigned roles.

        Users are taken from settings.keycloak_users, a list of dicts with:
          username  — Keycloak username
          password  — initial password (set as non-temporary)
          role      — realm role to assign (e.g. dtaas-admin, dtaas-user)
        Existing users are left unchanged; only missing ones are created.
        Role assignment is always re-applied in case it was missing.
        """
        users = self.settings.keycloak_users
        if not users:
            return

        realm = self.settings.keycloak_realm
        users_endpoint = f"{self.admin_url}/{realm}/users"
        roles_endpoint = f"{self.admin_url}/{realm}/roles"

        # Build a cache of existing usernames → user id
        existing: dict[str, str] = {}
        first = 0
        while True:
            page = self._request_json(
                f"{users_endpoint}?first={first}&max={PAGE_SIZE}", token=token
            )
            if not page:
                break
            for u in page:
                if u.get("username") and u.get("id"):
                    existing[u["username"]] = u["id"]
            if len(page) < PAGE_SIZE:
                break
            first += PAGE_SIZE

        # Build a cache of role name → {id, name} for role assignment
        role_cache: dict[str, dict[str, str]] = {}

        for user in users:
            username = user["username"]
            password = user["password"]
            role_name = user["role"]

            # Create user if missing
            if username not in existing:
                user_payload: dict[str, Any] = {
                    "username": username,
                    "enabled": True,
                    "credentials": [
                        {
                            "type": "password",
                            "value": password,
                            "temporary": False,
                        }
                    ],
                }
                if user.get("email"):
                    user_payload["email"] = user["email"]
                if user.get("firstName"):
                    user_payload["firstName"] = user["firstName"]
                if user.get("lastName"):
                    user_payload["lastName"] = user["lastName"]
                self._request_empty_or_log(
                    users_endpoint,
                    method="POST",
                    json_data=user_payload,
                    token=token,
                    description=f"Create user '{username}'",
                )
                if not self.dry_run:
                    # Re-fetch to get the new user's id
                    query = urlencode({"username": username, "exact": "true"})
                    results = self._request_json(
                        f"{users_endpoint}?{query}", token=token
                    )
                    for u in results:
                        if u.get("username") == username and u.get("id"):
                            existing[username] = u["id"]
                            break

            if not role_name:
                continue

            user_id = existing.get(username)
            if not user_id:
                continue  # dry-run or creation failed

            # Resolve role representation (id + name required by Keycloak API)
            if role_name not in role_cache:
                try:
                    role_rep = self._request_json(
                        f"{roles_endpoint}/{role_name}", token=token
                    )
                    role_cache[role_name] = {
                        "id": role_rep["id"],
                        "name": role_rep["name"],
                    }
                except RuntimeError:
                    print(
                        f"Warning: realm role '{role_name}' not found — "
                        f"skipping role assignment for '{username}'",
                        file=sys.stderr,
                    )
                    continue

            # Assign role (Keycloak ignores duplicates)
            self._request_empty_or_log(
                f"{users_endpoint}/{user_id}/role-mappings/realm",
                method="POST",
                json_data=[role_cache[role_name]],
                token=token,
                description=f"Assign role '{role_name}' to user '{username}'",
            )

    def ensure_realm(self, token: str) -> None:
        """Ensure the target realm exists, creating it if missing."""
        realm = self.settings.keycloak_realm
        try:
            self._request_json(f"{self.admin_url}/{realm}", token=token)
            return  # realm already exists
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise

        self._request_empty_or_log(
            self.admin_url,
            method="POST",
            json_data={"realm": realm, "enabled": True},
            token=token,
            description=f"Create realm '{realm}'",
        )

    def ensure_client(self, token: str) -> None:
        """Ensure the target client exists in the realm, creating it if missing."""
        realm = self.settings.keycloak_realm
        client_id = self.settings.keycloak_client_id
        query = urlencode({"clientId": client_id})
        clients = self._request_json(
            f"{self.admin_url}/{realm}/clients?{query}",
            token=token,
        )
        if any(c.get("clientId") == client_id for c in clients):
            return  # client already exists

        self._request_empty_or_log(
            f"{self.admin_url}/{realm}/clients",
            method="POST",
            json_data={
                "clientId": client_id,
                "protocol": "openid-connect",
                "publicClient": self.settings.keycloak_public_client,
                "standardFlowEnabled": self.settings.keycloak_standard_flow_enabled,
                "redirectUris": self.settings.keycloak_redirect_uris or [],
                "webOrigins": self.settings.keycloak_web_origins or [],
                "attributes": {
                    "pkce.code.challenge.method": self.settings.keycloak_pkce_method,
                },
            },
            token=token,
            description=f"Create client '{client_id}' in realm '{realm}'",
        )

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

        if self.dry_run:
            print(
                "[DRY-RUN] POST "
                f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes "
                f":: Create shared scope '{scope_name}'"
            )
            return f"dry-run-scope-id-{scope_name}"

        self._request_empty_or_log(
            f"{self.admin_url}/{self.settings.keycloak_realm}/client-scopes",
            method="POST",
            json_data={
                "name": scope_name,
                "protocol": "openid-connect",
                "description": "DTaaS shared custom mappers (profile claim; optional groups)",
            },
            token=token,
            description=f"Create shared scope '{scope_name}'",
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
            self._request_empty_or_log(
                f"{endpoint}/{existing_id}",
                method="PUT",
                json_data=updated,
                token=token,
                description=f"Update shared-scope mapper '{mapper['name']}'",
            )
            return

        self._request_empty_or_log(
            endpoint,
            method="POST",
            json_data=mapper,
            token=token,
            description=f"Create shared-scope mapper '{mapper['name']}'",
        )

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
            self._request_empty_or_log(
                f"{endpoint}/{existing_id}",
                method="PUT",
                json_data=updated,
                token=token,
                description=f"Update client mapper '{mapper['name']}'",
            )
            return

        self._request_empty_or_log(
            endpoint,
            method="POST",
            json_data=mapper,
            token=token,
            description=f"Create client mapper '{mapper['name']}'",
        )

    def ensure_realm_roles(self, token: str) -> None:
        """Ensure RBAC realm roles exist in the realm.

        Roles to create are taken from settings.keycloak_roles.
        Defaults to the three DTaaS roles when not configured:
          dtaas-admin   — full access to any workspace (cross-user)
          dtaas-user    — full access to own workspace
          dtaas-viewer  — read-only access to own workspace
        Existing roles are left unchanged; only missing ones are created.
        """
        _role_descriptions: dict[str, str] = {
            "dtaas-admin": "Full access to any workspace (cross-user)",
            "dtaas-user": "Full access to own workspace",
            "dtaas-viewer": "Read-only access to own workspace",
        }
        roles = self.settings.keycloak_roles or list(_role_descriptions)
        endpoint = f"{self.admin_url}/{self.settings.keycloak_realm}/roles"

        existing = self._request_json(endpoint, token=token)
        existing_names = {r.get("name") for r in existing if r.get("name")}

        for role_name in roles:
            if role_name in existing_names:
                continue
            self._request_empty_or_log(
                endpoint,
                method="POST",
                json_data={
                    "name": role_name,
                    "description": _role_descriptions.get(role_name, ""),
                },
                token=token,
                description=f"Create realm role '{role_name}'",
            )

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
        self._request_empty_or_log(
            endpoint,
            method="PUT",
            json_data=profile,
            token=token,
            description="Update user-profile schema mappers",
        )

    def ensure_scope_assigned(self, token: str, client_uuid: str, scope_id: str) -> None:
        """Ensure shared scope is assigned as a default scope on the client."""
        assigned = self._request_json(
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients/{client_uuid}"
            "/default-client-scopes",
            token=token,
        )
        if any(scope.get("id") == scope_id for scope in assigned):
            return

        self._request_empty_or_log(
            f"{self.admin_url}/{self.settings.keycloak_realm}/clients/{client_uuid}"
            f"/default-client-scopes/{scope_id}",
            method="PUT",
            token=token,
            description=(
                f"Assign shared scope '{self.settings.keycloak_shared_scope_name}' "
                "as default client scope"
            ),
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
                self._request_empty_or_log(
                    f"{self.admin_url}/{self.settings.keycloak_realm}/users/{user_id}",
                    method="PUT",
                    json_data=payload,
                    token=token,
                    description=f"Update profile attribute for user '{username}'",
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

    def _request_empty_or_log(
        self,
        url: str,
        method: str,
        token: str,
        description: str,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        """Execute a write request or log intended change in dry-run mode."""
        if self.dry_run:
            print(f"[DRY-RUN] {method} {url} :: {description}")
            return
        self._request_empty(
            url=url,
            method=method,
            token=token,
            json_data=json_data,
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
        keycloak_public_client=parse_bool_env("KEYCLOAK_PUBLIC_CLIENT", True),
        keycloak_standard_flow_enabled=parse_bool_env(
            "KEYCLOAK_STANDARD_FLOW_ENABLED", True
        ),
        keycloak_pkce_method=os.getenv("KEYCLOAK_PKCE_METHOD", "S256"),
        keycloak_redirect_uris=parse_csv_env("KEYCLOAK_REDIRECT_URIS"),
        keycloak_web_origins=parse_csv_env("KEYCLOAK_WEB_ORIGINS"),
        keycloak_post_logout_redirect_uris=parse_csv_env(
            "KEYCLOAK_POST_LOGOUT_REDIRECT_URIS"
        ),
        keycloak_default_client_scopes=parse_csv_env(
            "KEYCLOAK_DEFAULT_CLIENT_SCOPES"
        ),
        keycloak_optional_client_scopes=parse_csv_env(
            "KEYCLOAK_OPTIONAL_CLIENT_SCOPES"
        ),
        keycloak_roles=parse_csv_env("KEYCLOAK_ROLES"),
        keycloak_users=parse_users_env("KEYCLOAK_USERS"),
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
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print planned write operations without applying them",
        )
        args = parser.parse_args()

        env_file = args.env_file or resolve_default_env_file()
        if env_file:
            load_dotenv_file(env_file)

        configurator = KeycloakRestConfigurator(
            settings_from_env(),
            dry_run=args.dry_run,
        )
        configurator.run()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry-run completed successfully (no changes were written).")
    else:
        print("Keycloak shared scope and mappers configured successfully (REST API).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
