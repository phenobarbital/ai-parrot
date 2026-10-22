"""Tests for structured logging in LSPToolkit (FEAT-658 TASK-4272)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from parrot_tools.lsp.models import LSPConfig, LSPFailure
from parrot_tools.lsp.toolkit import LSPToolkit


@pytest.fixture
def toolkit(tmp_path: Path) -> LSPToolkit:
    return LSPToolkit(LSPConfig(repo_root=tmp_path, environment_id="env-1"))


async def test_open_logs_debug(toolkit: LSPToolkit, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        await toolkit._open()
    assert any(r.levelno == logging.DEBUG and "opened" in r.getMessage() for r in caplog.records)


async def test_close_logs_debug(toolkit: LSPToolkit, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        await toolkit._close()
    assert any(r.levelno == logging.DEBUG and "Closing LSP session" in r.getMessage() for r in caplog.records)


def test_failure_result_logs_warning(toolkit: LSPToolkit, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        toolkit._failure_result("lsp_diagnostics", LSPFailure("workspace_changed", "boom"))
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("lsp_diagnostics" in m and "workspace_changed" in m and "boom" in m for m in msgs)


def test_uri_for_path_uses_canonical_root(toolkit: LSPToolkit, tmp_path: Path) -> None:
    toolkit._canonical_root = tmp_path.resolve()
    assert toolkit._uri_for_path("a.py").endswith("/a.py")
