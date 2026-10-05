"""Regression cases for FEAT-627: managed command assets and standup documentation."""

import re
from pathlib import Path

import pytest


def _read_file(path: Path) -> str:
    """Read a file from the repo root."""
    return path.read_text()


def _repo_root() -> Path:
    """Return the repository root."""
    return Path(__file__).parents[6]


def test_managed_command_parity() -> None:
    """Verify managed command assets list identical standup/entity syntax."""
    root = _repo_root()

    # Read the managed asset from claude_code
    claude_assets_path = root / "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py"
    claude_assets = _read_file(claude_assets_path)

    # Read the checked-in command file
    cmd_path = root / ".claude/commands/parrotwiki.md"
    cmd_content = _read_file(cmd_path)

    # Extract SLASH_COMMAND_MD content
    slash_match = re.search(r'SLASH_COMMAND_MD = """(.*?)"""', claude_assets, re.DOTALL)
    assert slash_match, "SLASH_COMMAND_MD not found in claude_code/assets.py"
    slash_md = slash_match.group(1)

    # Verify both contain standup and entity in argument-hint
    assert "standup" in slash_md
    assert "entity" in slash_md
    assert "standup" in cmd_content
    assert "entity" in cmd_content

    # Verify both have the same standup bullet
    assert "wikitoolkit standup" in slash_md
    assert "wikitoolkit standup" in cmd_content

    # Verify both have the same entity bullet
    assert "wikitoolkit entity" in slash_md
    assert "wikitoolkit entity" in cmd_content

    # Verify both mention --period and --language options
    assert "--period day|week|month" in slash_md
    assert "--period day|week|month" in cmd_content
    assert "--language en|es" in slash_md
    assert "--language en|es" in cmd_content

    # Verify MCP opt-in notice is present in both
    assert "opt-in" in slash_md.lower()
    assert "opt-in" in cmd_content.lower()
    assert "--no-store --no-file --json" in slash_md
    assert "--no-store --no-file --json" in cmd_content


def test_codex_assets_mention_standup_and_entity() -> None:
    """Verify Codex skill assets expose standup/entity CLI surface."""
    root = _repo_root()
    codex_path = root / "packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py"
    codex_assets = _read_file(codex_path)

    # Extract SKILL content
    skill_match = re.search(r'SKILL = """(.*?)"""', codex_assets, re.DOTALL)
    assert skill_match, "SKILL not found in codex/assets.py"
    skill = skill_match.group(1)

    assert "wikitoolkit standup" in skill
    assert "wikitoolkit entity" in skill
    assert "day/week/month briefs" in skill
    assert "local-plane back-fill" in skill


def test_google_assets_mention_standup_and_entity() -> None:
    """Verify Gemini skill assets expose standup/entity CLI surface."""
    root = _repo_root()
    google_path = root / "packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py"
    google_assets = _read_file(google_path)

    # Extract SKILL content
    skill_match = re.search(r'SKILL = """(.*?)"""', google_assets, re.DOTALL)
    assert skill_match, "SKILL not found in google/assets.py"
    skill = skill_match.group(1)

    assert "wikitoolkit standup" in skill
    assert "wikitoolkit entity" in skill
    assert "day/week/month briefs" in skill
    assert "local-plane back-fill" in skill


def test_docs_show_actual_controls() -> None:
    """Verify docs show actual CLI controls from the standup CLI."""
    root = _repo_root()

    # Read the cheatsheet
    cheatsheet_path = root / "docs/wiki/cheatsheet.md"
    cheatsheet = _read_file(cheatsheet_path)

    # Verify cheatsheet covers standup controls
    assert "wikitoolkit standup" in cheatsheet
    assert "--period" in cheatsheet
    assert "--language" in cheatsheet
    assert "--no-llm" in cheatsheet
    assert "--out" in cheatsheet
    assert "--team" in cheatsheet
    assert "--no-store" in cheatsheet
    assert "--no-file" in cheatsheet
    assert "--json" in cheatsheet

    # Verify cheatsheet covers entity controls
    assert "wikitoolkit entity" in cheatsheet
    assert "entity reindex" in cheatsheet
    assert "--store" in cheatsheet

    # Verify cheatsheet links to runbook
    assert "wiki-standup.md" in cheatsheet

    # Read the guide
    guide_path = root / "docs/guides/llm-wiki-guide.md"
    guide = _read_file(guide_path)

    # Verify guide covers standup concepts
    assert "Standup Briefs and Typed Entities" in guide
    assert "Attributes Ingest and Back-fill" in guide
    assert "Personal and Team Filtering" in guide
    assert "Period Roll-ups" in guide
    assert "Model Fallback" in guide
    assert "Read-Only MCP Defaults" in guide
    assert "Cron Scheduling" in guide
    assert "wiki standup runbook" in guide.lower()

    # Read the runbook
    runbook_path = root / "docs/runbooks/wiki-standup.md"
    runbook = _read_file(runbook_path)

    # Verify runbook has key sections
    assert "Generate a brief" in runbook
    assert "Back-fill" in runbook
    assert "Identity" in runbook
    assert "Schedule" in runbook
    assert "Cron" in runbook
    assert "Troubleshooting" in runbook


def test_standup_cli_options_match_docs() -> None:
    """Verify the actual CLI options match what docs claim."""
    root = _repo_root()

    # Read the CLI source
    cli_path = root / "packages/ai-parrot/src/parrot/knowledge/wiki/standup/cli.py"
    cli_content = _read_file(cli_path)

    # Verify key options are defined in the CLI
    assert "--period" in cli_content
    assert "--language" in cli_content
    assert "--team" in cli_content
    assert "--me" in cli_content
    assert "--no-llm" in cli_content
    assert "--no-store" in cli_content
    assert "--no-file" in cli_content
    assert "--json" in cli_content
    assert "--out" in cli_content
    assert "--store" in cli_content


def test_entity_cli_options_match_docs() -> None:
    """Verify the entity CLI options match what docs claim."""
    root = _repo_root()

    # Read the entity CLI source
    entity_cli_path = root / "packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py"
    entity_cli_content = _read_file(entity_cli_path)

    # Verify add_entity has key options
    assert "--type" in entity_cli_content or "type_" in entity_cli_content
    assert "@click.argument(\"title\")" in entity_cli_content
    assert "--body" in entity_cli_content
    assert "--project" in entity_cli_content
    assert "--status" in entity_cli_content
    assert "--date" in entity_cli_content
    assert "--due" in entity_cli_content
    assert "--owner" in entity_cli_content
    assert "--store" in entity_cli_content

    # Verify entity group has reindex command
    assert "reindex" in entity_cli_content
    assert '@entity.command("reindex"' in entity_cli_content or "entity.command(" in entity_cli_content
