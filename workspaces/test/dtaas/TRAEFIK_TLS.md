# Workspace with Traefik, Keycloak, and TLS

This guide explains how to deploy the workspace container with Traefik reverse
proxy, OIDC/OAuth2 authentication using Keycloak, and TLS/HTTPS support for
secure multi-user deployments.

## ❓ Prerequisites

✅ Docker Engine v27 or later  
✅ Docker Compose v2.x  
✅ Ports 80 and 443 available on your host machine  
✅ At least 2GB RAM (includes Keycloak, Oathkeeper, and workspaces)  
✅ Valid TLS certificates (production) or self-signed certs (testing)  
✅ A domain name pointing to your server  

## 🗒️ Overview

The `compose.traefik.secure.tls.yml` file provides a production-ready setup with:

- **Traefik** — reverse proxy with TLS termination (port 80 redirects to HTTPS,
  port 443 serves HTTPS)
- **Keycloak** — embedded identity provider (OIDC)
- **Oathkeeper** — JWT proxy; validates tokens and forwards authenticated
  requests to workspaces
- **login-relay** — lightweight login relay service; initiates the Keycloak
  authorization code flow and sets the `dtaas_access_token` cookie after
  successful authentication
- **client** — DTaaS web interface
- **user1** workspace using the workspace image
- **user2** workspace using the mltooling/ml-workspace-minimal image
- **Two Docker networks**: `dtaas-frontend` and `dtaas-users`

## ⚙️ Initial Configuration

Please follow the steps in [`CONFIGURATION.md`](CONFIGURATION.md) for the `compose.traefik.secure.tls.yml` composition before building the workspace and running the setup.

## Create Workspace Files

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

To start all services with TLS:

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml  --env-file workspaces/test/dtaas/config/.env up -d
```

This will:

1. Start the Traefik reverse proxy with TLS (port 80 → 443 redirect,
   port 443 HTTPS)
2. Start Keycloak identity provider at `/auth`
3. Start Oathkeeper JWT proxy (validates tokens, routes workspace traffic)
4. Start the login-relay service at `/login-relay`
5. Start the DTaaS web client interface
6. Start workspace instances for both users

**Note**: First-time startup may take a few minutes for Keycloak to initialize.

## :gear: Configure Keycloak

After starting the services, configure Keycloak.
See [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) for full instructions, following the
**TLS / Oathkeeper** client setup section.

Quick steps:

1. Access Keycloak at `https://<SERVER_DNS>/auth`
2. Login with admin credentials from `.env`
3. Create a realm named `dtaas` (or match your `KEYCLOAK_REALM`)
4. Create a **confidential** OIDC client named `dtaas-workspace` with redirect
   URI `https://<SERVER_DNS>/login-relay/callback`
5. Copy the generated client secret and set `KEYCLOAK_CLIENT_SECRET` in `.env`
6. Add an **Audience mapper** to `dtaas-workspace-dedicated` scope with
   **Included Client Audience** set to `dtaas-workspace` (required for
   Oathkeeper JWT validation)
7. Create users in Keycloak matching `USERNAME1` and `USERNAME2` from `.env`
8. Restart the oathkeeper and login-relay services

## 🔒 Authentication Flow

1. User navigates to a workspace or SPA URL over HTTPS
2. Traefik routes the request to Oathkeeper (proxy port 4455)
3. Oathkeeper checks for a valid `dtaas_access_token` cookie (Keycloak JWT)
4. If no valid token: Oathkeeper redirects to
   `/login-relay?return_to=<original-url>`
5. login-relay generates a state nonce and redirects the browser to
   Keycloak login
6. User authenticates with Keycloak
7. Keycloak redirects to `/login-relay/callback` with an auth code
8. login-relay exchanges the code for a Keycloak JWT using the client secret
   (server-to-server)
9. login-relay sets the `dtaas_access_token` HttpOnly Secure cookie and
   redirects to the original URL
10. Oathkeeper validates the JWT, injects identity headers, and proxies
    the request to the workspace

The `dtaas_access_token` cookie expires after 5 minutes (matching Keycloak's
default access token lifetime). On expiry, Oathkeeper redirects silently to
login-relay, which re-authenticates using Keycloak's SSO session
(idle timeout: 30 minutes).

## :technologist: Accessing Workspaces

Once all services are running and Keycloak is configured, access them at
`https://<SERVER_DNS>`.

### Initial Access

1. Navigate to `https://<SERVER_DNS>` in your browser
2. You are redirected to Keycloak login
3. Log in with a user you created in Keycloak
4. You are redirected back to the DTaaS web interface

### Keycloak Admin Console

- **URL**: `https://<SERVER_DNS>/auth`
- Login with `KEYCLOAK_ADMIN` credentials from `.env`

### DTaaS Web Client

- **URL**: `https://<SERVER_DNS>/`

### User1 Workspace

All endpoints require authentication:

- **VNC Desktop**: `https://<SERVER_DNS>/user1/tools/vnc?path=user1%2Ftools%2Fvnc%2Fwebsockify`
- **VS Code**: `https://<SERVER_DNS>/user1/tools/vscode`
- **Jupyter Notebook**: `https://<SERVER_DNS>/user1`
- **Jupyter Lab**: `https://<SERVER_DNS>/user1/lab`

#### Service Discovery

The workspace provides a `/services` endpoint that returns a JSON list of
available services. This enables dynamic service discovery for frontend
applications.

**Example**: Get service list for user1

```bash
curl https://<SERVER_DNS>/user1/services
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

- **VNC Desktop**: `https://<SERVER_DNS>/user2/tools/vnc/?password=vncpassword`
- **VS Code**: `https://<SERVER_DNS>/user2/tools/vscode/`
- **Jupyter Notebook**: `https://<SERVER_DNS>/user2`
- **Jupyter Lab**: `https://<SERVER_DNS>/user2/lab`

## 🛑 Stopping Services

To stop all services:

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml  --env-file workspaces/test/dtaas/config/.env down
```

To stop and remove volumes:

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml  --env-file workspaces/test/dtaas/config/.env down -v
```

## 🔧 Customization

### Adding More Users

To add additional workspace instances, add a new service in `compose.traefik.secure.tls.yml`:

```yaml
  user3:
    image: workspace:latest
    restart: unless-stopped
    build:
      context: ../..
      dockerfile: Dockerfile.ubuntu.noble.gnome
    environment:
      - MAIN_USER=${USERNAME3:-user3}
    volumes:
      - "./files/common:/workspace/common"
      - "./files/${USERNAME3:-user3}:/workspace"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.u3.entryPoints=web-secure"
      - "traefik.http.routers.u3.rule=Host(`${SERVER_DNS}`) && PathPrefix(`/${USERNAME3:-user3}`)"
      - "traefik.http.routers.u3.tls=true"
      - "traefik.http.routers.u3.service=oathkeeper-proxy@docker"
    networks:
      - users
```

Also add `USERNAME3=${USERNAME3:-user3}` to the `environment` section of both
the `oathkeeper` and `login-relay` services.

**2. Add an access rule in `oathkeeper/access-rules.yml`:**

```yaml
- id: dtaas-user3-workspace
  version: "v0.36.0-beta.1"
  description: >
    Requires a valid Keycloak JWT. Proxies to the user3 workspace container.
  match:
    url: "<^https?://[^/]*/user3(/.*)?$>"
    methods:
      - GET
      - HEAD
      - POST
      - PUT
      - PATCH
      - DELETE
      - OPTIONS
  upstream:
    url: http://user3:8080
  authenticators:
    - handler: jwt
      config:
        token_from:
          header: Authorization
    - handler: jwt
      config:
        token_from:
          cookie: dtaas_access_token
  authorizer:
    handler: allow
  mutators:
    - handler: header
```

Replace `user3` in the `url` regexp and `upstream.url` with the actual username.

**Note**: Oathkeeper v26 with `regexp` matching strategy requires that URL
patterns do not overlap. Verify no other rule's pattern matches the same URLs.

**3. Add `USERNAME3` to `.env`:**

```bash
USERNAME3=user3
```

**4. Create the user directory:**

```bash
cp -r ./workspaces/test/dtaas/files/user1 ./workspaces/test/dtaas/files/user3
sudo chown -R 1000:100 workspaces/test/dtaas/files
```

**5. Create the user in Keycloak** (see [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md)).

## 🐛 Troubleshooting

### Certificate Issues

**Problem**: "NET::ERR_CERT_INVALID" in browser

**Solutions**:

- Verify certificate files exist in `./certs/` directory
- Check certificate file permissions
- Ensure `dynamic/tls.yml` correctly references certificate paths
- For self-signed certs, add security exception in browser

### Authentication Loop

**Problem**: Redirected to login repeatedly after authenticating

**Solutions**:

1. Clear browser cookies for `<SERVER_DNS>`
2. Verify the Keycloak client **Valid redirect URIs** includes `https://<SERVER_DNS>/login-relay/callback`
3. Ensure `KEYCLOAK_CLIENT_ID` in `.env` matches the client ID in Keycloak
4. Confirm client authentication is **ON** in Keycloak (confidential client)
5. Verify `KEYCLOAK_CLIENT_SECRET` in `.env` matches the Keycloak credentials tab
6. Check login-relay logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
     --env-file workspaces/test/dtaas/config/.env logs login-relay
   ```

### Oathkeeper 500 — "Multiple Rules Matched"

**Problem**: HTTP 500 from Oathkeeper

**Solution**: Access rule URL patterns in `oathkeeper/access-rules.yml` must
not overlap. Each URL must match exactly one rule. Review all patterns for
ambiguity.

### Services Not Accessible

1. Check all services are running:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
     --env-file workspaces/test/dtaas/config/.env ps
   ```

2. Check Oathkeeper logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
     --env-file workspaces/test/dtaas/config/.env logs oathkeeper
   ```

3. Check login-relay logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
     --env-file workspaces/test/dtaas/config/.env logs login-relay
   ```

4. Check Traefik logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
     --env-file workspaces/test/dtaas/config/.env logs traefik
   ```

### Keycloak Not Accessible

1. Check Keycloak is running:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
     --env-file workspaces/test/dtaas/config/.env ps keycloak
   ```

2. Check Keycloak logs:

   ```bash
   docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
     --env-file workspaces/test/dtaas/config/.env logs keycloak
   ```

3. First startup can take 1–2 minutes.

### Port Conflicts

**Problem**: Ports 80 or 443 already in use

**Solutions**:

- Check for other services: `sudo netstat -tlnp | grep -E ':(80|443)'`
- Stop conflicting services
- Or modify port mappings in compose file (not recommended for production)

## 📚 Additional Resources

- [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) — Keycloak realm, client, and user setup
- [CONFIGURATION.md](CONFIGURATION.md) — General configuration guide
- [certs/README.md](certs/README.md) — TLS certificate setup
- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [Oathkeeper Documentation](https://www.ory.sh/docs/oathkeeper)

## 🔄 Alternative Configurations

### Using a Different Identity Provider (Google, GitLab, etc.)

login-relay is hardcoded to Keycloak's OIDC endpoints. To use an external
provider, configure it as a **Keycloak Identity Provider** — Keycloak acts
as a broker and users log in via the external provider through Keycloak.
See the [Keycloak Identity Providers documentation](https://www.keycloak.org/docs/latest/server_admin/#_identity_broker).

### HTTP-Only with Keycloak (Development)

For development environments where TLS is not required, see [`TRAEFIK_SECURE.md`](TRAEFIK_SECURE.md).

This provides Keycloak authentication without TLS encryption.

### Basic Traefik (No Auth, No TLS)

For local development without authentication or encryption, see [`TRAEFIK.md`](TRAEFIK.md).

### Standalone Workspace (Single User)

For single-user local development, use:

```bash
docker compose -f workspaces/test/dtaas/compose.yml up -d
```
