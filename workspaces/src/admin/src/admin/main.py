"""
FastAPI application for workspace service discovery.

This service provides a /services endpoint that returns a JSON object
containing information about all available services in the workspace.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, APIRouter
from fastapi.responses import JSONResponse


def create_app(path_prefix: str = "") -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        path_prefix: Optional path prefix for all routes (e.g., "dtaas-user")

    Returns:
        Configured FastAPI application instance.
    """
    # Clean up path prefix
    if path_prefix:
        path_prefix = path_prefix.strip("/")
        if path_prefix:
            path_prefix = f"/{path_prefix}"
    else:
        path_prefix = ""

    # Create the FastAPI app
    fastapi_app = FastAPI(
        title="Workspace Admin Service",
        description="Service discovery and management for DTaaS workspace",
        version="0.1.0"
    )

    # Create router for our endpoints
    router = APIRouter()

    @router.get("/")
    async def root() -> Dict[str, Any]:
        """Root endpoint providing service information."""
        return {
            "service": "Workspace Admin Service",
            "version": "0.1.0",
            "endpoints": {
                "/services": "Get list of available workspace services",
                "/health": "Health check endpoint"
            }
        }

    @router.get("/services")
    async def get_services() -> JSONResponse:
        """
        Get list of available workspace services.

        Returns:
            JSONResponse containing service information.
        """
        services = load_services(os.environ["PATH_PREFIX"] if "PATH_PREFIX" in os.environ else "")
        return JSONResponse(content=services)

    @router.get("/health")
    async def health_check() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy"}

    # Include router with optional prefix
    fastapi_app.include_router(router, prefix=path_prefix)

    return fastapi_app


# Create default app instance
app = create_app()

# Path to services template
SERVICES_TEMPLATE_PATH = Path(__file__).parent / "services_template.json"


def load_services(path_prefix: str = "") -> Dict[str, Any]:
    """
    Load services from template and substitute environment variables.

    Returns:
        Dictionary containing service information with environment
        variables substituted.
    """
    # Read the services template
    with open(SERVICES_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        services = json.load(f)

    # Substitute {PATH_PREFIX} in endpoint values
    for _, service_info in services.items():
        if 'endpoint' in service_info:
            service_info['endpoint'] = service_info['endpoint'].replace(
                '{PATH_PREFIX}', path_prefix
            )

    return services


def cli():
    """
    Command-line interface for the workspace admin service.

    This allows the service to be run as a standalone utility
    similar to glances.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Workspace Admin Service - "
            "Service discovery for DTaaS workspaces"
        )
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind the service to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("ADMIN_SERVER_PORT", "8091")),
        help=(
            "Port to bind the service to "
            "(default: $ADMIN_SERVER_PORT or 8091)"
        )
    )
    parser.add_argument(
        "--path-prefix",
        default=os.getenv("PATH_PREFIX", "dtaas-user"),
        help="Path prefix for API routes (e.g., 'dtaas-user' for routes at /dtaas-user/services)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--list-services",
        action="store_true",
        help="List available services and exit"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0"
    )

    args = parser.parse_args()

    # Set up path prefix
    path_prefix = args.path_prefix.strip("/")
    if path_prefix:
        os.environ["PATH_PREFIX"] = path_prefix
        prefix_display = f"/{path_prefix}"
    else:
        prefix_display = ""

    if args.list_services:
        # Just list services and exit
        services = load_services(path_prefix)
        print(json.dumps(services, indent=2))
        sys.exit(0)

    # Start the server
    print(f"Starting Workspace Admin Service on {args.host}:{args.port}")
    print("Service endpoints:")
    print(f"  - http://{args.host}:{args.port}{prefix_display}/services")
    print(f"  - http://{args.host}:{args.port}{prefix_display}/health")
    print(f"  - http://{args.host}:{args.port}{prefix_display}/")

    # Recreate app with path prefix
    global app  # pylint: disable=global-statement
    app = create_app(path_prefix)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload
    )


if __name__ == "__main__":
    cli()
