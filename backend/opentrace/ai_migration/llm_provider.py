"""Production multi-LLM provider adapter supporting Gemini, OpenAI, Claude, Ollama, and local fallback."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from opentrace.ai_migration.models import (
    GenerationRequest,
    GenerationResponse,
    ProviderError,
    ProviderErrorCategory,
)
from opentrace.ai_migration.providers import DeterministicFakeProvider


class LiveLLMProvider:
    """Enterprise multi-LLM provider for intelligent code migration.

    Supports:
      - Google Gemini (GEMINI_API_KEY / GOOGLE_API_KEY)
      - OpenAI (OPENAI_API_KEY)
      - Anthropic (ANTHROPIC_API_KEY)
      - Ollama Local (OLLAMA_HOST, defaults to http://localhost:11434)
      - Deterministic fallback when no API key is provided
    """

    adapter_id = "live-llm-v1"

    def __init__(
        self,
        provider_name: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        ollama_host: str | None = None,
    ) -> None:
        self.provider_name = provider_name or self._detect_provider()
        self.api_key = api_key or self._get_key_for(self.provider_name)
        self.model_name = model_name
        self.ollama_host = ollama_host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self._fallback = DeterministicFakeProvider()

    @staticmethod
    def _detect_provider() -> str:
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return "gemini"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OLLAMA_HOST"):
            return "ollama"
        return "deterministic"

    @staticmethod
    def _get_key_for(provider: str) -> str | None:
        if provider == "gemini":
            return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if provider == "openai":
            return os.environ.get("OPENAI_API_KEY")
        if provider == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY")
        return None

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        start_time = time.monotonic()

        # If deterministic mode or no API key, use proven bounded fallback
        if self.provider_name == "deterministic" or (
            self.provider_name in ("gemini", "openai", "anthropic") and not self.api_key
        ):
            resp = self._fallback.generate(request)
            elapsed = int((time.monotonic() - start_time) * 1000)
            return resp.model_copy(update={"observed_duration_ms": elapsed})

        prompt = self._build_prompt(request)
        try:
            if self.provider_name == "gemini":
                raw_json = self._call_gemini(prompt, request.model_id or self.model_name or "gemini-2.0-flash")
            elif self.provider_name == "openai":
                raw_json = self._call_openai(prompt, request.model_id or self.model_name or "gpt-4o-mini")
            elif self.provider_name == "anthropic":
                raw_json = self._call_anthropic(prompt, request.model_id or self.model_name or "claude-3-5-haiku-20241022")
            elif self.provider_name == "ollama":
                raw_json = self._call_ollama(prompt, request.model_id or self.model_name or "qwen2.5-coder")
            else:
                raw_json = self._fallback.generate(request).content or "{}"

            elapsed = int((time.monotonic() - start_time) * 1000)
            clean_content = self._sanitize_json(raw_json)
            return GenerationResponse(content=clean_content, observed_duration_ms=elapsed)

        except urllib.error.HTTPError as exc:
            elapsed = int((time.monotonic() - start_time) * 1000)
            category = ProviderErrorCategory.AUTHENTICATION if exc.code in (401, 403) else ProviderErrorCategory.UNAVAILABLE
            if exc.code == 429:
                category = ProviderErrorCategory.RATE_LIMIT
            return GenerationResponse(
                error=ProviderError(category=category, message=f"HTTP {exc.code}: {exc.reason}"),
                observed_duration_ms=elapsed,
            )
        except TimeoutError:
            elapsed = int((time.monotonic() - start_time) * 1000)
            return GenerationResponse(
                error=ProviderError(category=ProviderErrorCategory.TIMEOUT, message="Provider request timed out"),
                observed_duration_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - start_time) * 1000)
            return GenerationResponse(
                error=ProviderError(category=ProviderErrorCategory.INVALID_RESPONSE, message=str(exc)),
                observed_duration_ms=elapsed,
            )

    def _build_prompt(self, request: GenerationRequest) -> str:
        source_items = [
            item for item in request.context_items
            if item.file is not None and item.content
        ]
        context_str = "\n\n".join(
            f"--- File: {it.file} (Lines {it.start_line}-{it.end_line}) ---\n{it.content}"
            for it in source_items[:4]
        )

        return (
            f"You are a specialized code migration agent for OpenTrace.\n"
            f"Objective: {request.migration_objective}\n\n"
            f"Target Code Context:\n{context_str}\n\n"
            f"Provide a minimal, bounded patch adapting this code to the updated API contract.\n"
            f"You MUST respond ONLY with valid JSON conforming to this schema:\n"
            f'{{\n'
            f'  "edits": [\n'
            f'    {{\n'
            f'      "file": "relative/path/to/file.py",\n'
            f'      "original_text": "exact snippet of original code to replace",\n'
            f'      "replacement_text": "new replacement code",\n'
            f'      "reason": "Clear explanation of this edit"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "explanation": "High-level summary of the migration"\n'
            f'}}\n'
            f"Do not include markdown code block formatting (```json) or conversational text."
        )

    def _call_gemini(self, prompt: str, model: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            }
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def _call_openai(self, prompt: str, model: str) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, prompt: str, model: str) -> str:
        url = "https://api.anthropic.com/v1/messages"
        payload = json.dumps({
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"]

    def _call_ollama(self, prompt: str, model: str) -> str:
        url = f"{self.ollama_host.rstrip('/')}/api/generate"
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["response"]

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
        return clean
