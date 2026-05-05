#!/usr/bin/env bash
set -xe

# Installs Jupyter and Python3

DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    python3 \
    python3-pip

# This package was preinstalled on the system and was clashing with the dependencies for jupyter
apt-get remove -y python3-psutil

pip install --break-system-packages --no-cache-dir \
    jupyter