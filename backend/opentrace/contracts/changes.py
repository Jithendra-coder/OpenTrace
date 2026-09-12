"""Deterministic compatibility comparison for normalized OpenAPI contracts."""

from __future__ import annotations

import hashlib
import json
from typing import TypeVar, cast

_T = TypeVar("_T")

from pydantic import JsonValue

from opentrace.contracts.models import (
    APIChange,
    APIOperation,
    APISpecification,
    BreakingClassification,
    ChangeCategory,
    ChangeCertainty,
    ChangeSeverity,
    CompatibilityDirection,
    Parameter,
    RequestBody,
    ResolutionState,
    Response,
    Schema,
    SecurityRequirements,
    SupportStatus,
)

_REQUEST = "request"
_RESPONSE = "response"


def compare_specifications(old: APISpecification, new: APISpecification) -> tuple[APIChange, ...]:
    """Compare two normalized specifications without parsing, I/O, or network access."""
    changes: dict[str, APIChange] = {}
    old_operations = {(operation.path, operation.method): operation for operation in old.operations}
    new_operations = {(operation.path, operation.method): operation for operation in new.operations}
    new_paths = {operation.path for operation in new.operations}

    for key in sorted(old_operations):
        operation = old_operations[key]
        replacement = new_operations.get(key)
        if replacement is None:
            category = (
                ChangeCategory.HTTP_METHOD_REMOVED
                if operation.path in new_paths
                else ChangeCategory.ENDPOINT_REMOVED
            )
            _record(
                changes,
                category=category,
                path=operation.path,
                method=operation.method,
                location="operation",
                old_value={"path": operation.path, "method": operation.method},
                new_value=None,
                severity=ChangeSeverity.HIGH,
                classification=BreakingClassification.CLIENT_BREAKING,
                direction=CompatibilityDirection.CLIENT_TO_SERVER,
                certainty=ChangeCertainty.EXACT,
                reason="The operation is absent from the new contract.",
                evidence={"old_operation": operation.id, "new_operation": None},
            )
            continue
        _compare_operation(old, new, operation, replacement, changes)

    return tuple(
        sorted(
            changes.values(),
            key=lambda change: (
                change.path,
                change.method,
                change.category.value,
                change.location,
                change.id,
            ),
        )
    )


def _compare_operation(
    old_specification: APISpecification,
    new_specification: APISpecification,
    old: APIOperation,
    new: APIOperation,
    changes: dict[str, APIChange],
) -> None:
    _compare_parameters(old_specification, new_specification, old, new, changes)
    _compare_security(old_specification, new_specification, old, new, changes)
    _compare_request_body(old_specification, new_specification, old, new, changes)
    _compare_responses(old_specification, new_specification, old, new, changes)


def _compare_parameters(
    old_specification: APISpecification,
    new_specification: APISpecification,
    old: APIOperation,
    new: APIOperation,
    changes: dict[str, APIChange],
) -> None:
    old_parameters = _parameter_index(old_specification, old.parameters)
    new_parameters = _parameter_index(new_specification, new.parameters)
    for identity, new_parameter in sorted(new_parameters.items()):
        old_parameter = old_parameters.get(identity)
        if new_parameter.required is not True or (
            old_parameter is not None and old_parameter.required is True
        ):
            continue
        name, location = identity
        _record(
            changes,
            category=ChangeCategory.REQUIRED_PARAMETER_ADDED,
            path=old.path,
            method=old.method,
            location=f"parameter.{location}.{name}",
            old_value=(_parameter_value(old_parameter) if old_parameter is not None else None),
            new_value=_parameter_value(new_parameter),
            severity=ChangeSeverity.HIGH,
            classification=BreakingClassification.CLIENT_BREAKING,
            direction=CompatibilityDirection.CLIENT_TO_SERVER,
            certainty=ChangeCertainty.EXACT,
            reason="A parameter that was absent or optional is required by the new contract.",
            evidence={
                "parameter_name": name,
                "parameter_location": location,
                "old_required": old_parameter.required if old_parameter else False,
                "new_required": True,
            },
        )


def _compare_security(
    old_specification: APISpecification,
    new_specification: APISpecification,
    old: APIOperation,
    new: APIOperation,
    changes: dict[str, APIChange],
) -> None:
    old_security = _effective_security(old_specification, old)
    new_security = _effective_security(new_specification, new)
    if old_security == new_security:
        return
    classification = (
        BreakingClassification.CLIENT_BREAKING
        if not old_security and new_security
        else BreakingClassification.POTENTIALLY_BREAKING
    )
    _record(
        changes,
        category=ChangeCategory.SECURITY_REQUIREMENT_CHANGED,
        path=old.path,
        method=old.method,
        location="security",
        old_value=_security_value(old_security),
        new_value=_security_value(new_security),
        severity=ChangeSeverity.HIGH,
        classification=classification,
        direction=CompatibilityDirection.CLIENT_TO_SERVER,
        certainty=ChangeCertainty.EXACT,
        reason="The effective OpenAPI security requirement changed for this operation.",
        assumptions=("Security alternatives are OR-ed; schemes in each alternative are AND-ed.",),
        evidence={
            "old_security_source": "operation" if old.security is not None else "root",
            "new_security_source": "operation" if new.security is not None else "root",
        },
    )


def _compare_request_body(
    old_specification: APISpecification,
    new_specification: APISpecification,
    old: APIOperation,
    new: APIOperation,
    changes: dict[str, APIChange],
) -> None:
    old_body = _resolve_request_body(old_specification, old.request_body)
    new_body = _resolve_request_body(new_specification, new.request_body)
    if old_body is None or new_body is None:
        return
    for media_type in sorted(set(old_body.content) & set(new_body.content)):
        old_schema = old_body.content[media_type]
        new_schema = new_body.content[media_type]
        if old_schema is None or new_schema is None:
            continue
        _compare_schema(
            old_specification,
            new_specification,
            old_schema,
            new_schema,
            context=_REQUEST,
            path=old.path,
            method=old.method,
            location=f"request.body[{media_type}]",
            media_type=media_type,
            changes=changes,
            active_references=set(),
        )


def _compare_responses(
    old_specification: APISpecification,
    new_specification: APISpecification,
    old: APIOperation,
    new: APIOperation,
    changes: dict[str, APIChange],
) -> None:
    for code in sorted(set(old.responses) & set(new.responses)):
        old_response = _resolve_response(old_specification, old.responses[code])
        new_response = _resolve_response(new_specification, new.responses[code])
        if old_response is None or new_response is None:
            continue
        for media_type in sorted(set(old_response.content) & set(new_response.content)):
            old_schema = old_response.content[media_type]
            new_schema = new_response.content[media_type]
            if old_schema is None or new_schema is None:
                continue
            _compare_schema(
                old_specification,
                new_specification,
                old_schema,
                new_schema,
                context=_RESPONSE,
                path=old.path,
                method=old.method,
                location=f"response.{code}[{media_type}]",
                media_type=media_type,
                changes=changes,
                active_references=set(),
            )


def _compare_schema(
    old_specification: APISpecification,
    new_specification: APISpecification,
    old_schema: Schema,
    new_schema: Schema,
    *,
    context: str,
    path: str,
    method: str,
    location: str,
    media_type: str,
    changes: dict[str, APIChange],
    active_references: set[tuple[str, str]],
) -> None:
    reference_pair = (
        old_schema.reference.target if old_schema.reference is not None else "",
        new_schema.reference.target if new_schema.reference is not None else "",
    )
    tracks_reference = bool(reference_pair[0] and reference_pair[1])
    if tracks_reference and reference_pair in active_references:
        return
    if tracks_reference:
        active_references.add(reference_pair)
    old_resolved = _resolve_schema(old_specification, old_schema)
    new_resolved = _resolve_schema(new_specification, new_schema)
    if old_resolved is None or new_resolved is None:
        if tracks_reference:
            active_references.remove(reference_pair)
        return
    old_schema, old_notes = old_resolved
    new_schema, new_notes = new_resolved
    certainty, assumptions = _schema_certainty(old_schema, new_schema, old_notes, new_notes)

    if old_schema.types != new_schema.types:
        _record(
            changes,
            category=(
                ChangeCategory.REQUEST_PROPERTY_TYPE_CHANGED
                if context == _REQUEST
                else ChangeCategory.RESPONSE_PROPERTY_TYPE_CHANGED
            ),
            path=path,
            method=method,
            location=location,
            old_value=_schema_value(old_schema),
            new_value=_schema_value(new_schema),
            severity=ChangeSeverity.HIGH,
            classification=BreakingClassification.CLIENT_BREAKING,
            direction=(
                CompatibilityDirection.CLIENT_TO_SERVER
                if context == _REQUEST
                else CompatibilityDirection.SERVER_TO_CLIENT
            ),
            certainty=certainty,
            reason=(
                "The request property type changed."
                if context == _REQUEST
                else "The response property type changed."
            ),
            assumptions=assumptions,
            evidence={
                "media_type": media_type,
                "old_types": list(old_schema.types),
                "new_types": list(new_schema.types),
            },
        )

    if old_schema.nullable and not new_schema.nullable:
        _record(
            changes,
            category=ChangeCategory.NULLABLE_REMOVED,
            path=path,
            method=method,
            location=location,
            old_value=_schema_value(old_schema),
            new_value=_schema_value(new_schema),
            severity=ChangeSeverity.MEDIUM,
            classification=(
                BreakingClassification.CLIENT_BREAKING
                if context == _REQUEST
                else BreakingClassification.POTENTIALLY_BREAKING
            ),
            direction=(
                CompatibilityDirection.CLIENT_TO_SERVER
                if context == _REQUEST
                else CompatibilityDirection.SERVER_TO_CLIENT
            ),
            certainty=certainty,
            reason="The normalized schema no longer permits null.",
            assumptions=(
                *assumptions,
                *(
                    ("Existing response consumers may depend on null as a semantic value.",)
                    if context == _RESPONSE
                    else ()
                ),
            ),
            evidence={"media_type": media_type, "old_nullable": True, "new_nullable": False},
        )

    removed_enum = _removed_enum_values(old_schema, new_schema)
    if removed_enum:
        _record(
            changes,
            category=ChangeCategory.ENUM_RESTRICTED,
            path=path,
            method=method,
            location=location,
            old_value={"enum": list(old_schema.enum)},
            new_value={"enum": list(new_schema.enum)},
            severity=ChangeSeverity.MEDIUM,
            classification=(
                BreakingClassification.CLIENT_BREAKING
                if context == _REQUEST
                else BreakingClassification.POTENTIALLY_BREAKING
            ),
            direction=(
                CompatibilityDirection.CLIENT_TO_SERVER
                if context == _REQUEST
                else CompatibilityDirection.SERVER_TO_CLIENT
            ),
            certainty=certainty,
            reason="Values previously allowed by the documented enum are absent from the new enum.",
            assumptions=(
                *assumptions,
                *(
                    ("Existing response consumers may depend on removed enum values.",)
                    if context == _RESPONSE
                    else ()
                ),
            ),
            evidence={"media_type": media_type, "removed_enum_values": removed_enum},
        )

    old_properties = {property.name: property for property in old_schema.properties}
    new_properties = {property.name: property for property in new_schema.properties}
    for name in sorted(old_properties):
        old_property = old_properties[name]
        new_property = new_properties.get(name)
        property_location = f"{location}.{name}"
        if new_property is None:
            _record(
                changes,
                category=(
                    ChangeCategory.REQUEST_PROPERTY_REMOVED
                    if context == _REQUEST
                    else ChangeCategory.RESPONSE_PROPERTY_REMOVED
                ),
                path=path,
                method=method,
                location=property_location,
                old_value=_property_value(old_property.required, old_property.schema_definition),
                new_value=None,
                severity=(ChangeSeverity.MEDIUM if context == _REQUEST else ChangeSeverity.HIGH),
                classification=(
                    BreakingClassification.POTENTIALLY_BREAKING
                    if context == _REQUEST
                    else BreakingClassification.CLIENT_BREAKING
                ),
                direction=(
                    CompatibilityDirection.CLIENT_TO_SERVER
                    if context == _REQUEST
                    else CompatibilityDirection.SERVER_TO_CLIENT
                ),
                certainty=(
                    ChangeCertainty.CONDITIONAL
                    if context == _REQUEST and certainty is ChangeCertainty.EXACT
                    else certainty
                ),
                reason=(
                    "The request property is absent from the new documented schema."
                    if context == _REQUEST
                    else "The response property is absent from the new documented schema."
                ),
                assumptions=(
                    *assumptions,
                    *(
                        (
                            "Existing clients may still send this property; incompatibility "
                            "depends on the new server's unknown-field handling.",
                        )
                        if context == _REQUEST
                        else ()
                    ),
                ),
                evidence={"media_type": media_type, "property": name},
            )
            continue
        _compare_schema(
            old_specification,
            new_specification,
            old_property.schema_definition,
            new_property.schema_definition,
            context=context,
            path=path,
            method=method,
            location=property_location,
            media_type=media_type,
            changes=changes,
            active_references=active_references,
        )

    if old_schema.items is not None and new_schema.items is not None:
        _compare_schema(
            old_specification,
            new_specification,
            old_schema.items,
            new_schema.items,
            context=context,
            path=path,
            method=method,
            location=f"{location}.items[]",
            media_type=media_type,
            changes=changes,
            active_references=active_references,
        )
    if tracks_reference:
        active_references.remove(reference_pair)


def _record(
    changes: dict[str, APIChange],
    *,
    category: ChangeCategory,
    path: str,
    method: str,
    location: str,
    old_value: object,
    new_value: object,
    severity: ChangeSeverity,
    classification: BreakingClassification,
    direction: CompatibilityDirection,
    certainty: ChangeCertainty,
    reason: str,
    assumptions: tuple[str, ...] = (),
    evidence: object,
) -> None:
    payload = {
        "category": category.value,
        "path": path,
        "method": method,
        "location": location,
        "old_value": old_value,
        "new_value": new_value,
    }
    identifier = (
        "api-change-"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
    )
    changes[identifier] = APIChange(
        id=identifier,
        category=category,
        path=path,
        method=method,
        location=location,
        old_value=cast(JsonValue | None, old_value),
        new_value=cast(JsonValue | None, new_value),
        severity=severity,
        breaking_classification=classification,
        compatibility_direction=direction,
        certainty=certainty,
        reason=reason,
        assumptions=assumptions,
        evidence=cast(dict[str, JsonValue], evidence),
    )


def _parameter_index(
    specification: APISpecification, parameters: tuple[Parameter, ...]
) -> dict[tuple[str, str], Parameter]:
    result: dict[tuple[str, str], Parameter] = {}
    for parameter in parameters:
        resolved = _resolve_component(
            specification, parameter, specification.parameters, "parameters"
        )
        if (
            isinstance(resolved, Parameter)
            and resolved.name is not None
            and resolved.location is not None
        ):
            result[(resolved.name, resolved.location)] = resolved
    return result


def _resolve_request_body(
    specification: APISpecification, body: RequestBody | None
) -> RequestBody | None:
    resolved = _resolve_component(
        specification, body, specification.request_bodies, "requestBodies"
    )
    return resolved if isinstance(resolved, RequestBody) else None


def _resolve_response(specification: APISpecification, response: Response) -> Response | None:
    resolved = _resolve_component(specification, response, specification.responses, "responses")
    return resolved if isinstance(resolved, Response) else None


def _resolve_component(
    specification: APISpecification,
    value: _T | None,
    components: dict[str, _T],
    component_name: str,
) -> _T | None:
    if value is None:
        return None
    reference = getattr(value, "reference", None)
    if reference is None:
        return value
    prefix = f"#/components/{component_name}/"
    if reference.resolution_state is not ResolutionState.EXACT or not reference.target.startswith(
        prefix
    ):
        return None
    return components.get(reference.target.removeprefix(prefix))


def _resolve_schema(
    specification: APISpecification, schema: Schema
) -> tuple[Schema, tuple[str, ...]] | None:
    notes: list[str] = []
    seen: set[str] = set()
    current = schema
    while current.reference is not None:
        reference = current.reference
        prefix = "#/components/schemas/"
        if (
            reference.resolution_state is not ResolutionState.EXACT
            or not reference.target.startswith(prefix)
        ):
            return None
        if reference.target in seen:
            return None
        seen.add(reference.target)
        target = specification.schemas.get(reference.target.removeprefix(prefix))
        if target is None:
            return None
        notes.append(f"Resolved internal reference {reference.target} through contract metadata.")
        current = target
    return current, tuple(notes)


def _schema_certainty(
    old: Schema, new: Schema, old_notes: tuple[str, ...], new_notes: tuple[str, ...]
) -> tuple[ChangeCertainty, tuple[str, ...]]:
    statuses = (old.support_status, new.support_status)
    composition = old.all_of or old.one_of or old.any_of or new.all_of or new.one_of or new.any_of
    if SupportStatus.UNSUPPORTED in statuses:
        return ChangeCertainty.UNRESOLVED, (
            *old_notes,
            *new_notes,
            "Schema parser marked a compared schema as unsupported; no exact compatibility "
            "conclusion is claimed.",
        )
    if SupportStatus.PARTIALLY_SUPPORTED in statuses or composition:
        return ChangeCertainty.PARTIAL, (
            *old_notes,
            *new_notes,
            *(
                ("Preserved partially supported schema structure.",)
                if SupportStatus.PARTIALLY_SUPPORTED in statuses
                else ()
            ),
            *(
                ("Schema composition is preserved but not solved for full subsumption.",)
                if composition
                else ()
            ),
        )
    return ChangeCertainty.EXACT, (*old_notes, *new_notes)


def _effective_security(
    specification: APISpecification, operation: APIOperation
) -> SecurityRequirements:
    return specification.security if operation.security is None else operation.security


def _security_value(requirements: SecurityRequirements) -> list[dict[str, list[str]]]:
    return [
        {requirement.scheme: list(requirement.scopes) for requirement in group}
        for group in requirements
    ]


def _parameter_value(parameter: Parameter | None) -> dict[str, JsonValue] | None:
    if parameter is None:
        return None
    return {
        "name": parameter.name,
        "location": parameter.location,
        "required": parameter.required,
    }


def _schema_value(schema: Schema) -> dict[str, JsonValue]:
    return {
        "type": schema.type,
        "types": list(schema.types),
        "format": schema.format,
        "nullable": schema.nullable,
        "enum": list(schema.enum),
        "support_status": schema.support_status.value,
    }


def _property_value(required: bool, schema: Schema) -> dict[str, JsonValue]:
    return {"required": required, **_schema_value(schema)}


def _removed_enum_values(old: Schema, new: Schema) -> list[str | int | float | bool | None]:
    if not old.enum or not new.enum:
        return []
    new_values = {_semantic_value(value) for value in new.enum}
    return [value for value in old.enum if _semantic_value(value) not in new_values]


def _semantic_value(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
