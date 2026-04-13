# Keycloak Setup Guide for DTaaS

This guide explains how to configure Keycloak as the identity provider for the
DTaaS workspace deployment. Oathkeeper uses Keycloak-issued JWTs for gateway
authentication.

## Architecture

```text
Browser  ──PKCE login──►  Keycloak (realm: dtaas, client: dtaas-client)
                               │
                         issues JWT with:
                           preferred_username
                           roles (realm roles)
                           aud (dtaas-workspace)
                               │
                         stored as dtaas_access_token cookie
                               │
                          Oathkeeper
                           (validates JWT)

Workspace-side authorization with OPA is decoupled from Oathkeeper.
```

## Prerequisites

- Docker Engine v27+
- Stack running (`compose.traefik.secure.yml` or `compose.traefik.secure.tls.yml`)
- `config/.env` configured (copy from `config/.env.example`)

## Quick Start — Automated Setup

The fastest way is the reset script with the configurator flag. It tears down
any existing stack, starts fresh, and fully configures Keycloak:

```powershell
.\scripts\reset-dtaas.ps1 -RunConfigurator
```

This runs `keycloak/configure_keycloak_rest.py` which creates idempotently:

| What | Details |
|---|---|
| **Realm** | `dtaas` (or value of `KEYCLOAK_REALM`) |
| **Client** | `dtaas-client` — public PKCE client, no secret |
| **Realm roles** | `dtaas-admin`, `dtaas-user`, `dtaas-viewer` |
| **Protocol mappers** | `roles` (realm roles flat array), `preferred_username`, audience |
| **Users** | From `KEYCLOAK_USERS` in `.env` with passwords and role assignments |

No manual Keycloak console steps required.

### Configuring Users in `.env`

Set `KEYCLOAK_USERS` as a JSON array in `config/.env`:

```bash
KEYCLOAK_USERS=[
  {"username":"user1","password":"user1","role":"dtaas-user","email":"user1@example.com","firstName":"User","lastName":"One"},
  {"username":"user2","password":"user2","role":"dtaas-user","email":"user2@example.com","firstName":"User","lastName":"Two"},
  {"username":"sandra","password":"sandra","role":"dtaas-admin","email":"sandra@example.com","firstName":"Sandra","lastName":"Admin"}
]
```

Valid roles: `dtaas-admin`, `dtaas-user`, `dtaas-viewer`.

---

## Manual Setup (Reference)

Use these steps if you need to configure Keycloak manually or are integrating
an external Keycloak instance.

### 1. Access Keycloak Admin Console

Navigate to `https://<SERVER_DNS>/auth` (TLS) or `http://<SERVER_DNS>/auth` (HTTP).
Click **Administration Console** and log in with the credentials from `.env`.

### 2. Create the Realm

1. In the top-left dropdown click **Create Realm**.
2. **Realm name**: `dtaas` (must match `KEYCLOAK_REALM` in `.env`).
3. Click **Create**.

> **HTTP deployments only**: Keycloak defaults to `sslRequired=external`. Disable
> it or Keycloak will reject HTTP requests from non-localhost addresses:
> - **Realm Settings → General → Require SSL → None**

### 3. Create the OIDC Client for DTaaS SPA (Public PKCE)

1. **Clients → Create client**
2. **Client type**: OpenID Connect. **Client ID**: `dtaas-client`. Click **Next**.
3. **Capability config**:
   - **Client authentication**: OFF (public client — no secret)
   - **Authentication flow**: Standard flow ✓, Direct access grants ✓ (for testing)
   - **PKCE**: S256
4. **Login settings**:
   - **Valid redirect URIs**: `https://<SERVER_DNS>/Library`, `https://<SERVER_DNS>/*`
   - **Web origins**: `https://<SERVER_DNS>`
5. Click **Save**.


### 4. Optional: Create Forward-Auth Client (Confidential)

If you use a forward-auth flow (instead of this repository's Oathkeeper-only validation),
create a second confidential client:

1. **Clients → Create client**
2. **Client type**: OpenID Connect. **Client ID**: `dtaas-workspace`. Click **Next**.
3. **Capability config**:
  - **Client authentication**: ON
  - **Standard flow**: ON
4. **Login settings**:
  - **Valid redirect URIs**: `https://<SERVER_DNS>/_oauth/*`
  - **Web origins**: `https://<SERVER_DNS>`
5. Save and copy the generated secret into:
  - `KEYCLOAK_FORWARD_AUTH_CLIENT_SECRET`
  - and optionally `KEYCLOAK_CLIENT_SECRET` (legacy alias)

### 5. Create Realm Roles

In **Realm roles → Create role**, create three roles:

| Role name | Description |
|---|---|
| `dtaas-admin` | Full access to any workspace (cross-user) |
| `dtaas-user` | Access to own workspace only |
| `dtaas-viewer` | Read-only access to own workspace |

### 6. Add Protocol Mappers

The `roles` claim **must be in the access token** so OPA can read it from
the JWT. Add these mappers to the client (or a shared client scope):

#### roles mapper (required for RBAC)

- **Mapper type**: User Realm Role
- **Name**: `roles`
- **Claim name**: `roles`
- **Add to access token**: ON
- **Add to userinfo**: ON
- **Multivalued**: ON

#### audience mapper (required for Oathkeeper)

- **Mapper type**: Audience
- **Name**: `audience`
- **Included client audience**: `dtaas-workspace`
- **Add to access token**: ON

### 7. Create Users

For each user:
1. **Users → Create new user**
2. Set **Username**, **Email**, **First/Last name**. **Email verified**: ON.
3. **Credentials** tab → **Set password** (Temporary: OFF).
4. **Role mapping** tab → **Assign role** → select the appropriate DTaaS role.

### 8. Disable SSL Requirement (HTTP deployments only)

```bash
docker exec dtaas-keycloak-1 /opt/keycloak/bin/kcadm.sh \
  config credentials --server http://localhost:8080/auth \
  --realm master --user <KEYCLOAK_ADMIN> --password <KEYCLOAK_ADMIN_PASSWORD>

docker exec dtaas-keycloak-1 /opt/keycloak/bin/kcadm.sh \
  update realms/master -s sslRequired=NONE

docker exec dtaas-keycloak-1 /opt/keycloak/bin/kcadm.sh \
  update realms/dtaas -s sslRequired=NONE
```

---

## Verifying the Configuration

After setup, decode a token to verify claims are correct:

```bash
# Get a token (requires Direct Access Grants enabled on the client)
TOKEN=$(curl -sk -X POST \
  "https://<SERVER_DNS>/auth/realms/dtaas/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=dtaas-client&username=user1&password=user1" \
  | jq -r '.access_token')

# Inspect claims
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq '{preferred_username, roles, aud}'
```

Expected output:
```json
{
  "preferred_username": "user1",
  "roles": ["dtaas-user"],
  "aud": ["dtaas-workspace", "account"]
}
```

---

## Production Considerations

### External Keycloak

To use an external Keycloak instance:

1. Set `KEYCLOAK_ISSUER_URL` in `.env` to the public issuer URL:
   ```bash
   KEYCLOAK_ISSUER_URL=https://keycloak.example.com/auth/realms/dtaas
   ```
2. Set `KEYCLOAK_JWKS_URL` to the external JWKS endpoint:
   ```bash
   KEYCLOAK_JWKS_URL=https://keycloak.example.com/auth/realms/dtaas/protocol/openid-connect/certs
   ```
3. Remove or comment out the `keycloak` service from the compose file.
4. Create the realm, client, roles, and mappers manually or via the configurator
   script pointed at the external instance.

### Secure Credentials

- Change the default Keycloak admin password in `.env`.
- Use strong, unique passwords for all users.
- Rotate secrets and certificates regularly.

### Database Backend

For production, configure Keycloak with PostgreSQL:

```yaml
keycloak:
  environment:
    - KC_DB=postgres
    - KC_DB_URL=jdbc:postgresql://postgres:5432/keycloak
    - KC_DB_USERNAME=keycloak
    - KC_DB_PASSWORD=secure_password
```

---

## Troubleshooting

### Keycloak Not Accessible

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
  --env-file workspaces/test/dtaas/config/.env logs keycloak
```

### Token Missing `roles` Claim

Run the configurator to create the missing mapper:

```bash
cd workspaces/test/dtaas/keycloak
python3 configure_keycloak_rest.py
```

Or add the mapper manually: **Client → dtaas-client → Client scopes →
Add mapper → By configuration → User Realm Role**.

### Token Missing `aud` Claim

Oathkeeper rejects tokens without the correct audience. Add the audience
mapper (see step 5 above) or run the configurator.

### "Invalid Client" Error

The client `dtaas-client` is a **public** PKCE client and should not require a
client secret. The separate `dtaas-workspace` client is confidential and should
be used only for forward-auth style setups.

### Configurator Script Fails

```bash
cd workspaces/test/dtaas/keycloak
python3 configure_keycloak_rest.py --help
```

Check that Keycloak is healthy before running:
```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml ps keycloak
```

## References

- [OATHKEEPER.md](OATHKEEPER.md) — Oathkeeper + OPA architecture and configuration
- [KEYCLOAK_CUSTOM_CLAIMS.md](KEYCLOAK_CUSTOM_CLAIMS.md) — Claims contract
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variable reference
- [Keycloak Documentation](https://www.keycloak.org/documentation)
