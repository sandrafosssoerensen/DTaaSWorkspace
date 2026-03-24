# Keycloak Configuration Scripts

These scripts configure the DTaaS Keycloak realm with the required client scopes and
protocol mappers for the `dtaas-workspace` client. All three scripts produce the same
result.

| Script | Requires | Platform |
|--------|----------|----------|
| `configure_keycloak_mappers.sh` | `kcadm`, `jq` | Linux / macOS |
| `configure_keycloak_rest.sh` | `curl`, `jq` | Linux / macOS / WSL |
| `configure_keycloak_windows.ps1` | PowerShell 7+ | Windows |

## What They Configure

All scripts perform the same operations against a running Keycloak instance:

1. Create (or reuse) a shared client scope named `dtaas-shared`.
2. Ensure the following protocol mappers exist in that scope:
   - `profile` — maps the `profile` user attribute to the userinfo token.
   - `groups` — maps group memberships to the `groups` claim in the access token.
   - `groups_owner` — maps group memberships to the
     `https://gitlab.org/claims/groups/owner` claim in the access token.
   - `sub_legacy` — maps the `sub_legacy` user attribute to the userinfo token.
3. Ensure the `profile` and `sub_legacy` user profile attributes exist in the realm.
4. Assign the `dtaas-shared` scope to the `dtaas-workspace` client's default scopes.
5. Optionally update every user's `profile` attribute to `<PROFILE_BASE_URL>/<username>`.

---

## configure_keycloak_mappers.sh

Uses the official Keycloak **`kcadm`** admin CLI. Supports two authentication modes:
service-account (client credentials) or admin username/password.

### Prerequisites

- `kcadm.sh` on your `PATH` (ships with Keycloak under `bin/`)
- `jq`

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_BASE_URL` | `http://localhost` | Keycloak base URL |
| `KEYCLOAK_CONTEXT_PATH` | `/auth` | Context path (use `/` for Keycloak 17+) |
| `KEYCLOAK_REALM` | `dtaas` | Target realm |
| `KEYCLOAK_CLIENT_ID` | `dtaas-workspace` | Client to configure |
| `KEYCLOAK_SHARED_SCOPE_NAME` | `dtaas-shared` | Shared scope name |
| `KEYCLOAK_ADMIN_CLIENT_ID` | _(empty)_ | Service-account client ID (preferred) |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | _(empty)_ | Service-account client secret |
| `KEYCLOAK_ADMIN` | `admin` | Fallback admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Fallback admin password |
| `PROFILE_BASE_URL` | `https://localhost/gitlab` | Base URL for user profile attributes |

### Usage

```sh
# Admin username/password (default)
KEYCLOAK_BASE_URL=https://keycloak.example.com \
KEYCLOAK_ADMIN=admin \
KEYCLOAK_ADMIN_PASSWORD=admin \
./configure_keycloak_mappers.sh

# Service account (preferred for automation)
KEYCLOAK_BASE_URL=https://keycloak.example.com \
KEYCLOAK_ADMIN_CLIENT_ID=my-admin-client \
KEYCLOAK_ADMIN_CLIENT_SECRET=my-secret \
./configure_keycloak_mappers.sh
```

---

## configure_keycloak_rest.sh

Uses the Keycloak **Admin REST API** directly via `curl` and `jq`. No `kcadm`
installation required. Well-suited for CI environments and containers.

### Prerequisites

- `curl`
- `jq`

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_BASE_URL` | `http://localhost` | Keycloak base URL |
| `KEYCLOAK_CONTEXT_PATH` | `/auth` | Context path (use `/` for Keycloak 17+) |
| `KEYCLOAK_REALM` | `dtaas` | Target realm |
| `KEYCLOAK_CLIENT_ID` | `dtaas-workspace` | Client to configure |
| `KEYCLOAK_SHARED_SCOPE_NAME` | `dtaas-shared` | Shared scope name |
| `KEYCLOAK_ADMIN` | `admin` | Admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Admin password |
| `PROFILE_BASE_URL` | `https://localhost/gitlab` | Base URL for user profile attributes |

### Usage

```sh
KEYCLOAK_BASE_URL=https://keycloak.example.com \
KEYCLOAK_ADMIN=admin \
KEYCLOAK_ADMIN_PASSWORD=admin \
./configure_keycloak_rest.sh
```

---

## configure_keycloak_windows.ps1

PowerShell implementation that uses `Invoke-RestMethod` against the Keycloak Admin REST
API. No external tools (`jq`, `curl`, `kcadm`) required.

### Prerequisites

- PowerShell 7+ (`pwsh`)

### Parameters

Parameters can be passed directly or via environment variables — environment variables
take precedence when set.

| Parameter / Env Variable | Default | Description |
|--------------------------|---------|-------------|
| `-KeycloakBaseUrl` / `KEYCLOAK_BASE_URL` | `http://localhost` | Keycloak base URL |
| `-KeycloakContextPath` / `KEYCLOAK_CONTEXT_PATH` | `/auth` | Context path |
| `-KeycloakRealm` / `KEYCLOAK_REALM` | `dtaas` | Target realm |
| `-KeycloakClientId` / `KEYCLOAK_CLIENT_ID` | `dtaas-workspace` | Client to configure |
| `-KeycloakSharedScopeName` / `KEYCLOAK_SHARED_SCOPE_NAME` | `dtaas-shared` | Shared scope name |
| `-KeycloakAdmin` / `KEYCLOAK_ADMIN` | `admin` | Admin username |
| `-KeycloakAdminPassword` / `KEYCLOAK_ADMIN_PASSWORD` | _(none)_ | Admin password (secure input; prompted if omitted in interactive mode) |
| `-ProfileBaseUrl` / `PROFILE_BASE_URL` | `https://localhost/gitlab` | Base URL for user profile attributes |

### Usage

```powershell
# Using parameters
$securePass = Read-Host "Enter Keycloak admin password" -AsSecureString
.\configure_keycloak_windows.ps1 `
  -KeycloakBaseUrl "https://keycloak.example.com" `
  -KeycloakAdmin "admin" `
  -KeycloakAdminPassword $securePass

# Using environment variables
$env:KEYCLOAK_BASE_URL = "https://keycloak.example.com"
$env:KEYCLOAK_ADMIN_PASSWORD = "secret"
.\configure_keycloak_windows.ps1
```

---

## Choosing the Right Script

- **Linux/macOS with kcadm available** — use `configure_keycloak_mappers.sh`. It
  supports service-account authentication which is safer for automation pipelines.
- **Linux/macOS/WSL without kcadm** — use `configure_keycloak_rest.sh`. Only `curl`
  and `jq` are needed.
- **Windows** — use `configure_keycloak_windows.ps1`. No additional tools required.
