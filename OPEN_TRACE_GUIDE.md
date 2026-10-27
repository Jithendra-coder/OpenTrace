# OpenTrace — Operational and AI Architecture Guide

OpenTrace compares OpenAPI versions, traces affected code, prepares a bounded migration candidate, and validates that candidate before a developer applies it. Generation is opt-in; the default path remains deterministic.

## Pipeline

```text
Old/new OpenAPI specs
        ↓
Contract diff + repository AST/call-site analysis
        ↓
Blast-radius graph + bounded, provenance-tracked RAG context
        ↓
RouteForge strategy + structured candidate generation
        ↓
Source/path/hash/syntax checks
        ↓
Docker-isolated tests + per-run evaluation report
        ↓
Developer review → apply or draft PR
```

`analyze` and `migrate` do not modify the target repository. A generated patch is a proposal. `validate` applies it to a temporary repository copy, checks syntax, then runs the repository's pytest suite in a network-disabled Docker container with resource limits. Docker is required; validation fails closed if the daemon is unavailable and never executes repository tests on the host. The runner image contains only `pytest` and `requests`, so tests that need other packages can fail for missing dependencies.

## Quick start

From the repository root:

```powershell
python -m pip install -e .
$env:PYTHONPATH = (Resolve-Path backend).Path

opentrace analyze --old sample1/api_v1.yaml --new sample1/api_v2.yaml --repo sample1 --output-dir .opentrace-sample1
opentrace migrate --workspace .opentrace-sample1 --policy balanced
opentrace validate --workspace .opentrace-sample1
opentrace evaluate --workspace .opentrace-sample1
```

The same commands work for a project of your own by supplying its old and new specifications and repository path. The CLI accepts `--old` and `--new` for the specification paths.

## Graph-grounded RAG

OpenTrace implements **code RAG with static-graph retrieval**. It combines the OpenAPI change with exact API call sites, target symbols, and reachable callers. The context selector prioritizes required direct evidence, adds nearby callers within file and character budgets, and records provenance IDs, content hashes, graph distance, omissions, and a manifest checksum. The model receives these selected spans rather than the entire repository.

This retrieval path does not use embeddings or a vector database: exact dependency links are more useful for “which code calls this changed API?” than semantic similarity alone. The current context selector reads evidence-addressed Python source spans. Retrieval coverage and context size are measurable; they do not establish that a generated repair is semantically correct. That requires a curated, repository-held-out benchmark with human-reviewed outcomes.

The per-run `opentrace evaluate` command writes `.opentrace/generation-evaluation.json`. It reports retrieval selection and omissions, generation status, patch identity, and validation gates. Semantic correctness is explicitly reported as `NOT_ASSESSED` unless a separate benchmark evaluates it.

## Live model providers

The deterministic provider is the default. To opt into a live model, configure a provider, a supported model ID for the selected strategy, and credentials where required:

```powershell
$env:AI_PROVIDER = "openai"
$env:OPENAI_API_KEY = "your-api-key"
$env:AI_MODEL_SMALL = "your-supported-model-id"
opentrace migrate --workspace .opentrace-sample1 --policy balanced --ai-enabled
opentrace validate --workspace .opentrace-sample1
opentrace evaluate --workspace .opentrace-sample1
```

Supported providers are OpenAI, Gemini, Anthropic, and local Ollama. `AI_PROVIDER=auto` selects a configured cloud key and otherwise tries Ollama at `OLLAMA_HOST` (default `http://localhost:11434`). Each live route needs a configured model ID. Missing credentials, model configuration, provider errors, and refusals are surfaced; live calls do not silently fall back to the fake provider.

Only selected context is sent to a provider. Cloud providers receive repository source text, so use Ollama when source must remain on a machine you control. Keep API keys in environment variables or an ignored `.env` file; never commit them.

## CLI and dashboard

The main CLI commands are:

| Command | Purpose |
|---|---|
| `analyze` | Compare contracts and inventory affected code. |
| `migrate` | Build a deterministic or live-model candidate, depending on opt-in configuration. |
| `validate` | Apply the candidate in a temporary copy and run syntax/tests. |
| `evaluate` | Save retrieval, generation, and validation evidence. |
| `apply` | Apply a validated proposal to the target repository. |
| `pr` | Create a draft pull request from the reviewed migration workspace. |

Start the local dashboard with:

```powershell
$env:OPENTRACE_WORKSPACE = "."
uvicorn opentrace.main:app --port 8000
```

The Docker Compose setup builds the dashboard image and serves it at `http://127.0.0.1:8000`. It does not mount the
host Docker socket; run validation from a host CLI with Docker available rather than granting the dashboard container
control of the host daemon.

## Project verification

Run the full test suite with `python -m pytest -q`. The checked-in demo screenshots and the latest verified counts are in the root README. The current results distinguish a fixture-backed migration demonstration from the actual repository's test and static self-scan; the fixture run uses a deterministic fake provider, not live LLM inference.
