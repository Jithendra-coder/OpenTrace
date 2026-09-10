"""Safe YAML/JSON OpenAPI file ingestion."""

import json
from collections.abc import Mapping
from pathlib import Path

import yaml
from yaml import YAMLError

from opentrace.contracts.errors import InvalidSpecificationError
from opentrace.contracts.models import APISpecification
from opentrace.contracts.normalizer import OpenAPINormalizer


class OpenAPIParser:
    """Load untrusted YAML or JSON content into a canonical specification."""

    def __init__(self, normalizer: OpenAPINormalizer | None = None) -> None:
        self._normalizer = normalizer or OpenAPINormalizer()

    def parse_file(self, path: Path) -> APISpecification:
        """Read a local document without resolving network or external references."""
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            raise InvalidSpecificationError(f"Unable to read OpenAPI document: {path}") from error
        return self.parse_text(content)

    def parse_text(self, content: str) -> APISpecification:
        """Safely parse content based on its shape, not solely a filename extension."""
        if not content.strip():
            raise InvalidSpecificationError("OpenAPI document is empty")
        try:
            loaded = (
                json.loads(content)
                if content.lstrip().startswith(("{", "["))
                else yaml.safe_load(content)
            )
        except (json.JSONDecodeError, YAMLError) as error:
            raise InvalidSpecificationError("OpenAPI document is not valid YAML or JSON") from error
        if not isinstance(loaded, Mapping):
            raise InvalidSpecificationError("OpenAPI document top level must be a mapping")
        return self._normalizer.normalize(loaded)
