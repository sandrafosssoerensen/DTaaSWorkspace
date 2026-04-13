# Oathkeeper RBAC Demo

> This demo describes the coupled Oathkeeper+OPA mode.
> The current default project setup is decoupled mode (Oathkeeper JWT-only at
> gateway, OPA reserved for workspace-side integration). See `OATHKEEPER.md` for
> the active architecture.

Demonstrates that Oathkeeper + OPA enforce JWT authentication and role-based
access control (RBAC) using Keycloak realm roles. Three roles are defined:

| Role | Access |
|---|---|
| `dtaas-admin` | Any workspace path, any HTTP method (cross-user) |
| `dtaas-user` | Own workspace path only, any HTTP method |
| `dtaas-viewer` | Own workspace path only, GET/HEAD/OPTIONS only |

Users provisioned automatically by `reset-dtaas.ps1 -RunConfigurator`:

| User | Password | Role | Workspace |
|---|---|---|---|
| `user1` | `user1` | `dtaas-user` | `/user1/` |
| `user2` | `user2` | `dtaas-user` | `/user2/` |
| `sandra` | `sandra` | `dtaas-admin` | `/sandra/` |

## Key Distinction

| Response | Meaning |
|---|---|
| 401 | Authentication failed — no valid token |
| 403 | Authenticated but RBAC denied — OPA said no |

## 1. Start the Stack

From the repo root, run the reset script — this tears down any existing stack,
starts fresh, and runs the Keycloak configurator (realm, client, roles, users):

```powershell
.\scripts\reset-dtaas.ps1 -RunConfigurator
```

Wait until all services are healthy:

```powershell
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml `
  --env-file workspaces/test/dtaas/config/.env ps
```

No manual Keycloak setup is needed — users and roles are created automatically.

## 2. Test OPA Policy Directly (no token needed)

OPA's port 8181 is not exposed to the host — it is internal to the Docker
network. Use `docker compose exec` to reach it from inside.

The `roles` array in the input mirrors what Keycloak emits in the JWT.
The v1 API endpoint always returns HTTP 200; the allow/deny result is in the
body. Because the policy has **no** `default allow := false`, a denied request
returns an **undefined** result — OPA emits `{}` with no `result` key. An
explicit `{"result": false}` would only appear with a default rule, which we
deliberately omit so that OPA's v0 API returns HTTP 404 for deny (the mechanism
the opa-proxy adapter relies on).

| OPA v1 output | Meaning |
|---|---|
| `{"result":true}` | Allow |
| `{}` | Deny — rule did not match (undefined) |

### dtaas-user scenarios

```bash
# Allow: dtaas-user accessing own workspace
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec opa \
  wget -qO- --post-data \
    '{"input": {"extra": {"preferred_username": "user1", "roles": ["dtaas-user"]}, "url": {"path": "/user1/tools/vscode"}, "method": "GET"}}' \
  --header 'Content-Type: application/json' \
  http://localhost:8181/v1/data/workspace/authz/allow
# Expected: {"result":true}

# Deny: dtaas-user accessing another user's workspace
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec opa \
  wget -qO- --post-data \
    '{"input": {"extra": {"preferred_username": "user1", "roles": ["dtaas-user"]}, "url": {"path": "/user2/tools/vscode"}, "method": "GET"}}' \
  --header 'Content-Type: application/json' \
  http://localhost:8181/v1/data/workspace/authz/allow
# Expected: {} (undefined — no rule matched → deny)
```

### dtaas-viewer scenarios

```bash
# Allow: dtaas-viewer read-only on own workspace
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec opa \
  wget -qO- --post-data \
    '{"input": {"extra": {"preferred_username": "user1", "roles": ["dtaas-viewer"]}, "url": {"path": "/user1/lab"}, "method": "GET"}}' \
  --header 'Content-Type: application/json' \
  http://localhost:8181/v1/data/workspace/authz/allow
# Expected: {"result":true}

# Deny: dtaas-viewer attempting a write on own workspace
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec opa \
  wget -qO- --post-data \
    '{"input": {"extra": {"preferred_username": "user1", "roles": ["dtaas-viewer"]}, "url": {"path": "/user1/lab"}, "method": "POST"}}' \
  --header 'Content-Type: application/json' \
  http://localhost:8181/v1/data/workspace/authz/allow
# Expected: {} (undefined — viewer + write method → no rule matched → deny)
```

### dtaas-admin scenarios

```bash
# Allow: dtaas-admin accessing another user's workspace
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec opa \
  wget -qO- --post-data \
    '{"input": {"extra": {"preferred_username": "sandra", "roles": ["dtaas-admin"]}, "url": {"path": "/user1/tools/vscode"}, "method": "POST"}}' \
  --header 'Content-Type: application/json' \
  http://localhost:8181/v1/data/workspace/authz/allow
# Expected: {"result":true}

# Allow: dtaas-admin accessing own workspace
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec opa \
  wget -qO- --post-data \
    '{"input": {"extra": {"preferred_username": "sandra", "roles": ["dtaas-admin"]}, "url": {"path": "/sandra/lab"}, "method": "GET"}}' \
  --header 'Content-Type: application/json' \
  http://localhost:8181/v1/data/workspace/authz/allow
# Expected: {"result":true}
```

### No role assigned — deny

```bash
# Deny: authenticated user with no DTaaS role
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec opa \
  wget -qO- --post-data \
    '{"input": {"extra": {"preferred_username": "user1", "roles": []}, "url": {"path": "/user1/lab"}, "method": "GET"}}' \
  --header 'Content-Type: application/json' \
  http://localhost:8181/v1/data/workspace/authz/allow
# Expected: {} (undefined — no matching role rule → deny)
```

This proves the authorization policy is correct independently of the rest of
the stack.

## 2b. Test opa-proxy 404→403 Conversion

`opa-proxy` (nginx) sits between Oathkeeper and OPA. It converts OPA's HTTP 404
deny response to HTTP 403 so Oathkeeper returns a proper 403 Forbidden (not 500).

Verify the conversion from a container on the `dtaas-users` network:

```bash
# Allow: opa-proxy passes OPA's 200 through unchanged
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec oathkeeper \
  wget -S -qO /dev/null --post-data \
    '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-user"]},"url":{"path":"/user1/lab"},"method":"GET"}' \
  --header 'Content-Type: application/json' \
  http://opa-proxy:8080/v0/data/workspace/authz/allow 2>&1 | head -1
# Expected: HTTP/1.1 200 OK

# Deny: opa-proxy converts OPA's 404 → 403
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml exec oathkeeper \
  wget -S -qO /dev/null --post-data \
    '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-user"]},"url":{"path":"/user2/lab"},"method":"GET"}' \
  --header 'Content-Type: application/json' \
  http://opa-proxy:8080/v0/data/workspace/authz/allow 2>&1 | head -1
# Expected: HTTP/1.1 403 Forbidden
```

Note: the v0 API takes raw input — no `{"input": ...}` wrapper.

## 3. Unauthenticated Requests Are Blocked (401)

```bash
# No token
curl -vk https://shared.dtaas-digitaltwin.com/user1/

# Garbage token
curl -vk -H "Authorization: Bearer notarealtoken" \
  https://shared.dtaas-digitaltwin.com/user1/
```

Both return `401 Unauthorized` from Oathkeeper before the request ever
reaches the workspace service.

## 4. Get a Real Token and Test RBAC End-to-End

> **Note:** The password grant below requires **Direct Access Grants** to be
> enabled on the `dtaas-client` in the Keycloak admin console
> (`Clients → dtaas-client → Advanced → Authentication flow → Direct access grants`).
> If not enabled, use the browser flow in step 6 instead.

### dtaas-user: own path allowed, other path denied

```bash
TOKEN=$(curl -sk -X POST \
  "https://shared.dtaas-digitaltwin.com/auth/realms/dtaas/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=dtaas-workspace&username=user1&password=user1" \
  | jq -r '.access_token')

# Verify roles in token
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq '{roles, preferred_username}'
# Expected: {"roles": ["dtaas-user"], "preferred_username": "user1"}

# Allow: user1's token on own workspace — should return 200
curl -sk -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  https://shared.dtaas-digitaltwin.com/user1/

# Deny: user1's token on user2's workspace — should return 403
curl -sk -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  https://shared.dtaas-digitaltwin.com/user2/
```

### dtaas-admin: cross-user access allowed

```bash
ADMIN_TOKEN=$(curl -sk -X POST \
  "https://shared.dtaas-digitaltwin.com/auth/realms/dtaas/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=dtaas-workspace&username=sandra&password=sandra" \
  | jq -r '.access_token')

# Verify admin role in token
echo $ADMIN_TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq '{roles, preferred_username}'
# Expected: {"roles": ["dtaas-admin"], "preferred_username": "sandra"}

# Allow: sandra accessing her own workspace — should return 200
curl -sk -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://shared.dtaas-digitaltwin.com/sandra/

# Allow: sandra accessing user1's workspace — should return 200
curl -sk -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://shared.dtaas-digitaltwin.com/user1/

# Allow: sandra accessing user2's workspace — should return 200
curl -sk -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://shared.dtaas-digitaltwin.com/user2/
```

## 5. Verify Injected Headers

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env \
  logs oathkeeper --tail 50
```

On an allowed request Oathkeeper's `header` mutator injects three headers
forwarded to the upstream workspace service:

| Header | Value |
|---|---|
| `X-User-Name` | `preferred_username` claim |
| `X-User-Subject` | `sub` claim (Keycloak user UUID) |
| `X-User-Groups` | `groups` claim (JSON array, for informational use) |

## 6. Browser Demo

The DTaaS client handles login via OIDC PKCE directly with Keycloak.
Oathkeeper reads the resulting `dtaas_access_token` cookie on workspace
requests (configured in `oathkeeper.yml` under `token_from.cookie`).

1. Open `https://shared.dtaas-digitaltwin.com` — the DTaaS client loads.
2. Log in as `user1` / `user1` (role: `dtaas-user`).
3. Navigate to `https://shared.dtaas-digitaltwin.com/user1/` — **loads (200)**.
4. Manually navigate to `https://shared.dtaas-digitaltwin.com/user2/` — **blocked (403)**.
5. Log out, log in as `sandra` / `sandra` (role: `dtaas-admin`).
6. Navigate to `https://shared.dtaas-digitaltwin.com/sandra/` — **loads (200)**.
7. Navigate to `https://shared.dtaas-digitaltwin.com/user1/` — **loads (200)** (cross-user admin access).
8. Navigate to `https://shared.dtaas-digitaltwin.com/user2/` — **loads (200)**.

## Summary

| Scenario | User | Role | Expected OPA output | What it proves |
|---|---|---|---|---|
| OPA v1 exec — own path, GET | `user1` | `dtaas-user` | `{"result":true}` | User policy correct |
| OPA v1 exec — other path, GET | `user1` | `dtaas-user` | `{}` (undefined = deny) | Cross-user isolation enforced |
| OPA v1 exec — own path, GET | `user1` | `dtaas-viewer` | `{"result":true}` | Viewer read access works |
| OPA v1 exec — own path, POST | `user1` | `dtaas-viewer` | `{}` (undefined = deny) | Viewer write blocked |
| OPA v1 exec — any path | `sandra` | `dtaas-admin` | `{"result":true}` | Admin cross-user access works |
| OPA v1 exec — no roles | `user1` | (none) | `{}` (undefined = deny) | Unassigned users denied |
| opa-proxy — allow path | `user1` | `dtaas-user` | HTTP 200 | v0 allow passes through |
| opa-proxy — deny path | `user1` | `dtaas-user` | HTTP 403 | OPA 404 converted to 403 |
| No token | — | — | 401 | Unauthenticated access blocked |
| Garbage token | — | — | 401 | Invalid tokens rejected |
| `user1` token on own path | `user1` | `dtaas-user` | HTTP 200 | Legitimate access works end-to-end |
| `user1` token on `user2` path | `user1` | `dtaas-user` | HTTP 403 | Valid token denied by RBAC |
| `sandra` token on `user1` path | `sandra` | `dtaas-admin` | HTTP 200 | Admin cross-user access end-to-end |
