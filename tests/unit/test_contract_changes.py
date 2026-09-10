import json

from opentrace.contracts.changes import compare_specifications
from opentrace.contracts.models import (
    BreakingClassification,
    ChangeCategory,
    ChangeCertainty,
    CompatibilityDirection,
)
from opentrace.contracts.parser import OpenAPIParser


def _specification(
    paths: dict[str, object],
    *,
    components: dict[str, object] | None = None,
    security: list[dict[str, list[str]]] | None = None,
    openapi: str = "3.0.3",
) -> object:
    document: dict[str, object] = {
        "openapi": openapi,
        "info": {"title": "M2 fixture", "version": "1"},
        "paths": paths,
    }
    if components is not None:
        document["components"] = components
    if security is not None:
        document["security"] = security
    return OpenAPIParser().parse_text(json.dumps(document))


def _operation(
    *,
    parameters: list[dict[str, object]] | None = None,
    request_schema: dict[str, object] | None = None,
    response_schema: dict[str, object] | None = None,
    response_code: str = "200",
    security: list[dict[str, list[str]]] | None = None,
) -> dict[str, object]:
    operation: dict[str, object] = {
        "responses": {
            response_code: {
                "description": "OK",
                **(
                    {"content": {"application/json": {"schema": response_schema}}}
                    if response_schema is not None
                    else {}
                ),
            }
        }
    }
    if parameters is not None:
        operation["parameters"] = parameters
    if request_schema is not None:
        operation["requestBody"] = {"content": {"application/json": {"schema": request_schema}}}
    if security is not None:
        operation["security"] = security
    return operation


def _changes(old_paths: dict[str, object], new_paths: dict[str, object], **kwargs: object):
    return compare_specifications(
        _specification(old_paths, **kwargs), _specification(new_paths, **kwargs)
    )


def test_endpoint_and_method_removal_are_distinct_client_breaks() -> None:
    old = {
        "/gone": {"get": _operation()},
        "/retained": {"get": _operation(), "post": _operation()},
    }
    new = {"/retained": {"get": _operation()}}

    changes = _changes(old, new)

    assert [(change.category, change.path, change.method) for change in changes] == [
        (ChangeCategory.ENDPOINT_REMOVED, "/gone", "GET"),
        (ChangeCategory.HTTP_METHOD_REMOVED, "/retained", "POST"),
    ]
    assert all(
        change.breaking_classification is BreakingClassification.CLIENT_BREAKING
        for change in changes
    )
    assert all(
        change.compatibility_direction is CompatibilityDirection.CLIENT_TO_SERVER
        for change in changes
    )


def test_required_parameter_uses_name_and_location_identity() -> None:
    old = {"/orders": {"get": _operation(parameters=[{"name": "id", "in": "query"}])}}
    new = {
        "/orders": {
            "get": _operation(
                parameters=[
                    {"name": "id", "in": "query", "required": True},
                    {"name": "id", "in": "header", "required": False},
                ]
            )
        }
    }

    changes = _changes(old, new)

    assert len(changes) == 1
    change = changes[0]
    assert change.category is ChangeCategory.REQUIRED_PARAMETER_ADDED
    assert change.location == "parameter.query.id"
    assert change.old_value == {"name": "id", "location": "query", "required": False}
    assert change.new_value == {"name": "id", "location": "query", "required": True}
    assert change.reason


def test_request_schema_rules_preserve_nested_and_array_locations() -> None:
    old_schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "number"},
            "remove_me": {"type": "string"},
            "customer": {"type": "object", "properties": {"zip": {"type": "string"}}},
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"price": {"type": "number"}}},
            },
        },
    }
    new_schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer"},
            "customer": {"type": "object", "properties": {"zip": {"type": "integer"}}},
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"price": {"type": "integer"}}},
            },
        },
    }
    old = {"/orders": {"post": _operation(request_schema=old_schema)}}
    new = {"/orders": {"post": _operation(request_schema=new_schema)}}

    changes = _changes(old, new)
    categories = {change.category for change in changes}
    locations = {change.location for change in changes}

    assert ChangeCategory.REQUEST_PROPERTY_REMOVED in categories
    assert ChangeCategory.REQUEST_PROPERTY_TYPE_CHANGED in categories
    assert "request.body[application/json].remove_me" in locations
    assert "request.body[application/json].customer.zip" in locations
    assert "request.body[application/json].items.items[].price" in locations
    removal = next(
        change for change in changes if change.category is ChangeCategory.REQUEST_PROPERTY_REMOVED
    )
    assert removal.breaking_classification is BreakingClassification.POTENTIALLY_BREAKING
    assert removal.certainty is ChangeCertainty.CONDITIONAL
    assert removal.assumptions


def test_response_schema_rules_keep_response_codes_and_context_separate() -> None:
    old_schema = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "old": {"type": "string"}},
    }
    new_schema = {"type": "object", "properties": {"id": {"type": "string"}}}
    old = {"/orders": {"get": _operation(response_schema=old_schema)}}
    new = {"/orders": {"get": _operation(response_schema=new_schema)}}

    changes = _changes(old, new)

    assert {change.category for change in changes} == {
        ChangeCategory.RESPONSE_PROPERTY_REMOVED,
        ChangeCategory.RESPONSE_PROPERTY_TYPE_CHANGED,
    }
    assert {change.location for change in changes} == {
        "response.200[application/json].id",
        "response.200[application/json].old",
    }
    assert all(
        change.compatibility_direction is CompatibilityDirection.SERVER_TO_CLIENT
        for change in changes
    )


def test_security_uses_effective_and_or_semantics_without_order_false_positives() -> None:
    old = {"/orders": {"get": _operation()}}
    new = {"/orders": {"get": _operation()}}
    reordered = compare_specifications(
        _specification(old, security=[{"oauth": ["write"], "key": []}, {"basic": []}]),
        _specification(new, security=[{"basic": []}, {"key": [], "oauth": ["write"]}]),
    )
    secured = compare_specifications(
        _specification(old),
        _specification(new, security=[{"key": []}]),
    )

    assert reordered == ()
    assert len(secured) == 1
    assert secured[0].category is ChangeCategory.SECURITY_REQUIREMENT_CHANGED
    assert secured[0].breaking_classification is BreakingClassification.CLIENT_BREAKING
    assert secured[0].evidence["old_security_source"] == "root"


def test_enum_and_nullability_are_context_aware_and_normalized() -> None:
    old = {
        "/orders": {
            "post": _operation(
                request_schema={"type": "string", "nullable": True, "enum": ["pending", "paid"]},
                response_schema={"type": "string", "nullable": True, "enum": ["pending", "paid"]},
            )
        }
    }
    new = {
        "/orders": {
            "post": _operation(
                request_schema={"type": "string", "enum": ["paid"]},
                response_schema={"type": "string", "enum": ["paid"]},
            )
        }
    }
    changes = _changes(old, new)

    assert [change.category for change in changes].count(ChangeCategory.ENUM_RESTRICTED) == 2
    assert [change.category for change in changes].count(ChangeCategory.NULLABLE_REMOVED) == 2
    assert any(
        change.category is ChangeCategory.ENUM_RESTRICTED
        and change.compatibility_direction is CompatibilityDirection.CLIENT_TO_SERVER
        and change.breaking_classification is BreakingClassification.CLIENT_BREAKING
        for change in changes
    )
    equivalent_nullability = compare_specifications(
        _specification(
            {"/orders": {"post": _operation(request_schema={"type": "string", "nullable": True})}}
        ),
        _specification(
            {"/orders": {"post": _operation(request_schema={"type": ["string", "null"]})}},
            openapi="3.1.0",
        ),
    )
    assert not [
        change
        for change in equivalent_nullability
        if change.category is ChangeCategory.NULLABLE_REMOVED
    ]


def test_referenced_schemas_and_partial_support_propagate_without_fake_exactness() -> None:
    old_paths = {
        "/orders": {"post": _operation(request_schema={"$ref": "#/components/schemas/Order"})}
    }
    new_paths = {
        "/orders": {"post": _operation(request_schema={"$ref": "#/components/schemas/Order"})}
    }
    old = _specification(
        old_paths,
        components={
            "schemas": {"Order": {"type": "object", "properties": {"amount": {"type": "number"}}}}
        },
    )
    new = _specification(
        new_paths,
        components={
            "schemas": {
                "Order": {
                    "type": "object",
                    "properties": {"amount": {"type": "integer", "unevaluatedProperties": False}},
                }
            }
        },
    )

    changes = compare_specifications(old, new)

    assert len(changes) == 1
    assert changes[0].category is ChangeCategory.REQUEST_PROPERTY_TYPE_CHANGED
    assert changes[0].certainty is ChangeCertainty.PARTIAL
    assert changes[0].assumptions


def test_deterministic_results_and_compatible_noise_produce_no_changes() -> None:
    original = {
        "/orders": {
            "get": _operation(parameters=[{"name": "page", "in": "query"}]),
        }
    }
    compatible = {
        "/orders": {
            "get": _operation(
                parameters=[{"name": "page", "in": "query"}, {"name": "limit", "in": "query"}]
            ),
        },
        "/new": {"post": _operation()},
    }
    old = _specification(original)
    new = _specification(compatible)

    assert compare_specifications(old, old) == ()
    assert compare_specifications(old, new) == ()
    repeated = [compare_specifications(old, new) for _ in range(3)]
    assert repeated[0] == repeated[1] == repeated[2]


def test_semantic_reordering_and_metadata_changes_are_not_contract_changes() -> None:
    old_schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string", "enum": ["one", "two"]},
            "b": {"type": "integer"},
        },
    }
    new_schema = {
        "type": "object",
        "properties": {
            "b": {"type": "integer", "description": "rewritten"},
            "a": {"type": "string", "enum": ["two", "one"]},
        },
    }
    old_operation = _operation(response_schema=old_schema)
    old_operation.update({"operationId": "oldName", "summary": "old", "tags": ["a", "b"]})
    new_operation = _operation(response_schema=new_schema)
    new_operation.update({"operationId": "newName", "summary": "new", "tags": ["b", "a"]})

    assert (
        compare_specifications(
            _specification({"/orders": {"get": old_operation}}),
            _specification({"/orders": {"get": new_operation}}),
        )
        == ()
    )


def test_unsupported_external_reference_is_not_presented_as_exact_comparison() -> None:
    old = _specification(
        {
            "/orders": {
                "post": _operation(
                    request_schema={"$ref": "https://example.test/order.yaml#/Order"}
                )
            }
        }
    )
    new = _specification({"/orders": {"post": _operation(request_schema={"type": "object"})}})

    assert compare_specifications(old, new) == ()
