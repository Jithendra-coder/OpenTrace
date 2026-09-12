"""GitHub integration module."""

from opentrace.github.client import GitHubClient, GitHubClientError
from opentrace.github.git import (
    GitError,
    apply_edits_to_working_tree,
    create_branch,
    current_branch,
    find_git_root,
    get_remote_url,
    parse_github_owner_repo,
    push_branch,
    stage_and_commit,
)
from opentrace.github.pr_template import build_pr_body, build_pr_title

__all__ = [
    "GitError",
    "GitHubClient",
    "GitHubClientError",
    "apply_edits_to_working_tree",
    "build_pr_body",
    "build_pr_title",
    "create_branch",
    "current_branch",
    "find_git_root",
    "get_remote_url",
    "parse_github_owner_repo",
    "push_branch",
    "stage_and_commit",
]
