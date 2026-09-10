"""opentrace pr — create a draft GitHub PR from the current migration plan."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from opentrace.cli.output import (
    bold, cyan, dim, green, print_banner, print_error,
    print_info, print_ok, print_section, print_warn, red, yellow,
)
from opentrace.cli.workspace import (
    analysis_path, analysis_exists,
    migration_plan_exists, migration_plan_path,
    read_json, validation_result_path, validation_exists,
)
from opentrace.github.client import GitHubClient, GitHubClientError
from opentrace.github.git import (
    GitError, apply_edits_to_working_tree, create_branch,
    current_branch, delete_local_branch, find_git_root,
    get_remote_url, parse_github_owner_repo, push_branch,
    restore_files, stage_and_commit,
)
from opentrace.github.pr_template import build_pr_body, build_pr_title


def run_pr(workspace: Path, dry_run: bool, base_branch: str | None) -> None:
    """Create a draft GitHub PR from the current .opentrace/ migration plan."""

    # --- Load workspace artifacts ---
    if not migration_plan_exists(workspace):
        print_error("No migration plan found. Run  opentrace migrate  first.")
        sys.exit(1)

    plan = read_json(migration_plan_path(workspace)) or {}
    patch_data = plan.get("patch")
    if not patch_data:
        print_error("No patch in migration plan. Nothing to PR.")
        sys.exit(1)

    analysis = read_json(analysis_path(workspace)) if analysis_exists(workspace) else {}
    validation = read_json(validation_result_path(workspace)) if validation_exists(workspace) else None

    repo_path = Path(plan.get("repo", workspace))
    edits = patch_data.get("edits", [])
    changes = (analysis or {}).get("changes", [])

    print_banner("OpenTrace  PR")
    print_info(f"Repo     : {repo_path}")
    print_info(f"Edits    : {len(edits)}")
    print_info(f"Dry run  : {dry_run}")
    print()

    if dry_run:
        # Resolve what we can without touching git or GitHub.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        patch_id = patch_data.get("id", "patch")[:12]
        branch_name = f"opentrace/migration-{ts}-{patch_id}"
        file_list = ", ".join(e.get("file", "?") for e in edits)
        print_section("Dry Run — No changes made")
        print_info(f"Would create branch  : {branch_name}")
        print_info(f"Would modify files   : {file_list}")
        print_info(f"Would commit and push to origin")
        print_info(f"Would open draft PR  : {repo_path} / {branch_name} → <default branch>")
        print_info("Re-run without --dry-run to actually create the PR.")
        print()
        return

    # --- Find git root ---
    try:
        git_root = find_git_root(repo_path)
    except GitError as exc:
        print_error(str(exc))
        sys.exit(1)

    print_info(f"Git root : {git_root}")

    # --- Parse GitHub owner/repo ---
    try:
        remote_url = get_remote_url(git_root)
        owner, repo_name = parse_github_owner_repo(remote_url)
    except GitError as exc:
        print_error(str(exc))
        sys.exit(1)

    print_info(f"GitHub   : {owner}/{repo_name}")
    print()

    # --- GitHub auth ---
    try:
        gh = GitHubClient.from_env()
    except GitHubClientError as exc:
        print_error(str(exc))
        print_info("Set your token: $env:GITHUB_TOKEN='ghp_...'")
        sys.exit(1)

    # --- Determine base branch ---
    if base_branch is None:
        try:
            base_branch = gh.get_default_branch(owner, repo_name)
        except GitHubClientError as exc:
            print_error(f"Could not get default branch: {exc}")
            sys.exit(1)
    print_info(f"Base     : {base_branch}")

    # --- Build branch name ---
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    patch_id = patch_data.get("id", "patch")[:12]
    branch_name = f"opentrace/migration-{ts}-{patch_id}"
    print_info(f"Branch   : {branch_name}")
    print()


    # --- Record original branch for rollback ---
    try:
        original_branch = current_branch(git_root)
    except GitError:
        original_branch = "main"

    modified_files: list[str] = []
    try:
        # 1. Create branch
        print(f"  Creating branch {cyan(branch_name)}...")
        create_branch(git_root, branch_name)

        # 2. Apply edits to working tree
        print(f"  Applying {len(edits)} edit(s)...")
        modified_files = apply_edits_to_working_tree(git_root, edits)
        for f in modified_files:
            print_ok(f"Applied → {f}")

        # 3. Commit
        commit_msg = _build_commit_message(changes, patch_data)
        print(f"  Committing...")
        commit_sha = stage_and_commit(git_root, modified_files, commit_msg)
        print_ok(f"Commit {commit_sha[:12]}")

        # 4. Push
        print(f"  Pushing {branch_name} to origin...")
        push_branch(git_root, branch_name)
        print_ok("Branch pushed.")

        # 5. Create draft PR
        print(f"  Opening draft PR on GitHub...")
        title = build_pr_title(changes, patch_data)
        body = build_pr_body(analysis or {}, plan, validation, patch_data, commit_sha, branch_name)

        pr = gh.create_draft_pr(
            owner, repo_name,
            title=title,
            body=body,
            head=branch_name,
            base=base_branch,
        )

    except (GitError, GitHubClientError) as exc:
        print_error(str(exc))
        print_warn("Rolling back working tree changes...")
        if modified_files:
            restore_files(git_root, modified_files)
        delete_local_branch(git_root, branch_name, original_branch)
        sys.exit(1)

    # --- Print result ---
    pr_url = pr.get("html_url", "?")
    pr_number = pr.get("number", "?")

    print_section("Draft PR Created")
    print_ok(f"PR #{pr_number} opened as DRAFT")
    print_info(f"URL: {cyan(pr_url)}")
    print()
    print(bold("  ⚠  Human review required before merging."))
    print(f"  {dim('This PR was generated by OpenTrace using the DeterministicFakeProvider.')}")
    print(f"  {dim('Review the diff carefully before approving.')}")
    print()

    # Write audit record
    audit = {
        "schema_version": "pr-audit-v1",
        "pr_number": pr_number,
        "pr_url": pr_url,
        "branch": branch_name,
        "base": base_branch,
        "commit_sha": commit_sha[:12],
        "files_modified": modified_files,
        "patch_id": patch_data.get("id"),
        "never_auto_merged": True,
    }
    from opentrace.cli.workspace import ensure_workspace, write_json
    ensure_workspace(workspace)
    pr_audit_path = workspace / ".opentrace" / "pr-audit.json"
    write_json(pr_audit_path, audit)
    print_ok(f"Audit record written → {pr_audit_path}")
    print()


def _build_commit_message(changes: list[dict], patch_data: dict) -> str:
    strategy = patch_data.get("selected_strategy", "UNKNOWN")
    if changes:
        c = changes[0]
        method = c.get("method", "").upper()
        path = c.get("path", "")
        field = c.get("field", "")
        summary = f"{method} {path}" + (f": remove {field}" if field else "")
    else:
        summary = "API migration"
    return (
        f"opentrace: migrate {summary} [{strategy}]\n\n"
        f"Generated by OpenTrace. Patch ID: {patch_data.get('id', '?')[:20]}\n"
        f"Human review required before merging."
    )
