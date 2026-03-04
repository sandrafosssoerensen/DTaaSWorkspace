# Single-User Deployment

This guide explains how to use the workspace container
for single-user deployments.

## ❓ Prerequisites

✅ Docker Engine v27 or later  
✅ Sufficient system resources (at least 1GB RAM per workspace instance)  
✅ Port 80 available on your host machine

## 🗒️ Overview

The `compose.yml` file sets up **user1** workspace using
the workspace image.

## ⚙️ Initial Configuration

Please follow the steps in [`CONFIGURATION.md`](CONFIGURATION.md) for
the `compose.yml` composition before running the setup.

## 💪 Get Workspace Image

You can either use a pre-built image or build it locally.

### Option 1: Use Pre-built Image (Recommended)

Pull the latest image from GitHub Container Registry or Docker Hub:

```bash
# From GitHub Container Registry
docker pull ghcr.io/into-cps-association/workspace:latest
docker tag ghcr.io/into-cps-association/workspace:latest workspace:latest

# Or from Docker Hub
docker pull intocps/workspace:latest
docker tag intocps/workspace:latest workspace:latest
```

### Option 2: Build Locally

Build the workspace image, either with docker compose:

```bash
docker compose -f workspaces/test/dtaas/compose.yml build
```

Or using the standard build command:

```bash
docker build -t workspace:latest -f workspaces/Dockerfile.ubuntu.noble.gnome \
  ./workspaces
```

## :rocket: Start Services

To start all services for a single user:

```bash
# run the compose file without environment variables
docker compose -f workspaces/test/dtaas/compose.yml up -d

# run the compose file with environment variables
docker compose -f workspaces/test/dtaas/compose.yml \
  --env-file workspaces/test/dtaas/config/.env up -d
```

This will start the workspace of single user.

## :technologist: Accessing Workspace

Once all services are running, access the workspaces through Traefik:

- **VNC Desktop**: `http://localhost/user1/tools/vnc?path=user1%2Ftools%2Fvnc%2Fwebsockify`
- **VS Code**: `http://localhost/user1/tools/vscode`
- **Jupyter Notebook**: `http://localhost/user1`
- **Jupyter Lab**: `http://localhost/user1/lab`

### Service Discovery

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
`MAIN_USER` environment variable.

### Use of ENV file

If `.env` file is used for docker compose command, remember to:

- Change `user1` to `USERNAME1`
- Change `localhost` in URL to the `SERVER_DNS`

## 🛑 Stopping Services

To stop all services:

```bash
# run the compose file without environment variables
docker compose -f workspaces/test/dtaas/compose.yml down

# run the compose file with environment variables
docker compose -f workspaces/test/dtaas/compose.yml --env-file workspaces/test/dtaas/config/.env down
```

## :shield: Security Considerations

⚠️ **Important**: This configuration is designed for development and testing,
and should not be reconfigured to be exposed to the internet.

For setting up a composition that can be exposed to the internet, see [TRAEFIK_TLS.md](./TRAEFIK_TLS.md).
