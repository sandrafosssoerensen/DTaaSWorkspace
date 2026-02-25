# Keycloak Setup Guide for DTaaS

This guide explains how to configure Keycloak for authentication in the DTaaS workspace deployment using `compose.traefik.secure.tls.yml`.

## Overview

The updated configuration uses:
- **Keycloak** as the identity provider (IdP) with OIDC support
- **Traefik Forward Auth** to protect routes using OIDC
- **Traefik** as the reverse proxy

## Architecture

```
User Request → Traefik → Forward Auth → Keycloak (OIDC)
                    ↓
              Protected Service
```

## Prerequisites

✅ Docker Engine v27 or later
✅ Docker Compose
✅ Port 80 available on your host
✅ At least 2GB RAM available

## Quick Start

### 1. Configure Environment Variables

Copy the example environment file and update it:

```bash
cp dtaas/.env.example dtaas/.env
```

Edit `dtaas/.env`:

```bash
# Keycloak Admin Credentials (for initial setup)
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=changeme

# Keycloak Realm
KEYCLOAK_REALM=dtaas

# Keycloak Client Configuration (will be created in step 2)
KEYCLOAK_CLIENT_ID=dtaas-workspace
KEYCLOAK_CLIENT_SECRET=<will-be-generated>

# Server Configuration
SERVER_DNS=foo.com

# Generate a secure secret for OAuth sessions
OAUTH_SECRET=$(openssl rand -base64 32)

# Usernames
USERNAME1=user1
USERNAME2=user2
```

### 2. Start Services

Build and start all services:

```bash
docker compose -f compose.traefik.secure.tls.yml build
docker compose -f compose.traefik.secure.tls.yml --env-file dtaas/.env up -d
```

### 3. Configure Keycloak

#### Access Keycloak Admin Console

1. Navigate to `https://foo.com/auth`
2. Click on "Administration Console"
3. Login with credentials from your `.env` file (default: admin/admin)

#### Create a Realm

1. In the top-left dropdown (currently showing "Master"), click "Create Realm"
2. **Realm name**: `dtaas` (or match your `KEYCLOAK_REALM` in .env)
3. Click "Create"

#### Create a Client

1. In the left sidebar, click "Clients"
2. Click "Create client"
3. Configure the client:
   - **Client type**: OpenID Connect
   - **Client ID**: `dtaas-workspace` (match `KEYCLOAK_CLIENT_ID` in .env)
   - Click "Next"
   
4. **Capability config**:
   - ✅ Client authentication: ON
   - ✅ Authorization: OFF
   - **Authentication flow**: Check "Standard flow"
   - Click "Next"

5. **Login settings**:
   - **Root URL**: `https://foo.com`
   - **Valid redirect URIs**: 
     - `https://foo.com/_oauth/*`
     - `https://foo.com/*`
   - **Valid post logout redirect URIs**: `https://foo.com/*`
   - **Web origins**: `https://foo.com`
   - Click "Save"

6. **Get the Client Secret**:
   - Go to the "Credentials" tab
   - Copy the "Client secret" value
   - Update `KEYCLOAK_CLIENT_SECRET` in your `.env` file

#### Create Users

1. In the left sidebar, click "Users"
2. Click "Create new user"
3. Fill in user details:
   - **Username**: `user1` (or your desired username)
   - **Email**: user's email (optional)
   - **First name** and **Last name**: optional
   - ✅ Email verified: ON (optional, for testing)
4. Click "Create"

5. **Set Password**:
   - Go to the "Credentials" tab
   - Click "Set password"
   - Enter a password
   - ⚠️ Temporary: OFF (so users don't need to change it on first login)
   - Click "Save"

6. Repeat for additional users (user2, etc.)

### 4. Restart Services

After configuring Keycloak, restart the services to apply the new client secret:

```bash
docker compose -f compose.traefik.secure.tls.yml --env-file dtaas/.env down
docker compose -f compose.traefik.secure.tls.yml --env-file dtaas/.env up -d
```

### 5. Test Authentication

1. Navigate to `https://foo.com/`
2. You should be redirected to Keycloak login
3. Login with one of the users you created
4. You should be redirected back to the DTaaS interface

## Access Control Configuration

To restrict which users can access specific workspaces, edit `dtaas/conf`:

```ini
# Allow only user1 to access /user1 paths
rule.user1_access.action=auth
rule.user1_access.rule=PathPrefix(`/user1`)
rule.user1_access.whitelist = user1@localhost

# Allow only user2 to access /user2 paths
rule.user2_access.action=auth
rule.user2_access.rule=PathPrefix(`/user2`)
rule.user2_access.whitelist = user2@localhost
```

**Note**: The whitelist uses the email address from Keycloak. Adjust accordingly.

## Production Considerations

### 1. Use HTTPS

For production, use `compose.traefik.secure.tls.yml` instead, which includes TLS/HTTPS configuration.

### 2. External Keycloak

To use an external Keycloak instance (recommended for production):

1. Update `KEYCLOAK_ISSUER_URL` in `.env`:
   ```bash
   KEYCLOAK_ISSUER_URL=https://keycloak.example.com/auth/realms/dtaas
   ```

2. Remove the `keycloak` service from `compose.traefik.secure.tls.yml` (optional):
   - Comment out or delete the entire `keycloak` service section
   - Remove `keycloak` from `depends_on` in `traefik-forward-auth`
   - Remove the `keycloak-data` volume

3. Update client redirect URIs in Keycloak to use your production domain

### 3. Secure Credentials

- Change default Keycloak admin password
- Use strong client secrets
- Store secrets securely (use Docker secrets or external secret managers)
- Rotate secrets regularly

### 4. Database Backend

For production, configure Keycloak with a proper database (PostgreSQL, MySQL):

```yaml
keycloak:
  environment:
    - KC_DB=postgres
    - KC_DB_URL=jdbc:postgresql://postgres:5432/keycloak
    - KC_DB_USERNAME=keycloak
    - KC_DB_PASSWORD=secure_password
```

## Troubleshooting

### Cannot Access Keycloak Admin Console

- Ensure the Keycloak service is running: `docker compose ps`
- Check Keycloak logs: `docker compose logs keycloak`
- Verify port 80 is accessible

### Authentication Loop/Redirect Issues

- Verify `KEYCLOAK_ISSUER_URL` matches the realm name
- Check that redirect URIs in Keycloak client include `/_oauth/*`
- Ensure `COOKIE_DOMAIN` matches your domain
- Clear browser cookies and try again

### "Invalid Client" Error

- Verify `KEYCLOAK_CLIENT_ID` matches the client ID in Keycloak
- Ensure `KEYCLOAK_CLIENT_SECRET` is correct
- Check that client authentication is enabled

### Forward Auth Not Working

- Check traefik-forward-auth logs: `docker compose logs traefik-forward-auth`
- Verify environment variables are set correctly
- Ensure Keycloak is accessible from the traefik-forward-auth container

## Advanced Configuration

### Custom Claims and Scopes

To access custom user attributes:

1. In Keycloak, create client scopes with mappers
2. Assign scopes to the client
3. Configure traefik-forward-auth to request additional scopes

### Role-Based Access Control (RBAC)

1. Create roles in Keycloak realm
2. Assign roles to users
3. Use role claims in traefik-forward-auth rules

### Single Sign-On (SSO)

Keycloak supports SSO across multiple applications. Configure additional clients for other services in your infrastructure.

## Migration from GitLab OAuth

If you're migrating from the previous GitLab OAuth setup:

1. Backup your current `.env` file
2. Update `.env` with Keycloak configuration
3. Update user whitelist in `dtaas/conf` to use Keycloak usernames/emails
4. Test with a single user before migrating all users

## References

- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [Traefik Forward Auth](https://github.com/thomseddon/traefik-forward-auth)
- [OIDC Specification](https://openid.net/specs/openid-connect-core-1_0.html)
