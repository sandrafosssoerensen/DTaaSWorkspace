# Workspace with Traefik Forward Auth (OIDC/Keycloak Security)

This guide explains how to use the workspace container with Traefik reverse proxy
and OIDC authentication via Keycloak and traefik-forward-auth for secure
multi-user deployments in the DTaaS installation.

## ❓ Prerequisites

✅ Docker Engine v27 or later
✅ Sufficient system resources (at least 2GB RAM - includes Keycloak)  
✅ Port 80 available on your host machine  

## 🗒️ Overview

The `compose.traefik.secure.yml` file sets up:

- **Traefik** reverse proxy on port 80
- **Keycloak** identity provider with OIDC support
- **traefik-forward-auth** for OIDC authentication
- **client** - DTaaS web interface
- **user1** workspace using the workspace image
- **user2** workspace using the mltooling/ml-workspace-minimal image
- Two Docker networks: `dtaas-frontend` and `dtaas-users`

## ⚙️ Initial Configuration

Please follow the steps in [`CONFIGURATION.md`](CONFIGURATION.md)
for the `compose.traefik.secure.yml` composition AND the setup instructions
for Keycloak in [`KEYCLOAK_SETUP.md`](KEYCLOAK_SETUP.md) before building
the workspace and running the setup.

### Create Workspace Files

All the deployment options require user directories for
storing workspace files. These need to
be created for `USERNAME1` and `USERNAME2` set in
`workspaces/test/dtaas/config/.env` file.

```bash
# create required files
cp -R workspaces/test/dtaas/files/user1 workspaces/test/dtaas/files/<USERNAME1>
cp -R workspaces/test/dtaas/files/user1 workspaces/test/dtaas/files/<USERNAME2>
# set file permissions for use inside the container
sudo chown -R 1000:100 workspaces/test/dtaas/files
```

## :rocket: Start Services

To start all services (Traefik, Keycloak, auth, client, and workspaces):

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml --env-file workspaces/test/dtaas/config/.env up -d
```

This will:

1. Start the Traefik reverse proxy on port 80
2. Start Keycloak identity provider at `/auth`
3. Start traefik-forward-auth for OIDC authentication
4. Start the DTaaS web client interface
5. Start workspace instances for both users

**Note**: First-time startup may take a few minutes for Keycloak to initialize.

## :gear: Configure Keycloak

After starting the services, you need to configure Keycloak.
See [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) for detailed instructions.

Quick steps:

1. For non-`localhost` scenarios, **Disable SSL requirement** on
   the new realm (see below)
2. Access Keycloak at `http://<SERVER_DNS>/auth`
3. Login with admin credentials from `.env`
4. Create a realm named `dtaas` (or match your `KEYCLOAK_REALM`)
5. Create an OIDC client named `dtaas-workspace`
6. Create users in Keycloak
7. Update `.env` with the client secret
8. Restart services

### Disable Realm SSL Requirement (HTTP only)

Keycloak defaults all realms to `sslRequired=external`, which rejects HTTP
requests arriving from non-localhost addresses. Since this composition runs
over plain HTTP behind Traefik, you must disable the SSL requirement for
the **master** realm and any new realm you create.

Using the Keycloak CLI inside the container:

```bash
# Authenticate to the Keycloak admin CLI
docker exec dtaas-keycloak-1 /opt/keycloak/bin/kcadm.sh \
  config credentials --server http://localhost:8080/auth \
  --realm master --user <KEYCLOAK_ADMIN> --password <KEYCLOAK_ADMIN_PASSWORD>

# Disable SSL on the master realm
docker exec dtaas-keycloak-1 /opt/keycloak/bin/kcadm.sh \
  update realms/master -s sslRequired=NONE

# Disable SSL on the dtaas realm (after creating it)
docker exec dtaas-keycloak-1 /opt/keycloak/bin/kcadm.sh \
  update realms/dtaas -s sslRequired=NONE
```

Replace `<KEYCLOAK_ADMIN>` and `<KEYCLOAK_ADMIN_PASSWORD>` with the values
from your `.env` file.

Alternatively, you can do this via the Keycloak Admin Console:

1. Go to **Realm Settings** → **General**
2. Set **Require SSL** to **None**
3. Save. Repeat for each realm.

## :technologist: Accessing Workspaces

Once all services are running and Keycloak is configured, access them through Traefik at `http://localhost`.

### Initial Access

1. Navigate to `http://localhost` in your web browser
2. You will be redirected to Keycloak for authentication
3. Log in with a user you created in Keycloak
4. You will be redirected back to the DTaaS web interface

### Keycloak Admin Console

- **URL**: `http://localhost/auth`
- Access to manage users, roles, clients, and authentication settings
- Login with `KEYCLOAK_ADMIN` credentials from `.env`

### DTaaS Web Client

- **URL**: `http://localhost/`
- Access to the main DTaaS web interface (requires authentication)

### User1 Workspace (workspace)

All endpoints require authentication:

- **VNC Desktop**: `http://localhost/user1/tools/vnc?path=user1%2Ftools%2Fvnc%2Fwebsockify`
- **VS Code**: `http://localhost/user1/tools/vscode`
- **Jupyter Notebook**: `http://localhost/user1`
- **Jupyter Lab**: `http://localhost/user1/lab`

#### Service Discovery

The workspace provides a `/services` endpoint that returns a JSON list of
available services. This enables dynamic service discovery for frontend
applications.

**Example**: Get service list for user1

```bash
curl http://localhost/user1/services
```

**Response**:

```json
{
  "desktop": {
    "name": "Desktop",
    "description": "Virtual Desktop Environment",
    "endpoint": "tools/vnc?path=user1%2Ftools%2Fvnc%2Fwebsockify"
  },
  "vscode": {
    "name": "VS Code",
    "description": "VS Code IDE",
    "endpoint": "tools/vscode"
  },
  "notebook": {
    "name": "Jupyter Notebook",
    "description": "Jupyter Notebook",
    "endpoint": ""
  },
  "lab": {
    "name": "Jupyter Lab",
    "description": "Jupyter Lab IDE",
    "endpoint": "lab"
  }
}
```

The endpoint values are dynamically populated with the user's username from the
`MAIN_USER` environment variable. This variable corresponds to `USERNAME1` of
`.env` file.

### User2 Workspace (ml-workspace-minimal)

All endpoints require authentication:

- **VNC Desktop**: `http://localhost/user2/tools/vnc/?password=vncpassword`
- **VS Code**: `http://localhost/user2/tools/vscode/`
- **Jupyter Notebook**: `http://localhost/user2`
- **Jupyter Lab**: `http://localhost/user2/lab`

### Custom URL

Remember to change the following variables in URLs to the variable values
specified in `.env`:

- Change `user1` to `USERNAME1` value
- Change `user2` to `USERNAME2` value
- Change `localhost` in URL to the `SERVER_DNS` value

## 🛑 Stopping Services

To stop all services:

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
  --env-file workspaces/test/dtaas/config/.env down
```

## 🔧 Customization

### Adding More Users

To add additional workspace instances, add a new service in `compose.traefik.secure.yml`:

```yaml
  user3:
    image: workspace:latest
    restart: unless-stopped
    build:
      context: .
      dockerfile: ../Dockerfile.ubuntu.noble.gnome
    environment:
      - MAIN_USER=${USERNAME3:-user3}
    volumes:
      - ./files/user3:/workspace
      - ./files/common:/workspace/common
    shm_size: 512m
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.u3.entryPoints=web"
      - "traefik.http.routers.u3.rule=Host(`${SERVER_DNS}`) && PathPrefix(`/${USERNAME3:-user3}`)"
      - "traefik.http.routers.u3.middlewares=traefik-forward-auth"
    networks:
      - users
```

Add the desired `USERNAME3` variable in `.env`:

```bash
# Username Configuration
# These usernames will be used as path prefixes for user workspaces
# Example: http://localhost/user1, http://localhost/user2
USERNAME1=user1
USERNAME2=user2
USERNAME3=user3 # <--- replace "user3" with your desired username
```

And, setup the base structure of the persistent directories for the new user:

```bash
cp -r workspaces/test/dtaas/files/user1 workspaces/test/dtaas/files/user3
sudo chown -R 1000:100 workspaces/test/dtaas/files
```

### Using a Different OAuth Provider

traefik-forward-auth supports multiple OAuth providers including GitLab, Google, Okta, and generic OAuth2.

**To use GitLab instead of Keycloak:**

1. Update the traefik-forward-auth environment in `compose.traefik.secure.yml`:

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

2. Remove the `keycloak` service from the compose file
3. Configure GitLab OAuth application (see [CONFIGURATION.md](CONFIGURATION.md))
4. Update `.env` with GitLab OAuth credentials

See [traefik-forward-auth documentation][tfa-docs] for other providers.

[tfa-docs]: https://github.com/thomseddon/traefik-forward-auth

### Using External Keycloak

To use an external Keycloak instance instead of the embedded one:

1. Update `KEYCLOAK_ISSUER_URL` in `.env`:

   ```bash
   KEYCLOAK_ISSUER_URL=https://keycloak.example.com/auth/realms/dtaas
   ```

2. Remove the `keycloak` service from compose file (optional)
3. Configure the client in your external Keycloak
4. Update `.env` with client credentials

**Minimal changes required!**

## 🤖 Automated CI Testing

For automated CI testing with Dex OIDC (no real OAuth provider needed),
see the dedicated documentation in [`ci/README.md`](ci/README.md).

## :shield: Security Considerations

### Current Setup (Development/Testing)

⚠️ **Important**: This configuration is designed for development and testing
and uses some insecure settings:

- `INSECURE_COOKIE=true` - Allows cookies over HTTP
- Traefik API is exposed (`--api.insecure=true`)
- No TLS/HTTPS encryption
- Debug logging enabled

For setting up a composition that includes TLS/HTTPS, see [TRAEFIK_TLS.md](TRAEFIK_TLS.md).

## 🔍 Troubleshooting

### Keycloak "HTTPS Required" Error

If Keycloak displays "We are sorry... HTTPS required" when accessed via HTTP:

1. This is caused by the per-realm `sslRequired` setting (defaults to `external`),
   which rejects HTTP from non-localhost clients
2. Fix it by disabling SSL requirement on the affected realm(s) — see
   [Disable Realm SSL Requirement](#disable-realm-ssl-requirement-http-only) above
3. If you previously ran the TLS composition (`compose.traefik.secure.tls.yml`),
   the `keycloak-data` volume may retain old SSL settings. Remove it and restart:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
     --env-file workspaces/test/dtaas/config/.env down
   docker volume rm dtaas_keycloak-data
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
     --env-file workspaces/test/dtaas/config/.env up -d
   ```

   Then re-apply the SSL disable steps after Keycloak starts.

### Keycloak Not Accessible

1. Check Keycloak is running:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
     --env-file workspaces/test/dtaas/config/.env ps keycloak
   ```

2. Check Keycloak logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml \
     --env-file workspaces/test/dtaas/config/.env logs keycloak
   ```

3. Wait for Keycloak to fully start (first startup can take 1-2 minutes)

### Authentication Loop

If you're stuck in an authentication loop:

1. Clear browser cookies for localhost
2. Check that `OAUTH_SECRET` is set and consistent
3. Verify Keycloak client redirect URI matches `http://localhost/_oauth/*`
4. Check traefik-forward-auth logs for errors
5. Ensure `KEYCLOAK_ISSUER_URL` is correct

### Services Not Accessible

1. Check all services are running:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml ps
   ```

2. Check Traefik logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml logs traefik
   ```

3. Check traefik-forward-auth logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.yml logs traefik-forward-auth
   ```

### OIDC/OAuth Errors

If you see OIDC errors:

1. Verify all environment variables in `.env` are correct
2. Check Keycloak client settings (client ID, secret, redirect URIs)
3. Ensure Keycloak realm name matches `KEYCLOAK_REALM`
4. Verify client authentication is enabled in Keycloak
5. Check that the issuer URL is accessible from the traefik-forward-auth container

### "Invalid Client" Error

- Verify `KEYCLOAK_CLIENT_SECRET` matches the value in Keycloak
- Ensure client authentication is enabled in Keycloak client settings

## 📚 Additional Resources

- [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) - Detailed Keycloak setup guide
- [KEYCLOAK_MIGRATION.md](KEYCLOAK_MIGRATION.md) - Migration guide from GitLab OAuth
- [CONFIGURATION.md](CONFIGURATION.md) - General configuration guide
- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [traefik-forward-auth GitHub](https://github.com/thomseddon/traefik-forward-auth)
- [OIDC Specification](https://openid.net/specs/openid-connect-core-1_0.html)
- [DTaaS Documentation](https://github.com/INTO-CPS-Association/DTaaS)
