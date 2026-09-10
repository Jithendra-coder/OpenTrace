"""Canonical, deterministic OpenAPI domain models for contract analysis."""

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ResolutionState(StrEnum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    UNSUPPORTED = "UNSUPPORTED"


class SupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class ChangeCategory(StrEnum):
    ENDPOINT_REMOVED = "endpoint_removed"
    HTTP_METHOD_REMOVED = "http_method_removed"
    REQUIRED_PARAMETER_ADDED = "required_parameter_added"
    REQUEST_PROPERTY_REMOVED = "request_property_removed"
    REQUEST_PROPERTY_TYPE_CHANGED = "request_property_type_changed"
    RESPONSE_PROPERTY_REMOVED = "response_property_removed"
    RESPONSE_PROPERTY_TYPE_CHANGED = "response_property_type_changed"
    SECURITY_REQUIREMENT_CHANGED = "security_requirement_changed"
    ENUM_RESTRICTED = "enum_restricted"
    NULLABLE_REMOVED = "nullable_removed"


class BreakingClassification(StrEnum):
    CLIENT_BREAKING = "CLIENT_BREAKING"
    SERVER_BREAKING = "SERVER_BREAKING"
    POTENTIALLY_BREAKING = "POTENTIALLY_BREAKING"
    COMPATIBLE = "COMPATIBLE"


class CompatibilityDirection(StrEnum):
    CLIENT_TO_SERVER = "CLIENT_TO_SERVER"
    SERVER_TO_CLIENT = "SERVER_TO_CLIENT"


class ChangeCertainty(StrEnum):
    EXACT = "EXACT"
    CONDITIONAL = "CONDITIONAL"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"


class ChangeSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CanonicalModel(BaseModel):
    """Immutable model with deterministic serialization for comparisons and tests."""

    model_config = ConfigDict(frozen=True)

    def canonical_json(self) -> str:
        """Return stable JSON without parser-boundary objects or incidental map ordering."""
        return json.dumps(
            self.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class Reference(CanonicalModel):
    target: str
    kind: str | None = None
    resolution_state: ResolutionState


class Schema(CanonicalModel):
    id: str
    type: str | None = None
    types: tuple[str, ...] = ()
    format: str | None = None
    nullable: bool = False
    enum: tuple[str | int | float | bool | None, ...] = ()
    properties: tuple["SchemaProperty", ...] = ()
    items: "Schema | None" = None
    required_properties: tuple[str, ...] = ()
    additional_properties_allowed: bool | None = None
    additional_properties_schema: "Schema | None" = None
    all_of: tuple["Schema", ...] = ()
    one_of: tuple["Schema", ...] = ()
    any_of: tuple["Schema", ...] = ()
    reference: Reference | None = None
    support_status: SupportStatus = SupportStatus.SUPPORTED
    warnings: tuple[str, ...] = ()


class SchemaProperty(CanonicalModel):
    name: str
    required: bool
    schema_definition: Schema = Field(serialization_alias="schema")


class Parameter(CanonicalModel):
    id: str
    name: str | None = None
    location: str | None = None
    required: bool | None = None
    description: str | None = None
    schema_definition: Schema | None = Field(default=None, serialization_alias="schema")
    reference: Reference | None = None


class RequestBody(CanonicalModel):
    id: str
    required: bool | None = None
    content: dict[str, Schema | None] = Field(default_factory=dict)
    description: str | None = None
    reference: Reference | None = None


class Header(CanonicalModel):
    name: str
    description: str | None = None
    required: bool | None = None
    schema_definition: Schema | None = Field(default=None, serialization_alias="schema")
    reference: Reference | None = None


class Response(CanonicalModel):
    id: str
    code: str | None = None
    description: str | None = None
    content: dict[str, Schema | None] = Field(default_factory=dict)
    headers: dict[str, Header] = Field(default_factory=dict)
    reference: Reference | None = None


class SecurityRequirement(CanonicalModel):
    scheme: str
    scopes: tuple[str, ...] = ()


SecurityRequirements = tuple[tuple[SecurityRequirement, ...], ...]


class SecurityScheme(CanonicalModel):
    name: str
    type: str | None = None
    scheme: str | None = None
    bearer_format: str | None = None
    description: str | None = None
    reference: Reference | None = None


class APIOperation(CanonicalModel):
    id: str
    method: str
    path: str
    operation_id: str | None = None
    tags: tuple[str, ...] = ()
    summary: str | None = None
    description: str | None = None
    parameters: tuple[Parameter, ...] = ()
    request_body: RequestBody | None = None
    responses: dict[str, Response] = Field(default_factory=dict)
    # None means the operation inherits the document-level requirement. An empty
    # tuple is OpenAPI's explicit "no security requirement" override.
    security: SecurityRequirements | None = None


class NormalizationMetadata(CanonicalModel):
    version: str = "1"
    warnings: tuple[str, ...] = ()


class APISpecification(CanonicalModel):
    id: str
    openapi_version: str
    title: str
    version: str
    servers: tuple[str, ...] = ()
    operations: tuple[APIOperation, ...] = ()
    schemas: dict[str, Schema] = Field(default_factory=dict)
    parameters: dict[str, Parameter] = Field(default_factory=dict)
    responses: dict[str, Response] = Field(default_factory=dict)
    request_bodies: dict[str, RequestBody] = Field(default_factory=dict)
    security_schemes: dict[str, SecurityScheme] = Field(default_factory=dict)
    security: SecurityRequirements = ()
    normalization: NormalizationMetadata = Field(default_factory=NormalizationMetadata)


class APIChange(CanonicalModel):
    """A deterministic, explainable old-to-new contract compatibility observation."""

    id: str
    category: ChangeCategory
    path: str
    method: str
    location: str
    old_value: JsonValue | None = None
    new_value: JsonValue | None = None
    severity: ChangeSeverity
    breaking_classification: BreakingClassification
    compatibility_direction: CompatibilityDirection
    certainty: ChangeCertainty
    reason: str
    assumptions: tuple[str, ...] = ()
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
