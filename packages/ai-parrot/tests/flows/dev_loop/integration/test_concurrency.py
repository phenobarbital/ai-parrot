"""Concurrency-cap enforcement test for the dev-loop dispatcher.

Verifies the global semaphore caps in-flight dispatches at
``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES``. This test does NOT require
``claude`` CLI — it stands up four mocked dispatches in parallel and
asserts only ``max_concurrent`` are simultaneously active.

Marked ``live`` for naming consistency with the rest of the integration
suite, but it can run anywhere with the ``redis`` Python package
installed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from unittest.mock import AsyncMock

from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher,
    ClaudeCodeDispatchProfile,
    ResearchOutput,
)


pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_concurrent_flows_respect_dispatcher_cap(
    skip_unless_redis_available,
    monkeypatch,
    tmp_path,
):
    """Spawn 4 dispatches with ``max_concurrent=2``; only 2 in flight."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    disp = ClaudeCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )

    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)

    active = {"n": 0, "max": 0}
    gate = asyncio.Event()

    class _SlowClient:
        async def ask_stream(self, prompt: str, *, options: Any):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            await gate.wait()

            class _Block:
                def __init__(self, text):
                    self.text = text

            class _Msg:
                def __init__(self, content):
                    self.content = content

            payload = (
                '{"jira_issue_key":"OPS-1",'
                '"spec_path":"x.spec.md","feat_id":"FEAT-1",'
                '"branch_name":"b","worktree_path":"' + str(tmp_path) + '",'
                '"log_excerpts":[]}'
            )
            yield _Msg(content=[_Block(text=payload)])

            class _Result:
                subtype = "success"
                content = []

            yield _Result()
            active["n"] -= 1

    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatcher.LLMFactory.create",
        lambda *a, **kw: _SlowClient(),
    )

    brief = ResearchOutput(
        jira_issue_key="OPS-0",
        spec_path="x",
        feat_id="FEAT-0",
        branch_name="b",
        worktree_path=str(tmp_path),
    )

    async def _dispatch_one(idx: int):
        return await disp.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput,
            run_id=f"run-{idx}",
            node_id="research",
            cwd=str(tmp_path),
        )

    tasks = [asyncio.create_task(_dispatch_one(i)) for i in range(4)]
    for _ in range(20):
        await asyncio.sleep(0)
    assert active["n"] <= 2
    gate.set()
    results = await asyncio.gather(*tasks)
    assert len(results) == 4
    assert active["max"] == 2
