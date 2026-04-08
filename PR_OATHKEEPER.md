# PR: Ory Oathkeeper and OPA Authorization for DTaaS Workspace Routes

## Summary

Replaces `traefik-forward-auth` with **Ory Oathkeeper** and **Open Policy Agent
(OPA)** as the authorization stack for workspace routes. Oathkeeper validates
Keycloak-issued JWTs at the edge and delegates per-user path isolation to an OPA
policy, removing the session-cookie based approach in favour of explicit Bearer
token enforcement.

## Changes

### `compose.traefik.secure.yml` and `compose.traefik.secure.tls.yml`

- Removed `traefik-forward-auth` service
- Added `oathkeeper` service (`oryd/oathkeeper:v0.40.8`)
  - Serves the decision API on port 4456 (called by Traefik `ForwardAuth`)
  - Uses a `sh -c sed` entrypoint wrapper to expand `${KEYCLOAK_JWKS_URL}`,
    `${KEYCLOAK_ISSUER_URL}`, and `${KEYCLOAK_TARGET_AUDIENCE}` placeholders —
    Oathkeeper v0.40.8 does not perform environment variable substitution in
    its YAML config natively
- Added `opa` service (`openpolicyagent/opa:0.70.0`)
  - Serves policy decisions on port 8181
  - Mounts `config/oathkeeper/policy.rego`
- Changed workspace route middleware from `traefik-forward-auth` to
  `oathkeeper-auth` on all `user1` and `user2` Traefik labels
- Oathkeeper `depends_on` both `keycloak` (healthy) and `opa` (started)
- Keycloak environment updated from deprecated `KEYCLOAK_ADMIN` /
  `KC_HOSTNAME` to `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD`

### `config/oathkeeper/oathkeeper.yml` *(new)*

- Configures Oathkeeper ports, log format, and access rule repository
- Enables `jwt` authenticator with `jwks_urls`, `trusted_issuers`,
  `allowed_algorithms` (RS256/384/512), and `target_audience` — all values
  substituted at startup via the `sed` wrapper
- Enables `remote_json` authorizer with a default OPA endpoint and payload
  template (required by Oathkeeper's schema validator even though per-rule
  overrides exist in `access-rules.yml`)
- Enables `header` mutator to inject `X-User-Name` and `X-User-Subject` into
  upstream requests

### `config/oathkeeper/access-rules.yml` *(new)*

- Single rule `dtaas-workspace-jwt-enforcement` matching all workspace URLs
  (`^https?://[^/]+/.+$`)
- Authenticator: `jwt` (Keycloak Bearer token verification)
- Authorizer: `remote_json` → OPA at `http://opa:8181/v1/data/workspace/authz/allow`
- Mutator: `header` injecting identity headers

### `config/oathkeeper/policy.rego` *(new)*

- Rego policy enforcing two conditions for `allow`:
  1. **Group membership**: `groups` JWT claim must contain `"dtaas"`
  2. **Path isolation**: `preferred_username` claim must match the first URL
     path segment (e.g. `user1` may only access `/user1/…`)
- Default deny — all requests are rejected unless both rules pass explicitly

### `config/.env.example`

- Removed `OAUTH_SECRET`, `KEYCLOAK_CLIENT_SECRET`, `DOCKER_HOST_HOSTNAME`
  (forward-auth specific)
- Kept `KEYCLOAK_ISSUER_URL` with updated documentation referencing Oathkeeper
- Added `KEYCLOAK_REALM` and `KEYCLOAK_TARGET_AUDIENCE`

### Documentation

- `OATHKEEPER.md` *(new)* — component table, config file reference, env var
  table, decision flow, OPA policy explanation with manual `curl` test
  commands, Traefik middleware config, troubleshooting table
- `OIDC_FLOWS_WITH_OATHKEEPER.md` *(new)* — architecture diagrams, flow
  comparison between current (`traefik-forward-auth`) and Oathkeeper setup
- `TRAEFIK_SECURE.md` — updated service list, startup instructions, and
  Keycloak setup references to reflect Oathkeeper stack
- `TRAEFIK_TLS.md` — same updates for TLS/HTTPS variant
- `KEYCLOAK_SETUP.md` — added Keycloak client configuration notes for
  Oathkeeper (confidential client, audience mapper, `groups` mapper)
- `CONFIGURATION.md` — updated env var reference table

## Why

`traefik-forward-auth` provides cookie-based session authentication but cannot
enforce fine-grained, claim-based authorization. In a multi-user deployment
where every user has their own workspace path, a valid login should not grant
access to other users' workspaces.

Oathkeeper + OPA separates concerns clearly:

- **Oathkeeper** handles cryptographic JWT verification (signature, issuer,
  audience, expiry)
- **OPA** evaluates the business policy (group membership + path isolation)

This makes the authorization rules explicit, testable independently of the
running stack, and extensible without changes to Traefik or Keycloak.

## Out of Scope

- The DTaaS web client (`dtaas-client`) PKCE login flow is unchanged — it
  authenticates directly with Keycloak and stores the access token in the
  browser. Oathkeeper only validates tokens on workspace routes.
- Custom claim injection (`groups`, `preferred_username`) still requires
  Keycloak protocol mappers to be configured. See
  [KEYCLOAK_SETUP.md](workspaces/test/dtaas/KEYCLOAK_SETUP.md) and
  [PR_CUSTOM_CLAIMS.md](PR_CUSTOM_CLAIMS.md) for automation.

## Validation

### Smoke test — OPA policy directly

```bash
# Allow: user1 accessing their own workspace
curl -s http://localhost:8181/v1/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"input": {"extra": {"preferred_username": "user1", "groups": ["dtaas"]},
        "url": {"path": "/user1/tools/vscode"}}}'
# Expected: {"result": true}

# Deny: user1 accessing user2's workspace
curl -s http://localhost:8181/v1/data/workspace/authz/allow \
  -H "Content-Type: application/json" \
  -d '{"input": {"extra": {"preferred_username": "user1", "groups": ["dtaas"]},
        "url": {"path": "/user2/tools/vscode"}}}'
# Expected: {"result": false}
```

### Stack startup

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
  --env-file workspaces/test/dtaas/config/.env up -d
```

All six services should reach `Up` state: `traefik`, `keycloak`, `oathkeeper`,
`opa`, `client`, `user1`, `user2`.

### Verify Oathkeeper decision API is reachable

```bash
curl -v http://localhost/user1/
# Expect: 401 Unauthorized (no token) — Oathkeeper is running and enforcing
```
