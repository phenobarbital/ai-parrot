"""Tests for the platform-agnostic knowledge upload service."""

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.auth.userinfo import EmployeeProfile
from parrot.integrations.knowledge_upload.models import (
    KnowledgeUploadConfig,
    UploaderIdentity,
    UploadOutcome,
    UploadRequest,
    UploadStatus,
    UploadTargetKind,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService
from parrot.integrations.knowledge_upload.targets.base import IngestTarget


class FakeTarget(IngestTarget):
    """Controllable target used to verify service lifecycle behavior."""

    kind = UploadTargetKind.BOOKSTORE

    def __init__(
        self,
        root: Path,
        gate: asyncio.Event | None = None,
        fail: bool = False,
        usable: bool = True,
        reason: str = "",
    ) -> None:
        self._root = root
        self.gate = gate
        self.fail = fail
        self.usable = usable
        self.reason = reason
        self.active = 0
        self.max_active = 0
        self.seen_paths: list[Path] = []

    @property
    def lock_key(self) -> Path:
        """Return the root used to serialize target writes."""
        return self._root

    @property
    def staging_dir(self) -> Path:
        """Return the private staging location."""
        return self._root / ".uploads"

    async def available(self) -> tuple[bool, str]:
        """Report this fake target as available."""
        return self.usable, self.reason

    async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
        """Record concurrent work and optionally wait or fail."""
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.seen_paths.append(staged_path)
        try:
            if self.gate:
                await self.gate.wait()
            if self.fail:
                raise RuntimeError("boom")
            return UploadOutcome(
                job_id=job_id,
                status=UploadStatus.ADDED,
                target=self.kind,
                filename=request.filename,
                message="ok",
            )
        finally:
            self.active -= 1


@pytest.fixture
def userinfo() -> AsyncMock:
    """Provide the authorized curator identity service."""
    user_info = AsyncMock()
    user_info.get_profile.return_value = EmployeeProfile(user_id=1, username="jlara", groups=["curators"])
    return user_info


def _request(data: bytes = b"# doc", name: str = "a.md") -> UploadRequest:
    """Build a conventional Bookstore request."""
    return UploadRequest(
        target=UploadTargetKind.BOOKSTORE,
        filename=name,
        data=data,
        identity=UploaderIdentity(platform="telegram", platform_user_id="9", nav_user_id="1"),
    )


def _service(tmp_path: Path, userinfo: AsyncMock, target: FakeTarget | None = None) -> KnowledgeUploadService:
    """Build an authorized service around the specified fake target."""
    config = KnowledgeUploadConfig(enabled=True, allowed_usernames=["jlara"], max_size_mb=1)
    target = target or FakeTarget(tmp_path)
    return KnowledgeUploadService(config, {UploadTargetKind.BOOKSTORE: target}, userinfo)


async def test_submit_rejects_extension_and_size(tmp_path: Path, userinfo: AsyncMock) -> None:
    """Invalid extension and oversize input do not create jobs."""
    service = _service(tmp_path, userinfo)
    assert (await service.submit(_request(name="a.doc"), AsyncMock())).status == UploadStatus.INVALID
    assert (await service.submit(_request(data=b"x" * (2 * 1024 * 1024)), AsyncMock())).status == UploadStatus.INVALID
    assert not service._jobs


async def test_job_notifies_and_deletes(tmp_path: Path, userinfo: AsyncMock) -> None:
    """Accepted work notifies with the final result and deletes staged bytes."""
    target = FakeTarget(tmp_path)
    service = _service(tmp_path, userinfo, target)
    notify = AsyncMock()
    assert (await service.submit(_request(), notify)).status == UploadStatus.ACCEPTED
    while service._jobs:
        await asyncio.sleep(0)
    notified = notify.await_args.args[0]
    assert notified.status == UploadStatus.ADDED
    assert target.seen_paths and not target.seen_paths[0].exists()


async def test_job_serializes_per_target_across_services(tmp_path: Path, userinfo: AsyncMock) -> None:
    """Separate service instances share one lock for the same target root."""
    gate = asyncio.Event()
    first_target = FakeTarget(tmp_path, gate)
    second_target = FakeTarget(tmp_path, gate)
    first = _service(tmp_path, userinfo, first_target)
    second = _service(tmp_path, userinfo, second_target)
    await first.submit(_request(name="first.md"), AsyncMock())
    await second.submit(_request(name="second.md"), AsyncMock())
    while first_target.active != 1:
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert second_target.active == 0
    gate.set()
    while first._jobs or second._jobs:
        await asyncio.sleep(0)
    assert first_target.max_active + second_target.max_active == 2


async def test_jobs_with_different_targets_may_overlap(tmp_path: Path, userinfo: AsyncMock) -> None:
    """Distinct target roots are not unnecessarily serialized."""
    gate = asyncio.Event()
    first_target = FakeTarget(tmp_path / "one", gate)
    second_target = FakeTarget(tmp_path / "two", gate)
    first = _service(tmp_path, userinfo, first_target)
    second = _service(tmp_path, userinfo, second_target)
    await first.submit(_request(name="first.md"), AsyncMock())
    await second.submit(_request(name="second.md"), AsyncMock())
    while first_target.active != 1 or second_target.active != 1:
        await asyncio.sleep(0)
    gate.set()
    while first._jobs or second._jobs:
        await asyncio.sleep(0)


async def test_job_failure_becomes_failed_outcome(tmp_path: Path, userinfo: AsyncMock) -> None:
    """Target failures become safe failed outcomes and still notify."""
    target = FakeTarget(tmp_path, fail=True)
    service = _service(tmp_path, userinfo, target)
    notify = AsyncMock()
    await service.submit(_request(), notify)
    while service._jobs:
        await asyncio.sleep(0)
    assert notify.await_args.args[0].status == UploadStatus.FAILED
    assert not target.seen_paths[0].exists()


async def test_shutdown_cancels_jobs(tmp_path: Path, userinfo: AsyncMock) -> None:
    """Shutdown cancels staged work and waits for its cleanup."""
    target = FakeTarget(tmp_path, asyncio.Event())
    service = _service(tmp_path, userinfo, target)
    await service.submit(_request(), AsyncMock())
    while target.active != 1:
        await asyncio.sleep(0)
    await service.shutdown()
    assert not service._jobs
    assert not target.seen_paths[0].exists()


async def test_denied_is_audited(tmp_path: Path, userinfo: AsyncMock, caplog: pytest.LogCaptureFixture) -> None:
    """Denied submissions write a single audit event without starting a job."""
    config = KnowledgeUploadConfig(enabled=True, allowed_usernames=["other"])
    service = KnowledgeUploadService(config, {UploadTargetKind.BOOKSTORE: FakeTarget(tmp_path)}, userinfo)
    with caplog.at_level(logging.INFO, logger="parrot.integrations.knowledge_upload.audit"):
        outcome = await service.submit(_request(), AsyncMock())
    records = [record for record in caplog.records if record.name.endswith("knowledge_upload.audit")]
    assert outcome.status == UploadStatus.DENIED
    assert len(records) == 1
    assert records[0].status == UploadStatus.DENIED.value
    assert not service._jobs


async def test_from_config_drops_unavailable_target(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup excludes unavailable targets and reports the configured reason."""
    unavailable = FakeTarget(tmp_path, usable=False, reason="missing charter")
    monkeypatch.setattr(
        "parrot.integrations.knowledge_upload.targets.build_targets",
        lambda config: {UploadTargetKind.BOOKSTORE: unavailable},
    )
    with caplog.at_level(logging.WARNING):
        service = await KnowledgeUploadService.from_config(KnowledgeUploadConfig(enabled=True))
    assert not service.available_targets()
    assert "missing charter" in caplog.text
