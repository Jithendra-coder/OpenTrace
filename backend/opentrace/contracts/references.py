"""Safe, non-networked handling of OpenAPI references."""

from collections.abc import Mapping
from typing import Any

from opentrace.contracts.errors import ReferenceResolutionError
from opentrace.contracts.models import Reference, ResolutionState


class ReferenceResolver:
    """Validate and describe internal references without recursively expanding them."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = document

    def reference(self, value: object) -> Reference:
        """Return an explicit reference after validating internal pointer targets."""
        if not isinstance(value, str) or not value:
            raise ReferenceResolutionError("$ref must be a non-empty string")
        if value.startswith("#") and not value.startswith("#/"):
            raise ReferenceResolutionError(f"Malformed internal $ref: {value}")
        if not value.startswith("#/"):
            return Reference(target=value, resolution_state=ResolutionState.UNSUPPORTED)

        parts = value[2:].split("/")
        if any(not part for part in parts):
            raise ReferenceResolutionError(f"Malformed internal $ref: {value}")

        target: object = self._document
        for raw_part in parts:
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, Mapping) or part not in target:
                raise ReferenceResolutionError(f"Internal $ref target does not exist: {value}")
            target = target[part]

        kind = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
        return Reference(target=value, kind=kind, resolution_state=ResolutionState.EXACT)
