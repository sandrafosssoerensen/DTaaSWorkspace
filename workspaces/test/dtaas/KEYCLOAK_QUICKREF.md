# Keycloak Integration - Quick Reference

## Summary of Changes

The `compose.traefik.secure.tls.yml` has been updated to use **Keycloak** for authentication instead of GitLab OAuth.

## What's New

### 1. New Keycloak Service
- **Image**: `quay.io/keycloak/keycloak:26.0.7`
- **Access**: `https://foo.com/auth`
- **Purpose**: OIDC-based identity provider
- **Storage**: Persistent volume `keycloak-data`

### 2. Updated Authentication Flow
```
User → Traefik → Forward Auth → Keycloak (OIDC) → Protected Service
```

### 3. New Environment Variables
| Variable | Purpose | Example |
|----------|---------|---------|
| `KEYCLOAK_ADMIN` | Admin username | `admin` |
| `KEYCLOAK_ADMIN_PASSWORD` | Admin password | `changeme` |
| `KEYCLOAK_REALM` | Realm name | `dtaas` |
| `KEYCLOAK_CLIENT_ID` | OIDC client ID | `dtaas-workspace` |
| `KEYCLOAK_CLIENT_SECRET` | OIDC client secret | `<from-keycloak>` |
| `KEYCLOAK_ISSUER_URL` | OIDC issuer URL | `https://foo.com/auth/realms/dtaas` |

## Quick Setup

### Step 1: Configure Environment
```bash
cd workspaces/test/dtaas
cp config/.env.example config/.env
# Edit .env with Keycloak credentials
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
4. Create client: `dtaas-workspace` (OIDC, confidential)
5. Set redirect URIs: `https://foo.com/_oauth/*`
6. Copy client secret to `.env`
7. Create users in Keycloak
8. Restart services

### Step 4: Test
Navigate to `https://foo.com/` and login with Keycloak user.

## Key Benefits

✅ **Standards-Based**: Uses OIDC/OAuth2 standards
✅ **Flexible**: Easy to switch to external Keycloak
✅ **Enterprise-Ready**: Supports SSO, MFA, user federation
✅ **Minimal Changes**: Environment-variable based configuration

## Migration Paths

### Use External Keycloak
Just change `KEYCLOAK_ISSUER_URL` in `.env`:
```bash
KEYCLOAK_ISSUER_URL=https://foo.com/auth/realms/dtaas
```

## Documentation

- 📖 [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) - Complete setup guide
- 🔄 [KEYCLOAK_MIGRATION.md](KEYCLOAK_MIGRATION.md) - Migration details
- ⚙️ [CONFIGURATION.md](CONFIGURATION.md) - Configuration reference
- 🔐 [TRAEFIK_SECURE.md](TRAEFIK_SECURE.md) - Traefik with auth

## Troubleshooting

### Cannot access Keycloak
```bash
docker compose -f compose.traefik.secure.tls.yml logs keycloak
```

### Authentication issues
```bash
docker compose -f compose.traefik.secure.tls.yml logs traefik-forward-auth
```

### Check all services
```bash
docker compose -f compose.traefik.secure.tls.yml ps
```

## Production Checklist

- [ ] Use HTTPS (compose.traefik.secure.tls.yml)
- [ ] Change Keycloak admin password
- [ ] Use external Keycloak instance
- [ ] Configure Keycloak with proper database
- [ ] Set `INSECURE_COOKIE=false`
- [ ] Use strong client secrets
- [ ] Enable MFA for users
- [ ] Regular backups of keycloak-data volume
- [ ] Set log level to INFO or WARN
- [ ] Review security policies

## Support

For issues or questions:
1. Check documentation links above
2. Review logs as shown in troubleshooting
3. Verify environment variables in `.env`
4. Check Keycloak client configuration
