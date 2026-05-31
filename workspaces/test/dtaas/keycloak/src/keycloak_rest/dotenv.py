"""Helpers for loading dotenv configuration files."""

from pathlib import Path
import os


def load_dotenv_file(env_file: str) -> None:
    """Load KEY=VALUE pairs from a dotenv file into process environment."""
    path = Path(env_file)
    if not path.is_file():
        raise RuntimeError(f"Env file not found: {env_file}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        _apply_line(raw_line)


def _apply_line(raw_line: str) -> None:
    """Parse one dotenv line and apply it to the environment."""
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return
    key, value = line.split("=", 1)
    normalized_key = key.strip()
    normalized_value = _unquote(value.strip())
    os.environ[normalized_key] = normalized_value


def _unquote(value: str) -> str:
    """Drop matching surrounding single or double quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def resolve_default_env_file() -> str | None:
    """Resolve a default dotenv path when available."""
    cwd_env = Path(".env")
    if cwd_env.is_file():
        return str(cwd_env)
    script_default = Path(__file__).resolve().parents[2] / "config" / ".env"
    if script_default.is_file():
        return str(script_default)
    return None
