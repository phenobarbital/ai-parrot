"""Tests for the Claude Code integration (installer + PreToolUse hook).

Covers ``parrot claude install/uninstall/status`` semantics (managed
markers, settings.json merging, git hook chaining) and the
``wikitoolkit claude-hook`` runtime (nudge conditions, throttling,
fail-silent guarantees). All offline against temp directories.
"""

import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.claude_code.hook import (
    build_nudge,
    run_pre_tool_use_hook,
)
from parrot.knowledge.wiki.claude_code.installer import (
    install_claude_integration,
    integration_status,
    uninstall_claude_integration,
)
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    load_project_config,
    save_project_config,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fake repo with a .git dir (so the git hook installs)."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        '"""A module."""\nX = 1\n', encoding="utf-8"
    )
    return tmp_path


def _built_repo(repo: Path) -> Path:
    """Build the wiki plane inside the fake repo."""
    result = CliRunner().invoke(
        wiki, ["build", "--path", str(repo), "--no-git", "-q"]
    )
    assert result.exit_code == 0, result.output
    return repo


class TestInstaller:
    def test_fresh_install_writes_all_artifacts(self, repo):
        actions = install_claude_integration(repo)
        assert len(actions) == 6

        assert (repo / ".parrot" / "wiki.json").exists()
        claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        assert assets.CLAUDE_MD_BEGIN in claude_md
        assert 'wikitoolkit query' in claude_md

        settings = json.loads(
            (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        entry = settings["hooks"]["PreToolUse"][0]
        assert entry["matcher"] == assets.HOOK_MATCHER
        assert entry["hooks"][0]["command"] == assets.HOOK_COMMAND

        assert (repo / ".claude" / "commands" / "parrotwiki.md").exists()

        hook = (repo / ".git" / "hooks" / "post-commit")
        assert hook.exists()
        assert "wikitoolkit upsert --changed" in hook.read_text()
        assert hook.stat().st_mode & 0o111  # executable

        gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
        assert ".parrot/" in gitignore

    def test_install_is_idempotent(self, repo):
        install_claude_integration(repo)
        snapshot = {
            p: p.read_text(encoding="utf-8")
            for p in [
                repo / "CLAUDE.md",
                repo / ".claude" / "settings.json",
                repo / ".claude" / "commands" / "parrotwiki.md",
                repo / ".git" / "hooks" / "post-commit",
                repo / ".gitignore",
            ]
        }
        install_claude_integration(repo)
        for path, before in snapshot.items():
            assert path.read_text(encoding="utf-8") == before

    def test_preserves_existing_claude_md(self, repo):
        (repo / "CLAUDE.md").write_text(
            "# My rules\n\nDo good work.\n", encoding="utf-8"
        )
        install_claude_integration(repo)
        text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        assert text.startswith("# My rules")
        assert assets.CLAUDE_MD_BEGIN in text

    def test_preserves_existing_settings_hooks(self, repo):
        settings_dir = repo / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(
            json.dumps({
                "permissions": {"allow": ["Bash(ls:*)"]},
                "hooks": {"PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "echo hi"}],
                }]},
            }),
            encoding="utf-8",
        )
        install_claude_integration(repo)
        settings = json.loads(
            (settings_dir / "settings.json").read_text(encoding="utf-8")
        )
        assert settings["permissions"] == {"allow": ["Bash(ls:*)"]}
        pre = settings["hooks"]["PreToolUse"]
        assert len(pre) == 2
        assert pre[0]["hooks"][0]["command"] == "echo hi"

    def test_invalid_settings_json_aborts(self, repo):
        settings_dir = repo / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("{broken", encoding="utf-8")
        with pytest.raises(RuntimeError):
            install_claude_integration(repo)

    def test_chains_into_existing_git_hook(self, repo):
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "post-commit").write_text(
            "#!/bin/sh\necho existing\n", encoding="utf-8"
        )
        install_claude_integration(repo)
        text = (hooks_dir / "post-commit").read_text(encoding="utf-8")
        assert "echo existing" in text
        assert assets.GIT_HOOK_BEGIN in text

    def test_no_git_hook_option(self, repo):
        install_claude_integration(repo, git_hook=False)
        assert not (repo / ".git" / "hooks" / "post-commit").exists()

    def test_uninstall_removes_only_ours(self, repo):
        (repo / "CLAUDE.md").write_text("# Mine\n", encoding="utf-8")
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "post-commit").write_text(
            "#!/bin/sh\necho existing\n", encoding="utf-8"
        )
        install_claude_integration(repo)
        uninstall_claude_integration(repo)

        text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        assert "# Mine" in text
        assert assets.CLAUDE_MD_BEGIN not in text
        settings = json.loads(
            (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        assert "hooks" not in settings
        assert not (repo / ".claude" / "commands" / "parrotwiki.md").exists()
        hook_text = (hooks_dir / "post-commit").read_text(encoding="utf-8")
        assert "echo existing" in hook_text
        assert assets.GIT_HOOK_BEGIN not in hook_text
        # Config + plane are intentionally left in place.
        assert (repo / ".parrot" / "wiki.json").exists()

    def test_status_reflects_install_state(self, repo):
        before = integration_status(repo)
        assert not before["claude_md_section"]
        install_claude_integration(repo)
        after = integration_status(repo)
        assert after["config"]
        assert after["claude_md_section"]
        assert after["pre_tool_use_hook"]
        assert after["slash_command"]
        assert after["git_post_commit_hook"]


class TestHookNudge:
    def _payload(self, repo: Path, tool: str, tool_input=None) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input or {},
            "cwd": str(repo),
        }

    def test_nudges_grep_when_built(self, repo):
        _built_repo(repo)
        out = build_nudge(self._payload(repo, "Grep"), root=repo, now=1000.0)
        assert out is not None
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        assert "wikitoolkit query" in hso["additionalContext"]
        # Non-blocking: never touches the permission flow.
        assert "permissionDecision" not in hso

    def test_no_nudge_when_not_built(self, repo):
        save_project_config(repo, WikiProjectConfig(wiki_name="x"))
        assert build_nudge(self._payload(repo, "Grep"), root=repo) is None

    def test_no_nudge_for_unmatched_tool(self, repo):
        _built_repo(repo)
        assert build_nudge(self._payload(repo, "Bash"), root=repo) is None

    def test_read_nudges_only_source_files(self, repo):
        _built_repo(repo)
        config = load_project_config(repo)
        csv = self._payload(repo, "Read", {"file_path": "/tmp/data.csv"})
        assert build_nudge(csv, root=repo, config=config, now=1000.0) is None
        py = self._payload(repo, "Read", {"file_path": "/src/mod.py"})
        assert (
            build_nudge(py, root=repo, config=config, now=1000.0) is not None
        )

    def test_throttle_cooldown(self, repo):
        _built_repo(repo)
        first = build_nudge(self._payload(repo, "Grep"), root=repo, now=1000.0)
        assert first is not None
        second = build_nudge(self._payload(repo, "Grep"), root=repo, now=1010.0)
        assert second is None  # inside the 300 s default cooldown
        third = build_nudge(self._payload(repo, "Grep"), root=repo, now=1400.0)
        assert third is not None

    def test_wrong_event_ignored(self, repo):
        _built_repo(repo)
        payload = self._payload(repo, "Grep")
        payload["hook_event_name"] = "PostToolUse"
        assert build_nudge(payload, root=repo) is None


class TestHookRuntime:
    def test_runtime_emits_json(self, repo):
        _built_repo(repo)
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {"pattern": "x"},
            "cwd": str(repo),
        }
        stdout = io.StringIO()
        code = run_pre_tool_use_hook(
            stdin=io.StringIO(json.dumps(payload)), stdout=stdout
        )
        assert code == 0
        response = json.loads(stdout.getvalue())
        assert response["suppressOutput"] is True
        assert "additionalContext" in response["hookSpecificOutput"]

    def test_runtime_never_fails_on_garbage(self):
        for garbage in ["", "not json", "[1,2,3]", '"str"']:
            code = run_pre_tool_use_hook(
                stdin=io.StringIO(garbage), stdout=io.StringIO()
            )
            assert code == 0

    def test_runtime_silent_outside_project(self, tmp_path):
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {},
            "cwd": str(tmp_path),
        }
        stdout = io.StringIO()
        code = run_pre_tool_use_hook(
            stdin=io.StringIO(json.dumps(payload)), stdout=stdout
        )
        assert code == 0
        assert stdout.getvalue() == ""


class TestClaudeCli:
    def test_install_status_uninstall_cycle(self, repo):
        from parrot.knowledge.wiki.claude_code.cli import claude

        runner = CliRunner()
        result = runner.invoke(
            claude, ["install", "--path", str(repo), "--no-build"]
        )
        assert result.exit_code == 0, result.output
        assert "integration installed" in result.output

        status = runner.invoke(
            claude, ["status", "--path", str(repo), "--json"]
        )
        info = json.loads(status.output)
        assert info["pre_tool_use_hook"] is True

        result = runner.invoke(claude, ["uninstall", "--path", str(repo)])
        assert result.exit_code == 0
        info = json.loads(
            runner.invoke(
                claude, ["status", "--path", str(repo), "--json"]
            ).output
        )
        assert info["pre_tool_use_hook"] is False

    def test_install_builds_plane_by_default(self, repo):
        from parrot.knowledge.wiki.claude_code.cli import claude

        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        config = load_project_config(repo)
        assert config.is_built(repo)
