# TLS Certificates Directory

This directory should contain your TLS certificates for HTTPS support.

## Required Files

Place your certificate files in this directory with the following structure:

```text
test/dtaas/certs/
├── fullchain.pem  # Full certificate chain
└── privkey.pem    # Private key
```

## Certificate Generation

### For Production

Obtain certificates from a Certificate Authority (CA) like:

- [Let's Encrypt](https://letsencrypt.org/) (Free, automated)
- [ZeroSSL](https://zerossl.com/) (Free)
- Commercial CA (Paid)

### For Testing/Development

Generate self-signed certificates, inject them into a local
version of the forward auth image, and update the compose file
to use the local image.
Disregard this directory's usual requirement of the presence of
the private key and full certificate chain.

(Ensure that your `/etc/hosts` file point your domain to 127.0.0.1)

#### ***Generate certificates***

From within the `test/dtaas/certs/` folder, replacing every instance of
`foo.com` with your domain:

```bash
wget https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-amd64
chmod 774 mkcert-v1.4.4-linux-amd64
sudo mv mkcert-v1.4.4-linux-amd64 /usr/local/bin/mkcert
whereis mkcert
mkcert -install
mkcert "foo.com" "localhost" "127.0.0.1" "::1"
mkcert "foo.com" "*.foo.com" "localhost" "127.0.0.1" "::1"
cp ~/.local/share/mkcert/rootCA.pem rootCA.crt
```

#### ***Build forward auth image with your certificate***

From within `test/dtaas/certs/`:

```bash
docker buildx build -t traefik-forward-auth-local:latest .
```

#### ***Update forward auth image name in compose file***

Update the `traefik-forward-auth` service definition in the
`compose.traefik.secure.tls.yml` file by replacing the line

```yaml
image: thomseddon/traefik-forward-auth:2.2.0
```

with

```yaml
image: traefik-forward-auth-local:latest
```

## Security Notes

⚠️ **Important Security Practices:**

- Never commit actual certificate files to version control
- Keep private keys secure and restrict file permissions
- Use strong encryption (RSA 2048+ bits or ECC)
- Rotate certificates before expiration
- For production, always use certificates from trusted CAs

## File Permissions

From within `test/dtaas/certs/`, set appropriate permissions for certificate files:

```bash
chmod 644 fullchain.pem
chmod 600 privkey.pem
```
