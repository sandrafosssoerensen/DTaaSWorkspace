# Testing the Python Keycloak Configurator

This guide explains how to test
`workspaces/test/dtaas/keycloak/configure_keycloak_rest.py` against a real
Keycloak instance.

## What This Tests

The Python script configures a Keycloak realm by:

1. Requesting an admin token.
2. Resolving the target client.
3. Creating or reusing the `dtaas-shared` client scope.
4. Creating the required protocol mappers.
5. Ensuring the `profile` and `sub_legacy` user profile attributes exist.
6. Assigning the shared scope to the target client.
7. Updating each user's `profile` attribute.

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
4. Create one or more users if you want to verify profile updates.

## Option 2: Test Against the Repository's DTaaS Keycloak Service

If you want to test against the Keycloak service used by the DTaaS test setup,
follow the environment setup in [workspaces/test/dtaas/KEYCLOAK_SETUP.md](../KEYCLOAK_SETUP.md)
and start one of the secure compose files.

Example:

```powershell
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml --env-file workspaces/test/dtaas/config/.env up -d
```

If you use the compose-based Keycloak, the base URL is typically:

```text
http://localhost/auth
```

or, when running behind TLS and a configured DNS name:

```text
https://<SERVER_DNS>/auth
```

## Run the Python Script

From the repository root, set the required environment variables and run the
script.

### Example for a local `start-dev` container

```powershell
$env:KEYCLOAK_BASE_URL = "http://localhost:18080"
$env:KEYCLOAK_CONTEXT_PATH = "/"
$env:KEYCLOAK_REALM = "dtaas"
$env:KEYCLOAK_CLIENT_ID = "dtaas-workspace"
$env:KEYCLOAK_SHARED_SCOPE_NAME = "dtaas-shared"
$env:KEYCLOAK_ADMIN = "admin"
$env:KEYCLOAK_ADMIN_PASSWORD = "admin"
$env:PROFILE_BASE_URL = "https://localhost/gitlab"

python workspaces/test/dtaas/keycloak/configure_keycloak_rest.py
```

### Example for a Keycloak instance exposed at `/auth`

```powershell
$env:KEYCLOAK_BASE_URL = "https://foo.com"
$env:KEYCLOAK_CONTEXT_PATH = "/auth"
$env:KEYCLOAK_REALM = "dtaas"
$env:KEYCLOAK_CLIENT_ID = "dtaas-workspace"
$env:KEYCLOAK_ADMIN = "admin"
$env:KEYCLOAK_ADMIN_PASSWORD = "changeme"

python workspaces/test/dtaas/keycloak/configure_keycloak_rest.py
```

Expected success output:

```text
Keycloak shared scope and mappers configured successfully (REST API).
```

## How to Verify the Result

In the Keycloak admin console, verify the following.

### Client Scope

1. Open `Client scopes`.
2. Confirm that `dtaas-shared` exists.

### Protocol Mappers

Open the `dtaas-shared` scope and verify these mappers exist:

1. `profile`
2. `groups`
3. `groups_owner`
4. `sub_legacy`

### User Profile Attributes

Open realm user profile settings and verify these attributes exist:

1. `profile`
2. `sub_legacy`

### Client Scope Assignment

1. Open client `dtaas-workspace`.
2. Check its default client scopes.
3. Confirm `dtaas-shared` is assigned.

### User Attribute Updates

If users exist in the realm:

1. Open a user.
2. Check the user's attributes.
3. Confirm `profile` is set to `<PROFILE_BASE_URL>/<username>`.

## Run the Unit Tests Too

The real-instance test checks live behavior. You should also run the unit tests:

```powershell
python -m unittest discover -s workspaces/test/dtaas/keycloak -p "test_*.py"
```

## Run the Integration Test (Real Keycloak)

The integration test lives in
`workspaces/test/dtaas/keycloak/test_integration_keycloak_rest.py`.

It starts a disposable Keycloak container, creates:

1. A test realm.
2. A target client.
3. A test user with an existing custom attribute.
4. A dedicated admin automation client (service account) with required roles.

Then it runs `configure_keycloak_rest.py` using `client_credentials` and verifies:

1. Required shared scope exists.
2. Required mappers exist.
3. Shared scope is assigned to the target client.
4. Existing user attributes are preserved while `profile` is updated.

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

### TLS or certificate failures

If you are testing against a self-signed TLS endpoint, use a trusted
certificate on the host or test against a local HTTP endpoint first.

### Wrong context path

Use:

1. `KEYCLOAK_CONTEXT_PATH=/` for recent `start-dev` containers.
2. `KEYCLOAK_CONTEXT_PATH=/auth` when Keycloak is exposed under `/auth`.