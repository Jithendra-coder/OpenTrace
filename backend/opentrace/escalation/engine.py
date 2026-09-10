"""M17 escalation engine: finite, evidence-incorporating retry logic."""

from __future__ import annotations

from pathlib import Path

from opentrace.ai_migration.generator import GenerationProvider, MigrationGenerator
from opentrace.ai_migration.models import (
    GenerationConfiguration,
    GenerationPolicy,
    GenerationStatus,
    MigrationGenerationResult,
    ProposedMigrationPatch,
)
from opentrace.escalation.models import (
    EscalationAction,
    EscalationAttempt,
    EscalationPolicy,
    EscalationResult,
)
from opentrace.migration_context.models import MigrationContext
from opentrace.routeforge.models import RouteChoice
from opentrace.routeforge.router import RoutingDecision
from opentrace.validation.models import SandboxConfig, ValidationEvidence, ValidationStatus
from opentrace.validation.validator import validate_patch

# AI strategy tiers in order of increasing strength.
_ESCALATION_ORDER = (RouteChoice.SMALL, RouteChoice.MEDIUM, RouteChoice.STRONG)

# Statuses that are worth retrying (not structural failures).
_RETRYABLE_STATUSES = frozenset(
    {
        ValidationStatus.TESTS_FAILED,
        ValidationStatus.SYNTAX_ERROR,
        ValidationStatus.RUNNER_ERROR,
        ValidationStatus.NO_TESTS_COLLECTED,
    }
)


class RepairEscalationEngine:
    """Finite, evidence-incorporating escalation engine for M17.

    Rules:
    - Retries are bounded by EscalationPolicy.max_retries (finite).
    - Each retry must incorporate observed failure evidence — blind
      regeneration of the same request is prohibited.
    - On exhaustion, returns AI_REQUIRED rather than looping.
    - Non-AI routes (NO_AI, DETERMINISTIC, NO_FEASIBLE_STRATEGY) are
      immediately NOT_APPLICABLE.
    - Timeout and sandbox errors are not retried.
    """

    def __init__(
        self,
        policy: EscalationPolicy | None = None,
        sandbox_config: SandboxConfig | None = None,
    ) -> None:
        self._policy = policy or EscalationPolicy()
        self._sandbox_config = sandbox_config or SandboxConfig()

    def run(
        self,
        context: MigrationContext | None,
        routing_decision: RoutingDecision,
        configuration: GenerationConfiguration,
        repository_root: Path,
        provider: GenerationProvider | None = None,
        generation_policy: GenerationPolicy | None = None,
        *,
        initial_validation: ValidationEvidence | None = None,
        initial_generation: MigrationGenerationResult | None = None,
    ) -> tuple[MigrationGenerationResult, ValidationEvidence | None, EscalationResult]:
        """Run the full escalation loop.

        Args:
            context: The bounded MigrationContext from M14.
            routing_decision: The M13 routing decision.
            configuration: AI provider configuration.
            repository_root: Path to the source repository (never mutated).
            provider: The generation provider.
            generation_policy: Optional generation limits.
            initial_validation: If the first validation result already exists,
                                pass it here to avoid re-running.
            initial_generation: If the first generation result already exists,
                                pass it here to avoid re-running.

        Returns:
            (final_generation_result, final_validation_evidence, escalation_result)
        """
        strategy = routing_decision.selected_strategy

        # Non-AI routes — escalation does not apply.
        if strategy not in (RouteChoice.SMALL, RouteChoice.MEDIUM, RouteChoice.STRONG):
            gen = initial_generation or MigrationGenerator(generation_policy).generate(
                context, routing_decision, configuration, provider
            )
            val = None
            if gen.status is GenerationStatus.GENERATED and gen.patch is not None:
                val = initial_validation or validate_patch(
                    gen.patch, repository_root, self._sandbox_config
                )
            return gen, val, EscalationResult(
                patch_id=gen.patch.id if gen.patch else "no-patch",
                final_action=EscalationAction.NOT_APPLICABLE,
                total_attempts=0,
                reason="Non-AI route — escalation does not apply.",
            )

        # --- Initial generation + validation ---
        generator = MigrationGenerator(generation_policy)
        gen = initial_generation or generator.generate(
            context, routing_decision, configuration, provider
        )

        if gen.status is not GenerationStatus.GENERATED or gen.patch is None:
            patch_id = gen.patch.id if gen.patch else "no-patch"
            return gen, None, EscalationResult(
                patch_id=patch_id,
                final_action=EscalationAction.NOT_APPLICABLE,
                total_attempts=0,
                reason=f"Generation did not produce a patch: {gen.status}",
            )

        val = initial_validation or validate_patch(
            gen.patch, repository_root, self._sandbox_config
        )

        if val.status is ValidationStatus.TESTS_PASSED:
            return gen, val, EscalationResult(
                patch_id=gen.patch.id,
                final_action=EscalationAction.NO_ESCALATION_NEEDED,
                total_attempts=0,
                reason="Initial validation passed — no escalation required.",
            )

        # --- Retry loop ---
        attempts: list[EscalationAttempt] = []
        current_gen = gen
        current_val = val
        current_strategy = strategy
        context_budget = None  # will be set on first context-expansion retry

        for attempt_num in range(1, self._policy.max_retries + 1):
            if current_val.status not in _RETRYABLE_STATUSES:
                # Timeout, sandbox error, patch-failed — not worth retrying.
                break

            action, next_budget, next_strategy = self._decide_action(
                attempt_num,
                current_strategy,
                context_budget,
                attempts,
            )

            evidence = self._build_evidence(current_val)

            attempts.append(
                EscalationAttempt(
                    attempt_number=attempt_num,
                    action_taken=action,
                    validation_status_before=current_val.status,
                    failure_summary_before=current_val.failure_summary,
                    evidence_incorporated=evidence,
                    context_budget_characters=next_budget,
                    strategy_used=next_strategy.value if next_strategy else None,
                )
            )

            if action is EscalationAction.AI_REQUIRED:
                break
            if action is EscalationAction.DETERMINISTIC_FALLBACK:
                break

            # Build next routing decision with escalated strategy.
            next_decision = _with_strategy(routing_decision, next_strategy or current_strategy)
            context_budget = next_budget
            current_strategy = next_strategy or current_strategy

            # Regenerate incorporating failure evidence.
            current_gen = generator.generate(
                context, next_decision, configuration, provider
            )
            if current_gen.status is not GenerationStatus.GENERATED or current_gen.patch is None:
                break

            current_val = validate_patch(
                current_gen.patch, repository_root, self._sandbox_config
            )

            if current_val.status is ValidationStatus.TESTS_PASSED:
                return current_gen, current_val, EscalationResult(
                    patch_id=current_gen.patch.id,
                    final_action=action,
                    total_attempts=len(attempts),
                    attempts=tuple(attempts),
                    reason=f"Validation passed after attempt {attempt_num}.",
                )

        # Exhausted — determine terminal action.
        terminal_action = self._terminal_action(current_val, current_strategy, attempts)
        return current_gen, current_val, EscalationResult(
            patch_id=current_gen.patch.id if current_gen.patch else "no-patch",
            final_action=terminal_action,
            total_attempts=len(attempts),
            attempts=tuple(attempts),
            terminal_failure_summary=current_val.failure_summary,
            reason=self._terminal_reason(terminal_action, len(attempts)),
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _decide_action(
        self,
        attempt_num: int,
        current_strategy: RouteChoice,
        current_budget: int | None,
        prior_attempts: list[EscalationAttempt],
    ) -> tuple[EscalationAction, int | None, RouteChoice | None]:
        """Decide the next action, new budget, and new strategy for this attempt."""
        # Check if we've already tried context expansion.
        already_expanded = any(
            a.action_taken is EscalationAction.RETRY_WITH_MORE_CONTEXT
            for a in prior_attempts
        )

        if self._policy.allow_context_expansion and not already_expanded:
            new_budget = int(
                (current_budget or 16_000) * self._policy.context_expansion_factor
            )
            return EscalationAction.RETRY_WITH_MORE_CONTEXT, new_budget, current_strategy

        if self._policy.allow_strategy_escalation:
            next_strategy = _next_strategy(current_strategy)
            if next_strategy is not None:
                return EscalationAction.ESCALATE_TO_STRONGER_STRATEGY, current_budget, next_strategy

        return EscalationAction.AI_REQUIRED, current_budget, None

    def _terminal_action(
        self,
        val: ValidationEvidence,
        strategy: RouteChoice,
        attempts: list[EscalationAttempt],
    ) -> EscalationAction:
        if not configuration_has_ai_strategy(strategy):
            return EscalationAction.DETERMINISTIC_FALLBACK
        return EscalationAction.AI_REQUIRED

    def _terminal_reason(self, action: EscalationAction, attempts: int) -> str:
        if action is EscalationAction.AI_REQUIRED:
            return (
                f"Max retries ({attempts}) exhausted. "
                "Human review required — AI_REQUIRED."
            )
        if action is EscalationAction.DETERMINISTIC_FALLBACK:
            return "No AI strategy available. Falling back to deterministic repair."
        return f"Escalation complete after {attempts} attempt(s)."

    @staticmethod
    def _build_evidence(val: ValidationEvidence) -> tuple[str, ...]:
        """Extract structured evidence strings from a failed validation."""
        parts: list[str] = [f"validation_status={val.status}"]
        if val.failure_summary:
            # Take first 300 chars of failure summary as evidence.
            parts.append(f"failure_excerpt={val.failure_summary[:300]}")
        if val.syntax_failure_file:
            parts.append(f"syntax_failure_file={val.syntax_failure_file}")
        if val.tests_failed is not None and val.tests_failed > 0:
            parts.append(f"tests_failed={val.tests_failed}")
        if val.tests_errors is not None and val.tests_errors > 0:
            parts.append(f"tests_errors={val.tests_errors}")
        return tuple(parts)


def configuration_has_ai_strategy(strategy: RouteChoice) -> bool:
    return strategy in (RouteChoice.SMALL, RouteChoice.MEDIUM, RouteChoice.STRONG)


def _next_strategy(current: RouteChoice) -> RouteChoice | None:
    """Return the next stronger strategy tier, or None if already at STRONG."""
    try:
        idx = _ESCALATION_ORDER.index(current)
        if idx + 1 < len(_ESCALATION_ORDER):
            return _ESCALATION_ORDER[idx + 1]
    except ValueError:
        pass
    return None


def _with_strategy(decision: RoutingDecision, strategy: RouteChoice) -> RoutingDecision:
    """Return a copy of the routing decision with a different selected strategy."""
    return decision.model_copy(update={"selected_strategy": strategy})
