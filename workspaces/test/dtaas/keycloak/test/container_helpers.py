"""Container lifecycle helpers for Keycloak integration tests."""

from __future__ import annotations

import subprocess


def remove_container(container_name: str) -> None:
    """Best-effort remove of integration-test container."""
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def docker_run_keycloak(
    container_name: str,
    port: int,
    admin_user: str,
    admin_password: str,
) -> None:
    """Start a disposable Keycloak container for integration testing."""
    result = subprocess.run(
        _docker_run_args(container_name, port, admin_user, admin_password),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start Keycloak container: {result.stderr}")


def _docker_run_args(
    container_name: str,
    port: int,
    admin_user: str,
    admin_password: str,
) -> list[str]:
    """Build docker run arguments for disposable Keycloak startup."""
    return [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        container_name,
        "-p",
        f"{port}:8080",
        "-e",
        f"KC_BOOTSTRAP_ADMIN_USERNAME={admin_user}",
        "-e",
        f"KC_BOOTSTRAP_ADMIN_PASSWORD={admin_password}",
        "quay.io/keycloak/keycloak:26.0.7",
        "start-dev",
    ]


def container_running(container_name: str) -> bool:
    """Check whether an integration container is still running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def container_logs_tail(container_name: str) -> str:
    """Return the most recent container logs for diagnostics."""
    result = subprocess.run(
        ["docker", "logs", "--tail", "80", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout or result.stderr or "<no logs available>"
