# Automated CI Testing (No Real OAuth Provider Needed)

Running the OAuth2 authentication flow in a CI environment
(e.g. GitHub Actions) is challenging because the standard authorization-code
flow requires a human to open a browser, enter credentials, and
click "Authorize".

This project solves the problem by replacing the real identity provider with
**[Dex](https://dexidp.io/)** – a lightweight, CNCF-standard OIDC server –
and scripting the entire login flow with Python's `requests` library.

## How it works

```text
requests.get()  →  Traefik  →  traefik-forward-auth  →  302 to Dex
  ↓                                                         ↓
POST credentials to Dex form  (no approval screen)
  ↓
302 to /_oauth?code=XXX  →  traefik-forward-auth exchanges code
  ↓
Sets _forward_auth session cookie  →  302 to /user1/
  ↓
GET /user1/ with cookie  →  HTTP 200  ✅
```

Two Dex settings make this fully headless:

- `skipApprovalScreen: true` — no consent page is presented after login
- `enablePasswordDB: true` — static username/password pairs in config

## Using the CI compose setup locally (HTTP)

```bash
# Start the self-contained CI stack (Dex + Traefik + forward-auth + workspaces)
docker compose -f workspaces/test/dtaas/ci/compose.traefik.secure.yml up -d

# Add local hostname resolution for Dex (needed so requests can follow
# OAuth redirects)
echo "127.0.0.1 dex" | sudo tee -a /etc/hosts

# Run the automated login script
pip install requests
python3 workspaces/test/dtaas/ci/scripts/ci_auth_login.py \
  http://localhost user1 http://dex:5556 password
```

## Testing the TLS setup on a developer machine

The TLS CI stack (`compose.traefik.secure.tls.yml`) uses certificates generated
by [mkcert](https://github.com/FiloSottile/mkcert) so that the
`traefik-forward-auth` container can validate HTTPS redirects through
`localhost` without disabling certificate verification.

### 1 — Install mkcert

**Linux / macOS (Homebrew)**

```bash
brew install mkcert
```

**Linux (direct binary)**

```bash
# Adjust the tag and arch as needed (linux-amd64 / linux-arm64)
MKCERT_VERSION="v1.4.4"
MKCERT_ARCH="linux-amd64"
curl -fsSL \
  "https://github.com/FiloSottile/mkcert/releases/download/${MKCERT_VERSION}/mkcert-${MKCERT_VERSION}-${MKCERT_ARCH}" \
  -o /tmp/mkcert
chmod +x /tmp/mkcert
sudo mv /tmp/mkcert /usr/local/bin/mkcert
```

**Windows (Chocolatey / Scoop)**

```powershell
choco install mkcert      # or: scoop install mkcert
```

### 2 — Install the local CA

This step installs mkcert's root CA into your system/browser trust stores
so that browsers and `curl` will trust the generated certificate.

```bash
mkcert -install
```

### 3 — Generate TLS certificates

Run from the **repository root**:

```bash
mkcert \
  -cert-file workspaces/test/dtaas/ci/certs/fullchain.pem \
  -key-file  workspaces/test/dtaas/ci/certs/privkey.pem \
  localhost 127.0.0.1 ::1

chmod 644 workspaces/test/dtaas/ci/certs/fullchain.pem
chmod 600 workspaces/test/dtaas/ci/certs/privkey.pem
```

Then copy the mkcert root CA into the certs directory so that the
`traefik-forward-auth` custom image can embed it:

```bash
cp "$(mkcert -CAROOT)/rootCA.pem" workspaces/test/dtaas/ci/certs/rootCA.crt
```

### 4 — Build the CA-aware traefik-forward-auth image

The custom image (`certs/Dockerfile`) layers the mkcert root CA on top of
the upstream `traefik-forward-auth` image so HTTPS redirects through
`localhost` are trusted:

```bash
docker build \
  -t traefik-forward-auth-local:latest \
  workspaces/test/dtaas/ci/certs/
```

### 5 — Add the Dex hostname to /etc/hosts

OAuth redirects from `traefik-forward-auth` point at `http://dex:5556/...`.
The Python login script runs on the host, so it needs `dex` to resolve:

```bash
echo "127.0.0.1 dex" | sudo tee -a /etc/hosts
```

### 6 — Start the TLS stack

```bash
docker compose \
  -f workspaces/test/dtaas/ci/compose.traefik.secure.tls.yml \
  up -d

echo "Waiting for services to be ready..."
sleep 30   # reduce to taste; Dex and Traefik are fast to start
```

Check that all containers are running:

```bash
docker compose \
  -f workspaces/test/dtaas/ci/compose.traefik.secure.tls.yml \
  ps
```

### 7 — Run the headless OAuth2 login script (HTTPS)

```bash
pip install requests

python3 workspaces/test/dtaas/ci/scripts/ci_auth_login.py \
  --no-verify https://localhost user1 http://dex:5556 password
```

`--no-verify` skips TLS verification in the Python `requests` calls (the
CA is embedded in the forward-auth container, not in the host Python
environment). A successful run ends with:

```
✅  Login successful – HTTP 200 received for /user1/
```

### 8 — Clean up

```bash
docker compose \
  -f workspaces/test/dtaas/ci/compose.traefik.secure.tls.yml \
  down -v

# Remove generated certificates (optional)
rm workspaces/test/dtaas/ci/certs/fullchain.pem \
   workspaces/test/dtaas/ci/certs/privkey.pem \
   workspaces/test/dtaas/ci/certs/rootCA.crt
```

## Relevant files

| File                             | Purpose                                       |
| -------------------------------- | --------------------------------------------- |
| `config/dex.yml`                 | Dex OIDC configuration with static test users |
| `compose.traefik.secure.yml`     | Self-contained CI stack (HTTP)                |
| `compose.traefik.secure.tls.yml` | Self-contained CI stack (HTTPS/TLS)           |
| `scripts/ci_auth_login.py`       | Headless OAuth2 login script (Python)         |
| `certs/Dockerfile`               | CA-aware traefik-forward-auth image for TLS   |

## Static test users

The test users are configured in `config/dex.yml`. Emails must match the
whitelist rules in `config/conf`. Default credentials:

| Username | Email             | Password   |
| -------- | ----------------- | ---------- |
| `user1`  | `user1@localhost` | `password` |
| `user2`  | `user2@localhost` | `password` |
