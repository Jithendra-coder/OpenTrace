"""Typed errors for invalid analysis requests."""


class CodeAnalysisError(ValueError):
    """Base error for analysis-boundary failures."""


class RepositoryRootError(CodeAnalysisError):
    """The requested repository root cannot be analyzed."""
