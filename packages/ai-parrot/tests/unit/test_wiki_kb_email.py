"""Unit tests for the email digest node (FEAT-481, spec Module 15 /
TASK-2674): flag-gated send, compiled-content-only.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest import conf
from parrot.flows.wiki_ingest.nodes.email import build_digest_content, run_email_digest
from parrot.tools.obsidian import ObsidianToolkit


def _toolkit(vault_path: Path) -> ObsidianToolkit:
    return ObsidianToolkit(
        vault_path=str(vault_path),
        allowed_operations={"read", "list", "search", "create", "update", "move", "delete"},
    )


def _write_daily_note(vault_path: Path, day: str, summary: str) -> None:
    daily_dir = vault_path / "Diary" / "Daily Notes"
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / f"{day}.md").write_text(
        f"---\nid: daily:{day}\n---\n\n# {day} Daily Notes\n\n## Daily Summary\n{summary}\n\n"
        "## Project Updates\nNone identified\n",
        encoding="utf-8",
    )


def _fake_agent(*, send_result: dict | None = None) -> AsyncMock:
    agent = AsyncMock()
    agent.send_email = AsyncMock(return_value=send_result if send_result is not None else {"status": "success"})
    agent.notification_succeeded = lambda result: (result or {}).get("status") == "success"
    return agent


@pytest.mark.asyncio
async def test_email_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Digests do not send unless FIREFLIES_WIKI_EMAIL_ENABLED=true."""
    monkeypatch.setattr(conf, "FIREFLIES_WIKI_EMAIL_ENABLED", False)
    _write_daily_note(tmp_path, "2026-08-20", "Acme progressed the rollout.")
    toolkit = _toolkit(tmp_path)
    agent = _fake_agent()

    outcome = await run_email_digest(
        agent, toolkit, kind="daily", window_days=1, recipients=["ops@example.com"], today=date(2026, 8, 20)
    )

    assert outcome.status == "skipped"
    assert outcome.emailed is False
    assert "FIREFLIES_WIKI_EMAIL_ENABLED" in outcome.reason
    agent.send_email.assert_not_called()


@pytest.mark.asyncio
async def test_email_sends_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "FIREFLIES_WIKI_EMAIL_ENABLED", True)
    _write_daily_note(tmp_path, "2026-08-20", "Acme progressed the rollout.")
    toolkit = _toolkit(tmp_path)
    agent = _fake_agent()

    outcome = await run_email_digest(
        agent, toolkit, kind="daily", window_days=1, recipients=["ops@example.com"], today=date(2026, 8, 20)
    )

    assert outcome.status == "ok"
    assert outcome.emailed is True
    assert outcome.days_covered == 1
    agent.send_email.assert_called_once()
    _, kwargs = agent.send_email.call_args
    assert "Acme progressed the rollout." in kwargs["message"]


@pytest.mark.asyncio
async def test_email_skips_when_no_recipients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "FIREFLIES_WIKI_EMAIL_ENABLED", True)
    _write_daily_note(tmp_path, "2026-08-20", "Acme progressed the rollout.")
    toolkit = _toolkit(tmp_path)
    agent = _fake_agent()

    outcome = await run_email_digest(
        agent, toolkit, kind="daily", window_days=1, recipients=[], today=date(2026, 8, 20)
    )

    assert outcome.status == "skipped"
    assert outcome.reason == "no recipients configured"
    agent.send_email.assert_not_called()


@pytest.mark.asyncio
async def test_email_skips_when_no_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "FIREFLIES_WIKI_EMAIL_ENABLED", True)
    toolkit = _toolkit(tmp_path)
    agent = _fake_agent()

    outcome = await run_email_digest(
        agent, toolkit, kind="daily", window_days=1, recipients=["ops@example.com"], today=date(2026, 8, 20)
    )

    assert outcome.status == "skipped"
    assert outcome.reason == "no daily-note content in the window"
    agent.send_email.assert_not_called()


@pytest.mark.asyncio
async def test_digest_content_derives_from_compiled_daily_notes_not_raw(tmp_path: Path) -> None:
    """Content comes from Diary/Daily Notes/ (compiled), never Raw/."""
    _write_daily_note(tmp_path, "2026-08-19", "Day one synthesis.")
    _write_daily_note(tmp_path, "2026-08-20", "Day two synthesis.")
    raw_dir = tmp_path / "Raw" / "Processed" / "Uncategorized" / "id-1"
    raw_dir.mkdir(parents=True)
    (raw_dir / "transcript.md").write_text("RAW TRANSCRIPT TEXT — must never appear", encoding="utf-8")
    toolkit = _toolkit(tmp_path)

    body, days_covered = await build_digest_content(toolkit, window_days=2, today=date(2026, 8, 20))

    assert days_covered == 2
    assert "Day one synthesis." in body
    assert "Day two synthesis." in body
    assert "RAW TRANSCRIPT TEXT" not in body


@pytest.mark.asyncio
async def test_email_partial_when_send_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "FIREFLIES_WIKI_EMAIL_ENABLED", True)
    _write_daily_note(tmp_path, "2026-08-20", "Acme progressed the rollout.")
    toolkit = _toolkit(tmp_path)
    agent = _fake_agent(send_result={"status": "error", "error": "SMTP down"})

    outcome = await run_email_digest(
        agent, toolkit, kind="weekly", window_days=1, recipients=["ops@example.com"], today=date(2026, 8, 20)
    )

    assert outcome.status == "partial"
    assert outcome.emailed is False
    assert outcome.reason == "SMTP down"
