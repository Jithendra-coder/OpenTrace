"""Provider-independent generation of unvalidated migration candidates."""

from opentrace.ai_migration.generator import (
    GenerationProvider,
    MigrationGenerator,
    generation_configuration_from_settings,
    generation_policy_from_settings,
)
from opentrace.ai_migration.models import (
    MIGRATION_GENERATION_POLICY_VERSION,
    MIGRATION_GENERATION_SCHEMA_VERSION,
    GenerationConfiguration,
    GenerationFailure,
    GenerationPolicy,
    GenerationRequest,
    GenerationResponse,
    GenerationStatus,
    MigrationGenerationResult,
    ProposedFileEdit,
    ProposedMigrationPatch,
    ProviderCandidate,
    ProviderEdit,
    ProviderError,
    ProviderErrorCategory,
)
from opentrace.ai_migration.llm_provider import LiveLLMProvider
from opentrace.ai_migration.providers import DeterministicFakeProvider, FakeProviderMode
from opentrace.ai_migration.vertical import analyze_migration_generation_vertical_slice

__all__ = [
    "MIGRATION_GENERATION_POLICY_VERSION",
    "MIGRATION_GENERATION_SCHEMA_VERSION",
    "DeterministicFakeProvider",
    "FakeProviderMode",
    "LiveLLMProvider",
    "GenerationConfiguration",
    "GenerationFailure",
    "GenerationPolicy",
    "GenerationProvider",
    "GenerationRequest",
    "GenerationResponse",
    "GenerationStatus",
    "MigrationGenerationResult",
    "MigrationGenerator",
    "ProposedFileEdit",
    "ProposedMigrationPatch",
    "ProviderCandidate",
    "ProviderEdit",
    "ProviderError",
    "ProviderErrorCategory",
    "analyze_migration_generation_vertical_slice",
    "generation_configuration_from_settings",
    "generation_policy_from_settings",
]
