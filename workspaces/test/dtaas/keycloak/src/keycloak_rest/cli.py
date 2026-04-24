"""CLI entrypoint for Keycloak REST configuration."""

from __future__ import annotations

import argparse
import sys

from .configurator import KeycloakRestConfigurator
from .dotenv import load_dotenv_file, resolve_default_env_file
from .settings import settings_from_env, validate_admin_auth


def parse_args() -> argparse.Namespace:
    """Create and parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Configure Keycloak shared scope mappers for DTaaS"
    )
    parser.add_argument(
        "--env-file",
        default="",
        help="Path to .env file containing KEYCLOAK_* settings",
    )
    return parser.parse_args()


def configure_from_args(args: argparse.Namespace) -> None:
    """Load environment file and run Keycloak configuration."""
    env_file = args.env_file or resolve_default_env_file()
    if env_file:
        load_dotenv_file(env_file)
    settings = settings_from_env()
    validate_admin_auth(settings.admin)
    configurator = KeycloakRestConfigurator(settings)
    configurator.run()


def main() -> int:
    """Command-line entrypoint."""
    try:
        configure_from_args(parse_args())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print("Keycloak shared scope and mappers configured successfully (REST API).")
    return 0
