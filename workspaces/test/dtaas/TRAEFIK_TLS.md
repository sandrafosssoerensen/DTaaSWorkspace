# Workspace with Traefik, OAuth2, and TLS

This guide explains how to deploy the workspace container with Traefik reverse
proxy, OAuth2 authentication, and TLS/HTTPS support for secure multi-user
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

- **Traefik** reverse proxy with TLS termination (ports 80, 443)
- **Automatic HTTP to HTTPS redirect**
- **OAuth2 authentication** via traefik-forward-auth
- **Multiple workspace instances** (user1, user2) behind authentication
- **Secure communication** with TLS certificates
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

1. Start Traefik reverse proxy with TLS on ports 80 (HTTP → HTTPS redirect)
   and 443 (HTTPS)
2. Start traefik-forward-auth service for OAuth2 authentication
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

- **Dashboard**: `https://yourdomain.com/dashboard/` (requires authentication)

## 🔒 Authentication Flow

1. User attempts to access a workspace URL
2. Traefik forwards the request to traefik-forward-auth
3. If not authenticated, user is redirected to OAuth2 provider
4. User logs in with OAuth2 provider
5. Provider redirects back with authorization code
6. traefik-forward-auth exchanges code for token and creates session
7. User is redirected to original URL and gains access

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
      - "traefik.http.routers.u3.middlewares=traefik-forward-auth"
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

Add Forward Auth config for user3 in [`conf`](./config/conf):

```txt

rule.user3_access.action=auth
rule.user3_access.rule=PathPrefix(`/user3`)
rule.user3_access.whitelist = user3@localhost 
```

Ensure that the username and email correspond to the workspaces GitLab user.

Don't forget to create the user's directory:

```bash
cp -r ./workspaces/test/dtaas/files/user1 ./workspaces/test/dtaas/files/user3
```

### Using Different OAuth2 Providers

The configuration can be adapted for different OAuth2 providers by changing
the environment variables in the `traefik-forward-auth` service:

#### Google OAuth2

```yaml
environment:
  - DEFAULT_PROVIDER=google
  - PROVIDERS_GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
  - PROVIDERS_GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
  - SECRET=${OAUTH_SECRET}
```

#### Generic OIDC Provider

```yaml
environment:
  - DEFAULT_PROVIDER=oidc
  - PROVIDERS_OIDC_ISSUER_URL=https://your-oidc-provider.com
  - PROVIDERS_OIDC_CLIENT_ID=${OIDC_CLIENT_ID}
  - PROVIDERS_OIDC_CLIENT_SECRET=${OIDC_CLIENT_SECRET}
  - SECRET=${OAUTH_SECRET}
```

## 🐛 Troubleshooting

### Certificate Issues

**Problem**: "NET::ERR_CERT_INVALID" in browser

**Solutions**:

- Verify certificate files exist in `./certs/` directory
- Check certificate file permissions
- Ensure `dynamic/tls.yml` correctly references certificate paths
- For self-signed certs, add security exception in browser

### OAuth2 Issues

**Problem**: Redirect loop after OAuth2 login

**Solutions**:

- Verify OAuth2 callback URL matches `https://yourdomain.com/_oauth`
- Check `SERVER_DNS` environment variable is set correctly
- Ensure `COOKIE_DOMAIN` matches your domain
- Verify OAuth2 application is approved and active

### Service Access Issues

**Problem**: Cannot access workspace after authentication

**Solutions**:

- Check service health:
  `docker compose -f compose.traefik.secure.tls.yml ps`
- View logs: `docker compose -f compose.traefik.secure.tls.yml logs`
- Verify Traefik routes:
  `docker compose -f compose.traefik.secure.tls.yml logs traefik`
- Test OAuth2 service:
  `docker compose -f compose.traefik.secure.tls.yml logs traefik-forward-auth`

### Port Conflicts

**Problem**: Ports 80 or 443 already in use

**Solutions**:

- Check for other services: `sudo netstat -tlnp | grep -E ':(80|443)'`
- Stop conflicting services
- Or modify port mappings in compose file (not recommended for production)

## 📚 Additional Resources

- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Traefik Forward Auth](https://github.com/thomseddon/traefik-forward-auth)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [OAuth 2.0 Specification](https://oauth.net/2/)

## 🔄 Alternative Configurations

### HTTP-Only with OAuth2 (Development)

For development environments where TLS is not required, see [`TRAEFIK_SECURE.md`](./TRAEFIK_SECURE.md).

This provides OAuth2 authentication without TLS encryption.

### Basic Traefik (No Auth, No TLS)

For local development without authentication or encryption, see [`TRAEFIK.md`](./TRAEFIK.md).

### Standalone Workspace (Single User)

For single-user local development, use:

```bash
docker compose -f workspaces/test/dtaas/compose.yml up -d
```
