"""Idempotent installer for the Claude Code wiki integration.

``install_claude_integration`` wires the repository knowledge graph
into Claude Code:

1. persists ``.parrot/wiki.json`` (the config the hook reads);
2. appends a managed section to ``CLAUDE.md`` telling the assistant to
   prefer ``wikitoolkit query "<question>"`` over grepping raw files;
3. merges a ``PreToolUse`` nudge hook into ``.claude/settings.json``
   (matcher ``Grep|Glob|Read|Bash`` → ``wikitoolkit claude-hook``);
4. writes wikitoolkit permission rules into ``.claude/settings.local.json``
   (per-user, not committed) and migrates any legacy rules out of the
   shared ``settings.json``;
5. writes the ``/parrotwiki`` slash command;
6. optionally installs a chained git ``post-commit`` hook that runs
   ``wikitoolkit upsert --changed`` after every commit;
7. optionally git-ignores ``.parrot/``.

Every step is marker-based and re-runnable; ``uninstall`` removes
exactly the managed artifacts and nothing else.
"""

from __future__ import annotations

import json
import logging
import shlex
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Optional, Sequence

from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.project import (
    WikiConfigError,
    WikiProjectConfig,
    config_path,
    load_effective_config,
    save_project_config,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Small marker-block helpers
# --------------------------------------------------------------------------


def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:
    """Insert or replace a marker-delimited block inside ``text``.

    Keys on the BEGIN marker alone: if a previous block was left with a
    BEGIN but no END (hand-edited or truncated file), the block is
    replaced through end-of-text rather than appended — so we never
    leave a stray BEGIN behind or emit a second, duplicate block.
    """
    block = block.rstrip("\n")
    if begin in text:
        head, _, rest = text.partition(begin)
        # Replace through the END marker; if it is missing (corrupted
        # block), replace to end-of-text and re-terminate with a newline.
        tail = rest.partition(end)[2] if end in rest else "\n"
        return f"{head}{block}{tail}"
    if text and not text.endswith("\n"):
        text += "\n"
    separator = "\n" if text else ""
    return f"{text}{separator}{block}\n"


def _remove_marker_block(text: str, begin: str, end: str) -> str:
    """Remove a marker-delimited block (markers included) from ``text``.

    Keys on the BEGIN marker: a block with a BEGIN but a missing END
    (corrupted) is still removed through end-of-text so no stray marker
    survives.
    """
    if begin not in text:
        return text
    head, _, rest = text.partition(begin)
    tail = rest.partition(end)[2] if end in rest else ""
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


def _hook_entry(root: Path) -> dict[str, Any]:
    """Build the PreToolUse hook entry for settings.json.

    The command is resolved to an absolute path so the hook fires
    correctly inside git worktrees (which do not inherit the venv's
    ``$PATH``).
    """
    return {
        "matcher": assets.HOOK_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": assets.hook_command(root),
                "timeout": 10,
            }
        ],
    }


def _is_our_command(command: Any) -> bool:
    """Whether a hook command invokes our ``wikitoolkit claude-hook``.

    Matching is done on parsed shell tokens, not on the literal
    ``HOOK_COMMAND`` substring: the installed command carries an absolute
    path, and an equivalent hand-written spelling — a quoted path, or one
    built from ``$CLAUDE_PROJECT_DIR`` — puts a quote between the binary
    and the subcommand. A substring check misses those and the caller
    appends a second, duplicate entry instead of upgrading the first.

    Args:
        command: The ``command`` field of a hook handler.

    Returns:
        True when the command runs our hook under any spelling.
    """
    text = str(command or "")
    try:
        tokens = shlex.split(text)
    except ValueError:  # unbalanced quotes — fall back to the raw needle
        return assets.HOOK_COMMAND in text
    if assets.HOOK_SUBCOMMAND not in tokens:
        return False
    return any(PurePosixPath(token).name == assets.HOOK_BIN_NAME for token in tokens)


def _is_our_hook(entry: dict[str, Any]) -> bool:
    """Whether a settings hook entry was installed by us."""
    return any(_is_our_command(hook.get("command")) for hook in entry.get("hooks", []))


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
        raise RuntimeError(f"Cannot parse {path} — fix or remove it first: {exc}") from exc
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

    resolved_cmd = assets.hook_command(root)

    ours = [e for e in pre if isinstance(e, dict) and _is_our_hook(e)]
    if ours:
        existing, *duplicates = ours
        # Upgrade an older install in place when the matcher or command
        # changed (e.g. bare → absolute path, or Grep|Glob|Read →
        # Grep|Glob|Read|Bash) so a re-run picks up the fix instead of
        # reporting "already installed".
        dirty = False
        if existing.get("matcher") != assets.HOOK_MATCHER:
            existing["matcher"] = assets.HOOK_MATCHER
            dirty = True
        for hook in existing.get("hooks", []):
            if _is_our_command(hook.get("command")) and hook.get("command") != resolved_cmd:
                hook["command"] = resolved_cmd
                dirty = True

        # Collapse copies left behind by an earlier install that failed to
        # recognise its own hook under a different spelling and appended a
        # second entry. A duplicate sharing an entry with someone else's
        # handler loses only our handler — the entry itself is not ours to
        # delete.
        dropped: list[int] = []
        for dup in duplicates:
            foreign = [h for h in dup.get("hooks", []) if not _is_our_command(h.get("command"))]
            if foreign:
                dup["hooks"] = foreign
            else:
                dropped.append(id(dup))
            dirty = True
        if dropped:
            pre[:] = [e for e in pre if id(e) not in dropped]

        if dirty:
            _write_settings(path, settings)
            if duplicates:
                noun = "duplicate" if len(duplicates) == 1 else "duplicates"
                return f".claude/settings.json — PreToolUse hook updated ({len(duplicates)} {noun} removed)"
            return ".claude/settings.json — PreToolUse hook updated"
        return ".claude/settings.json — PreToolUse hook already installed"
    pre.append(_hook_entry(root))
    _write_settings(path, settings)
    return ".claude/settings.json — PreToolUse wiki nudge hook added"


def _install_permissions(root: Path) -> list[str]:
    """Allowlist wikitoolkit commands in settings.local.json.

    Permissions are per-user (wikitoolkit is a local tool), so they
    belong in the non-committed ``settings.local.json``.  If the shared
    ``settings.json`` still carries legacy rules from a previous install,
    they are migrated out.
    """
    actions: list[str] = []

    # --- migrate legacy rules out of the shared settings.json ----------
    shared_path = root / ".claude" / "settings.json"
    shared = _load_settings(shared_path)
    if isinstance(shared, dict):
        s_perms = shared.get("permissions")
        s_allow = s_perms.get("allow", []) if isinstance(s_perms, dict) else []
        if isinstance(s_allow, list):
            legacy = [r for r in s_allow if r in assets.PERMISSION_RULES]
            if legacy:
                shared["permissions"]["allow"] = [r for r in s_allow if r not in assets.PERMISSION_RULES]
                if not shared["permissions"]["allow"]:
                    shared["permissions"].pop("allow")
                if not shared.get("permissions"):
                    shared.pop("permissions", None)
                _write_settings(shared_path, shared)
                actions.append(".claude/settings.json — migrated wikitoolkit " "permissions to settings.local.json")

    # --- write rules into settings.local.json --------------------------
    local_path = root / ".claude" / "settings.local.json"
    local = _load_settings(local_path) or {}

    permissions = local.get("permissions")
    if permissions is None:
        permissions = local["permissions"] = {}
    if not isinstance(permissions, dict):
        raise RuntimeError(f"{local_path}: 'permissions' is not a JSON object")
    allow = permissions.get("allow")
    if allow is None:
        allow = permissions["allow"] = []
    if not isinstance(allow, list):
        raise RuntimeError(f"{local_path}: 'permissions.allow' is not a list")

    all_rules = assets.permission_rules(root)
    missing = [r for r in all_rules if r not in allow]
    if not missing:
        actions.append(".claude/settings.local.json — wikitoolkit permissions " "already allowed")
    else:
        allow.extend(missing)
        _write_settings(local_path, local)
        actions.append(f".claude/settings.local.json — {len(missing)} wikitoolkit " "permission rule(s) added")
    return actions


def _managed_server_names(root: Path) -> list[str]:
    """Return the `.mcp.json` server names this installer manages.

    Always includes ``"wikitoolkit"`` (unconditionally reconciled by
    `_install_mcp_json`, never subject to a foreign-collision check) plus
    one `parrot-<name>` per ENABLED toolkit section whose *current*
    `.mcp.json` entry is confirmed ours via `_is_managed_toolkit_entry`.

    A name derived purely from the enabled toolkit config (the pre-FEAT-556
    behavior) can disagree with what `_install_mcp_json` actually wrote: a
    foreign `parrot-<name>` entry that collides with an enabled section's
    name is deliberately left untouched (installer.py:490-496, warning
    emitted) — approving that name here would silently authorize a
    third-party server the operator never wrote, with no approval prompt.
    Must be called AFTER `_install_mcp_json` has reconciled `.mcp.json` so
    the entry-shape check reflects the final state.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config

    path = root / ".mcp.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    servers = servers if isinstance(servers, dict) else {}

    cfg = load_toolkits_config(root)
    names = ["wikitoolkit"]
    for name, section in sorted(cfg.toolkits.items()):
        key = f"parrot-{name}"
        if section.enabled and _is_managed_toolkit_entry(servers.get(key), root, name):
            names.append(key)
    return names


def _install_mcp_approval(root: Path) -> str:
    """Merge the managed server names into `.claude/settings.local.json`.

    Claude Code leaves a project-scope `.mcp.json` server at "pending approval"
    until its name appears in `enabledMcpjsonServers`; an unapproved server is
    invisible to agents (verified 2026-09-12: sdd-worker saw no
    `mcp__parrot-sdd-coder__*` tools and fell back to its sequential loop).
    Never writes `enableAllProjectMcpServers`: per-name approval suffices and
    the global switch would also authorize unrelated third-party entries.

    Returns:
        One action string, phrased like `_install_permissions` (installer.py:294-301).

    Raises:
        RuntimeError: `enabledMcpjsonServers` exists but is not a JSON list.
    """
    local_path = root / ".claude" / "settings.local.json"
    local = _load_settings(local_path) or {}
    names = local.get("enabledMcpjsonServers")
    if names is None:
        names = local["enabledMcpjsonServers"] = []
    if not isinstance(names, list):
        raise RuntimeError(f"{local_path}: 'enabledMcpjsonServers' is not a list")
    missing = [n for n in _managed_server_names(root) if n not in names]
    if not missing:
        return ".claude/settings.local.json — MCP servers already authorized"
    names.extend(missing)
    _write_settings(local_path, local)
    return f".claude/settings.local.json — {len(missing)} MCP server(s) authorized ({', '.join(missing)})"


def _uninstall_mcp_approval(root: Path, removed_toolkit_names: Sequence[str] = ()) -> str | None:
    """Remove only the managed names from `enabledMcpjsonServers`.

    Always strips ``"wikitoolkit"`` (unambiguous, always ours) plus exactly
    the ``parrot-<name>`` names in ``removed_toolkit_names`` — the entries
    `_uninstall_mcp_json` just confirmed and deleted from `.mcp.json` via
    `_is_managed_toolkit_entry`. Never blanket-strips every `parrot-*` name:
    an operator's own unrelated `parrot-<name>` server, approved by hand and
    never touched by reconciliation, must survive `parrot claude uninstall`.

    Args:
        root: Repository root.
        removed_toolkit_names: The managed keys `_uninstall_mcp_json` just
            removed from `.mcp.json` (must be captured before that call, or
            passed empty when `.mcp.json` was absent/unparseable).

    Returns:
        An action string, or None when there was nothing to remove.
    """
    local_path = root / ".claude" / "settings.local.json"
    try:
        local = _load_settings(local_path)
    except RuntimeError:
        local = None
    if not isinstance(local, dict):
        return None

    names = local.get("enabledMcpjsonServers")
    if not isinstance(names, list):
        return None

    candidates = {"wikitoolkit", *removed_toolkit_names}
    to_remove = {n for n in names if n in candidates}
    if not to_remove:
        return None

    kept = [n for n in names if n not in to_remove]
    if len(kept) == len(names):
        return None

    if kept:
        local["enabledMcpjsonServers"] = kept
    else:
        local.pop("enabledMcpjsonServers", None)

    _write_settings(local_path, local)
    return f".claude/settings.local.json — {len(to_remove)} MCP server approval(s) removed"


def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool:
    """Whether a ``parrot-<name>`` ``.mcp.json`` entry was written by us.

    Managed-entry detection rule (FEAT-485, updated FEAT-556): an entry is
    "ours" iff its ``command`` ends with the resolved ``parrot`` binary name
    AND its ``args`` start with ``["mcp-local", name]``. This accepts both
    the pinned shape (FEAT-556) ``["mcp-local", name, "--config", <path>]``
    and the pre-FEAT-556 legacy shape ``["mcp-local", name]``. A
    ``parrot-<name>`` key whose content does not match this shape is a
    foreign entry with a colliding name — it must never be overwritten or
    removed by reconciliation. A pinned entry whose ``--config`` points
    outside ``root`` is treated as foreign (operator override).
    """
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    bin_name = PurePosixPath(assets.resolve_parrot_bin(root)).name
    if not isinstance(command, str) or not command.endswith(bin_name):
        return False
    args = entry.get("args")
    if not isinstance(args, list) or args[:2] != ["mcp-local", name]:
        return False
    # Accept the pinned shape (["mcp-local", name, "--config", <path>]) and the
    # pre-FEAT-556 two-arg shape, so an entry written by an older install — or
    # by an operator following examples/sdd-coder-mcp.yaml — is ADOPTED and
    # upgraded in place rather than warned about and skipped (installer.py:374-382).
    # A trailing "--config" with a path outside `root` is a foreign override.
    # Uses real path containment (resolved `parents`), not a string prefix: a
    # sibling directory like `root=/repo/worktree` vs.
    # `config_path=/repo/worktree2/...` shares the `startswith` prefix but is
    # NOT inside `root` — a naive substring check would misclassify it as ours.
    if len(args) >= 4 and args[2] == "--config":
        config_path = Path(args[3])
        if not config_path.is_absolute():
            return False
        resolved_config = config_path.resolve()
        resolved_root = root.resolve()
        if resolved_config != resolved_root and resolved_root not in resolved_config.parents:
            return False
    return True


def _install_mcp_json(root: Path) -> str:
    """Write/refresh the wikitoolkit entry plus one managed entry per
    enabled toolkit section in the project's .mcp.json (FEAT-485).

    ``.mcp.json`` lives at the project root (NOT inside ``.claude/``) and
    may already carry entries for other MCP servers. Reconciliation only
    ever touches the ``"wikitoolkit"`` key (unchanged, byte-identical
    behavior) and managed ``"parrot-<name>"`` keys — see
    :func:`_is_managed_toolkit_entry` for the detection rule. Any other
    entry, and any ``parrot-<name>`` entry that does not match the managed
    shape, is left completely untouched; a colliding foreign
    ``parrot-<name>`` name is reported as a warning and skipped instead of
    being overwritten.
    """
    path = root / ".mcp.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    entry = assets.mcp_json_entry(root)

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = data["mcpServers"] = {}

    changed = False
    if servers.get("wikitoolkit") == entry:
        wikitoolkit_status = "wikitoolkit entry already current"
    else:
        wikitoolkit_status = "wikitoolkit entry updated" if "wikitoolkit" in servers else "wikitoolkit entry added"
        servers["wikitoolkit"] = entry
        changed = True

    # --- toolkit reconciliation (FEAT-485) --------------------------------
    from parrot.mcp.toolkit_config import load_toolkits_config

    cfg = load_toolkits_config(root)
    enabled_names = {name for name, section in cfg.toolkits.items() if section.enabled}

    added: list[str] = []
    updated: list[str] = []
    removed: list[str] = []

    for name in sorted(enabled_names):
        key = f"parrot-{name}"
        toolkit_entry = assets.toolkit_mcp_json_entry(root, name, cfg.toolkits[name])
        existing = servers.get(key)
        if existing == toolkit_entry:
            continue
        if existing is not None and not _is_managed_toolkit_entry(existing, root, name):
            print(
                f"Warning: .mcp.json — '{key}' already exists and was not written by "
                "`parrot claude install`; leaving it untouched.",
                file=sys.stderr,
            )
            continue
        servers[key] = toolkit_entry
        changed = True
        (updated if existing is not None else added).append(key)

    for key in [k for k in servers if k != "wikitoolkit" and k.startswith("parrot-")]:
        name = key[len("parrot-") :]
        if name in enabled_names:
            continue
        if _is_managed_toolkit_entry(servers[key], root, name):
            del servers[key]
            changed = True
            removed.append(key)

    if not changed:
        return f".mcp.json — {wikitoolkit_status}"

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    parts = [wikitoolkit_status]
    if added:
        parts.append(f"{len(added)} toolkit entry(s) added ({', '.join(added)})")
    if updated:
        parts.append(f"{len(updated)} toolkit entry(s) updated ({', '.join(updated)})")
    if removed:
        parts.append(f"{len(removed)} toolkit entry(s) removed ({', '.join(removed)})")
    return ".mcp.json — " + "; ".join(parts)


def _uninstall_mcp_json(root: Path) -> tuple[str | None, list[str]]:
    """Remove the wikitoolkit entry and all managed toolkit entries.

    Preserves any other MCP server entries (including foreign
    ``parrot-<name>`` entries that do not match the managed shape);
    removes the file entirely only when it becomes empty.

    Returns:
        A tuple of (action string or ``None`` when nothing was removed —
        mirrors every other uninstall step in this module, which only
        appends to ``actions`` when something was actually removed —, and
        the list of ``parrot-<name>`` keys confirmed managed and removed,
        for `_uninstall_mcp_approval` to strip the matching approvals
        without blanket-stripping every `parrot-*` name).
    """
    path = root / ".mcp.json"
    if not path.exists():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ".mcp.json — could not parse, skipping", []
    if not isinstance(data, dict):
        return None, []

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return None, []

    removed: list[str] = []
    if "wikitoolkit" in servers:
        del servers["wikitoolkit"]
        removed.append("wikitoolkit")

    toolkit_names_removed: list[str] = []
    for key in [k for k in servers if k != "wikitoolkit" and k.startswith("parrot-")]:
        name = key[len("parrot-") :]
        if _is_managed_toolkit_entry(servers[key], root, name):
            del servers[key]
            removed.append(key)
            toolkit_names_removed.append(key)

    if not removed:
        return None, []

    if not servers:
        data.pop("mcpServers", None)
    if not data:
        path.unlink()
        return ".mcp.json — removed (was empty)", toolkit_names_removed
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if removed == ["wikitoolkit"]:
        return ".mcp.json — wikitoolkit entry removed", toolkit_names_removed
    return f".mcp.json — managed entries removed ({', '.join(removed)})", toolkit_names_removed


def _install_slash_command(root: Path) -> str:
    """Write the /parrotwiki slash command file."""
    path = root / ".claude" / "commands" / assets.SLASH_COMMAND_FILENAME
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == assets.SLASH_COMMAND_MD:
        return ".claude/commands/parrotwiki.md — already current"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(assets.SLASH_COMMAND_MD, encoding="utf-8")
    return ".claude/commands/parrotwiki.md — " + ("updated" if existing is not None else "created")


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


#: Interpreter basenames whose syntax accepts the POSIX-sh redirection
#: (`>/dev/null 2>&1`, `|| true`) used by :data:`assets.GIT_HOOK_BLOCK`.
_SH_FAMILY: frozenset[str] = frozenset(
    {
        "sh",
        "bash",
        "dash",
        "ash",
        "ksh",
        "ksh93",
        "mksh",
        "zsh",
    }
)


def _shebang_is_sh_compatible(first_line: str) -> bool:
    """Whether appending POSIX-sh syntax to this hook is safe.

    A missing shebang is treated as ``sh`` (git's default). The
    interpreter basename is matched exactly against :data:`_SH_FAMILY`
    rather than by substring, so ``csh``/``pwsh`` (which contain the
    substring ``"sh"`` but reject sh redirection syntax) are correctly
    rejected while ``#!/usr/bin/env bash`` is accepted.
    """
    if not first_line.startswith("#!"):
        return True
    tokens = first_line[2:].split()
    if not tokens:
        return True
    interpreter = PurePosixPath(tokens[0]).name
    if interpreter == "env" and len(tokens) > 1:
        interpreter = PurePosixPath(tokens[1]).name
    return interpreter in _SH_FAMILY


def _install_git_hook(root: Path) -> str:
    """Install (or chain into) the git post-commit auto-upsert hook."""
    hook_path = _git_hook_path(root)
    if hook_path is None:
        return "git hook — skipped (not a git repository)"
    block = assets.git_hook_block(root)
    new_file = assets.git_hook_new_file(root)
    if hook_path.exists():
        text = hook_path.read_text(encoding="utf-8")
        if assets.GIT_HOOK_BEGIN in text:
            return "git post-commit hook — already installed"
        first_line = text.splitlines()[0] if text.strip() else ""
        if not _shebang_is_sh_compatible(first_line):
            # Appending sh syntax to a python/node/csh hook would break it.
            return (
                "git post-commit hook — skipped (existing hook is not a "
                "shell script; add `wikitoolkit upsert --changed --quiet` "
                "to it manually)"
            )
        if not text.endswith("\n"):
            text += "\n"
        hook_path.write_text(text + block, encoding="utf-8")
        action = "git post-commit hook — chained into existing hook"
    else:
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(new_file, encoding="utf-8")
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
    bookstore: bool = True,
    toolkits: Sequence[str] = (),
    approve_mcp: bool = True,
) -> list[str]:
    """Install the wiki ↔ Claude Code integration into a repository.

    Args:
        root: Repository root.
        config: Wiki project config; loaded/created when omitted.
        git_hook: Install the git post-commit auto-upsert hook.
        gitignore: Add ``.parrot/`` to .gitignore.
        bookstore: Install the Bookstore MCP server and skill when an
            indexed library exists (no indexing performed).
        toolkits: Toolkit template names to seed into
            `.parrot/mcp-toolkits.yaml` before `.mcp.json` reconciliation.
            Empty seeds nothing (spec §8 Q1: opt-in).
        approve_mcp: Authorize the managed servers in
            `.claude/settings.local.json` after reconciliation.

    Returns:
        Human-readable list of actions performed.
    """
    root = root.resolve()
    config = config or load_effective_config(root).config
    existed = config_path(root).exists()
    # Migrate an older config's nudge tools to include ``Bash`` so shell
    # searches are nudged after an upgrade — but only from the exact old
    # default, never overriding a user's customised list.
    migrated = False
    if config.claude.nudge_tools == ["Grep", "Glob", "Read"]:
        config.claude.nudge_tools = ["Grep", "Glob", "Read", "Bash"]
        migrated = True
    if not existed:
        actions = [f".parrot/wiki.json — config written " f"(wiki '{config.wiki_name}', backend {config.backend})"]
    elif migrated:
        actions = [".parrot/wiki.json — nudge tools upgraded (added Bash)"]
    else:
        actions = [".parrot/wiki.json — config already present"]
    save_project_config(root, config)

    actions.append(_install_claude_md(root))
    actions.append(_install_settings_hook(root))
    actions.extend(_install_permissions(root))
    if toolkits:
        from parrot.mcp.toolkit_seed import seed_toolkit_sections

        seeded = seed_toolkit_sections(root, toolkits)
        if seeded.created_file:
            actions.append(".parrot/mcp-toolkits.yaml — created")
        if seeded.added:
            actions.append(
                f".parrot/mcp-toolkits.yaml — added {len(seeded.added)} section(s) ({', '.join(seeded.added)})"
            )
        if seeded.skipped:
            actions.append(
                f".parrot/mcp-toolkits.yaml — {len(seeded.skipped)} section(s) already present "
                f"({', '.join(seeded.skipped)})"
            )
        if seeded.unknown:
            actions.append(f".parrot/mcp-toolkits.yaml — unknown template(s) skipped ({', '.join(seeded.unknown)})")
    actions.append(_install_mcp_json(root))
    if approve_mcp:
        actions.append(_install_mcp_approval(root))
    actions.append(_install_slash_command(root))
    if git_hook:
        actions.append(_install_git_hook(root))
    if gitignore:
        actions.append(_install_gitignore(root))
    if bookstore:
        from .bookstore import install_bookstore

        actions.extend(install_bookstore(root))
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

    from .bookstore import uninstall_bookstore

    actions.extend(uninstall_bookstore(root))

    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        text = claude_md.read_text(encoding="utf-8")
        updated = _remove_marker_block(text, assets.CLAUDE_MD_BEGIN, assets.CLAUDE_MD_END)
        if updated != text:
            claude_md.write_text(updated, encoding="utf-8")
            actions.append("CLAUDE.md — wiki section removed")

    # --- shared settings.json: remove hook + any legacy permissions ------
    settings_path = root / ".claude" / "settings.json"
    try:
        settings = _load_settings(settings_path)
    except RuntimeError:
        settings = None
    if isinstance(settings, dict):
        dirty = False
        hooks = settings.get("hooks")
        pre = hooks.get("PreToolUse", []) if isinstance(hooks, dict) else []
        if isinstance(pre, list):
            # Strip our handler rather than the whole entry: a user may have
            # added their own command alongside it, and that is not ours to
            # remove.
            kept = []
            removed = False
            for entry in pre:
                if not (isinstance(entry, dict) and _is_our_hook(entry)):
                    kept.append(entry)
                    continue
                removed = True
                foreign = [h for h in entry.get("hooks", []) if not _is_our_command(h.get("command"))]
                if foreign:
                    # Entries are mutated in place, so `kept` and `pre` can
                    # stay equal even here — hence the explicit flag.
                    entry["hooks"] = foreign
                    kept.append(entry)
            if removed:
                settings["hooks"]["PreToolUse"] = kept
                if not kept:
                    settings["hooks"].pop("PreToolUse")
                if not settings["hooks"]:
                    settings.pop("hooks")
                dirty = True
                actions.append(".claude/settings.json — PreToolUse hook removed")
        permissions = settings.get("permissions")
        allow = permissions.get("allow", []) if isinstance(permissions, dict) else []
        if isinstance(allow, list):
            kept_allow = [r for r in allow if r not in assets.PERMISSION_RULES]
            if len(kept_allow) != len(allow):
                settings["permissions"]["allow"] = kept_allow
                if not kept_allow:
                    settings["permissions"].pop("allow")
                if not settings["permissions"]:
                    settings.pop("permissions")
                dirty = True
                actions.append(".claude/settings.json — wikitoolkit permissions removed")
        if dirty:
            _write_settings(settings_path, settings)

    # --- settings.local.json: remove permissions -----------------------
    local_path = root / ".claude" / "settings.local.json"
    try:
        local = _load_settings(local_path)
    except RuntimeError:
        local = None
    if isinstance(local, dict):
        l_perms = local.get("permissions")
        l_allow = l_perms.get("allow", []) if isinstance(l_perms, dict) else []
        if isinstance(l_allow, list):
            # Remove both the static rules and any absolute-path variants
            # that a previous install may have written.
            all_rules = assets.permission_rules(root)
            kept_local = [r for r in l_allow if r not in all_rules]
            if len(kept_local) != len(l_allow):
                local["permissions"]["allow"] = kept_local
                if not kept_local:
                    local["permissions"].pop("allow")
                if not local.get("permissions"):
                    local.pop("permissions", None)
                _write_settings(local_path, local)
                actions.append(".claude/settings.local.json — wikitoolkit " "permissions removed")

    mcp_json_action, removed_toolkit_names = _uninstall_mcp_json(root)
    if mcp_json_action:
        actions.append(mcp_json_action)

    approval_action = _uninstall_mcp_approval(root, removed_toolkit_names)
    if approval_action:
        actions.append(approval_action)

    command_path = root / ".claude" / "commands" / assets.SLASH_COMMAND_FILENAME
    if command_path.exists():
        command_path.unlink()
        actions.append(".claude/commands/parrotwiki.md — removed")

    hook_path = _git_hook_path(root)
    if hook_path and hook_path.exists():
        text = hook_path.read_text(encoding="utf-8")
        if assets.GIT_HOOK_BEGIN in text:
            updated = _remove_marker_block(text, assets.GIT_HOOK_BEGIN, assets.GIT_HOOK_END)
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
        config = load_effective_config(root).config
    except WikiConfigError:
        # Status is read-only — report against defaults rather than fail.
        config = WikiProjectConfig(wiki_name=root.name or "codebase")

    claude_md = root / "CLAUDE.md"
    claude_md_installed = claude_md.exists() and assets.CLAUDE_MD_BEGIN in claude_md.read_text(encoding="utf-8")

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
            hook_installed = any(isinstance(e, dict) and _is_our_hook(e) for e in pre)

    # Permissions live in settings.local.json (fall back to settings.json
    # for legacy installs).
    permissions_installed = False
    for sf in ("settings.local.json", "settings.json"):
        try:
            sf_data = _load_settings(root / ".claude" / sf)
        except RuntimeError:
            sf_data = None
        if isinstance(sf_data, dict):
            p_allow = (sf_data.get("permissions") or {}).get("allow", [])
            if isinstance(p_allow, list) and all(r in p_allow for r in assets.PERMISSION_RULES):
                permissions_installed = True
                break

    git_hook_file = _git_hook_path(root)
    git_hook_installed = bool(
        git_hook_file and git_hook_file.exists() and assets.GIT_HOOK_BEGIN in git_hook_file.read_text(encoding="utf-8")
    )

    mcp_json_path = root / ".mcp.json"
    mcp_json_installed = False
    if mcp_json_path.exists():
        try:
            mcp_data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            mcp_data = None
        if isinstance(mcp_data, dict):
            mcp_json_installed = "wikitoolkit" in mcp_data.get("mcpServers", {})

    # Compute mcp_approved (True when every _managed_server_names(root) entry appears in enabledMcpjsonServers)
    mcp_approved = False
    try:
        local_settings = _load_settings(root / ".claude" / "settings.local.json")
    except Exception:
        local_settings = None
    if isinstance(local_settings, dict):
        approved_servers = local_settings.get("enabledMcpjsonServers")
        if isinstance(approved_servers, list):
            try:
                managed_names = _managed_server_names(root)
                mcp_approved = all(name in approved_servers for name in managed_names)
            except Exception:
                pass

    from .bookstore import bookstore_status

    return {
        **bookstore_status(root),
        "root": str(root),
        "config": config_path(root).exists(),
        "wiki_built": config.is_built(root),
        "claude_md_section": claude_md_installed,
        "pre_tool_use_hook": hook_installed,
        "permissions": permissions_installed,
        "slash_command": (root / ".claude" / "commands" / assets.SLASH_COMMAND_FILENAME).exists(),
        "git_post_commit_hook": git_hook_installed,
        "mcp_json": mcp_json_installed,
        "mcp_servers_authorized": mcp_approved,
        "toolkits_yaml": (root / ".parrot" / "mcp-toolkits.yaml").exists(),
    }
