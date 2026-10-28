"""Tests for closeout_builtins (FEAT-764)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.sdd.closeout_builtins import BUILTINS, run_builtin
from scripts.sdd.closeout_hooks_config import HookContext, HookKind, HookSpec


@pytest.fixture
def tmp_spec(tmp_path: Path) -> Path:
    """Create a minimal spec file."""
    spec = tmp_path / "spec.md"
    spec.write_text("""
# Feature Spec

**Jira**: [FEAT-123]

## Overview

Some content.
""", encoding="utf-8")
    return spec


@pytest.fixture
def ctx(tmp_spec: Path) -> HookContext:
    """Default context."""
    return HookContext(
        feat_id="FEAT-123",
        spec_path=str(tmp_spec),
        branch="feat-FEAT-123",
        base_branch="dev",
        worktree=str(tmp_spec.parent / "worktree"),
        pr_url="https://github.com/org/repo/pull/1",
        merge_sha="abc123",
    )


async def _mock_request(method: str, url: str, *, headers: dict | None = None, json_body: Any = None, data: str | None = None, timeout: int = 60) -> tuple[int, Any]:
    """Mock _request for tests."""
    if "jira" in url and "transitions" in url:
        if method == "GET":
            return 200, {
                "transitions": [
                    {"id": "11", "name": "To Do", "to": {"name": "To Do"}},
                    {"id": "21", "name": "Done", "to": {"name": "Done"}},
                ]
            }
        elif method == "POST":
            return 204, {}
    elif "jira" in url and "comment" in url:
        return 201, {}
    elif "telegram" in url:
        return 200, {"ok": True}
    elif "ntfy" in url or "gotify" in url:
        return 200, {}
    elif "webhook" in url:
        return 200, {}
    return 404, "not found"


def test_jira_no_key_skipped(tmp_path: Path, ctx: HookContext):
    """Spec without Jira key → skipped."""
    spec = tmp_path / "no_jira.md"
    spec.write_text("# Spec\nNo Jira key here.", encoding="utf-8")
    ctx.spec_path = str(spec)
    hook = HookSpec(name="jira", kind=HookKind.BUILTIN, builtin="jira.transition", blocking=True)
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_request):
        result = run_builtin(hook, ctx, tmp_path)
    assert result.status == "skipped"
    assert "No Jira key in spec" in result.summary


def test_jira_transition_matches_status_and_comments(tmp_path: Path, ctx: HookContext, monkeypatch):
    """Jira transition matches status and posts comment."""
    monkeypatch.setenv("JIRA_INSTANCE", "https://jira.example.com")
    monkeypatch.setenv("JIRA_USERNAME", "user")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    hook = HookSpec(name="jira", kind=HookKind.BUILTIN, builtin="jira.transition", blocking=True, with_={"status": "Done"})
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_request):
        result = run_builtin(hook, ctx, tmp_path)
    assert result.status == "pass"
    assert "Transitioned" in result.summary


def test_jira_no_matching_transition_fails(tmp_path: Path, ctx: HookContext, monkeypatch):
    """No matching transition → fail listing available names."""
    monkeypatch.setenv("JIRA_INSTANCE", "https://jira.example.com")
    monkeypatch.setenv("JIRA_USERNAME", "user")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")

    async def _mock_no_transition(*args, **kwargs):
        if "transitions" in args[1]:
            return 200, {"transitions": [{"id": "11", "name": "To Do", "to": {"name": "To Do"}}]}
        return 404, ""

    hook = HookSpec(name="jira", kind=HookKind.BUILTIN, builtin="jira.transition", blocking=True, with_={"status": "Done"})
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_no_transition):
        result = run_builtin(hook, ctx, tmp_path)
    assert result.status == "fail"
    assert "No matching transition" in result.summary


def test_telegram_missing_token_skipped(monkeypatch):
    """Missing Telegram token → skipped."""
    monkeypatch.delenv("SDD_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SDD_TELEGRAM_CHAT_ID", raising=False)
    hook = HookSpec(name="tg", kind=HookKind.BUILTIN, builtin="telegram.send", blocking=False)
    ctx = HookContext(feat_id="FEAT-123", spec_path="spec.md", branch="b", base_branch="dev", worktree="w")
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_request):
        result = run_builtin(hook, ctx, Path("/tmp"))
    assert result.status == "skipped"
    assert "Missing Telegram credentials" in result.summary


def test_telegram_payload(monkeypatch):
    """Telegram sends the expected payload."""
    monkeypatch.setenv("SDD_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("SDD_TELEGRAM_CHAT_ID", "123")
    hook = HookSpec(name="tg", kind=HookKind.BUILTIN, builtin="telegram.send", blocking=False, with_={"template": "{feat_id}: {pr_url}"})
    ctx = HookContext(feat_id="FEAT-123", spec_path="spec.md", branch="b", base_branch="dev", worktree="w", pr_url="https://github.com/org/repo/pull/1")
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_request) as mock_req:
        result = run_builtin(hook, ctx, Path("/tmp"))
    assert result.status == "pass"
    assert "Telegram message sent" in result.summary


def test_push_ntfy_request_shape(monkeypatch):
    """ntfy sends the documented URL/headers/body."""
    monkeypatch.setenv("SDD_NTFY_URL", "https://ntfy.sh")
    monkeypatch.setenv("SDD_NTFY_TOPIC", "sdd")
    hook = HookSpec(name="push", kind=HookKind.BUILTIN, builtin="push.send", blocking=False, with_={"provider": "ntfy", "title": "Title", "message": "Msg", "priority": "5"})
    ctx = HookContext(feat_id="FEAT-123", spec_path="spec.md", branch="b", base_branch="dev", worktree="w")
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_request) as mock_req:
        result = run_builtin(hook, ctx, Path("/tmp"))
    assert result.status == "pass"
    assert "ntfy notification sent" in result.summary


def test_push_gotify_request_shape(monkeypatch):
    """gotify sends the documented URL/headers/body."""
    monkeypatch.setenv("SDD_GOTIFY_URL", "https://gotify.example.com")
    hook = HookSpec(name="push", kind=HookKind.BUILTIN, builtin="push.send", blocking=False, with_={"provider": "gotify", "title": "Title", "message": "Msg", "priority": "5"})
    ctx = HookContext(feat_id="FEAT-123", spec_path="spec.md", branch="b", base_branch="dev", worktree="w")
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_request) as mock_req:
        result = run_builtin(hook, ctx, Path("/tmp"))
    assert result.status == "pass"
    assert "gotify notification sent" in result.summary


def test_webhook_posts_context(monkeypatch):
    """Webhook POSTs the JSON context."""
    monkeypatch.setenv("SDD_WEBHOOK_URL", "https://webhook.site/abc")
    hook = HookSpec(name="wh", kind=HookKind.BUILTIN, builtin="webhook.post", blocking=False)
    ctx = HookContext(feat_id="FEAT-123", spec_path="spec.md", branch="b", base_branch="dev", worktree="w", pr_url="https://github.com/org/repo/pull/1")
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_request) as mock_req:
        result = run_builtin(hook, ctx, Path("/tmp"))
    assert result.status == "pass"
    assert "Webhook POST successful" in result.summary


def test_non_2xx_is_fail(monkeypatch):
    """Non-2xx status → fail."""
    async def _mock_500(*args, **kwargs):
        return 500, "error"

    monkeypatch.setenv("SDD_WEBHOOK_URL", "https://webhook.site/abc")
    hook = HookSpec(name="wh", kind=HookKind.BUILTIN, builtin="webhook.post", blocking=False)
    ctx = HookContext(feat_id="FEAT-123", spec_path="spec.md", branch="b", base_branch="dev", worktree="w")
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_500):
        result = run_builtin(hook, ctx, Path("/tmp"))
    assert result.status == "fail"
    assert "failed: HTTP 500" in result.summary


def test_run_builtin_exception_becomes_fail(monkeypatch):
    """Unexpected exception → fail with type name."""
    async def _mock_error(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setenv("SDD_WEBHOOK_URL", "https://webhook.site/abc")
    hook = HookSpec(name="wh", kind=HookKind.BUILTIN, builtin="webhook.post", blocking=False)
    ctx = HookContext(feat_id="FEAT-123", spec_path="spec.md", branch="b", base_branch="dev", worktree="w")
    with patch("scripts.sdd.closeout_builtins._request", side_effect=_mock_error):
        result = run_builtin(hook, ctx, Path("/tmp"))
    assert result.status == "fail"
    assert "ValueError" in result.summary
