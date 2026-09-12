"""Direct, evidence-backed API-change impact matching."""

from opentrace.impact.matcher import DirectImpactMatcher, MatchingPolicy
from opentrace.impact.models import (
    DirectImpact,
    ImpactAnalysis,
    ImpactCandidate,
    ImpactEvidence,
    UnmatchedImpact,
)
from opentrace.impact.vertical import analyze_vertical_slice

__all__ = [
    "DirectImpact",
    "DirectImpactMatcher",
    "ImpactAnalysis",
    "ImpactCandidate",
    "ImpactEvidence",
    "MatchingPolicy",
    "UnmatchedImpact",
    "analyze_vertical_slice",
]
