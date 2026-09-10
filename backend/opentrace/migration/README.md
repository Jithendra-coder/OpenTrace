# M10 deterministic migration policy

M10 consumes canonical M1–M6 evidence and produces candidate source edits only. It never executes analyzed
repository code, runs tests, installs dependencies, or consults M7–M9 model artifacts.

| M2 change category | M10 deterministic status | Policy |
| --- | --- | --- |
| `endpoint_removed` | `UNSUPPORTED` | No authoritative replacement endpoint. |
| `http_method_removed` | `UNSUPPORTED` | No method substitution is guessed. |
| `required_parameter_added` | `UNSUPPORTED` | No value is invented. |
| `request_property_removed` | `SUPPORTED` | `remove-request-property-v1` removes one exact literal outgoing JSON field. |
| `request_property_type_changed` | `UNSUPPORTED` | No semantic conversion is guessed. |
| `response_property_removed` | `UNSUPPORTED` | Downstream response behavior is not inferred. |
| `response_property_type_changed` | `UNSUPPORTED` | No response conversion is authoritative. |
| `security_requirement_changed` | `UNSUPPORTED` | Credentials, tokens, and headers are never synthesized. |
| `enum_restricted` | `UNSUPPORTED` | No replacement enum value is selected. |
| `nullable_removed` | `UNSUPPORTED` | No replacement value is invented. |

The supported request-property rule requires exact URL/method/request-field/direct-impact evidence and a local
literal dictionary, either inline or through one bounded local assignment. Dynamic construction, mutation, merges,
shared payloads, ambiguous duplicate keys, and stale source evidence produce an explicit non-candidate result.
