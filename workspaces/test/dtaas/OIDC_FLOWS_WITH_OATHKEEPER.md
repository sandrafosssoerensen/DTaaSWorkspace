# OIDC Flows in DTaaS with Oathkeeper

This document shows how the flows would look after introducing Oathkeeper as
a Policy Enforcement Point (PEP) in front of workspace routes.

## High-Level Architecture

```text
Browser
  │
  ├── React SPA (dtaas-client, PKCE) ───────────────► Keycloak
  │
  └── Workspace request
        │
        ▼
      Traefik
        │ ForwardAuth
        ▼
      Oathkeeper (JWT verification + policy call)
        │
        ├── JWKS + issuer checks against Keycloak
        └── authorization decision from OPA
        │
        ▼
      Workspace service
```

## Flow A: React SPA Login (Authorization Code + PKCE)

This part stays the same as today for the public browser client.

1. User opens the DTaaS client at https://shared.dtaas-digitaltwin.com/.
2. The SPA starts Authorization Code + PKCE against Keycloak with client_id dtaas-client.
3. Keycloak authenticates user and redirects back to /Library with an auth code.
4. SPA exchanges code with code_verifier at the token endpoint.
5. SPA receives id_token and access_token and keeps token in browser session context.

## Flow B: Workspace Access with Oathkeeper Enforcement

This is the new part compared to current state.

1. User requests a protected workspace route such as:
   https://shared.dtaas-digitaltwin.com/sandra/tools/vscode/
2. Browser sends Authorization: Bearer <access_token>.
3. Traefik forward-auth middleware calls Oathkeeper decision endpoint.
4. Oathkeeper validates JWT using Keycloak realm metadata and JWKS:
   - signature
   - issuer claim
   - audience claim
   - token expiry
5. Oathkeeper sends normalized request context to OPA policy endpoint.
6. OPA returns allow or deny based on claims and route policy.
7. If allow, Oathkeeper returns 200 and can inject identity headers.
8. Traefik forwards request to workspace container.
9. If deny, request is rejected with 401 or 403 before reaching workspace.

## Key Behavior Changes vs Current Setup

1. Current:
   - traefik-forward-auth mostly handles browser session auth.
   - route-level authorization is limited.
2. With Oathkeeper:
   - every protected request is policy-checked.
   - JWT verification is explicit and centralized.
   - fine-grained, claim-based authorization is possible.

## Expected Component Responsibilities

| Component | Responsibility with Oathkeeper |
|---|---|
| Keycloak | IdP, token issuance, signing keys (JWKS) |
| React SPA (dtaas-client) | PKCE login, holds user token |
| Traefik | Routing and ForwardAuth hook |
| Oathkeeper | JWT authentication and policy decision orchestration |
| OPA | Authorization policy evaluation |
| Workspace services | Business function only, trust gateway headers |

## Example Claims Used for Authorization

The same custom claims can drive policy decisions:

- groups
- https://gitlab.org/claims/groups/owner
- preferred_username
- sub
- profile

Example policy intent:

- allow users in group dtaas-users
- require preferred_username path match for per-user workspace routes
- allow elevated actions for users in owner claim group

## Minimal Request Path Comparison

Current path:

```text
Browser -> Traefik -> traefik-forward-auth -> Workspace
```

With Oathkeeper:

```text
Browser -> Traefik -> Oathkeeper -> OPA -> Workspace
```

## Practical Notes for Adoption

1. Add Oathkeeper and OPA services to compose.
2. Mount oathkeeper.yml, access-rules.yml, and policy.rego.
3. Wire Traefik middleware to Oathkeeper decision endpoint.
4. Set KEYCLOAK_JWKS_URL, KEYCLOAK_ISSUER_URL, KEYCLOAK_TARGET_AUDIENCE.
5. Keep dtaas-client PKCE setup unchanged.
6. Re-test route behavior for both allow and deny cases.

## Comparison Document

Use this file together with:

- [OIDC_FLOWS.md](OIDC_FLOWS.md)

to compare current implemented flow vs Oathkeeper target flow.
