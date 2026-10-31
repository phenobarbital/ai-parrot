"""FEAT-783 TASK-4990 — durable sink (AC-10)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.observability import ObservabilityConfig
from parrot.observability.recorders.factory import build_recorders_from_config
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.spec_usage import SpecUsageRecorder, read_spec_usage


def test_root_inside_worktree_base_is_refused(tmp_path: Path) -> None:
    """A durable root cannot equal or descend from the disposable worktree base."""
    with pytest.raises(ValueError, match="cannot be inside"):
        SpecUsageRecorder(tmp_path / "worktrees" / "usage", worktree_base_path=str(tmp_path / "worktrees"))


@pytest.mark.asyncio
async def test_round_trip_and_unattributed_skipped(tmp_path: Path) -> None:
    """Attributed records round-trip in order and unattributed records are ignored."""
    root = tmp_path / "durable"
    recorder = SpecUsageRecorder(root, worktree_base_path=str(tmp_path / "worktrees"))

    await recorder.record(UsageRecord(provider="openai", model="gpt-5", input_tokens=10, feat_id="FEAT-783"))
    await recorder.record(UsageRecord(provider="anthropic", model="claude", output_tokens=5, feat_id="FEAT-783"))
    await recorder.record(UsageRecord(provider="openai", model="gpt-5"))
    await recorder.aclose()

    with (root / "FEAT-783.jsonl").open("a", encoding="utf-8") as usage_file:
        usage_file.write("not-json\n")

    records = read_spec_usage(root, "FEAT-783")
    assert [record.provider for record in records] == ["openai", "anthropic"]
    assert not (root / "None.jsonl").exists()


@pytest.mark.asyncio
async def test_write_failure_never_raises(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Filesystem failures are swallowed and produce only one warning."""
    root = tmp_path / "not-a-directory"
    root.write_text("occupied", encoding="utf-8")
    recorder = SpecUsageRecorder(root, worktree_base_path=str(tmp_path / "worktrees"))

    with caplog.at_level(logging.WARNING, logger="parrot.observability.recorders.spec_usage"):
        await recorder.record(UsageRecord(provider="openai", feat_id="FEAT-783"))
        await recorder.record(UsageRecord(provider="openai", feat_id="FEAT-783"))
        await recorder.aclose()

    warnings = [record for record in caplog.records if "Spec usage write failed" in record.message]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_rows_readable_by_separate_process(tmp_path: Path) -> None:
    """Rows remain readable from a fresh Python interpreter after the writer flushes."""
    root = tmp_path / "durable"
    recorder = SpecUsageRecorder(root, worktree_base_path=str(tmp_path / "worktrees"))
    await recorder.record(UsageRecord(provider="openai", feat_id="FEAT-783"))
    await recorder.aclose()

    script = (
        "from pathlib import Path\n"
        "import sys\n"
        "from parrot.observability.recorders.spec_usage import read_spec_usage\n"
        "print(f'ROW_COUNT={len(read_spec_usage(Path(sys.argv[1]), sys.argv[2]))}')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
    result = subprocess.run(
        [sys.executable, "-c", script, str(root), "FEAT-783"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    assert "ROW_COUNT=1" in result.stdout.splitlines()


def test_factory_builds_spec_usage_recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory uses the configured root and canonical worktree base setting."""
    from parrot import conf

    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path / "worktrees"))
    root = tmp_path / "durable"
    config = ObservabilityConfig(usage_backend="spec_usage", spec_usage_root=str(root))

    recorders = build_recorders_from_config(config)

    assert len(recorders) == 1
    assert isinstance(recorders[0], SpecUsageRecorder)
    assert recorders[0].root == root


def test_factory_skips_root_inside_worktree_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Invalid factory configuration warns and installs no recorder."""
    from parrot import conf

    worktree_base = tmp_path / "worktrees"
    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(worktree_base))
    config = ObservabilityConfig(usage_backend="spec_usage", spec_usage_root=str(worktree_base / "usage"))

    with caplog.at_level(logging.WARNING, logger="parrot.observability.recorders.factory"):
        recorders = build_recorders_from_config(config)

    assert recorders == []
    assert "Spec usage recorder disabled" in caplog.text


def test_default_root_is_canonical_spec_usage_subdir(tmp_path: Path) -> None:
    """The helper, the recorder default and the engine share one root: <durable>/spec-usage."""
    from parrot.observability.recorders.spec_usage import SPEC_USAGE_SUBDIR, default_spec_usage_root

    worktrees = str(tmp_path / "worktrees")
    durable = tmp_path / "durable"

    root = default_spec_usage_root(worktrees, str(durable))

    assert root == (durable / SPEC_USAGE_SUBDIR).resolve()
    assert SpecUsageRecorder(root, worktree_base_path=worktrees).root == root
    assert default_spec_usage_root(worktrees, str(durable / "x")).parent.name == "x"
