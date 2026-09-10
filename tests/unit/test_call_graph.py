from pathlib import Path

from opentrace.code_analysis import build_call_graph


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_cross_module_aliases_relative_imports_and_same_names(tmp_path: Path) -> None:
    _write(tmp_path, "payments/__init__.py", "")
    _write(tmp_path, "emails/__init__.py", "")
    _write(tmp_path, "services/__init__.py", "")
    _write(tmp_path, "payments/helpers.py", "def send() -> None:\n    pass\n")
    _write(tmp_path, "emails/helpers.py", "def send() -> None:\n    pass\n")
    _write(tmp_path, "services/payment.py", "def create() -> None:\n    pass\n")
    _write(
        tmp_path,
        "services/caller.py",
        "from payments.helpers import send as pay_send\n"
        "from emails.helpers import send as email_send\n"
        "from .payment import create\n\n"
        "def run() -> None:\n"
        "    pay_send()\n"
        "    email_send()\n"
        "    create()\n",
    )
    _write(
        tmp_path,
        "services/module_caller.py",
        "import services.payment\n\n"
        "def run() -> None:\n"
        "    services.payment.create()\n",
    )

    graph = build_call_graph(tmp_path)
    edges = {(edge.caller_symbol, edge.callee_symbol) for edge in graph.edges}

    assert ("services/caller.py::run", "payments/helpers.py::send") in edges
    assert ("services/caller.py::run", "emails/helpers.py::send") in edges
    assert ("services/caller.py::run", "services/payment.py::create") in edges
    assert ("services/module_caller.py::run", "services/payment.py::create") in edges
    assert len(graph.edges) == 4


def test_shadowing_methods_async_nested_and_cycles(tmp_path: Path) -> None:
    _write(tmp_path, "services/__init__.py", "")
    _write(tmp_path, "services/payment.py", "def create() -> None:\n    pass\n")
    _write(
        tmp_path,
        "analysis.py",
        "from services.payment import create\n\n"
        "def local_assignment() -> None:\n"
        "    create = lambda: None\n"
        "    create()\n\n"
        "def parameter(create) -> None:\n"
        "    create()\n\n"
        "def nested() -> None:\n"
        "    def create() -> None:\n"
        "        pass\n"
        "    create()\n\n"
        "class A:\n"
        "    def save(self) -> None:\n"
        "        pass\n"
        "    def run(self) -> None:\n"
        "        self.save()\n\n"
        "class B:\n"
        "    def save(self) -> None:\n"
        "        pass\n\n"
        "def known() -> None:\n"
        "    service = A()\n"
        "    service.save()\n"
        "    A().save()\n\n"
        "def unknown(obj) -> None:\n"
        "    obj.save()\n\n"
        "async def submit() -> None:\n"
        "    await nested()\n\n"
        "def walk() -> None:\n"
        "    walk()\n\n"
        "def first() -> None:\n"
        "    second()\n\n"
        "def second() -> None:\n"
        "    first()\n",
    )

    graph = build_call_graph(tmp_path)
    edges = {(edge.caller_symbol, edge.callee_symbol) for edge in graph.edges}
    unresolved = {(call.caller_symbol, call.raw_call) for call in graph.unresolved_calls}

    assert ("analysis.py::local_assignment", "services/payment.py::create") not in edges
    assert ("analysis.py::parameter", "services/payment.py::create") not in edges
    assert ("analysis.py::nested", "analysis.py::nested.create") in edges
    assert ("analysis.py::A.run", "analysis.py::A.save") in edges
    assert ("analysis.py::known", "analysis.py::A.save") in edges
    assert ("analysis.py::submit", "analysis.py::nested") in edges
    assert ("analysis.py::walk", "analysis.py::walk") in edges
    assert ("analysis.py::first", "analysis.py::second") in edges
    assert ("analysis.py::second", "analysis.py::first") in edges
    assert any(caller == "analysis.py::unknown" and "obj.save" in raw for caller, raw in unresolved)


def test_graph_is_deterministic_and_exposes_adjacency(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "def helper() -> None:\n    pass\n\ndef caller() -> None:\n    helper()\n",
    )

    first = build_call_graph(tmp_path)
    second = build_call_graph(tmp_path)

    assert first.canonical_json() == second.canonical_json()
    assert [symbol.qualified_name for symbol in first.callees("mod.py::caller")] == [
        "mod.py::helper"
    ]
    assert [symbol.qualified_name for symbol in first.callers("mod.py::helper")] == [
        "mod.py::caller"
    ]
    assert first.coverage.call_expressions_inspected == 1
    assert first.coverage.edges_resolved == 1
