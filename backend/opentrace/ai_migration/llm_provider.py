"""Live LLM adapters normalized to OpenTrace's guarded candidate contract."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from opentrace.ai_migration.models import (
    GenerationRequest,
    GenerationResponse,
    ProviderError,
    ProviderErrorCategory,
)

_OPENAI_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "context_item_id": {"type": "string"},
                    "original_text": {"type": "string"},
                    "replacement_text": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "file",
                    "context_item_id",
                    "original_text",
                    "replacement_text",
                    "reason",
                ],
                "additionalProperties": False,
            },
        },
        "explanation": {"type": "string"},
    },
    "required": ["edits", "explanation"],
    "additionalProperties": False,
}


class _ProviderRefusal(Exception):
    pass


class LiveLLMProvider:
    """Provider adapter for OpenAI, Gemini, Anthropic, and local Ollama."""

    adapter_id = "live-llm-v1"
    _SUPPORTED_PROVIDERS = frozenset({"openai", "gemini", "anthropic", "ollama"})

    def __init__(
        self,
        provider_name: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        ollama_host: str | None = None,
    ) -> None:
        selected = (provider_name or os.environ.get("AI_PROVIDER") or "auto").lower()
        self.provider_name = self._detect_provider() if selected == "auto" else selected
        self.api_key = api_key or self._get_key_for(self.provider_name)
        self.model_name = model_name
        self.ollama_host = ollama_host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    @staticmethod
    def _detect_provider() -> str:
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return "gemini"
        if os.environ.get("OLLAMA_HOST"):
            return "ollama"
        return "deterministic"

    @staticmethod
    def _get_key_for(provider: str) -> str | None:
        return {
            "gemini": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            "openai": os.environ.get("OPENAI_API_KEY"),
            "anthropic": os.environ.get("ANTHROPIC_API_KEY"),
        }.get(provider)

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        start_time = time.monotonic()

        if self.provider_name not in self._SUPPORTED_PROVIDERS:
            return self._error(
                ProviderErrorCategory.UNAVAILABLE,
                "No live LLM provider is configured. Set AI_PROVIDER and provider credentials.",
                start_time,
            )
        if self.provider_name != "ollama" and not self.api_key:
            return self._error(
                ProviderErrorCategory.AUTHENTICATION,
                f"No API key is configured for the {self.provider_name} provider.",
                start_time,
            )

        prompt = self._build_prompt(request)
        model = request.model_id or self.model_name
        if not model:
            return self._error(
                ProviderErrorCategory.INVALID_RESPONSE,
                "No model is configured for this generation request.",
                start_time,
            )

        try:
            if self.provider_name == "gemini":
                raw_json = self._call_gemini(
                    prompt, request.system_instructions, model, request.timeout_seconds
                )
            elif self.provider_name == "openai":
                raw_json = self._call_openai(
                    prompt, request.system_instructions, model, request.timeout_seconds
                )
            elif self.provider_name == "anthropic":
                raw_json = self._call_anthropic(
                    prompt, request.system_instructions, model, request.timeout_seconds
                )
            else:
                raw_json = self._call_ollama(
                    prompt, request.system_instructions, model, request.timeout_seconds
                )
            return GenerationResponse(
                content=self._sanitize_json(raw_json),
                observed_duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        except _ProviderRefusal as exc:
            return GenerationResponse(
                refusal=str(exc),
                observed_duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        except urllib.error.HTTPError as exc:
            category = (
                ProviderErrorCategory.AUTHENTICATION
                if exc.code in (401, 403)
                else ProviderErrorCategory.RATE_LIMIT
                if exc.code == 429
                else ProviderErrorCategory.INVALID_RESPONSE
                if 400 <= exc.code < 500
                else ProviderErrorCategory.UNAVAILABLE
            )
            return self._error(
                category,
                f"Provider returned HTTP {exc.code}; check the configured model and provider status.",
                start_time,
            )
        except urllib.error.URLError as exc:
            category = (
                ProviderErrorCategory.TIMEOUT
                if isinstance(exc.reason, TimeoutError)
                else ProviderErrorCategory.UNAVAILABLE
            )
            return self._error(category, "Provider connection failed.", start_time)
        except TimeoutError:
            return self._error(
                ProviderErrorCategory.TIMEOUT, "Provider request timed out.", start_time
            )
        except Exception:
            return self._error(
                ProviderErrorCategory.INVALID_RESPONSE,
                "Provider returned an unreadable or unsupported response.",
                start_time,
            )

    @staticmethod
    def _error(
        category: ProviderErrorCategory, message: str, start_time: float
    ) -> GenerationResponse:
        return GenerationResponse(
            error=ProviderError(category=category, message=message),
            observed_duration_ms=int((time.monotonic() - start_time) * 1000),
        )

    @staticmethod
    def _build_prompt(request: GenerationRequest) -> str:
        context = [
            {
                "context_item_id": item.id,
                "file": item.file,
                "symbol": item.symbol,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "content": item.content,
            }
            for item in request.context_items
            if item.file is not None and item.content
        ]
        return json.dumps(
            {
                "migration_objective": request.migration_objective,
                "selected_strategy": request.selected_strategy.value,
                "api_change_ids": request.api_change_ids,
                "target_ids": request.target_ids,
                "context_items": context,
                "required_response_contract": _OPENAI_CANDIDATE_SCHEMA,
            },
            ensure_ascii=False,
        )

    def _call_gemini(self, prompt: str, instructions: str, model: str, timeout: int) -> str:
        model_path = urllib.parse.quote(model, safe="-._")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_path}:generateContent"
        payload = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key or ""},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidate = data["candidates"][0]
            if candidate.get("finishReason") == "SAFETY":
                raise _ProviderRefusal("Provider refused the request for safety reasons.")
            return candidate["content"]["parts"][0]["text"]

    def _call_openai(self, prompt: str, instructions: str, model: str, timeout: int) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "developer", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "migration_candidate",
                        "strict": True,
                        "schema": _OPENAI_CANDIDATE_SCHEMA,
                    },
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            message = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]
            if message.get("refusal"):
                raise _ProviderRefusal(message["refusal"])
            return message["content"]

    def _call_anthropic(self, prompt: str, instructions: str, model: str, timeout: int) -> str:
        payload = json.dumps(
            {
                "model": model,
                "max_tokens": 4096,
                "system": instructions,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("stop_reason") == "refusal":
                raise _ProviderRefusal("Provider refused the request.")
            return data["content"][0]["text"]

    def _call_ollama(self, prompt: str, instructions: str, model: str, timeout: int) -> str:
        url = f"{self.ollama_host.rstrip('/')}/api/generate"
        payload = json.dumps(
            {"model": model, "system": instructions, "prompt": prompt, "stream": False, "format": "json"}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))["response"]

    @staticmethod
    def _sanitize_json(text: str) -> str:
        clean = text.strip()
        if clean.startswith("```"):
            lines = clean.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean = "\n".join(lines).strip()
        try:
            candidate = json.loads(clean)
        except (TypeError, ValueError):
            return clean
        if not isinstance(candidate, dict) or not isinstance(candidate.get("edits"), list):
            return clean
        for edit in candidate["edits"]:
            if isinstance(edit, dict) and isinstance(edit.get("original_text"), str):
                edit["original_text_hash"] = hashlib.sha256(
                    edit["original_text"].encode("utf-8")
                ).hexdigest()
        return json.dumps(candidate, ensure_ascii=False)
