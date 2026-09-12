"""FEAT-555 TASK-3196 — `--base` threading into the dev-flow ideation payload."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput  # verified: dev_flow/models.py:61,166
from parrot.flows.dev_flow.nodes.ideation import IdeationNode, _IdeationBrief  # verified: nodes/ideation.py:101


def _brief(**overrides):
    payload = {"kind": "new_feature", "title": "t", "description": "d"}
    payload.update(overrides)
    return DevRequestBrief(**payload)


def test_defaults_are_none():
    b = _brief()
    assert b.flow_type is None and b.base_branch is None


def test_staging_feature_accepted():
    assert _brief(flow_type="feature", base_branch="staging").base_branch == "staging"


def test_hotfix_requires_main():
    with pytest.raises(ValidationError):
        _brief(flow_type="hotfix", base_branch="dev")


def test_ideation_brief_default_base_branch():
    assert _IdeationBrief(mode="brainstorm", title="t", description="d").base_branch == "dev"


class _ScriptedDispatcher:
    """Minimal scripted dispatcher, mirroring test_ideation_node.py's ScriptedDispatcher."""

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        self.calls.append({"brief": brief})
        return self._outputs.pop(0)


@pytest.mark.asyncio
async def test_ideation_payload_carries_base_branch(tmp_path, monkeypatch):
    from parrot import conf

    proposals = tmp_path / "sdd" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "telemetry.brainstorm.md").write_text("# Brainstorm", encoding="utf-8")
    monkeypatch.setattr(conf, "PROJECT_ROOT", tmp_path, raising=False)

    output = IdeationOutput(
        document_path="sdd/proposals/telemetry.brainstorm.md",
        document_kind="brainstorm",
        slug="telemetry",
        committed=True,
    )
    dispatcher = _ScriptedDispatcher([output])
    node = IdeationNode(dispatcher=dispatcher)
    brief = _brief(flow_type="feature", base_branch="staging")

    await node.execute({"run_id": "run-basebranch01", "dev_brief": brief})

    assert dispatcher.calls[0]["brief"].base_branch == "staging"


def test_subagent_instructions_mention_base_branch():
    from pathlib import Path

    import parrot.flows.dev_flow.nodes.ideation as mod

    text = (Path(mod.__file__).parent.parent / "_subagent_data" / "sdd-ideation.md").read_text(encoding="utf-8")
    assert "| `base_branch` |" in text
    assert "base_branch: dev\n" not in text.split("## Step 3")[1][:600]
