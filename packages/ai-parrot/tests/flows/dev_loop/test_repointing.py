"""Import repointing tests for parrot/flows/dev_loop/ (TASK-1313).

Verifies that all 8 dev_loop files have been updated to use canonical
parrot.bots.flows.* import paths instead of legacy parrot.bots.flow.* paths.
"""
import inspect
import pathlib


def _src(module_or_path) -> str:
    """Return source text for a module or path."""
    if isinstance(module_or_path, (str, pathlib.Path)):
        return pathlib.Path(module_or_path).read_text()
    return pathlib.Path(inspect.getfile(module_or_path)).read_text()


def test_devloop_flow_imports_canonical_agentsflow():
    """dev_loop/flow.py uses parrot.bots.flows (plural) for AgentsFlow."""
    import parrot.flows.dev_loop.flow as _mod  # noqa: PLC0415

    src = _src(_mod)
    assert "parrot.bots.flow import AgentsFlow" not in src, (
        "Legacy 'parrot.bots.flow' AgentsFlow import found in dev_loop/flow.py"
    )
    assert "parrot.bots.flows" in src


def test_devloop_nodes_no_legacy_node_import():
    """All dev_loop node files use parrot.bots.flows.core.node (plural)."""
    nodes_dir = pathlib.Path(
        inspect.getfile(__import__("parrot.flows.dev_loop", fromlist=["dev_loop"]))
    ).parent / "nodes"

    legacy_pattern = "parrot.bots.flow.node"
    for py_file in sorted(nodes_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        src = py_file.read_text()
        assert legacy_pattern not in src, (
            f"Legacy import '{legacy_pattern}' found in {py_file.name}"
        )


def test_devloop_bug_intake_uses_canonical_node():
    """bug_intake.py builds on DevLoopNode (canonical parrot.bots.flows core)."""
    import parrot.flows.dev_loop.nodes.bug_intake as _mod  # noqa: PLC0415

    src = _src(_mod)
    assert "parrot.flows.dev_loop.nodes.base import DevLoopNode" in src


def test_devloop_development_uses_canonical_node():
    """development.py builds on DevLoopNode (canonical parrot.bots.flows core)."""
    import parrot.flows.dev_loop.nodes.development as _mod  # noqa: PLC0415

    src = _src(_mod)
    assert "parrot.flows.dev_loop.nodes.base import DevLoopNode" in src


def test_devloop_qa_uses_canonical_node():
    """qa.py builds on DevLoopNode (canonical parrot.bots.flows core)."""
    import parrot.flows.dev_loop.nodes.qa as _mod  # noqa: PLC0415

    src = _src(_mod)
    assert "parrot.flows.dev_loop.nodes.base import DevLoopNode" in src


def test_devloop_research_uses_canonical_node():
    """research.py builds on DevLoopNode (canonical parrot.bots.flows core)."""
    import parrot.flows.dev_loop.nodes.research as _mod  # noqa: PLC0415

    src = _src(_mod)
    assert "parrot.flows.dev_loop.nodes.base import DevLoopNode" in src
