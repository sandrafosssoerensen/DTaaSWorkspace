# OIDC Flows in DTaaS with Oathkeeper

This document describes the current DTaaS flow where Oathkeeper and OPA are
decoupled:

- Oathkeeper handles gateway JWT authentication for Traefik routes.
- OPA is reserved for workspace-side authorization integration.

## Mermaid Architecture

```mermaid
flowchart TB
 subgraph PIP["PIP - Identity"]
      Keycloak["Keycloak <br> JWT: roles + username"]
  end
 subgraph PAP["PAP - Policy"]
      Policy["policy.rego <br> access-rules.yml"]
  end
 subgraph PEP["PEP - Enforcement"]
      Traefik["Traefik <br> ForwardAuth"]
      Oathkeeper["Oathkeeper <br> JWT validation"]
  end
 subgraph PDP["PDP - Decision"]
      OPA["OPA <br> allow / deny (workspace side)"]
  end
   Browser(["Browser"]) -- 1. login --> Keycloak
   Keycloak -- 2. JWT cookie --> Browser
   Browser -- 3. request + cookie --> Traefik
   Traefik -- 4. ForwardAuth --> Oathkeeper
   Keycloak -. 5. JWKS fetched and cached .-> Oathkeeper
   Oathkeeper -- 6. allow or deny --> Traefik
   Traefik -- 7. forward --> Workspace(["Workspace"])
   PAP -. rules .-> PDP
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| Keycloak | IdP: user authentication, token issuance, JWKS |
| React SPA (`dtaas-client`) | PKCE login and token handling |
| Traefik | Routing and ForwardAuth integration |
| Oathkeeper | JWT verification + identity header injection |
| OPA | Workspace-side policy evaluation (decoupled from Oathkeeper) |

## Flow A: User Login (Authorization Code + PKCE)

1. User opens the DTaaS client at `https://<SERVER_DNS>/`.
2. The SPA starts PKCE flow against Keycloak.
3. Keycloak authenticates the user and redirects back with auth code.
4. SPA exchanges code and receives access token.
5. SPA stores token as `dtaas_access_token` cookie for browser navigation.

## Flow B: Workspace Request (Gateway Authentication)

1. Browser requests workspace path (for example `/user1/tools/vscode`) with
  `dtaas_access_token` cookie.
2. Traefik calls Oathkeeper via ForwardAuth (`/decisions`).
3. Oathkeeper validates JWT:
  - Signature against Keycloak JWKS
  - `iss` equals configured issuer
  - `aud` contains configured audience
  - Expiry
4. If valid, Oathkeeper returns allow and forwards identity headers.
5. Traefik routes request to workspace container.

## Important Note on Step 5 (JWKS)

Oathkeeper does not call Keycloak on every request for signature verification.
It fetches JWKS and caches keys, then verifies JWT locally for subsequent
requests.

## Current Security Characteristics

| Area | Current state |
|---|---|
| Authentication at gateway | Enforced by Oathkeeper |
| Missing/invalid token | Denied (`401`) |
| Cross-user path RBAC at gateway | Not enforced in decoupled mode |
| Workspace-side RBAC | Planned via OPA integration with workspace nginx |

## Related Documents

- `OATHKEEPER.md`
- `TRAEFIK_SECURE.md`
- `TRAEFIK_TLS.md`
- `KEYCLOAK_SETUP.md`
