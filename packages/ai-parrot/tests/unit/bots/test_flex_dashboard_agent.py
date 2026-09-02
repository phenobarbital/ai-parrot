"""Unit tests for `agents/flex_dashboard.py` (FEAT-491 TASK-2696)."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Worktree-safe file-path loading, same technique as the other flex tests.
# `agents/flex_dashboard.py` (the agent FILE) and `agents/flex_dashboard/`
# (the sibling PACKAGE for transformers/skills/kb) share the same name —
# Python's FileFinder always resolves a plain `import agents.flex_dashboard`
# to the PACKAGE (verified empirically), matching how production actually
# loads agent files: `parrot.registry.registry.AgentRegistry
# ._load_modules_from_directory` globs `agents/*.py` and loads each one via
# `importlib.util.spec_from_file_location` under a SYNTHETIC module name
# (`parrot.dynamic_agents.dir_<hash>.<stem>`) — never a plain dotted
# `agents.<name>` import. This test mirrors that: the agent file is loaded
# under its OWN distinct synthetic name, never "agents.flex_dashboard" —
# that name is reserved for the real package the agent file's own
# `import agents.flex_dashboard.transformers` statement resolves against.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_AGENTS_DIR = _REPO_ROOT / "agents"
_FLEX_DIR = _AGENTS_DIR / "flex_dashboard"
_AGENT_FILE = _AGENTS_DIR / "flex_dashboard.py"


def _load_package(name: str, init_path: Path, search_dir: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, init_path, submodule_search_locations=[str(search_dir)])
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load package {name!r} from {init_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_flex_dashboard_agent_module():
    # Pre-register the real "agents.flex_dashboard" package chain so the
    # agent file's own `import agents.flex_dashboard.transformers` resolves
    # from THIS worktree deterministically (same defensive chain as
    # test_flex_dashboard_transformers.py).
    _load_package("agents", _AGENTS_DIR / "__init__.py", _AGENTS_DIR)
    _load_package("agents.flex_dashboard", _FLEX_DIR / "__init__.py", _FLEX_DIR)
    _load_module("agents.flex_dashboard.normalize", _FLEX_DIR / "normalize.py")
    _load_module("agents.flex_dashboard.transformers", _FLEX_DIR / "transformers.py")
    # The agent FILE gets its own, distinct synthetic name.
    return _load_module("flex_dashboard_agent_under_test", _AGENT_FILE)


@pytest.fixture(scope="module")
def flex_dashboard_module():
    return _load_flex_dashboard_agent_module()


@pytest.fixture
def flex_agent(flex_dashboard_module):
    """A bare FlexDashboard instance — offline, no network/DB."""
    FlexDashboard = flex_dashboard_module.FlexDashboard
    return FlexDashboard(name="flex-dashboard-test", injection_detection=False)


class TestAgentConstruction:
    def test_instantiates_offline(self, flex_agent):
        assert flex_agent.agent_id == "flex_dashboard"
        assert flex_agent._dataset_manager is not None

    def test_output_routing_enabled(self, flex_agent):
        assert flex_agent._output_routing_enabled is True

    def test_use_kb_enabled(self, flex_agent):
        assert flex_agent.use_kb is True
        assert flex_agent.kb_store is not None

    def test_working_memory_and_infographic_toolkits_attached(self, flex_agent, flex_dashboard_module):
        from parrot.tools.infographic_toolkit import InfographicToolkit
        from parrot.tools.working_memory import WorkingMemoryToolkit

        # ToolManager stores per-method `ToolkitTool` wrappers, not the
        # toolkit instances themselves — recover the parent toolkit via
        # `bound_method.__self__` (same technique
        # `ToolManager.cleanup_toolkits` uses, manager.py:2183-2184).
        parents = {
            getattr(getattr(t, "bound_method", None), "__self__", None) for t in flex_agent.tool_manager.tools.values()
        }
        assert any(isinstance(p, WorkingMemoryToolkit) for p in parents)
        assert any(isinstance(p, InfographicToolkit) for p in parents)

    def test_mixin_order(self, flex_dashboard_module):
        from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin

        FlexDashboard = flex_dashboard_module.FlexDashboard
        mro = FlexDashboard.__mro__
        assert mro.index(NarrativeMixin) < mro.index(InfographicAuthoringMixin)

    def test_skill_paths_anchored_to_file(self, flex_dashboard_module):
        FlexDashboard = flex_dashboard_module.FlexDashboard
        assert FlexDashboard.skill_paths == [flex_dashboard_module.SKILLS_DIR]
        assert flex_dashboard_module.SKILLS_DIR.is_absolute()


class TestAgentDatasets:
    @pytest.mark.asyncio
    async def test_agent_datasets(self, flex_agent, flex_dashboard_module):
        await flex_agent.register_datasets()

        expected = flex_dashboard_module.DATASET_SLUGS
        assert set(expected) == {
            "msl",
            "finance",
            "hours",
            "employees",
            "region_utilization",
            "rep_utilization",
        }

        for alias, slug in expected.items():
            entry = flex_agent._dataset_manager.get_dataset_entry(alias)
            assert entry is not None, f"missing dataset entry for alias {alias!r}"
            assert entry.query_slug == slug, f"alias {alias!r} slug mismatch"

    @pytest.mark.asyncio
    async def test_finance_slug_capitalization_preserved(self, flex_agent):
        await flex_agent.register_datasets()
        entry = flex_agent._dataset_manager.get_dataset_entry("finance")
        assert entry.query_slug == "Finance_results_bi"

    @pytest.mark.asyncio
    async def test_register_datasets_does_not_fetch(self, flex_agent):
        """add_query is lazy — no DataFrame is loaded at registration."""
        await flex_agent.register_datasets()
        for alias in ("msl", "finance", "hours", "employees", "region_utilization", "rep_utilization"):
            entry = flex_agent._dataset_manager.get_dataset_entry(alias)
            assert entry.df is None


class TestKbDocsLoaded:
    @pytest.mark.asyncio
    async def test_kb_docs_loaded(self, flex_agent):
        flex_agent.kb_store.add_facts = AsyncMock()

        await flex_agent._load_kb_docs()

        flex_agent.kb_store.add_facts.assert_awaited_once()
        facts = flex_agent.kb_store.add_facts.call_args.args[0]
        assert len(facts) == 5  # one per agents/flex_dashboard/kb/*.md

        kpis = {f["metadata"]["kpi"] for f in facts}
        assert kpis == {
            "payroll_contribution",
            "pay_code_allocation",
            "rep_utilization",
            "proximity_staffing",
            "datasets",
        }
        for fact in facts:
            assert fact["metadata"]["category"] == "kpi"
            assert fact["content"]  # non-empty markdown text

    @pytest.mark.asyncio
    async def test_load_kb_docs_noop_without_kb_store(self, flex_agent):
        # use_kb=True is hardcoded by design (spec §3 Module 3); simulate the
        # defensive branch directly rather than fighting the agent's own
        # forced kwarg.
        flex_agent.kb_store = None
        # Should not raise even though kb_store is None.
        await flex_agent._load_kb_docs()
