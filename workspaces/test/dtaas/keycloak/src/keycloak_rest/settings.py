"""Settings and environment parsing for Keycloak REST configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AdminAuth:
    """Admin credentials for Keycloak API access."""

    client_id: str = ""
    client_secret: str = ""
    username: str = "admin"
    password: str = "admin"


@dataclass(frozen=True)
class RealmConfig:
    """Keycloak realm and client configuration."""

    name: str = "dtaas"
    client_id: str = "dtaas-workspace"
    use_shared_scope: bool = False
    shared_scope_name: str = "dtaas-shared"
    user_profiles: list[str] | None = None


@dataclass(frozen=True)
class Settings:
    """Configuration settings loaded from environment variables."""

    keycloak_base_url: str = "http://localhost"
    keycloak_context_path: str = "/auth"
    profile_base_url: str = ""
    realm: RealmConfig = field(default_factory=RealmConfig)
    admin: AdminAuth = field(default_factory=AdminAuth)


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
    raise RuntimeError(f"Invalid boolean value for {name}: '{raw}'. Use true/false.")


def parse_user_profiles_env(name: str) -> list[str] | None:
    """Parse optional JSON list of usernames from environment."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    loaded = _load_json_array(raw, name)
    usernames = [str(item).strip() for item in loaded if str(item).strip()]
    return usernames or None


def _load_json_array(raw: str, name: str) -> list[object]:
    """Parse a JSON value and validate it is an array."""
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON value for {name}. Expected array of usernames."
        ) from exc
    if not isinstance(loaded, list):
        raise RuntimeError(f"Invalid value for {name}. Expected JSON array.")
    return loaded


def normalize_path(path: str) -> str:
    """Normalize context path so root resolves to an empty suffix."""
    if path in ("", "/"):
        return ""
    return path[:-1] if path.endswith("/") else path


def settings_from_env() -> Settings:
    """Build settings using environment variables with script defaults."""
    base_url = os.getenv("KEYCLOAK_BASE_URL", "http://localhost")
    profile_default = os.getenv("PROFILE_BASE_URL", base_url)
    return Settings(
        keycloak_base_url=base_url,
        keycloak_context_path=os.getenv("KEYCLOAK_CONTEXT_PATH", "/auth"),
        profile_base_url=os.getenv("KEYCLOAK_PROFILE_BASE_URL", profile_default),
        realm=RealmConfig(
            name=os.getenv("KEYCLOAK_REALM", "dtaas"),
            client_id=os.getenv("KEYCLOAK_CLIENT_ID", "dtaas-workspace"),
            use_shared_scope=parse_bool_env("KEYCLOAK_USE_SHARED_SCOPE", False),
            shared_scope_name=os.getenv("KEYCLOAK_SHARED_SCOPE_NAME", "dtaas-shared"),
            user_profiles=parse_user_profiles_env("KEYCLOAK_USER_PROFILES"),
        ),
        admin=AdminAuth(
            client_id=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", ""),
            client_secret=os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", ""),
            username=os.getenv("KEYCLOAK_ADMIN", "admin"),
            password=os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin"),
        ),
    )
