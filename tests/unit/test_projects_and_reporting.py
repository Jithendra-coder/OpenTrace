"""Unit tests for Project Registry, HTML Reporting, and Dashboard Multi-Project API."""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from opentrace.projects.registry import ProjectRegistry, ProjectRecord
from opentrace.reporting.html_report import generate_html_report
from opentrace.main import create_app


@pytest.fixture
def temp_home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def registry(temp_home: Path) -> ProjectRegistry:
    return ProjectRegistry(root_dir=temp_home)


def test_registry_init_and_default(registry: ProjectRegistry) -> None:
    projects = registry.list_projects()
    assert len(projects) >= 1
    active = registry.get_active_project()
    assert active.is_active is True
    assert active.id == "default"


def test_registry_add_project(registry: ProjectRegistry, tmp_path: Path) -> None:
    repo_dir = tmp_path / "my_service"
    repo_dir.mkdir()

    proj = registry.add_project(name="My Service", repo_path=str(repo_dir))
    assert proj.name == "My Service"
    assert proj.repo_path == str(repo_dir)
    assert proj.is_active is True
    assert (repo_dir / ".opentrace").exists()

    active = registry.get_active_project()
    assert active.id == proj.id


def test_registry_add_invalid_path(registry: ProjectRegistry) -> None:
    with pytest.raises(ValueError, match="does not exist or is not a directory"):
        registry.add_project(name="Bad", repo_path="non/existent/path/xyz")


def test_registry_switch_project(registry: ProjectRegistry, tmp_path: Path) -> None:
    repo_1 = tmp_path / "repo_1"
    repo_1.mkdir()
    repo_2 = tmp_path / "repo_2"
    repo_2.mkdir()

    p1 = registry.add_project("P1", str(repo_1))
    p2 = registry.add_project("P2", str(repo_2))

    assert registry.get_active_project().id == p2.id

    switched = registry.switch_project(p1.id)
    assert switched.id == p1.id
    assert registry.get_active_project().id == p1.id


def test_registry_remove_project(registry: ProjectRegistry, tmp_path: Path) -> None:
    repo_1 = tmp_path / "repo_1"
    repo_1.mkdir()
    p1 = registry.add_project("P1", str(repo_1))
    assert any(p.id == p1.id for p in registry.list_projects())

    registry.remove_project(p1.id)
    assert not any(p.id == p1.id for p in registry.list_projects())


def test_generate_html_report_empty(tmp_path: Path) -> None:
    html = generate_html_report(tmp_path)
    assert "<!DOCTYPE html>" in html
    assert "ChangeMesh Migration Report" in html or "OpenTrace" in html
    assert "Visual Call Graph &amp; Blast Radius" in html or "Visual Call Graph" in html


def test_generate_html_report_populated(tmp_path: Path) -> None:
    sdir = tmp_path / ".opentrace"
    sdir.mkdir()

    analysis_data = {
        "changes": [
            {"method": "POST", "path": "/payments", "field": "amount", "change_type": "request_property_removed"}
        ],
        "direct_impacts": [
            {"file": "payment_service.py", "line": 29, "symbol": "create_payment"}
        ],
        "indirect_symbols": [
            {"file": "checkout.py", "symbol": "checkout", "distance": 1}
        ]
    }
    (sdir / "analysis.json").write_text(json.dumps(analysis_data), encoding="utf-8")

    plan_data = {
        "generation_status": "GENERATED",
        "selected_strategy": "SMALL",
        "policy": "balanced",
        "patch": {
            "edits": [
                {
                    "file": "payment_service.py",
                    "symbol": "create_payment",
                    "expected_original_text": '"amount": amount,',
                    "replacement_text": ""
                }
            ]
        }
    }
    (sdir / "migration-plan.json").write_text(json.dumps(plan_data), encoding="utf-8")

    html = generate_html_report(tmp_path)
    assert "POST /payments" in html
    assert "payment_service.py" in html
    assert "checkout.py" in html
    assert "diff-line del" in html


def test_dashboard_projects_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home_dir = tmp_path / "home"
    monkeypatch.setenv("CHANGEMESH_HOME", str(home_dir))
    monkeypatch.setenv("SPECIMPACT_HOME", str(home_dir))

    app = create_app()
    client = TestClient(app)

    # Test GET /api/projects
    res = client.get("/api/projects")
    assert res.status_code == 200
    data = res.json()
    assert "projects" in data
    assert len(data["projects"]) >= 1

    # Test POST /api/projects
    repo_dir = tmp_path / "test_api_repo"
    repo_dir.mkdir()

    add_res = client.post("/api/projects", json={
        "name": "Test API Repo",
        "repo_path": str(repo_dir)
    })
    assert add_res.status_code == 200
    add_data = add_res.json()
    assert add_data["ok"] is True
    proj_id = add_data["project"]["id"]

    # Test POST /api/projects/switch
    switch_res = client.post("/api/projects/switch", json={"project_id": proj_id})
    assert switch_res.status_code == 200
    assert switch_res.json()["ok"] is True

    # Test GET /api/export-report
    export_res = client.get("/api/export-report")
    assert export_res.status_code == 200
    assert "text/html" in export_res.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in export_res.text
