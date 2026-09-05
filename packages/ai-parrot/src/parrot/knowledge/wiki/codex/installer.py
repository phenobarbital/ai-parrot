"""Idempotent installer for Codex WikiToolkit infrastructure."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.wiki.codex import assets
from parrot.knowledge.wiki.project import WikiProjectConfig, config_path, load_effective_config, save_project_config

_TABLE_HEADER = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")


def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:
    """Insert or replace a marker-delimited block."""
    block = block.rstrip("\n")
    if begin in text:
        head, _, rest = text.partition(begin)
        tail = rest.partition(end)[2] if end in rest else "\n"
        return f"{head}{block}{tail}"
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    separator = "\n" if prefix else ""
    return f"{prefix}{separator}{block}\n"


def _remove_marker_block(text: str, begin: str, end: str) -> str:
    """Remove a marker-delimited block, including a truncated block."""
    if begin not in text:
        return text
    head, _, rest = text.partition(begin)
    tail = rest.partition(end)[2] if end in rest else ""
    head = head.rstrip(" \t\n")
    tail = tail.lstrip("\n")
    if not head and not tail:
        return ""
    return f"{head}\n{tail}" if tail else f"{head}\n"


def _validate_toml(path: Path, text: str) -> None:
    """Fail before changing a user-owned invalid TOML file."""
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Cannot parse {path} — fix or remove it first: {exc}") from exc
    if not isinstance(value, dict):  # pragma: no cover - tomllib contract
        raise RuntimeError(f"{path} is not a TOML document")


def _remove_toml_table(text: str, table: str) -> str:
    """Remove one TOML table hierarchy while retaining unrelated tables."""
    lines = text.splitlines(keepends=True)
    start: Optional[int] = None
    end = len(lines)
    for index, line in enumerate(lines):
        match = _TABLE_HEADER.match(line.rstrip("\n"))
        if match is None:
            continue
        current = match.group(1).strip()
        is_target = current == table or current.startswith(f"{table}.")
        if start is None:
            if is_target:
                start = index
            continue
        if not is_target:
            end = index
            break
    if start is None:
        return text
    return "".join(lines[:start] + lines[end:]).rstrip("\n") + "\n"


def _install_agents(root: Path) -> str:
    path = root / "AGENTS.md"
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    after = _upsert_marker_block(
        before,
        assets.AGENTS_SECTION,
        assets.AGENTS_BEGIN,
        assets.AGENTS_END,
    )
    if after != before:
        path.write_text(after, encoding="utf-8")
        return f"AGENTS.md — wiki section {'updated' if before else 'created'}"
    return "AGENTS.md — wiki section already current"


def _install_skill(root: Path) -> str:
    path = root / assets.SKILL_PATH
    before = path.read_text(encoding="utf-8") if path.exists() else None
    if before == assets.SKILL:
        return f"{assets.SKILL_PATH} — already current"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(assets.SKILL, encoding="utf-8")
    return f"{assets.SKILL_PATH} — {'updated' if before is not None else 'created'}"


def _existing_table_names(text: str) -> set[str]:
    """Top-level TOML table header names present in ``text``."""
    names: set[str] = set()
    for line in text.splitlines():
        match = _TABLE_HEADER.match(line)
        if match is not None:
            names.add(match.group(1).strip())
    return names


def _install_mcp(root: Path) -> str:
    """Write/refresh the managed MCP block: wikitoolkit table plus one
    ``[mcp_servers.parrot-<name>]`` table per enabled toolkit section
    (FEAT-485). Re-running regenerates the whole managed block from
    config — that IS the reconciliation (disabled/deleted sections simply
    disappear from the regenerated block; no per-table tracking needed).

    A toolkit name colliding with a table already present OUTSIDE the
    managed marker block is never overwritten: it is reported as a
    warning on stderr and omitted from our managed block instead (mirrors
    the Claude Code installer's warn-and-skip semantics for `.mcp.json`).
    """
    from parrot.mcp.toolkit_config import load_toolkits_config

    path = root / ".codex" / "config.toml"
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    _validate_toml(path, before)
    without_managed = _remove_marker_block(before, assets.MCP_BEGIN, assets.MCP_END)
    without_existing = _remove_toml_table(without_managed, assets.MCP_TABLE)

    cfg = load_toolkits_config(root)
    existing_tables = _existing_table_names(without_existing)

    sections = {}
    for name, section in cfg.toolkits.items():
        if not section.enabled:
            continue
        table_name = f"mcp_servers.parrot-{name}"
        if table_name in existing_tables:
            print(
                f"Warning: .codex/config.toml — '[{table_name}]' already exists outside "
                "the managed block and was not written by `parrot codex install`; "
                "omitting it from the managed MCP block.",
                file=sys.stderr,
            )
            continue
        sections[name] = section

    toolkit_block = assets.toolkit_mcp_block(root, sections)
    after = _upsert_marker_block(
        # Replace an existing block in place: removing and appending it would
        # reorder adjacent managed integrations (such as Bookstore) on rerun.
        before if assets.MCP_BEGIN in before else without_existing,
        assets.mcp_block(root, toolkit_block),
        assets.MCP_BEGIN,
        assets.MCP_END,
    )
    _validate_toml(path, after)
    if after == before:
        return ".codex/config.toml — wikitoolkit MCP already current"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(after, encoding="utf-8")
    if sections:
        names = ", ".join(f"parrot-{name}" for name in sorted(sections))
        return (
            ".codex/config.toml — wikitoolkit MCP installed with automatic tool approval; "
            f"{len(sections)} toolkit table(s) ({names})"
        )
    return ".codex/config.toml — wikitoolkit MCP installed with automatic tool approval"


def _install_rules(root: Path) -> str:
    path = root / assets.RULES_PATH
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    after = _upsert_marker_block(
        before,
        assets.rules_block(root),
        assets.RULES_BEGIN,
        assets.RULES_END,
    )
    if after == before:
        return f"{assets.RULES_PATH} — WikiToolkit command surfaces already allowed"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(after, encoding="utf-8")
    return f"{assets.RULES_PATH} — WikiToolkit command surfaces allowed"


def _install_gitignore(root: Path) -> str:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    ignored = {".parrot", ".parrot/", "/.parrot", "/.parrot/"}
    if any(line.strip() in ignored for line in text.splitlines()):
        return ".gitignore — .parrot/ already ignored"
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(
        text + "# parrot LLM-wiki state (local retrieval plane)\n.parrot/\n",
        encoding="utf-8",
    )
    return ".gitignore — added .parrot/"


def install_codex_integration(
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    gitignore: bool = True,
    bookstore: bool = True,
) -> list[str]:
    """Install project-scoped Codex instructions, skill, MCP, and rules."""
    root = root.resolve()
    config = config or load_effective_config(root).config
    existed = config_path(root).exists()
    save_project_config(root, config)
    actions = [
        (
            ".parrot/wiki.json — config already present"
            if existed
            else f".parrot/wiki.json — config written (wiki '{config.wiki_name}', backend {config.backend})"
        ),
        _install_agents(root),
        _install_skill(root),
        _install_mcp(root),
        _install_rules(root),
    ]
    if gitignore:
        actions.append(_install_gitignore(root))
    if bookstore:
        from .bookstore import install_bookstore

        actions.extend(install_bookstore(root))
    return actions


def uninstall_codex_integration(root: Path) -> list[str]:
    """Remove only Codex artifacts managed by this installer."""
    root = root.resolve()
    actions: list[str] = []
    from .bookstore import uninstall_bookstore

    actions.extend(uninstall_bookstore(root))

    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        before = agents_path.read_text(encoding="utf-8")
        after = _remove_marker_block(before, assets.AGENTS_BEGIN, assets.AGENTS_END)
        if after != before:
            agents_path.write_text(after, encoding="utf-8")
            actions.append("AGENTS.md — wiki section removed")

    skill_path = root / assets.SKILL_PATH
    if skill_path.exists() and skill_path.read_text(encoding="utf-8") == assets.SKILL:
        skill_path.unlink()
        actions.append(f"{assets.SKILL_PATH} — removed")

    config_file = root / ".codex" / "config.toml"
    if config_file.exists():
        before = config_file.read_text(encoding="utf-8")
        _validate_toml(config_file, before)
        after = _remove_marker_block(before, assets.MCP_BEGIN, assets.MCP_END)
        if after != before:
            config_file.write_text(after, encoding="utf-8")
            actions.append(".codex/config.toml — wikitoolkit MCP removed")

    rules_path = root / assets.RULES_PATH
    if rules_path.exists():
        before = rules_path.read_text(encoding="utf-8")
        after = _remove_marker_block(before, assets.RULES_BEGIN, assets.RULES_END)
        if after != before:
            if after.strip():
                rules_path.write_text(after, encoding="utf-8")
            else:
                rules_path.unlink()
            actions.append(f"{assets.RULES_PATH} — WikiToolkit permissions removed")

    if not actions:
        actions.append("nothing to remove — integration not installed")
    return actions


def integration_status(root: Path) -> dict[str, Any]:
    """Report whether each Codex integration artifact is installed."""
    root = root.resolve()
    config = load_effective_config(root).config
    agents_path = root / "AGENTS.md"
    codex_config = root / ".codex" / "config.toml"
    rules_path = root / assets.RULES_PATH

    # FEAT-485: count enabled toolkit sections actually present as managed
    # tables inside the current MCP block (0 when the block is absent or
    # a name collided and was omitted at install time).
    toolkit_count = 0
    if codex_config.exists():
        text = codex_config.read_text(encoding="utf-8")
        if assets.MCP_BEGIN in text:
            _, _, rest = text.partition(assets.MCP_BEGIN)
            block = rest.partition(assets.MCP_END)[0]
            toolkit_count = len(re.findall(r"^\[mcp_servers\.parrot-", block, flags=re.MULTILINE))

    from .bookstore import bookstore_status

    return {
        **bookstore_status(root),
        "root": str(root),
        "config": config_path(root).exists(),
        "wiki_built": config.is_built(root),
        "agents_md_section": agents_path.exists() and assets.AGENTS_BEGIN in agents_path.read_text(encoding="utf-8"),
        "skill": (root / assets.SKILL_PATH).exists(),
        "mcp": codex_config.exists() and assets.MCP_BEGIN in codex_config.read_text(encoding="utf-8"),
        "toolkit_count": toolkit_count,
        "permissions": rules_path.exists() and assets.RULES_BEGIN in rules_path.read_text(encoding="utf-8"),
    }
