# Purpose

The main changes made so far are listed here.

## 21-Jan-2026

* **Keycloak Integration**: Added Keycloak as the default identity provider for authentication
  * Replaced GitLab OAuth with OIDC-based authentication
  * New `keycloak` service in `compose.traefik.secure.yml`
  * Updated `traefik-forward-auth` to use OIDC provider
  * Added persistent volume for Keycloak data
* **Environment Configuration**: Updated `.env.example` with Keycloak-specific variables
  * Maintained backward compatibility with GitLab OAuth
  * Added comprehensive comments for both authentication methods
* **Documentation**: Created comprehensive setup and migration guides
  * [KEYCLOAK_SETUP.md](KEYCLOAK_SETUP.md) - Detailed Keycloak configuration
  * [KEYCLOAK_MIGRATION.md](KEYCLOAK_MIGRATION.md) - Migration guide from GitLab
  * Updated [CONFIGURATION.md](CONFIGURATION.md) to reference Keycloak
  * Updated [TRAEFIK_SECURE.md](TRAEFIK_SECURE.md) with Keycloak instructions
* **Flexibility**: Designed for minimal changes when moving Keycloak external
  * Environment variable based configuration
  * Easy to switch between internal and external Keycloak
  * Can still use GitLab OAuth with minor compose file modifications


## Week of 10-Feb-2026

### Added
* Admin service FastAPI application with `/services` endpoint for service discovery
* CLI interface for admin service (`workspace-admin` command) with options for listing services, host, port, and reload
* Comprehensive test suite for admin service with 84% coverage (14 tests)
* Detailed documentation (DOCUMENTATION.md and README.md) for admin service

### Changed
* Admin service installation changed from poetry run to wheel package + pipx installation
* Poetry installation now uses install.python-poetry.org installer with virtualenvs configured in-project

### Fixed
* ShellCheck issues in install_admin.sh (test syntax, variable bracing, error handling)
* Docker build path from `${INST_DIR}/../../admin` to `${INST_DIR}/../admin`
* Linting issues: removed whitespace, unused imports, fixed f-strings
* Type hints for FastAPI response endpoints
* Mistakes in workspace admin installation

## Week of 03-Feb-2026

### Changed
* Workspace Docker image now published to `intocps/workspace` registry

## Week of 20-Jan-2026

### Changed
* Docker labels moved from build stage to deploy stage in Dockerfile

## Week of 13-Jan-2026

### Added
* TLS/HTTPS support with OAuth2 authentication for production deployments
* New Docker compose files for TLS configuration
* Self-signed certificate generation support
* `.gitattributes` file specifying LF line endings for all non-binary files

### Changed
* Workspace name changed from `workspace-nouveau` to `workspace`
* GitHub Actions updated to reflect new image location
* Traefik-forward-auth version updated to fix endless redirect loop bug
* Consolidated environment file setup between OAuth2 and TLS features

### Fixed
* Docker image publish problems
* Regular user set for login user

## Week of 06-Jan-2026

### Added
* Automated Docker image publishing to GHCR and Docker Hub
* OCI labels to Dockerfile for better metadata
* PUBLISHING.md documentation for Docker image publishing workflow
* CLAUDE.md file for Claude code use

### Changed
* Main image name from "workspace-nouveau" to "workspace"

## Week of 16-Dec-2025

### Added
* Traefik reverse proxy integration for multi-user deployments
* OAuth2-secured multi-user deployment with traefik-forward-auth and DTaaS web client integration
* Strict linting enforcement in GitHub Actions workflows
* New project structure with dedicated DTaaS testing directory
* Configuration and certificates organization in dedicated DTaaS directory

### Fixed
* Resolved Copilot review comments from PR #10

### Changed
* Improved documentation for multi-user deployments

## 15-Dec-2025


* Adds both ml-workspace and workspace in one docker compose
  and puts them behind traefik proxy
* Based on the KASM core ubuntu image.
* Added VSCode service with [code-server](https://github.com/coder/code-server),
  is started by the [custom_startup.sh](/startup/custom_startup.sh) script.
* Jupyter is available.
* No longer need to authenticate when opening VNC Desktop.
* User is now a sudoer, can install debian packages, and user password
  can be set at container instantiation (via the environment variable USER_PW).
* All access to services is over http (VNC https is hidden behind reverse proxy).
* Reverse proxy exists, and VNC's websocket is forced to adchere to path structure with 'path' argument as path of http request.
* Still need to get image under 500 MB.
