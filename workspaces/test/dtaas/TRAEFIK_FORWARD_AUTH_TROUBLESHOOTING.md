# Traefik Forward-Auth Troubleshooting Guide

## Quick Fix (TLS Stack with mkcert)

If `traefik-forward-auth` is crashing with `x509: certificate signed by unknown authority`:

```bash
# 1. Build the local forward-auth image with injected root CA
docker build -t traefik-forward-auth-local:latest workspaces/test/dtaas/certs

# 2. Recreate the forward-auth container
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env \
  up -d --force-recreate --no-deps traefik-forward-auth

# 3. Verify it's running (should show "Up" without "Restarting")
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env ps traefik-forward-auth

# 4. Check logs for "Listening on :4181" (success) or errors
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env logs --tail 30 traefik-forward-auth
```

## Root Cause Analysis

### Symptom 1: "connection refused" on port 443
**Non-TLS stack** (`compose.traefik.secure.yml`):
- Only exposes port 80; Traefik has no TLS listener
- When `.env` sets `KEYCLOAK_ISSUER_URL=https://...`, forward-auth tries to reach port 443 and fails
- **Fix**: Use HTTP issuer URL in non-TLS compose OR switch to TLS compose for HTTPS

### Symptom 2: "x509: certificate signed by unknown authority"
**TLS stack** (`compose.traefik.secure.tls.yml`):
- Traefik serves HTTPS successfully with mkcert certificate
- Standard `thomseddon/traefik-forward-auth` image doesn't trust the self-signed mkcert CA
- Certificate works for browser (if CA imported) but fails inside container
- **Fix**: Use `traefik-forward-auth-local:latest` image that includes `rootCA.crt`

## Diagnostic Commands

### 1. Check service health
```bash
# See which containers are running/restarting
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env ps

# Example healthy output:
# dtaas-traefik-forward-auth-1   traefik-forward-auth-local:latest   Up 5 seconds
# dtaas-traefik-1                traefik:v3.6.4                      Up 5 seconds  0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```

### 2. Check forward-auth logs
```bash
# Last 60 lines (includes startup messages)
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env logs --tail 60 traefik-forward-auth

# Success indicator: "level=info msg="Listening on :4181""
# Failure indicator: "level=fatal msg="Get https://...: x509: certificate signed by unknown authority""
```

### 3. Verify certificate is loaded in Traefik
```bash
# Check if TLS config file and cert files exist inside Traefik
docker compose -f workspaces/test/dtaas/compose.traefik.secure.tls.yml \
  --env-file workspaces/test/dtaas/config/.env exec -T traefik \
  sh -lc "ls -l /etc/traefik-certs; cat /etc/traefik/tls.yml"

# Should show:
# -rwxrwxrwx    1 root     root           1586 ... fullchain.pem
# -rwxrwxrwx    1 root     root           1704 ... privkey.pem
# tls:
#   stores:
#     default:
#       defaultCertificate:
#         certFile: /etc/traefik-certs/fullchain.pem
#         keyFile: /etc/traefik-certs/privkey.pem
```

### 4. Test HTTPS endpoint from container
```bash
# Probe Keycloak OIDC endpoint from inside the network
docker run --rm --network dtaas-frontend curlimages/curl:8.7.1 \
  -vk https://shared.dtaas-digitaltwin.com/auth/realms/dtaas/.well-known/openid-configuration

# Success: HTTP/2 200 with JSON response
# Failure: "SSL certificate verify result: unable to get local issuer certificate"
```

## Configuration Checklist

### Before starting TLS stack
- [ ] Cert files exist: `workspaces/test/dtaas/certs/fullchain.pem` and `privkey.pem`
- [ ] Root CA exists: `workspaces/test/dtaas/certs/rootCA.crt` (for local image)
- [ ] Traefik TLS config: `workspaces/test/dtaas/dynamic/tls.yml` points to cert files
- [ ] `.env` file has `KEYCLOAK_ISSUER_URL=https://shared.dtaas-digitaltwin.com/auth/realms/dtaas`
- [ ] Docker image exists: verify with `docker image ls | grep traefik-forward-auth-local`

### Browser HTTPS issues
- **Chrome error**: `net::ERR_CERT_AUTHORITY_INVALID` + HSTS warning
  - Cause: mkcert root CA not imported into Windows trust store
  - **Solution 1** (for dev): Ignore in Chrome (advanced → Proceed) on first visit (records HSTS)
  - **Solution 2** (recommended): Import `rootCA.crt` into Windows:
    ```bash
    # From certs directory
    certutil -addstore root rootCA.crt
    # Restart Chrome after
    ```
  - **Solution 3**: Use a different browser (Firefox allows per-profile CA imports)

## Reference: Which Compose File to Use

| Use Case | File | Port 443 | Auth Image | Notes |
|----------|------|---------|------------|-------|
| **Development, HTTP only** | `compose.traefik.secure.yml` | No | Standard | Use HTTP issuer URL in env |
| **Development, with HTTPS** | `compose.traefik.secure.tls.yml` | Yes | `traefik-forward-auth-local:latest` | Requires building custom image |
| **Production** | Third-party TLS setup | Yes | Standard | Use real cert + real CA |

## Prevention: Update Compose File Comment

The YAML comment in `compose.traefik.secure.tls.yml` should remind developers:

```yaml
traefik-forward-auth:
  # IMPORTANT: Use traefik-forward-auth-local:latest (not thomseddon/traefik-forward-auth)
  # The local image includes rootCA.crt so OIDC issuer TLS verification succeeds.
  # Build it first: docker build -t traefik-forward-auth-local:latest workspaces/test/dtaas/certs
  image: traefik-forward-auth-local:latest
```

## Common Mistakes

1. **Forget to rebuild image**: Changed to local image in compose but didn't build → container won't start
2. **Wrong issuer URL for non-TLS**: Using HTTPS issuer in `compose.traefik.secure.yml` → port 443 refused
3. **Expect auto-TLS trust**: Self-signed certs never work cross-OS without explicit CA import or local image injection
4. **Run compose without .env**: Default values may not match your setup

---

**Generated**: April 1, 2026  
**Test Setup**: mkcert self-signed certificates + Docker Compose + Traefik v3.6.4
