"""
Unit tests for the admin service.

Tests the /services endpoint and service discovery functionality.
"""

import json

import pytest
from fastapi.testclient import TestClient

from admin.main import create_app, load_services, SERVICES_TEMPLATE_PATH


@pytest.fixture(name='test_client')
def fixture_test_client():
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


@pytest.fixture(name='test_client_with_prefix')
def fixture_test_client_with_prefix():
    """Create a test client for the FastAPI app with path prefix."""
    app = create_app(path_prefix="user1")
    return TestClient(app)


def test_root_endpoint(test_client):
    """Test the root endpoint returns service information."""
    response = test_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Workspace Admin Service"
    assert "endpoints" in data
    assert "/services" in data["endpoints"]


def test_health_check(test_client):
    """Test the health check endpoint."""
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_services_endpoint(test_client):
    """Test the /services endpoint returns service list."""
    response = test_client.get("/services")
    assert response.status_code == 200

    services = response.json()

    # Check that we have the expected services
    assert "desktop" in services
    assert "vscode" in services
    assert "notebook" in services
    assert "lab" in services

    # Check desktop service structure
    desktop = services["desktop"]
    assert "name" in desktop
    assert "description" in desktop
    assert "endpoint" in desktop
    assert desktop["name"] == "Desktop"


def test_services_endpoint_returns_all_services(test_client):
    """Test /services endpoint returns all defined services."""
    response = test_client.get("/services")
    assert response.status_code == 200

    services = response.json()

    # Verify all expected services are present
    required_services = ["desktop", "vscode", "notebook", "lab"]
    for service_id in required_services:
        assert service_id in services


def test_load_services_preserves_structure():
    """Test that load_services preserves the service structure."""
    services = load_services()

    # Check all required services exist
    required_services = ["desktop", "vscode", "notebook", "lab"]
    for service_id in required_services:
        assert service_id in services
        assert "name" in services[service_id]
        assert "description" in services[service_id]
        assert "endpoint" in services[service_id]


def test_services_template_file_exists():
    """Test that the services template file exists."""
    assert SERVICES_TEMPLATE_PATH.exists()
    assert SERVICES_TEMPLATE_PATH.is_file()


def test_services_template_valid_json():
    """Test that the services template is valid JSON."""
    with open(SERVICES_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        services = json.load(f)

    # Should not raise an exception
    assert isinstance(services, dict)
    assert len(services) > 0


def test_cli_list_services(monkeypatch, capsys):
    """Test CLI --list-services flag."""
    import sys
    monkeypatch.setattr(sys, 'argv', ['workspace-admin', '--list-services'])

    from admin.main import cli

    with pytest.raises(SystemExit) as exc_info:
        cli()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "desktop" in output
    assert "vscode" in output


def test_cli_version(monkeypatch):
    """Test CLI --version flag."""
    import sys
    monkeypatch.setattr(sys, 'argv', ['workspace-admin', '--version'])

    from admin.main import cli

    with pytest.raises(SystemExit) as exc_info:
        cli()

    # argparse exits with 0 for --version
    assert exc_info.value.code == 0


def test_load_services_with_missing_endpoint():
    """Test load_services handles services without endpoint field."""
    services = load_services()
    # All services should have endpoint field, even if empty
    for service_info in services.values():
        assert 'endpoint' in service_info


def test_services_endpoint_json_structure(test_client):
    """Test that services endpoint returns proper JSON structure."""
    response = test_client.get("/services")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    services = response.json()
    # Verify it's a dictionary with string keys
    assert isinstance(services, dict)
    for key, value in services.items():
        assert isinstance(key, str)
        assert isinstance(value, dict)
        assert "name" in value
        assert "description" in value
        assert "endpoint" in value


def test_root_endpoint_version(test_client):
    """Test that root endpoint includes version."""
    response = test_client.get("/")
    data = response.json()
    assert "version" in data
    assert data["version"] == "0.1.0"


def test_health_endpoint_returns_json(test_client):
    """Test that health endpoint returns JSON."""
    response = test_client.get("/health")
    assert response.headers["content-type"] == "application/json"


def test_root_endpoint_with_prefix(test_client_with_prefix):
    """Test root endpoint with path prefix."""
    response = test_client_with_prefix.get("/user1/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Workspace Admin Service"


def test_services_endpoint_with_prefix(test_client_with_prefix):
    """Test services endpoint with path prefix."""
    response = test_client_with_prefix.get("/user1/services")
    assert response.status_code == 200
    services = response.json()
    assert "desktop" in services


def test_health_endpoint_with_prefix(test_client_with_prefix):
    """Test health endpoint with path prefix."""
    response = test_client_with_prefix.get("/user1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_path_prefix_not_accessible_without_prefix(test_client_with_prefix):
    """Test that endpoints are not accessible without prefix when prefix is set."""
    # When app has prefix, root-level routes should not work
    response = test_client_with_prefix.get("/services")
    assert response.status_code == 404


def test_create_app_with_various_prefixes():
    """Test creating app with different prefix formats."""
    # Test with leading/trailing slashes - routes should work
    app1 = create_app("/user1/")
    client1 = TestClient(app1)
    assert client1.get("/user1/health").status_code == 200

    app2 = create_app("user1")
    client2 = TestClient(app2)
    assert client2.get("/user1/health").status_code == 200

    app3 = create_app("")
    client3 = TestClient(app3)
    assert client3.get("/health").status_code == 200

    app4 = create_app("/")
    client4 = TestClient(app4)
    assert client4.get("/health").status_code == 200
