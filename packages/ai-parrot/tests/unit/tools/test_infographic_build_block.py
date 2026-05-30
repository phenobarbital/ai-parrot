"""Unit tests for InfographicToolkit.build_block + prompt injection (FEAT-197).

``build_block`` lets the LLM assemble chart/table blocks from DataFrames already
in the pandas REPL (instead of hand-writing large block JSON), appending each
validated block to an accumulator list variable. ``set_bot`` also injects the
infographic usage guide into the bot's system prompt so the capability works
ad-hoc, with no per-report skill.
"""
from __future__ import annotations

import sys

import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock

# Force real infographic modules (bypass conftest stubs).
for _mod in (
    "parrot.models.infographic",
    "parrot.models.infographic_templates",
    "parrot.tools.infographic_toolkit",
    "parrot.storage.models",
):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _ri  # noqa: E402
import parrot.models.infographic_templates as _rt  # noqa: E402
import parrot.storage.models as _rsm  # noqa: E402

sys.modules["parrot.models.infographic"] = _ri
sys.modules["parrot.models.infographic_templates"] = _rt
sys.modules["parrot.storage.models"] = _rsm

import parrot.tools.infographic_toolkit as _rtk  # noqa: E402
sys.modules["parrot.tools.infographic_toolkit"] = _rtk

from parrot.tools.infographic_toolkit import InfographicToolkit  # noqa: E402
# Capture these at module load (collection time) so they reference the SAME
# registry/module objects the toolkit (_rtk) bound to — later test files pop &
# re-import these modules, so a late in-function import would resolve to a
# different registry instance and templates we register would be invisible.
from parrot.models.infographic import BlockType  # noqa: E402
from parrot.models.infographic_templates import (  # noqa: E402
    BlockSpec,
    InfographicTemplate,
    infographic_registry,
)


@pytest.fixture
def repl():
    """A live REPL locals dict the toolkit reads from and writes into."""
    return {
        "rev": pd.DataFrame(
            {
                "date": ["D1", "D2", "D3"],
                "rev_dod": [10, 20, 30],
                "ebitda": [1.5, 2.5, 3.5],
            }
        )
    }


@pytest.fixture
def toolkit(repl):
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    tk = InfographicToolkit(artifact_store=store)
    bot = MagicMock()
    bot._get_repl_locals = MagicMock(return_value=repl)
    bot._current_user_id = None
    bot._current_agent_id = None
    bot._current_session_id = None
    bot.user_id, bot.agent_id, bot.session_id = "u", "a", "s"
    bot.system_prompt_template = "BASE PROMPT."
    tk._bot = bot
    return tk


# ---------------------------------------------------------------------------
# build_block — chart
# ---------------------------------------------------------------------------

class TestBuildChart:
    @pytest.mark.asyncio
    async def test_chart_from_dataframe(self, toolkit, repl):
        r = await toolkit.build_block(
            block_type="chart", data_variable="rev", chart_type="bar",
            label_column="date", value_columns=["rev_dod", "ebitda"],
            title="Rev", layout="half",
        )
        assert r["ok"] is True
        assert r["index"] == 0 and r["n_blocks"] == 1
        block = repl["infographic_blocks"][0]
        assert block["type"] == "chart"
        assert block["chart_type"] == "bar"
        assert block["labels"] == ["D1", "D2", "D3"]
        names = [s["name"] for s in block["series"]]
        assert names == ["rev_dod", "ebitda"]
        assert block["series"][0]["values"] == [10, 20, 30]
        assert block["layout"] == "half"

    @pytest.mark.asyncio
    async def test_chart_missing_chart_type(self, toolkit):
        r = await toolkit.build_block(
            block_type="chart", data_variable="rev",
            label_column="date", value_columns=["rev_dod"],
        )
        assert r["ok"] is False
        assert r["code"] == "BLOCK_CHART_INCOMPLETE"

    @pytest.mark.asyncio
    async def test_chart_bad_column(self, toolkit):
        r = await toolkit.build_block(
            block_type="chart", data_variable="rev", chart_type="bar",
            label_column="nope", value_columns=["rev_dod"],
        )
        assert r["ok"] is False
        assert r["code"] == "BLOCK_COLUMN_MISSING"
        assert "nope" in r["detail"]["missing"]

    @pytest.mark.asyncio
    async def test_chart_max_rows_caps(self, toolkit, repl):
        await toolkit.build_block(
            block_type="chart", data_variable="rev", chart_type="line",
            label_column="date", value_columns=["rev_dod"], max_rows=2,
        )
        assert repl["infographic_blocks"][0]["labels"] == ["D1", "D2"]


# ---------------------------------------------------------------------------
# build_block — table
# ---------------------------------------------------------------------------

class TestBuildTable:
    @pytest.mark.asyncio
    async def test_table_from_dataframe(self, toolkit, repl):
        r = await toolkit.build_block(
            block_type="table", data_variable="rev",
            table_columns=["date", "rev_dod"], title="T",
        )
        assert r["ok"] is True
        block = repl["infographic_blocks"][0]
        assert block["type"] == "table"
        assert block["columns"] == ["date", "rev_dod"]
        assert block["rows"] == [["D1", 10], ["D2", 20], ["D3", 30]]

    @pytest.mark.asyncio
    async def test_table_defaults_to_all_columns(self, toolkit, repl):
        await toolkit.build_block(block_type="table", data_variable="rev")
        assert repl["infographic_blocks"][0]["columns"] == ["date", "rev_dod", "ebitda"]

    @pytest.mark.asyncio
    async def test_table_missing_data_variable(self, toolkit):
        r = await toolkit.build_block(block_type="table", data_variable="ghost")
        assert r["ok"] is False
        assert r["code"] == "BLOCK_DATA_VAR_MISSING"


# ---------------------------------------------------------------------------
# build_block — literal + accumulator semantics
# ---------------------------------------------------------------------------

class TestBuildLiteralAndAccumulator:
    @pytest.mark.asyncio
    async def test_literal_block(self, toolkit, repl):
        r = await toolkit.build_block(
            block_type="hero_card",
            block={"type": "hero_card", "label": "Total", "value": "$60"},
        )
        assert r["ok"] is True
        assert repl["infographic_blocks"][0]["label"] == "Total"

    @pytest.mark.asyncio
    async def test_literal_requires_block(self, toolkit):
        r = await toolkit.build_block(block_type="summary")
        assert r["ok"] is False
        assert r["code"] == "BLOCK_LITERAL_MISSING"

    @pytest.mark.asyncio
    async def test_blocks_appended_in_call_order(self, toolkit, repl):
        await toolkit.build_block(
            block_type="title",
            block={"type": "title", "title": "Report"},
        )
        await toolkit.build_block(
            block_type="chart", data_variable="rev", chart_type="bar",
            label_column="date", value_columns=["rev_dod"],
        )
        await toolkit.build_block(
            block_type="table", data_variable="rev",
        )
        assert [b["type"] for b in repl["infographic_blocks"]] == [
            "title", "chart", "table",
        ]

    @pytest.mark.asyncio
    async def test_custom_accumulator_name(self, toolkit, repl):
        await toolkit.build_block(
            block_type="title", into="fp_blocks",
            block={"type": "title", "title": "R"},
        )
        assert "fp_blocks" in repl and len(repl["fp_blocks"]) == 1

    @pytest.mark.asyncio
    async def test_accumulator_wrong_type(self, toolkit, repl):
        repl["infographic_blocks"] = "not-a-list"
        r = await toolkit.build_block(
            block_type="title", block={"type": "title", "title": "R"},
        )
        assert r["ok"] is False
        assert r["code"] == "BLOCK_ACCUMULATOR_INVALID"

    @pytest.mark.asyncio
    async def test_built_blocks_feed_render(self, toolkit):
        """Blocks built into the accumulator render via blocks_variable."""
        tmpl = InfographicTemplate(
            name="_bb_render_test", description="d",
            block_specs=[BlockSpec(
                block_type=BlockType.CHART, min_items=1, max_items=1, required=True,
            )],
        )
        infographic_registry.register(tmpl)
        await toolkit.build_block(
            block_type="chart", data_variable="rev", chart_type="line",
            label_column="date", value_columns=["rev_dod"],
        )
        result = await toolkit.render(
            template_name="_bb_render_test", theme="light", mode="deterministic",
            blocks_variable="infographic_blocks", data_variables=["rev"],
        )
        assert result.artifact_id


# ---------------------------------------------------------------------------
# Prompt injection via set_bot
# ---------------------------------------------------------------------------

class TestPromptInjection:
    def test_set_bot_injects_guidance(self):
        tk = InfographicToolkit(artifact_store=MagicMock())
        bot = MagicMock()
        bot.system_prompt_template = "BASE."
        tk.set_bot(bot)
        assert "## Infographic Generation Mode" in bot.system_prompt_template
        assert "infographic_build_block" in bot.system_prompt_template

    def test_injection_is_idempotent(self):
        tk = InfographicToolkit(artifact_store=MagicMock())
        bot = MagicMock()
        bot.system_prompt_template = "BASE."
        tk.set_bot(bot)
        tk.set_bot(bot)
        assert bot.system_prompt_template.count("## Infographic Generation Mode") == 1

    def test_no_prompt_attr_is_noop(self):
        tk = InfographicToolkit(artifact_store=MagicMock())
        bot = MagicMock()
        bot.system_prompt_template = 12345  # not a string
        tk.set_bot(bot)  # must not raise
        assert tk._bot is bot
