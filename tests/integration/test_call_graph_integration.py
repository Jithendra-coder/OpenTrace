from pathlib import Path

from opentrace.code_analysis import build_call_graph


def test_real_demo_call_graph_preserves_m4_direct_only_boundary() -> None:
    root = Path(__file__).parents[2] / "demo" / "ecommerce"
    graph = build_call_graph(root)

    edges = {(edge.caller_symbol, edge.callee_symbol, edge.edge_kind) for edge in graph.edges}

    assert (
        "orders.py::place_order",
        "checkout.py::checkout",
        "CALLS",
    ) in edges
    assert (
        "checkout.py::checkout",
        "payment_service.py::create_payment",
        "CALLS",
    ) in edges
    assert graph.callers("payment_service.py::create_payment")[0].qualified_name == (
        "checkout.py::checkout"
    )
    assert graph.callees("orders.py::place_order")[0].qualified_name == (
        "checkout.py::checkout"
    )
    assert graph.coverage.edges_resolved == 2
    assert graph.coverage.calls_unresolved == 2
