# ⚙️ DTaaS Configuration

This document outlines the configuration needed for the docker compose files.
Not all parts of the configuration are required by the compose files.
Here is a mapping of the sections needed for the configuration files. All sections
assume that you are in the `workspaces/test/dtaas/` directory.

- `compose.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
  - [User Directories](#-user-directories)
- `compose.traefik.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
  - [User Directories](#-user-directories)
- `compose.traefik.secure.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
  - [User Directories](#-user-directories)
  - [Domain](#-domain)
  - [Protocol - HTTP](#-http)
  - [Web Client](#️-dtaas-web-client-config)
  - [OAuth2](#-oauth2-configuration)
  - [Forward Auth](#-traefik-forward-auth-configuration)
- `compose.traefik.secure.tls.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
  - [User Directories](#-user-directories)
  - [Domain - Remote](#️-remote-testing)
  - [Protocol - HTTPS](#-https)
  - [Web Client](#️-dtaas-web-client-config)
  - [OAuth2](#-oauth2-configuration)
  - [Forward Auth](#-traefik-forward-auth-configuration)

## 🌍 Environment

The compose commands used in the setup guides sets the environment
with an environment file. An example of this file can be found at
[`config/.env.example`](./config/.env.example).

Create a copy of this example file without the example suffix:

```bash
cp config/.env.example config/.env
```

## 👥 Usernames

The usernames of the main users for the workspaces can be changed in
the [environment variable file](#-environment) `config/.env`.
Change the default values (`user1` and `user2`) to your desired usernames:

```bash
# Username Configuration
# These usernames will be used as path prefixes for user workspaces
# Example: http://localhost/user1, http://localhost/user2
USERNAME1=user1
USERNAME2=user2
```

**NOTE:** If the composition also needs forward auth, then these
usernames must match the names of the gitlab users used in the forward auth.

## 📁 User Directories

The compose files need user directories in `files`.
Copy existing `user1` directory and paste as two new directories
with usernames selected for your case. These usernames are mentioned as
`USERNAME1` and `USERNAME2` in the docker compose files.

## 🌐 Domain

Decide on whether you are testing locally or remotely.

### 🏠 Local testing

**NOTE:** `compose.traefik.secure.tls.yml` can **not** be tested locally.
Follow the steps in [Remote testing](#️-remote-testing) instead.

From now on whenever you see `<DOMAIN_NAME>` in this guide, replace it with `localhost`.

### ☁️ Remote testing

From now on whenever you see `<DOMAIN_NAME>` in this guide, replace it with
your remote machines domain name. (Ensure that you remote machine has
a domain name, and that it is accesible from the internet.)

Go to the [Environment file](./config/.env) and replace the current value of
the `SERVER_DNS` variable with your domain name:

```bash
# Server Configuration
# Replace with your domain name
SERVER_DNS=<DOMAIN_NAME>
```

## 🔗 Protocol

The protocol used in the further configuration is dependent on your composition:

### 🔓 HTTP

From now on, whenever you see `<PROTOCOL>` in this guide, replace it with `http`.

### 🔒 HTTPS

From now on, whenever you see `<PROTOCOL>` in this guide, replace it with `https`.

Then, make sure that you have valid TLS certifcates on the machine and
that they are properly located. The `fullchain.pem` and `privkey.pem`
secrets should be located in the [`certs/`](./certs/) directory.

There are multiple ways to setup of TLS certificates. If you are hosting on
a webserver, then you can use Certbot from Let's Encrypt:

```bash
# Install certbot
sudo apt-get update
sudo apt-get install certbot

# Generate certificates
sudo certbot certonly --standalone -d <DOMAIN_NAME>

# Copy certificates to the project
sudo cp /etc/letsencrypt/live/<DOMAIN_NAME>/fullchain.pem ./certs/
sudo cp /etc/letsencrypt/live/<DOMAIN_NAME>/privkey.pem ./certs/
sudo chown $USER:$USER ./certs/*.pem
chmod 644 ./certs/fullchain.pem
chmod 600 ./certs/privkey.pem
```

## 🖥️ DTaaS Web Client Config

The DTaaS Web Client can be configured with a small javascript file,
an example of which can be found at
[`config/client.js.example`](./config/client.js.example).

Create a copy of this example file without the example suffix:

```bash
cp config/client.js.example config/client.js
```

Then, edit the new DTaaS Web Client config file, updating the following values:

### 🔑🖥️ Client OAuth2 Setup

In addition, the DTaaS web client uses OAuth2 authorization as well.
It needs a client application.
The following steps explain creation of Client OAuth2 application
on a Gitlab installation.

1. Go to your GitLab instance → Edit Profile Settings → Applications
2. Create a new OAuth App with:
   - **Application name**: DTaaS Workspace
   - **Homepage URL**: `https://yourdomain.com`
   - **Authorization callback URL**: `https://yourdomain.com/Library`
   - **Scopes**: `openid`, `profile`, `read_user`, `read_repository`, `api`
3. Save the **Client ID**

Create and update the DTaaS web client configuration.

```bash
cp workspaces/test/dtaas/config/client.js.example \
  workspaces/test/dtaas/config/client.js
```

Update the `REACT_APP_CLIENT_ID` with the **Client ID** generated above
and `REACT_APP_AUTH_AUTHORITY` with URL of your GitLab instance, for example
`https://gitlab.com`.

## 🔑 OAuth2 Configuration

Both this composition and the contained DTaaS Web Client uses
OAuth2 for authentication. You'll need to configure an OAuth2 apllication
for each, with your OAuth2 provider. This guide assumes that you use
Gitlab as your provider; other providers are possible but are not covered
by this guide.

### 🎯 Keycloak Authentication Setup (Recommended)

The default configuration for `compose.traefik.secure.yml` and
`compose.traefik.secure.tls.yml` now use **Keycloak**
for authentication via OIDC (OpenID Connect). Keycloak provides a robust, 
enterprise-grade identity and access management solution.

**For detailed Keycloak setup instructions, see [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md)**

Quick overview:
1. Start services with `docker compose -f compose.traefik.secure.yml up -d`
2. Access Keycloak at either `http://localhost/auth` or `https://foo.com/auth`
3. Create a realm and OIDC client
4. Create users in Keycloak
5. Update `.env` with client credentials


#### Configure Environment Variables

1. **For Keycloak (default)**, edit `config/.env` and fill in your Keycloak credentials:

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
   # KEYCLOAK_ISSUER_URL=https://foo.com/auth/realms/dtaas
   KEYCLOAK_ISSUER_URL=http://keycloak:8080/auth/realms/dtaas

   # Secret key for encrypting OAuth session data
   # Generate a random string (at least 16 characters), for example:
   #   openssl rand -base64 32
   # Then paste the generated value here:
   OAUTH_SECRET=<RANDOM_SECRET>
   ```

### 🔄 GitLab OAuth2 Configuration (Legacy/Alternative)

If you prefer to use GitLab instead of Keycloak, you can modify the 
`traefik-forward-auth` service configuration in the compose file.

1. Go to your GitLab instance → Profile Settings → Applications
2. Create a new application with:
   - **Name**: DTaaS Workspace
   - **Redirect URI**: either `http://localhost/_oauth` or `https://yourdomain.com/_oauth`
   - **Confidential**: Ticked
   - **Scopes**: `read_user`, `read_email`

#### Configure Environment Variables

Update the environment file, [`config/.env`](config/.env),
   with the **Application ID** and **Secret**:

   ```bash
   ...
   # OAuth Application Client ID
   # Obtained when creating the OAuth application in GitLab
   OAUTH_CLIENT_ID=<APPLICATION_ID>

   # OAuth Application Client Secret
   # Obtained when creating the OAuth application in GitLab
   OAUTH_CLIENT_SECRET=<SECRET>
   ...
   ```

4. Generate a base 64, 32 byte random string:

   ```bash
   openssl rand -base64 32
   ```

   and update the environment file, [`config/.env`](./config/.env), with it:

   ```bash
   ...
   # Secret key for encrypting OAuth session data
   # Generate a random string (at least 16 characters)
   # Example: openssl rand -base64 32
   OAUTH_SECRET=<RANDOM_STRIN>
   ...
   ```

## 🚪 Traefik Forward Auth Configuration

The [`config/conf.example`](./config/conf.example) contains
example configuration for the forward-auth service.

Create a copy of this example file without the example suffix:

```bash
cp config/conf.example config/conf
```

Then update the configuration file with the usernames and emails of
the GitLab users that correspond to user 1 and 2 respectively.
(You must either have two seperate GitLab users, or skip the configuration of
one of the two users).

```txt
rule.user1_access.action=auth
rule.user1_access.rule=PathPrefix(`/<USERNAME_USER1>`)
rule.user1_access.whitelist = <EMAIL_USER1>

rule.user2_access.action=auth
rule.user2_access.rule=PathPrefix(`/<USERNAME_USER2>`)
rule.user2_access.whitelist = <EMAIL_USER2>
```

**NOTE:** Ensure that the usernames set in the
[Usernames configuration step](#-usernames) are the same as those set
in the Traefik Forward Auth configuration file.
