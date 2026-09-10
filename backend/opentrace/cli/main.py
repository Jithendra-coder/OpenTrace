"""OpenTrace CLI — analyze, migrate, validate, apply.

Entry point: opentrace <command> [options] (alias: opentrace <command>)

Commands:
  analyze   Detect API changes and find affected code.
  migrate   Generate a migration plan for detected changes.
  validate  Test the proposed patch in an isolated sandbox.
  apply     Apply validated patches to the repository (requires confirmation).
  status    Show the current .opentrace/ workspace state.
"""

from __future__ import annotations

import opentrace.compat  # noqa: F401 (Ensures StrEnum on Python 3.10)
import argparse
import io
import sys
from pathlib import Path


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows if needed."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

from opentrace.cli.commands.analyze import run_analyze
from opentrace.cli.commands.apply import run_apply
from opentrace.cli.commands.migrate import run_migrate
from opentrace.cli.commands.status import run_status
from opentrace.cli.commands.validate import run_validate
from opentrace.cli.commands.pr import run_pr
from opentrace.cli.output import print_banner, print_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opentrace",
        description="OpenTrace — Automated API Change Impact & Migration Engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="OpenTrace 1.0.0",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # --- analyze ---
    p_analyze = sub.add_parser(
        "analyze",
        help="Detect API changes and find affected code.",
        description="Compare two OpenAPI specs and scan a repository for affected code.",
    )
    p_analyze.add_argument("--old-spec", "--old", dest="old_spec", required=True, metavar="FILE",
                           help="Path to the old OpenAPI spec (YAML or JSON).")
    p_analyze.add_argument("--new-spec", "--new", dest="new_spec", required=True, metavar="FILE",
                           help="Path to the new OpenAPI spec (YAML or JSON).")
    p_analyze.add_argument("--repo", required=True, metavar="DIR",
                           help="Path to the repository root to scan.")
    p_analyze.add_argument("--output-dir", default=".", metavar="DIR",
                           help="Directory to write .opentrace/ workspace (default: .).")

    # --- migrate ---
    p_migrate = sub.add_parser(
        "migrate",
        help="Generate a migration plan for detected changes.",
        description="Use the RouteForge router to generate a migration plan.",
    )
    p_migrate.add_argument("--workspace", default=".", metavar="DIR",
                           help="Directory containing .opentrace/ workspace (default: .).")
    p_migrate.add_argument(
        "--policy",
        choices=["economy", "balanced", "critical"],
        default="balanced",
        help="Migration policy (default: balanced).",
    )
    p_migrate.add_argument(
        "--ai-enabled",
        action="store_true",
        default=False,
        help="Enable AI-assisted migration (requires AI provider configuration).",
    )

    # --- validate ---
    p_validate = sub.add_parser(
        "validate",
        help="Test the proposed patch in an isolated sandbox.",
        description="Run the generated patch in an isolated temp workspace.",
    )
    p_validate.add_argument("--workspace", default=".", metavar="DIR",
                            help="Directory containing .opentrace/ workspace (default: .).")
    p_validate.add_argument("--timeout", type=int, default=60, metavar="SECONDS",
                             help="Sandbox timeout in seconds (default: 60).")

    # --- apply ---
    p_apply = sub.add_parser(
        "apply",
        help="Apply validated patches to the repository.",
        description="Apply patches to the real repository after explicit confirmation.",
    )
    p_apply.add_argument("--workspace", default=".", metavar="DIR",
                         help="Directory containing .opentrace/ workspace (default: .).")
    p_apply.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Skip confirmation prompt (use carefully).",
    )

    # --- status ---
    p_status = sub.add_parser(
        "status",
        help="Show the current .opentrace/ workspace state.",
    )
    p_status.add_argument("--workspace", default=".", metavar="DIR",
                          help="Directory containing .opentrace/ workspace (default: .).")

    # --- pr ---
    p_pr = sub.add_parser(
        "pr",
        help="Create a draft GitHub PR from the migration plan.",
        description=(
            "Create a branch, apply the patch, commit, push, and open a draft PR. "
            "Requires GITHUB_TOKEN environment variable."
        ),
    )
    p_pr.add_argument("--workspace", default=".", metavar="DIR",
                      help="Directory containing .opentrace/ workspace (default: .).")
    p_pr.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would happen without making any changes.",
    )
    p_pr.add_argument(
        "--base-branch",
        default=None,
        metavar="BRANCH",
        help="Base branch for the PR (default: repo default branch).",
    )

    return parser


def main() -> None:
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "analyze":
            run_analyze(
                old_spec=Path(args.old_spec),
                new_spec=Path(args.new_spec),
                repo=Path(args.repo),
                output_dir=Path(args.output_dir),
            )
        elif args.command == "migrate":
            run_migrate(
                workspace=Path(args.workspace),
                policy=args.policy,
                ai_enabled=args.ai_enabled,
            )
        elif args.command == "validate":
            run_validate(
                workspace=Path(args.workspace),
                timeout=args.timeout,
            )
        elif args.command == "apply":
            run_apply(
                workspace=Path(args.workspace),
                yes=args.yes,
            )
        elif args.command == "status":
            run_status(workspace=Path(args.workspace))
        elif args.command == "pr":
            run_pr(
                workspace=Path(args.workspace),
                dry_run=args.dry_run,
                base_branch=args.base_branch,
            )
    except KeyboardInterrupt:
        print_error("\nAborted.")
        sys.exit(1)
    except Exception as exc:
        print_error(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
