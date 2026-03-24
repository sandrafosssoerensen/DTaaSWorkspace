# Run Keycloak Script Tests

This guide explains how to run the integration test script in [scripts/keycloak/test/test_keycloak_scripts.ps1](scripts/keycloak/test/test_keycloak_scripts.ps1).

## What The Test Verifies

The script starts a temporary Keycloak container, creates a test realm and client, runs the Keycloak configuration scripts, and verifies:

1. Shared scope dtaas-shared exists.
2. Required mappers exist: profile, groups, groups_owner, sub_legacy.
3. Shared scope is assigned to the dtaas-workspace client default scopes.

## Prerequisites

1. Docker is installed and running.
2. Windows PowerShell 5.1 or later is available.
3. Internet access is available for first-time Docker image pulls.

## Run The Integration Test

From repository root [.](/):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\test\test_keycloak_scripts.ps1
```

Expected end summary:

- Results: N passed, 0 failed

## Important Credential Note

1. The test script no longer uses a hardcoded password.
2. If `-AdminPass` is not supplied, it generates a random ephemeral password per run.
3. Never commit real admin credentials to source control.

## Useful Test Options

Keep test container for debugging:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\test\test_keycloak_scripts.ps1 -KeepContainer
```

Use a different host port:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\test\test_keycloak_scripts.ps1 -Port 18090
```

Increase startup timeout:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\test\test_keycloak_scripts.ps1 -TimeoutSeconds 300
```

Override admin user and password explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\test\test_keycloak_scripts.ps1 -AdminUser "admin" -AdminPass "replace-this-value"
```

## Running configure_keycloak_windows.ps1 With Secure Password

The script [scripts/keycloak/configure_keycloak_windows.ps1](scripts/keycloak/configure_keycloak_windows.ps1) now expects a secure password input.

Option 1: Prompt securely

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\configure_keycloak_windows.ps1 -KeycloakBaseUrl "http://localhost" -KeycloakContextPath "/" -KeycloakRealm "dtaas" -KeycloakClientId "dtaas-workspace" -KeycloakAdmin "admin"
```

Option 2: Pass SecureString directly

```powershell
$securePass = Read-Host "Enter Keycloak admin password" -AsSecureString
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\configure_keycloak_windows.ps1 -KeycloakBaseUrl "http://localhost" -KeycloakContextPath "/" -KeycloakRealm "dtaas" -KeycloakClientId "dtaas-workspace" -KeycloakAdmin "admin" -KeycloakAdminPassword $securePass
```

Option 3: Use environment variable (for CI and non-interactive execution)

```powershell
$env:KEYCLOAK_ADMIN_PASSWORD = "replace-this-value"
powershell -ExecutionPolicy Bypass -File .\scripts\keycloak\configure_keycloak_windows.ps1 -KeycloakBaseUrl "http://localhost" -KeycloakContextPath "/" -KeycloakRealm "dtaas" -KeycloakClientId "dtaas-workspace" -KeycloakAdmin "admin"
```

## Troubleshooting

If startup fails:

1. Ensure Docker daemon is running.
2. Ensure selected host port is free.
3. Re-run with -KeepContainer and inspect logs:

```powershell
docker logs <container-name>
```
