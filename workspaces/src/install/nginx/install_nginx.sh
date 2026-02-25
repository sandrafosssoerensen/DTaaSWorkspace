#!/usr/bin/env bash
set -xe

DEBIAN_FRONTEND=noninteractive apt-get install -y curl gnupg2 ca-certificates lsb-release ubuntu-keyring

curl https://nginx.org/keys/nginx_signing.key | gpg --dearmor \
    | tee /usr/share/keyrings/nginx-archive-keyring.gpg >/dev/null

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] \
http://nginx.org/packages/ubuntu $(lsb_release -cs) nginx" \
    | tee /etc/apt/sources.list.d/nginx.list

echo -e "Package: *\nPin: origin nginx.org\nPin: release o=nginx\nPin-Priority: 900\n" \
    | tee /etc/apt/preferences.d/99nginx

DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y nginx

mkdir -p "${HOME}/.nginx/logs"
mkdir -p "${HOME}/.nginx/temp"
chown -R 1000:0 "${HOME}/.nginx"