"""Unit tests for parrot.integrations.devloop.models (TASK-3200)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from parrot.integrations.devloop.models import DevLoopIntegrationConfig, Requester, RunRecord
from parrot.integrations.slack.models import SlackAgentConfig


def test_config_from_dict_defaults() -> None:
    cfg = DevLoopIntegrationConfig.from_dict("devbot", {"enabled": True, "repo_path": "/srv/x"})
    assert cfg.enabled and cfg.repo_path == "/srv/x" and cfg.max_concurrent_runs is None


def test_config_env_fallback() -> None:
    with patch("parrot.integrations.devloop.models.config") as mock_config:
        mock_config.get.side_effect = lambda key: {"DEVBOT_DEVLOOP_REPO_PATH": "/env/repo"}.get(key)
        cfg = DevLoopIntegrationConfig(name="devbot")
    assert cfg.repo_path == "/env/repo"


def test_config_env_fallback_never_overrides_explicit() -> None:
    with patch("parrot.integrations.devloop.models.config") as mock_config:
        mock_config.get.side_effect = lambda key: {"DEVBOT_DEVLOOP_REPO_PATH": "/env/repo"}.get(key)
        cfg = DevLoopIntegrationConfig(name="devbot", repo_path="/explicit")
    assert cfg.repo_path == "/explicit"


def test_validate_requires_criteria_when_enabled() -> None:
    cfg = DevLoopIntegrationConfig(name="b", enabled=True)
    assert any("default_acceptance_criteria" in e for e in cfg.validate())


def test_validate_passes_when_disabled_with_no_criteria() -> None:
    cfg = DevLoopIntegrationConfig(name="b", enabled=False)
    assert cfg.validate() == []


def test_validate_rejects_disallowed_head() -> None:
    cfg = DevLoopIntegrationConfig(
        name="b",
        enabled=True,
        default_acceptance_criteria=[{"kind": "shell", "name": "x", "command": "rm -rf /"}],
    )
    errors = cfg.validate()
    assert errors
    assert any("rm" in e for e in errors)


def test_validate_accepts_allowlisted_head() -> None:
    cfg = DevLoopIntegrationConfig(
        name="b",
        enabled=True,
        default_acceptance_criteria=[{"kind": "shell", "name": "x", "command": "pytest -q"}],
    )
    assert cfg.validate() == []


def test_requester_actor() -> None:
    assert Requester(transport="slack", tenant_id="T1", user_id="U1").actor == "slack:T1:U1"


def test_run_record_json_roundtrip() -> None:
    record = RunRecord(
        run_id="run-abcd1234",
        kind="feature",
        title="Some feature",
        requester=Requester(transport="slack", tenant_id="T1", user_id="U1"),
        channel_id="C1",
        started_at=time.time(),
    )
    dumped = record.model_dump_json()
    restored = RunRecord.model_validate_json(dumped)
    assert restored == record


def test_slack_config_parses_devloop_section() -> None:
    cfg = SlackAgentConfig.from_dict("devbot", {"chatbot_id": "a", "bot_token": "xoxb", "devloop": {"enabled": True}})
    assert cfg.devloop is not None and cfg.devloop.enabled


def test_slack_config_without_devloop_is_none() -> None:
    assert SlackAgentConfig.from_dict("b", {"chatbot_id": "a", "bot_token": "xoxb"}).devloop is None
