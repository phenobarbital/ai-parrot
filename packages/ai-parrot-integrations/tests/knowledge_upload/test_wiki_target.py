from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.knowledge_upload import (
    UploaderIdentity,
    UploadRequest,
    UploadStatus,
    UploadTargetKind,
    WikiTargetConfig,
)
from parrot.integrations.knowledge_upload.targets.wiki import WikiTarget


def _entry(action, source="model", briefing="because"):
    entry = MagicMock(proposed_action=action, decision_source=source, briefing=briefing)
    entry.model_copy.return_value = entry
    return entry


def _target(tmp_path, entry, report=None):
    target = WikiTarget(WikiTargetConfig(wiki_root=str(tmp_path)))
    target._runtime = SimpleNamespace(
        acquirer=MagicMock(acquire=AsyncMock(return_value=SimpleNamespace(text="# doc"))),
        router=MagicMock(triage=AsyncMock(return_value=entry)),
        orchestrator=MagicMock(
            ingest=AsyncMock(
                return_value=report or SimpleNamespace(status="ok", error=None, pages_created=3, pages_updated=0)
            )
        ),
        wiki_config=object(),
        charter=SimpleNamespace(version="v1"),
        store=object(),
    )
    return target


def _request(force=False):
    return UploadRequest(
        target=UploadTargetKind.WIKI,
        filename="sop.md",
        data=b"# sop",
        force=force,
        identity=UploaderIdentity(platform="slack", platform_user_id="U1"),
    )


@pytest.mark.asyncio
async def test_admit_is_ingested(tmp_path):
    target = _target(tmp_path, _entry("admit"))
    outcome = await target.ingest(tmp_path / "sop.md", _request(), "j1")

    assert outcome.status == UploadStatus.ADDED
    call = target._runtime.orchestrator.ingest.call_args
    assert call.args[0] == str(tmp_path / "sop.md")
    assert call.kwargs["charter_version"] == "v1"
    target._runtime.router.triage.return_value.model_copy.assert_called_once_with(
        update={"decision": "admit", "decision_source": "auto"}
    )


@pytest.mark.parametrize("action", ["archive", "discard"])
@pytest.mark.asyncio
async def test_non_admit_rejected(tmp_path, action):
    target = _target(tmp_path, _entry(action, briefing="off-charter"))
    outcome = await target.ingest(tmp_path / "sop.md", _request(), "j1")

    assert outcome.status == UploadStatus.REJECTED_BY_TRIAGE
    assert "off-charter" in outcome.message
    assert outcome.detail["triage_action"] == action
    target._runtime.orchestrator.ingest.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_skipped_and_force_flag(tmp_path):
    target = _target(tmp_path, _entry("discard", source="heuristic", briefing="Rejected by heuristic: duplicate: same"))
    outcome = await target.ingest(tmp_path / "sop.md", _request(), "j1")

    assert outcome.status == UploadStatus.SKIPPED
    assert outcome.message == "Already present (same content) — use --force"
    target._runtime.orchestrator.ingest.assert_not_called()

    forced_target = _target(tmp_path, _entry("admit"))
    await forced_target.ingest(tmp_path / "sop.md", _request(force=True), "j2")
    assert forced_target._runtime.router.triage.call_args.kwargs["skip_duplicate_check"] is True


@pytest.mark.asyncio
async def test_failed_report_sanitizes_error_and_checkpoint_failure_does_not_fail(tmp_path):
    report = SimpleNamespace(status="error", error=f"failed at {tmp_path}/private.md", pages_created=0, pages_updated=0)
    target = _target(tmp_path, _entry("admit"), report=report)

    from parrot.knowledge.wiki.store import SQLiteWikiStore

    store = MagicMock(spec=SQLiteWikiStore)
    store.checkpoint = AsyncMock(side_effect=RuntimeError("checkpoint unavailable"))
    target._runtime.store = store
    outcome = await target.ingest(tmp_path / "sop.md", _request(), "j1")

    assert outcome.status == UploadStatus.FAILED
    assert str(tmp_path) not in outcome.message
    store.checkpoint.assert_awaited_once()


@pytest.mark.asyncio
async def test_unavailable_without_charter(tmp_path):
    ok, reason = await WikiTarget(WikiTargetConfig(wiki_root=str(tmp_path))).available()

    assert not ok
    assert "charter" in reason
