"""M22 Dashboard API — all /api/* routes for the frontend."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["dashboard"])

from opentrace.projects.registry import get_registry
from opentrace.reporting.html_report import generate_html_report
from fastapi.responses import HTMLResponse


# Workspace root is determined from active project in registry, OPENTRACE_WORKSPACE, or legacy SPECIMPACT_WORKSPACE env var.
def _workspace() -> Path:
    try:
        active = get_registry().get_active_project()
        if active and active.repo_path:
            p = Path(active.repo_path)
            if p.exists():
                return p.resolve()
    except Exception:
        pass
    env = os.environ.get("OPENTRACE_WORKSPACE") or os.environ.get("SPECIMPACT_WORKSPACE", ".")
    return Path(env).resolve()


def _state_dir() -> Path:
    ws = _workspace()
    ot_dir = ws / ".opentrace"
    cm_dir = ws / ".changemesh"
    si_dir = ws / ".specimpact"
    if ot_dir.exists():
        return ot_dir
    if cm_dir.exists():
        return cm_dir
    if si_dir.exists():
        return si_dir
    return ot_dir


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl_dir(directory: Path) -> list[dict]:
    records: list[dict] = []
    if not directory.exists():
        return records
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


# ─────────────────────────────────────────────
# Projects API
# ─────────────────────────────────────────────

class AddProjectRequest(BaseModel):
    name: str
    repo_path: str
    spec_path: str | None = None


class SwitchProjectRequest(BaseModel):
    project_id: str


@router.get("/projects")
async def get_projects() -> JSONResponse:
    reg = get_registry()
    projs = reg.list_projects()
    active = reg.get_active_project()
    return JSONResponse({
        "projects": [p.model_dump() for p in projs],
        "active_id": active.id if active else None,
    })


@router.post("/projects")
async def post_add_project(req: AddProjectRequest) -> JSONResponse:
    try:
        reg = get_registry()
        proj = reg.add_project(name=req.name, repo_path=req.repo_path, spec_path=req.spec_path)
        return JSONResponse({"ok": True, "project": proj.model_dump()})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/switch")
async def post_switch_project(req: SwitchProjectRequest) -> JSONResponse:
    try:
        reg = get_registry()
        proj = reg.switch_project(req.project_id)
        return JSONResponse({"ok": True, "project": proj.model_dump()})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str) -> JSONResponse:
    try:
        reg = get_registry()
        reg.remove_project(project_id)
        return JSONResponse({"ok": True, "message": "Project removed"})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# Report Export
# ─────────────────────────────────────────────

@router.get("/export-report")
async def export_report() -> HTMLResponse:
    try:
        ws = _workspace()
        html = generate_html_report(ws)
        return HTMLResponse(
            content=html,
            headers={
                "Content-Disposition": f'attachment; filename="opentrace-report-{ws.name}.html"',
                "Content-Type": "text/html; charset=utf-8",
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# GET /api/workspace  — full workspace state
# ─────────────────────────────────────────────

@router.get("/workspace")
async def get_workspace() -> JSONResponse:
    d = _state_dir()
    analysis    = _read_json(d / "analysis.json")
    plan        = _read_json(d / "migration-plan.json")
    validation  = _read_json(d / "validation-result.json")
    pr_audit    = _read_json(d / "pr-audit.json")
    feedback    = _read_jsonl_dir(d / "feedback")

    return JSONResponse({
        "workspace": str(_workspace()),
        "specimpact_dir": str(d),
        "exists": d.exists(),
        "analysis": analysis,
        "plan": plan,
        "validation": validation,
        "pr_audit": pr_audit,
        "feedback": feedback,
        "version": "1.0.0-dev",
    })


# ─────────────────────────────────────────────
# POST /api/analyze
# ─────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    old_spec: str
    new_spec: str
    repo: str

@router.post("/analyze")
async def post_analyze(req: AnalyzeRequest) -> JSONResponse:
    def _run() -> dict:
        from opentrace.blast_radius.vertical import analyze_vertical_slice
        from opentrace.cli.workspace import ensure_workspace, write_json, analysis_path

        old_spec = Path(req.old_spec)
        new_spec = Path(req.new_spec)
        repo = Path(req.repo)
        for p in (old_spec, new_spec, repo):
            if not p.exists():
                raise ValueError(f"Path does not exist: {p}")

        blast = analyze_vertical_slice(old_spec, new_spec, repo)
        changes = list(blast.changes) if blast.changes else []
        direct = list(blast.direct_impacts) if blast.direct_impacts else []
        direct_symbols = {getattr(d, "symbol", getattr(d, "function_name", "")) for d in direct}
        indirect_symbols = [
            s for s in (blast.impacted_symbols or ())
            if getattr(s, "distance", 0) > 0 or getattr(s, "symbol", "") not in direct_symbols
        ]

        ws = _workspace()
        ensure_workspace(ws)
        artifact = {
            "schema_version": "analysis-v1",
            "old_spec": str(old_spec.resolve()),
            "new_spec": str(new_spec.resolve()),
            "repo": str(repo.resolve()),
            "changes_count": len(changes),
            "direct_count": len(direct),
            "indirect_count": len(indirect_symbols),
            "changes": [_change_dict(c) for c in changes],
            "direct_impacts": [_impact_dict(d) for d in direct],
        }
        write_json(analysis_path(ws), artifact)
        return artifact

    try:
        result = await asyncio.to_thread(_run)
        return JSONResponse({"ok": True, "analysis": result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# POST /api/migrate
# ─────────────────────────────────────────────

class MigrateRequest(BaseModel):
    policy: str = "balanced"

@router.post("/migrate")
async def post_migrate(req: MigrateRequest) -> JSONResponse:
    def _run() -> dict:
        from opentrace.cli.commands.migrate import run_migrate as _rm
        # Reuse the CLI function but capture workspace state after.
        ws = _workspace()
        # run_migrate writes migration-plan.json, then we read it back.
        import io, sys, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _rm(ws, req.policy, ai_enabled=False)

        plan = _read_json(_state_dir() / "migration-plan.json")
        return plan or {}

    try:
        result = await asyncio.to_thread(_run)
        return JSONResponse({"ok": True, "plan": result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# POST /api/validate
# ─────────────────────────────────────────────

@router.post("/validate")
async def post_validate() -> JSONResponse:
    def _run() -> dict:
        from opentrace.cli.commands.validate import run_validate as _rv
        ws = _workspace()
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _rv(ws, timeout=60)
        result = _read_json(_state_dir() / "validation-result.json")
        return result or {}

    try:
        result = await asyncio.to_thread(_run)
        return JSONResponse({"ok": True, "validation": result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# POST /api/pr
# ─────────────────────────────────────────────

class PRRequest(BaseModel):
    dry_run: bool = True
    base_branch: str | None = None
    github_token: str | None = None  # per-request only, never stored

@router.post("/pr")
async def post_pr(req: PRRequest) -> JSONResponse:
    def _run() -> dict:
        import os
        ws = _workspace()
        # Set token for this thread only.
        token_was = os.environ.get("GITHUB_TOKEN", "")
        if req.github_token:
            os.environ["GITHUB_TOKEN"] = req.github_token
        try:
            from opentrace.cli.commands.pr import run_pr as _rpr
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                _rpr(ws, dry_run=req.dry_run, base_branch=req.base_branch)
            pr_audit = _read_json(_state_dir() / "pr-audit.json")
            return {"output": buf.getvalue(), "pr_audit": pr_audit}
        finally:
            if req.github_token:
                if token_was:
                    os.environ["GITHUB_TOKEN"] = token_was
                else:
                    os.environ.pop("GITHUB_TOKEN", None)

    try:
        result = await asyncio.to_thread(_run)
        return JSONResponse({"ok": True, **result})
    except SystemExit:
        raise HTTPException(status_code=400, detail="PR command failed. Check server logs.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# GET /api/feedback
# ─────────────────────────────────────────────

@router.get("/feedback")
async def get_feedback() -> JSONResponse:
    records = _read_jsonl_dir(_state_dir() / "feedback")
    return JSONResponse({"feedback": records})


# ─────────────────────────────────────────────
# POST /api/reset
# ─────────────────────────────────────────────

@router.post("/reset")
async def post_reset() -> JSONResponse:
    def _run() -> None:
        import shutil
        sdir = _state_dir()
        if sdir.exists():
            shutil.rmtree(sdir)

    try:
        await asyncio.to_thread(_run)
        return JSONResponse({"ok": True, "message": "Workspace reset successfully"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# GET /api/cli-status
# ─────────────────────────────────────────────

def _discover_python_environments() -> list[dict[str, object]]:
    import os
    import shutil
    import subprocess
    import sys
    import sysconfig

    seen: set[str] = set()
    envs: list[dict[str, object]] = []

    # 1. Current active runtime is always first and immediately known
    current_norm = os.path.normcase(os.path.abspath(sys.executable))
    seen.add(current_norm)
    scripts_dir = sysconfig.get_path("scripts") or ""
    cm_exe = os.path.join(scripts_dir, "opentrace.exe") if scripts_dir else ""
    si_exe = os.path.join(scripts_dir, "specimpact.exe") if scripts_dir else ""
    has_exe = os.path.isfile(cm_exe) or os.path.isfile(si_exe)
    exe_path = cm_exe if os.path.isfile(cm_exe) else (si_exe if os.path.isfile(si_exe) else (shutil.which("opentrace") or shutil.which("specimpact") or None))

    envs.append({
        "executable": sys.executable,
        "version": f"Python {sys.version.split()[0]}",
        "installed": True,
        "exe_path": exe_path,
    })

    def _probe(path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        if "WindowsApps" in path:
            return
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            return
        seen.add(norm)
        try:
            ver_proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
            ver = (ver_proc.stdout or ver_proc.stderr).strip()
            if not ver.startswith("Python"):
                return

            # Fast spec check with importlib.util (0.1s instead of 9.5s)
            chk = subprocess.run(
                [path, "-c", "import importlib.util, sys; sys.exit(0 if (importlib.util.find_spec('opentrace') or importlib.util.find_spec('specimpact')) else 1)"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            has_cli = (chk.returncode == 0)

            scripts_proc = subprocess.run(
                [path, "-c", "import sysconfig; print(sysconfig.get_path('scripts'))"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            s_dir = (scripts_proc.stdout or "").strip()
            cm_p = os.path.join(s_dir, "opentrace.exe") if s_dir else ""
            si_p = os.path.join(s_dir, "specimpact.exe") if s_dir else ""
            has_e = os.path.isfile(cm_p) or os.path.isfile(si_p)
            e_path = cm_p if os.path.isfile(cm_p) else (si_p if os.path.isfile(si_p) else "")

            envs.append({
                "executable": path,
                "version": ver,
                "installed": has_cli or has_e,
                "exe_path": e_path if has_e else None,
            })
        except Exception:
            pass

    # Check Windows py launcher
    try:
        proc = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=5)
        for line in proc.stdout.splitlines():
            if "\\" in line:
                p = line.split()[-1].strip()
                _probe(p)
    except Exception:
        pass

    # Common Windows installation paths
    candidates = [
        shutil.which("python"),
        shutil.which("python3"),
        os.path.expanduser(r"~\anaconda3\python.exe"),
        os.path.expanduser(r"~\miniconda3\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python310\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python314\python.exe"),
    ]
    for c in candidates:
        if c:
            _probe(c)

    return envs


@router.get("/cli-status")
async def get_cli_status() -> JSONResponse:
    import shutil
    import sys

    cm_exe = shutil.which("opentrace") or shutil.which("specimpact")
    envs = _discover_python_environments()
    installed_count = sum(1 for e in envs if e.get("installed"))

    return JSONResponse({
        "installed": cm_exe is not None or installed_count > 0,
        "path": cm_exe or (envs[0]["exe_path"] if envs and envs[0].get("exe_path") else "Not in system PATH"),
        "python": sys.executable,
        "environments": envs,
        "installed_count": installed_count,
        "total_environments": len(envs),
        "install_command": "pip install -e .",
        "quick_commands": [
            "opentrace analyze --old sample1/api_v1.yaml --new sample1/api_v2.yaml --repo sample1",
            "opentrace migrate --policy balanced",
            "opentrace validate",
            "opentrace status",
            "opentrace apply --yes"
        ]
    })


# ─────────────────────────────────────────────
# POST /api/install-cli
# ─────────────────────────────────────────────

@router.post("/install-cli")
async def post_install_cli() -> JSONResponse:
    import shutil
    import subprocess
    import sys

    def _install() -> dict[str, object]:
        root_dir = str(Path(__file__).resolve().parents[3]).rstrip("\\/")
        envs = _discover_python_environments()
        results = []
        any_success = False

        for env in envs:
            py_exe = str(env["executable"])
            # If already installed, mark as ready and skip expensive reinstall
            if env.get("installed"):
                any_success = True
                results.append({
                    "executable": py_exe,
                    "version": env["version"],
                    "success": True,
                    "output": "Already configured and active."
                })
                continue

            try:
                cmd = [py_exe, "-m", "pip", "install", "-e", root_dir]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                ok = (proc.returncode == 0)
                if ok:
                    any_success = True
                    # Quick check for pytest
                    subprocess.run([py_exe, "-m", "pip", "install", "pytest"], capture_output=True, text=True, timeout=60)
                results.append({
                    "executable": py_exe,
                    "version": env["version"],
                    "success": ok,
                    "output": (proc.stdout[-250:] if ok else proc.stderr[-250:]).strip()
                })
            except Exception as exc:
                results.append({
                    "executable": py_exe,
                    "version": env["version"],
                    "success": False,
                    "output": str(exc)
                })

        cm_exe = shutil.which("opentrace") or shutil.which("specimpact")
        success_count = sum(1 for r in results if r["success"])
        return {
            "success": any_success or success_count > 0,
            "environments": results,
            "path": cm_exe or "Installed across active environments",
            "message": f"Successfully configured {success_count} of {len(results)} Python environment(s)."
        }

    try:
        res = await asyncio.to_thread(_install)
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# GET /api/download/installer-bat
# ─────────────────────────────────────────────

@router.get("/download/installer-bat")
async def get_download_installer_bat():
    from fastapi.responses import Response

    project_root = str(Path(__file__).resolve().parents[3]).rstrip("\\/")
    raw_template = """@echo off
setlocal enabledelayedexpansion
echo ===================================================
echo   OpenTrace CLI 1-Click Windows Installer
echo ===================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required. Please install Python from https://python.org
    pause
    exit /b 1
)

set "TARGET_DIR=__PROJECT_ROOT__"
if not exist "!TARGET_DIR!\\pyproject.toml" (
    set "SCRIPT_DIR=%~dp0"
    set "TARGET_DIR=!SCRIPT_DIR:~0,-1!"
)

if not exist "!TARGET_DIR!\\pyproject.toml" (
    echo [ERROR] Could not locate OpenTrace project root.
    echo Please make sure the OpenTrace repository is present on your system.
    pause
    exit /b 1
)

echo [1/3] Installing OpenTrace in editable mode from:
echo   "!TARGET_DIR!"
echo.

python -m pip install -e "!TARGET_DIR!"
if errorlevel 1 (
    echo [ERROR] pip install failed. Please verify your Python environment.
    pause
    exit /b 1
)

echo.
echo [2/3] Resolving Python Scripts path...
for /f "delims=" %%I in ('python -c "import sysconfig; print(sysconfig.get_path('scripts'))"') do set "SCRIPTS_DIR=%%I"
if defined SCRIPTS_DIR (
    set "PATH=!SCRIPTS_DIR!;%PATH%"
    echo   Added to session PATH: !SCRIPTS_DIR!
)

echo.
echo [3/3] Verifying installation...
opentrace --version >nul 2>&1
if errorlevel 1 (
    python -m opentrace.cli.main --version
) else (
    opentrace --version
)

echo.
echo ===================================================
echo   [SUCCESS] OpenTrace CLI Successfully Installed!
echo.
echo   You can now run in any terminal:
echo     opentrace analyze --old v1.yaml --new v2.yaml --repo ./src
echo     opentrace migrate --policy balanced
echo     opentrace validate
echo ===================================================
pause
"""
    script_content = raw_template.replace("__PROJECT_ROOT__", project_root)
    return Response(
        content=script_content,
        media_type="application/x-bat",
        headers={"Content-Disposition": "attachment; filename=install-opentrace.bat"}
    )


# ─────────────────────────────────────────────
# GET /api/download/installer-ps1
# ─────────────────────────────────────────────

@router.get("/download/installer-ps1")
async def get_download_installer_ps1():
    from fastapi.responses import Response

    project_root = str(Path(__file__).resolve().parents[3]).rstrip("\\/")
    raw_template = """# OpenTrace CLI 1-Click PowerShell Installer
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  OpenTrace CLI PowerShell Installer" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python 3.10+ is required. Please install Python from https://python.org"
    Read-Host "Press Enter to exit"
    exit 1
}

$targetDir = "__PROJECT_ROOT__"
if (-not (Test-Path "$targetDir\\pyproject.toml")) {
    $targetDir = $PSScriptRoot
}
if (-not (Test-Path "$targetDir\\pyproject.toml")) {
    Write-Error "Could not find OpenTrace directory containing pyproject.toml."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`n[1/3] Installing OpenTrace from $targetDir..." -ForegroundColor Yellow
& python -m pip install -e "$targetDir"

if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`n[2/3] Detecting Python Scripts path..." -ForegroundColor Yellow
try {
    $scriptsDir = (& python -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
    if ($scriptsDir -and (Test-Path $scriptsDir)) {
        $env:PATH = "$scriptsDir;$env:PATH"
        Write-Host "  Added to session PATH: $scriptsDir" -ForegroundColor Green
    }
} catch {}

Write-Host "`n[3/3] Verifying CLI installation..." -ForegroundColor Yellow
& python -m opentrace.cli.main --version

Write-Host "`n===================================================" -ForegroundColor Green
Write-Host "  [SUCCESS] OpenTrace CLI Successfully Installed!" -ForegroundColor Green
Write-Host "  Run 'opentrace --help' in any terminal." -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Green
Read-Host "Press Enter to finish"
"""
    script_content = raw_template.replace("__PROJECT_ROOT__", project_root)
    return Response(
        content=script_content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=install-opentrace.ps1"}
    )


# ─────────────────────────────────────────────
# POST /api/terminal/run
# ─────────────────────────────────────────────

class TerminalRunRequest(BaseModel):
    command: str

@router.post("/terminal/run")
async def post_terminal_run(req: TerminalRunRequest) -> JSONResponse:
    import subprocess
    import sys

    cmd_str = req.command.strip()
    if not (cmd_str.startswith("opentrace ") or cmd_str == "opentrace" or cmd_str.startswith("opentrace ") or cmd_str == "opentrace" or cmd_str.startswith("pytest ")):
        raise HTTPException(status_code=400, detail="Only 'opentrace', 'opentrace', and 'pytest' commands are supported.")

    def _exec():
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd_str],
            cwd=str(_workspace_dir()),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "command": cmd_str,
        }

    try:
        result = await asyncio.to_thread(_exec)
        return JSONResponse(result)
    except subprocess.TimeoutExpired:
        return JSONResponse({"exit_code": -1, "stdout": "", "stderr": "Command timed out after 60s", "command": cmd_str})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _change_dict(c: object) -> dict:
    category = getattr(c, "category", None)
    cat_val = category.value if hasattr(category, "value") else str(getattr(c, "change_type", ""))
    return {
        "method": str(getattr(c, "method", "")),
        "path": str(getattr(c, "path", "")),
        "change_type": cat_val,
        "field": str(getattr(c, "location", getattr(c, "field_path", ""))),
        "change_id": str(getattr(c, "id", getattr(c, "change_id", ""))),
    }

def _impact_dict(i: object) -> dict:
    return {
        "file": str(getattr(i, "file", getattr(i, "source_file", ""))),
        "line": getattr(i, "line", getattr(i, "start_line", None)),
        "symbol": str(getattr(i, "symbol", getattr(i, "function_name", ""))),
        "change_id": str(getattr(i, "change_id", getattr(i, "id", ""))),
    }
