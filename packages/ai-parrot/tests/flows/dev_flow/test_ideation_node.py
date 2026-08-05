"""Unit tests for IdeationNode — the FEAT-412 HITL round-trip (TASK-2126).

Exercises the normative sequence of spec §2 with a **scripted fake
dispatcher** (no Claude SDK, no Redis): mode selection per intent, ONE gate
per round carrying all questions, answers reaching the re-dispatch payload,
the round bound, the fail-closed/rejection paths, the `committed=False`
fail-fast, and the gateless autonomous fallback.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow.nodes.ideation import IdeationNode
from parrot.flows.dev_loop.models import DevAgentSpec, FeatureBrief, JudgePanelConfig
from parrot.flows.dev_loop.session_state import SessionHost

RUN_ID = "run-ideation01"

Q1 = "Which store backs the telemetry?"
Q2 = "Sync or async flush?"


class ScriptedDispatcher:
    """Returns a pre-scripted IdeationOutput per dispatch, recording payloads.

    Mirrors the ``fake_ideation_dispatcher`` fixture the task specifies:
    round 1 → open questions; round 2 (with answers) → none, committed.
    """

    def __init__(self, outputs: list[IdeationOutput]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    async def dispatch(
        self,
        *,
        brief: Any,
        profile: Any,
        output_model: Any,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Any = None,
    ) -> Any:
        self.calls.append(
            {
                "brief": brief,
                "profile": profile,
                "output_model": output_model,
                "run_id": run_id,
                "node_id": node_id,
                "cwd": cwd,
                "session_host": session_host,
            }
        )
        if not self._outputs:
            raise AssertionError("ScriptedDispatcher exhausted — unexpected dispatch")
        return self._outputs.pop(0)


@pytest.fixture
def doc(tmp_path, monkeypatch):
    """A committed-looking document under a fake PROJECT_ROOT."""
    proposals = tmp_path / "sdd" / "proposals"
    proposals.mkdir(parents=True)
    path = proposals / "telemetry.brainstorm.md"
    path.write_text("# Brainstorm", encoding="utf-8")

    from parrot import conf

    monkeypatch.setattr(conf, "PROJECT_ROOT", tmp_path, raising=False)
    return path


@pytest.fixture
def proposal_doc(tmp_path, monkeypatch):
    proposals = tmp_path / "sdd" / "proposals"
    proposals.mkdir(parents=True, exist_ok=True)
    path = proposals / "telemetry.proposal.md"
    path.write_text("# Proposal", encoding="utf-8")

    from parrot import conf

    monkeypatch.setattr(conf, "PROJECT_ROOT", tmp_path, raising=False)
    return path


def _brief(kind: str = "new_feature", **extra) -> DevRequestBrief:
    return DevRequestBrief(
        kind=kind,
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
        **extra,
    )


def _output(**over) -> IdeationOutput:
    base = {
        "document_path": "sdd/proposals/telemetry.brainstorm.md",
        "document_kind": "brainstorm",
        "slug": "telemetry",
        "committed": True,
    }
    base.update(over)
    return IdeationOutput(**base)


async def _answer_gate(host: SessionHost, answers: dict[str, str]) -> None:
    """Approve the single pending gate with `answers`."""
    await asyncio.sleep(0.01)
    gate_id = next(
        g for g, gate in host.state.gates.items() if gate.status == "pending"
    )
    host.resolve_gate(gate_id, "approved", resolved_by="alice", answers=answers)


# ---------------------------------------------------------------------------
# Registration + mode selection
# ---------------------------------------------------------------------------


def test_node_is_registered():
    from parrot.bots.flows.flow.flow import NODE_REGISTRY

    assert "dev_flow.ideation" in NODE_REGISTRY
    assert NODE_REGISTRY["dev_flow.ideation"] is IdeationNode


@pytest.mark.asyncio
async def test_new_feature_emits_brainstorm(doc):
    dispatcher = ScriptedDispatcher([_output()])
    node = IdeationNode(dispatcher=dispatcher)
    ctx = {"run_id": RUN_ID, "dev_brief": _brief("new_feature")}

    result = await node.execute(ctx)

    assert dispatcher.calls[0]["brief"].mode == "brainstorm"
    assert isinstance(result, FeatureBrief)
    assert result.document_kind == "brainstorm"
    assert ctx["feature_brief"] is result


@pytest.mark.asyncio
async def test_enhancement_emits_proposal(proposal_doc):
    dispatcher = ScriptedDispatcher(
        [
            _output(
                document_path="sdd/proposals/telemetry.proposal.md",
                document_kind="proposal",
            )
        ]
    )
    node = IdeationNode(dispatcher=dispatcher)
    ctx = {"run_id": RUN_ID, "dev_brief": _brief("enhancement")}

    result = await node.execute(ctx)

    assert dispatcher.calls[0]["brief"].mode == "proposal"
    assert result.document_kind == "proposal"


@pytest.mark.asyncio
async def test_dispatch_payload_and_profile(doc):
    dispatcher = ScriptedDispatcher([_output()])
    node = IdeationNode(dispatcher=dispatcher)
    brief = _brief("new_feature", context="see PR #12")

    await node.execute({"run_id": RUN_ID, "dev_brief": brief})

    call = dispatcher.calls[0]
    payload = call["brief"]
    assert payload.title == brief.title
    assert payload.description == brief.description
    assert payload.context == "see PR #12"
    assert payload.answers == {}
    assert payload.document_path == ""
    assert payload.round == 1
    assert call["output_model"] is IdeationOutput
    assert call["run_id"] == RUN_ID
    assert call["node_id"] == "ideation"

    profile = call["profile"]
    # The prompt travels as a system prompt — dev_loop's loader must not be
    # asked for a dev_flow-owned subagent name.
    assert profile.subagent is None
    assert "SDD Ideation" in profile.system_prompt_override
    assert profile.permission_mode == "acceptEdits"
    for tool in ("Read", "Write", "Edit", "Bash"):
        assert tool in profile.allowed_tools


# ---------------------------------------------------------------------------
# Passthrough into the FeatureBrief
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passthrough_jira_pool_and_panel(doc):
    dispatcher = ScriptedDispatcher([_output()])
    node = IdeationNode(dispatcher=dispatcher)
    brief = _brief(
        "new_feature",
        jira_issue_key="PARROT-7",
        dev_agents=[DevAgentSpec(agent="claude-code", count=3)],
        judge_panel=JudgePanelConfig(judges=[{"agent": "codex"}]),
    )

    result = await node.execute({"run_id": RUN_ID, "dev_brief": brief})

    assert result.jira_issue_key == "PARROT-7"
    assert result.dev_agents is not None
    assert result.dev_agents[0].count == 3
    assert result.judge_panel is not None


@pytest.mark.asyncio
async def test_resumed_existing_flag_passthrough(doc):
    dispatcher = ScriptedDispatcher([_output(resumed_existing=True)])
    node = IdeationNode(dispatcher=dispatcher)
    ctx = {"run_id": RUN_ID, "dev_brief": _brief()}

    await node.execute(ctx)

    assert ctx["ideation_output"].resumed_existing is True


# ---------------------------------------------------------------------------
# The HITL round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_roundtrip_answers_reach_redispatch(doc):
    """Round 1 asks 2 questions; the answers land in the round-2 payload."""
    dispatcher = ScriptedDispatcher(
        [_output(open_questions=[Q1, Q2], committed=True), _output()]
    )
    node = IdeationNode(dispatcher=dispatcher)
    host = SessionHost(RUN_ID)
    ctx = {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
    answers = {Q1: "pgvector", Q2: "async"}

    resolver = asyncio.ensure_future(_answer_gate(host, answers))
    result = await node.execute(ctx)
    await resolver

    # ONE gate for the whole round, carrying ALL questions.
    assert len(host.state.gates) == 1
    gate = next(iter(host.state.gates.values()))
    assert gate.kind == "open_questions"
    assert gate.questions == [Q1, Q2]
    assert gate.node_id == "ideation"
    assert gate.on_expiry == "fail"  # fail-closed
    # The document path is in the title so an unintended resume is visible.
    assert "sdd/proposals/telemetry.brainstorm.md" in gate.title

    # Round 2 received the answers and the document to resume.
    assert len(dispatcher.calls) == 2
    second = dispatcher.calls[1]["brief"]
    assert second.answers == answers
    assert second.document_path == "sdd/proposals/telemetry.brainstorm.md"
    assert second.round == 2
    assert isinstance(result, FeatureBrief)


@pytest.mark.asyncio
async def test_partial_answers_are_accepted(doc):
    dispatcher = ScriptedDispatcher([_output(open_questions=[Q1, Q2]), _output()])
    node = IdeationNode(dispatcher=dispatcher)
    host = SessionHost(RUN_ID)

    resolver = asyncio.ensure_future(_answer_gate(host, {Q1: "pgvector"}))
    await node.execute(
        {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
    )
    await resolver

    assert dispatcher.calls[1]["brief"].answers == {Q1: "pgvector"}


@pytest.mark.asyncio
async def test_no_questions_means_no_gate(doc):
    dispatcher = ScriptedDispatcher([_output()])
    node = IdeationNode(dispatcher=dispatcher)
    host = SessionHost(RUN_ID)

    await asyncio.wait_for(
        node.execute(
            {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
        ),
        timeout=2,
    )

    assert host.state.gates == {}
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_rounds_bounded(doc):
    """A subagent that keeps asking stops after DEV_FLOW_IDEATION_MAX_ROUNDS."""
    # Always returns open questions; 1 initial + max_rounds re-dispatches.
    dispatcher = ScriptedDispatcher([_output(open_questions=[Q1]) for _ in range(4)])
    node = IdeationNode(dispatcher=dispatcher, ideation_max_rounds=2)
    host = SessionHost(RUN_ID)

    async def _answer_all():
        for _ in range(2):
            await _answer_gate(host, {Q1: "an answer"})

    resolver = asyncio.ensure_future(_answer_all())
    result = await asyncio.wait_for(
        node.execute(
            {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
        ),
        timeout=5,
    )
    await resolver

    # Exactly max_rounds gates, and 1 + max_rounds dispatches.
    assert len(host.state.gates) == 2
    assert len(dispatcher.calls) == 3
    # Leftover questions do NOT block the run.
    assert isinstance(result, FeatureBrief)


@pytest.mark.asyncio
async def test_max_rounds_zero_opens_no_gate(doc):
    dispatcher = ScriptedDispatcher([_output(open_questions=[Q1])])
    node = IdeationNode(dispatcher=dispatcher, ideation_max_rounds=0)
    host = SessionHost(RUN_ID)

    result = await asyncio.wait_for(
        node.execute(
            {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
        ),
        timeout=2,
    )

    assert host.state.gates == {}
    assert isinstance(result, FeatureBrief)


@pytest.mark.asyncio
async def test_max_rounds_reads_conf_when_not_overridden(doc, monkeypatch):
    from parrot import conf

    monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MAX_ROUNDS", 1, raising=False)
    dispatcher = ScriptedDispatcher([_output(open_questions=[Q1]) for _ in range(3)])
    node = IdeationNode(dispatcher=dispatcher)
    host = SessionHost(RUN_ID)

    resolver = asyncio.ensure_future(_answer_gate(host, {Q1: "a"}))
    await asyncio.wait_for(
        node.execute(
            {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
        ),
        timeout=5,
    )
    await resolver

    assert len(host.state.gates) == 1
    assert len(dispatcher.calls) == 2


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_rejected_raises(doc):
    """Rejection = the user aborts the ideation → failure_handler."""
    dispatcher = ScriptedDispatcher([_output(open_questions=[Q1])])
    node = IdeationNode(dispatcher=dispatcher)
    host = SessionHost(RUN_ID)

    async def _reject():
        await asyncio.sleep(0.01)
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(
            gate_id, "rejected", resolved_by="bob", comment="wrong document"
        )

    resolver = asyncio.ensure_future(_reject())
    with pytest.raises(RuntimeError, match="rejected by bob"):
        await node.execute(
            {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
        )
    await resolver

    # No re-dispatch happened.
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_gate_expired_raises(doc):
    """Fail-closed expiry: silence is not consent for spec decisions."""
    dispatcher = ScriptedDispatcher([_output(open_questions=[Q1])])
    node = IdeationNode(dispatcher=dispatcher)
    host = SessionHost(RUN_ID)

    async def _expire():
        await asyncio.sleep(0.01)
        gate_id = next(iter(host.state.gates))
        gate = host.state.gates[gate_id]
        host.expire_due_gates(now=(gate.expires_at or 0) + 1)

    resolver = asyncio.ensure_future(_expire())
    with pytest.raises(RuntimeError, match="expired"):
        await node.execute(
            {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}
        )
    await resolver


@pytest.mark.asyncio
async def test_uncommitted_output_raises(doc):
    """committed=False → raise BEFORE building the FeatureBrief."""
    dispatcher = ScriptedDispatcher([_output(committed=False, summary="commit hook said no")])
    node = IdeationNode(dispatcher=dispatcher)
    ctx = {"run_id": RUN_ID, "dev_brief": _brief()}

    with pytest.raises(RuntimeError, match="did not commit"):
        await node.execute(ctx)

    assert "feature_brief" not in ctx


@pytest.mark.asyncio
async def test_unreadable_document_raises(tmp_path, monkeypatch):
    """committed=True but no such file → actionable node error, not ValidationError."""
    from parrot import conf

    monkeypatch.setattr(conf, "PROJECT_ROOT", tmp_path, raising=False)
    dispatcher = ScriptedDispatcher(
        [_output(document_path="sdd/proposals/ghost.brainstorm.md")]
    )
    node = IdeationNode(dispatcher=dispatcher)

    with pytest.raises(RuntimeError, match="no.*readable document"):
        await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})


@pytest.mark.asyncio
async def test_wrong_brief_type_raises(doc, tmp_path):
    """A FeatureBrief must never reach this node — it routes to the planner."""
    fb_doc = tmp_path / "x.spec.md"
    fb_doc.write_text("# s", encoding="utf-8")
    node = IdeationNode(dispatcher=ScriptedDispatcher([]))

    with pytest.raises(ValueError, match="DevRequestBrief"):
        await node.execute(
            {
                "run_id": RUN_ID,
                "dev_brief": FeatureBrief(
                    document_path=str(fb_doc), document_kind="spec"
                ),
            }
        )


@pytest.mark.asyncio
async def test_missing_brief_raises(doc):
    node = IdeationNode(dispatcher=ScriptedDispatcher([]))
    with pytest.raises(ValueError, match="requires ctx"):
        await node.execute({"run_id": RUN_ID})


# ---------------------------------------------------------------------------
# Gateless (autonomous) fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_host_runs_gateless(doc, caplog):
    """No session_host → warn and proceed; questions stay in the document."""
    import logging

    dispatcher = ScriptedDispatcher([_output(open_questions=[Q1, Q2])])
    node = IdeationNode(dispatcher=dispatcher)

    with caplog.at_level(logging.WARNING):
        result = await asyncio.wait_for(
            node.execute({"run_id": RUN_ID, "dev_brief": _brief()}), timeout=2
        )

    assert isinstance(result, FeatureBrief)
    assert len(dispatcher.calls) == 1  # no re-dispatch without answers
    assert any("no session_host" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Wiki context injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_context_is_injected(doc):
    class FakeWiki:
        async def build_research_context(self, query: str):
            self.query = query
            return "## ranked pages"

    wiki = FakeWiki()
    dispatcher = ScriptedDispatcher([_output()])
    node = IdeationNode(dispatcher=dispatcher, wiki_search=wiki)

    await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

    assert dispatcher.calls[0]["brief"].graph_context == "## ranked pages"
    assert "compression budget telemetry" in wiki.query


@pytest.mark.asyncio
async def test_wiki_failure_degrades_to_empty_context(doc):
    class BoomWiki:
        async def build_research_context(self, query: str):
            raise RuntimeError("wiki plane not built")

    dispatcher = ScriptedDispatcher([_output()])
    node = IdeationNode(dispatcher=dispatcher, wiki_search=BoomWiki())

    result = await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

    assert dispatcher.calls[0]["brief"].graph_context == ""
    assert isinstance(result, FeatureBrief)


@pytest.mark.asyncio
async def test_no_wiki_means_empty_context(doc):
    dispatcher = ScriptedDispatcher([_output()])
    node = IdeationNode(dispatcher=dispatcher)

    await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

    assert dispatcher.calls[0]["brief"].graph_context == ""
