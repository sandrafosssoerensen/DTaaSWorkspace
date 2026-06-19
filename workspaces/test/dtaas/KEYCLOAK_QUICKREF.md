# Keycloak Integration - Quick Reference

## Summary

The `compose.traefik.secure.tls.yml` setup uses **Keycloak** for identity and
**Oathkeeper** as the authentication proxy — replacing the previous GitLab OAuth
and traefik-forward-auth setup.

## Authentication Flow

```
User → Traefik (TLS) → [forwardAuth: Oathkeeper :4456] → workspace / SPA
                               ↓ no token / expired token
                        login-relay (/login-relay) → Keycloak (OIDC)
                               → /login-relay/callback → sets dtaas_access_token cookie
                               → original destination
```

## Key Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `KEYCLOAK_ADMIN` | Admin username | `admin` |
| `KEYCLOAK_ADMIN_PASSWORD` | Admin password | `changeme` |
| `KEYCLOAK_REALM` | Realm name | `dtaas` |
| `KEYCLOAK_CLIENT_ID` | Confidential client (login-relay) | `dtaas-workspace` |
| `KEYCLOAK_CLIENT_SECRET` | Client secret for login-relay | `<from-keycloak>` |
| `KEYCLOAK_PUBLIC_URL` | Public Keycloak URL (browser-facing) | `https://foo.com/auth` |
| `KEYCLOAK_INTERNAL_URL` | Internal Keycloak URL (container-to-container) | `http://keycloak:8080/auth` |
| `SERVER_DNS` | Public domain name | `foo.com` |
| `USERNAME1` / `USERNAME2` | Workspace usernames (must match Keycloak) | `user1` |
| `WORKSPACE_USERS` | Comma-separated list of workspace users | `user1,user2` |

## Quick Setup

### Step 1: Configure Environment

```bash
cd workspaces/test/dtaas
cp config/.env.example config/.env
# Edit .env with your values
```

### Step 2: Start Services

```bash
docker compose -f compose.traefik.secure.tls.yml build
docker compose -f compose.traefik.secure.tls.yml --env-file config/.env up -d
```

### Step 3: Setup Keycloak (First Time Only)

1. Go to `https://foo.com/auth`
2. Login with admin credentials
3. Create realm: `dtaas`
4. Create confidential client: `dtaas-workspace`
   - Client authentication: **ON**
   - Valid redirect URIs: `https://foo.com/login-relay/callback`
5. Copy client secret to `.env` as `KEYCLOAK_CLIENT_SECRET`
6. Create a public client: `dtaas-client` (for the SPA)
   - Client authentication: **OFF** (public)
   - Valid redirect URIs: `https://foo.com/library`
7. Create users — usernames must match `USERNAME1` / `USERNAME2` in `.env`
8. Restart services

See [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) for the full setup guide.

### Step 4: Test

Navigate to `https://foo.com/` — you should be redirected to Keycloak login.

## Key Benefits

✅ **Standards-Based**: Uses OIDC/OAuth2 (authorization code flow)
✅ **Per-User Enforcement**: Oathkeeper + login-relay RBAC ensures each user
   can only access their own workspace
✅ **Enterprise-Ready**: Supports SSO, MFA, user federation
✅ **Flexible**: Easy to switch to an external Keycloak instance

## Use External Keycloak

Update `.env`:

```bash
KEYCLOAK_PUBLIC_URL=https://keycloak.example.com/auth
KEYCLOAK_INTERNAL_URL=https://keycloak.example.com/auth
```

Then remove the `keycloak` service from `compose.traefik.secure.tls.yml`.

## Documentation

- 📖 [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) — Complete setup guide
- 🔄 [KEYCLOAK_MIGRATION.md](KEYCLOAK_MIGRATION.md) — Migration details
- ⚙️ [CONFIGURATION.md](CONFIGURATION.md) — Configuration reference
- 🔒 [TRAEFIK_TLS.md](TRAEFIK_TLS.md) — Traefik TLS + Oathkeeper deployment
- 💡 [MOTIVATION.md](MOTIVATION.md) — Architecture rationale

## Troubleshooting

### Cannot Access Keycloak

```bash
docker compose -f compose.traefik.secure.tls.yml logs keycloak
```

### Authentication Issues (redirect loop, cookie not set)

```bash
docker compose -f compose.traefik.secure.tls.yml logs login-relay
docker compose -f compose.traefik.secure.tls.yml logs oathkeeper
```

### Check All Services

```bash
docker compose -f compose.traefik.secure.tls.yml ps
```

## Production Checklist

- [ ] Use HTTPS (`compose.traefik.secure.tls.yml`)
- [ ] Change Keycloak admin password
- [ ] Use external Keycloak instance (recommended)
- [ ] Configure Keycloak with a proper database (PostgreSQL)
- [ ] Use a strong `KEYCLOAK_CLIENT_SECRET`
- [ ] Enable MFA for users in Keycloak
- [ ] Regular backups of `keycloak-data` volume
- [ ] Set Keycloak log level to `INFO` or `WARN`
- [ ] Review Oathkeeper access rules for your users

## Support

For issues or questions:

1. Check documentation links above
2. Review logs as shown in troubleshooting
3. Verify environment variables in `.env`
4. Check Keycloak client configuration (redirect URIs, client authentication ON/OFF)
