"""User profile attribute helpers for Keycloak REST configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from .constants import PAGE_SIZE
from .http_client import HttpClient


@dataclass(frozen=True)
class AdminContext:
    """Bundled admin HTTP context passed to user-profile helpers."""

    admin_url: str
    realm: str
    token: str
    http: HttpClient


def ensure_user_profile_mappers(ctx: AdminContext) -> None:
    """Ensure user-profile metadata exists for mapped user attributes."""
    endpoint = f"{ctx.admin_url}/{ctx.realm}/users/profile"
    profile = ctx.http.request_json(endpoint, token=ctx.token)
    attributes = profile.get("attributes", [])
    for name, display in {"profile": "Profile URL"}.items():
        _upsert_profile_attribute(attributes, name, display)
    profile["attributes"] = attributes
    ctx.http.request_empty(endpoint, method="PUT", json_data=profile, token=ctx.token)


def _upsert_profile_attribute(
    attributes: list[dict[str, Any]], name: str, display: str
) -> None:
    """Create or normalize one user-profile attribute entry by name."""
    for attr in attributes:
        if attr.get("name") == name:
            attr["displayName"] = display
            attr["permissions"] = {"view": ["admin"], "edit": ["admin"]}
            attr["multivalued"] = False
            attr.pop("required", None)
            return
    attributes.append(
        {
            "name": name,
            "displayName": display,
            "permissions": {"view": ["admin"], "edit": ["admin"]},
            "multivalued": False,
        }
    )


def update_user_profiles(
    ctx: AdminContext,
    profile_base_url: str,
    user_profiles: list[str] | None,
) -> None:
    """Merge and update each selected user's profile attribute URL."""
    selected = set(user_profiles or [])
    for user in _iter_realm_users(ctx):
        if not _user_selected(user, selected):
            continue
        _update_user_profile(ctx, user["id"], user["username"], profile_base_url)


def _iter_realm_users(ctx: AdminContext) -> list[dict[str, Any]]:
    """Collect users from paginated realm user API calls."""
    users: list[dict[str, Any]] = []
    first = 0
    while True:
        query = urlencode({"first": first, "max": PAGE_SIZE})
        page = ctx.http.request_json(
            f"{ctx.admin_url}/{ctx.realm}/users?{query}", token=ctx.token
        )
        if not page:
            return users
        users.extend(page)
        if len(page) < PAGE_SIZE:
            return users
        first += PAGE_SIZE


def _user_selected(user: dict[str, Any], selected: set[str]) -> bool:
    """Return whether a user has required fields and matches selection."""
    username = user.get("username", "")
    user_id = user.get("id", "")
    if not user_id or not username:
        return False
    return not selected or username in selected


def _update_user_profile(
    ctx: AdminContext, user_id: str, username: str, profile_base_url: str
) -> None:
    """Update one user to include the expected profile URL attribute."""
    endpoint = f"{ctx.admin_url}/{ctx.realm}/users/{user_id}"
    user_details = ctx.http.request_json(endpoint, token=ctx.token)
    merged_attributes = dict(user_details.get("attributes", {}))
    merged_attributes["profile"] = [_profile_url(profile_base_url, username)]
    payload = dict(user_details)
    payload["attributes"] = merged_attributes
    ctx.http.request_empty(endpoint, method="PUT", json_data=payload, token=ctx.token)


def _profile_url(profile_base_url: str, username: str) -> str:
    """Build normalized user profile URL from configured base URL."""
    return f"{profile_base_url.rstrip('/')}/{username}"
