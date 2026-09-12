"""Typed, provider-neutral generation contracts."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrace.migration_context.models import ContextItem
from opentrace.routeforge.models import RouteChoice

MIGRATION_GENERATION_SCHEMA_VERSION = "migration-generation-v1"
MIGRATION_GENERATION_POLICY_VERSION = "migration-generation-policy-v1"


class CanonicalModel(BaseModel):
    """Frozen, inspectable artifacts without provider SDK objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class GenerationStatus(StrEnum):
    GENERATED = "GENERATED"
    NOT_REQUIRED = "NOT_REQUIRED"
    AI_DISABLED = "AI_DISABLED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    REFUSED = "REFUSED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    UNSAFE_OUTPUT = "UNSAFE_OUTPUT"


class ProviderErrorCategory(StrEnum):
    AUTHENTICATION = "AUTHENTICATION"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class GenerationPolicy(CanonicalModel):
    version: str = MIGRATION_GENERATION_POLICY_VERSION
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    maximum_response_characters: int = Field(default=16_000, ge=1)
    maximum_edits: int = Field(default=8, ge=1)
    maximum_files: int = Field(default=8, ge=1)
    maximum_replacement_characters: int = Field(default=8_000, ge=1)
    maximum_original_characters: int = Field(default=8_000, ge=1)
    maximum_explanation_characters: int = Field(default=1_000, ge=1)


class GenerationConfiguration(CanonicalModel):
    """Runtime-only mapping from abstract RouteForge strategy to configured model ID."""

    ai_enabled: bool = False
    provider_id: str = "disabled"
    model_by_strategy: dict[RouteChoice, str] = Field(default_factory=dict)
    endpoint: str | None = None

    @model_validator(mode="after")
    def provider_mapping_is_abstract_and_complete_when_enabled(self) -> GenerationConfiguration:
        ai_strategies = {RouteChoice.SMALL, RouteChoice.MEDIUM, RouteChoice.STRONG}
        if set(self.model_by_strategy) - ai_strategies:
            raise ValueError("only SMALL, MEDIUM, and STRONG may have generation model mappings")
        if any(not model.strip() for model in self.model_by_strategy.values()):
            raise ValueError("configured model identifiers must be non-empty")
        if not self.provider_id.strip():
            raise ValueError("provider identifier must be non-empty")
        return self

    def model_for(self, strategy: RouteChoice) -> str | None:
        return self.model_by_strategy.get(strategy)


class GenerationRequest(CanonicalModel):
    id: str
    schema_version: str = MIGRATION_GENERATION_SCHEMA_VERSION
    generation_policy_version: str
    migration_context_id: str
    migration_context_checksum: str
    context_policy_version: str
    api_change_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    selected_strategy: RouteChoice
    routing_decision_id: str
    router_version: str
    routing_policy_version: str
    provider_adapter_id: str
    model_id: str
    timeout_seconds: int = Field(ge=1)
    maximum_response_characters: int = Field(ge=1)
    system_instructions: str
    migration_objective: str
    context_items: tuple[ContextItem, ...]
    context_item_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    fingerprint: str


class ProviderError(CanonicalModel):
    category: ProviderErrorCategory
    message: str


class GenerationResponse(CanonicalModel):
    """Raw normalized adapter response; its content remains untrusted."""

    content: str | None = None
    refusal: str | None = None
    error: ProviderError | None = None
    observed_duration_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def has_exactly_one_outcome(self) -> GenerationResponse:
        if sum(value is not None for value in (self.content, self.refusal, self.error)) != 1:
            raise ValueError("provider response must contain exactly one outcome")
        return self


class GenerationFailure(CanonicalModel):
    status: GenerationStatus
    code: str
    message: str
    provider_error_category: ProviderErrorCategory | None = None


class ProviderEdit(CanonicalModel):
    """Strict JSON-only edit envelope emitted by a provider adapter."""

    file: str
    context_item_id: str
    original_text: str = Field(min_length=1)
    original_text_hash: str
    replacement_text: str
    reason: str = Field(min_length=1)


class ProviderCandidate(CanonicalModel):
    edits: tuple[ProviderEdit, ...] = Field(min_length=1)
    explanation: str = Field(min_length=1)


class ProposedFileEdit(CanonicalModel):
    id: str
    file: str
    context_item_id: str
    symbol: str | None = None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    source_item_hash: str
    original_text_hash: str
    expected_original_text: str
    replacement_text: str
    reason: str
    response_item_indexes: tuple[int, ...]


class ProposedMigrationPatch(CanonicalModel):
    id: str
    migration_context_id: str
    migration_context_checksum: str
    routing_decision_id: str
    selected_strategy: RouteChoice
    provider_adapter_id: str
    model_id: str
    generation_policy_version: str
    generation_fingerprint: str
    provider_response_hash: str
    edits: tuple[ProposedFileEdit, ...]
    explanation: str
    warnings: tuple[str, ...] = ()


class MigrationGenerationResult(CanonicalModel):
    id: str
    status: GenerationStatus
    migration_context_id: str | None = None
    request: GenerationRequest | None = None
    patch: ProposedMigrationPatch | None = None
    failure: GenerationFailure | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def outcome_matches_status(self) -> MigrationGenerationResult:
        if self.status is GenerationStatus.GENERATED:
            if self.patch is None or self.failure is not None:
                raise ValueError("GENERATED requires a patch and no failure")
        elif self.patch is not None:
            raise ValueError("non-generated results cannot contain a patch")
        return self
