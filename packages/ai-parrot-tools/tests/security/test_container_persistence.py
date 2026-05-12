"""Unit tests for ContainerSecurityToolkit persistence integration (FEAT-162)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.security.container_security_toolkit import ContainerSecurityToolkit

# Minimal valid Trivy JSON output that the parser can handle
_TRIVY_STDOUT = '{"SchemaVersion": 2, "ArtifactName": "test", "Results": []}'


def _stub_executor_scan_image(toolkit: ContainerSecurityToolkit) -> None:
    toolkit.executor.scan_image = AsyncMock(
        return_value=(_TRIVY_STDOUT, "", 0)
    )


def _stub_executor_scan_filesystem(toolkit: ContainerSecurityToolkit) -> None:
    toolkit.executor.scan_filesystem = AsyncMock(
        return_value=(_TRIVY_STDOUT, "", 0)
    )


class TestContainerPersistence:
    def test_inheritance(self) -> None:
        """ContainerSecurityToolkit must inherit ReportPersistenceMixin first."""
        from parrot_tools.security.persistence import ReportPersistenceMixin
        assert issubclass(ContainerSecurityToolkit, ReportPersistenceMixin)

    def test_kwargs_pop_keeps_super_init_clean(self) -> None:
        """Constructing with persistence kwargs must NOT raise."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(file_manager=fm, report_store=store)
        assert toolkit.file_manager is fm
        assert toolkit.report_store is store

    def test_noop_when_persistence_kwargs_missing(self) -> None:
        """Without persistence kwargs, file_manager and report_store are None."""
        toolkit = ContainerSecurityToolkit()
        assert toolkit.file_manager is None
        assert toolkit.report_store is None

    async def test_trivy_scan_image_persists(self) -> None:
        """trivy_scan_image calls _persist_report once when deps are wired."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(file_manager=fm, report_store=store)
        _stub_executor_scan_image(toolkit)

        with patch.object(toolkit, "_persist_report", new=AsyncMock()) as p:
            await toolkit.trivy_scan_image(image="nginx:latest")
        p.assert_called_once()
        call_kwargs = p.call_args.kwargs
        assert call_kwargs["scanner"] == "trivy"
        assert call_kwargs["framework"] is None

    async def test_trivy_scan_filesystem_persists(self) -> None:
        """trivy_scan_filesystem calls _persist_report once when deps are wired."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(file_manager=fm, report_store=store)
        _stub_executor_scan_filesystem(toolkit)

        with patch.object(toolkit, "_persist_report", new=AsyncMock()) as p:
            await toolkit.trivy_scan_filesystem(path="/app")
        p.assert_called_once()
        call_kwargs = p.call_args.kwargs
        assert call_kwargs["scanner"] == "trivy"
        assert call_kwargs["scope"] == {"target_path": "/app"}

    async def test_persist_content_is_path(self) -> None:
        """_persist_report receives a Path (temp file) as content."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(file_manager=fm, report_store=store)
        _stub_executor_scan_filesystem(toolkit)

        captured: dict = {}

        async def _capture(**kwargs):
            captured["content"] = kwargs["content"]
            captured["path_exists"] = isinstance(kwargs["content"], Path) and kwargs["content"].exists()

        with patch.object(toolkit, "_persist_report", new=_capture):
            await toolkit.trivy_scan_filesystem(path="/app")

        assert isinstance(captured.get("content"), Path), "content must be a Path"
        assert captured.get("path_exists"), "temp file must exist during _persist_report call"

    async def test_temp_file_deleted_after_persist(self) -> None:
        """Temp file is deleted after _persist_report completes."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(file_manager=fm, report_store=store)
        _stub_executor_scan_filesystem(toolkit)

        seen_path: list[Path] = []

        async def _capture(**kwargs):
            seen_path.append(kwargs["content"])

        with patch.object(toolkit, "_persist_report", new=_capture):
            await toolkit.trivy_scan_filesystem(path="/app")

        assert seen_path, "No temp file path was captured"
        assert not seen_path[0].exists(), f"Temp file {seen_path[0]} was NOT deleted"

    async def test_temp_file_deleted_on_persist_failure(self) -> None:
        """Temp file is deleted even when _persist_report raises."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(file_manager=fm, report_store=store)
        _stub_executor_scan_filesystem(toolkit)

        seen_path: list[Path] = []

        async def _boom(**kwargs):
            seen_path.append(kwargs["content"])
            raise RuntimeError("persist exploded")

        with patch.object(toolkit, "_persist_report", new=_boom):
            with pytest.raises(RuntimeError, match="persist exploded"):
                await toolkit.trivy_scan_filesystem(path="/app")

        assert seen_path, "No temp file path was captured"
        assert not seen_path[0].exists(), f"Temp file {seen_path[0]} leaked on failure"

    async def test_no_tempfile_when_noop(self) -> None:
        """When deps are absent, no temp file is created."""
        toolkit = ContainerSecurityToolkit()  # no persistence kwargs
        _stub_executor_scan_filesystem(toolkit)

        with patch("tempfile.NamedTemporaryFile") as ntf:
            await toolkit.trivy_scan_filesystem(path="/app")
        ntf.assert_not_called()

    async def test_return_shape_unchanged(self) -> None:
        """Scan methods still return ScanResult even with persistence active."""
        from parrot_tools.security.models import ScanResult
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(file_manager=fm, report_store=store)
        _stub_executor_scan_image(toolkit)

        with patch.object(toolkit, "_persist_report", new=AsyncMock()):
            result = await toolkit.trivy_scan_image(image="nginx:latest")
        assert isinstance(result, ScanResult)
