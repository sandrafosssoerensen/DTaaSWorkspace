#!/usr/bin/env bash
set -e

apt-get clean
rm -rf /var/lib/apt/lists/*
rm -Rf /root/.cache/pip
rm -rf /tmp/*