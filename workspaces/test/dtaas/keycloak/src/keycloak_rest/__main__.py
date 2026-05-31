"""Runnable module entrypoint for Keycloak REST configurator."""

from .cli import main

if __name__ == "__main__":
    exit(main())
