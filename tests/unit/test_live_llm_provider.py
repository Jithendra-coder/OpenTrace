from __future__ import annotations

import hashlib
import io
import json
import urllib.error

import pytest

from opentrace.ai_migration import GenerationRequest, LiveLLMProvider
from opentrace.ai_migration.models import ProviderErrorCategory
from opentrace.migration_context.models import ContextItem, ContextItemRole
from opentrace.routeforge.models import RouteChoice


def _request() -> GenerationRequest:
    content = "def old_call(): pass"
    item = ContextItem(
        id="context-item-1",
        role=ContextItemRole.DIRECT_API_CALL,
        file="src/client.py",
        symbol="src/client.py::send",
        start_line=1,
        end_line=1,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        reason_selected="direct call site",
        priority=1,
        rank=1,
    )
    return GenerationRequest(
        id="request-1",
        generation_policy_version="policy-v1",
        migration_context_id="context-1",
        migration_context_checksum="checksum-1",
        context_policy_version="context-policy-v1",
        api_change_ids=("change-1",),
        target_ids=("target-1",),
        selected_strategy=RouteChoice.SMALL,
        routing_decision_id="route-1",
        router_version="router-v1",
        routing_policy_version="routing-v1",
        provider_adapter_id="live-llm-v1",
        model_id="test-model",
        timeout_seconds=7,
        maximum_response_characters=4096,
        system_instructions="Return the requested JSON only.",
        migration_objective="Update the affected call.",
        context_items=(item,),
        context_item_ids=(item.id,),
        fingerprint="fingerprint-1",
    )


def _candidate() -> str:
    return json.dumps(
        {
            "edits": [
                {
                    "file": "src/client.py",
                    "context_item_id": "context-item-1",
                    "original_text": "old_call()",
                    "replacement_text": "new_call()",
                    "reason": "API contract changed",
                }
            ],
            "explanation": "Update the request.",
        }
    )


@pytest.mark.parametrize(
    ("provider_name", "provider_response", "expected_url"),
    (
        (
            "openai",
            lambda text: {"choices": [{"message": {"content": text}}]},
            "https://api.openai.com/v1/chat/completions",
        ),
        (
            "gemini",
            lambda text: {
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}
                ]
            },
            "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent",
        ),
        (
            "anthropic",
            lambda text: {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]},
            "https://api.anthropic.com/v1/messages",
        ),
        (
            "ollama",
            lambda text: {"response": text},
            "http://127.0.0.1:11434/api/generate",
        ),
    ),
)
def test_live_provider_builds_provider_request_and_normalizes_candidate(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    provider_response: object,
    expected_url: str,
) -> None:
    captured: dict[str, object] = {}
    candidate = _candidate()

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        payload = provider_response(candidate)
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("opentrace.ai_migration.llm_provider.urllib.request.urlopen", fake_urlopen)
    provider = LiveLLMProvider(
        provider_name=provider_name,
        api_key="test-secret",
        ollama_host="http://127.0.0.1:11434",
    )

    response = provider.generate(_request())

    assert response.error is None
    assert response.refusal is None
    assert response.observed_duration_ms is not None
    assert captured["timeout"] == 7
    request = captured["request"]
    assert request.full_url == expected_url
    assert "test-secret" not in request.full_url
    assert "old_call()" in response.content
    parsed = json.loads(response.content)
    assert parsed["edits"][0]["original_text_hash"] == hashlib.sha256(
        b"old_call()"
    ).hexdigest()

    body = json.loads(request.data)
    if provider_name == "openai":
        assert body["messages"][0] == {
            "role": "developer",
            "content": "Return the requested JSON only.",
        }
        assert body["response_format"]["json_schema"]["strict"] is True
        prompt = body["messages"][1]["content"]
    elif provider_name == "gemini":
        assert body["systemInstruction"]["parts"][0]["text"] == "Return the requested JSON only."
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        prompt = body["contents"][0]["parts"][0]["text"]
    else:
        assert body["system"] == "Return the requested JSON only."
        prompt = body["messages"][0]["content"] if provider_name == "anthropic" else body["prompt"]

    prompt_context = json.loads(prompt)["context_items"]
    assert prompt_context == [
        {
            "context_item_id": "context-item-1",
            "file": "src/client.py",
            "symbol": "src/client.py::send",
            "start_line": 1,
            "end_line": 1,
            "content": "def old_call(): pass",
        }
    ]


def test_live_provider_requires_credentials_without_falling_back_to_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = LiveLLMProvider(provider_name="openai").generate(_request())

    assert response.content is None
    assert response.error is not None
    assert response.error.category is ProviderErrorCategory.AUTHENTICATION


def test_live_provider_maps_rate_limit_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def rate_limited(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, None)

    monkeypatch.setattr("opentrace.ai_migration.llm_provider.urllib.request.urlopen", rate_limited)
    response = LiveLLMProvider(provider_name="openai", api_key="test-secret").generate(_request())

    assert response.error is not None
    assert response.error.category is ProviderErrorCategory.RATE_LIMIT
