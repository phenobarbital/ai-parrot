"""Regression contract: MCP-local identity and configured PBAC bootstrap (M10c)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.semantic.bootstrap import LocalSemanticLayerToolkit
import parrot.semantic.bootstrap as bootstrap
from parrot.semantic.context import current_identity, current_pctx
from parrot.semantic.errors import SemanticAccessError, SemanticPolicyError
from parrot.semantic.models import SemanticQuery

from . import _guard_factory
from ._models import models_dir  # noqa: F401

sys.modules.setdefault("semantic_test_guard_factory", _guard_factory)


def _write_policy(path: Path, *, allow: bool) -> Path:
    """Write a deterministic local PBAC fixture policy."""
    path.mkdir()
    (path / "decisions.json").write_text(json.dumps({"allow": allow}), encoding="utf-8")
    return path


def _kwargs(models_dir: Path, policy_dir: Path) -> dict[str, object]:
    """Return the only trusted configuration accepted by the local toolkit."""
    return {
        "models_dir": str(models_dir),
        "dialect": "duckdb",
        "agent_id": "local-semantic",
        "static_subject": {"user_id": "operator", "tenant_id": "local", "roles": ["admin"]},
        "guard_factory": "semantic_test_guard_factory.build_guard",
        "guard_factory_kwargs": {"policy_dir": str(policy_dir)},
    }


@pytest.mark.asyncio
async def test_configured_factory_governed_allow_deny(tmp_path: Path, models_dir: Path) -> None:
    """Construct actual MCP toolkits and enforce explicit allow and deny policies."""
    root = tmp_path / "mcp"
    root.mkdir()
    allow_policy = _write_policy(tmp_path / "allow", allow=True)
    config = root / "toolkits.yaml"
    config.write_text(
        "toolkits:\n  semantic-layer:\n    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit\n    kwargs: "
        + json.dumps(_kwargs(models_dir, allow_policy))
        + "\n",
        encoding="utf-8",
    )
    server = create_toolkit_mcp_server("semantic-layer", root=root, config_path=config)
    toolkit = server._owned_toolkit
    tool = toolkit.get_tool("sl_compile_query")
    assert tool is not None
    allowed = await tool._execute(query=SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))
    assert "SELECT" in allowed["sql"]
    assert toolkit._ledger.entries[-1].static_subject is True
    assert toolkit._ledger.entries[-1].channel == "mcp-local"

    denied_toolkit = LocalSemanticLayerToolkit(**_kwargs(models_dir, _write_policy(tmp_path / "deny", allow=False)))
    denied_tool = denied_toolkit.get_tool("sl_compile_query")
    assert denied_tool is not None
    with pytest.raises(SemanticAccessError, match="PBAC denied"):
        await denied_tool._execute(query=SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))


def test_missing_invalid_factory_fails_closed(
    tmp_path: Path, models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject absent factories, invalid returns, and policy-load failures at startup."""
    policy_dir = _write_policy(tmp_path / "policy", allow=True)
    kwargs = _kwargs(models_dir, policy_dir)
    with pytest.raises(TypeError):
        LocalSemanticLayerToolkit(**{key: value for key, value in kwargs.items() if key != "guard_factory"})

    with pytest.raises(SemanticPolicyError) as invalid:
        LocalSemanticLayerToolkit(**{**kwargs, "guard_factory": "semantic_test_invalid_factory.build_guard"})
    assert invalid.value.code == "invalid_policy_guard"

    with pytest.raises(SemanticPolicyError) as failed:
        LocalSemanticLayerToolkit(**{**kwargs, "guard_factory_kwargs": {"policy_dir": str(tmp_path / "missing")}})
    assert failed.value.code == "guard_factory_failed"

    real_import = bootstrap.importlib.import_module

    def unavailable(module_name: str) -> ModuleType:
        """Simulate a missing mandatory navigator-auth evaluator module."""
        if module_name == "navigator_auth.abac.policies.evaluator":
            raise ModuleNotFoundError(module_name)
        return real_import(module_name)

    monkeypatch.setattr(bootstrap.importlib, "import_module", unavailable)
    with pytest.raises(SemanticPolicyError) as unavailable_error:
        LocalSemanticLayerToolkit(**kwargs)
    assert unavailable_error.value.code == "pbac_unavailable"


def _invalid_guard(*args: object, **kwargs: object) -> object:
    """Return an invalid value to prove startup validates factory results."""
    del args, kwargs
    return object()


_INVALID_FACTORY_MODULE = ModuleType("semantic_test_invalid_factory")
_INVALID_FACTORY_MODULE.build_guard = _invalid_guard
sys.modules.setdefault("semantic_test_invalid_factory", _INVALID_FACTORY_MODULE)


@pytest.mark.asyncio
async def test_local_only_identity_and_wrapper_cleanup(tmp_path: Path, models_dir: Path) -> None:
    """Ignore caller identity, retain a fixed local scope, and reset after failure."""
    toolkit = LocalSemanticLayerToolkit(**_kwargs(models_dir, _write_policy(tmp_path / "policy", allow=True)))
    tool = toolkit.get_tool("sl_compile_query")
    assert tool is not None
    supplied = PermissionContext(UserSession("attacker", "other", frozenset({"admin"})))
    result = await tool._execute(
        query=SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]),
        _permission_context=supplied,
    )
    assert result["audit_id"] == toolkit._ledger.entries[-1].entry_id
    assert toolkit._ledger.entries[-1].user_id == "operator"
    assert current_pctx() is None
    assert current_identity() is None
    with pytest.raises(SemanticAccessError):
        await toolkit.compile_query(SemanticQuery(model="orders", metrics=["revenue"]))
