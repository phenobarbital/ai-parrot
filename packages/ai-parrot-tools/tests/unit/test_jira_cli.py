"""Tests for the Jira CLI (FEAT-696 M5)."""

from __future__ import annotations

import re
import stat
import time
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from parrot.auth.jira_oauth import JiraTokenSet
from parrot_tools import jira_cli
from parrot_tools.jira_cli import cli, parse_pasted_redirect, upsert_env
from parrot_tools.jira_kb import JiraKnowledgeBase, LimitsEntry, PrioritiesEntry

REDIRECT_URI = "http://localhost:8080/callback"
SITE_A = {"id": "cloud-a", "url": "https://acme.atlassian.net", "name": "Acme", "scopes": []}
SITE_B = {"id": "cloud-b", "url": "https://beta.atlassian.net", "name": "Beta", "scopes": []}
TOKEN_DATA = {
    "access_token": "ACCESS-SECRET-VALUE",
    "refresh_token": "REFRESH-SECRET-VALUE",
    "expires_in": 3600,
    "scope": "read:jira-work offline_access",
}
MYSELF = {"accountId": "acc-1", "displayName": "Jesus Lara", "emailAddress": "jesus@example.com"}
CLIENT_SECRET = "client-secret-value"
FIXED_STATE = "fixed-state-nonce"


@pytest.fixture
def settings_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the local token store at a temporary file and clear Jira env vars."""
    path = tmp_path / "jira" / "settings.local.json"
    monkeypatch.setenv("JIRA_LOCAL_SETTINGS", str(path))
    for name in ("JIRA_CLIENT_ID", "JIRA_CLIENT_SECRET", "JIRA_REDIRECT_URI", "JIRA_KB_PATH", "JIRA_LOCAL_SITE"):
        monkeypatch.delenv(name, raising=False)
    return path


@pytest.fixture
def fake_network(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the network helpers used by ``auth`` with in-memory fakes."""
    state: dict[str, Any] = {"resources": [SITE_A], "exchange_calls": [], "myself_calls": []}

    async def _exchange(client_id: str, client_secret: str, code: str, redirect_uri: str):
        state["exchange_calls"].append((client_id, client_secret, code, redirect_uri))
        return dict(TOKEN_DATA), list(state["resources"])

    async def _myself(access_token: str, cloud_id: str) -> dict[str, Any]:
        state["myself_calls"].append((access_token, cloud_id))
        return dict(MYSELF)

    monkeypatch.setattr(jira_cli, "_new_state", lambda: FIXED_STATE)
    monkeypatch.setattr(jira_cli, "_exchange_and_list", _exchange)
    monkeypatch.setattr(jira_cli, "_myself", _myself)
    return state


def _auth_args(env_file: Path, *extra: str) -> list[str]:
    return [
        "auth",
        "--client-id",
        "client-id-value",
        "--client-secret",
        CLIENT_SECRET,
        "--redirect-uri",
        REDIRECT_URI,
        "--env-file",
        str(env_file),
        *extra,
    ]


def _state_from_output(output: str) -> str:
    match = re.search(r"state=([^&\s]+)", output)
    assert match, output
    return match.group(1)


def _make_token(site_url: str = SITE_A["url"], cloud_id: str = SITE_A["id"]) -> JiraTokenSet:
    now = time.time()
    return JiraTokenSet(
        access_token="ACCESS-SECRET-VALUE",
        refresh_token="REFRESH-SECRET-VALUE",
        expires_at=now + 3600,
        cloud_id=cloud_id,
        site_url=site_url,
        account_id="acc-1",
        display_name="Jesus Lara",
        email="jesus@example.com",
        scopes=["read:jira-work"],
        granted_at=now,
        last_refreshed_at=now,
    )


class TestParseRedirect:
    def test_url_with_code_and_state(self):
        code, state = parse_pasted_redirect("http://localhost/cb?code=abc&state=xyz")
        assert code == "abc"
        assert state == "xyz"

    def test_bare_code(self):
        code, state = parse_pasted_redirect("abc123")
        assert code == "abc123"
        assert state is None

    def test_error_redirect_raises(self):
        with pytest.raises(click.ClickException, match="Authorization denied: access_denied"):
            parse_pasted_redirect("http://localhost/cb?error=access_denied")

    def test_state_mismatch_is_returned_for_caller_to_check(self):
        code, state = parse_pasted_redirect("http://localhost/cb?code=abc&state=wrong")
        assert code == "abc"
        assert state == "wrong"


class TestUpsertEnv:
    def test_replaces_existing_line_in_place(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("# header\nFOO=1\nJIRA_CLIENT_ID=old\nBAR=2\n", encoding="utf-8")
        upsert_env(env, {"JIRA_CLIENT_ID": "new"})
        assert env.read_text(encoding="utf-8") == "# header\nFOO=1\nJIRA_CLIENT_ID=new\nBAR=2\n"

    def test_appends_new_key(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("FOO=1", encoding="utf-8")
        upsert_env(env, {"JIRA_AUTH_TYPE": "oauth2_local"})
        assert env.read_text(encoding="utf-8") == "FOO=1\nJIRA_AUTH_TYPE=oauth2_local\n"

    def test_quotes_values_with_hash_and_spaces(self, tmp_path: Path):
        env = tmp_path / ".env"
        upsert_env(env, {"JIRA_CLIENT_SECRET": "abc#def", "JIRA_REDIRECT_URI": "a b"})
        content = env.read_text(encoding="utf-8")
        assert "JIRA_CLIENT_SECRET='abc#def'\n" in content
        assert "JIRA_REDIRECT_URI='a b'\n" in content

    def test_keeps_export_prefix_and_unrelated_lines(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("export JIRA_CLIENT_ID=old\n# keep me\nOTHER=x\n", encoding="utf-8")
        upsert_env(env, {"JIRA_CLIENT_ID": "new"})
        assert env.read_text(encoding="utf-8") == "export JIRA_CLIENT_ID=new\n# keep me\nOTHER=x\n"

    def test_new_file_is_created_with_mode_0600(self, tmp_path: Path):
        env = tmp_path / "nested" / ".env"
        upsert_env(env, {"JIRA_CLIENT_SECRET": "s"})
        assert env.exists()
        assert stat.S_IMODE(env.stat().st_mode) == 0o600


class TestCliHelp:
    def test_jiratoolkit_help_lists_subcommands(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        for name in ("auth", "status", "logout", "sync-kb"):
            assert name in result.output

    def test_lazy_command_resolves_through_parrot_cli(self):
        from parrot.cli import cli as parrot_cli

        assert parrot_cli._lazy_commands["jiratoolkit"] == "parrot_tools.jira_cli"
        result = CliRunner().invoke(parrot_cli, ["jiratoolkit", "--help"])
        assert result.exit_code == 0, result.output
        assert "auth" in result.output


class TestAuthCommand:
    def test_state_mismatch_aborts_without_saving(self, settings_path, fake_network, tmp_path):
        env = tmp_path / ".env"
        runner = CliRunner()
        result = runner.invoke(cli, _auth_args(env), input=f"{REDIRECT_URI}?code=abc&state=wrong-state\n")
        assert result.exit_code != 0
        assert "State mismatch" in result.output
        assert not settings_path.exists()
        assert not env.exists()
        assert fake_network["exchange_calls"] == []

    def test_url_without_state_aborts(self, settings_path, fake_network, tmp_path):
        result = CliRunner().invoke(cli, _auth_args(tmp_path / ".env"), input=f"{REDIRECT_URI}?code=abc\n")
        assert result.exit_code != 0
        assert not settings_path.exists()

    def test_error_redirect_aborts(self, settings_path, fake_network, tmp_path):
        result = CliRunner().invoke(cli, _auth_args(tmp_path / ".env"), input=f"{REDIRECT_URI}?error=access_denied\n")
        assert result.exit_code != 0
        assert "access_denied" in result.output
        assert fake_network["exchange_calls"] == []

    def test_bare_code_rejected_by_default(self, settings_path, fake_network, tmp_path):
        result = CliRunner().invoke(cli, _auth_args(tmp_path / ".env"), input="bare-code-123\n")
        assert result.exit_code != 0
        assert "full redirected URL" in result.output
        assert fake_network["exchange_calls"] == []

    def test_bare_code_accepted_only_with_flag(self, settings_path, fake_network, tmp_path):
        env = tmp_path / ".env"
        result = CliRunner().invoke(cli, _auth_args(env, "--allow-bare-code"), input="bare-code-123\n")
        assert result.exit_code == 0, result.output
        assert "without a state check" in result.output
        assert fake_network["exchange_calls"][0][2] == "bare-code-123"
        assert LocalStoreHelper.load_default(settings_path).cloud_id == SITE_A["id"]

    def test_client_secret_flag_warns(self, settings_path, fake_network, tmp_path):
        result = CliRunner().invoke(cli, _auth_args(tmp_path / ".env"), input="\n")
        assert "--client-secret exposes the secret" in result.output

    def test_pasted_url_with_matching_state_saves_everything(self, settings_path, fake_network, tmp_path):
        env = tmp_path / ".env"
        runner = CliRunner()
        first = runner.invoke(cli, _auth_args(env), input="\n")
        state = _state_from_output(first.output)
        result = runner.invoke(cli, _auth_args(env), input=f"{REDIRECT_URI}?code=abc&state={state}\n")
        assert result.exit_code == 0, result.output
        assert "Site:" in result.output and SITE_A["url"] in result.output
        assert "Jesus Lara" in result.output
        assert "Expires:" in result.output
        # Secrets never reach the terminal.
        assert "ACCESS-SECRET-VALUE" not in result.output
        assert "REFRESH-SECRET-VALUE" not in result.output
        assert CLIENT_SECRET not in result.output
        # Tokens live only in the settings file, mode 0600.
        assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
        stored = LocalStoreHelper.load_default(settings_path)
        assert stored.refresh_token == "REFRESH-SECRET-VALUE"
        # Client settings land in .env.
        env_text = env.read_text(encoding="utf-8")
        assert "JIRA_CLIENT_ID=client-id-value\n" in env_text
        assert f"JIRA_CLIENT_SECRET={CLIENT_SECRET}\n" in env_text
        assert f"JIRA_REDIRECT_URI={REDIRECT_URI}\n" in env_text
        assert "JIRA_AUTH_TYPE=oauth2_local\n" in env_text

    def test_multi_site_choice_selects_second_site(self, settings_path, fake_network, tmp_path):
        fake_network["resources"] = [SITE_A, SITE_B]
        runner = CliRunner()
        first = runner.invoke(cli, _auth_args(tmp_path / ".env"), input="\n")
        state = _state_from_output(first.output)
        result = runner.invoke(cli, _auth_args(tmp_path / ".env"), input=f"{REDIRECT_URI}?code=abc&state={state}\n2\n")
        assert result.exit_code == 0, result.output
        assert LocalStoreHelper.load_default(settings_path).site_url == SITE_B["url"]

    def test_invalid_site_choice_aborts(self, settings_path, fake_network, tmp_path):
        fake_network["resources"] = [SITE_A, SITE_B]
        runner = CliRunner()
        first = runner.invoke(cli, _auth_args(tmp_path / ".env"), input="\n")
        state = _state_from_output(first.output)
        result = runner.invoke(
            cli, _auth_args(tmp_path / ".env"), input=f"{REDIRECT_URI}?code=abc&state={state}\n9\nx\n"
        )
        assert result.exit_code != 0
        assert not settings_path.exists()

    def test_site_flag_selects_matching_site(self, settings_path, fake_network, tmp_path):
        fake_network["resources"] = [SITE_A, SITE_B]
        runner = CliRunner()
        first = runner.invoke(cli, _auth_args(tmp_path / ".env", "--site", SITE_B["url"]), input="\n")
        state = _state_from_output(first.output)
        result = runner.invoke(
            cli,
            _auth_args(tmp_path / ".env", "--site", SITE_B["url"]),
            input=f"{REDIRECT_URI}?code=abc&state={state}\n",
        )
        assert result.exit_code == 0, result.output
        assert LocalStoreHelper.load_default(settings_path).cloud_id == SITE_B["id"]

    def test_unknown_site_flag_aborts(self, settings_path, fake_network, tmp_path):
        runner = CliRunner()
        first = runner.invoke(cli, _auth_args(tmp_path / ".env", "--site", "https://nope.atlassian.net"), input="\n")
        state = _state_from_output(first.output)
        result = runner.invoke(
            cli,
            _auth_args(tmp_path / ".env", "--site", "https://nope.atlassian.net"),
            input=f"{REDIRECT_URI}?code=abc&state={state}\n",
        )
        assert result.exit_code != 0
        assert not settings_path.exists()


class TestStatusAndLogout:
    def test_status_without_credentials_exits_nonzero(self, settings_path):
        result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output

    def test_status_never_prints_secrets(self, settings_path, monkeypatch):
        LocalStoreHelper.save(settings_path, _make_token())

        async def _ok(access_token: str, cloud_id: str) -> dict[str, Any]:
            return dict(MYSELF)

        monkeypatch.setattr(jira_cli, "_myself", _ok)
        result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0, result.output
        assert SITE_A["url"] in result.output
        assert "Probe /myself: ok" in result.output
        assert "ACCESS-SECRET-VALUE" not in result.output
        assert "REFRESH-SECRET-VALUE" not in result.output

    def test_logout_removes_entry_and_leaves_env_untouched(self, settings_path, tmp_path):
        LocalStoreHelper.save(settings_path, _make_token())
        env = tmp_path / ".env"
        env.write_text("JIRA_CLIENT_ID=keep\n", encoding="utf-8")
        result = CliRunner().invoke(cli, ["logout"])
        assert result.exit_code == 0, result.output
        assert not settings_path.exists()
        assert env.read_text(encoding="utf-8") == "JIRA_CLIENT_ID=keep\n"


class TestSyncKb:
    @staticmethod
    def _live(projects=None, components=None, scale=None, field_ids=None) -> dict[str, Any]:
        return {
            "projects": projects or {},
            "components": components or [],
            "priority_scale": scale or ["Highest", "High", "Medium"],
            "live_field_ids": field_ids or {"customfield_10001"},
        }

    def test_sync_keeps_curated_sections_and_refreshes_structure(self, settings_path, monkeypatch, tmp_path):
        output = tmp_path / "kb.yaml"
        curated = JiraKnowledgeBase(
            site="https://old.atlassian.net",
            status_map={"done": ["Closed"]},
            limits=LimitsEntry(summary_max_chars=80),
            priorities=PrioritiesEntry(scale=["Old"], legacy=["Blocker"], default="Medium"),
            fields={"team": "customfield_10001", "gone": "customfield_99999"},
        )
        curated.save(output)

        monkeypatch.setattr(jira_cli, "_load_fresh_token", lambda site=None: _make_token())

        async def _fetch(token, project_keys):
            assert project_keys is None
            return self._live(components=["Core"], scale=["Highest", "High"], field_ids={"customfield_10001"})

        monkeypatch.setattr(jira_cli, "_fetch_structure", _fetch)
        result = CliRunner().invoke(cli, ["sync-kb", "-o", str(output)])
        assert result.exit_code == 0, result.output

        merged = JiraKnowledgeBase.load(output)
        assert merged.site == SITE_A["url"]
        assert merged.cloud_id == SITE_A["id"]
        assert merged.verified is not None
        assert merged.status_map == {"done": ["Closed"]}
        assert merged.limits.summary_max_chars == 80
        assert merged.priorities.legacy == ["Blocker"]
        assert merged.priorities.default == "Medium"
        assert merged.priorities.scale == ["Highest", "High"]
        assert merged.components == ["Core"]
        assert merged.fields == {"team": "customfield_10001"}

    def test_sync_restricts_to_requested_projects(self, settings_path, monkeypatch, tmp_path):
        monkeypatch.setattr(jira_cli, "_load_fresh_token", lambda site=None: _make_token())
        seen: dict[str, Any] = {}

        async def _fetch(token, project_keys):
            seen["keys"] = project_keys
            return self._live()

        monkeypatch.setattr(jira_cli, "_fetch_structure", _fetch)
        result = CliRunner().invoke(cli, ["sync-kb", "-o", str(tmp_path / "kb.yaml"), "--projects", "NAV, OPS"])
        assert result.exit_code == 0, result.output
        assert seen["keys"] == ["NAV", "OPS"]

    def test_sync_without_credentials_aborts(self, settings_path, tmp_path):
        result = CliRunner().invoke(cli, ["sync-kb", "-o", str(tmp_path / "kb.yaml")])
        assert result.exit_code != 0
        assert "auth" in result.output
        assert not (tmp_path / "kb.yaml").exists()

    def test_unreadable_existing_kb_is_not_overwritten(self, settings_path, monkeypatch, tmp_path):
        output = tmp_path / "kb.yaml"
        output.write_text("- just a list\n", encoding="utf-8")
        monkeypatch.setattr(jira_cli, "_load_fresh_token", lambda site=None: _make_token())
        result = CliRunner().invoke(cli, ["sync-kb", "-o", str(output)])
        assert result.exit_code != 0
        assert output.read_text(encoding="utf-8") == "- just a list\n"


class LocalStoreHelper:
    """Small accessor for the settings file used by the assertions above."""

    @staticmethod
    def load_default(path: Path) -> JiraTokenSet:
        from parrot_tools.jira_local_auth import LocalJiraTokenStore

        token = LocalJiraTokenStore(path).get()
        assert token is not None
        return token

    @staticmethod
    def save(path: Path, token: JiraTokenSet) -> None:
        from parrot_tools.jira_local_auth import LocalJiraTokenStore

        LocalJiraTokenStore(path).save(token)
