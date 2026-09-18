"""One adapter contract over three asymmetric MCP hosts (FEAT-570, spec §3 M1).

Claude Code, Codex and Google Antigravity differ in config format, ownership
detection and — critically — scope: Google's primary config is USER-GLOBAL.
`parrot toolkits` talks to this protocol, never to a host's private helpers.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, Sequence

from pydantic import BaseModel


class HostKind(str, Enum):
    """The MCP hosts `parrot toolkits` can register a toolkit with."""

    CLAUDE = "claude"
    CODEX = "codex"
    GOOGLE = "google"


class HostEntryState(BaseModel):
    """One toolkit's entry state in one host."""

    host: HostKind
    config_paths: tuple[Path, ...]
    config_present: bool
    repo_scoped: bool
    managed: bool
    foreign: bool


class HostAdapter(Protocol):
    """One MCP host's toolkit-entry surface. Implementations NEVER touch wikitoolkit."""

    kind: HostKind

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        """Config files this host reads, most significant first."""

    def is_repo_scoped(self) -> bool:
        """False when the primary config is user-global (Google only)."""

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        """Per-toolkit entry state. Reads config files only; imports no toolkit."""

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        """Rewrite ONLY this host's `parrot-<name>` entries. Returns (actions, warnings)."""

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        """Claude Code only; returns None elsewhere."""


class ClaudeAdapter:
    """Claude Code — repo `.mcp.json`, per-entry managed-shape ownership, approvals."""

    kind = HostKind.CLAUDE

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        return (root / ".mcp.json",)

    def is_repo_scoped(self) -> bool:
        return True

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        from parrot.knowledge.wiki.claude_code.installer import _is_managed_toolkit_entry

        path = root / ".mcp.json"
        config_present = path.exists()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if config_present else {}
        except (OSError, ValueError):
            data = {}
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        servers = servers if isinstance(servers, dict) else {}

        states: dict[str, HostEntryState] = {}
        for name in names:
            entry = servers.get(f"parrot-{name}")
            managed = _is_managed_toolkit_entry(entry, root, name)
            states[name] = HostEntryState(
                host=self.kind,
                config_paths=self.config_paths(root),
                config_present=config_present,
                repo_scoped=self.is_repo_scoped(),
                managed=managed,
                foreign=entry is not None and not managed,
            )
        return states

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.claude_code.installer import reconcile_toolkit_entries

        return reconcile_toolkit_entries(root)

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        from parrot.knowledge.wiki.claude_code.installer import (
            install_toolkit_approvals,
            uninstall_toolkit_approvals,
        )

        if removed:
            # NEVER `_uninstall_mcp_approval` here: it also strips "wikitoolkit"
            # by design (it backs the FULL `parrot claude uninstall` path).
            # `uninstall_toolkit_approvals` is the toolkit-only sibling that
            # never touches wikitoolkit (FEAT-570 AC5).
            return uninstall_toolkit_approvals(root, removed)
        # NEVER `_install_mcp_approval` here: it merges `_managed_server_names`,
        # which unconditionally prepends "wikitoolkit" even when no wikitoolkit
        # `.mcp.json` entry exists (spec §7 Known Risk S3) — pre-authorizing a
        # server that was never installed. `install_toolkit_approvals` is the
        # toolkit-only sibling that never touches wikitoolkit (FEAT-570 AC5).
        return install_toolkit_approvals(root)


class CodexAdapter:
    """Codex — repo `.codex/config.toml`, STRUCTURAL ownership (managed marker block)."""

    kind = HostKind.CODEX

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        return (root / ".codex" / "config.toml",)

    def is_repo_scoped(self) -> bool:
        return True

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        from parrot.knowledge.wiki.codex import assets as codex_assets
        from parrot.knowledge.wiki.codex.installer import _existing_table_names

        path = root / ".codex" / "config.toml"
        config_present = path.exists()
        text = path.read_text(encoding="utf-8") if config_present else ""

        if codex_assets.MCP_BEGIN in text:
            head, _, rest = text.partition(codex_assets.MCP_BEGIN)
            if codex_assets.MCP_END in rest:
                block_body, _, tail = rest.partition(codex_assets.MCP_END)
            else:
                block_body, tail = rest, ""
            inside_tables = _existing_table_names(block_body)
            outside_text = head + tail
        else:
            inside_tables = set()
            outside_text = text
        outside_tables = _existing_table_names(outside_text)

        states: dict[str, HostEntryState] = {}
        for name in names:
            table_name = f"mcp_servers.parrot-{name}"
            managed = table_name in inside_tables
            foreign = (not managed) and table_name in outside_tables
            states[name] = HostEntryState(
                host=self.kind,
                config_paths=self.config_paths(root),
                config_present=config_present,
                repo_scoped=self.is_repo_scoped(),
                managed=managed,
                foreign=foreign,
            )
        return states

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.codex.installer import reconcile_toolkit_tables

        return reconcile_toolkit_tables(root)

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        return None


class GoogleAdapter:
    """Antigravity — USER-GLOBAL `~/.gemini/config/mcp_config.json` + repo plugin file."""

    kind = HostKind.GOOGLE

    def __init__(self, mcp_path: Optional[Path] = None) -> None:
        """Accepts an override so tests never touch the real home directory."""
        self._mcp_path = mcp_path

    def config_paths(self, root: Path) -> tuple[Path, ...]:
        from parrot.knowledge.wiki.google.installer import toolkit_config_paths

        return toolkit_config_paths(root, self._mcp_path)

    def is_repo_scoped(self) -> bool:
        return False

    def inspect(self, root: Path, names: Sequence[str]) -> dict[str, HostEntryState]:
        from parrot.knowledge.wiki.google.installer import _is_managed_toolkit_entry

        primary_path = self.config_paths(root)[0]
        config_present = primary_path.exists()
        try:
            data = json.loads(primary_path.read_text(encoding="utf-8")) if config_present else {}
        except (OSError, ValueError):
            data = {}
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        servers = servers if isinstance(servers, dict) else {}

        states: dict[str, HostEntryState] = {}
        for name in names:
            entry = servers.get(f"parrot-{name}")
            managed = _is_managed_toolkit_entry(entry, root, name)
            states[name] = HostEntryState(
                host=self.kind,
                config_paths=self.config_paths(root),
                config_present=config_present,
                repo_scoped=False,
                managed=managed,
                foreign=entry is not None and not managed,
            )
        return states

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.google.installer import reconcile_toolkit_entries

        return reconcile_toolkit_entries(root, self._mcp_path)

    def sync_approvals(self, root: Path, removed: Sequence[str] = ()) -> Optional[str]:
        return None


def get_adapter(kind: HostKind) -> HostAdapter:
    """Return the adapter for `kind`."""
    return {HostKind.CLAUDE: ClaudeAdapter(), HostKind.CODEX: CodexAdapter(), HostKind.GOOGLE: GoogleAdapter()}[kind]


def detect_hosts(root: Path) -> list[HostKind]:
    """Hosts whose config already exists — the default target set for `parrot toolkits`.

    Spec §8 Q1 interim default (a): Google IS auto-detected when its user-global
    config exists, and callers warn that writing it affects every project on the
    machine (see `HostAdapter.is_repo_scoped`). Creates nothing.
    """
    detected: list[HostKind] = []
    for kind in HostKind:
        adapter = get_adapter(kind)
        if any(path.exists() for path in adapter.config_paths(root)):
            detected.append(kind)
    return detected
