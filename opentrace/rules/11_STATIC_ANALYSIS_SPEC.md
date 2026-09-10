# Static Analysis Specification

Python AST is the primary mechanism. Initial clients are `requests` and `httpx`; planned M3 forms include `import requests; requests.post(...)`, `import requests as r; r.post(...)`, `from requests import post; post(...)`, `import httpx; httpx.post(...)`, `client = httpx.Client(); client.post(...)`, and `async with httpx.AsyncClient() as client: await client.post(...)`. Analyze source structure, never execute repository code to infer usage.

Extract symbols and HTTP call sites with precise location, client/method, host/path, request/response field evidence, aliases and resolution state: `EXACT`, `PARTIAL`, or `UNRESOLVED`. Preserve payload aliases/nested dictionaries, awaits, wrappers, methods, nested functions, decorators, re-exports and shadowing evidence where statically resolvable. Partial or unresolved information must never be upgraded to exact; dynamic endpoints produce warnings and bounded evidence.

Comments, docstrings, documentation examples, unrelated strings, variable names, and endpoint-like text are not API call sites. A local function named `post` or a shadowed `requests` identifier is not a recognized client absent valid import/binding evidence. Perfect Python static analysis is not promised: reflection, runtime imports/configuration and unresolvable wrappers remain partial or unsupported. M3 release blocking requires adversarial false-positive cases to produce no call site.

## M3 boundary

M3 owns repository discovery, AST parsing, static import/binding evidence, symbol extraction, HTTP call extraction, bounded URL/payload/response-field evidence, and structured warnings. It may use normalized API-call identity fields but must not compare them with `APIChange` objects or rank/directly impact symbols; that begins at M4. It must not construct call graphs (M5), infer blast radius/risk (M6), create datasets/models, or introduce migration/AI/validation/product infrastructure.
