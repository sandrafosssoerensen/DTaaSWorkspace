# ⚙️ DTaaS Configuration

This document outlines the configuration needed for the docker compose files.
Not all parts of the configuration are required by the compose files.
Here is a mapping of the sections needed for the configuration files. All sections
assume that you are in the `workspaces/test/dtaas/` directory.

- `compose.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
- `compose.traefik.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
- `compose.traefik.secure.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
  - [Domain](#-domain)
  - [Protocol - HTTP](#-http)
  - [Web Client](#️-dtaas-web-client-config)
  - [OAuth2](#-oauth2-configuration-with-gitlab)
  - [Forward Auth](#-traefik-forward-auth-configuration)
- `compose.traefik.secure.tls.yml`:
  - [Environment](#-environment)
  - [Usernames](#-usernames)
  - [Domain - Remote](#️-remote-testing)
  - [Protocol - HTTPS](#-https)
  - [Web Client](#️-dtaas-web-client-config)
  - [OAuth2](#-oauth2-configuration-with-gitlab)
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

```js
if (typeof window !== 'undefined') {
  window.env = {
...
   REACT_APP_URL: '<PROTOCOL>://<DOMAIN_NAME>/',
...
   REACT_APP_REDIRECT_URI: '<PROTOCOL>://<DOMAIN_NAME>/Library',
...
  };
}
```

## 🔑 OAuth2 Configuration with GitLab

Both this composition and the contained DTaaS Web Client uses
OAuth2 for authentication. You'll need to configure an OAuth2 apllication
for each, with your OAuth2 provider. This guide assumes that you use
Gitlab as your provider; other providers are possible but are not covered
by this guide.

### 🔑🚪 Forward Auth OAuth2 setup

1. Go to your GitLab instance → Profile Settings → Applications
2. Create a new application with:
   - **Name**: DTaaS Workspace
   - **Redirect URI**: `<PROTOCOL>://<DOMAIN_NAME>/_oauth`
   - **Confidential**: Ticked
   - **Scopes**: `read_user`
3. Update the environment file, [`config/.env`](./config/.env),
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

### 🔑🖥️ DTaaS Web Client OAuth2 Setup

1. Go to your GitLab instance → Profile Settings → Applications
2. Create a new application with:
   - **Name**: DTaaS Web Client
   - **Redirect URI**: `<PROTOCOL>://<DOMAIN_NAME>/Library`
   - **Confidential**: **Un**ticked
   - **Scopes**: `api`, `read_user`, `read_repository`, `openid`, `profile`
3. Update the DTaaS Web Client config file, [`config/client.js`](./config/client.js),
   with the **Application ID**:

   ```js
   if (typeof window !== 'undefined') {
     window.env = {
   ...
      REACT_APP_CLIENT_ID: '<APPLICATION_ID>',
   ...
     };
   }
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
