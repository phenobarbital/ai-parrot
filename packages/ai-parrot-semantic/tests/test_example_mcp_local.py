"""Regression contract: the MCP-local allow/deny example (FEAT-769 M4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.errors import SemanticAccessError

pytest.importorskip("duckdb")
pytest.importorskip("navigator_auth.abac.policies.evaluator")
pytest.importorskip("navigator_auth.abac.policies.environment")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "mcp_local_agent.py"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the skip checks."""
    spec = importlib.util.spec_from_file_location("semantic_mcp_local_example", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.mark.asyncio
async def test_smoke_runs_both_decisions(example: ModuleType) -> None:
    """Spec AC5: a real allow returns a result AND a real deny raises."""
    summary = await example.smoke()
    assert "SELECT" in summary["allow"]["sql"]
    assert summary["deny"] == "denied"


@pytest.mark.asyncio
async def test_deny_raises_through_the_real_factory(example: ModuleType, tmp_path: Path) -> None:
    """The deny decision raises SemanticAccessError from an actual tool execution."""
    sys.modules[example.FACTORY_MODULE] = example
    try:
        policy_dir = tmp_path / "deny-policy"
        policy_dir.mkdir()
        (policy_dir / "decisions.json").write_text('{"allow": false}', encoding="utf-8")
        config = example.write_toolkit_config(
            tmp_path / "config",
            models=example._common.MODELS_DIR,
            policy_dir=policy_dir,
            factory=f"{example.FACTORY_MODULE}.build_guard",
        )
        with pytest.raises(SemanticAccessError, match="PBAC denied"):
            await example.run_decision(config, allow=False)
    finally:
        sys.modules.pop(example.FACTORY_MODULE, None)


@pytest.mark.asyncio
async def test_a_silently_succeeding_deny_fails_the_example(
    example: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec AC7: if the deny stops raising, smoke() must fail rather than pass."""

    async def silently_succeed(config: Path, *, allow: bool) -> dict[str, str]:
        """Return a result for both decisions to simulate a broken deny path."""
        del config, allow
        return {"sql": "SELECT 1"}

    monkeypatch.setattr(example, "run_decision", silently_succeed)
    with pytest.raises(RuntimeError, match="deny unexpectedly succeeded"):
        await example.smoke()


def test_missing_policy_configuration_fails_closed(example: ModuleType, tmp_path: Path) -> None:
    """build_guard refuses to default to allow when decisions.json is absent."""
    from parrot.auth import RlsRegistry

    with pytest.raises(ValueError):
        example.build_guard(rls_registry=RlsRegistry(), policy_dir=str(tmp_path / "missing"))
