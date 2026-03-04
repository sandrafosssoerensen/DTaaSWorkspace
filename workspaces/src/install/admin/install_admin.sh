#!/usr/bin/env bash
set -e

echo "Installing Admin Service"

# Install Poetry and pipx
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3-poetry \
    python-is-python3 \
    pipx

poetry --version
pipx --version

# Copy admin service to /opt/admin
cp -r "${ADMIN_DIR}" /opt/

# Verify pyproject.toml exists
if [[ ! -f /opt/admin/pyproject.toml ]]; then
    echo "Error: pyproject.toml not found in /opt/admin"
    ls -la /opt/admin/
    exit 1
fi

# Build the wheel package
cd /opt/admin
poetry config virtualenvs.in-project true
poetry install --only main --no-root
poetry build

# Install the wheel package using pipx
# Find the built wheel file
WHEEL_FILE=$(find /opt/admin/dist -name "*.whl" -type f | head -n 1) || true
if [[ -z "${WHEEL_FILE}" ]]; then
    echo "Error: No wheel file found in /opt/admin/dist"
    exit 1
fi

echo "Installing wheel: ${WHEEL_FILE}"
pipx install "${WHEEL_FILE}"
pipx ensurepath
# shellcheck disable=SC1090
source ~/.bashrc

# Verify installation
if ! command -v workspace-admin &> /dev/null; then
    echo "Error: workspace-admin command not found after installation"
    exit 1
fi

workspace-admin --version

echo "Admin Service installation complete"
