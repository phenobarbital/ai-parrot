"""Offline contracts for native LLM-Wiki coding-agent wiring."""

import io
import json

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
        assert coding_agents.hook(
            agent, io.StringIO(json.dumps({"hook_event_name": event})), output
        ) == 0
        response = json.loads(output.getvalue())
        assert "systemMessage" in response
        assert "permissionDecision" not in response
