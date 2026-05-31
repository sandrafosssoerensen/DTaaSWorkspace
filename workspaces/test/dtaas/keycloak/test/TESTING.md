# Testing the Python Keycloak Configurator

This guide explains how to test the modular Keycloak REST configurator against a real
Keycloak instance.

## Module Structure

The Keycloak configurator is organized into two main packages:

- **`src/keycloak_rest/`**:
  - `cli.py` — Command-line interface
  - `configurator.py` — Main workflow orchestration
  - `user_profiles.py` — User profile attribute helpers and `AdminContext`
  - `settings.py` — Configuration parsing
  - `http_client.py` — HTTP request handling
  - `dotenv.py` — Environment file handling
  - `constants.py` — Static definitions (mappers, pagination)

- **`test/`** — Test modules:
  - `test_configure_keycloak_rest.py` — Unit tests
  - `test_integration_keycloak_rest.py` — Integration tests
  - `integration_helpers.py` — Helper utilities
  - `integration_setup.py` — Setup helpers
  - `container_helpers.py` — Docker lifecycle helpers

## What This Tests

The Python script configures a Keycloak realm by:

1. Requesting an admin token.
2. Resolving the target client UUID from `KEYCLOAK_MAPPER_CLIENT_ID` (falls back
   to `KEYCLOAK_CLIENT_ID`, then defaults to `dtaas-client`).
3. Creating the required protocol mapper(s) directly on the client
   (`KEYCLOAK_USE_SHARED_SCOPE=false`, the default), or on a named shared client
   scope when `KEYCLOAK_USE_SHARED_SCOPE=true` is set.
4. Setting each user's `profile` attribute to `<KEYCLOAK_PROFILE_BASE_URL>/<username>`.

`KEYCLOAK_CLIENT_ID` is used exclusively by `traefik-forward-auth` for gateway
authentication and is intentionally separate from `KEYCLOAK_MAPPER_CLIENT_ID`,
which controls which client receives the custom mappers.

## Prerequisites

You need:

1. Python 3 available on your host.
2. A running Keycloak instance.
3. An admin username and password for that Keycloak instance.
4. A realm and client to target.

## Option 1: Test Against a Temporary Local Keycloak Container

Start a disposable Keycloak container:

```powershell
docker run --rm -d --name keycloak-test `
  -p 18080:8080 `
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin `
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin `
  quay.io/keycloak/keycloak:26.0.7 start-dev
```

After the container starts, open the admin console at:

```text
http://localhost:18080
```

Then create the test realm and clients:

1. Open the administration console.
2. Create realm `dtaas`.
3. Create client `dtaas-client` (receives custom mappers — the configurator target).
4. Create client `dtaas-workspace` (confidential, used by `traefik-forward-auth`).

## Option 2: Test Against the Repository's DTaaS Keycloak Service

If you want to test against the Keycloak service used by the DTaaS test setup,
follow the environment setup in [workspaces/test/dtaas/KEYCLOAK_SETUP.md](../KEYCLOAK_SETUP.md)
and start one of the secure compose files.

Example:

```powershell
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml --env-file workspaces/test/dtaas/config/.env up -d
```

If you use the compose-based Keycloak, set the variables as follows:

- `KEYCLOAK_BASE_URL` — the base origin only, **without** the context path:
  - `http://localhost` (compose default, Keycloak at `/auth`)
  - `https://<SERVER_DNS>` (TLS with DNS)
- `KEYCLOAK_CONTEXT_PATH` — the path prefix Keycloak is mounted at (e.g. `/auth`)

## Run the Python Module

From the repository root, load configuration from `.env` file and run the configurator module:

### Command to run (with --env-file)

```powershell
cd workspaces/test/dtaas/keycloak
python -m src.keycloak_rest --env-file ../config/.env
```

Or from the repository root:

```powershell
python -m workspaces.test.dtaas.keycloak.src.keycloak_rest --env-file workspaces/test/dtaas/config/.env
```

### Alternative: Direct environment variables

If you prefer to set environment variables directly instead of using an .env file:

```powershell
$env:KEYCLOAK_BASE_URL = "http://localhost:18080"
$env:KEYCLOAK_CONTEXT_PATH = "/"
$env:KEYCLOAK_REALM = "dtaas"
$env:KEYCLOAK_MAPPER_CLIENT_ID = "dtaas-client"   # client that receives the mappers
$env:KEYCLOAK_CLIENT_ID = "dtaas-workspace"        # used by traefik-forward-auth only
$env:KEYCLOAK_ADMIN = "admin"
$env:KEYCLOAK_ADMIN_PASSWORD = "admin"

python -m workspaces.test.dtaas.keycloak.src.keycloak_rest
```

## How to Verify the Result

In the Keycloak admin console, verify the following.

### Protocol Mappers (default mode)

1. Open `Clients` → `dtaas-client` → `Mappers` tab.
2. Confirm that `profile` and `groups` exist with:
   - `profile`: User attribute `profile`, Add to userinfo: on, Add to access token: off
   - `groups`: Add to access token: on, Add to userinfo: on
3. Open `Clients` → `dtaas-workspace` → `Mappers` tab.
4. Confirm it is **empty** — mappers belong on `dtaas-client`, not `dtaas-workspace`.

### Client Scope Mappers (shared scope mode)

1. Open `Client scopes` → `dtaas-shared` (or your configured scope name).
2. Open its `Mappers` tab.
3. Confirm that `profile` and `groups` exist with the settings above.
4. Open `Clients` → `dtaas-client` → `Client scopes` tab.
5. Confirm `dtaas-shared` appears under default scopes.

### User Profile Attributes

1. Open `Users` → select `user1` → `Attributes` tab.
2. Confirm `profile` = `https://<SERVER_DNS>/user1`.
3. Repeat for other users.

## Run the Unit Tests

```powershell
python -m unittest workspaces.test.dtaas.keycloak.test.test_configure_keycloak_rest -v
```

## Run the Integration Test (Real Keycloak)

The integration test lives in
`workspaces/test/dtaas/keycloak/test/test_integration_keycloak_rest.py`.

It starts a disposable Keycloak container, creates:

1. A test realm.
2. A target client (public, direct-access grants enabled).
3. A test user with a pre-seeded `profile` attribute and a login password.
4. A dedicated admin automation client (service account) with required roles.

Then it runs the configurator module using `client_credentials` and verifies:

1. Required mapper (`profile`) is present on the target client.
2. Userinfo endpoint returns the `profile` claim for the test user.

Run it explicitly:

```powershell
$env:RUN_KEYCLOAK_INTEGRATION = "1"
py -m unittest workspaces.test.dtaas.keycloak.test.test_integration_keycloak_rest
```

Optional custom port:

```powershell
$env:RUN_KEYCLOAK_INTEGRATION = "1"
$env:KEYCLOAK_INTEGRATION_PORT = "18082"
py -m unittest workspaces.test.dtaas.keycloak.test_integration_keycloak_rest
```

By design, this test is skipped unless `RUN_KEYCLOAK_INTEGRATION=1` is set.

## Troubleshooting

### `Failed to retrieve admin access token`

Check:

1. The base URL and context path are correct.
2. The admin username and password are correct.
3. The Keycloak container is fully started.

### `Client not found: dtaas-client`

Create `dtaas-client` first in the target realm. The configurator targets
`KEYCLOAK_MAPPER_CLIENT_ID` (default: `dtaas-client`), not `KEYCLOAK_CLIENT_ID`.
`KEYCLOAK_CLIENT_ID` is reserved for `traefik-forward-auth`.

### Shared scope mode issues

If `KEYCLOAK_USE_SHARED_SCOPE=true`, the script places mappers on a shared
client scope; `KEYCLOAK_SHARED_SCOPE_NAME` controls the scope name and
defaults to `dtaas-shared`. When unset or `false` (the default), mappers are
placed directly on the client.

### TLS or certificate failures

If you are testing against a self-signed TLS endpoint, use a trusted
certificate on the host or test against a local HTTP endpoint first.

### Wrong context path

Use:

1. `KEYCLOAK_CONTEXT_PATH=/` for recent `start-dev` containers.
2. `KEYCLOAK_CONTEXT_PATH=/auth` when Keycloak is exposed under `/auth`.