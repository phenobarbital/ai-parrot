"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import parrot_tools.tool_optimizations.inspection as inspection_module
import parrot_tools.tool_optimizations.reader as reader_module
from parrot_tools.tool_optimizations.inspection_models import InspectionBatchArgs
from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit

from .conftest import git


def test_path_policy_and_equivalence(tmp_path: Path) -> None:
    """All six operations obey policy and match individual read-only results."""
    git(tmp_path, "init", "-q", "-b", "dev")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("alpha\nbeta\ngamma\n")
    git(tmp_path, "add", "pkg")
    git(tmp_path, "commit", "-q", "-m", "base")
    base_sha = git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    (tmp_path / "pkg" / "mod.py").write_text("alpha\nbeta\ngamma\ndelta\n")
    git(tmp_path, "commit", "-q", "-am", "head")
    head_sha = git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / "real.py").write_text("one\n")
    (tmp_path / "link.py").symlink_to(tmp_path / "real.py")

    toolkit = BoundedSourceToolkit(repo_root=tmp_path)

    async def scenario():
        info_direct = await toolkit.source_info("pkg/mod.py")
        read_direct = await toolkit.source_read("pkg/mod.py", 1, 2)

        requests = [
            {"id": "r1", "kind": "read", "path": "pkg/mod.py", "start_line": 1, "end_line": 2},
            {"id": "r2", "kind": "info", "path": "pkg/mod.py"},
            {"id": "r3", "kind": "search", "paths": ["pkg/mod.py"], "text": "beta"},
            {"id": "r4", "kind": "search", "paths": ["pkg/mod.py"], "text": "b.ta"},
            {"id": "r5", "kind": "files", "paths": ["pkg"]},
            {"id": "r6", "kind": "git_status"},
            {"id": "r7", "kind": "git_diff_names", "base_sha": base_sha, "head_sha": head_sha},
        ]
        equivalence_result = await toolkit.source_inspect_batch(requests, concurrency=4)

        policy_requests = [
            {"id": "sym", "kind": "read", "path": "link.py"},
            {"id": "secret", "kind": "read", "path": ".env"},
            {"id": "escape", "kind": "read", "path": "../outside.py"},
        ]
        policy_result = await toolkit.source_inspect_batch(policy_requests, concurrency=3)
        return info_direct, read_direct, equivalence_result, policy_result

    info_direct, read_direct, equivalence_result, policy_result = asyncio.run(scenario())

    assert equivalence_result.status == "ok"
    items = {item["id"]: item for item in equivalence_result.data["items"]}
    assert len(items) == 7

    # read/info equivalence with the direct single-operation calls.
    assert items["r1"]["data"]["content"] == read_direct.content
    assert items["r1"]["data"]["sha256"] == read_direct.sha256
    assert items["r2"]["data"]["sha256"] == info_direct.sha256
    assert items["r2"]["data"]["line_count"] == info_direct.line_count

    # search finds the literal substring...
    assert items["r3"]["status"] == "ok"
    assert items["r3"]["data"]["matches"][0] == {"path": "pkg/mod.py", "line": 2, "excerpt": "beta"}
    # ...and a regex metacharacter is never interpreted as a pattern.
    assert items["r4"]["status"] == "ok"
    assert items["r4"]["data"]["matches"] == []

    # files lists the confined tree.
    assert "pkg/mod.py" in items["r5"]["data"]["paths"]

    # git_status/git_diff_names run fixed argv against real commit ids.
    assert items["r6"]["status"] == "ok"
    assert any("real.py" in entry for entry in items["r6"]["data"]["entries"])
    assert items["r7"]["status"] == "ok"
    assert items["r7"]["data"]["paths"] == ["pkg/mod.py"]

    assert equivalence_result.data["partial"] is False

    # Secrets, symlinks and traversal are rejected for read the same way
    # source_read rejects them directly -- and no item ever disappears.
    assert policy_result.status == "ok"
    policy_items = {item["id"]: item for item in policy_result.data["items"]}
    assert set(policy_items) == {"sym", "secret", "escape"}
    assert policy_items["sym"]["error_code"] == "symlink_rejected"
    assert policy_items["secret"]["error_code"] == "secret_file"
    assert policy_items["escape"]["error_code"] == "path_outside_root"
    assert policy_result.data["partial"] is True


def test_duplicate_ids_and_extra_arguments_rejected(tmp_path: Path) -> None:
    """A duplicate item id or an undeclared argument is refused before I/O."""
    with pytest.raises(ValidationError, match="duplicate request id"):
        InspectionBatchArgs(
            requests=[
                {"id": "same", "kind": "info", "path": "a.py"},
                {"id": "same", "kind": "info", "path": "b.py"},
            ]
        )

    with pytest.raises(ValidationError):
        InspectionBatchArgs(requests=[{"id": "x", "kind": "info", "path": "a.py", "bogus": 1}])

    with pytest.raises(ValidationError):
        InspectionBatchArgs(requests=[{"id": "x", "kind": "read", "path": "a.py"}], bogus_top_level=True)


def test_global_concurrency_and_partial_deadlines(tmp_path: Path) -> None:
    """Two batches share four slots and retain every item identity on failure."""
    for i in range(8):
        (tmp_path / f"f{i}.py").write_text(f"line{i}\n")
    toolkit = BoundedSourceToolkit(repo_root=tmp_path)
    original_do_read = inspection_module.InspectionRunner._do_read

    peak = {"value": 0}
    active = {"value": 0}

    async def run_two_concurrent_batches():
        lock = asyncio.Lock()

        async def _tracking_do_read(self, request, started):
            async with lock:
                active["value"] += 1
                peak["value"] = max(peak["value"], active["value"])
            try:
                await asyncio.sleep(0.05)
                return await original_do_read(self, request, started)
            finally:
                async with lock:
                    active["value"] -= 1

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(inspection_module.InspectionRunner, "_do_read", _tracking_do_read)
            batch_a = [{"id": f"a{i}", "kind": "read", "path": f"f{i}.py"} for i in range(4)]
            batch_b = [{"id": f"b{i}", "kind": "read", "path": f"f{i + 4}.py"} for i in range(4)]
            return await asyncio.gather(
                toolkit.source_inspect_batch(batch_a, concurrency=4),
                toolkit.source_inspect_batch(batch_b, concurrency=4),
            )

    result_a, result_b = asyncio.run(run_two_concurrent_batches())

    # Both batches ran through the SAME cached runner (one per toolkit
    # instance), so they shared the four admission slots rather than each
    # getting their own.
    assert 2 <= peak["value"] <= 4
    for result in (result_a, result_b):
        assert result.status == "ok"
        assert {item["id"] for item in result.data["items"]}.__len__() == 4
        assert all(item["status"] == "ok" for item in result.data["items"])

    # An item stuck past its own deadline is reported without erasing its
    # sibling's identity or result.
    async def run_with_hang():
        async def _hanging_do_read(self, request, started):
            if request.id == "slow":
                await asyncio.sleep(5)
            return await original_do_read(self, request, started)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(inspection_module, "_ITEM_TIMEOUT_SECONDS", 0.05)
            mp.setattr(inspection_module.InspectionRunner, "_do_read", _hanging_do_read)
            requests = [
                {"id": "slow", "kind": "read", "path": "f0.py"},
                {"id": "fast", "kind": "read", "path": "f1.py"},
            ]
            return await toolkit.source_inspect_batch(requests, concurrency=2)

    hang_result = asyncio.run(run_with_hang())
    hang_items = {item["id"]: item for item in hang_result.data["items"]}
    assert set(hang_items) == {"slow", "fast"}
    assert hang_items["slow"]["status"] == "error"
    assert hang_items["slow"]["error_code"] == "item_timeout"
    assert hang_items["fast"]["status"] == "ok"
    assert hang_result.data["partial"] is True


def test_git_subprocess_is_killed_and_reaped_on_timeout(tmp_path: Path) -> None:
    """A git subprocess that never returns is killed and reaped, not orphaned."""
    toolkit = BoundedSourceToolkit(repo_root=tmp_path)
    runner = toolkit._inspection_runner
    calls = {"kill": False, "waited": False}

    class _HangingProcess:
        returncode = None

        def kill(self) -> None:
            calls["kill"] = True

        async def wait(self) -> int:
            calls["waited"] = True
            return -9

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(5)
            return b"", b""

    async def _fake_create_subprocess_exec(*_args, **_kwargs):
        return _HangingProcess()

    async def scenario():
        with pytest.raises(inspection_module._ItemTimeout):
            await runner._run_git(["status"], timeout=0.05)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(inspection_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        asyncio.run(scenario())

    assert calls["kill"] is True
    assert calls["waited"] is True


def test_utf8_budget_and_stale_snapshot(tmp_path: Path) -> None:
    """Large Unicode output is bounded and changed files invalidate consistency."""
    big = ("あ" * 100 + "\n") * 200
    (tmp_path / "big.py").write_text(big, encoding="utf-8")
    toolkit = BoundedSourceToolkit(repo_root=tmp_path)

    async def budget_scenario():
        requests = [{"id": "hits", "kind": "search", "paths": ["big.py"], "text": "あ", "max_matches": 100}]
        return await toolkit.source_inspect_batch(requests, concurrency=1, max_output_bytes=24576)

    result = asyncio.run(budget_scenario())
    item = result.data["items"][0]
    assert item["id"] == "hits"
    assert item["status"] == "ok"
    assert item["truncated"] is True
    assert item["continuation"] is not None

    serialized_bytes = len(json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"))
    assert serialized_bytes <= 24576

    # A file mutated mid-scan is reported as its own item error, and the
    # whole batch is marked inconsistent rather than silently trusted.
    victim = tmp_path / "small.py"
    victim.write_text("line1\nline2\nline3\n")
    real_read_line_range = reader_module.read_line_range

    def _mutating_read_line_range(*args, **kwargs):
        span = real_read_line_range(*args, **kwargs)
        victim.write_bytes(b"totally different content\n")
        return span

    async def stale_scenario():
        requests = [
            {"id": "victim", "kind": "read", "path": "small.py", "start_line": 1, "end_line": 2},
            {"id": "peer", "kind": "info", "path": "big.py"},
        ]
        return await toolkit.source_inspect_batch(requests, concurrency=2)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(reader_module, "read_line_range", _mutating_read_line_range)
        stale_result = asyncio.run(stale_scenario())

    stale_items = {item["id"]: item for item in stale_result.data["items"]}
    assert stale_items["victim"]["status"] == "error"
    assert stale_items["victim"]["error_code"] == "concurrent_modification"
    assert stale_items["peer"]["status"] == "ok"
    assert stale_result.data["partial"] is True
    assert stale_result.data["consistent"] is False
