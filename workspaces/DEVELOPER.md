# Developer Documentation

This document provides comprehensive information about environment variables,
build arguments, and configuration options used in the workspace Docker image
and build process.

## Table of Contents

- [Docker Build Arguments](#docker-build-arguments)
- [Dockerfile Environment Variables](#dockerfile-environment-variables)
- [Runtime Environment Variables](#runtime-environment-variables)
- [Multi-Architecture Build](#multi-architecture-build)
- [Installation Scripts](#installation-scripts)
- [Startup Scripts](#startup-scripts)

## Docker Build Arguments

These arguments are used when building the Docker image. Some (`TARGETARCH`, `TARGETPLATFORM` and `BUILDPLATFORM`) are automatically provided by Docker Buildx during
multi-platform builds, while others (`INSTALLATION`) can be set manually, changing contents of the resulting image.

### INSTALLATION

- **Type**: Build ARG
- **Description**: Profile for installation of services.
- **Possible Values**: `full` or `minimal`
- **Default**: `full`
- **Usage**: Set it explicitly when building the image to change what services are installed:
`docker build -t workspace:latest -f workspaces/Dockerfile.ubuntu.noble.gnome --build-arg INSTALLATION=minimal ./workspaces`
- **Example**:

  ```dockerfile
  ARG INSTALLATION
  FROM kasmweb/core-ubuntu-noble:1.18.0 AS configure
  ...
  FROM configure AS install-full
  # Install and environment layers for all services
  ...
  FROM configure AS install-minimal
  # Install and environment layers for the minimal number of services
  # needed to run the image
  ...
  FROM install-${INSTALLATION} AS setup
  ```

### TARGETARCH

- **Type**: Build ARG
- **Description**: Target architecture for the build
- **Possible Values**: `amd64`, `arm64`, `arm`, `ppc64le`, `s390x`, etc.
- **Usage**: Automatically set by Docker Buildx when building with `--platform`
- **Example**:

  ```dockerfile
  ARG TARGETARCH
  RUN echo "Building for architecture: ${TARGETARCH}"
  ```

### TARGETPLATFORM

- **Type**: Build ARG
- **Description**: Target platform in the format `os/arch[/variant]`
- **Possible Values**: `linux/amd64`, `linux/arm64`, `linux/arm/v7`, etc.
- **Usage**: Automatically set by Docker Buildx when building with `--platform`
- **Example**:

  ```dockerfile
  ARG TARGETPLATFORM
  RUN echo "Building for platform: ${TARGETPLATFORM}"
  ```

### BUILDPLATFORM

- **Type**: Build ARG
- **Description**: Platform of the builder machine (not the target)
- **Possible Values**: `linux/amd64`, `linux/arm64`, etc.
- **Usage**: Useful for cross-compilation scenarios
- **Example**:

  ```dockerfile
  ARG BUILDPLATFORM
  RUN echo "Building on platform: ${BUILDPLATFORM}"
  ```

## Dockerfile Environment Variables

These environment variables are set in the Dockerfile and are available during
both build and runtime.

### Service Ports

#### ADMIN_SERVER_PORT

- **Default**: `8091`
- **Description**: Port for the Admin FastAPI service
- **Usage**: Admin service listens on this port for service discovery requests

#### CODE_SERVER_PORT

- **Default**: `8054`
- **Description**: Port for VS Code Server
- **Usage**: VS Code web interface is accessible on this port

#### JUPYTER_SERVER_PORT

- **Default**: `8090`
- **Description**: Port for Jupyter Server
- **Usage**: Jupyter Notebook/Lab interface is accessible on this port

### Directory Paths

#### HOME

- **Default**: `/home/kasm-default-profile`
- **Description**: Home directory for the default Kasm user
- **Usage**: Working directory for user sessions

#### INST_DIR

- **Default**: `${STARTUPDIR}/install`
- **Description**: Directory containing installation scripts
- **Usage**: Referenced during Docker build to install software components

#### ADMIN_DIR

- **Default**: `${STARTUPDIR}/admin`
- **Description**: Directory containing admin service files
- **Usage**: Location of the admin FastAPI application

#### PERSISTENT_DIR

- **Default**: `/workspace`
- **Description**: Directory for persistent data storage
- **Usage**: Mounted volume for user data that persists across container restarts

#### STARTUPDIR

- **Default**: `/dockerstartup` (inherited from base image)
- **Description**: Directory containing startup scripts
- **Usage**: Executed during container initialization

### Kasm VNC Configuration

#### VNCOPTIONS

- **Default**: `"${VNCOPTIONS} -disableBasicAuth"`
- **Description**: Additional VNC server options
- **Usage**: Disables basic authentication for VNC (auth handled by container)

#### KASM_SVC_AUDIO

- **Default**: `0`
- **Description**: Disable audio service
- **Usage**: Audio streaming is disabled by default

#### KASM_SVC_AUDIO_INPUT

- **Default**: `0`
- **Description**: Disable audio input service
- **Usage**: Audio input/microphone is disabled by default

#### KASM_SVC_UPLOADS

- **Default**: `0`
- **Description**: Disable file upload service
- **Usage**: File uploads through Kasm interface are disabled

#### KASM_SVC_GAMEPAD

- **Default**: `0`
- **Description**: Disable gamepad service
- **Usage**: Gamepad support is disabled by default

#### KASM_SVC_WEBCAM

- **Default**: `0`
- **Description**: Disable webcam service
- **Usage**: Webcam access is disabled by default

#### KASM_SVC_PRINTER

- **Default**: `0`
- **Description**: Disable printer service
- **Usage**: Printing functionality is disabled by default

#### KASM_SVC_SMARTCARD

- **Default**: `0`
- **Description**: Disable smartcard service
- **Usage**: Smartcard reader support is disabled by default

## Runtime Environment Variables

These variables can be set when running the container to customize its behavior.

### MAIN_USER

- **Type**: Runtime ENV
- **Default**: Not set in Dockerfile, typically set in compose files or docker run
- **Description**: Username for the workspace session
- **Usage**: Used by startup scripts to configure user-specific paths and services
- **Example**:

  ```bash
  docker run -e MAIN_USER=user1 workspace:latest
  ```

### NO_VNC_PORT

- **Type**: Runtime ENV (read from Kasm base image)
- **Default**: Inherited from base image
- **Description**: Port for noVNC web interface
- **Usage**: Used by nginx configuration to proxy VNC connections

### JUPYTER_DISABLED

- **Type**: Runtime ENV
- **Default**: `0` (Jupyter is **enabled** by default in the `full` build)
- **Description**: Controls whether Jupyter Server is started at container runtime
- **Possible Values**: `0` (start Jupyter), `1` (skip Jupyter)
- **Usage**: Set to `1` to disable Jupyter (automatically set to `1` in the
  `minimal` build via Dockerfile)
- **Example**:

  ```bash
  docker run -e JUPYTER_DISABLED=1 workspace:latest
  ```

### VSCODE_DISABLED

- **Type**: Runtime ENV
- **Default**: `0` (VS Code Server is **enabled** by default in the `full` build)
- **Description**: Controls whether VS Code Server is started at container runtime
- **Possible Values**: `0` (start VS Code Server), `1` (skip VS Code Server)
- **Usage**: Set to `1` to disable VS Code Server (automatically set to `1` in the
  `minimal` build via Dockerfile)
- **Example**:

  ```bash
  docker run -e VSCODE_DISABLED=1 workspace:latest
  ```

## Multi-Architecture Build

### Building for Multiple Architectures

The workspace image supports building for multiple processor architectures using
Docker Buildx:

```bash
# Create a builder instance (one-time setup)
docker buildx create --name multiarch --use

# Single-platform build and load into local Docker
docker build -t workspace:latest \
  -f workspaces/Dockerfile.ubuntu.noble.gnome \
  --build-arg INSTALLATION=minimal \
  ./workspaces

# Multi-platform build without loading or saving
# Build arg is optional
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t workspace:minimal-build \
  -f workspaces/Dockerfile.ubuntu.noble.gnome \
  --build-arg INSTALLATION=minimal \
  ./workspaces


# Multi-platform build -> push to registry
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t workspace:minimal-build \
  -f workspaces/Dockerfile.ubuntu.noble.gnome \
  --build-arg INSTALLATION=minimal \
  --push \
  ./workspaces

# Build each arch to Docker-format tar, then load (creates separate images locally)
# NOTE: use type=docker (not type=tar) so that docker load can read the archive.
docker buildx build \
  --platform linux/amd64 \
  -t workspace-amd64 \
  -f workspaces/Dockerfile.ubuntu.noble.gnome \
  --output type=docker,dest=./workspace-amd64.tar \
  ./workspaces

docker buildx build \
  --platform linux/arm64 \
  -t workspace-arm64 \
  -f workspaces/Dockerfile.ubuntu.noble.gnome \
  --output type=docker,dest=./workspace-arm64.tar \
  ./workspaces

docker load -i ./workspace-amd64.tar
docker load -i ./workspace-arm64.tar
```

### Architecture-Specific Considerations

When adding new software or scripts:

1. **Check architecture compatibility**: Ensure downloaded binaries support both
   amd64 and arm64
2. **Use `${TARGETARCH}` in downloads**: Many projects provide separate
   downloads per architecture
3. **Test on both architectures**: If possible, test builds on both platforms
4. **Use QEMU for testing**: You can test arm64 builds on amd64 using QEMU
   emulation

Example of architecture-aware installation:

```bash
#!/bin/bash
# Example: Download architecture-specific binary

ARCH="${TARGETARCH:-amd64}"  # Default to amd64 if not set
wget "https://example.com/download-${ARCH}.tar.gz"
```

## Installation Scripts

Installation scripts are located in `src/install/` and are executed during the
Docker build process.

### Script Environment

- **Working Directory**: `$HOME` (`/home/kasm-default-profile`)
- **User**: `root`
- **Available Variables**: All Dockerfile ENV variables plus ARG variables
- **Execution**: Scripts run in order specified in Dockerfile RUN instruction

### Best Practices for Installation Scripts

1. **Use bash shebang**: Start scripts with `#!/bin/bash`
2. **Set error handling**: Use `set -e` to exit on errors
3. **Clean up**: Remove temporary files and package caches
4. **Pin versions**: Specify exact versions for reproducible builds
5. **Handle architectures**: Use `${TARGETARCH}` when downloading binaries

### Example Installation Script

```bash
#!/bin/bash
set -e

# Get architecture (defaults to amd64 if not in Docker build)
ARCH="${TARGETARCH:-amd64}"

# Install package
VERSION="1.2.3"
wget "https://example.com/package-${VERSION}-${ARCH}.deb"
apt-get install -y ./package-${VERSION}-${ARCH}.deb
rm ./package-${VERSION}-${ARCH}.deb

# Clean up
apt-get clean
rm -rf /var/lib/apt/lists/*
```

### Real-World Examples

#### VSCode Server Installation

The VSCode installation script (`src/install/vscode/install_vscode_server.sh`) uses
TARGETARCH to download the correct architecture-specific package:

```bash
# Use TARGETARCH if available (set by Docker Buildx), otherwise detect architecture
ARCH="${TARGETARCH:-amd64}"

# code-server uses the same architecture naming as Docker (amd64/arm64)
fetch "https://github.com/coder/code-server/releases/download/v${VERSION}/code-server_${VERSION}_${ARCH}.deb" \
    "${CACHE_DIR}/code-server_${VERSION}_${ARCH}.deb"
```

#### Firefox Installation

The Firefox installation script (`src/install/firefox/install_firefox.sh`) demonstrates
a simplified approach to convert architecture names to GNU triplet format:

```bash
# Prefer TARGETARCH (set by Docker Buildx); fallback to system uname -m
# Convert to GNU triplet format for library paths
src_arch="${TARGETARCH:-$(uname -m)}"

case "${src_arch}" in
  amd64|x86_64)
    GNU_ARCH="x86_64"
    ;;
  arm64|aarch64)
    GNU_ARCH="aarch64"
    ;;
  386)
    GNU_ARCH="i386"
    ;;
  *)
    GNU_ARCH="${src_arch}"
    ;;
esac

# Use GNU_ARCH for system library paths
ln /usr/lib/"${GNU_ARCH}"-linux-gnu/pkcs11/p11-kit-trust.so /usr/lib/firefox/libnssckbi.so
```

This approach handles both Docker architecture names (amd64/arm64) and system
architecture names (x86_64/aarch64) in a single case statement.

## Startup Scripts

Startup scripts are located in `src/startup/` and are executed when the
container starts.

### Startup Script Order

1. `dtaas_shim.sh` - First script that restores environment and switches to
   MAIN_USER
2. `kasm_default_profile.sh` - Base image startup (inherited)
3. `vnc_startup.sh` - VNC server initialization (inherited)
4. `custom_startup.sh` - Custom service initialization

### Available Variables at Startup

- All Dockerfile ENV variables
- Runtime environment variables (e.g., `MAIN_USER`)
- Restored variables from `/tmp/.docker_set_envs`

### dtaas_shim.sh

- **Purpose**: Environment restoration and user switching
- **Key Functions**:
  - Sources `/tmp/.docker_set_envs` to restore build-time environment
  - Switches execution to `MAIN_USER` using `su -m`
  - Continues startup chain

### custom_startup.sh

- **Purpose**: Start custom services
- **Key Functions**:
  - Configures nginx reverse proxy
  - Starts Jupyter Server on `$JUPYTER_SERVER_PORT` (unless `INSTALLATION=minimal`)
  - Starts VS Code Server on `$CODE_SERVER_PORT` (unless `INSTALLATION=minimal`)
  - Starts Admin service on `$ADMIN_SERVER_PORT`

### configure_nginx.py

- **Purpose**: Generate nginx configuration from template
- **Key Functions**:
  - Substitutes environment variables in `nginx.conf` template
  - Configures routing for all services
  - Handles path-based routing for multi-user deployments

## Environment Variable Precedence

1. **Runtime** (`docker run -e` or `compose.yml`): Highest priority, overrides
   all
2. **Dockerfile ENV**: Default values, can be overridden at runtime
3. **Dockerfile ARG**: Only available during build, not at runtime

## Debugging Environment Variables

### During Build

```bash
# Add to Dockerfile to inspect values during build
RUN env | sort
RUN echo "TARGETARCH=${TARGETARCH}"
RUN echo "TARGETPLATFORM=${TARGETPLATFORM}"
```

### During Runtime

```bash
# Exec into running container
docker exec -it <container> bash
env | sort

# Check specific variable
echo $MAIN_USER
echo $ADMIN_SERVER_PORT
```

### Check Restored Environment

```bash
# View environment variables saved during build
docker exec -it <container> cat /tmp/.docker_set_envs
```

## Adding New Environment Variables

When adding new environment variables:

1. **Document here**: Add entry to this file with description and default value
2. **Update Dockerfile**: Add to ENV instruction or use ARG for build-time only
3. **Update scripts**: Use the variable in relevant scripts
4. **Update compose files**: Set runtime values in compose.yml examples if needed
5. **Update documentation**: Update README.md if user-facing

## References

- [Docker ARG and ENV](https://docs.docker.com/engine/reference/builder/#arg)
- [Docker Multi-platform builds](https://docs.docker.com/build/building/multi-platform/)
- [Dockerfile best practices](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [Kasm Workspaces Documentation](https://kasmweb.com/docs/latest/index.html)
