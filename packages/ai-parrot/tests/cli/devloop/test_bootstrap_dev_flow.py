"""FEAT-555 TASK-3197 — topology-aware preflight, build_dev_flow_runtime, load_headless_brief."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import parrot.cli.devloop.bootstrap as bootstrap_mod
from parrot.cli.devloop.bootstrap import DevFlowRuntime, load_headless_brief, preflight

_JIRA_KEYS = {"JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN"}


@pytest.mark.asyncio
async def test_preflight_dev_flow_jira_advisory(monkeypatch):
    import parrot.conf as real_conf

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key == "REDIS_URL":
            return "redis://localhost:6379/0"
        if key in _JIRA_KEYS:
            return ""
        return original_get(key, fallback=fallback)

    for key in _JIRA_KEYS:
        monkeypatch.setattr(real_conf, key, "", raising=False)
    monkeypatch.setattr(real_conf, "REDIS_URL", "redis://localhost:6379/0", raising=False)
    monkeypatch.setattr(real_conf.config, "get", fake_get)
    monkeypatch.setattr(bootstrap_mod, "_redis_ping", AsyncMock(return_value=(True, "")))
    with patch.object(bootstrap_mod, "shutil") as mock_shutil:
        mock_shutil.which.return_value = "/usr/bin/claude"
        result = await preflight(topology="dev_flow")

    assert result.ok is True
    jira_check = next(c for c in result.checks if c.name == "jira")
    assert jira_check.passed is True
    assert jira_check.hint.startswith("(advisory")


@pytest.mark.asyncio
async def test_preflight_dev_loop_jira_hard(monkeypatch):
    import parrot.conf as real_conf

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key in _JIRA_KEYS:
            return ""
        return original_get(key, fallback=fallback)

    for key in _JIRA_KEYS:
        monkeypatch.setattr(real_conf, key, "", raising=False)
    monkeypatch.setattr(real_conf.config, "get", fake_get)
    monkeypatch.setattr(bootstrap_mod, "_redis_ping", AsyncMock(return_value=(True, "")))
    with patch.object(bootstrap_mod, "shutil") as mock_shutil:
        mock_shutil.which.return_value = "/usr/bin/claude"
        result = await preflight(topology="dev_loop")

    jira_check = next(c for c in result.checks if c.name == "jira")
    assert jira_check.passed is False
    assert result.ok is False


@pytest.mark.asyncio
async def test_preflight_redis_ping_failure_fails_both(monkeypatch):
    import parrot.conf as real_conf

    monkeypatch.setattr(real_conf, "JIRA_URL", "https://jira.example.com", raising=False)
    monkeypatch.setattr(real_conf, "JIRA_USERNAME", "user", raising=False)
    monkeypatch.setattr(real_conf, "JIRA_API_TOKEN", "token", raising=False)
    monkeypatch.setattr(bootstrap_mod, "_redis_ping", AsyncMock(return_value=(False, "no PONG")))
    with patch.object(bootstrap_mod, "shutil") as mock_shutil:
        mock_shutil.which.return_value = "/usr/bin/claude"
        result_loop = await preflight(topology="dev_loop")
        result_flow = await preflight(topology="dev_flow")

    assert result_loop.ok is False
    assert result_flow.ok is False


@pytest.mark.asyncio
async def test_build_dev_flow_runtime_wiring():
    ok = bootstrap_mod.PreflightResult(ok=True, checks=[])
    with (
        patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok)),
        patch.object(bootstrap_mod, "_build_jira_toolkit", return_value=None),
        patch.object(bootstrap_mod, "_build_git_toolkit", return_value=None),
        patch.object(bootstrap_mod, "_build_wiki_toolkit", return_value=None),
        patch("parrot.flows.dev_flow.flow.build_dev_flow") as build,
        patch("parrot.flows.dev_flow.runner.DevFlowRunner") as runner_cls,
        patch("parrot.flows.dev_loop.agent_builder.build_dispatcher", return_value=(MagicMock(), MagicMock())),
        patch("parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config", AsyncMock(return_value=None)),
        patch("parrot.flows.dev_loop.wiki_search.DevLoopWikiSearch.from_project", return_value=None),
    ):
        rt = await bootstrap_mod.build_dev_flow_runtime()

    assert isinstance(rt, DevFlowRuntime)
    kwargs = build.call_args.kwargs
    assert kwargs["codereview_dispatcher"] is None
    assert kwargs["name"] == "dev-flow-headless"
    assert runner_cls.call_args.kwargs["dev_loop_flow_kwargs"] is rt.dev_loop_flow_kwargs


def test_load_headless_brief_routes_on_kind(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"kind": "new_feature", "title": "t", "description": "d"}))
    assert type(load_headless_brief(str(f))).__name__ == "DevRequestBrief"

    f.write_text(json.dumps({"kind": "nope"}))
    with pytest.raises(ValueError):
        load_headless_brief(str(f))

    f.write_text(json.dumps({"kind": "enhancement", "title": "t", "description": "d"}))
    assert type(load_headless_brief(str(f))).__name__ == "DevRequestBrief"

    doc = tmp_path / "doc.md"
    doc.write_text("# Doc", encoding="utf-8")
    f.write_text(json.dumps({"kind": "feature", "document_path": str(doc), "document_kind": "brainstorm"}))
    assert type(load_headless_brief(str(f))).__name__ == "FeatureBrief"

    f.write_text(
        json.dumps(
            {
                "kind": "bug",
                "summary": "slack devloop bug",
                "affected_component": "ai-parrot",
                "acceptance_criteria": [{"kind": "shell", "name": "unit", "command": "pytest -q"}],
                "escalation_assignee": "alice",
                "reporter": "bob",
            }
        )
    )
    assert type(load_headless_brief(str(f))).__name__ == "WorkBrief"


def test_load_headless_brief_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_headless_brief(str(tmp_path / "nope.json"))


def test_load_headless_brief_yaml(tmp_path):
    import yaml

    f = tmp_path / "b.yaml"
    f.write_text(yaml.safe_dump({"kind": "new_feature", "title": "t", "description": "d"}))
    assert type(load_headless_brief(str(f))).__name__ == "DevRequestBrief"
