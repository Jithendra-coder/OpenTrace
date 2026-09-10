# OpenAPI Analysis Specification

Eventual input support: YAML/JSON OpenAPI 3.x, local and nested `$ref`, arrays, `allOf`/`oneOf`/`anyOf`, required/nullable/null properties, path/query/header parameters, request bodies, multiple responses, headers, and security requirements. Normalize without erasing source locations, reference chains, unsupported features or unresolved references.

Initial categories: `endpoint_removed`, `http_method_removed`, `required_parameter_added`, `request_property_removed`, `request_property_type_changed`, `response_property_removed`, `response_property_type_changed`, `security_requirement_changed`, `enum_restricted`, `nullable_removed`.

Each `APIChange` exposes category, path, method, location, old/new values, severity, `breaking_classification`, compatibility direction, certainty, assumptions and reason. Classification is one of `CLIENT_BREAKING`, `SERVER_BREAKING`, `POTENTIALLY_BREAKING`, or `COMPATIBLE`; a change may have more than one affected direction. Do not call every syntactic diff breaking. For example, request-property removal may be conditional on whether servers reject unknown properties, while response-property removal can break clients that consume it. Preserve the conditional assumption rather than overclaiming.

Initial categories are rules to evaluate, not universal conclusions. Unsupported versions/features return structured `PARTIALLY_SUPPORTED` or `UNSUPPORTED` warnings, never guessed semantics. M2 release blocking includes compatible optional additions that must not be incorrectly reported as breaking.
