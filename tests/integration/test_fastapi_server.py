from fastapi.testclient import TestClient
from opentrace.main import create_app

from opentrace import __version__


def test_package_imports() -> None:
    assert __version__ == "0.1.0"


def test_health_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "opentrace"


def test_version_endpoint_uses_package_version() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["service"] == "opentrace"
    assert response.json()["version"] == __version__
