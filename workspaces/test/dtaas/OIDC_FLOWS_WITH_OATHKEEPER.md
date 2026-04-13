# OIDC Flows in DTaaS with Oathkeeper

This document describes the current authentication and authorization flows
after introducing Oathkeeper as a Policy Enforcement Point (PEP) in front
of workspace routes.

## High-Level Architecture

```text
Browser
  │
  ├── React SPA (PKCE login) ──────────────────────────► Keycloak
  │       sets dtaas_access_token cookie
  │
  └── Workspace request (cookie)
        │
        ▼
      Traefik
        │ ForwardAuth
        ▼
      Oathkeeper
        │ reads dtaas_access_token cookie
        │ verifies JWT (signature, issuer, audience, expiry)
        │ checks Keycloak JWKS
        │
        ▼
      opa-proxy (nginx 404→403 adapter)
        │
        ▼
      OPA (v0 API — RBAC policy)
        │ 200 allow / 404 deny
        ▼
      opa-proxy converts 404 → 403
        │
        ▼
      Oathkeeper: 200 → allow, 403 → ErrForbidden
        │
        ▼
      Workspace service (receives X-User-Name, X-User-Subject, X-User-Groups)
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| Keycloak | IdP: token issuance, signing keys (JWKS), realm roles |
| React SPA (`dtaas-client`) | PKCE login; stores access token as `dtaas_access_token` cookie |
| Traefik | Routing and ForwardAuth hook |
| Oathkeeper | JWT verification (authenticator) + policy orchestration (authorizer) |
| opa-proxy | nginx adapter: converts OPA's 404 deny to 403 so Oathkeeper returns correct status |
| OPA | RBAC policy evaluation (`policy.rego`) |
| Workspace services | Business function only; trust gateway headers |

## Flow A: React SPA Login (Authorization Code + PKCE)

1. User opens the DTaaS client at `https://<SERVER_DNS>/`.
2. The SPA starts Authorization Code + PKCE against Keycloak with
   `client_id=dtaas-workspace`.
3. Keycloak authenticates the user and redirects back to `/Library` with an
   auth code.
4. SPA exchanges the code (+ `code_verifier`) at the token endpoint.
5. SPA receives `id_token` and `access_token`.
6. The access token is stored as the `dtaas_access_token` cookie so that
   subsequent workspace navigation requests carry it automatically.

## Flow B: Workspace Request with Oathkeeper Enforcement

1. Browser navigates to a workspace route, e.g.
   `https://<SERVER_DNS>/user1/tools/vscode`.
2. The `dtaas_access_token` cookie is sent automatically by the browser.
3. Traefik's `oathkeeper-auth` ForwardAuth middleware calls
   `http://oathkeeper:4456/decisions`.
4. Oathkeeper reads the JWT from the `dtaas_access_token` cookie and validates:
   - Signature (RS256/384/512) against Keycloak's JWKS endpoint
   - `iss` claim matches `KEYCLOAK_ISSUER_URL`
   - `aud` claim contains `KEYCLOAK_TARGET_AUDIENCE` (`dtaas-workspace`)
   - Token expiry
5. Oathkeeper posts the request context as raw JSON to
   `http://opa-proxy:8080/v0/data/workspace/authz/allow`:
   ```json
   {
     "subject": "<sub claim>",
     "extra": { "preferred_username": "user1", "roles": ["dtaas-user"], ... },
     "url": { "path": "/user1/tools/vscode" },
     "method": "GET"
   }
   ```
6. opa-proxy forwards the request to OPA (`http://opa:8181/v0/data/...`).
7. OPA evaluates `policy.rego` and returns HTTP 200 (allow) or HTTP 404
   (undefined/deny).
8. opa-proxy passes through 200; converts 404 → 403.
9. Oathkeeper receives:
   - HTTP 200 → allow; injects `X-User-Name`, `X-User-Subject`,
     `X-User-Groups` headers and returns 200 to Traefik.
   - HTTP 403 → `ErrForbidden`; returns 403 to Traefik (and client).
10. Traefik forwards allowed requests to the workspace container.

## Claims Used for Authorization

Keycloak emits these claims in the JWT access token via protocol mappers
configured by `configure_keycloak_rest.py`:

| Claim | Source | Used by |
|---|---|---|
| `preferred_username` | Standard OIDC `profile` scope | OPA path-matching |
| `roles` | `oidc-usermodel-realm-role-mapper` | OPA RBAC role checks |
| `aud` | Audience mapper | Oathkeeper audience validation |

### RBAC Roles

| Role | Access |
|---|---|
| `dtaas-admin` | Any workspace path, any HTTP method |
| `dtaas-user` | Own workspace only, any method |
| `dtaas-viewer` | Own workspace only, GET/HEAD/OPTIONS only |

## Key Behavior vs Previous Setup

| Aspect | Before | Now |
|---|---|---|
| Authorization model | None (path was unprotected) | RBAC via Keycloak realm roles |
| Token verification | None | Oathkeeper validates every request |
| Cross-user access | Always possible | Blocked by OPA for `dtaas-user` and `dtaas-viewer` |
| Admin cross-user access | N/A | `dtaas-admin` role grants access to any workspace |
| Identity headers | Not injected | `X-User-Name`, `X-User-Subject`, `X-User-Groups` forwarded upstream |

## Related Documents

- [OATHKEEPER.md](OATHKEEPER.md) — Configuration reference and troubleshooting
- [OATHKEEPER_DEMO.md](OATHKEEPER_DEMO.md) — Step-by-step demo
- [OIDC_FLOWS.md](OIDC_FLOWS.md) — Comparison with previous auth approach
- [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) — Keycloak realm and client setup
