"""Unit tests for agents/oddie.py — OdooAgent (FEAT-240 TASK-1574).

Tests verify:
- Model resolves to "gemini-3.5-flash" via GoogleModel enum.
- Registry resolves "odoo_agent" to OdooAgent.
- OdooToolkit is constructed from ODOO_TEST_* env vars.
- agent_tools() returns both odoo_* and pageindex_* tools (or at least odoo_*).
- WorkingMemoryToolkit registered in configure().
- ConfirmationGuard attached after configure().
- UserInfo KB registered and always_active.
- Skill discovery path is set to agents/odoo_agent/skills/.

Module loading strategy:
    We add the worktree's ``agents/`` directory to sys.path and import
    ``oddie`` as a top-level module.  This avoids the ``parrot.agents``
    plugin importer (which targets the main repo's ``plugins/`` dir) and
    lets ``oddie.py`` import ``parrot.*`` modules from whatever source is
    already on sys.path (the main repo's compiled packages).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.models.google import GoogleModel

# ── Resolve paths ─────────────────────────────────────────────────────────────

# test file is at: <worktree_root>/packages/ai-parrot/tests/test_odoo_agent.py
# worktree_root = 4 parents up
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_AGENTS_DIR = _WORKTREE_ROOT / "agents"
_ODDIE_PATH = _AGENTS_DIR / "oddie.py"

# Stable module name for the loaded oddie module.
_MOD_NAME = "oddie"


# ── Module loader ─────────────────────────────────────────────────────────────


def _ensure_parrot_utils_stubs() -> None:
    """Ensure all Cython-dependent ``parrot.utils.*`` sub-modules are importable.

    The worktree's ``packages/ai-parrot/src`` is first on sys.path (added by
    ``packages/ai-parrot/conftest.py``).  Several modules under
    ``parrot/utils/`` are Cython (``.pyx``) or depend on ``.pyx`` modules,
    which are not compiled in the worktree.  We install lightweight stubs for
    all sub-modules that are known to fail in this environment.
    """
    import types as _t

    # parrot.utils.types (Cython .pyx → .so missing in worktree)
    if "parrot.utils.types" not in sys.modules:
        stub = _t.ModuleType("parrot.utils.types")
        class SafeDict(dict):
            """Stub."""
        stub.SafeDict = SafeDict
        sys.modules["parrot.utils.types"] = stub

    # parrot.utils.parsers.toml (references Cython-based toml parser)
    if "parrot.utils.parsers" not in sys.modules:
        p = _t.ModuleType("parrot.utils.parsers")
        p.__path__ = []
        sys.modules["parrot.utils.parsers"] = p

    if "parrot.utils.parsers.toml" not in sys.modules:
        pt = _t.ModuleType("parrot.utils.parsers.toml")
        _TOMLParser = type("TOMLParser", (), {
            "__init__": lambda self, *a, **kw: None,
            "parse": lambda self, *a, **kw: {},
        })
        pt.TOMLParser = _TOMLParser
        sys.modules["parrot.utils.parsers.toml"] = pt

    # Make sure parrot.utils.parsers.__init__ has TOMLParser exposed
    p = sys.modules["parrot.utils.parsers"]
    if not hasattr(p, "TOMLParser"):
        p.TOMLParser = sys.modules["parrot.utils.parsers.toml"].TOMLParser


def _load_oddie_module() -> Any:
    """Load agents/oddie.py as module ``oddie`` on sys.path.

    Adds ``agents/`` to sys.path so that ``oddie.py`` can be imported as
    the module ``oddie``.  Also installs a ``parrot.utils.types`` stub so
    the full ``parrot.bots`` / ``parrot.stores.kb`` import chains succeed in
    the worktree test environment (which lacks the compiled Cython ``.so``).

    Returns:
        The loaded module.
    """
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]

    if not _ODDIE_PATH.is_file():
        raise FileNotFoundError(f"agents/oddie.py not found at {_ODDIE_PATH}")

    # Stub parrot.utils.* BEFORE importing anything from parrot.*
    _ensure_parrot_utils_stubs()

    # The conftest installs a minimal stub for parrot.bots.agent (its _ToolManager
    # lacks register_toolkit, set_confirmation_guard, get_tools).  Remove the stubs
    # so the REAL parrot.bots modules load from the compiled packages on sys.path.
    for _key in list(sys.modules):
        if _key in ("parrot.bots", "parrot.bots.agent", "parrot.bots.abstract",
                    "parrot.bots.base"):
            del sys.modules[_key]

    # Ensure agents/ is on sys.path for `import oddie`
    agents_dir = str(_AGENTS_DIR)
    if agents_dir not in sys.path:
        sys.path.insert(0, agents_dir)

    import importlib as _il
    mod = _il.import_module("oddie")
    return mod


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def oddie_module() -> Any:
    """Load agents/oddie.py once per test module.

    Returns:
        The loaded ``oddie`` module.
    """
    return _load_oddie_module()


@pytest.fixture(autouse=True)
def odoo_test_env(monkeypatch: Any) -> None:
    """Inject ODOO_TEST_* env vars for all tests in this module."""
    monkeypatch.setenv("ODOO_TEST_URL", "http://prozac:8069")
    monkeypatch.setenv("ODOO_TEST_DATABASE", "odoo")
    monkeypatch.setenv("ODOO_TEST_USERNAME", "admin")
    monkeypatch.setenv("ODOO_TEST_PASSWORD", "admin")


# ── Skill file frontmatter ────────────────────────────────────────────────────


def test_install_module_skill_frontmatter() -> None:
    """install-odoo-module/SKILL.md must have valid frontmatter with name and description."""
    import yaml

    p = _AGENTS_DIR / "odoo_agent" / "skills" / "install-odoo-module" / "SKILL.md"
    assert p.is_file(), f"SKILL.md not found at {p}"
    text = p.read_text()
    assert text.startswith("---"), f"SKILL.md does not start with '---': {text[:50]!r}"
    fm = yaml.safe_load(text.split("---")[1])
    assert "name" in fm, f"Missing 'name' in frontmatter: {fm}"
    assert "description" in fm, f"Missing 'description' in frontmatter: {fm}"


def test_structured_response_skill_frontmatter() -> None:
    """structured-operation-response/SKILL.md must have valid frontmatter."""
    import yaml

    p = (
        _AGENTS_DIR
        / "odoo_agent"
        / "skills"
        / "structured-operation-response"
        / "SKILL.md"
    )
    assert p.is_file(), f"SKILL.md not found at {p}"
    text = p.read_text()
    assert text.startswith("---"), f"SKILL.md does not start with '---': {text[:50]!r}"
    fm = yaml.safe_load(text.split("---")[1])
    assert "name" in fm, f"Missing 'name' in frontmatter: {fm}"
    assert "description" in fm, f"Missing 'description' in frontmatter: {fm}"


# ── Model resolution ──────────────────────────────────────────────────────────


def test_model_is_gemini_3_5_flash(oddie_module: Any) -> None:
    """OdooAgent.model must resolve to the string 'gemini-3.5-flash'."""
    OdooAgent = oddie_module.OdooAgent

    model_val = getattr(OdooAgent.model, "value", OdooAgent.model)
    assert model_val == "gemini-3.5-flash", (
        f"Expected 'gemini-3.5-flash', got {model_val!r}"
    )


def test_model_is_gemini_enum_member(oddie_module: Any) -> None:
    """OdooAgent.model must be the GoogleModel.GEMINI_3_5_FLASH enum member."""
    OdooAgent = oddie_module.OdooAgent

    assert OdooAgent.model == GoogleModel.GEMINI_3_5_FLASH


# ── Registry ──────────────────────────────────────────────────────────────────


def test_agent_registered(oddie_module: Any) -> None:
    """@register_agent(name='odoo_agent') must be resolvable from the registry."""
    from parrot.registry import agent_registry

    # Loading oddie_module already triggered @register_agent
    assert agent_registry.has("odoo_agent"), (
        "OdooAgent was not registered under 'odoo_agent'"
    )


# ── Tool construction ─────────────────────────────────────────────────────────


def test_agent_tools_include_odoo_tools(oddie_module: Any) -> None:
    """agent_tools() must include at least odoo_search_records."""
    OdooAgent = oddie_module.OdooAgent

    with patch.object(oddie_module, "PageIndexToolkit") as mock_pi_cls, \
         patch.object(oddie_module, "GoogleGenAIClient"), \
         patch.object(oddie_module, "PageIndexLLMAdapter"):
        mock_pi = MagicMock()
        mock_pi.get_tools.return_value = []
        mock_pi_cls.return_value = mock_pi

        agent = OdooAgent(name="OdooAgent")
        tools = agent.agent_tools()

    tool_names = {t.name for t in tools}
    assert any("odoo" in name for name in tool_names), (
        f"No odoo_* tools found in agent_tools(): {tool_names}"
    )
    assert "odoo_search_records" in tool_names


def test_odoo_toolkit_uses_test_env(oddie_module: Any) -> None:
    """OdooToolkit must be constructed from ODOO_TEST_* env vars."""
    OdooAgent = oddie_module.OdooAgent

    with patch.object(oddie_module, "OdooToolkit") as mock_tk_cls, \
         patch.object(oddie_module, "PageIndexToolkit") as mock_pi_cls, \
         patch.object(oddie_module, "GoogleGenAIClient"), \
         patch.object(oddie_module, "PageIndexLLMAdapter"):
        mock_tk = MagicMock()
        mock_tk.get_tools.return_value = []
        mock_tk_cls.return_value = mock_tk

        mock_pi = MagicMock()
        mock_pi.get_tools.return_value = []
        mock_pi_cls.return_value = mock_pi

        agent = OdooAgent(name="OdooAgent")
        agent.agent_tools()

    call_kwargs = mock_tk_cls.call_args.kwargs
    assert call_kwargs.get("url") == "http://prozac:8069"
    assert call_kwargs.get("database") == "odoo"
    assert call_kwargs.get("username") == "admin"
    assert call_kwargs.get("verify_ssl") is False


# ── configure() — WorkingMemory + HITL + UserInfo ────────────────────────────


@pytest.mark.asyncio
async def test_working_memory_registered_after_configure(oddie_module: Any) -> None:
    """WorkingMemoryToolkit must be registered in configure()."""
    OdooAgent = oddie_module.OdooAgent

    with patch.object(oddie_module, "PageIndexToolkit") as mock_pi_cls, \
         patch.object(oddie_module, "GoogleGenAIClient"), \
         patch.object(oddie_module, "PageIndexLLMAdapter"), \
         patch.object(OdooAgent, "_configure_skill_registry", new_callable=AsyncMock):
        mock_pi = MagicMock()
        mock_pi.get_tools.return_value = []
        mock_pi_cls.return_value = mock_pi

        agent = OdooAgent(name="OdooAgent")
        with patch.object(type(agent).__mro__[2], "configure", new_callable=AsyncMock):
            await agent.configure()

    tool_names = {t.name for t in agent.tool_manager.get_tools()}
    assert any("wm" in name for name in tool_names), (
        f"No wm_* tools found after configure(): {tool_names}"
    )


@pytest.mark.asyncio
async def test_confirmation_guard_attached_after_configure(oddie_module: Any) -> None:
    """tool_manager.confirmation_guard must not be None after configure()."""
    OdooAgent = oddie_module.OdooAgent

    with patch.object(oddie_module, "PageIndexToolkit") as mock_pi_cls, \
         patch.object(oddie_module, "GoogleGenAIClient"), \
         patch.object(oddie_module, "PageIndexLLMAdapter"), \
         patch.object(OdooAgent, "_configure_skill_registry", new_callable=AsyncMock):
        mock_pi = MagicMock()
        mock_pi.get_tools.return_value = []
        mock_pi_cls.return_value = mock_pi

        agent = OdooAgent(name="OdooAgent")
        with patch.object(type(agent).__mro__[2], "configure", new_callable=AsyncMock):
            await agent.configure()

    assert agent.tool_manager.confirmation_guard is not None, (
        "ConfirmationGuard was not attached to tool_manager after configure()"
    )


@pytest.mark.asyncio
async def test_userinfo_kb_registered_after_configure(oddie_module: Any) -> None:
    """UserInfo KB must be registered and always_active after configure()."""
    OdooAgent = oddie_module.OdooAgent

    with patch.object(oddie_module, "PageIndexToolkit") as mock_pi_cls, \
         patch.object(oddie_module, "GoogleGenAIClient"), \
         patch.object(oddie_module, "PageIndexLLMAdapter"), \
         patch.object(OdooAgent, "_configure_skill_registry", new_callable=AsyncMock):
        mock_pi = MagicMock()
        mock_pi.get_tools.return_value = []
        mock_pi_cls.return_value = mock_pi

        from parrot.stores.kb.user import UserInfo

        agent = OdooAgent(name="OdooAgent")
        with patch.object(type(agent).__mro__[2], "configure", new_callable=AsyncMock):
            await agent.configure()

    user_infos = [kb for kb in agent.knowledge_bases if isinstance(kb, UserInfo)]
    assert len(user_infos) >= 1, "UserInfo KB was not registered"
    assert all(kb.always_active for kb in user_infos), (
        "UserInfo KB must have always_active=True"
    )


# ── Skill paths ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_paths_set_to_odoo_agent_skills(oddie_module: Any) -> None:
    """skill_paths must point to agents/odoo_agent/skills/ after configure()."""
    OdooAgent = oddie_module.OdooAgent

    with patch.object(oddie_module, "PageIndexToolkit") as mock_pi_cls, \
         patch.object(oddie_module, "GoogleGenAIClient"), \
         patch.object(oddie_module, "PageIndexLLMAdapter"), \
         patch.object(OdooAgent, "_configure_skill_registry", new_callable=AsyncMock):
        mock_pi = MagicMock()
        mock_pi.get_tools.return_value = []
        mock_pi_cls.return_value = mock_pi

        agent = OdooAgent(name="OdooAgent")
        with patch.object(type(agent).__mro__[2], "configure", new_callable=AsyncMock):
            await agent.configure()

    skill_dirs = getattr(agent, "skill_paths", [])
    assert any("odoo_agent" in str(p) and "skills" in str(p) for p in skill_dirs), (
        f"skill_paths does not point to agents/odoo_agent/skills/: {skill_dirs}"
    )


# ── cleanup() ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_releases_odoo_toolkit(oddie_module: Any) -> None:
    """cleanup() must call OdooToolkit.cleanup() and not raise."""
    OdooAgent = oddie_module.OdooAgent

    with patch.object(oddie_module, "PageIndexToolkit") as mock_pi_cls, \
         patch.object(oddie_module, "GoogleGenAIClient"), \
         patch.object(oddie_module, "PageIndexLLMAdapter"):
        mock_pi = MagicMock()
        mock_pi.get_tools.return_value = []
        mock_pi_cls.return_value = mock_pi

        agent = OdooAgent(name="OdooAgent")
        agent.agent_tools()  # initialises _odoo_toolkit

    mock_odoo_cleanup = AsyncMock()
    agent._odoo_toolkit.cleanup = mock_odoo_cleanup

    with patch.object(type(agent).__mro__[2], "cleanup", new_callable=AsyncMock):
        await agent.cleanup()

    mock_odoo_cleanup.assert_called_once()
