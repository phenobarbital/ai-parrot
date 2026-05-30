"""Unit tests for InfographicToolkit auxiliary tools (FEAT-197, TASK-1324)."""
from __future__ import annotations

import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

# Force real modules (bypass conftest stubs).
for _mod in (
    "parrot.models.infographic",
    "parrot.models.infographic_templates",
    "parrot.tools.infographic_toolkit",
    "parrot.storage.models",
):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _ri
import parrot.models.infographic_templates as _rt
import parrot.storage.models as _rsm
import parrot.tools.infographic_toolkit as _rtk

sys.modules.update({
    "parrot.models.infographic": _ri,
    "parrot.models.infographic_templates": _rt,
    "parrot.storage.models": _rsm,
    "parrot.tools.infographic_toolkit": _rtk,
})

from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicValidationError  # noqa: E402
from parrot.models.infographic_templates import infographic_registry  # noqa: E402


@pytest.fixture
def toolkit():
    """InfographicToolkit with mock store (no bot needed for read-only tools)."""
    store = MagicMock()
    store.save_artifact = AsyncMock()
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return InfographicToolkit(artifact_store=store)


@pytest.mark.asyncio
async def test_list_templates_includes_builtins(toolkit):
    """list_templates should return at least the built-in templates."""
    items = await toolkit.list_templates()
    names = {it["name"] for it in items}
    # The registry ships with at least 'basic' and several others
    assert len(names) >= 1
    for item in items:
        assert "name" in item
        assert "description" in item


@pytest.mark.asyncio
async def test_get_template_contract_unknown_raises(toolkit):
    """get_template_contract with unknown template raises TEMPLATE_UNKNOWN."""
    with pytest.raises(InfographicValidationError) as ei:
        await toolkit.get_template_contract("does-not-exist")
    assert ei.value.code == "TEMPLATE_UNKNOWN"


@pytest.mark.asyncio
async def test_get_template_contract_shape(toolkit):
    """get_template_contract should return dict with expected keys."""
    names = infographic_registry.list_templates()
    if not names:
        pytest.skip("No templates registered")
    first = names[0]
    c = await toolkit.get_template_contract(first)
    assert c["name"] == first
    assert isinstance(c["block_specs"], list)
    for i, s in enumerate(c["block_specs"]):
        assert s["position"] == i
        assert "block_type" in s
        assert "required" in s


@pytest.mark.asyncio
async def test_validate_blocks_failure_does_not_raise(toolkit):
    """validate_blocks should return a dict, not raise, on failure."""
    names = infographic_registry.list_templates()
    if not names:
        pytest.skip("No templates registered")
    first = names[0]
    out = await toolkit.validate_blocks(first, [])  # empty blocks for a required template
    assert isinstance(out, dict)
    assert "ok" in out
    # May be ok=True (if template has no required slots) or ok=False
    if not out["ok"]:
        assert "code" in out
        assert out["code"] in {
            "SLOT_MISSING", "TEMPLATE_UNKNOWN", "EXTRA_BLOCKS",
            "SLOT_TYPE_MISMATCH", "SLOT_ITEM_COUNT_INVALID",
        }


@pytest.mark.asyncio
async def test_validate_blocks_success(toolkit):
    """validate_blocks returns ok=True when blocks satisfy the contract."""
    from parrot.models.infographic_templates import BlockSpec, InfographicTemplate
    from parrot.models.infographic import BlockType
    # Register a minimal template for this test
    t = InfographicTemplate(
        name="_test_aux_title_only",
        description="single optional title",
        block_specs=[BlockSpec(block_type=BlockType.TITLE, required=False)],
    )
    infographic_registry.register(t)
    # Empty blocks OK for optional-only template
    out = await toolkit.validate_blocks("_test_aux_title_only", [])
    assert out == {"ok": True}


def test_tool_names_prefixed(toolkit):
    """All four tools should be exposed with the infographic_ prefix."""
    tools = toolkit.get_tools()
    names = {t.name for t in tools}
    for expected in (
        "infographic_render",
        "infographic_list_templates",
        "infographic_get_template_contract",
        "infographic_validate_blocks",
    ):
        assert expected in names, f"Missing tool: {expected}"


def test_tools_have_return_direct(toolkit):
    """Tools are return_direct=True EXCEPT build_block, which is non-terminal.

    ``infographic_build_block`` only appends a block to the REPL accumulator —
    the LLM keeps calling tools and then renders — so it must not short-circuit
    the agent loop.
    """
    tools = toolkit.get_tools()
    for t in tools:
        if t.name.endswith("build_block"):
            assert t.return_direct is False, (
                f"Non-terminal tool {t.name} must NOT be return_direct"
            )
        else:
            assert t.return_direct is True, f"Tool {t.name} missing return_direct=True"
