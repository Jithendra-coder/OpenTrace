"""Structured errors raised at the untrusted OpenAPI document boundary."""


class SpecificationError(ValueError):
    """Base error for an OpenAPI document that cannot be normalized."""


class InvalidSpecificationError(SpecificationError):
    """The document is malformed or lacks required OpenAPI structure."""


class UnsupportedOpenAPIVersionError(SpecificationError):
    """The document is not an explicitly supported OpenAPI 3.x version."""


class ReferenceResolutionError(SpecificationError):
    """An internal reference is malformed or cannot be resolved."""
