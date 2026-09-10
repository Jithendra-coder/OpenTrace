"""Trusted, centralized deterministic migration policy for M10."""

from __future__ import annotations

from dataclasses import dataclass

from opentrace.contracts.models import ChangeCategory
from opentrace.migration.models import Repairability


@dataclass(frozen=True)
class RepairRule:
    id: str
    version: str
    category: ChangeCategory
    required_evidence: tuple[str, ...]
    conditions: tuple[str, ...]


REMOVE_REQUEST_PROPERTY_RULE = RepairRule(
    id="remove-request-property-v1",
    version="1",
    category=ChangeCategory.REQUEST_PROPERTY_REMOVED,
    required_evidence=(
        "exact APIChange identity",
        "exact APICallSite identity and request-field evidence",
        "exact DirectImpact evidence",
        "literal request-body dictionary",
        "source span and source hash",
    ),
    conditions=(
        "remove only the structurally matched outgoing JSON property",
        "do not resolve aliases beyond one local literal assignment",
        "reject dynamic keys, merges, mutations, and shared payloads",
    ),
)


RULE_REGISTRY: dict[ChangeCategory, RepairRule] = {
    REMOVE_REQUEST_PROPERTY_RULE.category: REMOVE_REQUEST_PROPERTY_RULE,
}


SUPPORT_MATRIX: dict[ChangeCategory, tuple[Repairability, str]] = {
    ChangeCategory.ENDPOINT_REMOVED: (
        Repairability.UNSUPPORTED,
        "No authoritative replacement endpoint is defined.",
    ),
    ChangeCategory.HTTP_METHOD_REMOVED: (
        Repairability.UNSUPPORTED,
        "No authoritative method substitution is defined.",
    ),
    ChangeCategory.REQUIRED_PARAMETER_ADDED: (
        Repairability.UNSUPPORTED,
        "No authoritative value source is available; values are never invented.",
    ),
    ChangeCategory.REQUEST_PROPERTY_REMOVED: (
        Repairability.SUPPORTED,
        "Exact literal request-body removal is supported under remove-request-property-v1.",
    ),
    ChangeCategory.REQUEST_PROPERTY_TYPE_CHANGED: (
        Repairability.UNSUPPORTED,
        "Type conversions may change semantics and are not guessed.",
    ),
    ChangeCategory.RESPONSE_PROPERTY_REMOVED: (
        Repairability.UNSUPPORTED,
        "Downstream response behavior cannot be safely inferred.",
    ),
    ChangeCategory.RESPONSE_PROPERTY_TYPE_CHANGED: (
        Repairability.UNSUPPORTED,
        "Response conversions are not mechanically authoritative.",
    ),
    ChangeCategory.SECURITY_REQUIREMENT_CHANGED: (
        Repairability.UNSUPPORTED,
        "Credentials, headers, and tokens are never synthesized.",
    ),
    ChangeCategory.ENUM_RESTRICTED: (
        Repairability.UNSUPPORTED,
        "No uniquely authoritative replacement enum value is defined.",
    ),
    ChangeCategory.NULLABLE_REMOVED: (
        Repairability.UNSUPPORTED,
        "No safe replacement for null is defined.",
    ),
}


def support_matrix() -> dict[str, dict[str, str]]:
    """Return a serializable copy of the complete current M2 support matrix."""

    return {
        category.value: {"status": status.value, "reason": reason}
        for category, (status, reason) in SUPPORT_MATRIX.items()
    }


def rule_for(category: ChangeCategory) -> RepairRule | None:
    return RULE_REGISTRY.get(category)
