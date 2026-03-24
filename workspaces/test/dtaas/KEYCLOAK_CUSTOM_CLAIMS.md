# DTaaS Keycloak Custom Claims Contract

This is document containing how the userinfo payload is expected by DTaaS.

## Target Userinfo Payload

```json
{
  "sub": "2f9d9d8b-...",
  "sub_legacy": "xxx",
  "name": "alice",
  "nickname": "alice",
  "preferred_username": "alice",
  "profile": "https://foo.com/gitlab/alice",
  "picture": "https://secure.gravatar.com/avatar/xxx?s=80&d=identicon",
  "groups": ["dtaas"],
  "https://gitlab.org/claims/groups/owner": ["dtaas"]
}
```

Notes:
- `sub` remains the standard Keycloak subject (stable identifier), not a custom mapper.
- `name`, `nickname`, `preferred_username`, and `picture` come from standard OIDC scopes.
- `sub_legacy` is a custom user attribute mapper.
- `profile` is a custom user attribute mapper.
- `groups` and `https://gitlab.org/claims/groups/owner` are group membership mappers.

## Mapper Configuration (Shared Client Scope)

Required custom mappers in the shared scope:
- `profile`:
  `oidc-usermodel-attribute-mapper`, `user.attribute=profile`, `claim.name=profile`, userinfo only.
- `sub_legacy`:
  `oidc-usermodel-attribute-mapper`, `user.attribute=sub_legacy`, `claim.name=sub_legacy`, userinfo only.
- `groups`:
  `oidc-group-membership-mapper`, `claim.name=groups`, userinfo only, multivalued.
- `groups_owner`:
  `oidc-group-membership-mapper`, `claim.name=https://gitlab.org/claims/groups/owner`, userinfo only, multivalued.

Not part of this contract:
- `department`
- `cost_center`

## Data Requirements

For each user:
- Set `attributes.profile` to `https://foo.com/gitlab/<username>`.
- Set `attributes.sub_legacy` to legacy subject value.
- Ensure user belongs to at least one group (for both group claims).

## Automation Commands

Primary (kcadm):

```bash
cd workspaces/test/dtaas
chmod +x config/configure_keycloak_mappers.sh

KEYCLOAK_BASE_URL=https://foo.com \
KEYCLOAK_CONTEXT_PATH=/auth \
KEYCLOAK_REALM=dtaas \
KEYCLOAK_CLIENT_ID=dtaas-client \
KEYCLOAK_ADMIN=admin \
KEYCLOAK_ADMIN_PASSWORD=admin \
PROFILE_BASE_URL=https://foo.com/gitlab \
./config/configure_keycloak_mappers.sh
```

Fallback (REST, bash):

```bash
cd workspaces/test/dtaas
chmod +x config/configure_keycloak_rest.sh
./config/configure_keycloak_rest.sh
```

Fallback (REST, Windows):

```powershell
cd workspaces/test/dtaas
powershell -ExecutionPolicy Bypass -File .\config\configure_keycloak_windows.ps1
```

## Approaches

This repository supports three equivalent automation approaches for mapper reconciliation:
- `config/configure_keycloak_mappers.sh` (kcadm-based shell script)
- `config/configure_keycloak_rest.sh` (REST-based shell script)
- `config/configure_keycloak_windows.ps1` (REST-based PowerShell script)

Selection guidance:
- Run one approach per reconciliation run (do not chain multiple script variants in one run).
- Re-run after claims-contract changes.
- Validate userinfo output against this document after each run.

## Step-by-Step by Approach

Use the approach that matches your terminal and tooling. Each flow is complete by itself.

### Approach A: Windows PowerShell (REST)

1. Open PowerShell and go to repository folder:

```powershell
cd "c:\Users\sandr\Desktop\R&D Projekt\DTaaSWorkspace\workspaces\test\dtaas"
```

2. Set environment values:

```powershell
$env:KEYCLOAK_BASE_URL = "https://shared.dtaas-digitaltwin.com"
$env:KEYCLOAK_CONTEXT_PATH = "/auth"
$env:KEYCLOAK_REALM = "dtaas"
$env:KEYCLOAK_CLIENT_ID = "dtaas-client"
$env:KEYCLOAK_SHARED_SCOPE_NAME = "dtaas-shared"
$env:KEYCLOAK_ADMIN = "admin"
$env:KEYCLOAK_ADMIN_PASSWORD = "admin"
$env:PROFILE_BASE_URL = "https://shared.dtaas-digitaltwin.com/auth"
```

3. Run script:

```powershell
powershell -ExecutionPolicy Bypass -File .\config\configure_keycloak_windows.ps1
```

### Approach B: Bash (REST)

1. Open Git Bash or WSL and go to repository folder:

```bash
cd /c/Users/sandr/Desktop/R\&D\ Projekt/DTaaSWorkspace/workspaces/test/dtaas
```

2. Set environment values:

```bash
export KEYCLOAK_BASE_URL=https://foo.com
export KEYCLOAK_CONTEXT_PATH=/auth
export KEYCLOAK_REALM=dtaas
export KEYCLOAK_CLIENT_ID=dtaas-client
export KEYCLOAK_SHARED_SCOPE_NAME=dtaas-shared
export KEYCLOAK_ADMIN=admin
export KEYCLOAK_ADMIN_PASSWORD=YOUR_ADMIN_PASSWORD
export PROFILE_BASE_URL=https://foo.com/gitlab
```

3. Run script:

```bash
chmod +x config/configure_keycloak_rest.sh
./config/configure_keycloak_rest.sh
```

### Approach C: Bash (kcadm)

1. Open Git Bash or WSL and go to repository folder:

```bash
cd /c/Users/sandr/Desktop/R\&D\ Projekt/DTaaSWorkspace/workspaces/test/dtaas
```

2. Ensure dependencies exist: `kcadm.sh`, `jq`.

3. Set environment values and run script:

```bash
chmod +x config/configure_keycloak_mappers.sh

KEYCLOAK_BASE_URL=https://foo.com \
KEYCLOAK_CONTEXT_PATH=/auth \
KEYCLOAK_REALM=dtaas \
KEYCLOAK_CLIENT_ID=dtaas-client \
KEYCLOAK_ADMIN=admin \
KEYCLOAK_ADMIN_PASSWORD=YOUR_ADMIN_PASSWORD \
PROFILE_BASE_URL=https://foo.com/gitlab \
./config/configure_keycloak_mappers.sh
```

### Common Verification (all approaches)

After any approach succeeds, verify userinfo output:

```bash
curl -H "Authorization: Bearer <access_token>" \
  https://foo.com/auth/realms/dtaas/protocol/openid-connect/userinfo
```

Confirm the response matches the Target Userinfo Payload in this document.

## Verification

1. Obtain an access token for a test user.
2. Call userinfo endpoint:

```bash
curl -H "Authorization: Bearer <access_token>" \
  https://foo.com/auth/realms/dtaas/protocol/openid-connect/userinfo
```

3. Confirm userinfo includes exactly the target claims above for DTaaS.

## How Scripts Are Configured

Use these snippets as the expected configuration behavior.

### kcadm Script Behavior (`configure_keycloak_mappers.sh`)

```bash
# groups mapper: userinfo only
ensure_scope_mapper "groups" "oidc-group-membership-mapper" \
  "-s config.full.path=false -s config.id.token.claim=false -s config.access.token.claim=false -s config.claim.name=groups -s config.userinfo.token.claim=true -s config.multivalued=true"

# namespaced owner groups mapper: userinfo only
ensure_scope_mapper "groups_owner" "oidc-group-membership-mapper" \
  "-s config.full.path=false -s config.id.token.claim=false -s config.access.token.claim=false -s config.claim.name=https://gitlab.org/claims/groups/owner -s config.userinfo.token.claim=true -s config.multivalued=true"

# legacy subject mapper: userinfo only
ensure_scope_mapper "sub_legacy" "oidc-usermodel-attribute-mapper" \
  "-s config.user.attribute=sub_legacy -s config.claim.name=sub_legacy -s config.jsonType.label=String -s config.id.token.claim=false -s config.access.token.claim=false -s config.userinfo.token.claim=true"
```

### Windows Script Behavior (`configure_keycloak_windows.ps1`)

```powershell
Ensure-Mapper "groups" "oidc-group-membership-mapper" @{
    "full.path" = "false"
    "id.token.claim" = "false"
    "access.token.claim" = "false"
    "claim.name" = "groups"
    "userinfo.token.claim" = "true"
    "multivalued" = "true"
}

Ensure-Mapper "groups_owner" "oidc-group-membership-mapper" @{
    "full.path" = "false"
    "id.token.claim" = "false"
    "access.token.claim" = "false"
    "claim.name" = "https://gitlab.org/claims/groups/owner"
    "userinfo.token.claim" = "true"
    "multivalued" = "true"
}

Ensure-Mapper "sub_legacy" "oidc-usermodel-attribute-mapper" @{
    "user.attribute" = "sub_legacy"
    "claim.name" = "sub_legacy"
    "jsonType.label" = "String"
    "id.token.claim" = "false"
    "access.token.claim" = "false"
    "userinfo.token.claim" = "true"
}
```
