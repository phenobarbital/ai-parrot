"""Per-repository wiki configuration for the ``wikitoolkit`` CLI.

A repository that uses the LLM Wiki as its codebase knowledge plane
carries a small JSON config at ``.parrot/wiki.json`` (relative to the
repo root).  The config records where the retrieval plane lives and
how the repo is scanned, and is what the Claude Code integration
(``parrot claude install``) reads to find the wiki from hooks.

All helpers here are dependency-light (stdlib + pydantic) so the
PreToolUse hook can import them with minimal startup cost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

#: Directory (relative to repo root) holding parrot project state.
PARROT_DIR = ".parrot"

#: Config filename inside :data:`PARROT_DIR`.
CONFIG_FILENAME = "wiki.json"


class ClaudeIntegrationConfig(BaseModel):
    """Settings for the Claude Code integration.

    Attributes:
        nudge_cooldown_seconds: Minimum seconds between two hook
            nudges, so search-heavy turns are not spammed.
        nudge_tools: Tool names the PreToolUse nudge applies to.
    """

    nudge_cooldown_seconds: int = Field(default=300, ge=0)
    nudge_tools: list[str] = Field(
        default_factory=lambda: ["Grep", "Glob", "Read"]
    )


class WikiProjectConfig(BaseModel):
    """Repository-level wiki configuration (``.parrot/wiki.json``).

    Attributes:
        wiki_name: Wiki identifier; defaults to the repo directory name.
        storage_dir: Wiki storage directory, relative to the repo root.
        backend: Retrieval-plane backend (``sqlite`` or ``memory``).
        include_suffixes: File suffixes scanned into the wiki; empty
            means the scanner defaults.
        exclude_dirs: Extra directory names pruned during scans.
        body_max_chars: Cap on stored page body length.
        max_file_kb: Files larger than this many KiB are skipped.
        claude: Claude Code integration settings.
    """

    wiki_name: str = Field(default="codebase")
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")
    backend: Literal["sqlite", "memory"] = Field(default="sqlite")
    include_suffixes: list[str] = Field(default_factory=list)
    exclude_dirs: list[str] = Field(default_factory=list)
    body_max_chars: int = Field(default=16_000, ge=1_000)
    max_file_kb: int = Field(default=512, ge=1)
    claude: ClaudeIntegrationConfig = Field(
        default_factory=ClaudeIntegrationConfig
    )

    def storage_path(self, root: Path) -> Path:
        """Resolve the wiki storage directory against the repo root."""
        storage = Path(self.storage_dir)
        return storage if storage.is_absolute() else root / storage

    def db_path(self, root: Path) -> Path:
        """Path of the SQLite retrieval plane (sqlite backend)."""
        return self.storage_path(root) / "wiki.db"

    def is_built(self, root: Path) -> bool:
        """Whether the retrieval plane exists on disk for this repo."""
        if self.backend == "sqlite":
            return self.db_path(root).exists()
        return (self.storage_path(root) / "pages").exists()


def config_path(root: Path) -> Path:
    """Return the config file path for a repo root."""
    return root / PARROT_DIR / CONFIG_FILENAME


def find_project_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk upwards from ``start`` to the nearest configured repo root.

    A directory is a wiki project root when it contains
    ``.parrot/wiki.json``; as a fallback, the nearest ``.git`` root is
    returned so ``wikitoolkit build`` can bootstrap a fresh repo.

    Args:
        start: Directory to start from (defaults to CWD).

    Returns:
        The project root, or ``None`` when neither marker is found.
    """
    current = (start or Path.cwd()).resolve()
    git_root: Optional[Path] = None
    for candidate in (current, *current.parents):
        if config_path(candidate).exists():
            return candidate
        if git_root is None and (candidate / ".git").exists():
            git_root = candidate
    return git_root


class WikiConfigError(ValueError):
    """Raised when an existing ``.parrot/wiki.json`` cannot be used."""


def load_project_config(root: Path) -> WikiProjectConfig:
    """Load the repo's wiki config.

    Args:
        root: Repository root.

    Returns:
        Parsed config; defaults (with ``wiki_name`` set to the repo
        directory name) when no config file exists.

    Raises:
        WikiConfigError: When a config file exists but is invalid —
            silently substituting defaults would let the next
            ``save_project_config`` clobber the user's settings.
    """
    path = config_path(root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WikiProjectConfig.model_validate(data)
        except (OSError, ValueError) as exc:
            raise WikiConfigError(
                f"Invalid wiki config at {path} — fix or remove it: {exc}"
            ) from exc
    return WikiProjectConfig(wiki_name=root.name or "codebase")


def save_project_config(root: Path, config: WikiProjectConfig) -> Path:
    """Persist the wiki config to ``.parrot/wiki.json``.

    Args:
        root: Repository root.
        config: Config to write.

    Returns:
        The path written.
    """
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return path
