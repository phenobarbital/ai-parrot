"""Offline contracts for native LLM-Wiki coding-agent wiring."""

import io
import json

import pytest

from parrot.knowledge.wiki import coding_agents


def test_install_is_idempotent_and_preserves_settings(tmp_path):
    settings = tmp_path / ".gemini/settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"theme": "user", "hooks": {"AfterTool": []}}))

    coding_agents.install("gemini", tmp_path)
    first = settings.read_bytes()
    coding_agents.install("gemini", tmp_path)
    second = settings.read_bytes()

    assert first == second
    data = json.loads(second)
    assert data["theme"] == "user"
    assert len(data["hooks"]["AfterTool"]) == 1
    assert (tmp_path / "GEMINI.md").is_file()
    assert (tmp_path / ".gemini/skills/parrot-wiki/SKILL.md").is_file()


def test_codex_and_claude_emit_advisory_hook_responses(tmp_path):
    for agent, event in (("codex", "PreToolUse"), ("claude", "PreToolUse")):
        output = io.StringIO()
        assert coding_agents.hook(agent, io.StringIO(json.dumps({"hook_event_name": event})), output) == 0
        response = json.loads(output.getvalue())
        assert "systemMessage" in response
        assert "permissionDecision" not in response


@pytest.mark.parametrize("agent,canonical", [("codex", "codex"), ("gemini", "google"), ("google", "google")])
def test_install_writes_conventions_block(tmp_path, agent, canonical):
    (tmp_path / ".agent" / "rules").mkdir(parents=True)
    (tmp_path / ".agent" / "rules" / "codebase-conventions.md").write_text("RULE-ONE\n")
    (tmp_path / ".agent" / "rules" / "python-development.md").write_text("RULE-TWO\n")
    coding_agents.install(agent, tmp_path)
    instruction = tmp_path / coding_agents._AGENTS[agent][0]
    text = instruction.read_text()
    assert f"<!-- parrot:conventions:{canonical}:begin -->" in text and "RULE-ONE" in text
    coding_agents.install(agent, tmp_path)
    assert instruction.read_text() == text


def test_claude_install_writes_no_conventions_block(tmp_path):
    coding_agents.install("claude", tmp_path)
    instruction = tmp_path / coding_agents._AGENTS["claude"][0]
    text = instruction.read_text()
    assert "<!-- parrot:conventions" not in text


def test_gemini_and_google_share_one_conventions_block(tmp_path):
    (tmp_path / ".agent" / "rules").mkdir(parents=True)
    (tmp_path / ".agent" / "rules" / "codebase-conventions.md").write_text("RULE-ONE\n")
    (tmp_path / ".agent" / "rules" / "python-development.md").write_text("RULE-TWO\n")
    coding_agents.install("gemini", tmp_path)
    from parrot.knowledge.wiki.google.installer import _install_gemini_md

    _install_gemini_md(tmp_path)
    assert (tmp_path / "GEMINI.md").read_text().count("<!-- parrot:conventions:google:begin -->") == 1

    # Test the reverse order too
    (tmp_path / "GEMINI.md").unlink()
    _install_gemini_md(tmp_path)
    coding_agents.install("gemini", tmp_path)
    assert (tmp_path / "GEMINI.md").read_text().count("<!-- parrot:conventions:google:begin -->") == 1
