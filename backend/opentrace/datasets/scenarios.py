"""Deterministic scenario construction with independent ground truth."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass

from opentrace.datasets.models import (
    GENERATOR_VERSION,
    GroundTruthImpactType,
    GroundTruthTarget,
    ScenarioDefinition,
    ScenarioFamily,
    ScenarioSource,
)

MUTATION_FAMILIES = (
    "endpoint_removed",
    "http_method_removed",
    "required_parameter_added",
    "request_property_removed",
    "request_property_type_changed",
    "response_property_removed",
    "response_property_type_changed",
    "security_requirement_changed",
    "enum_restricted",
    "nullable_removed",
)


@dataclass(frozen=True)
class _ScenarioParts:
    family: ScenarioFamily
    index: int
    mutation_family: str
    api_family: str
    host: str
    path: str
    method: str
    old_document: dict[str, object]
    new_document: dict[str, object]
    direct_source: str
    depth: int
    branch: bool = False
    special: str | None = None
    hard_negative: bool = False
    hard_positive: bool = False
    tags: tuple[str, ...] = ()


def build_scenarios(
    seed: int, synthetic_count: int, include_curated: bool, include_realistic: bool
) -> tuple[ScenarioDefinition, ...]:
    """Build reproducible synthetic, curated, and realistic scenario definitions."""

    scenarios: list[ScenarioDefinition] = []
    for index in range(synthetic_count):
        mutation = MUTATION_FAMILIES[index % len(MUTATION_FAMILIES)]
        scenarios.append(_materialize(_synthetic_parts(seed, index, mutation), seed))
    if include_curated:
        scenarios.extend(_materialize(parts, seed) for parts in _curated_parts(seed))
    if include_realistic:
        scenarios.extend(_materialize(parts, seed) for parts in _realistic_parts(seed))
    return tuple(sorted(scenarios, key=lambda scenario: scenario.scenario_id))


def _synthetic_parts(seed: int, index: int, mutation: str) -> _ScenarioParts:
    rng = random.Random(seed + index * 7919)
    api_family, host, path = (
        ("payments", "payments.example.com", "/payments")
        if index % 3 == 0
        else ("identity", "identity.example.com", "/profiles")
        if index % 3 == 1
        else ("inventory", "inventory.example.com", "/items")
    )
    method = (
        "GET"
        if mutation
        in {"endpoint_removed", "required_parameter_added", "security_requirement_changed"}
        else "POST"
    )
    depth = 1 + rng.randrange(3)
    branch = rng.randrange(2) == 1
    old_document, new_document = _mutation_documents(mutation, api_family, host, path, method)
    source = _direct_source(mutation, host, path, method, rng.randrange(3))
    return _ScenarioParts(
        family=ScenarioFamily.SYNTHETIC,
        index=index,
        mutation_family=mutation,
        api_family=api_family,
        host=host,
        path=path,
        method=method,
        old_document=old_document,
        new_document=new_document,
        direct_source=source,
        depth=depth,
        branch=branch,
        tags=("seeded", "structural-variation"),
    )


def _curated_parts(seed: int) -> tuple[_ScenarioParts, ...]:
    common = _mutation_documents(
        "request_property_removed", "payments", "payments.example.com", "/payments", "POST"
    )
    unsupported = tuple(
        {
            **document,
            "webhooks": {"paymentEvent": {"post": {"description": "unsupported fixture branch"}}},
        }
        for document in common
    )
    return (
        _ScenarioParts(
            ScenarioFamily.CURATED,
            0,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _direct_source("request_property_removed", "other.example.com", "/other", "POST", 0),
            1,
            hard_negative=True,
            tags=("same-field-wrong-endpoint",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            1,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _direct_source("request_property_removed", "other.example.com", "/payments", "POST", 0),
            1,
            hard_negative=True,
            tags=("same-path-wrong-host",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            2,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _direct_source(
                "request_property_removed", "payments.example.com", "/payments", "GET", 0
            ),
            1,
            hard_negative=True,
            tags=("same-path-wrong-method",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            3,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _response_collision_source(),
            1,
            hard_negative=True,
            tags=("request-response-collision",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            4,
            "required_parameter_added",
            "identity",
            "identity.example.com",
            "/profiles",
            "GET",
            *_mutation_documents(
                "required_parameter_added", "identity", "identity.example.com", "/profiles", "GET"
            ),
            _query_body_collision_source(),
            1,
            hard_negative=True,
            tags=("query-body-collision",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            5,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _dynamic_source(),
            1,
            hard_positive=True,
            tags=("dynamic-url", "positive-disagreement"),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            6,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _shadowed_source(),
            1,
            hard_negative=True,
            tags=("shadowed-http-client",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            7,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _cycle_source(),
            1,
            tags=("cycle",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            8,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _diamond_source(),
            2,
            tags=("diamond",),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            9,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _failed_fragment_source(),
            1,
            hard_positive=True,
            tags=("failed-source-fragment", "coverage-warning"),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            10,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _wrapper_source(),
            1,
            hard_positive=True,
            tags=("wrapper-function", "positive-disagreement"),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            11,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _dynamic_dispatch_source(),
            1,
            hard_positive=True,
            tags=("dynamic-dispatch", "positive-disagreement", "multiple-seeds"),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            12,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            common[0],
            common[1],
            _direct_source(
                "request_property_removed", "payments.example.com", "/payments", "POST", 0
            ),
            0,
            special="disconnected",
            tags=("disconnected-near-match", "multiple-seeds"),
        ),
        _ScenarioParts(
            ScenarioFamily.CURATED,
            13,
            "request_property_removed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            unsupported[0],
            unsupported[1],
            _direct_source(
                "request_property_removed", "payments.example.com", "/payments", "POST", 0
            ),
            0,
            special="disconnected",
            tags=("openapi-unsupported-structure", "partial-contract-fixture"),
        ),
    )


def _realistic_parts(seed: int) -> tuple[_ScenarioParts, ...]:
    payment = _mutation_documents(
        "request_property_type_changed", "payments", "payments.example.com", "/payments", "POST"
    )
    inventory = _mutation_documents(
        "response_property_removed", "inventory", "inventory.example.com", "/items", "GET"
    )
    return (
        _ScenarioParts(
            ScenarioFamily.REALISTIC,
            0,
            "request_property_type_changed",
            "payments",
            "payments.example.com",
            "/payments",
            "POST",
            payment[0],
            payment[1],
            _direct_source(
                "request_property_type_changed", "payments.example.com", "/payments", "POST", 1
            ),
            3,
            branch=True,
            tags=("payment-workflow", "manually-constructed"),
        ),
        _ScenarioParts(
            ScenarioFamily.REALISTIC,
            1,
            "response_property_removed",
            "inventory",
            "inventory.example.com",
            "/items",
            "GET",
            inventory[0],
            inventory[1],
            _direct_source(
                "response_property_removed", "inventory.example.com", "/items", "GET", 2
            ),
            2,
            branch=True,
            tags=("inventory-workflow", "manually-constructed"),
        ),
    )


def _materialize(parts: _ScenarioParts, seed: int) -> ScenarioDefinition:
    sources = _repository_sources(parts)
    truth = _truth_for_sources(parts, sources)
    old_spec = _canonical_document(parts.old_document)
    new_spec = _canonical_document(parts.new_document)
    fingerprint = _digest(
        old_spec,
        new_spec,
        *(source.content for source in sources),
        *(target.canonical_json() for target in truth),
    )
    scenario_id = _digest(GENERATOR_VERSION, parts.family.value, seed, parts.index, fingerprint)
    repository_id = _digest("repository", parts.api_family, parts.index, parts.special or "base")
    repository_family_id = _digest("repository-family", parts.family.value, parts.index % 3)
    api_family_id = _digest("api-family", parts.api_family)
    migration_id = _digest("migration", scenario_id, parts.mutation_family)
    return ScenarioDefinition(
        scenario_id=scenario_id,
        scenario_fingerprint=fingerprint,
        family=parts.family,
        repository_id=repository_id,
        repository_family_id=repository_family_id,
        api_family_id=api_family_id,
        migration_id=migration_id,
        mutation_family=parts.mutation_family,
        seed=seed if parts.family is ScenarioFamily.SYNTHETIC else None,
        old_spec=old_spec,
        new_spec=new_spec,
        sources=sources,
        ground_truth=truth,
        provenance=(
            "synthetic deterministic template"
            if parts.family is ScenarioFamily.SYNTHETIC
            else "curated hand-authored adversarial scenario"
            if parts.family is ScenarioFamily.CURATED
            else "realistic manually constructed scenario; not real-world source"
        ),
        intended_role=(
            "future ranking development"
            if parts.family is ScenarioFamily.SYNTHETIC
            else "adversarial evaluation only"
            if parts.family is ScenarioFamily.CURATED
            else "realistic structural smoke coverage"
        ),
        hard_negative=parts.hard_negative,
        hard_positive=parts.hard_positive,
        tags=parts.tags,
    )


def _repository_sources(parts: _ScenarioParts) -> tuple[ScenarioSource, ...]:
    files: dict[str, str] = {
        "__init__.py": "",
        "service.py": parts.direct_source,
        "nearby.py": _nearby_source(parts.host, parts.path),
    }
    if parts.special in {"wrapper", "dispatch", "disconnected"}:
        pass
    elif parts.special == "cycle" or "cycle" in parts.tags:
        files.update(
            {
                "service.py": (
                    parts.direct_source
                    + "\n\ndef first(value: object) -> object:\n"
                    "    return second(value)\n\n"
                    "def second(value: object) -> object:\n"
                    "    first(value)\n"
                    "    return handle(value)\n"
                )
            }
        )
    elif "diamond" in parts.tags:
        files.update(
            {
                "left.py": (
                    "from service import handle\n\n"
                    "def left(value: object) -> object:\n"
                    "    return handle(value)\n"
                ),
                "right.py": (
                    "from service import handle\n\n"
                    "def right(value: object) -> object:\n"
                    "    return handle(value)\n"
                ),
            }
        )
    elif parts.special == "failed" or "failed-source-fragment" in parts.tags:
        files["broken.py"] = "def broken(:\n    pass\n"
    else:
        previous = "service"
        for level in range(parts.depth):
            module = f"flow_{level}"
            function = f"step_{level}"
            files[f"{module}.py"] = (
                f"from {previous} import {'handle' if level == 0 else f'step_{level - 1}'}\n\n"
                f"def {function}(value: object) -> object:\n"
                f"    return {'handle' if level == 0 else f'step_{level - 1}'}(value)\n"
            )
            previous = module
        files["entry.py"] = (
            f"from {previous} import "
            f"{'step_' + str(parts.depth - 1) if parts.depth else 'handle'}\n\n"
            "def entry(value: object) -> object:\n"
            f"    return {'step_' + str(parts.depth - 1) if parts.depth else 'handle'}(value)\n"
        )
        if parts.branch:
            files["alternate.py"] = (
                "from service import handle\n\n"
                "def alternate(value: object) -> object:\n"
                "    return handle(value)\n"
            )
    return tuple(
        ScenarioSource(path=path, content=content) for path, content in sorted(files.items())
    )


def _truth_for_sources(
    parts: _ScenarioParts, sources: tuple[ScenarioSource, ...]
) -> tuple[GroundTruthTarget, ...]:
    names = {source.path for source in sources}
    targets = [
        GroundTruthTarget(
            symbol="service.py::handle",
            impact_type=GroundTruthImpactType.DIRECT,
            distance=0,
            path=("service.py::handle",),
            rationale=(
                "Scenario construction made service.handle emit or consume the mutated "
                "API contract element."
            ),
        )
    ]
    if "cycle" in parts.tags:
        targets.extend(
            (
                GroundTruthTarget(
                    symbol="service.py::second",
                    impact_type=GroundTruthImpactType.INDIRECT,
                    distance=1,
                    path=("service.py::second", "service.py::handle"),
                    rationale="Scenario construction connected second to handle.",
                ),
                GroundTruthTarget(
                    symbol="service.py::first",
                    impact_type=GroundTruthImpactType.INDIRECT,
                    distance=2,
                    path=("service.py::first", "service.py::second", "service.py::handle"),
                    rationale="Scenario construction connected first through the cycle.",
                ),
            )
        )
    elif "diamond" in parts.tags:
        targets.extend(
            (
                GroundTruthTarget(
                    symbol="left.py::left",
                    impact_type=GroundTruthImpactType.INDIRECT,
                    distance=1,
                    path=("left.py::left", "service.py::handle"),
                    rationale="Scenario construction connected the left branch.",
                ),
                GroundTruthTarget(
                    symbol="right.py::right",
                    impact_type=GroundTruthImpactType.INDIRECT,
                    distance=1,
                    path=("right.py::right", "service.py::handle"),
                    rationale="Scenario construction connected the right branch.",
                ),
            )
        )
    elif "wrapper-function" in parts.tags:
        targets = [
            GroundTruthTarget(
                symbol="service.py::send",
                impact_type=GroundTruthImpactType.DIRECT,
                distance=0,
                path=("service.py::send",),
                rationale="Scenario construction placed the API call in service.send.",
            ),
            GroundTruthTarget(
                symbol="service.py::handle",
                impact_type=GroundTruthImpactType.INDIRECT,
                distance=1,
                path=("service.py::handle", "service.py::send"),
                rationale="Scenario construction routed handle through the wrapper.",
            ),
        ]
    elif "disconnected-near-match" in parts.tags:
        pass
    elif not parts.hard_negative:
        previous = "service.py::handle"
        for level in range(parts.depth):
            current = f"flow_{level}.py::step_{level}"
            targets.append(
                GroundTruthTarget(
                    symbol=current,
                    impact_type=GroundTruthImpactType.INDIRECT,
                    distance=level + 1,
                    path=(current, previous),
                    rationale="Scenario construction connected this upstream caller.",
                )
            )
            previous = current
        entry = "entry.py::entry"
        targets.append(
            GroundTruthTarget(
                symbol=entry,
                impact_type=GroundTruthImpactType.INDIRECT,
                distance=parts.depth + 1,
                path=(entry, previous),
                rationale="Scenario construction connected the entry caller.",
            )
        )
        if parts.branch:
            targets.append(
                GroundTruthTarget(
                    symbol="alternate.py::alternate",
                    impact_type=GroundTruthImpactType.INDIRECT,
                    distance=1,
                    path=("alternate.py::alternate", "service.py::handle"),
                    rationale="Scenario construction connected a shared alternate caller.",
                )
            )
    if parts.hard_negative:
        return ()
    if "failed-source-fragment" in parts.tags:
        return tuple(
            target
            for target in targets
            if target.symbol in names or target.symbol.startswith("service.py::")
        )
    return tuple(targets)


def _mutation_documents(
    mutation: str, api_family: str, host: str, path: str, method: str
) -> tuple[dict[str, object], dict[str, object]]:
    base_info = {"title": f"{api_family.title()} API", "version": "1"}
    old_paths: dict[str, object]
    new_paths: dict[str, object]
    old_operation: dict[str, object] = {"responses": {"200": {"description": "OK"}}}
    new_operation: dict[str, object] = {"responses": {"200": {"description": "OK"}}}
    if mutation == "endpoint_removed":
        old_paths = {path: {method.lower(): old_operation}}
        new_paths = {}
    elif mutation == "http_method_removed":
        old_paths = {path: {"get": old_operation, "post": old_operation}}
        new_paths = {path: {"get": old_operation}}
    elif mutation == "required_parameter_added":
        old_operation["parameters"] = [
            {"name": "page", "in": "query", "schema": {"type": "integer"}}
        ]
        new_operation["parameters"] = [
            {"name": "page", "in": "query", "required": True, "schema": {"type": "integer"}}
        ]
        old_paths, new_paths = (
            {path: {method.lower(): old_operation}},
            {path: {method.lower(): new_operation}},
        )
    elif mutation in {
        "request_property_removed",
        "request_property_type_changed",
        "enum_restricted",
        "nullable_removed",
    }:
        old_schema, new_schema = _request_schemas(mutation)
        old_operation["requestBody"] = {"content": {"application/json": {"schema": old_schema}}}
        new_operation["requestBody"] = {"content": {"application/json": {"schema": new_schema}}}
        old_paths, new_paths = (
            {path: {method.lower(): old_operation}},
            {path: {method.lower(): new_operation}},
        )
    elif mutation in {"response_property_removed", "response_property_type_changed"}:
        old_operation["responses"] = {
            "200": {
                "description": "OK",
                "content": {"application/json": {"schema": _response_schema(mutation, True)}},
            }
        }
        new_operation["responses"] = {
            "200": {
                "description": "OK",
                "content": {"application/json": {"schema": _response_schema(mutation, False)}},
            }
        }
        old_paths, new_paths = (
            {path: {method.lower(): old_operation}},
            {path: {method.lower(): new_operation}},
        )
    elif mutation == "security_requirement_changed":
        new_operation["security"] = [{"apiKey": []}]
        old_paths, new_paths = (
            {path: {method.lower(): old_operation}},
            {path: {method.lower(): new_operation}},
        )
    else:
        raise ValueError(f"unsupported synthetic mutation: {mutation}")
    old_document: dict[str, object] = {
        "openapi": "3.0.3",
        "info": base_info,
        "servers": [{"url": f"https://{host}"}],
        "paths": old_paths,
    }
    new_document: dict[str, object] = {
        "openapi": "3.0.3",
        "info": {**base_info, "version": "2"},
        "servers": [{"url": f"https://{host}"}],
        "paths": new_paths,
    }
    if mutation == "security_requirement_changed":
        new_document["components"] = {
            "securitySchemes": {"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}
        }
    return old_document, new_document


def _request_schemas(mutation: str) -> tuple[dict[str, object], dict[str, object]]:
    if mutation == "request_property_removed":
        return _object_schema(
            {"amount": {"type": "number"}, "currency": {"type": "string"}}
        ), _object_schema({"currency": {"type": "string"}})
    if mutation == "request_property_type_changed":
        return _object_schema({"amount": {"type": "number"}}), _object_schema(
            {"amount": {"type": "string"}}
        )
    if mutation == "enum_restricted":
        return _object_schema(
            {"state": {"type": "string", "enum": ["pending", "paid"]}}
        ), _object_schema({"state": {"type": "string", "enum": ["paid"]}})
    return _object_schema({"state": {"type": "string", "nullable": True}}), _object_schema(
        {"state": {"type": "string"}}
    )


def _response_schema(mutation: str, old: bool) -> dict[str, object]:
    if mutation == "response_property_removed":
        properties = (
            {"id": {"type": "integer"}, "state": {"type": "string"}}
            if old
            else {"state": {"type": "string"}}
        )
    else:
        properties = {"id": {"type": "integer"}} if old else {"id": {"type": "string"}}
    return _object_schema(properties)


def _object_schema(properties: Mapping[str, object]) -> dict[str, object]:
    return {"type": "object", "properties": properties}


def _direct_source(mutation: str, host: str, path: str, method: str, client_variant: int) -> str:
    url = f"https://{host}{path}"
    if mutation == "required_parameter_added":
        call = f"requests.get({url!r}, params={{'page': value}})"
    elif mutation in {"response_property_removed", "response_property_type_changed"}:
        call = f"requests.{method.lower()}({url!r})"
    elif mutation in {"endpoint_removed", "http_method_removed", "security_requirement_changed"}:
        call = f"requests.{method.lower()}({url!r})"
    else:
        call = (
            f"requests.post({url!r}, json={{'amount': value, 'state': value, 'currency': value}})"
        )
    if client_variant == 1:
        call = call.replace("requests.", "httpx.", 1)
        import_line = "import httpx"
    elif client_variant == 2:
        call = call.replace("requests.", "session.", 1)
        import_line = "import requests\nsession = requests.Session()"
    else:
        import_line = "import requests"
    if mutation in {"response_property_removed", "response_property_type_changed"}:
        return (
            f"{import_line}\n\n"
            "def handle(value: object) -> object:\n"
            f"    response = {call}\n"
            "    return response.json()['id']\n"
        )
    return f"{import_line}\n\ndef handle(value: object) -> object:\n    return {call}\n"


def _nearby_source(host: str, path: str) -> str:
    other_path = "/settings" if path != "/settings" else "/other"
    return (
        "import requests\n\n"
        "def nearby(value: object) -> object:\n"
        f"    return requests.post('https://{host}{other_path}', json={{'amount': value}})\n"
    )


def _response_collision_source() -> str:
    return (
        "import requests\n\n"
        "def handle(value: object) -> object:\n"
        "    response = requests.post("
        "'https://payments.example.com/payments', json={'currency': value})\n"
        "    return response.json()['amount']\n"
    )


def _query_body_collision_source() -> str:
    return (
        "import requests\n\n"
        "def handle(value: object) -> object:\n"
        "    return requests.get('https://identity.example.com/profiles', json={'page': value})\n"
    )


def _dynamic_source() -> str:
    return (
        "import requests\n\n"
        "def build_url(value: object) -> str:\n"
        "    return str(value)\n\n"
        "def handle(value: object) -> object:\n"
        "    return requests.post(build_url(value), json={'amount': value})\n"
    )


def _shadowed_source() -> str:
    return (
        "import requests\n\n"
        "def handle(value: object) -> object:\n"
        "    requests = object()\n"
        "    return requests.post('/payments', json={'amount': value})\n"
    )


def _cycle_source() -> str:
    return (
        "import requests\n\n"
        "def handle(value: object) -> object:\n"
        "    return requests.post("
        "'https://payments.example.com/payments', json={'amount': value})\n\n"
        "def first(value: object) -> object:\n"
        "    return second(value)\n\n"
        "def second(value: object) -> object:\n"
        "    first(value)\n"
        "    return handle(value)\n"
    )


def _diamond_source() -> str:
    return (
        "import requests\n\n"
        "def handle(value: object) -> object:\n"
        "    return requests.post("
        "'https://payments.example.com/payments', json={'amount': value})\n"
    )


def _failed_fragment_source() -> str:
    return (
        "import requests\n\n"
        "def handle(value: object) -> object:\n"
        "    return requests.post("
        "'https://payments.example.com/payments', json={'amount': value})\n"
    )


def _wrapper_source() -> str:
    return (
        "import requests\n\n"
        "def send(value: object) -> object:\n"
        "    return requests.post("
        "'https://payments.example.com/payments', json={'amount': value})\n\n"
        "def handle(value: object) -> object:\n"
        "    return send(value)\n"
    )


def _dynamic_dispatch_source() -> str:
    return (
        "import requests\n\n"
        "def handle(value: object) -> object:\n"
        "    method = 'post'\n"
        "    client = getattr(requests, method)\n"
        "    return client('https://payments.example.com/payments', "
        "json={'amount': value})\n"
    )


def _canonical_document(document: dict[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def _digest(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
