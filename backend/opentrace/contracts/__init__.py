"""OpenAPI contract ingestion, normalization, and compatibility comparison."""

from opentrace.contracts.changes import compare_specifications
from opentrace.contracts.parser import OpenAPIParser

__all__ = ["OpenAPIParser", "compare_specifications"]
