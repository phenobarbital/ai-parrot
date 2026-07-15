"""Idempotent installer for the Claude Code wiki integration.

``install_claude_integration`` wires the repository knowledge graph
into Claude Code:

1. persists ``.parrot/wiki.json`` (the config the hook reads);
2. appends a managed section to ``CLAUDE.md`` telling the assistant to
   prefer ``wikitoolkit query "<question>"`` over grepping raw files;
3. merges a ``PreToolUse`` nudge hook into ``.claude/settings.json``
   (matcher ``Grep|Glob|Read`` → ``wikitoolkit claude-hook``);
4. writes the ``/parrotwiki`` slash command;
5. optionally installs a chained git ``post-commit`` hook that runs
   ``wikitoolkit upsert --changed`` after every commit;
6. optionally git-ignores ``.parrot/``.

Every step is marker-based and re-runnable; ``uninstall`` removes
exactly the managed artifacts and nothing else.
"""

from __future__ import annotations

import json
import logging
import stat
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.project import (
    WikiConfigError,
    WikiProjectConfig,
    config_path,
    load_project_config,
    save_project_config,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Small marker-block helpers
# --------------------------------------------------------------------------


def _upsert_marker_block(
    text: str, block: str, begin: str, end: str
) -> str:
    """Insert or replace a marker-delimited block inside ``text``."""
    block = block.rstrip("\n")
    if begin in text and end in text:
        head, _, rest = text.partition(begin)
        _, _, tail = rest.partition(end)
        return f"{head}{block}{tail}"
    if text and not text.endswith("\n"):
        text += "\n"
    separator = "\n" if text else ""
    return f"{text}{separator}{block}\n"


def _remove_marker_block(text: str, begin: str, end: str) -> str:
    """Remove a marker-delimited block (markers included) from ``text``."""
    if begin not in text or end not in text:
        return text
    head, _, rest = text.partition(begin)
    _, _, tail = rest.partition(end)
    head = head.rstrip(" \t").rstrip("\n")
    if not head and not tail.strip():
        return ""
    return head + ("\n" + tail.lstrip("\n") if tail.strip() else "\n")


# --------------------------------------------------------------------------
# Individual install steps (each returns a human-readable action string)
# --------------------------------------------------------------------------


def _install_claude_md(root: Path) -> str:
    """Write/refresh the managed CLAUDE.md section."""
    path = root / "CLAUDE.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _upsert_marker_block(
        text,
        assets.CLAUDE_MD_SECTION,
        assets.CLAUDE_MD_BEGIN,
        assets.CLAUDE_MD_END,
    )
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return f"CLAUDE.md — wiki section {'updated' if text else 'created'}"
    return "CLAUDE.md — wiki section already current"


def _hook_entry() -> dict[str, Any]:
    """Build the PreToolUse hook entry for settings.json."""
    return {
        "matcher": assets.HOOK_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": assets.HOOK_COMMAND,
                "timeout": 10,
            }
        ],
    }


def _is_our_hook(entry: dict[str, Any]) -> bool:
    """Whether a settings hook entry was installed by us."""
    for hook in entry.get("hooks", []):
        if assets.HOOK_COMMAND in str(hook.get("command", "")):
            return True
    return False


def _load_settings(path: Path) -> Optional[dict[str, Any]]:
    """Read a Claude settings.json file.

    Args:
        path: Settings file path.

    Returns:
        The parsed object, or ``None`` when the file does not exist.

    Raises:
        RuntimeError: When the file exists but is not valid JSON or is
            not a JSON object — callers must not silently clobber it.
    """
    if not path.exists():
        return None
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot parse {path} — fix or remove it first: {exc}"
        ) from exc
    if not isinstance(settings, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return settings


def _write_settings(path: Path, settings: dict[str, Any]) -> None:
    """Persist a settings object as pretty JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _install_settings_hook(root: Path) -> str:
    """Merge the PreToolUse nudge hook into .claude/settings.json."""
    path = root / ".claude" / "settings.json"
    settings = _load_settings(path) or {}

    hooks = settings.get("hooks")
    if hooks is None:
        hooks = settings["hooks"] = {}
    if not isinstance(hooks, dict):
        raise RuntimeError(f"{path}: 'hooks' is not a JSON object")
    pre = hooks.get("PreToolUse")
    if pre is None:
        pre = hooks["PreToolUse"] = []
    if not isinstance(pre, list):
        raise RuntimeError(f"{path}: 'hooks.PreToolUse' is not a list")

    if any(isinstance(e, dict) and _is_our_hook(e) for e in pre):
        return ".claude/settings.json — PreToolUse hook already installed"
    pre.append(_hook_entry())
    _write_settings(path, settings)
    return ".claude/settings.json — PreToolUse wiki nudge hook added"


def _install_slash_command(root: Path) -> str:
    """Write the /parrotwiki slash command file."""
    path = root / ".claude" / "commands" / assets.SLASH_COMMAND_FILENAME
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == assets.SLASH_COMMAND_MD:
        return ".claude/commands/parrotwiki.md — already current"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(assets.SLASH_COMMAND_MD, encoding="utf-8")
    return (
        ".claude/commands/parrotwiki.md — "
        + ("updated" if existing is not None else "created")
    )


def _git_hook_path(root: Path) -> Optional[Path]:
    """Locate .git/hooks/post-commit, or None when not a git repo."""
    git_dir = root / ".git"
    if git_dir.is_dir():
        return git_dir / "hooks" / "post-commit"
    if git_dir.is_file():  # worktree: `gitdir: <path>` pointer
        try:
            content = git_dir.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if content.startswith("gitdir:"):
            target = Path(content.split(":", 1)[1].strip())
            if not target.is_absolute():
                target = (root / target).resolve()
            # Linked worktrees: git resolves hooks/ against the COMMON
            # git dir (the `commondir` pointer), not the per-worktree
            # gitdir — a hook written to the latter never runs.
            commondir = target / "commondir"
            if commondir.is_file():
                try:
                    rel = commondir.read_text(encoding="utf-8").strip()
                except OSError:
                    return None
                target = (target / rel).resolve()
            return target / "hooks" / "post-commit"
    return None


def _install_git_hook(root: Path) -> str:
    """Install (or chain into) the git post-commit auto-upsert hook."""
    hook_path = _git_hook_path(root)
    if hook_path is None:
        return "git hook — skipped (not a git repository)"
    if hook_path.exists():
        text = hook_path.read_text(encoding="utf-8")
        if assets.GIT_HOOK_BEGIN in text:
            return "git post-commit hook — already installed"
        first_line = text.splitlines()[0] if text.strip() else ""
        if first_line.startswith("#!") and "sh" not in first_line:
            # Appending sh syntax to a python/node hook would break it.
            return (
                "git post-commit hook — skipped (existing hook is not a "
                "shell script; add `wikitoolkit upsert --changed --quiet` "
                "to it manually)"
            )
        if not text.endswith("\n"):
            text += "\n"
        hook_path.write_text(text + assets.GIT_HOOK_BLOCK, encoding="utf-8")
        action = "git post-commit hook — chained into existing hook"
    else:
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(assets.GIT_HOOK_NEW_FILE, encoding="utf-8")
        action = "git post-commit hook — created"
    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return action


def _install_gitignore(root: Path) -> str:
    """Ensure .parrot/ is git-ignored."""
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = {line.strip() for line in text.splitlines()}
    if {".parrot/", ".parrot", "/.parrot/", "/.parrot"} & lines:
        return ".gitignore — .parrot/ already ignored"
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(
        text + "# parrot LLM-wiki state (local retrieval plane)\n.parrot/\n",
        encoding="utf-8",
    )
    return ".gitignore — added .parrot/"


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def install_claude_integration(
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    git_hook: bool = True,
    gitignore: bool = True,
) -> list[str]:
    """Install the wiki ↔ Claude Code integration into a repository.

    Args:
        root: Repository root.
        config: Wiki project config; loaded/created when omitted.
        git_hook: Install the git post-commit auto-upsert hook.
        gitignore: Add ``.parrot/`` to .gitignore.

    Returns:
        Human-readable list of actions performed.
    """
    root = root.resolve()
    config = config or load_project_config(root)
    actions = [
        f".parrot/wiki.json — config written "
        f"(wiki '{config.wiki_name}', backend {config.backend})"
        if not config_path(root).exists()
        else ".parrot/wiki.json — config already present"
    ]
    save_project_config(root, config)

    actions.append(_install_claude_md(root))
    actions.append(_install_settings_hook(root))
    actions.append(_install_slash_command(root))
    if git_hook:
        actions.append(_install_git_hook(root))
    if gitignore:
        actions.append(_install_gitignore(root))
    return actions


def uninstall_claude_integration(root: Path) -> list[str]:
    """Remove every managed artifact written by the installer.

    Leaves ``.parrot/wiki.json`` and the wiki plane itself in place —
    only the Claude Code wiring is removed.

    Args:
        root: Repository root.

    Returns:
        Human-readable list of actions performed.
    """
    root = root.resolve()
    actions: list[str] = []

    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        text = claude_md.read_text(encoding="utf-8")
        updated = _remove_marker_block(
            text, assets.CLAUDE_MD_BEGIN, assets.CLAUDE_MD_END
        )
        if updated != text:
            claude_md.write_text(updated, encoding="utf-8")
            actions.append("CLAUDE.md — wiki section removed")

    settings_path = root / ".claude" / "settings.json"
    try:
        settings = _load_settings(settings_path)
    except RuntimeError:
        settings = None
    if isinstance(settings, dict):
        hooks = settings.get("hooks")
        pre = hooks.get("PreToolUse", []) if isinstance(hooks, dict) else []
        if isinstance(pre, list):
            kept = [
                e for e in pre
                if not (isinstance(e, dict) and _is_our_hook(e))
            ]
            if len(kept) != len(pre):
                settings["hooks"]["PreToolUse"] = kept
                if not kept:
                    settings["hooks"].pop("PreToolUse")
                if not settings["hooks"]:
                    settings.pop("hooks")
                _write_settings(settings_path, settings)
                actions.append(
                    ".claude/settings.json — PreToolUse hook removed"
                )

    command_path = root / ".claude" / "commands" / assets.SLASH_COMMAND_FILENAME
    if command_path.exists():
        command_path.unlink()
        actions.append(".claude/commands/parrotwiki.md — removed")

    hook_path = _git_hook_path(root)
    if hook_path and hook_path.exists():
        text = hook_path.read_text(encoding="utf-8")
        if assets.GIT_HOOK_BEGIN in text:
            updated = _remove_marker_block(
                text, assets.GIT_HOOK_BEGIN, assets.GIT_HOOK_END
            )
            if updated.strip() in {"", "#!/bin/sh"}:
                hook_path.unlink()
                actions.append("git post-commit hook — removed")
            else:
                hook_path.write_text(updated, encoding="utf-8")
                actions.append("git post-commit hook — wiki block removed")

    if not actions:
        actions.append("nothing to remove — integration not installed")
    return actions


def integration_status(root: Path) -> dict[str, Any]:
    """Report which integration pieces are currently installed.

    Args:
        root: Repository root.

    Returns:
        Mapping of artifact name → bool (or detail string).
    """
    root = root.resolve()
    try:
        config = load_project_config(root)
    except WikiConfigError:
        # Status is read-only — report against defaults rather than fail.
        config = WikiProjectConfig(wiki_name=root.name or "codebase")

    claude_md = root / "CLAUDE.md"
    claude_md_installed = (
        claude_md.exists()
        and assets.CLAUDE_MD_BEGIN in claude_md.read_text(encoding="utf-8")
    )

    settings_path = root / ".claude" / "settings.json"
    hook_installed = False
    try:
        settings = _load_settings(settings_path)
    except RuntimeError:
        settings = None
    if isinstance(settings, dict):
        hooks = settings.get("hooks")
        pre = hooks.get("PreToolUse", []) if isinstance(hooks, dict) else []
        if isinstance(pre, list):
            hook_installed = any(
                isinstance(e, dict) and _is_our_hook(e) for e in pre
            )

    git_hook_file = _git_hook_path(root)
    git_hook_installed = bool(
        git_hook_file
        and git_hook_file.exists()
        and assets.GIT_HOOK_BEGIN
        in git_hook_file.read_text(encoding="utf-8")
    )

    return {
        "root": str(root),
        "config": config_path(root).exists(),
        "wiki_built": config.is_built(root),
        "claude_md_section": claude_md_installed,
        "pre_tool_use_hook": hook_installed,
        "slash_command": (
            root / ".claude" / "commands" / assets.SLASH_COMMAND_FILENAME
        ).exists(),
        "git_post_commit_hook": git_hook_installed,
    }
