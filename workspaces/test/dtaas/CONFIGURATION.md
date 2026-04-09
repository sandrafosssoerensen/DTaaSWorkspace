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

## 📁 User Directories

The compose files need user directories in `files`.
Copy existing `user1` directory and paste as two new directories
with usernames selected for your case. These usernames are mentioned as
`USERNAME1` and `USERNAME2` in the docker compose files.

Example:

```bash
cp -R workspaces/test/dtaas/files/user1 workspaces/test/dtaas/files/<USERNAME1>
cp -R workspaces/test/dtaas/files/user1 workspaces/test/dtaas/files/<USERNAME2>
```

Important:

- This is a one-time setup per username (unless you delete the folder).
- In multi-user compose files, `./files/<USERNAME>` is bind-mounted to `/workspace`.
- If private DTaaS library paths return Jupyter 404, verify these per-user
  subdirectories exist under `files/<USERNAME>`: `functions`, `models`, `tools`,
  `data`, `digital_twins`.

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

The DTaaS web client also uses OIDC directly and must point to the Keycloak
issuer. Use the Keycloak realm issuer URL:

- `https://<DOMAIN_NAME>/auth/realms/dtaas` for TLS deployments
- `http://<DOMAIN_NAME>/auth/realms/dtaas` for HTTP-only development

Configure a Keycloak OIDC client for the DTaaS web frontend with:

1. **Client ID**: `dtaas-workspace`
2. **Redirect URI**: `<PROTOCOL>://<DOMAIN_NAME>/Library`
3. **Post logout redirect URI**: `<PROTOCOL>://<DOMAIN_NAME>/`
4. **Standard flow** enabled
5. **PKCE** enabled if your DTaaS frontend requires public-client login

Update [`config/client.js`](./config/client.js) so these values match your realm:

- `REACT_APP_CLIENT_ID`: the Keycloak client ID
- `REACT_APP_AUTH_AUTHORITY`: the realm issuer URL
- `REACT_APP_REDIRECT_URI`: `<PROTOCOL>://<DOMAIN_NAME>/Library`
- `REACT_APP_LOGOUT_REDIRECT_URI`: `<PROTOCOL>://<DOMAIN_NAME>/`

## 🔑 OAuth2 Configuration

Both this composition and the contained DTaaS Web Client use OIDC for authentication
through Keycloak as the identity provider.

### 🎯 Keycloak Authentication Setup

The default configuration for `compose.traefik.secure.yml` and
`compose.traefik.secure.tls.yml` use **Keycloak**
for authentication via OIDC (OpenID Connect). Keycloak provides a robust, 
enterprise-grade identity and access management solution.

**For detailed Keycloak setup instructions, see [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md)**

Quick overview:
1. Start services with `docker compose -f compose.traefik.secure.yml up -d`
2. Access Keycloak at `http://localhost/auth`
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
   KEYCLOAK_ISSUER_URL=http://keycloak:8080/auth/realms/dtaas

   # Secret key for encrypting OAuth session data
   # Generate a random string (at least 16 characters)
   OAUTH_SECRET=$(openssl rand -base64 32)
   ```
