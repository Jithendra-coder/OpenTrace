"""Canonical static call-graph artifacts for M5."""

from __future__ import annotations

import networkx as nx  # type: ignore[import-untyped]
from pydantic import Field

from opentrace.code_analysis.models import (
    APICallSite,
    CanonicalModel,
    CodeSymbol,
    ResolutionState,
)


class CallEdge(CanonicalModel):
    """One evidence-backed caller-to-callee relationship."""

    id: str
    edge_kind: str = "CALLS"
    caller_symbol_id: str
    callee_symbol_id: str
    caller_symbol: str
    callee_symbol: str
    caller_file: str
    callee_file: str
    line: int
    column: int
    resolution_state: ResolutionState
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def source_line(self) -> int:
        return self.line

    @property
    def source_column(self) -> int:
        return self.column

    @property
    def edge_type(self) -> str:
        return self.edge_kind

    @property
    def type(self) -> str:
        return self.edge_kind


class UnresolvedCall(CanonicalModel):
    """A call expression whose local repository target was not proven."""

    id: str
    caller_symbol_id: str
    caller_symbol: str
    caller_file: str
    line: int
    column: int
    raw_call: str
    resolution_state: ResolutionState = ResolutionState.UNRESOLVED
    reason: str
    warnings: tuple[str, ...] = ()


class GraphCoverage(CanonicalModel):
    """Counts describing what the graph construction actually inspected."""

    files_discovered: int = 0
    files_parsed: int = 0
    files_failed: int = 0
    symbols_discovered: int = 0
    call_expressions_inspected: int = 0
    edges_resolved: int = 0
    calls_unresolved: int = 0


class StaticCallGraph(CanonicalModel):
    """Deterministic local call graph with NetworkX-backed adjacency queries."""

    policy_version: str = "python-callgraph-v1"
    nodes: tuple[CodeSymbol, ...] = ()
    edges: tuple[CallEdge, ...] = ()
    unresolved_calls: tuple[UnresolvedCall, ...] = ()
    coverage: GraphCoverage = Field(default_factory=GraphCoverage)
    warnings: tuple[str, ...] = ()
    api_call_sites: tuple[APICallSite, ...] = ()

    def _symbol_index(self) -> dict[str, CodeSymbol]:
        return {symbol.id: symbol for symbol in self.nodes}

    def _resolve_symbol(self, symbol: str) -> CodeSymbol | None:
        for candidate in self.nodes:
            if candidate.id == symbol or candidate.qualified_name == symbol:
                return candidate
        return None

    @property
    def nx_graph(self) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph()
        graph.graph["policy_version"] = self.policy_version
        for node in self.nodes:
            graph.add_node(node.id, symbol=node)
        for edge in self.edges:
            graph.add_edge(
                edge.caller_symbol_id,
                edge.callee_symbol_id,
                key=edge.id,
                edge=edge,
            )
        return graph

    def callers(self, symbol: str) -> tuple[CodeSymbol, ...]:
        target = self._resolve_symbol(symbol)
        if target is None:
            return ()
        graph = self.nx_graph
        symbols = self._symbol_index()
        return tuple(
            sorted(
                (symbols[node] for node in graph.predecessors(target.id) if node in symbols),
                key=lambda value: (value.qualified_name, value.id),
            )
        )

    def callees(self, symbol: str) -> tuple[CodeSymbol, ...]:
        source = self._resolve_symbol(symbol)
        if source is None:
            return ()
        graph = self.nx_graph
        symbols = self._symbol_index()
        return tuple(
            sorted(
                (symbols[node] for node in graph.successors(source.id) if node in symbols),
                key=lambda value: (value.qualified_name, value.id),
            )
        )


DependencyEdge = CallEdge
