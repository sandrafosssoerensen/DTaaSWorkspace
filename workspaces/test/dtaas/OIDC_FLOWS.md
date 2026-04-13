# OIDC Flows in DTaaS

Two separate Keycloak clients handle two different parts of the user journey.
Both use Authorization Code flow, but with different security models suited to
their context.

## Architecture Overview

```text
Browser
  │
  ├─── DTaaS React SPA (dtaas-client) ──── Authorization Code + PKCE ───► Keycloak
  │         ↓ access token stored in browser
  │    calls workspace APIs with Bearer token
  │
  └─── Traefik ForwardAuth (dtaas-workspace) ── Authorization Code + secret ─► Keycloak
            ↓ session cookie
       workspace routes protected
```

**Component roles:**

| Component              | Role                                                              |
|------------------------|-------------------------------------------------------------------|
| Keycloak               | Identity Provider (IdP) — issues tokens for both clients          |
| DTaaS React SPA        | Public client — performs PKCE flow directly in the browser        |
| traefik-forward-auth   | Confidential client — server-side session management for Traefik  |
| Traefik                | Edge gateway — delegates auth decisions via ForwardAuth           |

---

## Flow 1: Authorization Code + PKCE (DTaaS React SPA)

The React web client (`dtaas-client`) is a **public client** — it runs entirely
in the browser and cannot safely hold a secret. PKCE is configured in Keycloak
manually to enforce this protection.

### Why PKCE?

PKCE (Proof Key for Code Exchange) prevents authorization code interception
attacks. Instead of a static client secret, the browser generates a fresh
`code_verifier` per login and sends only its SHA-256 hash (`code_challenge`) to
Keycloak. When exchanging the code for tokens, the original `code_verifier` must
match — something an intercepting party cannot reproduce.

### Step-by-step Flow

```text
1. User navigates to https://shared.dtaas-digitaltwin.com/ (the DTaaS client)
2. React SPA initiates Authorization Code + PKCE:
     a. Generates code_verifier (random string)
        and code_challenge = BASE64URL(SHA256(code_verifier))
     b. Redirects the browser to Keycloak:
          GET /auth/realms/dtaas/protocol/openid-connect/auth
              ?response_type=code
              &client_id=dtaas-client
              &redirect_uri=https://shared.dtaas-digitaltwin.com/Library
              &scope=openid profile email
              &code_challenge=<hash>
              &code_challenge_method=S256
              &state=<random>
3. User authenticates in Keycloak.
4. Keycloak redirects back to /Library?code=<authz_code>&state=<random>
5. React SPA exchanges the code for tokens (no client_secret — PKCE only):
          POST /auth/realms/dtaas/protocol/openid-connect/token
              grant_type=authorization_code
              code=<authz_code>
              redirect_uri=https://shared.dtaas-digitaltwin.com/Library
              client_id=dtaas-client
              code_verifier=<original>    ← proves same party initiated the flow
6. Keycloak validates the code_verifier against the stored code_challenge
   and returns id_token, access_token, refresh_token.
7. React SPA stores the access token in memory/session storage and uses it
   as a Bearer token when calling workspace APIs.
```

### Keycloak Client Setup (`dtaas-client`)

Configured manually in Keycloak:
- **Client type**: Public (no client secret)
- **Standard Flow Enabled**: `true`
- **PKCE Method**: `S256` (set under Advanced settings → Proof Key for Code Exchange)
- **Valid Redirect URIs**: `https://shared.dtaas-digitaltwin.com/Library`

---

## Flow 2: Authorization Code with Client Secret (traefik-forward-auth)

`traefik-forward-auth` is a **confidential client** running server-side. It
handles the OAuth redirect/callback itself and stores the resulting session in
an encrypted cookie. No token is ever passed to the browser.

### Step-by-step Flow

```text
1. User navigates to https://shared.dtaas-digitaltwin.com/sandra
2. Traefik ForwardAuth middleware forwards the request to traefik-forward-auth.
3. No valid session cookie → redirects browser to Keycloak:
          GET /auth/realms/dtaas/protocol/openid-connect/auth
              ?response_type=code
              &client_id=dtaas-workspace
              &redirect_uri=https://shared.dtaas-digitaltwin.com/_oauth
              &scope=openid profile email
              &state=<random>
4. User authenticates in Keycloak.
5. Keycloak redirects back to /_oauth?code=<authz_code>&state=<random>
6. traefik-forward-auth exchanges the code server-side:
          POST /auth/realms/dtaas/protocol/openid-connect/token
              grant_type=authorization_code
              code=<authz_code>
              redirect_uri=https://shared.dtaas-digitaltwin.com/_oauth
              client_id=dtaas-workspace
              client_secret=<secret>      ← held server-side only, never in browser
7. Keycloak returns id_token and access_token.
8. traefik-forward-auth creates an encrypted session cookie and redirects
   the user back to /sandra.
9. All subsequent requests carry the session cookie. traefik-forward-auth
   validates it and forwards requests to the workspace service.
```

### Keycloak Client Setup (`dtaas-workspace`)

Configured manually in Keycloak:
- **Client type**: Confidential (Client Authentication ON)
- **Standard Flow Enabled**: `true`
- **Valid Redirect URIs**: `https://shared.dtaas-digitaltwin.com/_oauth/*`

---

## Custom Claims

The `configure_keycloak_rest.py` script configures a `profile` protocol mapper
that can be placed either directly on the `dtaas-workspace` client (default)
or on a shared client scope (when `KEYCLOAK_USE_SHARED_SCOPE=true`; default is `false`).

**Userinfo endpoint** (`profile` mapper, `userinfo.token.claim: true`):

```json
{
  "preferred_username": "sandra",
  "profile": "https://shared.dtaas-digitaltwin.com/sandra"
}
```

> **Note**: The `profile` claim is userinfo-only — it is intentionally excluded
> from the access token (`access.token.claim: false`).

Additional claims like `groups` are built-in Keycloak mappers and can be added
to the client independently. The `groups_owner` and `sub_legacy` mappers are
not currently configured by this script.

---

## Comparison

| Aspect                 | `dtaas-client` (React SPA)        | `dtaas-workspace` (traefik-forward-auth) |
|------------------------|-----------------------------------|------------------------------------------|
| Client type            | Public                            | Confidential                             |
| Client secret          | None                              | Yes (server-side only)                   |
| PKCE                   | Yes — required, enforced in Keycloak | No                                    |
| Token held by          | Browser (memory/session storage)  | traefik-forward-auth (never browser)     |
| Session persistence    | Browser token lifetime            | Encrypted cookie (12h default)           |
| Redirect URI           | `/Library`                        | `/_oauth`                                |

---

## Related Documents

- [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) — Create realm, client, and users
- [KEYCLOAK_MIGRATION.md](KEYCLOAK_MIGRATION.md) — Migration from GitLab OAuth
- [TRAEFIK_SECURE.md](TRAEFIK_SECURE.md) — Traefik + traefik-forward-auth setup
- [TRAEFIK_TLS.md](TRAEFIK_TLS.md) — TLS variant with cert-based routing
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variable reference
