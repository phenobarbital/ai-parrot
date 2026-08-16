"""Unit tests for DevIntakeNode (FEAT-412, TASK-2125).

Covers brief loading (ctx instance / ctx dict / JSON prompt), the per-kind
publication contract (`dev_brief` always, `feature_brief` only for the
document intake), the `flow.intake_validated` event, and fail-before-return
validation.

The Redis client is mocked exactly as ``test_intent_classifier.py`` does it,
so no live Redis is needed.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from parrot.flows.dev_flow.models import DevRequestBrief
from parrot.flows.dev_flow.nodes.dev_intake import DevIntakeNode
from parrot.flows.dev_loop.models import FeatureBrief

RUN_ID = "run-devintake01"


@pytest.fixture
def node(monkeypatch) -> DevIntakeNode:
    """Node with a mocked Redis client so no live Redis is needed."""
    n = DevIntakeNode(redis_url="redis://localhost:6379/0")
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(n, "_ensure_redis", _ensure_redis)
    n._fake_redis = fake_redis  # type: ignore[attr-defined]
    return n


@pytest.fixture
def nl_brief() -> DevRequestBrief:
    return DevRequestBrief(
        kind="enhancement",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
    )


@pytest.fixture
def doc_brief(tmp_path) -> FeatureBrief:
    doc = tmp_path / "existing-idea.proposal.md"
    doc.write_text("# Proposal", encoding="utf-8")
    return FeatureBrief(document_path=str(doc), document_kind="proposal")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_node_is_registered():
    from parrot.bots.flows.flow.flow import NODE_REGISTRY

    assert "dev_flow.dev_intake" in NODE_REGISTRY
    assert NODE_REGISTRY["dev_flow.dev_intake"] is DevIntakeNode


def test_default_node_id():
    n = DevIntakeNode(redis_url="redis://localhost:6379/0")
    assert n.name == "dev_intake"
    # Constructible without a live Redis (lazy connect).
    assert n._redis is None


# ---------------------------------------------------------------------------
# Brief loading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loads_brief_from_ctx(node, nl_brief):
    ctx = {"run_id": RUN_ID, "dev_brief": nl_brief}

    result = await node.execute(ctx)

    assert result is nl_brief
    assert ctx["dev_brief"] is nl_brief
    # A natural-language intake must NOT pre-populate feature_brief —
    # IdeationNode produces it later.
    assert "feature_brief" not in ctx


@pytest.mark.asyncio
async def test_loads_brief_from_ctx_dict(node):
    ctx = {
        "run_id": RUN_ID,
        "dev_brief": {
            "kind": "new_feature",
            "title": "t",
            "description": "d",
        },
    }

    result = await node.execute(ctx)

    assert isinstance(result, DevRequestBrief)
    assert result.kind == "new_feature"
    assert ctx["dev_brief"] is result


@pytest.mark.asyncio
async def test_loads_brief_from_json_prompt(node):
    ctx = {
        "run_id": RUN_ID,
        "initial_task": json.dumps(
            {"kind": "enhancement", "title": "t", "description": "d"}
        ),
    }

    result = await node.execute(ctx)

    assert isinstance(result, DevRequestBrief)
    assert result.kind == "enhancement"
    assert ctx["dev_brief"] is result


@pytest.mark.asyncio
async def test_no_source_raises(node):
    with pytest.raises(ValueError, match="requires ctx"):
        await node.execute({"run_id": RUN_ID})


# ---------------------------------------------------------------------------
# Kind routing / publication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_brief_for_cel_routing(node, nl_brief):
    """The topology routes on `result.kind`, so it must be on the result."""
    result = await node.execute({"run_id": RUN_ID, "dev_brief": nl_brief})
    assert result.kind == "enhancement"

    doc_result = await node.execute(
        {"run_id": RUN_ID, "dev_brief": nl_brief.model_copy(
            update={"kind": "new_feature"}
        )}
    )
    assert doc_result.kind == "new_feature"


@pytest.mark.asyncio
async def test_feature_kind_publishes_feature_brief(node, doc_brief):
    """`feature` intake hands the document straight to PlannerNode's key."""
    ctx = {"run_id": RUN_ID, "dev_brief": doc_brief}

    result = await node.execute(ctx)

    assert result is doc_brief
    assert result.kind == "feature"
    assert ctx["feature_brief"] is doc_brief
    assert ctx["dev_brief"] is doc_brief


@pytest.mark.asyncio
async def test_feature_brief_accepted_from_its_own_key(node, doc_brief):
    ctx = {"run_id": RUN_ID, "feature_brief": doc_brief}

    result = await node.execute(ctx)

    assert result is doc_brief
    assert ctx["dev_brief"] is doc_brief


@pytest.mark.asyncio
async def test_never_publishes_bug_mode_keys(node, nl_brief, doc_brief):
    """dev-flow never populates the bug-mode keys."""
    for brief in (nl_brief, doc_brief):
        ctx = {"run_id": RUN_ID, "dev_brief": brief}
        await node.execute(ctx)
        assert "bug_brief" not in ctx
        assert "work_brief" not in ctx


# ---------------------------------------------------------------------------
# Validation happens before return
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_brief_raises_before_return(node, tmp_path):
    """An unreadable FeatureBrief.document_path fails at load time."""
    ctx = {
        "run_id": RUN_ID,
        "dev_brief": {
            "kind": "feature",
            "document_path": str(tmp_path / "missing.spec.md"),
            "document_kind": "spec",
        },
    }

    with pytest.raises(ValueError):
        await node.execute(ctx)

    # Nothing published, no event emitted.
    assert not isinstance(ctx.get("dev_brief"), FeatureBrief)
    assert "feature_brief" not in ctx
    assert node._fake_redis.xadd.await_count == 0


@pytest.mark.asyncio
async def test_unknown_kind_raises(node):
    ctx = {
        "run_id": RUN_ID,
        "dev_brief": {"kind": "bug", "title": "t", "description": "d"},
    }
    with pytest.raises(ValueError, match="explicit kind"):
        await node.execute(ctx)
    assert node._fake_redis.xadd.await_count == 0


@pytest.mark.asyncio
async def test_missing_required_field_raises(node):
    ctx = {"run_id": RUN_ID, "dev_brief": {"kind": "enhancement", "title": "t"}}
    with pytest.raises(ValueError):
        await node.execute(ctx)


# ---------------------------------------------------------------------------
# flow.intake_validated event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_intake_validated_event(node, nl_brief):
    await node.execute({"run_id": RUN_ID, "dev_brief": nl_brief})

    assert node._fake_redis.xadd.await_count == 1
    args, kwargs = node._fake_redis.xadd.await_args
    assert args[0] == f"flow:{RUN_ID}:flow"
    envelope = json.loads(args[1]["event"])
    assert envelope["kind"] == "flow.intake_validated"
    assert envelope["run_id"] == RUN_ID
    assert envelope["node_id"] == "dev_intake"
    assert envelope["payload"]["kind"] == "enhancement"
    assert envelope["payload"]["title"] == "compression budget telemetry"
    assert kwargs["maxlen"] == 10_000
    assert kwargs["approximate"] is True


@pytest.mark.asyncio
async def test_event_payload_for_feature_kind(node, doc_brief):
    await node.execute({"run_id": RUN_ID, "dev_brief": doc_brief})

    envelope = json.loads(node._fake_redis.xadd.await_args[0][1]["event"])
    payload = envelope["payload"]
    assert payload["kind"] == "feature"
    assert payload["document_kind"] == "proposal"
    assert payload["document_path"] == doc_brief.document_path
    # NL-only fields must not leak into the document payload.
    assert "title" not in payload


@pytest.mark.asyncio
async def test_no_run_id_skips_event(node, nl_brief):
    ctx = {"dev_brief": nl_brief}

    result = await node.execute(ctx)

    assert result is nl_brief
    assert node._fake_redis.xadd.await_count == 0


@pytest.mark.asyncio
async def test_redis_failure_does_not_break_the_node(monkeypatch, nl_brief):
    """A degraded Redis drops the event but must never fail the run."""
    n = DevIntakeNode(redis_url="redis://localhost:6379/0")

    async def _boom():
        raise RuntimeError("redis is down")

    monkeypatch.setattr(n, "_ensure_redis", _boom)

    result = await n.execute({"run_id": RUN_ID, "dev_brief": nl_brief})

    assert result is nl_brief


@pytest.mark.asyncio
async def test_xadd_failure_does_not_break_the_node(monkeypatch, nl_brief):
    n = DevIntakeNode(redis_url="redis://localhost:6379/0")
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(side_effect=RuntimeError("stream gone"))

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(n, "_ensure_redis", _ensure_redis)

    result = await n.execute({"run_id": RUN_ID, "dev_brief": nl_brief})

    assert result is nl_brief


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_releases_client():
    n = DevIntakeNode(redis_url="redis://localhost:6379/0")
    fake_redis = AsyncMock()
    fake_redis.aclose = AsyncMock()
    n._redis = fake_redis  # type: ignore[attr-defined]

    await n.close()

    fake_redis.aclose.assert_awaited_once()
    assert n._redis is None


@pytest.mark.asyncio
async def test_close_is_safe_without_client():
    n = DevIntakeNode(redis_url="redis://localhost:6379/0")
    await n.close()  # must not raise
    assert n._redis is None
