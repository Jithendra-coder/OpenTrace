"""Project registry for managing multiple local projects."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field


class ProjectRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    repo_path: str
    spec_path: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_scanned: str | None = None
    is_active: bool = False


class ProjectRegistry:
    """Manages local project registrations stored in user home or workspace."""

    def __init__(self, root_dir: Path | None = None) -> None:
        if root_dir is not None:
            self.root_dir = root_dir
        else:
            home_override = (
                os.environ.get("OPENTRACE_HOME")
                or os.environ.get("CHANGEMESH_HOME")
                or os.environ.get("SPECIMPACT_HOME")
            )
            self.root_dir = Path(home_override) if home_override else (Path.home() / ".opentrace")
        self.registry_file = self.root_dir / "projects.json"
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_file.exists():
            default_proj = ProjectRecord(
                id="default",
                name="Default Workspace",
                repo_path=str(Path.cwd().resolve()),
                is_active=True,
            )
            self._save([default_proj])

    def _load(self) -> list[ProjectRecord]:
        if not self.registry_file.exists():
            return []
        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
            return [ProjectRecord(**item) for item in data]
        except Exception:
            return []

    def _save(self, projects: list[ProjectRecord]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        data = [p.model_dump() for p in projects]
        self.registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_projects(self) -> list[ProjectRecord]:
        projects = self._load()
        if not projects:
            self._ensure_storage()
            projects = self._load()
        valid = [p for p in projects if p.id == "default" or Path(p.repo_path).exists()]
        if len(valid) != len(projects):
            projects = valid
            if projects and not any(p.is_active for p in projects):
                projects[0].is_active = True
            self._save(projects)
        return projects

    def get_active_project(self) -> ProjectRecord:
        projects = self.list_projects()
        for p in projects:
            if p.is_active:
                return p
        if projects:
            projects[0].is_active = True
            self._save(projects)
            return projects[0]
        # Fallback
        default = ProjectRecord(
            id="default",
            name="Default Workspace",
            repo_path=str(Path.cwd().resolve()),
            is_active=True,
        )
        self._save([default])
        return default

    def add_project(self, name: str, repo_path: str, spec_path: str | None = None) -> ProjectRecord:
        resolved_repo = Path(repo_path).resolve()
        if not resolved_repo.exists() or not resolved_repo.is_dir():
            raise ValueError(f"Repository path does not exist or is not a directory: {repo_path}")

        projects = self._load()
        for p in projects:
            p.is_active = False

        new_proj = ProjectRecord(
            name=name.strip() or resolved_repo.name,
            repo_path=str(resolved_repo),
            spec_path=str(Path(spec_path).resolve()) if spec_path else None,
            is_active=True,
        )
        (resolved_repo / ".opentrace").mkdir(parents=True, exist_ok=True)

        projects.append(new_proj)
        self._save(projects)
        return new_proj

    def switch_project(self, project_id: str) -> ProjectRecord:
        projects = self._load()
        target = None
        for p in projects:
            if p.id == project_id:
                p.is_active = True
                target = p
            else:
                p.is_active = False

        if not target:
            raise KeyError(f"Project with ID '{project_id}' not found.")

        self._save(projects)
        return target

    def remove_project(self, project_id: str) -> None:
        projects = self._load()
        filtered = [p for p in projects if p.id != project_id]
        if len(filtered) == len(projects):
            raise KeyError(f"Project with ID '{project_id}' not found.")

        if filtered and not any(p.is_active for p in filtered):
            filtered[0].is_active = True

        self._save(filtered)


_registry_instance: ProjectRegistry | None = None


def get_registry() -> ProjectRegistry:
    global _registry_instance
    home_override = (
        os.environ.get("OPENTRACE_HOME")
        or os.environ.get("CHANGEMESH_HOME")
        or os.environ.get("SPECIMPACT_HOME")
    )
    if _registry_instance is None or (home_override and str(_registry_instance.root_dir) != str(Path(home_override))):
        _registry_instance = ProjectRegistry()
    return _registry_instance
