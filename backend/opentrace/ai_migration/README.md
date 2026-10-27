# Guarded AI migration

OpenTrace can request a structured, unvalidated migration candidate after M14 selects bounded context and M13 chooses
an abstract `SMALL`, `MEDIUM`, or `STRONG` route. `LiveLLMProvider` supports OpenAI, Gemini, Anthropic, and Ollama;
the CLI uses it only with `--ai-enabled` or `AI_ENABLED=true`. Without that opt-in, the local deterministic provider
keeps the bundled demo working without credentials.

Configure `AI_PROVIDER` as `openai`, `gemini`, `anthropic`, or `ollama`. `auto` prefers available OpenAI, Anthropic,
then Gemini credentials, and attempts the local Ollama endpoint if no cloud key is set. Set the corresponding API key
and `AI_MODEL_SMALL`, `AI_MODEL_MEDIUM`, and/or `AI_MODEL_STRONG` to model IDs supported by that provider. The selected
strategy must have a model ID. `AI_PROVIDER_ENDPOINT` overrides the Ollama host. Provider calls use the generation
timeout and return explicit errors; they never silently substitute a deterministic patch when credentials or the
provider are unavailable.

Only selected context is sent to the configured provider. OpenAI requests use strict structured output, and all provider
responses pass the same Pydantic schema, context-item authorization, exact-source-hash, path, size, overlap, and Python
syntax checks. API keys are read from environment variables and are not written to migration plans. Treat remote
providers as receiving source code; use Ollama when code must stay on a machine you control.

Candidates remain in-memory proposals. They are never applied or executed by generation; run `opentrace validate` to
apply the candidate to a temporary repository copy and test it in a network-disabled Docker container. Docker is
required and there is no host-execution fallback. Review the result before applying the patch to the original source.
