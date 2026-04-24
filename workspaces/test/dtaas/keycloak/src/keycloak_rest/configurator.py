"""Keycloak REST configurator implementation."""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import urlencode

from .constants import PAGE_SIZE, dtaas_client_config, workspace_client_config
from .http_client import HttpClient
from .settings import Settings, normalize_path
from .user_profiles import AdminContext, ensure_user_profile_mappers, update_user_profiles


def _token_expiry(token: str) -> float:
    """Return the exp claim from a JWT, or infinity if it cannot be decoded."""
    try:
        segment = token.split(".")[1]
        segment += "=" * ((4 - len(segment) % 4) % 4)
        claims = json.loads(base64.urlsafe_b64decode(segment))
        return float(claims.get("exp", float("inf")))
    except (IndexError, ValueError, TypeError, AttributeError):
        return float("inf")


class KeycloakRestConfigurator:
    """Implements the Keycloak REST configuration workflow."""

    def __init__(self, settings: Settings, http: HttpClient | None = None) -> None:
        self.settings = settings
        self.http = http if http is not None else HttpClient()
        self.server_url = (
            f"{settings.keycloak_base_url}"
            f"{normalize_path(settings.keycloak_context_path)}"
        )
        self.admin_url = f"{self.server_url}/admin/realms"

    def run(self) -> None:
        """Run the full claims-configuration workflow."""
        token = self.get_access_token()
        self.ensure_realm(token)
        token = self._fresh_token(token)
        self.ensure_clients(token)
        token = self._fresh_token(token)
        client_uuid = self.get_client_uuid(token)
        self._configure_mappers(token, client_uuid)
        token = self._fresh_token(token)
        ctx = AdminContext(self.admin_url, self.settings.realm.name, token, self.http)
        ensure_user_profile_mappers(ctx)
        token = self._fresh_token(token)
        ctx = AdminContext(self.admin_url, self.settings.realm.name, token, self.http)
        update_user_profiles(
            ctx, self.settings.profile_base_url, self.settings.realm.user_profiles
        )

    def _fresh_token(self, current: str) -> str:
        """Return current token, or a new one if expiry is within 30 seconds."""
        if time.time() + 30 >= _token_expiry(current):
            return self.get_access_token()
        return current

    def ensure_realm(self, token: str) -> None:
        """Create the configured realm if it does not already exist."""
        realms = self.http.request_json(self.admin_url, token=token)
        realm_name = self.settings.realm.name
        if isinstance(realms, list) and any(
            r.get("realm") == realm_name for r in realms
        ):
            return
        self.http.request_empty(
            self.admin_url,
            method="POST",
            json_data={"realm": realm_name, "enabled": True},
            token=token,
        )

    def ensure_clients(self, token: str) -> None:
        """Create dtaas-workspace and dtaas-client in the realm if absent.

        Skipped when KEYCLOAK_CLIENT_ROOT_URL is not set, leaving deployments
        that manage clients separately unaffected.
        """
        root_url = self.settings.realm.client_root_url
        if not root_url:
            return
        for config in [workspace_client_config(root_url), dtaas_client_config(root_url)]:
            self._create_client_if_missing(token, config)

    def _create_client_if_missing(
        self, token: str, client_config: dict[str, Any]
    ) -> None:
        """POST the client only when no existing client matches its clientId."""
        client_id = client_config["clientId"]
        query = urlencode({"clientId": client_id})
        existing = self.http.request_json(
            f"{self.admin_url}/{self.settings.realm.name}/clients?{query}",
            token=token,
        )
        if existing:
            return
        self.http.request_empty(
            f"{self.admin_url}/{self.settings.realm.name}/clients",
            method="POST",
            json_data=client_config,
            token=token,
        )

    def get_access_token(self) -> str:
        """Get an admin token using service account or username/password."""
        payload = self._build_admin_auth_payload()
        body = urlencode(payload).encode("utf-8")
        response = self.http.request_json(
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

    def _build_admin_auth_payload(self) -> dict[str, str]:
        """Select service-account or password grant payload."""
        if self.settings.admin.client_id:
            return {
                "grant_type": "client_credentials",
                "client_id": self.settings.admin.client_id,
                "client_secret": self.settings.admin.client_secret,
            }
        return {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.settings.admin.username,
            "password": self.settings.admin.password,
        }

    def get_client_uuid(self, token: str) -> str:
        """Resolve the target client UUID from configured clientId."""
        client_id = self.settings.realm.client_id
        found = self._client_uuid_from_query(token, client_id)
        if found:
            return found
        found = self._find_client_uuid_paged(token, client_id)
        if found:
            return found
        raise RuntimeError(f"Client not found: {client_id}")

    def _client_uuid_from_query(self, token: str, client_id: str) -> str:
        """Try resolving client UUID using the direct clientId query."""
        query = urlencode({"clientId": client_id})
        clients = self.http.request_json(
            f"{self.admin_url}/{self.settings.realm.name}/clients?{query}",
            token=token,
        )
        return self._extract_client_uuid(clients, client_id)

    def _find_client_uuid_paged(self, token: str, client_id: str) -> str:
        """Scan paginated client results to find a matching client UUID."""
        first = 0
        while True:
            clients = self.http.request_json(
                f"{self.admin_url}/{self.settings.realm.name}/clients"
                f"?first={first}&max={PAGE_SIZE}",
                token=token,
            )
            if not clients:
                return ""
            found = self._extract_client_uuid(clients, client_id)
            if found:
                return found
            if len(clients) < PAGE_SIZE:
                return ""
            first += PAGE_SIZE

    def _extract_client_uuid(self, clients: list[dict[str, Any]], client_id: str) -> str:
        """Find matching client UUID from a list of client dicts."""
        for client in clients:
            if client.get("clientId") == client_id and client.get("id"):
                return client["id"]
        return ""

    def _configure_mappers(self, token: str, client_uuid: str) -> None:
        """Configure mappers either through shared scope or per-client mapping."""
        if self.settings.realm.use_shared_scope:
            self._configure_shared_scope_mappers(token, client_uuid)
            return
        for mapper in self.settings.mappers:
            self.ensure_mapper_on_client(token, client_uuid, mapper)

    def _configure_shared_scope_mappers(self, token: str, client_uuid: str) -> None:
        """Ensure shared scope exists, contains mappers, and is assigned."""
        scope_id = self.get_or_create_scope_id(token)
        for mapper in self.settings.mappers:
            self.ensure_mapper(token, scope_id, mapper)
        self.ensure_scope_assigned(token, client_uuid, scope_id)

    def get_or_create_scope_id(self, token: str) -> str:
        """Resolve shared scope ID, creating the scope when missing."""
        scope_name = self.settings.realm.shared_scope_name
        found = self._find_scope_id(token, scope_name)
        if found:
            return found
        self._create_scope(token, scope_name)
        found = self._find_scope_id(token, scope_name)
        if found:
            return found
        raise RuntimeError(f"Failed to resolve shared scope: {scope_name}")

    def _find_scope_id(self, token: str, scope_name: str) -> str:
        """Find scope ID by shared scope name."""
        scopes = self.http.request_json(
            f"{self.admin_url}/{self.settings.realm.name}/client-scopes?q={scope_name}",
            token=token,
        )
        for scope in scopes:
            if scope.get("name") == scope_name and scope.get("id"):
                return scope["id"]
        return ""

    def _create_scope(self, token: str, scope_name: str) -> None:
        """Create a client scope for shared custom mappers."""
        self.http.request_empty(
            f"{self.admin_url}/{self.settings.realm.name}/client-scopes",
            method="POST",
            json_data={
                "name": scope_name,
                "protocol": "openid-connect",
                "description": "DTaaS shared custom mappers (profile claim; optional groups)",
            },
            token=token,
        )

    def ensure_mapper(self, token: str, scope_id: str, mapper: dict[str, Any]) -> None:
        """Upsert mapper by name in the shared scope."""
        endpoint = (
            f"{self.admin_url}/{self.settings.realm.name}/client-scopes/{scope_id}"
            "/protocol-mappers/models"
        )
        self._ensure_mapper_at_endpoint(token, endpoint, mapper)

    def ensure_mapper_on_client(
        self, token: str, client_uuid: str, mapper: dict[str, Any]
    ) -> None:
        """Upsert mapper by name directly on a target client."""
        endpoint = (
            f"{self.admin_url}/{self.settings.realm.name}/clients/{client_uuid}"
            "/protocol-mappers/models"
        )
        self._ensure_mapper_at_endpoint(token, endpoint, mapper)

    def _ensure_mapper_at_endpoint(
        self, token: str, endpoint: str, mapper: dict[str, Any]
    ) -> None:
        """Create or update mapper by name for the provided endpoint."""
        existing = self.http.request_json(endpoint, token=token)
        existing_id = self._find_mapper_id(existing, mapper["name"])
        if not existing_id:
            self.http.request_empty(endpoint, method="POST", json_data=mapper, token=token)
            return
        updated = dict(mapper)
        updated["id"] = existing_id
        self.http.request_empty(
            f"{endpoint}/{existing_id}", method="PUT", json_data=updated, token=token
        )

    def _find_mapper_id(self, existing: list[dict[str, Any]], mapper_name: str) -> str:
        """Return mapper id for a mapper name if present in existing mappings."""
        for item in existing:
            if item.get("name") == mapper_name and item.get("id"):
                return item["id"]
        return ""

    def ensure_scope_assigned(self, token: str, client_uuid: str, scope_id: str) -> None:
        """Ensure shared scope is assigned as default scope on the client."""
        endpoint = (
            f"{self.admin_url}/{self.settings.realm.name}"
            f"/clients/{client_uuid}/default-client-scopes"
        )
        assigned = self.http.request_json(endpoint, token=token)
        if any(scope.get("id") == scope_id for scope in assigned):
            return
        self.http.request_empty(f"{endpoint}/{scope_id}", method="PUT", token=token)