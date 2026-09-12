"""Static Python repository analysis."""

from opentrace.code_analysis.call_graph import analyze_call_graph, build_call_graph
from opentrace.code_analysis.call_models import (
    CallEdge,
    DependencyEdge,
    GraphCoverage,
    StaticCallGraph,
    UnresolvedCall,
)
from opentrace.code_analysis.models import (
    APICallSite,
    CodeSymbol,
    FileAnalysisState,
    RepositoryAnalysis,
    RepositoryFile,
    ResolutionState,
    SymbolKind,
)
from opentrace.code_analysis.repository import (
    RepositoryAnalyzer,
    analyze_repository,
    discover_python_files,
)

__all__ = [
    "APICallSite",
    "CallEdge",
    "CodeSymbol",
    "DependencyEdge",
    "FileAnalysisState",
    "GraphCoverage",
    "RepositoryAnalysis",
    "RepositoryAnalyzer",
    "RepositoryFile",
    "ResolutionState",
    "StaticCallGraph",
    "SymbolKind",
    "UnresolvedCall",
    "analyze_call_graph",
    "analyze_repository",
    "build_call_graph",
    "discover_python_files",
]
