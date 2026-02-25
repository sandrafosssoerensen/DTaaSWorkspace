# ⚙️ DTaaS Configuration

This document outlines the configuration needed for the docker compose files.
Not all parts of the configuration are required by the compose files.
Here is a mapping of the sections needed for the configuration files. All sections assume that you are in the `workspaces/test/dtaas/` directory.

<<<<<<<< HEAD:workspaces/test/dtaas/CONFIGURATION.md
- `compose.traefik.yml`:
   - [Environment](#-environment)
   - [Usernames](#-usernames)
- `compose.traefik.secure.yml`: [Usernames](#-usernames),
  [server OAuth2](#server-oauth2-setup), [client OAuth2](#client-oauth2-setup),
  [env file](#configure-environment-variables)
- `compose.traefik.secure.tls.yml`: [usernames](#-usernames),
  [server OAuth2](#server-oauth2-setup), [client OAuth2](#client-oauth2-setup),
========
- `compose.traefik.yml`: [user directories](#-create-user-directories)
- `compose.traefik.secure.yml`: [user directories](#-create-user-directories),
  [Keycloak Setup](#-keycloak-authentication-setup-recommended), 
  [client OAuth2](#client-oauth2-setup),
  [env file](#configure-environment-variables)
- `compose.traefik.secure.tls.yml`:  [user directories](#-create-user-directories),
  [Keycloak Setup](#-keycloak-authentication-setup-recommended),
  [client OAuth2](#client-oauth2-setup),
>>>>>>>> upstream/keyclock-traefik-integration:OLD_CONF.md
  [traefik forward auth](#traefik-forward-auth-configuration),
  [env file](#configure-environment-variables)

## 🌍 Environment

The compose commands used in the setup guides sets the environment with an environment file. An example of this file can be found at [`config/.env.example`](./config/.env.example).

<<<<<<<< HEAD:workspaces/test/dtaas/CONFIGURATION.md
Create a copy of this example file without the example suffix:

```bash
cp config/.env.example config/.env
```

## 👥 Usernames

The usernames of the main users for the workspaces can be changed in the [environment variable file](#-environment) `config/.env`. Change the default values (`user1` and `user2`) to your desired usernames:

```bash
# Username Configuration
# These usernames will be used as path prefixes for user workspaces
# Example: http://localhost/user1, http://localhost/user2
USERNAME1=user1
USERNAME2=user2
```
## 🔑 OAuth2 Configuration with GitLab
========
## 🔑 Authentication Setup
>>>>>>>> upstream/keyclock-traefik-integration:OLD_CONF.md

### 🎯 Keycloak Authentication Setup (Recommended)

The default configuration for `compose.traefik.secure.yml` now uses **Keycloak** 
for authentication via OIDC (OpenID Connect). Keycloak provides a robust, 
enterprise-grade identity and access management solution.

**For detailed Keycloak setup instructions, see [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md)**

Quick overview:
1. Start services with `docker compose -f compose.traefik.secure.yml up -d`
2. Access Keycloak at `http://localhost/auth`
3. Create a realm and OIDC client
4. Create users in Keycloak
5. Update `.env` with client credentials

### 🔄 GitLab OAuth2 Configuration (Legacy/Alternative)

If you prefer to use GitLab instead of Keycloak, you can modify the 
`traefik-forward-auth` service configuration in the compose file.

#### Server OAuth2 Setup

This setup uses traefik-forward-auth with OAuth2 for authentication. You'll
need to configure an OAuth2 application with your provider.

1. Go to your GitLab instance → Edit Profile Settings → Applications
2. Create a new application with:
   - **Name**: DTaaS Workspace
   - **Redirect URI**: `https://yourdomain.com/_oauth`
   - **Scopes**: `read_user`
3. Save the **Application ID** and **Secret**

These values are used later in `dtaas/.env` file.

### Client OAuth2 Setup

In addition, the DTaaS web client uses OAuth2 authorization as well.
It needs a client application.

1. Go to your GitLab instance → Edit Profile Settings → Applications
2. Create a new OAuth App with:
   - **Application name**: DTaaS Workspace
   - **Homepage URL**: `https://yourdomain.com`
   - **Authorization callback URL**: `https://yourdomain.com/Library`
   - **Scopes**: `openid`, `profile`, `read_user`, `read_repository`, `api`
3. Save the **Client ID**

Create and update the DTaaS web client configuration.

```bash
cp config/client.js.example config/client.js
```

Update the `REACT_APP_CLIENT_ID` with the **Client ID** generated above
and `REACT_APP_AUTH_AUTHORITY` with URL of your GitLab instance, for example
`https://gitlab.com`.

### Configure Environment Variables

1. Copy the example environment file:

   ```bash
   cp dtaas/.env.example dtaas/.env
   ```

2. **For Keycloak (default)**, edit `dtaas/.env` and fill in your Keycloak credentials:

   ```bash
   # Keycloak Admin Credentials
   KEYCLOAK_ADMIN=admin
   KEYCLOAK_ADMIN_PASSWORD=changeme

   # Keycloak Realm
   KEYCLOAK_REALM=dtaas

   # Keycloak Client Credentials (obtain from Keycloak after creating client)
   KEYCLOAK_CLIENT_ID=dtaas-workspace
   KEYCLOAK_CLIENT_SECRET=your_client_secret_here

   # Keycloak Issuer URL
   KEYCLOAK_ISSUER_URL=http://keycloak:8080/auth/realms/dtaas

   # Secret key for encrypting OAuth session data
   # Generate a random string (at least 16 characters)
   OAUTH_SECRET=$(openssl rand -base64 32)
   ```

   **For GitLab OAuth (alternative)**, edit `dtaas/.env`:

   ```bash
   # Your GitLab instance URL (without trailing slash)
   # Example: https://gitlab.com or https://gitlab.example.com
   OAUTH_URL=https://gitlab.com

   # OAuth Application Client ID
   # Obtained when creating the OAuth application in GitLab
   OAUTH_CLIENT_ID=your_application_id_here

   # OAuth Application Client Secret
   # Obtained when creating the OAuth application in GitLab
   OAUTH_CLIENT_SECRET=your_secret_here

   # Secret key for encrypting OAuth session data
   # Generate a random string (at least 16 characters)
   # Example: openssl rand -base64 32
   OAUTH_SECRET=your_random_secret_key_here
   ```

3. Generate a secure random secret:

   ```bash
   openssl rand -base64 32
   ```

   Use the output as your `OAUTH_SECRET` value.

4. (OPTIONAL) Update the USERNAME variables in .env, replacing the defaults with
   your desired usernames.

   ```bash
   # Username Configuration
   # These usernames will be used as path prefixes for user workspaces
   # Example: http://localhost/user1, http://localhost/user2
   USERNAME1=user1
   USERNAME2=user2
   ```

### 🚪 Traefik Forward Auth Configuration

The `dtaas/conf.example` contains example configuration for forward-auth service.
Copy it and update it with the chosen usernames and their email addresses.

```txt
rule.user1_access.action=auth
rule.user1_access.rule=PathPrefix(`/user1`)
rule.user1_access.whitelist = user1@localhost

rule.user2_access.action=auth
rule.user2_access.rule=PathPrefix(`/user2`)
rule.user2_access.whitelist = user2@localhost
```
