"""Regression cases for FEAT-627."""

import json
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.identity as subject
from parrot.knowledge.wiki.project import StandupConfig


@pytest.mark.asyncio
async def test_identity_precedence_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify configured identity wins and a valid cache is used next."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    configured = StandupConfig.model_validate(
        {
            "me": {
                "wiki": "human:configured",
                "jira_account_id": "configured-id",
                "jira_display_name": "Configured Name",
                "aliases": ["configured-alias"],
            }
        }
    )
    result = await subject.resolve_identity(configured, explicit="human:explicit", root=tmp_path)
    assert result.wiki == "human:configured"
    assert result.jira_account_id == "configured-id"
    assert result.jira_display_name == "Configured Name"
    assert result.aliases == ["configured-alias"]

    cache = tmp_path / "jira_identity.json"
    cache.write_text(
        json.dumps(
            {
                "account_id": "cache-id",
                "display_name": "Cached Name",
                "resolved_at": "2026-10-03T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    cached = await subject.resolve_identity(StandupConfig(), explicit="human:explicit", root=tmp_path)
    assert cached.wiki == "human:explicit"
    assert cached.jira_account_id == "cache-id"
    assert cached.jira_display_name == "Cached Name"

    cache.unlink()

    class _Person:
        """G9-safe Jira result."""

        account_id = "probed-id"
        display_name = "Probed Name"

    class _Jira:
        """Configured Jira stub without transport access."""

        auth_type = "token_auth"

        async def myself(self) -> _Person:
            """Return a safe identity projection."""
            return _Person()

    import parrot.interfaces.jira as jira

    monkeypatch.setattr(jira, "JiraInterface", _Jira)
    probed = await subject.resolve_identity(StandupConfig(), explicit="human:explicit", root=tmp_path)
    assert probed.jira_account_id == "probed-id"
    assert probed.jira_display_name == "Probed Name"
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert set(payload) == {"account_id", "display_name", "resolved_at"}
    assert payload["account_id"] == "probed-id"
    assert payload["display_name"] == "Probed Name"


@pytest.mark.asyncio
async def test_g9_and_offline_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify cache corruption and missing credentials retain wiki-only identity."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    (tmp_path / "jira_identity.json").write_text('{"email":"unsafe@example.test"}', encoding="utf-8")

    class _OfflineJira:
        """Unconfigured Jira stub: no credentials, no transport."""

        auth_type = None

    import parrot.interfaces.jira as jira

    monkeypatch.setattr(jira, "JiraInterface", _OfflineJira)
    result = await subject.resolve_identity(StandupConfig(), explicit="human:offline", root=tmp_path)
    assert result.model_dump() == {
        "wiki": "human:offline",
        "jira_account_id": None,
        "jira_display_name": None,
        "aliases": [],
    }


def test_authoring_compatibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify authoring helper remains available under the CLI import name."""
    assert tmp_path.exists()
    monkeypatch.delenv("CLAUDE_AGENT_ID", raising=False)
    monkeypatch.setenv("PARROT_AGENT_ID", "worker-7")
    from parrot.knowledge.wiki.cli import _authoring_identity

    assert _authoring_identity("human:given") == "human:given"
    assert _authoring_identity(None) == "agent:worker-7"
    assert subject.authoring_identity(None) == "agent:worker-7"
