"""FEAT-713 M9 — scheduler adapter."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from parrot.scheduler.accounting_jobs import AccountingValidationJobs, register_accounting_schedules
from parrot.scheduler.base import SchedulerManager


async def test_register_accounting_schedules(scheduler_namespace: str) -> None:
    """Exactly one daily job is registered under the expected id."""
    manager = SchedulerManager(registered_name=scheduler_namespace)
    try:
        assert register_accounting_schedules(manager, lambda: object()) == 1
        assert "auto_accounting_validate_accounting_models" in manager._code_jobs
    finally:
        await manager.stop_headless(wait=False)


async def test_job_uses_same_toolkit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The job passes the factory's instance to run_live_validation and returns a dict."""
    live = pytest.importorskip("parrot.semantic.accounting.live")
    toolkit = object()
    seen: list[object] = []

    class _Report:
        models = ()

        def model_dump(self, mode: str = "python") -> dict:
            return {"models": []}

    async def fake(tk: object) -> _Report:
        seen.append(tk)
        return _Report()

    monkeypatch.setattr(live, "run_live_validation", fake)
    result = await AccountingValidationJobs(lambda: toolkit).validate_accounting_models()
    assert seen == [toolkit]
    assert result == {"models": []}


def test_module_imports_without_semantic() -> None:
    """Importing the adapter does not import parrot.semantic."""
    code = (
        "import sys; import parrot.scheduler.accounting_jobs; "
        "print('LEAK' if any(m == 'parrot.semantic' or m.startswith('parrot.semantic.') for m in sys.modules) else 'OK')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == "OK"
