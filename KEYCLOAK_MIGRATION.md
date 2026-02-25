# Keycloak Integration - Migration Guide

This document describes the changes made to integrate Keycloak authentication into the DTaaS workspace deployment.

## What Changed

The `compose.traefik.secure.yml` file has been updated to use **Keycloak** as the identity provider instead of GitLab OAuth. This provides:

- ✅ **OIDC Standards Compliance**: Uses OpenID Connect for authentication
- ✅ **Better User Management**: Centralized identity and access management
- ✅ **Flexibility**: Easy to switch between internal and external Keycloak
- ✅ **Enterprise Features**: Support for SSO, MFA, user federation, and more
- ✅ **Backward Compatibility**: Can still use GitLab OAuth with minor configuration changes

## New Services

### Keycloak Service

A new `keycloak` service has been added to the compose file:

```yaml
keycloak:
  image: quay.io/keycloak/keycloak:26.0.7
  # Accessible at http://foo.com/auth
  # Provides OIDC authentication
```

**Key Features:**
- Runs in development mode (`start-dev`)
- Accessible via Traefik at `/auth` path
- Persistent data storage with Docker volume
- Configurable via environment variables

## Modified Services

### traefik-forward-auth

Updated to use OIDC provider instead of generic OAuth:

**Before:**
```yaml
environment:
  - DEFAULT_PROVIDER=generic-oauth
  - PROVIDERS_GENERIC_OAUTH_AUTH_URL=${OAUTH_URL}/oauth/authorize
  - PROVIDERS_GENERIC_OAUTH_TOKEN_URL=${OAUTH_URL}/oauth/token
  - PROVIDERS_GENERIC_OAUTH_USER_URL=${OAUTH_URL}/api/v4/user
```

**After:**
```yaml
environment:
  - DEFAULT_PROVIDER=oidc
  - PROVIDERS_OIDC_ISSUER_URL=${KEYCLOAK_ISSUER_URL}
  - PROVIDERS_OIDC_CLIENT_ID=${KEYCLOAK_CLIENT_ID}
  - PROVIDERS_OIDC_CLIENT_SECRET=${KEYCLOAK_CLIENT_SECRET}
```

## Configuration Files Updated

### 1. `compose.traefik.secure.yml`

- Added `keycloak` service
- Updated `traefik-forward-auth` to use OIDC
- Added `keycloak-data` volume for persistence
- Added `depends_on` to ensure Keycloak starts before auth

### 2. `dtaas/.env.example`

- Added Keycloak-specific environment variables
- Maintained backward compatibility with GitLab OAuth
- Added comprehensive comments for both authentication methods

### 3. `CONFIGURATION.md`

- Updated to reference Keycloak setup as the primary method
- Kept GitLab OAuth instructions as an alternative
- Added link to dedicated Keycloak setup guide

### 4. `KEYCLOAK_SETUP.md` (New)

- Comprehensive setup guide for Keycloak
- Step-by-step configuration instructions
- Troubleshooting section
- Production deployment considerations

## Environment Variables

### New Required Variables

```bash
# Keycloak admin credentials
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=changeme

# Keycloak realm and client
KEYCLOAK_REALM=dtaas
KEYCLOAK_CLIENT_ID=dtaas-workspace
KEYCLOAK_CLIENT_SECRET=<from-keycloak>
KEYCLOAK_ISSUER_URL=http://keycloak:8080/auth/realms/dtaas
```

### Deprecated Variables (GitLab OAuth)

These are no longer used by default but remain for backward compatibility:

```bash
OAUTH_URL=https://gitlab.com
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
```

### Shared Variables

```bash
OAUTH_SECRET=...  # Still used for session encryption
SERVER_DNS=foo.com
USERNAME1=user1
USERNAME2=user2
```

## Migration Path

### Option 1: Use Embedded Keycloak (Default)

1. Pull the latest changes
2. Update your `.env` file with Keycloak variables
3. Follow [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md)
4. Restart services

### Option 2: Use External Keycloak

1. Set up Keycloak externally
2. Update `KEYCLOAK_ISSUER_URL` to point to external Keycloak
3. Remove `keycloak` service from compose file (optional)
4. Configure client in external Keycloak
5. Update `.env` with credentials
6. Restart services

### Option 3: Continue Using GitLab OAuth

1. Modify `traefik-forward-auth` service in compose file:
   ```yaml
   environment:
     - DEFAULT_PROVIDER=generic-oauth
     - PROVIDERS_GENERIC_OAUTH_AUTH_URL=${OAUTH_URL}/oauth/authorize
     - PROVIDERS_GENERIC_OAUTH_TOKEN_URL=${OAUTH_URL}/oauth/token
     - PROVIDERS_GENERIC_OAUTH_USER_URL=${OAUTH_URL}/api/v4/user
     - PROVIDERS_GENERIC_OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID}
     - PROVIDERS_GENERIC_OAUTH_CLIENT_SECRET=${OAUTH_CLIENT_SECRET}
     - PROVIDERS_GENERIC_OAUTH_SCOPE=read_user
   ```
2. Remove `keycloak` service from compose file
3. Keep your existing `.env` configuration

## Benefits of This Design

### Minimal Changes for External Keycloak

The configuration uses environment variables that make it easy to switch from embedded to external Keycloak:

```bash
# Internal (default)
KEYCLOAK_ISSUER_URL=http://keycloak:8080/auth/realms/dtaas

# External (just change the URL)
KEYCLOAK_ISSUER_URL=https://keycloak.company.com/auth/realms/dtaas
```

No compose file changes needed!

### Standard OIDC Implementation

Using standard OIDC means:
- Compatible with any OIDC provider (not just Keycloak)
- Could switch to Okta, Auth0, Azure AD, etc. with just env var changes
- Following security best practices
- Better token management and refresh

### Container Isolation

- Keycloak runs in its own container
- Can be removed/replaced without affecting other services
- Data persisted in Docker volume
- Easy to backup and restore

## Testing the Setup

After deploying the changes:

1. **Check services are running:**
   ```bash
   docker compose -f compose.traefik.secure.yml ps
   ```

2. **Verify Keycloak is accessible:**
   ```bash
   curl -I http://foo.com/auth
   # Should return 200 OK
   ```

3. **Test authentication flow:**
   - Navigate to `http://foo.com/`
   - Should redirect to Keycloak login
   - Login with created user
   - Should redirect back to application

4. **Check logs if issues occur:**
   ```bash
   docker compose -f compose.traefik.secure.yml logs keycloak
   docker compose -f compose.traefik.secure.yml logs traefik-forward-auth
   ```

## Production Considerations

Before deploying to production:

1. ✅ Use HTTPS (switch to `compose.traefik.secure.tls.yml`)
2. ✅ Change default Keycloak admin password
3. ✅ Use external Keycloak instance
4. ✅ Configure Keycloak with proper database (PostgreSQL/MySQL)
5. ✅ Set up proper backup strategy for Keycloak data
6. ✅ Configure Keycloak realm with appropriate security policies
7. ✅ Set `INSECURE_COOKIE=false` in traefik-forward-auth
8. ✅ Use strong client secrets
9. ✅ Enable MFA for users
10. ✅ Regular security audits

## References

- [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) - Detailed setup instructions
- [CONFIGURATION.md](CONFIGURATION.md) - General configuration guide
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [Traefik Forward Auth](https://github.com/thomseddon/traefik-forward-auth)
- [OIDC Specification](https://openid.net/specs/openid-connect-core-1_0.html)
