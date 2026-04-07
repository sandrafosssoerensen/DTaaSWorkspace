# Injects a local mkcert root CA into the thomseddon/traefik-forward-auth
# image so that HTTPS redirects through a self-signed certificate are
# validated instead of rejected.
#
# Build (from workspaces/test/dtaas/ci/):
#   docker build -t traefik-forward-auth-local:latest ./certs/

# Stage 1: prepare the updated CA bundle on Alpine
FROM alpine:3.21 AS cert-builder
# hadolint ignore=DL3018
RUN apk add --no-cache ca-certificates
COPY rootCA.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates

# Stage 2: copy updated bundle into the forward-auth image.
# NOTE: thomseddon/traefik-forward-auth:2.2.0 has a bug where it fails to
# process the /_oauth callback when that route is also protected by the
# traefik-forward-auth middleware ("self-middleware" issue). The
# fix-dont-require-self-middleware-test1 tag contains the patch for this.
# Track https://github.com/thomseddon/traefik-forward-auth for a stable
# release containing the fix before switching to a versioned tag.
FROM thomseddon/traefik-forward-auth:fix-dont-require-self-middleware-test1
COPY --from=cert-builder /etc/ssl/certs/ca-certificates.crt \
     /etc/ssl/certs/ca-certificates.crt

CMD ["traefik-forward-auth"]
