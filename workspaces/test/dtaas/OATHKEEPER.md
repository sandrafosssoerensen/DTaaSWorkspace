# Oathkeeper and OPA Authorization in DTaaS

This document describes how Ory Oathkeeper and Open Policy Agent (OPA) are used
in the DTaaS workspace to enforce JWT authentication and per-user path
authorization on workspace routes.

## Overview

Oathkeeper acts as the **Policy Enforcement Point (PEP)** between Traefik and
workspace services. For every request to a workspace route, Traefik's
`ForwardAuth` middleware calls Oathkeeper's decision API before forwarding the
request. Oathkeeper validates the JWT and delegates authorization to OPA.

```text
Browser
  |
  v
Traefik  ──ForwardAuth──>  Oathkeeper (JWT validation)
                                  |
                                  v
                             OPA (path policy)
                                  |
                                  v (allow)
                           Workspace service
```

## Components

| Component | Image | Port | Role |
|---|---|---|---|
| Oathkeeper | `oryd/oathkeeper:v0.40.8` | 4455 (proxy), 4456 (decision API) | JWT verification, auth orchestration |
| OPA | `openpolicyagent/opa:0.70.0` | 8181 | Per-user path authorization |

## Configuration Files

All files live in `workspaces/test/dtaas/oathkeeper/`:

| File | Purpose |
|---|---|
| `oathkeeper.yml` | Main Oathkeeper config: ports, authenticators, authorizers, mutators |
| `access-rules.yml` | URL matching rules mapping routes to authenticators and authorizers |
| `policy.rego` | Rego policy evaluated by OPA for authorization decisions |

## Environment Variables

Set in the `oathkeeper` service in the compose file (derived from `.env`):

| Variable | Description | Example |
|---|---|---|
| `KEYCLOAK_JWKS_URL` | Internal container URL to Keycloak's JWKS endpoint | `http://keycloak:8080/auth/realms/dtaas/protocol/openid-connect/certs` |
| `KEYCLOAK_ISSUER_URL` | Public Keycloak issuer URL — must match the `iss` claim in JWTs | `http://localhost/auth/realms/dtaas` |
| `KEYCLOAK_TARGET_AUDIENCE` | Required `aud` claim in access tokens | `dtaas-workspace` |

> **Note:** Oathkeeper v0.40.8 does not expand `${VAR}` placeholders in its
> YAML config at runtime. The compose files use a `sh -c sed` wrapper to
> substitute these variables before starting the server.

## Decision Flow

1. Browser sends `Authorization: Bearer <access_token>` to a workspace route.
2. Traefik's `oathkeeper-auth` ForwardAuth middleware forwards the request
   to `http://oathkeeper:4456/decisions`.
3. Oathkeeper matches the URL against `access-rules.yml`.
4. The `jwt` authenticator fetches Keycloak's public keys from `KEYCLOAK_JWKS_URL`
   and verifies the token signature, issuer, audience, and expiry.
5. If the token is valid, Oathkeeper calls OPA at
   `http://opa:8181/v1/data/workspace/authz/allow` with the JWT claims and
   request context as input.
6. OPA evaluates `policy.rego` and returns `true` (allow) or `false` (deny).
7. On allow, Oathkeeper returns HTTP 200 and Traefik forwards the request to
   the workspace. The `X-User-Name` and `X-User-Subject` headers are injected.
8. On deny, Traefik returns HTTP 403 to the browser.

## OPA Authorization Policy

The policy in `policy.rego` enforces two conditions:

1. **Group membership**: the `groups` JWT claim must contain `"dtaas"`.
2. **Path isolation**: the `preferred_username` JWT claim must match the first
   path segment of the URL.

```
/user1/tools/vscode  →  preferred_username must equal "user1"
/user2/lab/          →  preferred_username must equal "user2"
```

Both conditions must be true for a request to be allowed. This means:

- A legitimate user cannot access another user's workspace.
- A user not in the `dtaas` group is always denied, even for their own path.

The `groups` and `preferred_username` claims are injected by Keycloak via
protocol mappers. See [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) for mapper
configuration.

### Testing the Policy Manually

With OPA running, test allow/deny decisions directly:

```bash
# Allow: user1 accessing /user1/tools/vscode
curl -s http://localhost:8181/v1/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"input": {"extra": {"preferred_username": "user1", "groups": ["dtaas"]},
        "url": {"path": "/user1/tools/vscode"}}}'
# Expected: {"result": true}

# Deny: user1 accessing /user2/tools/vscode
curl -s http://localhost:8181/v1/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"input": {"extra": {"preferred_username": "user1", "groups": ["dtaas"]},
        "url": {"path": "/user2/tools/vscode"}}}'
# Expected: {"result": false}

# Deny: user not in dtaas group
curl -s http://localhost:8181/v1/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"input": {"extra": {"preferred_username": "user1", "groups": ["other"]},
        "url": {"path": "/user1/tools/vscode"}}}'
# Expected: {"result": false}
```

## Traefik Middleware Configuration

The ForwardAuth middleware is defined on the `oathkeeper` service labels in
the compose file:

```yaml
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.address=http://oathkeeper:4456/decisions"
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.authResponseHeaders=X-User-Name,X-User-Subject"
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.authRequestHeaders=Authorization"
```

The middleware is applied on workspace service routes, not on the client or
Keycloak routes. The DTaaS web client handles its own PKCE login flow directly
with Keycloak; Oathkeeper only protects the `/user1/...` and `/user2/...` paths.

## Troubleshooting

### Oathkeeper exits immediately on startup

Check logs with:

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
  --env-file workspaces/test/dtaas/config/.env logs oathkeeper
```

Common causes:

| Error | Fix |
|---|---|
| `"${KEYCLOAK_JWKS_URL}" is not valid "uri"` | Env var not substituted — check the `sed` wrapper in the compose entrypoint |
| `missing properties: "remote", "payload"` | The `remote_json` global config in `oathkeeper.yml` is missing `remote` and `payload` fields |
| `access-rules.yml` not found | Check the volume mount path in the compose file |

### Requests return 403 unexpectedly

1. Confirm the JWT includes a `groups` claim containing `"dtaas"` — check via
   [jwt.io](https://jwt.io).
2. Confirm the `preferred_username` claim matches the first path segment of
   the URL exactly (case-sensitive).
3. Check Oathkeeper logs for the specific rejection reason:
   ```bash
   docker compose logs oathkeeper --tail 50
   ```
4. Test the OPA policy directly with the `curl` commands above.

### Keycloak claims are missing from the token

The `groups` and `preferred_username` claims require protocol mappers in
Keycloak. See [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) for the required mapper
configuration.

## Related Documents

- [TRAEFIK_SECURE.md](TRAEFIK_SECURE.md) — Deployment guide for the full stack
- [TRAEFIK_TLS.md](TRAEFIK_TLS.md) — TLS/HTTPS variant
- [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) — Keycloak realm and client setup
- [OIDC_FLOWS_WITH_OATHKEEPER.md](OIDC_FLOWS_WITH_OATHKEEPER.md) — Architecture and flow diagrams
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variable reference
