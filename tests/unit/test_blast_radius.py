from opentrace.blast_radius import analyze_blast_radius
from opentrace.blast_radius.models import ImpactType, RiskLevel
from opentrace.code_analysis.call_models import CallEdge, GraphCoverage, StaticCallGraph
from opentrace.code_analysis.models import CodeSymbol, ResolutionState, SymbolKind
from opentrace.contracts.models import (
    APIChange,
    BreakingClassification,
    ChangeCategory,
    ChangeCertainty,
    ChangeSeverity,
    CompatibilityDirection,
)
from opentrace.impact.models import DirectImpact


def _symbol(name: str) -> CodeSymbol:
    return CodeSymbol(
        id=f"symbol-{name}",
        file=f"{name}.py",
        qualified_name=f"{name}.py::{name}",
        kind=SymbolKind.FUNCTION,
        line=1,
        end_line=2,
        column=0,
        end_column=1,
    )


def _graph(symbols: tuple[CodeSymbol, ...], pairs: tuple[tuple[str, str], ...]) -> StaticCallGraph:
    by_name = {
        symbol.qualified_name.split("::", 1)[1].removesuffix(".py"): symbol
        for symbol in symbols
    }
    edges = tuple(
        CallEdge(
            id=f"edge-{caller}-{callee}",
            caller_symbol_id=by_name[caller].id,
            callee_symbol_id=by_name[callee].id,
            caller_symbol=by_name[caller].qualified_name,
            callee_symbol=by_name[callee].qualified_name,
            caller_file=by_name[caller].file,
            callee_file=by_name[callee].file,
            line=1,
            column=0,
            resolution_state=ResolutionState.EXACT,
        )
        for caller, callee in pairs
    )
    return StaticCallGraph(
        nodes=symbols,
        edges=edges,
        coverage=GraphCoverage(
            files_discovered=len(symbols),
            files_parsed=len(symbols),
            symbols_discovered=len(symbols),
            call_expressions_inspected=len(edges),
            edges_resolved=len(edges),
        ),
    )


def _change(change_id: str = "change-1") -> APIChange:
    return APIChange(
        id=change_id,
        category=ChangeCategory.REQUEST_PROPERTY_REMOVED,
        path="/payments",
        method="POST",
        location="request.body.amount",
        severity=ChangeSeverity.HIGH,
        breaking_classification=BreakingClassification.CLIENT_BREAKING,
        compatibility_direction=CompatibilityDirection.CLIENT_TO_SERVER,
        certainty=ChangeCertainty.EXACT,
        reason="test change",
    )


def _direct(
    symbol: CodeSymbol, change_id: str = "change-1", impact_id: str | None = None
) -> DirectImpact:
    return DirectImpact(
        id=impact_id or f"impact-{symbol.id}",
        change_id=change_id,
        call_site_id="missing-call-site",
        file=symbol.file,
        symbol=symbol.qualified_name,
        line=1,
        impact_score=1.0,
        certainty=ResolutionState.EXACT,
        policy_version="direct-impact-baseline-v1",
    )


def test_cycle_and_diamond_propagation_are_finite_and_deduplicated() -> None:
    cycle_symbols = tuple(_symbol(name) for name in ("a", "b", "direct"))
    cycle = analyze_blast_radius(
        [_direct(cycle_symbols[2])],
        _graph(cycle_symbols, (("a", "b"), ("b", "a"), ("b", "direct"))),
        changes=[_change()],
    )
    assert [(item.symbol, item.distance) for item in cycle.impacted_symbols] == [
        ("direct.py::direct", 0),
        ("b.py::b", 1),
        ("a.py::a", 2),
    ]

    diamond_symbols = tuple(_symbol(name) for name in ("a", "b", "c", "direct"))
    diamond = analyze_blast_radius(
        [_direct(diamond_symbols[3])],
        _graph(
            diamond_symbols,
            (("a", "b"), ("a", "c"), ("b", "direct"), ("c", "direct")),
        ),
        changes=[_change()],
    )
    assert [(item.symbol, item.distance) for item in diamond.impacted_symbols] == [
        ("direct.py::direct", 0),
        ("b.py::b", 1),
        ("c.py::c", 1),
        ("a.py::a", 2),
    ]
    assert len({item.symbol for item in diamond.impacted_symbols}) == 4


def test_multiple_sources_share_upstream_and_keep_shortest_provenance() -> None:
    symbols = tuple(_symbol(name) for name in ("upstream", "first", "second"))
    graph = _graph(symbols, (("upstream", "first"), ("upstream", "second"), ("first", "second")))
    changes = [_change("change-1"), _change("change-2")]
    impacts = [
        _direct(symbols[1], "change-1", "impact-first"),
        _direct(symbols[2], "change-2", "impact-second"),
    ]

    result = analyze_blast_radius(impacts, graph, changes=changes)
    upstream = next(
        item for item in result.impacted_symbols if item.symbol == "upstream.py::upstream"
    )

    assert upstream.impact_type is ImpactType.INDIRECT
    assert upstream.distance == 1
    assert upstream.source_direct_impact_ids == ("impact-first", "impact-second")
    assert upstream.source_change_ids == ("change-1", "change-2")
    assert {e.distance for e in upstream.propagation} == {1}


def test_partial_seed_and_incomplete_graph_remain_uncertain() -> None:
    symbols = tuple(_symbol(name) for name in ("caller", "direct"))
    graph = _graph(symbols, (("caller", "direct"),)).model_copy(
        update={
            "coverage": GraphCoverage(
                files_discovered=2,
                files_parsed=1,
                files_failed=1,
                calls_unresolved=1,
            )
        }
    )
    direct = _direct(symbols[1]).model_copy(update={"certainty": ResolutionState.PARTIAL})

    result = analyze_blast_radius([direct], graph, changes=[_change()])
    caller = next(item for item in result.impacted_symbols if item.symbol == "caller.py::caller")

    assert caller.certainty is ResolutionState.PARTIAL
    assert result.risk_assessment is not None
    assert result.risk_assessment.risk_score <= 100
    assert result.risk_assessment.certainty is ResolutionState.PARTIAL
    assert result.risk_assessment.risk_level in set(RiskLevel)
    assert "incomplete" in " ".join(result.warnings)


def test_deterministic_serialization_and_disconnected_exclusion() -> None:
    symbols = tuple(_symbol(name) for name in ("direct", "caller", "unrelated"))
    graph = _graph(symbols, (("caller", "direct"),))
    direct = _direct(symbols[0])
    first = analyze_blast_radius([direct], graph, changes=[_change()])
    second = analyze_blast_radius([direct], graph, changes=[_change()])

    assert first.canonical_json() == second.canonical_json()
    assert all(item.symbol != "unrelated.py::unrelated" for item in first.impacted_symbols)
    assert first.maximum_distance == 1
