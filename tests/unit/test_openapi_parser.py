from pathlib import Path

import pytest
from opentrace.contracts.errors import (
    InvalidSpecificationError,
    ReferenceResolutionError,
    UnsupportedOpenAPIVersionError,
)
from opentrace.contracts.models import ResolutionState, SupportStatus
from opentrace.contracts.parser import OpenAPIParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "openapi"


def test_normalizes_operations_parameters_schemas_and_security() -> None:
    specification = OpenAPIParser().parse_file(FIXTURES / "payment.yaml")

    assert specification.openapi_version == "3.0.3"
    assert specification.servers == ("https://api.example.test/v1",)
    assert [operation.id for operation in specification.operations] == [
        "GET /payments/{payment_id}",
        "PATCH /payments/{payment_id}",
    ]
    get_payment = specification.operations[0]
    assert [parameter.name for parameter in get_payment.parameters] == ["payment_id", "expand"]
    assert get_payment.parameters[0].required is True
    assert get_payment.responses["200"].content["application/problem+json"] is None
    assert get_payment.responses["default"].reference is not None
    assert get_payment.responses["default"].reference.resolution_state is ResolutionState.EXACT
    assert specification.security[0][0].scopes == ("payments:write",)
    assert specification.security_schemes["bearerAuth"].scheme == "bearer"

    payment = specification.schemas["Payment"]
    assert payment.required_properties == ("amount", "status")
    assert [(property.name, property.required) for property in payment.properties] == [
        ("amount", True),
        ("metadata", False),
        ("status", True),
        ("tags", False),
    ]
    assert payment.properties[2].schema_definition.enum == ("failed", "paid", "pending")
    assert payment.properties[3].schema_definition.items is not None
    assert payment.properties[3].schema_definition.items.type == "string"
    assert payment.properties[1].schema_definition.additional_properties_schema is not None
    update = specification.schemas["PaymentUpdate"]
    assert update.all_of[0].reference is not None
    assert update.all_of[1].properties[0].schema_definition.nullable is True
    assert specification.schemas["PaymentChoice"].one_of
    assert specification.schemas["PaymentEither"].any_of


def test_yaml_and_json_normalize_to_identical_canonical_json() -> None:
    parser = OpenAPIParser()

    yaml_specification = parser.parse_file(FIXTURES / "equivalent.yaml")
    json_specification = parser.parse_file(FIXTURES / "equivalent.json")

    assert yaml_specification.canonical_json() == json_specification.canonical_json()


@pytest.mark.parametrize(
    ("document", "error", "message"),
    [
        ("", InvalidSpecificationError, "empty"),
        ("[]", InvalidSpecificationError, "top level must be a mapping"),
        ("info: {}\npaths: {}", InvalidSpecificationError, '"openapi"'),
        (
            "openapi: 2.0\ninfo: {title: Test, version: '1'}\npaths: {}",
            UnsupportedOpenAPIVersionError,
            "Unsupported OpenAPI version",
        ),
        ("openapi: [", InvalidSpecificationError, "not valid YAML or JSON"),
        (
            (
                "openapi: 3.0.3\ninfo: {title: Test, version: '1'}\npaths: {}\n"
                "value: !!python/object/apply:os.system ['echo unsafe']"
            ),
            InvalidSpecificationError,
            "not valid YAML or JSON",
        ),
    ],
)
def test_rejects_malformed_or_unsafe_documents(
    document: str, error: type[ValueError], message: str
) -> None:
    with pytest.raises(error, match=message):
        OpenAPIParser().parse_text(document)


def test_unknown_path_keys_do_not_become_operations() -> None:
    specification = OpenAPIParser().parse_text(
        """
        openapi: 3.0.3
        info: {title: Test, version: '1'}
        paths:
          /widgets:
            summary: Not an operation
            description: Also not an operation
            servers: []
            parameters: []
            post:
              responses: {'200': {description: OK}}
        """
    )

    assert [operation.id for operation in specification.operations] == ["POST /widgets"]

    with pytest.raises(InvalidSpecificationError, match="unsupported path item field"):
        OpenAPIParser().parse_text(
            """
            openapi: 3.0.3
            info: {title: Unknown Method, version: '1'}
            paths:
              /widgets:
                fetch:
                  responses: {'200': {description: OK}}
            """
        )


def test_references_are_validated_and_cycles_remain_reference_nodes() -> None:
    parser = OpenAPIParser()
    specification = parser.parse_text(
        """
        openapi: 3.1.0
        info: {title: Cycles, version: '1'}
        paths: {}
        components:
          schemas:
            Node:
              type: object
              properties:
                child: {$ref: '#/components/schemas/Node'}
        """
    )

    child = specification.schemas["Node"].properties[0].schema_definition
    assert child.reference is not None
    assert child.reference.target == "#/components/schemas/Node"

    with pytest.raises(ReferenceResolutionError, match="does not exist"):
        parser.parse_text(
            """
            openapi: 3.0.3
            info: {title: Missing, version: '1'}
            paths: {}
            components:
              schemas:
                Broken: {$ref: '#/components/schemas/Missing'}
            """
        )

    with pytest.raises(ReferenceResolutionError, match="Malformed"):
        parser.parse_text(
            """
            openapi: 3.0.3
            info: {title: Malformed, version: '1'}
            paths: {}
            components:
              schemas:
                Broken: {$ref: '#'}
            """
        )


def test_common_internal_component_reference_kinds_are_preserved() -> None:
    specification = OpenAPIParser().parse_text(
        """
        openapi: 3.0.3
        info: {title: Component References, version: '1'}
        paths:
          /widgets:
            parameters:
              - {$ref: '#/components/parameters/Locale'}
            post:
              requestBody: {$ref: '#/components/requestBodies/Widget'}
              responses:
                default: {$ref: '#/components/responses/Error'}
        components:
          parameters:
            Locale: {name: locale, in: query, schema: {type: string}}
          requestBodies:
            Widget:
              content: {application/json: {schema: {type: object}}}
          responses:
            Error: {description: Error}
        """
    )

    operation = specification.operations[0]
    assert operation.parameters[0].reference is not None
    assert operation.parameters[0].reference.kind == "components/parameters"
    assert operation.request_body is not None
    assert operation.request_body.reference is not None
    assert operation.request_body.reference.kind == "components/requestBodies"
    assert operation.responses["default"].reference is not None
    assert operation.responses["default"].reference.kind == "components/responses"


def test_external_references_are_explicitly_unsupported() -> None:
    specification = OpenAPIParser().parse_text(
        """
        openapi: 3.2.0
        info: {title: External, version: '1'}
        paths: {}
        components:
          schemas:
            Remote: {$ref: 'https://example.test/schema.yaml#/Thing'}
        """
    )

    reference = specification.schemas["Remote"].reference
    assert reference is not None
    assert reference.resolution_state is ResolutionState.UNSUPPORTED
    assert specification.schemas["Remote"].support_status is SupportStatus.UNSUPPORTED


def test_rejects_invalid_path_parameter_and_preserves_multiple_response_codes() -> None:
    parser = OpenAPIParser()
    with pytest.raises(InvalidSpecificationError, match="must be required"):
        parser.parse_text(
            """
            openapi: 3.0.3
            info: {title: Invalid Parameter, version: '1'}
            paths:
              /widgets/{id}:
                parameters:
                  - name: id
                    in: path
                    required: false
                    schema: {type: string}
                get:
                  responses: {'200': {description: OK}}
            """
        )

    specification = parser.parse_text(
        """
        openapi: 3.0.3
        info: {title: Responses, version: '1'}
        paths:
          /widgets:
            get:
              responses:
                '200': {description: OK}
                '404': {description: Missing}
                default: {description: Error}
        """
    )
    assert list(specification.operations[0].responses) == ["200", "404", "default"]


def test_rejects_empty_responses() -> None:
    with pytest.raises(InvalidSpecificationError, match="responses must not be empty"):
        OpenAPIParser().parse_text(
            """
            openapi: 3.0.3
            info: {title: Empty Responses, version: '1'}
            paths:
              /widgets:
                get:
                  responses: {}
            """
        )


def test_unknown_schema_structure_is_explicitly_partial() -> None:
    specification = OpenAPIParser().parse_text(
        """
        openapi: 3.1.0
        info: {title: Partial Schema, version: '1'}
        paths: {}
        components:
          schemas:
            Custom: {type: string, unevaluatedProperties: false}
        """
    )

    schema = specification.schemas["Custom"]
    assert schema.support_status is SupportStatus.PARTIALLY_SUPPORTED
    assert schema.warnings == ("unsupported schema fields: unevaluatedProperties",)
