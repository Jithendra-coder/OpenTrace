"""CLI workspace: reads and writes the .opentrace/ state directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_OPENTRACE_DIR = ".opentrace"
_ANALYSIS_FILE = "analysis.json"
_MIGRATION_PLAN_FILE = "migration-plan.json"
_VALIDATION_FILE = "validation-result.json"


def workspace_dir(base: Path) -> Path:
    ot_dir = base / ".opentrace"
    cm_dir = base / ".changemesh"
    si_dir = base / ".specimpact"
    if not ot_dir.exists():
        if cm_dir.exists():
            return cm_dir
        if si_dir.exists():
            return si_dir
    return ot_dir


def analysis_path(base: Path) -> Path:
    return workspace_dir(base) / _ANALYSIS_FILE


def migration_plan_path(base: Path) -> Path:
    return workspace_dir(base) / _MIGRATION_PLAN_FILE


def validation_result_path(base: Path) -> Path:
    return workspace_dir(base) / _VALIDATION_FILE


def ensure_workspace(base: Path) -> Path:
    ws = workspace_dir(base)
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, default=str, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def workspace_exists(base: Path) -> bool:
    return workspace_dir(base).exists()


def analysis_exists(base: Path) -> bool:
    return analysis_path(base).exists()


def migration_plan_exists(base: Path) -> bool:
    return migration_plan_path(base).exists()


def validation_exists(base: Path) -> bool:
    return validation_result_path(base).exists()
