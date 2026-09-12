"""Deterministic direct API-change to call-site matching."""

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

from opentrace.code_analysis.models import APICallSite, ResolutionState
from opentrace.contracts.models import APIChange, ChangeCategory
from opentrace.impact.models import DirectImpact, ImpactAnalysis, ImpactEvidence, UnmatchedImpact


@dataclass(frozen=True)
class MatchingPolicy:
    """Centralized, explainable baseline policy; this is not a learned model."""

    version: str = "direct-impact-baseline-v1"
    host_exact_weight: float = 0.20
    host_unknown_weight: float = 0.05
    path_exact_weight: float = 0.30
    path_template_weight: float = 0.24
    path_partial_weight: float = 0.18
    method_weight: float = 0.20
    changed_field_weight: float = 0.20
    parameter_weight: float = 0.20
    direct_invocation_weight: float = 0.05
    resolution_exact_weight: float = 0.05
    resolution_partial_weight: float = 0.02


@dataclass(frozen=True)
class _Feature:
    name: str
    observed_value: str
    contribution: float
    resolution_state: ResolutionState
    explanation: str


@dataclass(frozen=True)
class _Evaluation:
    features: tuple[_Feature, ...]
    warnings: tuple[str, ...]
    certainty: ResolutionState
    request_fields: tuple[str, ...] = ()
    response_fields: tuple[str, ...] = ()
    parameter_locations: tuple[str, ...] = ()


_OPERATION_CATEGORIES = frozenset(
    {
        ChangeCategory.ENDPOINT_REMOVED,
        ChangeCategory.HTTP_METHOD_REMOVED,
        ChangeCategory.SECURITY_REQUIREMENT_CHANGED,
    }
)
_REQUEST_FIELD_CATEGORIES = frozenset(
    {
        ChangeCategory.REQUEST_PROPERTY_REMOVED,
        ChangeCategory.REQUEST_PROPERTY_TYPE_CHANGED,
        ChangeCategory.ENUM_RESTRICTED,
        ChangeCategory.NULLABLE_REMOVED,
    }
)
_RESPONSE_FIELD_CATEGORIES = frozenset(
    {
        ChangeCategory.RESPONSE_PROPERTY_REMOVED,
        ChangeCategory.RESPONSE_PROPERTY_TYPE_CHANGED,
        ChangeCategory.ENUM_RESTRICTED,
        ChangeCategory.NULLABLE_REMOVED,
    }
)


class DirectImpactMatcher:
    """Match structured contract changes with structured call-site evidence."""

    def __init__(
        self,
        policy: MatchingPolicy | None = None,
        api_hosts: tuple[str, ...] = (),
    ) -> None:
        self.policy = policy or MatchingPolicy()
        hosts = {_host(value) for value in api_hosts}
        self.api_hosts = tuple(sorted(host for host in hosts if host is not None))

    def match(
        self,
        changes: tuple[APIChange, ...] | list[APIChange],
        call_sites: tuple[APICallSite, ...] | list[APICallSite],
    ) -> ImpactAnalysis:
        impacts: list[DirectImpact] = []
        unmatched: list[UnmatchedImpact] = []
        calls = tuple(
            sorted(call_sites, key=lambda call: (call.file, call.line, call.column, call.id))
        )
        for change in sorted(
            changes, key=lambda value: (value.path, value.method, value.location, value.id)
        ):
            evaluations: list[DirectImpact] = []
            warnings: set[str] = set()
            for call in calls:
                evaluation = self._evaluate(change, call)
                if evaluation is not None:
                    warnings.update(evaluation.warnings)
                    evaluations.append(self._impact(change, call, evaluation))
                elif evaluation is None:
                    continue
            if evaluations:
                impacts.extend(evaluations)
            else:
                unmatched.append(
                    UnmatchedImpact(
                        change_id=change.id,
                        evaluated_call_site_ids=tuple(call.id for call in calls),
                        reason=(
                            "No call site supplied sufficient structured evidence for this change."
                        ),
                        warnings=tuple(sorted(warnings)),
                    )
                )
        return ImpactAnalysis(
            policy_version=self.policy.version,
            direct_impacts=tuple(
                sorted(
                    impacts,
                    key=lambda impact: (impact.file, impact.line, impact.change_id, impact.id),
                )
            ),
            unmatched=tuple(sorted(unmatched, key=lambda value: value.change_id)),
            warnings=tuple(sorted({warning for item in unmatched for warning in item.warnings})),
        )

    def _evaluate(self, change: APIChange, call: APICallSite) -> _Evaluation | None:
        if call.method != change.method.upper():
            return None
        path_feature = _path_feature(
            change.path, call.resolved_path, call.url_resolution_state, self.policy
        )
        if path_feature is None:
            return None
        host_feature, host_warning, host_certainty = self._host_feature(call)
        if host_feature is None:
            return None
        features = [path_feature, host_feature]
        warnings = [host_warning] if host_warning else []
        certainty = _combine_certainty(call.url_resolution_state, host_certainty)
        features.append(
            _Feature(
                "http_method_match",
                "exact",
                self.policy.method_weight,
                ResolutionState.EXACT,
                "Exact HTTP method match.",
            )
        )
        features.append(
            _Feature(
                "direct_http_invocation",
                call.invocation_kind,
                self.policy.direct_invocation_weight,
                ResolutionState.EXACT,
                f"Direct {call.library} HTTP invocation.",
            )
        )
        if call.url_resolution_state is ResolutionState.EXACT:
            features.append(
                _Feature(
                    "url_resolution",
                    "exact",
                    self.policy.resolution_exact_weight,
                    ResolutionState.EXACT,
                    "URL resolution is exact.",
                )
            )
        elif call.url_resolution_state is ResolutionState.PARTIAL:
            features.append(
                _Feature(
                    "url_resolution",
                    "partial",
                    self.policy.resolution_partial_weight,
                    ResolutionState.PARTIAL,
                    "URL resolution is partial; dynamic path segments remain uncertain.",
                )
            )
            certainty = _combine_certainty(certainty, ResolutionState.PARTIAL)
        else:
            return None
        request_fields: tuple[str, ...] = ()
        response_fields: tuple[str, ...] = ()
        parameter_locations: tuple[str, ...] = ()
        if change.category in _OPERATION_CATEGORIES:
            pass
        elif change.category is ChangeCategory.REQUIRED_PARAMETER_ADDED:
            parameter = _parameter_location(change.location)
            if parameter is None:
                return None
            location, name = parameter
            matched = _parameter_used(call, location, name)
            if not matched:
                return None
            parameter_locations = (f"{location}.{name}",)
            features.append(
                _Feature(
                    "changed_parameter_used",
                    f"{location}.{name}",
                    self.policy.parameter_weight,
                    ResolutionState.EXACT,
                    f"Changed {location} parameter {name!r} is used by the call site.",
                )
            )
        elif change.category in _REQUEST_FIELD_CATEGORIES and change.location.startswith(
            "request."
        ):
            field = _change_field(change.location, "request")
            if field is None:
                return None
            request_fields = _matching_fields(field, call.request_fields)
            if not request_fields:
                return None
            features.append(
                _Feature(
                    "changed_request_field_used",
                    field,
                    self.policy.changed_field_weight,
                    call.request_field_resolution_state,
                    f"Request payload uses changed field {field!r}.",
                )
            )
            certainty = _combine_certainty(certainty, call.request_field_resolution_state)
        elif change.category in _RESPONSE_FIELD_CATEGORIES and change.location.startswith(
            "response."
        ):
            field = _change_field(change.location, "response")
            if field is None:
                return None
            response_fields = _matching_fields(field, call.response_fields_used)
            if not response_fields:
                return None
            features.append(
                _Feature(
                    "changed_response_field_used",
                    field,
                    self.policy.changed_field_weight,
                    call.response_field_resolution_state,
                    f"Response handling uses changed field {field!r}.",
                )
            )
            certainty = _combine_certainty(certainty, call.response_field_resolution_state)
            if not change.location.startswith(
                "response.default"
            ) and not change.location.startswith("response.200"):
                warnings.append("Call analysis does not attribute response usage to a response status code.")
                certainty = _combine_certainty(certainty, ResolutionState.PARTIAL)
        else:
            return None
        return _Evaluation(
            tuple(features),
            tuple(warnings),
            certainty,
            request_fields,
            response_fields,
            parameter_locations,
        )

    def _host_feature(
        self, call: APICallSite
    ) -> tuple[_Feature | None, str | None, ResolutionState]:
        if not self.api_hosts:
            return (
                _Feature(
                    "api_identity",
                    "target host unavailable",
                    0.0,
                    ResolutionState.PARTIAL,
                    "Target API host was not supplied; host identity is unresolved.",
                ),
                "Target API host was not supplied; host identity is unresolved.",
                ResolutionState.PARTIAL,
            )
        if call.resolved_host is None:
            return (
                _Feature(
                    "api_identity",
                    "call host unavailable",
                    self.policy.host_unknown_weight,
                    ResolutionState.PARTIAL,
                    "Call-site host is unresolved; path and method evidence are "
                    "retained with reduced certainty.",
                ),
                "Call-site host is unresolved.",
                ResolutionState.PARTIAL,
            )
        call_host = call.resolved_host
        if call_host is None:
            return None, None, ResolutionState.UNRESOLVED
        if call_host.casefold() not in {host.casefold() for host in self.api_hosts}:
            return None, None, ResolutionState.UNRESOLVED
        return (
            _Feature(
                "api_identity",
                call_host,
                self.policy.host_exact_weight,
                ResolutionState.EXACT,
                f"Call-site host {call_host} matches the target API identity.",
            ),
            None,
            ResolutionState.EXACT,
        )

    def _impact(
        self, change: APIChange, call: APICallSite, evaluation: _Evaluation
    ) -> DirectImpact:
        maximum = (
            self.policy.host_exact_weight
            + self.policy.path_exact_weight
            + self.policy.method_weight
            + self.policy.direct_invocation_weight
            + self.policy.resolution_exact_weight
        )
        if (
            change.category is ChangeCategory.REQUIRED_PARAMETER_ADDED
            or change.category in _REQUEST_FIELD_CATEGORIES
            or change.category in _RESPONSE_FIELD_CATEGORIES
        ):
            maximum += (
                self.policy.parameter_weight
                if change.category is ChangeCategory.REQUIRED_PARAMETER_ADDED
                else self.policy.changed_field_weight
            )
        score = min(
            1.0, max(0.0, sum(feature.contribution for feature in evaluation.features) / maximum)
        )
        evidence = tuple(
            ImpactEvidence(
                feature=feature.name,
                observed_value=feature.observed_value,
                contribution=feature.contribution / maximum,
                resolution_state=feature.resolution_state,
                explanation=feature.explanation,
            )
            for feature in evaluation.features
        )
        reasons = tuple(feature.explanation for feature in evaluation.features)
        identifier = _stable_id(self.policy.version, change.id, call.id)
        return DirectImpact(
            id=identifier,
            change_id=change.id,
            call_site_id=call.id,
            file=call.file,
            symbol=call.owning_symbol,
            line=call.line,
            match_features=tuple(feature.name for feature in evaluation.features),
            impact_score=score,
            evidence=evidence,
            reasons=reasons,
            certainty=evaluation.certainty,
            warnings=evaluation.warnings,
            matched_host=call.resolved_host,
            matched_path=call.resolved_path,
            matched_method=call.method,
            matched_request_fields=evaluation.request_fields,
            matched_response_fields=evaluation.response_fields,
            matched_parameter_locations=evaluation.parameter_locations,
            policy_version=self.policy.version,
        )


def _path_feature(
    api_path: str,
    call_path: str | None,
    resolution: ResolutionState,
    policy: MatchingPolicy,
) -> _Feature | None:
    if call_path is None:
        return None
    api_parts = _path_parts(api_path)
    call_parts = _path_parts(call_path)
    if len(api_parts) != len(call_parts):
        return None
    if api_parts == call_parts:
        return _Feature(
            "endpoint_path_match",
            "exact",
            policy.path_exact_weight,
            ResolutionState.EXACT,
            "Exact normalized endpoint path match.",
        )
    if not all(
        _template_part(left, right) for left, right in zip(api_parts, call_parts, strict=True)
    ):
        return None
    state = (
        ResolutionState.PARTIAL
        if resolution is ResolutionState.PARTIAL or "{dynamic}" in call_parts
        else ResolutionState.EXACT
    )
    weight = (
        policy.path_partial_weight
        if state is ResolutionState.PARTIAL
        else policy.path_template_weight
    )
    explanation = "Path template segments match structurally."
    if state is ResolutionState.PARTIAL:
        explanation = "Path template matches with a dynamically resolved segment."
    return _Feature("endpoint_path_match", "template", weight, state, explanation)


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.split("/") if part)


def _template_part(api_part: str, call_part: str) -> bool:
    return api_part.startswith("{") and api_part.endswith("}") or api_part == call_part


def _parameter_location(location: str) -> tuple[str, str] | None:
    prefix = "parameter."
    if not location.startswith(prefix):
        return None
    value = location.removeprefix(prefix)
    if "." not in value:
        return None
    parts = value.split(".", 1)
    return parts[0], parts[1]


def _parameter_used(call: APICallSite, location: str, name: str) -> bool:
    if location == "query":
        return name in call.query_parameters
    if location == "header":
        return name.casefold() in {value.casefold() for value in call.headers}
    if location == "path":
        return call.resolved_path is not None
    return False


def _change_field(location: str, context: str) -> str | None:
    prefix = f"{context}."
    if not location.startswith(prefix):
        return None
    value = location.removeprefix(prefix)
    if "]" in value:
        value = value.split("]", 1)[1]
    return _normalize_field(value.lstrip(".")) or None


def _matching_fields(target: str, fields: tuple[str, ...]) -> tuple[str, ...]:
    normalized_target = _normalize_field(target)
    return tuple(sorted(field for field in fields if _normalize_field(field) == normalized_target))


def _normalize_field(value: str) -> str:
    parts = [part for part in value.split(".") if part]
    normalized: list[str] = []
    for index, part in enumerate(parts):
        if part == "items" and index + 1 < len(parts) and parts[index + 1] == "items[]":
            continue
        normalized.append(part)
    return ".".join(normalized)


def _combine_certainty(left: ResolutionState, right: ResolutionState) -> ResolutionState:
    if ResolutionState.UNRESOLVED in (left, right):
        return ResolutionState.UNRESOLVED
    if ResolutionState.PARTIAL in (left, right):
        return ResolutionState.PARTIAL
    return ResolutionState.EXACT


def _host(value: str) -> str | None:
    parsed = urlsplit(value)
    return parsed.hostname or (value if "/" not in value and ":" not in value else None)


def _stable_id(*parts: str) -> str:
    return "impact-" + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
