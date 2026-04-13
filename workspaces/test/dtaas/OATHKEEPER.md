# Oathkeeper Authentication in DTaaS

This document describes the current DTaaS gateway design where Oathkeeper and OPA
are decoupled:

- Oathkeeper is used by Traefik ForwardAuth for JWT authentication.
- OPA remains available for workspace-side authorization integration.

## Current Architecture

```text
Browser
  │
  ├── React SPA (PKCE login) ───────────────► Keycloak
  │        stores dtaas_access_token cookie
  │
  └── Workspace request (cookie)
           │
           ▼
        Traefik
           │ ForwardAuth
           ▼
        Oathkeeper
           │ validates JWT
           │
           ▼
        Workspace service

OPA is currently decoupled from Oathkeeper and intended for workspace-side nginx.
```

## Responsibilities

| Component | Responsibility |
|---|---|
| Keycloak | IdP, token issuance, JWKS |
| Traefik | Routing + ForwardAuth hook |
| Oathkeeper | JWT validation and identity header injection |
| OPA | Workspace-side policy engine (decoupled from gateway for now) |

## Oathkeeper Behavior

Oathkeeper currently uses:

- `jwt` authenticator
- `allow` authorizer
- `header` mutator

This means:

- Invalid or missing token: request denied (`401`)
- Valid token: request allowed through gateway

Fine-grained RBAC such as `user1` denied on `/user2/...` is not enforced at the
gateway in this mode.

## Configuration Files

Main files under `workspaces/test/dtaas/oathkeeper/`:

| File | Purpose |
|---|---|
| `oathkeeper.yml` | Oathkeeper server/authenticator/mutator config |
| `access-rules.yml` | Route matching and handler selection |
| `policy.rego` | OPA policy for workspace-side integration |

## Environment Variables (Oathkeeper)

| Variable | Description |
|---|---|
| `KEYCLOAK_JWKS_URL` | Internal JWKS endpoint used for signature verification |
| `KEYCLOAK_ISSUER_URL` | Expected `iss` claim |
| `KEYCLOAK_TARGET_AUDIENCE` | Expected `aud` claim |

## Traefik ForwardAuth Labels

```yaml
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.address=http://oathkeeper:4456/decisions"
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.authRequestHeaders=Authorization,Cookie"
- "traefik.http.middlewares.oathkeeper-auth.forwardauth.authResponseHeaders=X-User-Name,X-User-Subject,X-User-Groups"
```

`Cookie` forwarding is required because browser navigation requests carry the
`dtaas_access_token` cookie.

## Verification Checklist

1. Requests without token are denied (`401`).
2. Requests with valid token are forwarded to workspace.
3. Oathkeeper logs show successful JWT validation and no schema errors.
4. JWT `aud` matches `KEYCLOAK_TARGET_AUDIENCE`.

## Troubleshooting

### Oathkeeper startup fails

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env logs oathkeeper
```

Common causes:

- Unsubstituted `${KEYCLOAK_*}` variables
- Invalid issuer/audience values
- Missing mounted config files

### Requests return 401 unexpectedly

Check:

1. Token has correct `iss` and `aud`.
2. Keycloak JWKS endpoint is reachable from Oathkeeper container.
3. `dtaas_access_token` cookie is present in browser requests.

## Notes on OPA

OPA is intentionally decoupled from Oathkeeper in the current design. Workspace
RBAC enforcement is planned via workspace nginx integration, not via Oathkeeper
`remote_json` at the Traefik gateway.

## Related Documents

- `OIDC_FLOWS_WITH_OATHKEEPER.md`
- `TRAEFIK_SECURE.md`
- `TRAEFIK_TLS.md`
- `KEYCLOAK_SETUP.md`
