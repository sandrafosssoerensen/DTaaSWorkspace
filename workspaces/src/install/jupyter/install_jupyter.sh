#!/usr/bin/env bash
set -xe

# Installs Jupyter and Python3

DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends\
    python3 \
    python3-pip

pip install --break-system-packages --no-cache-dir \
    jupyterlab \
    notebook