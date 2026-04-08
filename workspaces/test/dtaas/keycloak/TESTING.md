# Testing the Python Keycloak Configurator

This guide explains how to test
`workspaces/test/dtaas/keycloak/configure_keycloak_rest.py` against a real
Keycloak instance.

## What This Tests

The Python script configures a Keycloak realm by:

1. Requesting an admin token.
2. Resolving the target client UUID.
3. Creating the required protocol mapper(s) directly on the client (default), or
   on a named shared client scope when `KEYCLOAK_USE_SHARED_SCOPE=true` is set.

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

Then create the test realm and client:

1. Open the administration console.
2. Create realm `dtaas`.
3. Create client `dtaas-workspace`.

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

## Run the Python Script

From the repository root, load configuration from `.env` file and run the script:

### Command to run (with --env-file)

```powershell
cd workspaces/test/dtaas/keycloak
python configure_keycloak_rest.py --env-file ../config/.env
```

Or from the repository root:

```powershell
python workspaces/test/dtaas/keycloak/configure_keycloak_rest.py --env-file workspaces/test/dtaas/config/.env
```

### Alternative: Direct environment variables (legacy)

If you prefer to set environment variables directly instead of using an .env file:

```powershell
$env:KEYCLOAK_BASE_URL = "http://localhost:18080"
$env:KEYCLOAK_CONTEXT_PATH = "/"
$env:KEYCLOAK_REALM = "dtaas"
$env:KEYCLOAK_CLIENT_ID = "dtaas-workspace"
$env:KEYCLOAK_ADMIN = "admin"
$env:KEYCLOAK_ADMIN_PASSWORD = "admin"

python workspaces/test/dtaas/keycloak/configure_keycloak_rest.py
```

## How to Verify the Result

In the Keycloak admin console, verify the following.

### Protocol Mappers (default mode)

1. Open `Clients` → `dtaas-workspace` → `Client scopes` tab.
2. Click the dedicated client scope (named after the client) → `Mappers`.
3. Confirm that `profile` exists with:
   - User attribute: `profile`
   - Add to userinfo: on
   - Add to access token: off

### Client Scope Mappers (shared scope mode)

1. Open `Client scopes` → `dtaas-shared` (or your configured scope name).
2. Open its `Mappers` tab.
3. Confirm that `profile` exists with the settings above.
4. Open `Clients` → `dtaas-workspace` → `Client scopes` tab.
5. Confirm `dtaas-shared` appears under default scopes.

## Run the Unit Tests Too

```powershell
python -m unittest discover -s workspaces/test/dtaas/keycloak -p "test_*.py"
```

## Run the Integration Test (Real Keycloak)

The integration test lives in
`workspaces/test/dtaas/keycloak/test_integration_keycloak_rest.py`.

It starts a disposable Keycloak container, creates:

1. A test realm.
2. A target client (public, direct-access grants enabled).
3. A test user with a pre-seeded `profile` attribute and a login password.
4. A dedicated admin automation client (service account) with required roles.

Then it runs `configure_keycloak_rest.py` using `client_credentials` and verifies:

1. Required mapper (`profile`) is present on the target client.
2. Userinfo endpoint returns the `profile` claim for the test user.

Run it explicitly:

```powershell
$env:RUN_KEYCLOAK_INTEGRATION = "1"
py -m unittest workspaces.test.dtaas.keycloak.test_integration_keycloak_rest
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

### `Client not found: dtaas-workspace`

Create the client first in the target realm, or set `KEYCLOAK_CLIENT_ID` to an
existing client.

### `KEYCLOAK_SHARED_SCOPE_NAME must be set`

`KEYCLOAK_USE_SHARED_SCOPE=true` was set but `KEYCLOAK_SHARED_SCOPE_NAME` was
not provided. Set both variables together.

### TLS or certificate failures

If you are testing against a self-signed TLS endpoint, use a trusted
certificate on the host or test against a local HTTP endpoint first.

### Wrong context path

Use:

1. `KEYCLOAK_CONTEXT_PATH=/` for recent `start-dev` containers.
2. `KEYCLOAK_CONTEXT_PATH=/auth` when Keycloak is exposed under `/auth`.