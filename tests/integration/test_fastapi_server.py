import os

from fastapi.testclient import TestClient
from opentrace import __version__
from opentrace.api import dashboard
from opentrace.cli.commands import pr
from opentrace.main import create_app


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


def test_dashboard_rejects_cross_origin_state_changes() -> None:
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post(
            "/api/reset",
            headers={"origin": "https://attacker.example", "sec-fetch-site": "cross-site"},
        )

    assert response.status_code == 403


def test_dashboard_rejects_untrusted_host_header() -> None:
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post(
            "/api/reset",
            headers={"host": "attacker.example", "origin": "http://attacker.example"},
        )

    assert response.status_code == 403


def test_shell_command_endpoint_is_not_exposed() -> None:
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post("/api/terminal/run", json={"command": "opentrace --version"})

    assert response.status_code in (404, 405)


def test_pr_request_token_does_not_mutate_process_environment(
    tmp_path, monkeypatch
) -> None:
    observed = {}
    monkeypatch.setenv("GITHUB_TOKEN", "process-token")
    monkeypatch.setattr(dashboard, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(dashboard, "_state_dir", lambda: tmp_path / ".opentrace")

    def fake_run_pr(workspace, *, dry_run, base_branch, github_token):
        observed.update(token=github_token, dry_run=dry_run)
        print("stub PR")

    monkeypatch.setattr(pr, "run_pr", fake_run_pr)
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post(
            "/api/pr", json={"dry_run": True, "github_token": "request-token"}
        )

    assert response.status_code == 200
    assert observed == {"token": "request-token", "dry_run": True}
    assert os.environ["GITHUB_TOKEN"] == "process-token"
