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
                           opa-proxy (nginx, 404→403 adapter)
                                  |
                                  v
                             OPA (path policy)
                                  |
                                  v (allow → 200, deny → 404→403)
                           Workspace service
```

## Components

| Component | Image | Port | Role |
|---|---|---|---|
| Oathkeeper | `oryd/oathkeeper:v26.2.0` | 4455 (proxy), 4456 (decision API) | JWT verification, auth orchestration |
| opa-proxy | `nginx:alpine` | 8080 | Converts OPA's 404 deny response to 403 |
| OPA | `openpolicyagent/opa:1.15.2` | 8181 | Per-user RBAC path authorization |

## Configuration Files

All files live in `workspaces/test/dtaas/oathkeeper/`:

| File | Purpose |
|---|---|
| `oathkeeper.yml` | Main Oathkeeper config: ports, authenticators, authorizers, mutators |
| `access-rules.yml` | URL matching rules mapping routes to authenticators and authorizers |
| `policy.rego` | Rego RBAC policy evaluated by OPA for authorization decisions |
| `opa-proxy.nginx.conf` | nginx config for the opa-proxy 404→403 adapter |

## Environment Variables

Set in the `oathkeeper` service in the compose file (derived from `.env`):

| Variable | Description | Example |
|---|---|---|
| `KEYCLOAK_JWKS_URL` | Internal container URL to Keycloak's JWKS endpoint | `http://keycloak:8080/auth/realms/dtaas/protocol/openid-connect/certs` |
| `KEYCLOAK_ISSUER_URL` | Public Keycloak issuer URL — must match the `iss` claim in JWTs | `http://localhost/auth/realms/dtaas` |
| `KEYCLOAK_TARGET_AUDIENCE` | Required `aud` claim in access tokens | `dtaas-workspace` |

> **Note:** Oathkeeper does not expand `${VAR}` placeholders in its YAML config
> at runtime. The compose files use a `sh -c sed` wrapper to substitute these
> variables before starting the server.

## Decision Flow

1. Browser sends a request (with `dtaas_access_token` cookie) to a workspace route.
2. Traefik's `oathkeeper-auth` ForwardAuth middleware forwards the request
   to `http://oathkeeper:4456/decisions`.
3. Oathkeeper matches the URL against `access-rules.yml`.
4. The `jwt` authenticator reads the JWT from the `dtaas_access_token` cookie,
   fetches Keycloak's public keys from `KEYCLOAK_JWKS_URL`, and verifies the
   token signature, issuer, audience, and expiry.
5. If the token is valid, Oathkeeper calls `http://opa-proxy:8080/v0/data/workspace/authz/allow`
   with the JWT claims and request context as raw JSON input.
6. `opa-proxy` (nginx) forwards the request to OPA (`http://opa:8181/...`).
7. OPA evaluates `policy.rego` and returns HTTP 200 (allow) or HTTP 404 (deny).
8. `opa-proxy` passes through 200 unchanged and converts 404 → 403.
9. Oathkeeper sees 200 (allow) or 403 (deny). On 403, it returns
   `ErrForbidden` and the client gets HTTP 403. On 200, Oathkeeper injects
   `X-User-Name`, `X-User-Subject`, and `X-User-Groups` headers and returns 200
   so Traefik forwards the request to the workspace.

> **Why the opa-proxy adapter?**
> Oathkeeper's `remote_json` authorizer returns `ErrForbidden` (403) only
> when the remote endpoint responds with HTTP 403. For any other non-200 status
> (including OPA's 404), it raises a plain internal error and returns HTTP 500 to
> the client. The `opa-proxy` nginx adapter sits between Oathkeeper and OPA and
> converts OPA's 404 deny response to 403, so Oathkeeper follows the correct
> ErrForbidden path.
>
> OPA's `/v0/data/` endpoint is used (not `/v1/data/`) because it returns HTTP 200
> for allow and HTTP 404 for deny (undefined), giving a meaningful status code.
> The `/v1/data/` endpoint always returns HTTP 200 with the result in the body
> (`{"result": true/false}`), but `remote_json` does not read the response body —
> it only checks the status code — so v1 would grant every request.

## OPA Authorization Policy (RBAC)

The policy in `policy.rego` enforces role-based access control using Keycloak
realm roles emitted as a flat `roles` array in the JWT access token:

| Role | Access |
|---|---|
| `dtaas-admin` | Full access to any workspace path (cross-user) |
| `dtaas-user` | Full access to own workspace only (all HTTP methods) |
| `dtaas-viewer` | Read-only access to own workspace (GET/HEAD/OPTIONS only) |

Path ownership is determined by matching the JWT `preferred_username` claim
against the first URL path segment:

```
/user1/tools/vscode  →  preferred_username must equal "user1"
/user2/lab/          →  preferred_username must equal "user2"
```

The `preferred_username` and `roles` claims are emitted by Keycloak via protocol
mappers configured by `configure_keycloak_rest.py`.

### Testing the Policy Manually

OPA's `/v0/data/` endpoint takes the raw input document — do **not** wrap in
`{"input": ...}` (that is the v1 format). Use `-w "%{http_code}"` to check the
HTTP status code: 200 = allow, 404 = deny.

```bash
# Allow: user1 (dtaas-user) accessing /user1/lab
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8181/v0/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-user"]},"url":{"path":"/user1/lab"},"method":"GET"}'
# Expected: 200

# Deny: user1 accessing user2's workspace
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8181/v0/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-user"]},"url":{"path":"/user2/lab"},"method":"GET"}'
# Expected: 404

# Allow: admin (dtaas-admin) accessing user2's workspace
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8181/v0/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"subject":"sandra","extra":{"preferred_username":"sandra","roles":["dtaas-admin"]},"url":{"path":"/user2/lab"},"method":"GET"}'
# Expected: 200

# Allow: viewer (dtaas-viewer) reading own workspace
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8181/v0/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-viewer"]},"url":{"path":"/user1/lab"},"method":"GET"}'
# Expected: 200

# Deny: viewer writing to own workspace
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8181/v0/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-viewer"]},"url":{"path":"/user1/lab"},"method":"POST"}'
# Expected: 404
```

### Testing the opa-proxy Adapter

After adding `opa-proxy`, verify it correctly converts 404 → 403:

```bash
# Should return 403 (proxy converted OPA's 404 deny to 403)
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8080/v0/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-user"]},"url":{"path":"/user2/lab"},"method":"GET"}'
# Expected: 403

# Should return 200 (allow passes through unchanged)
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8080/v0/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"subject":"user1","extra":{"preferred_username":"user1","roles":["dtaas-user"]},"url":{"path":"/user1/lab"},"method":"GET"}'
# Expected: 200
```

## Traefik Middleware Configuration

The ForwardAuth middleware is defined on the `oathkeeper` service labels in
the compose file:

```yaml
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.address=http://oathkeeper:4456/decisions"
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.authResponseHeaders=X-User-Name,X-User-Subject,X-User-Groups"
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.authRequestHeaders=Authorization,Cookie"
```

The middleware is applied on workspace service routes, not on the client or
Keycloak routes. The DTaaS web client handles its own PKCE login flow directly
with Keycloak; Oathkeeper only protects the `/<username>/...` workspace paths.

In the current implementation, browser navigation requests are authenticated via
the `dtaas_access_token` cookie mirrored from the frontend runtime, which is why
`Cookie` must be forwarded to Oathkeeper.

## Static Policy Model

The current deployment is a static policy model:

- **Identity and token issuance**: Keycloak
- **Gateway and routing**: Traefik
- **PEP enforcement**: Oathkeeper
- **PDP evaluation**: OPA via `policy.rego`

Static means request evaluation depends on versioned config and policy files in
this repository, not dynamic remote policy bundles.

Static policy sources in this repo:

- `workspaces/test/dtaas/oathkeeper/oathkeeper.yml`
- `workspaces/test/dtaas/oathkeeper/access-rules.yml`
- `workspaces/test/dtaas/oathkeeper/policy.rego`
- `workspaces/test/dtaas/config/.env`

## Acceptance Checklist (Static Model)

Use this checklist after deployment changes:

1. A valid user token can access `/<preferred_username>/...` paths.
2. The same user is denied when accessing another username path.
3. Expired token requests are denied by Oathkeeper.
4. Oathkeeper logs show successful decision flow (no schema/config errors).
5. Common and private DTaaS library paths both load for the active user.
6. A full `docker compose down`/`up` cycle preserves behavior.

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

### Requests return 401 unexpectedly

1. Confirm the JWT `aud` claim contains `dtaas-client` — check via
   [jwt.io](https://jwt.io). The audience mapper must be configured in
   Keycloak via `configure_keycloak_rest.py`. If the claim is missing,
   Oathkeeper rejects the token at the authentication step.
2. Confirm the token issuer (`iss`) matches `KEYCLOAK_ISSUER_URL` exactly
   (including scheme and path).
3. Check Oathkeeper logs for the specific rejection reason:
   ```bash
   docker compose logs oathkeeper --tail 50
   ```

### Requests return 403 unexpectedly

1. Confirm the `preferred_username` claim matches the first path segment of
   the URL exactly (case-sensitive).
2. Check Oathkeeper logs for the specific rejection reason:
   ```bash
   docker compose logs oathkeeper --tail 50
   ```
3. Test the OPA policy directly with the `curl` commands above.

### Keycloak claims are missing from the token

The `preferred_username` claim requires the `profile` scope and the `aud`
claim requires the audience mapper — both are configured via
`configure_keycloak_rest.py`. See [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) for
details.

## Related Documents

- [TRAEFIK_SECURE.md](TRAEFIK_SECURE.md) — Deployment guide for the full stack
- [TRAEFIK_TLS.md](TRAEFIK_TLS.md) — TLS/HTTPS variant
- [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) — Keycloak realm and client setup
- [OIDC_FLOWS_WITH_OATHKEEPER.md](OIDC_FLOWS_WITH_OATHKEEPER.md) — Architecture and flow diagrams
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variable reference
