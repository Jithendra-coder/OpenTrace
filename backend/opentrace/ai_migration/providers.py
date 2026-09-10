"""Deterministic provider adapter used only for M15 tests and local demonstrations."""

from __future__ import annotations

import hashlib
import json
import re

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from opentrace.ai_migration.models import (
    GenerationRequest,
    GenerationResponse,
    ProviderError,
    ProviderErrorCategory,
)
from opentrace.migration_context.models import ContextItem, ContextItemRole


class FakeProviderMode(StrEnum):
    VALID = "VALID"
    MALFORMED = "MALFORMED"
    REFUSAL = "REFUSAL"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    UNSAFE_PATH = "UNSAFE_PATH"
    SENSITIVE_FILE = "SENSITIVE_FILE"
    UNAUTHORIZED_FILE = "UNAUTHORIZED_FILE"
    OVERSIZED = "OVERSIZED"
    EXTRA_PROSE = "EXTRA_PROSE"
    DUPLICATE = "DUPLICATE"
    OVERLAPPING = "OVERLAPPING"
    MULTI_FILE = "MULTI_FILE"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class DeterministicFakeProvider:
    """A no-network adapter exercising the same strict boundary as any future provider."""

    adapter_id = "deterministic-fake-v1"

    def __init__(self, mode: FakeProviderMode = FakeProviderMode.VALID) -> None:
        self.mode = mode
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        if self.mode is FakeProviderMode.REFUSAL:
            return GenerationResponse(refusal="Insufficient supported evidence for a candidate.")
        if self.mode is FakeProviderMode.TIMEOUT:
            return GenerationResponse(
                error=ProviderError(category=ProviderErrorCategory.TIMEOUT, message="timed out")
            )
        if self.mode is FakeProviderMode.UNAVAILABLE:
            return GenerationResponse(
                error=ProviderError(
                    category=ProviderErrorCategory.UNAVAILABLE,
                    message="service unavailable",
                )
            )
        if self.mode is FakeProviderMode.MALFORMED:
            return GenerationResponse(content="{not valid json")
        if self.mode is FakeProviderMode.OVERSIZED:
            return GenerationResponse(content="x" * 16_001)
        payload = self._candidate(request)
        if self.mode is FakeProviderMode.EXTRA_PROSE:
            return GenerationResponse(content=f"candidate follows: {_json(payload)}")
        return GenerationResponse(content=_json(payload))

    def _candidate(self, request: GenerationRequest) -> dict[str, object]:
        item, original, replacement = self._target(request.context_items)
        edit: dict[str, object] = {
            "file": item.file,
            "context_item_id": item.id,
            "original_text": original,
            "original_text_hash": _sha256(original),
            "replacement_text": replacement,
            "reason": "Minimal bounded candidate based only on the supplied context item.",
        }
        if self.mode is FakeProviderMode.UNSAFE_PATH:
            edit["file"] = "../../.env"
        elif self.mode is FakeProviderMode.SENSITIVE_FILE:
            edit["file"] = ".env"
        elif self.mode is FakeProviderMode.UNAUTHORIZED_FILE:
            edit["file"] = "admin/secrets.py"
        edits: list[dict[str, object]] = [edit]
        if self.mode is FakeProviderMode.MULTI_FILE:
            other = next(
                candidate
                for candidate in request.context_items
                if candidate.file is not None
                and candidate.file != item.file
                and candidate.content
            )
            edits.append(
                {
                    "file": other.file,
                    "context_item_id": other.id,
                    "original_text": other.content,
                    "original_text_hash": _sha256(other.content),
                    "replacement_text": other.content,
                    "reason": "Second authorized file retained as a bounded candidate edit.",
                }
            )
        if self.mode is FakeProviderMode.DUPLICATE:
            edits.append(dict(edit))
        if self.mode is FakeProviderMode.OVERLAPPING:
            overlap = dict(edit)
            overlap["original_text"] = original[: max(1, len(original) - 1)]
            overlap["original_text_hash"] = _sha256(str(overlap["original_text"]))
            edits.append(overlap)
        return {
            "edits": edits,
            "explanation": "Generated candidate only; it has not been applied or validated.",
        }

    @staticmethod
    def _target(items: tuple[ContextItem, ...]) -> tuple[ContextItem, str, str]:
        # Filter for actual code context items (avoid JSON evidence strings)
        code_roles = {
            getattr(ContextItemRole, "DIRECT_API_CALL", None),
            getattr(ContextItemRole, "TARGET_SYMBOL", None),
            getattr(ContextItemRole, "CALLER_SYMBOL", None),
        }
        source_items = [
            item
            for item in items
            if item.file is not None
            and item.start_line is not None
            and item.content
            and (getattr(item, "role", None) in code_roles)
        ]
        if not source_items:
            source_items = [
                item
                for item in items
                if item.file is not None and item.start_line is not None and item.content
            ]
        if not source_items:
            source_items = [item for item in items if item.file is not None and item.content]
        if not source_items:
            first = items[0]
            return first, first.content[:1] if first.content else "", ""

        # Prioritize DIRECT_API_CALL items first
        direct_items = [
            item
            for item in source_items
            if getattr(item, "role", None) == getattr(ContextItemRole, "DIRECT_API_CALL", None)
        ]
        candidate_items = direct_items + [i for i in source_items if i not in direct_items]

        # 1. Exact known removal patterns
        for item in candidate_items:
            for p in (
                '"amount": amount, ',
                '"amount": price, ',
                ', "amount": amount',
                ', "amount": price',
                '"plan_id": plan_id, ',
                '"plan_id": plan, ',
                ', "plan_id": plan_id',
                ', "plan_id": plan',
                '"plan_id": plan_id',
                '"amount": amount',
            ):
                if p in item.content and item.content.count(p) == 1:
                    return item, p, ""

        # 2. Multiline dictionary pattern with indentation and newline
        pattern_multiline = re.compile(
            r'^[ \t]*["\'][\w_]+["\']\s*:\s*[^,\r\n]+,?[ \t]*\r?\n', re.MULTILINE
        )
        for item in candidate_items:
            matches = pattern_multiline.findall(item.content)
            for m in matches:
                if item.content.count(m) == 1:
                    return item, m, ""

        # 3. Inline dictionary pattern (trailing comma or leading comma)
        pattern_trailing = re.compile(r'["\'][\w_]+["\']\s*:\s*[^,}\r\n]+,\s*')
        for item in candidate_items:
            matches = pattern_trailing.findall(item.content)
            for m in matches:
                if item.content.count(m) == 1:
                    return item, m, ""

        pattern_leading = re.compile(r',\s*["\'][\w_]+["\']\s*:\s*[^,}\r\n]+')
        for item in candidate_items:
            matches = pattern_leading.findall(item.content)
            for m in matches:
                if item.content.count(m) == 1:
                    return item, m, ""

        first = candidate_items[0]
        original = first.content[:1]
        return first, original, original
