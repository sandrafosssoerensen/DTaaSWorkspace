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

Please see [Configuration](CONFIGURATION.md) for information on
configuring the application setup specified in the compose file.

## 🔐 TLS Certificate Setup

### Option 1: Production Certificates (Recommended)

For production, obtain certificates from a trusted Certificate Authority:

#### Using Let's Encrypt with Certbot

```bash
# Install certbot
sudo apt-get update
sudo apt-get install certbot

# Generate certificates
sudo certbot certonly --standalone -d yourdomain.com

# Copy certificates to the project
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ./certs/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ./certs/
sudo chown $USER:$USER ./certs/*.pem
chmod 644 ./certs/fullchain.pem
chmod 600 ./certs/privkey.pem
```

### Option 2: Self-Signed Certificates (Testing Only, Local Only)

For local development and testing, generate self-signed certificates.
See `certs/README.md`, section "Certificate Generation" subsection
"For Testing/Development" for the steps.

⚠️ **Note**: Self-signed certificates will show security warnings in browsers
and should only be used for testing.

## 💻 (Local Domain Redirection)

If you are testing and/or developing locally, ensure that
`yourdomain.com` points to your local machine by adding the
following line to `/etc/hosts`:

```bash
127.0.0.1 yourdomain.com
```

## 💪 Build Workspace Image

Before starting the services, build the workspace image:

```bash
docker compose -f compose.traefik.secure.tls.yml  --env-file dtaas/.env build user1
```

Or use the standard build command:

```bash
docker build -t workspace:latest -f Dockerfile .
```

## :rocket: Start Services

To start all services with TLS:

```bash
docker compose -f compose.traefik.secure.tls.yml  --env-file dtaas/.env up -d
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
docker compose -f compose.traefik.secure.tls.yml  --env-file dtaas/.env down
```

To stop and remove volumes:

```bash
docker compose -f compose.traefik.secure.tls.yml  --env-file dtaas/.env down -v
```

## ⚙️ Network Configuration

The setup uses two Docker networks:

- **dtaas-frontend**: Used by Traefik and traefik-forward-auth for external communication
- **dtaas-users**: Shared network for workspace instances

This separation provides better network isolation and security.

## 🔧 Customization

### Adding More Users

To add additional workspace instances, add a new service in `compose.traefik.secure.tls.yml`:

```yaml
user3:
  image: workspace:latest
  restart: unless-stopped
  environment:
    - MAIN_USER=user3
  volumes:
    - ./persistent_dir/user3:/workspace
    - ./persistent_dir/common:/workspace/common
  shm_size: 512m
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.u3.entryPoints=websecure"
    - "traefik.http.routers.u3.rule=Host(`${SERVER_DNS:-localhost}`) && PathPrefix(`/user3`)"
    - "traefik.http.routers.u3.tls=true"
    - "traefik.http.routers.u3.middlewares=traefik-forward-auth"
  networks:
    - users
```

Don't forget to create the user's directory:

```bash
mkdir -p persistent_dir/user3
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

## :shield: Security Best Practices

### TLS Configuration

✅ Use certificates from trusted Certificate Authorities for production  
✅ Keep private keys secure with proper file permissions (600)  
✅ Rotate certificates before expiration  
✅ Use strong key sizes (RSA 2048+ bits or ECC)  
✅ Enable HSTS (HTTP Strict Transport Security) for production

### OAuth2 Configuration

✅ Use strong, random secrets for `OAUTH_SECRET`  
✅ Rotate OAuth2 secrets periodically  
✅ Limit OAuth2 application scopes to minimum required  
✅ Use environment variables for sensitive configuration  
✅ Never commit `.env` files to version control

### Network Security

✅ Use Docker networks to isolate services  
✅ Don't expose internal services directly  
✅ Configure firewall rules to limit access  
✅ Enable Docker socket protection  
✅ Regularly update Docker images

### Container Security

✅ Run containers as non-root users when possible  
✅ Set resource limits (CPU, memory) for containers  
✅ Use read-only volumes where appropriate  
✅ Scan images for vulnerabilities regularly  
✅ Keep base images and dependencies updated

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

For development environments where TLS is not required, use:

```bash
docker compose -f compose.traefik.secure.yml  --env-file dtaas/.env up -d
```

This provides OAuth2 authentication without TLS encryption.

### Basic Traefik (No Auth, No TLS)

For local development without authentication or encryption, use:

```bash
docker compose -f compose.traefik.yml  --env-file dtaas/.env up -d
```

### Standalone Workspace (Single User)

For single-user local development, use:

```bash
docker compose -f compose.yml up -d
```
