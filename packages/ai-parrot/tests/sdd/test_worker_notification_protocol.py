"""Qualify the feature-only notification instruction and its installed twin."""

from __future__ import annotations

from pathlib import Path
import subprocess
import re

import pytest

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / ".claude/agents/sdd-worker.md"
SHIPPED = ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md"


def test_worker_notification_protocol_order() -> None:
    """Only feature completion records after push and before the final summary."""
    source_content = SOURCE.read_text(encoding="utf-8")

    # Find the completion steps (look for the numbered steps)
    lines = source_content.split("\n")

    push_line_idx = None
    notification_line_idx = None
    summary_line_idx = None

    for i, line in enumerate(lines):
        if "2. **Push the feature branch**" in line:
            push_line_idx = i
        elif "2a. **Record optional desktop completion" in line:
            notification_line_idx = i
        elif "3. **Print summary:**" in line:
            summary_line_idx = i

    assert push_line_idx is not None, "Could not find push step"
    assert notification_line_idx is not None, "Could not find notification step"
    assert summary_line_idx is not None, "Could not find summary step"

    # Verify the order
    assert (
        push_line_idx < notification_line_idx < summary_line_idx
    ), "Notification instruction is not properly ordered between push and summary"

    # Verify the command is exactly as specified
    notification_section = "\n".join(lines[notification_line_idx:summary_line_idx])
    command_pattern = r'"(\$PARROT_SDD_NOTIFY_PYTHON)" -S "(\$PARROT_SDD_NOTIFY_HELPER)" --complete'
    assert re.search(command_pattern, notification_section), "Notification command not found or incorrect format"

    # Verify exclusions are mentioned
    exclusions = [
        "task-scoped JSON brief mode",
        "child completion",
        "interrupts",
        "blocked/unfinished tasks",
        "unfinished review",
        "failed push",
    ]

    for exclusion in exclusions:
        assert exclusion in notification_section, f"Exclusion '{exclusion}' not mentioned"


def test_notification_worker_asset_matches_source() -> None:
    """Source and installed worker bytes implement the same protocol."""
    assert SOURCE.read_bytes() == SHIPPED.read_bytes()


def test_completion_command_is_guarded() -> None:
    """Verify the extracted command has proper guards without executing it."""
    source_content = SOURCE.read_text(encoding="utf-8")

    # Extract just our notification command block
    lines = source_content.split("\n")
    notification_line_idx = None
    for i, line in enumerate(lines):
        if "2a. **Record optional desktop completion" in line:
            notification_line_idx = i
            break

    assert notification_line_idx is not None, "Could not find notification step"

    # Find the shell block within our notification section
    shell_block_start = None
    shell_block_end = None
    for i in range(notification_line_idx, len(lines)):
        if lines[i].strip() == "```bash":
            shell_block_start = i + 1
        elif shell_block_start is not None and lines[i].strip() == "```":
            shell_block_end = i
            break

    assert shell_block_start is not None and shell_block_end is not None, "Could not find shell block"

    shell_block_lines = lines[shell_block_start:shell_block_end]
    shell_block = "\n".join(shell_block_lines)

    # Verify the command structure
    assert 'if [ -n "${PARROT_SDD_NOTIFY_PYTHON:-}" ] && [ -n "${PARROT_SDD_NOTIFY_HELPER:-}" ]; then' in shell_block
    assert '"$PARROT_SDD_NOTIFY_PYTHON" -S "$PARROT_SDD_NOTIFY_HELPER" --complete' in shell_block
    assert "fi" in shell_block

    # Verify it's properly guarded
    assert "PARROT_SDD_NOTIFY_PYTHON" in shell_block
    assert "PARROT_SDD_NOTIFY_HELPER" in shell_block


def test_operator_notification_documentation() -> None:
    """Document feature completion, same-host delivery and CLI lifetime accurately."""
    doc_content = (ROOT / "docs/dev_loop/claude-native-sandbox.md").read_text(encoding="utf-8")

    # Check for required concepts (using partial matches to be more robust)
    required_concepts = [
        "best-effort host desktop notifications",
        "feature worker records completion",
        "host Stop hook consumes that explicit receipt",
        "Claude Code and its pane remain open",
        "Delivery needs `notify-send`",
        "SSH/headless hosts may show nothing",
        "delivery failures never fail the worker",
        "One launch permits at most one attempt",
        "reattach",
        "new hooks",
        "launch a new session",
        "PATH, HOME, DISPLAY, WAYLAND_DISPLAY",
        "Host delivery runs outside the worker's Bash sandbox",
        "A changed HEAD invalidates a recorded receipt",
    ]

    for concept in required_concepts:
        assert concept in doc_content, f"Required concept '{concept}' not documented"
