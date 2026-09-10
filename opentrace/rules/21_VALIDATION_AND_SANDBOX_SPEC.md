# Validation and Sandbox Specification

From M16, validation flows: candidate patch → patch validation → syntax validation → temporary repository copy → isolated environment → dependency setup → pytest → structured result → destroy environment. Output includes `patch_applied`, `syntax_ok`, `tests_collected`, `tests_passed`, `tests_failed`, `timeout`, `exit_code`, and sanitized `failure_summary`.

Never execute arbitrary submitted repository code directly on the host. Enforce ephemeral filesystems/workspaces, least privilege/restricted privileges, CPU limits, memory limits, PID limits, execution timeout, restricted network where practical, redacted logs, cleanup verification and audit metadata. Docker is a useful boundary but not a claim of perfect isolation; threat model and deployment controls must be documented before production use.
