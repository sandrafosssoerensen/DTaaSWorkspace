# Workspace with Traefik, Oathkeeper, and TLS

This guide explains how to deploy the workspace container with Traefik reverse
proxy, Oathkeeper JWT/OPA authorization, and TLS/HTTPS support for secure multi-user
deployments.

## ❓ Prerequisites

✅ Docker Engine v27 or later  
✅ Docker Compose v2.x  
✅ Sufficient system resources (at least 1GB RAM per workspace instance)  
✅ Valid TLS certificates (production) or self-signed certs (testing)
✅ OAuth2 provider (GitLab, GitHub, Google, etc.)  
✅ Domain name pointing to your server (production) or localhost (testing)

## 🗒️ Overview

The `compose.traefik.secure.tls.yml` file provides a production-ready setup with:

- **Traefik** reverse proxy with TLS termination (ports 80, 443) and HTTP→HTTPS redirect
- **Keycloak** identity provider with OIDC/PKCE support
- **Ory Oathkeeper** for JWT verification and auth decisioning
- **opa-proxy** nginx adapter that converts OPA's 404 deny response to 403
- **OPA** for RBAC path authorization (roles: `dtaas-admin`, `dtaas-user`, `dtaas-viewer`)
- **user1**, **user2**, **admin** workspaces behind authentication
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

Notes:

- This is a one-time setup per username. You do not need to recreate these
  folders on every `docker compose down` / `up`.
- The per-user folder is bind-mounted to `/workspace`.
- For DTaaS private library paths, ensure each user folder contains
  `functions`, `models`, `tools`, `data`, and `digital_twins`.

## :rocket: Start Services

To start all services with TLS:

```bash
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml  --env-file workspaces/test/dtaas/config/.env up -d
```

This will:

1. Start Traefik reverse proxy with TLS on ports 80 (HTTP → HTTPS redirect)
   and 443 (HTTPS)
2. Start Oathkeeper and OPA authorization services
3. Start workspace instances for user1 and user2, protected by
   authentication

## :technologist: Accessing Workspaces

Once all services are running, access the workspaces through Traefik with HTTPS:

### User1 Workspace (workspace)

- **VNC Desktop**: `https://yourdomain.com/user1/tools/vnc?path=user1%2Ftools%2Fvnc%2Fwebsockify`
- **VS Code**: `https://yourdomain.com/user1/tools/vscode`
- **Jupyter Notebook**: `https://yourdomain.com/user1`
- **Jupyter Lab**: `https://yourdomain.com/user1/lab`

#### Service Discovery

The workspace provides a `/services` endpoint that returns a JSON list of
available services. This enables dynamic service discovery for frontend
applications.

**Example**: Get service list for user1

```bash
curl https://yourdomain.com/user1/services
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

- **VNC Desktop**: `https://yourdomain.com/user2/tools/vnc/?password=vncpassword`
- **VS Code**: `https://yourdomain.com/user2/tools/vscode/`
- **Jupyter Notebook**: `https://yourdomain.com/user2`
- **Jupyter Lab**: `https://yourdomain.com/user2/lab`

### Traefik Dashboard

- Dashboard is disabled by default in the hardened setup.
- To expose it securely:
  1. Set `TRAEFIK_DASHBOARD_USERS` in `config/.env` using an `htpasswd` bcrypt hash.
  2. Uncomment the dashboard labels in `compose.traefik.secure.tls.yml`.
  3. Access `https://yourdomain.com/dashboard/`.

## 🔒 Authorization Flow

1. Browser sends workspace request with `dtaas_access_token` cookie (set by the
   DTaaS React SPA after PKCE login).
2. Traefik forwards the request to Oathkeeper's ForwardAuth decision API.
3. Oathkeeper reads the JWT from the cookie; validates signature (RS256/384/512),
   issuer, audience, and expiry against Keycloak's JWKS endpoint.
4. Oathkeeper posts the request context to opa-proxy, which forwards it to OPA
   using the v0 data API (raw JSON input, no `{"input": ...}` wrapper).
5. OPA evaluates `policy.rego` (RBAC: role vs path match) and returns HTTP 200
   (allow) or HTTP 404 (undefined/deny).
6. opa-proxy passes through 200 and converts 404 → 403.
7. Oathkeeper receives 200 → allow (injects identity headers); 403 → 403 Forbidden
   to client.

## ✅ PKCE + Oathkeeper + OPA Verification Checklist

Run this checklist after deployment to confirm secure authentication and
authorization behavior.

1. Start the TLS stack:
  `docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml --env-file workspaces/test/dtaas/config/.env up -d`
2. Verify services are healthy:
  `docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml ps`
3. Verify login uses Keycloak PKCE flow in browser (no password grant from the client).
4. After login, confirm workspace access with own path succeeds:
  `https://<SERVER_DNS>/<USERNAME1>/`
5. Confirm cross-user access is denied:
  log in as `USERNAME1` and request `https://<SERVER_DNS>/<USERNAME2>/`
6. Validate JWT checks in Oathkeeper logs (issuer, signature, audience):
  `docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml logs oathkeeper`
7. Validate OPA authorization decisions and opa-proxy conversions:
  `docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml logs opa opa-proxy`
8. Confirm token claims include `preferred_username` and `roles` (realm roles array).
9. Ensure Traefik insecure API is not enabled in compose configuration.

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
      - "./files/user3:/workspace"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.u3.rule=Host(`${SERVER_DNS:-localhost}`) && PathPrefix(`/${USERNAME3:-user3}`)"
      - "traefik.http.routers.u3.tls=true"
      - "traefik.http.routers.u3.middlewares=oathkeeper-auth"
    networks:
      - users
```

Add the desired `USERNAME3` variable in [`.env`](./config/.env):

```bash
# Username Configuration
# These usernames will be used as path prefixes for user workspaces
# Example: http://localhost/user1, http://localhost/user2
USERNAME1=user1
USERNAME2=user2
USERNAME3=user3 # <--- replace "user3" with your desired username
```

Ensure the new user is assigned one of the DTaaS realm roles in Keycloak
(`dtaas-admin`, `dtaas-user`, or `dtaas-viewer`). The OPA policy in
[`policy.rego`](./oathkeeper/policy.rego) grants access based on the `roles`
JWT claim — no policy edits are needed when adding users.

Don't forget to create the user's directory:

```bash
cp -r ./workspaces/test/dtaas/files/user1 ./workspaces/test/dtaas/files/user3
sudo chown -R 1000:100 workspaces/test/dtaas/files
```

### Using Different Identity Providers

To use another OIDC-compatible provider, update Oathkeeper environment values
for JWKS URL, trusted issuer, and target audience in the compose file.

## 🐛 Troubleshooting

### Certificate Issues

**Problem**: "NET::ERR_CERT_INVALID" in browser

**Solutions**:

- Verify certificate files exist in `./certs/` directory
- Check certificate file permissions
- Ensure `dynamic/tls.yml` correctly references certificate paths
- For self-signed certs, add security exception in browser

### Oathkeeper/OPA Issues

**Problem**: Authorized user still gets access denied

**Solutions**:

- Verify the `dtaas_access_token` cookie is being sent (set by the DTaaS SPA after login)
- Check `KEYCLOAK_ISSUER_URL`, `KEYCLOAK_JWKS_URL`, and `KEYCLOAK_TARGET_AUDIENCE`
- Verify the token contains `preferred_username` and `roles` (run `configure_keycloak_rest.py` if mappers are missing)
- Check OPA policy decisions: `docker compose logs opa`
- Check opa-proxy status conversions: `docker compose logs opa-proxy`
- Check Oathkeeper decisions: `docker compose logs oathkeeper`

### Service Access Issues

**Problem**: Cannot access workspace after authentication

**Solutions**:

- Check service health:
  `docker compose -f compose.traefik.secure.tls.yml ps`
- View logs: `docker compose -f compose.traefik.secure.tls.yml logs`
- Verify Traefik routes:
  `docker compose -f compose.traefik.secure.tls.yml logs traefik`
- Test Oathkeeper/OPA services:
  `docker compose -f compose.traefik.secure.tls.yml logs oathkeeper opa-proxy opa`

### Port Conflicts

**Problem**: Ports 80 or 443 already in use

**Solutions**:

- Check for other services: `sudo netstat -tlnp | grep -E ':(80|443)'`
- Stop conflicting services
- Or modify port mappings in compose file (not recommended for production)

## 📚 Additional Resources

- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Ory Oathkeeper Documentation](https://www.ory.sh/docs/oathkeeper/)
- [Open Policy Agent Documentation](https://www.openpolicyagent.org/docs/latest/)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [OAuth 2.0 Specification](https://oauth.net/2/)

## 🔄 Alternative Configurations

### HTTP-Only with Oathkeeper (Development)

For development environments where TLS is not required, see [`TRAEFIK_SECURE.md`](TRAEFIK_SECURE.md).

This provides Oathkeeper/OPA authorization without TLS encryption.

### Basic Traefik (No Auth, No TLS)

For local development without authentication or encryption, see [`TRAEFIK.md`](TRAEFIK.md).

### Standalone Workspace (Single User)

For single-user local development, use:

```bash
docker compose -f workspaces/test/dtaas/compose.yml up -d
```
