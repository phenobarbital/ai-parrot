"""
Unit tests for the deterministic tab-assembly helper (FEAT-308).

TASK-1777: Deterministic Tab-Assembly Helper

NOTE (Codebase Contract correction): the task's pseudo-code used
``block["block_type"]`` as the discriminator key and a ``"text"`` block
type. Verified against ``parrot/models/infographic.py`` and
``InfographicToolkit._validate_blocks`` (``block_raw.get("type")``,
infographic_toolkit.py:981), the real block schema discriminates on
``"type"`` (not ``"block_type"``), there is no ``"text"`` BlockType (the
closest prose block is ``SummaryBlock``, ``type="summary"``), ``TitleBlock``
uses a ``title`` field (not ``content``), and ``TabPane`` requires an ``id``.
Tests below assert against the corrected, verified shape.
"""
from unittest.mock import MagicMock

from parrot.bots.flows.core.result import NodeResult
from parrot.bots.flows.crew.result_infographic import (
    build_deterministic_tabs,
    merge_tab1_blocks,
)


def _make_node_result(node_id, name, result_text):
    return NodeResult(
        node_id=node_id, node_name=name, task="test",
        result=result_text, metadata={},
    )


class TestBuildDeterministicTabs:
    def test_single_result_one_tab(self):
        """0 research agents -> only Final Result tab."""
        mem = MagicMock()
        mem.results = {}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["type"] == "tab_view")
        assert len(tab_view["tabs"]) == 1  # just Final Result

    def test_many_agents_no_clamp(self):
        """8 research agents -> 9 tabs (Final Result + 8 agent tabs)."""
        mem = MagicMock()
        mem.results = {
            f"agent-{i}": _make_node_result(f"agent-{i}", f"Agent {i}", f"Result {i}")
            for i in range(8)
        }
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["type"] == "tab_view")
        assert len(tab_view["tabs"]) == 9

    def test_excludes_result_agent(self):
        """The ResultAgent's node_id is absent from per-agent tabs."""
        mem = MagicMock()
        mem.results = {
            "researcher": _make_node_result("researcher", "Researcher", "data"),
            "result-agent": _make_node_result("result-agent", "ResultAgent", "infographic"),
        }
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["type"] == "tab_view")
        tab_labels = [t["label"] for t in tab_view["tabs"]]
        assert "ResultAgent" not in tab_labels
        assert "Researcher" in tab_labels or "Final Result" in tab_labels

    def test_large_result_linked_out(self):
        """Oversized result is summarized, not dumped raw."""
        mem = MagicMock()
        huge = "x" * 60_000
        mem.results = {"agent-1": _make_node_result("agent-1", "Agent 1", huge)}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["type"] == "tab_view")
        agent_tab = next(t for t in tab_view["tabs"] if t["label"] != "Final Result")
        content = str(agent_tab["blocks"])
        assert len(content) < 60_000

    def test_content_fits_summary_block_max_length(self):
        """All tab content blocks respect SummaryBlock's max_length=2000."""
        mem = MagicMock()
        huge = "y" * 100_000
        mem.results = {"agent-1": _make_node_result("agent-1", "Agent 1", huge)}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id=None)
        tab_view = next(b for b in blocks if b["type"] == "tab_view")
        for tab in tab_view["tabs"]:
            for block in tab["blocks"]:
                assert len(block["content"]) <= 2000

    def test_tabs_have_required_id_and_label(self):
        """Each tab dict has the id/label fields TabPane requires."""
        mem = MagicMock()
        mem.results = {"researcher": _make_node_result("researcher", "Researcher", "data")}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id=None)
        tab_view = next(b for b in blocks if b["type"] == "tab_view")
        for tab in tab_view["tabs"]:
            assert "id" in tab and tab["id"]
            assert "label" in tab and tab["label"]

    def test_title_block_uses_title_field(self):
        """Title block uses the verified `title` field (not `content`)."""
        mem = MagicMock()
        mem.results = {}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id=None)
        title_block = next(b for b in blocks if b["type"] == "title")
        assert "title" in title_block
        assert title_block["title"]

    def test_artifact_store_used_for_large_result(self):
        """When an artifact_store is supplied, large results link out via publish()."""
        mem = MagicMock()
        huge = "z" * 60_000
        mem.results = {"agent-1": _make_node_result("agent-1", "Agent 1", huge)}
        store = MagicMock()
        store.publish.return_value = "https://artifacts.example.com/agent-1.txt"
        blocks = build_deterministic_tabs(
            mem, final_output="Done", exclude_node_id=None, artifact_store=store,
        )
        tab_view = next(b for b in blocks if b["type"] == "tab_view")
        agent_tab = next(t for t in tab_view["tabs"] if t["label"] != "Final Result")
        content = agent_tab["blocks"][0]["content"]
        assert "https://artifacts.example.com/agent-1.txt" in content
        store.publish.assert_called_once()


class TestMergeTab1Blocks:
    def test_inserts_tab1_first(self):
        """Tab 1 (Exec Summary) is the first tab after merge."""
        tab1 = [{"type": "summary", "content": "Executive Summary"}]
        det_blocks = [
            {"type": "title", "title": "Report"},
            {
                "type": "tab_view",
                "tabs": [
                    {
                        "id": "final-result",
                        "label": "Final Result",
                        "blocks": [{"type": "summary", "content": "Done"}],
                    },
                ],
            },
        ]
        merged = merge_tab1_blocks(tab1, det_blocks)
        tab_view = next(b for b in merged if b["type"] == "tab_view")
        assert tab_view["tabs"][0]["label"] == "Executive Summary"
        assert len(tab_view["tabs"]) == 2

    def test_does_not_mutate_input(self):
        """merge_tab1_blocks does not mutate the deterministic_blocks input."""
        tab1 = [{"type": "summary", "content": "Executive Summary"}]
        det_blocks = [
            {"type": "title", "title": "Report"},
            {"type": "tab_view", "tabs": [{"id": "final-result", "label": "Final Result", "blocks": []}]},
        ]
        merge_tab1_blocks(tab1, det_blocks)
        tab_view = next(b for b in det_blocks if b["type"] == "tab_view")
        assert len(tab_view["tabs"]) == 1
