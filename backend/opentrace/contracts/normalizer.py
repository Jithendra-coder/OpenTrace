"""Deterministic OpenAPI 3.x normalization without compatibility analysis."""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from opentrace.contracts.errors import InvalidSpecificationError, UnsupportedOpenAPIVersionError
from opentrace.contracts.models import (
    APIOperation,
    APISpecification,
    Header,
    NormalizationMetadata,
    Parameter,
    RequestBody,
    ResolutionState,
    Response,
    Schema,
    SchemaProperty,
    SecurityRequirement,
    SecurityRequirements,
    SecurityScheme,
    SupportStatus,
)
from opentrace.contracts.references import ReferenceResolver

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
_PARAMETER_LOCATIONS = frozenset({"path", "query", "header", "cookie"})
_PATH_ITEM_FIELDS = frozenset({"$ref", "summary", "description", "servers", "parameters"})
_SCHEMA_FIELDS = frozenset(
    {
        "$ref",
        "type",
        "format",
        "nullable",
        "enum",
        "properties",
        "items",
        "required",
        "additionalProperties",
        "allOf",
        "oneOf",
        "anyOf",
        "description",
        "title",
        "default",
        "example",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "xml",
        "externalDocs",
        "discriminator",
        "not",
    }
)
T = TypeVar("T")


class OpenAPINormalizer:
    """Normalize a parser-boundary mapping into canonical domain models."""

    def normalize(self, document: Mapping[str, Any]) -> APISpecification:
        version = self._openapi_version(document)
        info = self._mapping(document.get("info"), 'missing required top-level "info" mapping')
        title = self._string(info.get("title"), 'missing required "info.title"')
        document_version = self._string(info.get("version"), 'missing required "info.version"')
        paths = self._mapping(document.get("paths"), 'missing required top-level "paths" mapping')
        resolver = ReferenceResolver(document)
        components = self._mapping_or_empty(document.get("components"), "components")

        schemas: dict[str, Schema] = self._component_map(
            components,
            "schemas",
            lambda name, value: self._schema(value, f"#/components/schemas/{name}", resolver),
        )
        parameters: dict[str, Parameter] = self._component_map(
            components,
            "parameters",
            lambda name, value: self._parameter(value, f"#/components/parameters/{name}", resolver),
        )
        responses: dict[str, Response] = self._component_map(
            components,
            "responses",
            lambda name, value: self._response(
                value, f"#/components/responses/{name}", None, resolver
            ),
        )
        request_bodies: dict[str, RequestBody] = self._component_map(
            components,
            "requestBodies",
            lambda name, value: self._request_body(
                value, f"#/components/requestBodies/{name}", resolver
            ),
        )
        security_schemes: dict[str, SecurityScheme] = self._component_map(
            components,
            "securitySchemes",
            lambda name, value: self._security_scheme(name, value, resolver),
        )

        operations = self._operations(paths, resolver)
        servers = tuple(
            sorted(
                self._string(self._mapping(server, "server").get("url"), "server requires a URL")
                for server in self._sequence_or_empty(document.get("servers"), "servers")
            )
        )
        security = self._security(document.get("security"), "security")
        return APISpecification(
            id=f"{title}:{document_version}",
            openapi_version=version,
            title=title,
            version=document_version,
            servers=servers,
            operations=operations,
            schemas=schemas,
            parameters=parameters,
            responses=responses,
            request_bodies=request_bodies,
            security_schemes=security_schemes,
            security=security,
            normalization=NormalizationMetadata(),
        )

    def _operations(
        self, paths: Mapping[str, Any], resolver: ReferenceResolver
    ) -> tuple[APIOperation, ...]:
        operations: list[APIOperation] = []
        for raw_path, path_item in sorted(paths.items()):
            path = self._path(raw_path)
            item = self._mapping(path_item, f"path item {path}")
            inherited_parameters = self._parameters(
                item.get("parameters"), f"{path} parameters", resolver
            )
            if "$ref" in item:
                resolver.reference(item["$ref"])
            for raw_method, operation in sorted(item.items()):
                method = str(raw_method).lower()
                if method not in _HTTP_METHODS:
                    if not str(raw_method).startswith("x-") and raw_method not in _PATH_ITEM_FIELDS:
                        raise InvalidSpecificationError(
                            f"unsupported path item field {raw_method!r} at {path}"
                        )
                    continue
                operation_data = self._mapping(operation, f"{method.upper()} {path}")
                operation_id = operation_data.get("operationId")
                if operation_id is not None and not isinstance(operation_id, str):
                    raise InvalidSpecificationError(
                        f"operationId for {method.upper()} {path} must be a string"
                    )
                own_parameters = self._parameters(
                    operation_data.get("parameters"),
                    f"{method.upper()} {path} parameters",
                    resolver,
                )
                parameters = tuple(
                    sorted((*inherited_parameters, *own_parameters), key=lambda value: value.id)
                )
                request_body = (
                    self._request_body(
                        operation_data["requestBody"],
                        f"{method.upper()} {path} requestBody",
                        resolver,
                    )
                    if "requestBody" in operation_data
                    else None
                )
                responses_data = self._mapping(
                    operation_data.get("responses"), f"{method.upper()} {path} responses"
                )
                if not responses_data:
                    raise InvalidSpecificationError(
                        f"{method.upper()} {path} responses must not be empty"
                    )
                responses = {
                    str(code): self._response(
                        value, f"{method.upper()} {path} responses/{code}", str(code), resolver
                    )
                    for code, value in sorted(responses_data.items())
                }
                tags = self._string_sequence(
                    operation_data.get("tags"), f"{method.upper()} {path} tags"
                )
                summary = self._optional_string(operation_data.get("summary"), "summary")
                description = self._optional_string(
                    operation_data.get("description"), "description"
                )
                operations.append(
                    APIOperation(
                        id=f"{method.upper()} {path}",
                        method=method.upper(),
                        path=path,
                        operation_id=operation_id,
                        tags=tags,
                        summary=summary,
                        description=description,
                        parameters=parameters,
                        request_body=request_body,
                        responses=responses,
                        security=(
                            self._security(
                                operation_data["security"], f"{method.upper()} {path} security"
                            )
                            if "security" in operation_data
                            else None
                        ),
                    )
                )
        return tuple(sorted(operations, key=lambda operation: operation.id))

    def _schema(self, value: object, identifier: str, resolver: ReferenceResolver) -> Schema:
        data = self._mapping(value, f"schema {identifier}")
        reference = resolver.reference(data["$ref"]) if "$ref" in data else None
        types, nullable, status, warnings = self._schema_types(
            data.get("type"), data.get("nullable"), identifier
        )
        required = self._string_sequence(data.get("required"), f"schema {identifier} required")
        properties_data = self._mapping_or_empty(
            data.get("properties"), f"schema {identifier} properties"
        )
        properties = tuple(
            SchemaProperty(
                name=name,
                required=name in required,
                schema_definition=self._schema(
                    property_value, f"{identifier}/properties/{name}", resolver
                ),
            )
            for name, property_value in sorted(properties_data.items())
        )
        items = (
            self._schema(data["items"], f"{identifier}/items", resolver)
            if "items" in data
            else None
        )
        additional_allowed, additional_schema = self._additional_properties(
            data.get("additionalProperties"), identifier, resolver
        )
        enum = self._enum(data.get("enum"), identifier)
        unknown_fields = tuple(
            sorted(key for key in data if key not in _SCHEMA_FIELDS and not key.startswith("x-"))
        )
        unknown_warnings = (
            (f"unsupported schema fields: {', '.join(unknown_fields)}",) if unknown_fields else ()
        )
        support_status = (
            SupportStatus.UNSUPPORTED
            if reference is not None and reference.resolution_state is ResolutionState.UNSUPPORTED
            else SupportStatus.PARTIALLY_SUPPORTED
            if unknown_fields or status is SupportStatus.PARTIALLY_SUPPORTED
            else status
        )
        return Schema(
            id=identifier,
            type=types[0] if len(types) == 1 else None,
            types=types,
            format=self._optional_string(data.get("format"), f"schema {identifier} format"),
            nullable=nullable,
            enum=enum,
            properties=properties,
            items=items,
            required_properties=required,
            additional_properties_allowed=additional_allowed,
            additional_properties_schema=additional_schema,
            all_of=self._schema_sequence(data.get("allOf"), f"{identifier}/allOf", resolver),
            one_of=self._schema_sequence(data.get("oneOf"), f"{identifier}/oneOf", resolver),
            any_of=self._schema_sequence(data.get("anyOf"), f"{identifier}/anyOf", resolver),
            reference=reference,
            support_status=support_status,
            warnings=(*warnings, *unknown_warnings),
        )

    def _schema_types(
        self, type_value: object, nullable_value: object, identifier: str
    ) -> tuple[tuple[str, ...], bool, SupportStatus, tuple[str, ...]]:
        nullable = nullable_value is True
        if nullable_value not in (None, True, False):
            raise InvalidSpecificationError(f"schema {identifier} nullable must be a boolean")
        if type_value is None:
            return (), nullable, SupportStatus.SUPPORTED, ()
        if isinstance(type_value, str):
            return (type_value,), nullable, SupportStatus.SUPPORTED, ()
        if isinstance(type_value, Sequence) and not isinstance(type_value, (str, bytes)):
            values = self._string_sequence(type_value, f"schema {identifier} type")
            nullable = nullable or "null" in values
            non_null = tuple(value for value in values if value != "null")
            status = (
                SupportStatus.SUPPORTED if len(non_null) <= 1 else SupportStatus.PARTIALLY_SUPPORTED
            )
            warnings = (
                ()
                if status is SupportStatus.SUPPORTED
                else ("multiple non-null schema types preserved",)
            )
            return non_null, nullable, status, warnings
        raise InvalidSpecificationError(
            f"schema {identifier} type must be a string or list of strings"
        )

    def _parameter(self, value: object, identifier: str, resolver: ReferenceResolver) -> Parameter:
        data = self._mapping(value, f"parameter {identifier}")
        reference = resolver.reference(data["$ref"]) if "$ref" in data else None
        if reference is not None and len(data) == 1:
            return Parameter(id=identifier, reference=reference)
        name = self._string(data.get("name"), f"parameter {identifier} requires a name")
        location = self._string(data.get("in"), f"parameter {identifier} requires an in location")
        if location not in _PARAMETER_LOCATIONS:
            raise InvalidSpecificationError(
                f"parameter {identifier} has unsupported location: {location}"
            )
        required = data.get("required", False)
        if not isinstance(required, bool):
            raise InvalidSpecificationError(f"parameter {identifier} required must be a boolean")
        if location == "path" and not required:
            raise InvalidSpecificationError(f"path parameter {name} must be required")
        schema = (
            self._schema(data["schema"], f"{identifier}/schema", resolver)
            if "schema" in data
            else None
        )
        return Parameter(
            id=identifier,
            name=name,
            location=location,
            required=required,
            description=self._optional_string(data.get("description"), "parameter description"),
            schema_definition=schema,
            reference=reference,
        )

    def _parameters(
        self, value: object, identifier: str, resolver: ReferenceResolver
    ) -> tuple[Parameter, ...]:
        if value is None:
            return ()
        items = self._sequence(value, identifier)
        return tuple(
            sorted(
                (
                    self._parameter(item, f"{identifier}/{index}", resolver)
                    for index, item in enumerate(items)
                ),
                key=lambda parameter: parameter.id,
            )
        )

    def _request_body(
        self, value: object, identifier: str, resolver: ReferenceResolver
    ) -> RequestBody:
        data = self._mapping(value, f"request body {identifier}")
        reference = resolver.reference(data["$ref"]) if "$ref" in data else None
        if reference is not None and len(data) == 1:
            return RequestBody(id=identifier, reference=reference)
        required = data.get("required", False)
        if not isinstance(required, bool):
            raise InvalidSpecificationError(f"request body {identifier} required must be a boolean")
        return RequestBody(
            id=identifier,
            required=required,
            content=self._content(data.get("content"), f"{identifier}/content", resolver),
            description=self._optional_string(data.get("description"), "request body description"),
            reference=reference,
        )

    def _response(
        self, value: object, identifier: str, code: str | None, resolver: ReferenceResolver
    ) -> Response:
        data = self._mapping(value, f"response {identifier}")
        reference = resolver.reference(data["$ref"]) if "$ref" in data else None
        if reference is not None and len(data) == 1:
            return Response(id=identifier, code=code, reference=reference)
        headers_data = self._mapping_or_empty(data.get("headers"), f"response {identifier} headers")
        headers = {
            name: self._header(name, header, f"{identifier}/headers/{name}", resolver)
            for name, header in sorted(headers_data.items())
        }
        return Response(
            id=identifier,
            code=code,
            description=self._optional_string(data.get("description"), "response description"),
            content=self._content(data.get("content"), f"{identifier}/content", resolver),
            headers=headers,
            reference=reference,
        )

    def _header(
        self, name: str, value: object, identifier: str, resolver: ReferenceResolver
    ) -> Header:
        data = self._mapping(value, f"header {identifier}")
        reference = resolver.reference(data["$ref"]) if "$ref" in data else None
        required = data.get("required")
        if required is not None and not isinstance(required, bool):
            raise InvalidSpecificationError(f"header {identifier} required must be a boolean")
        return Header(
            name=name,
            description=self._optional_string(data.get("description"), "header description"),
            required=required,
            schema_definition=(
                self._schema(data["schema"], f"{identifier}/schema", resolver)
                if "schema" in data
                else None
            ),
            reference=reference,
        )

    def _content(
        self, value: object, identifier: str, resolver: ReferenceResolver
    ) -> dict[str, Schema | None]:
        content = self._mapping_or_empty(value, identifier)
        return {
            media_type: self._media_schema(media, f"{identifier}/{media_type}", resolver)
            for media_type, media in sorted(content.items())
        }

    def _media_schema(
        self, value: object, identifier: str, resolver: ReferenceResolver
    ) -> Schema | None:
        media_type = self._mapping(value, f"media type {identifier}")
        return (
            self._schema(media_type["schema"], f"{identifier}/schema", resolver)
            if "schema" in media_type
            else None
        )

    def _additional_properties(
        self, value: object, identifier: str, resolver: ReferenceResolver
    ) -> tuple[bool | None, Schema | None]:
        if value is None:
            return None, None
        if isinstance(value, bool):
            return value, None
        return None, self._schema(value, f"{identifier}/additionalProperties", resolver)

    def _schema_sequence(
        self, value: object, identifier: str, resolver: ReferenceResolver
    ) -> tuple[Schema, ...]:
        if value is None:
            return ()
        return tuple(
            self._schema(item, f"{identifier}/{index}", resolver)
            for index, item in enumerate(self._sequence(value, identifier))
        )

    def _security_scheme(
        self, name: str, value: object, resolver: ReferenceResolver
    ) -> SecurityScheme:
        data = self._mapping(value, f"security scheme {name}")
        reference = resolver.reference(data["$ref"]) if "$ref" in data else None
        return SecurityScheme(
            name=name,
            type=self._optional_string(data.get("type"), "security scheme type"),
            scheme=self._optional_string(data.get("scheme"), "security scheme scheme"),
            bearer_format=self._optional_string(
                data.get("bearerFormat"), "security scheme bearerFormat"
            ),
            description=self._optional_string(
                data.get("description"), "security scheme description"
            ),
            reference=reference,
        )

    def _security(self, value: object, identifier: str) -> SecurityRequirements:
        if value is None:
            return ()
        requirements = self._sequence(value, identifier)
        parsed: list[tuple[SecurityRequirement, ...]] = []
        for requirement in requirements:
            mapping = self._mapping(requirement, identifier)
            parsed.append(
                tuple(
                    SecurityRequirement(
                        scheme=scheme, scopes=self._string_sequence(scopes, identifier)
                    )
                    for scheme, scopes in sorted(mapping.items())
                )
            )
        return tuple(
            sorted(
                parsed,
                key=lambda group: tuple(
                    (requirement.scheme, requirement.scopes) for requirement in group
                ),
            )
        )

    def _component_map(
        self, components: Mapping[str, Any], name: str, parser: Callable[[str, object], T]
    ) -> dict[str, T]:
        values = self._mapping_or_empty(components.get(name), f"components.{name}")
        return {key: parser(key, value) for key, value in sorted(values.items())}

    @staticmethod
    def _openapi_version(document: Mapping[str, Any]) -> str:
        version = document.get("openapi")
        if isinstance(version, (int, float)) and not isinstance(version, bool):
            raise UnsupportedOpenAPIVersionError(f"Unsupported OpenAPI version: {version}")
        if not isinstance(version, str):
            raise InvalidSpecificationError('missing required top-level "openapi" field')
        if not re.fullmatch(r"3\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.-]+)?", version):
            raise UnsupportedOpenAPIVersionError(f"Unsupported OpenAPI version: {version}")
        return version

    @staticmethod
    def _path(value: object) -> str:
        if (
            not isinstance(value, str)
            or not value.startswith("/")
            or any(char.isspace() for char in value)
        ):
            raise InvalidSpecificationError(
                "path keys must be non-empty slash-prefixed paths without whitespace"
            )
        return value

    @staticmethod
    def _mapping(value: object, context: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise InvalidSpecificationError(f"{context} must be a mapping")
        if not all(isinstance(key, str) for key in value):
            raise InvalidSpecificationError(f"{context} must use string keys")
        return value

    def _mapping_or_empty(self, value: object, context: str) -> Mapping[str, Any]:
        return {} if value is None else self._mapping(value, context)

    @staticmethod
    def _sequence(value: object, context: str) -> Sequence[Any]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise InvalidSpecificationError(f"{context} must be a list")
        return value

    def _sequence_or_empty(self, value: object, context: str) -> Sequence[Any]:
        return () if value is None else self._sequence(value, context)

    @staticmethod
    def _string(value: object, context: str) -> str:
        if not isinstance(value, str) or not value:
            raise InvalidSpecificationError(f"{context} must be a non-empty string")
        return value

    def _optional_string(self, value: object, context: str) -> str | None:
        return None if value is None else self._string(value, context)

    def _string_sequence(self, value: object, context: str) -> tuple[str, ...]:
        if value is None:
            return ()
        return tuple(sorted(self._string(item, context) for item in self._sequence(value, context)))

    def _enum(self, value: object, identifier: str) -> tuple[str | int | float | bool | None, ...]:
        if value is None:
            return ()
        values = self._sequence(value, f"schema {identifier} enum")
        if not all(isinstance(item, (str, int, float, bool)) or item is None for item in values):
            raise InvalidSpecificationError(
                f"schema {identifier} enum values must be JSON primitives"
            )
        return tuple(sorted(values, key=lambda item: json.dumps(item, sort_keys=True)))
