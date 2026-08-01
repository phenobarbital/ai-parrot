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
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

try:  # POSIX only — see wiki_write_lock().
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

#: Directory (relative to repo root) holding parrot project state.
PARROT_DIR = ".parrot"

#: Config filename inside :data:`PARROT_DIR`.
CONFIG_FILENAME = "wiki.json"

#: Lock filename inside the wiki storage directory, guarding writers.
LOCK_FILENAME = "wiki.lock"

#: Poll interval while waiting for a contended lock.
_LOCK_POLL_SECONDS = 0.05


@contextmanager
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:
    """Hold the exclusive writer lock for a wiki store.

    A full ``build`` rewrites the entire store and can run for many
    minutes, while the git post-commit hook fires ``upsert --changed``
    on its own schedule. Without mutual exclusion the two write the
    same SQLite file concurrently.

    The lock lives **beside the store**, not at the repository root:
    ``storage_dir`` may be absolute, so two repositories can share one
    store and must contend on the same lock for it to mean anything.
    Pass :meth:`WikiProjectConfig.storage_path`, never the repo root.

    It is advisory: the context manager yields whether the lock was
    acquired and lets the caller decide what that means. ``build``
    refuses; ``upsert`` waits briefly (so back-to-back commits are not
    silently dropped) and then skips, because a commit hook must never
    stall behind a multi-minute build. The lock is held via ``flock``
    on an open descriptor, so the kernel releases it if the holder
    crashes — no stale lock file can wedge the wiki.

    On platforms without :mod:`fcntl` it degrades to a no-op and always
    yields ``True``: no protection, but no false blocking either.

    Args:
        store_dir: Directory holding the wiki store, created if absent.
        timeout: Seconds to keep retrying before giving up. ``0.0``
            (the default) tries exactly once.

    Yields:
        ``True`` when the lock is held by this caller, ``False`` when
        another process holds it.
    """
    store_dir.mkdir(parents=True, exist_ok=True)
    handle = open(store_dir / LOCK_FILENAME, "a+")  # noqa: SIM115 - closed below
    try:
        if fcntl is None:  # pragma: no cover - non-POSIX platform
            yield True
            return

        deadline = time.monotonic() + max(timeout, 0.0)
        acquired = False
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(_LOCK_POLL_SECONDS)

        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class ClaudeIntegrationConfig(BaseModel):
    """Settings for the Claude Code integration.

    Attributes:
        nudge_cooldown_seconds: Minimum seconds between two hook
            nudges, so search-heavy turns are not spammed.
        nudge_tools: Tool names the PreToolUse nudge applies to.
    """

    nudge_cooldown_seconds: int = Field(default=60, ge=0)
    nudge_tools: list[str] = Field(
        default_factory=lambda: ["Grep", "Glob", "Read", "Bash"]
    )


class WikiProjectConfig(BaseModel):
    """Repository-level wiki configuration (``.parrot/wiki.json``).

    Attributes:
        wiki_name: Wiki identifier; defaults to the repo directory name.
        storage_dir: Wiki storage directory, relative to the repo root.
        backend: Retrieval-plane backend (``sqlite``, ``memory``, or
            ``arangodb``).
        include_suffixes: File suffixes scanned into the wiki; empty
            means the scanner defaults.
        exclude_dirs: Extra directory names pruned during scans.
        body_max_chars: Cap on stored page body length.
        max_file_kb: Files larger than this many KiB are skipped.
        claude: Claude Code integration settings.
        sync_graph: When ``True``, authoring commands (``remember`` /
            ``link``) also mirror their writes into the project's
            GraphIndex plane (``.parrot/graph/``) as audited commits.
        arango_database: ArangoDB database name for the ``arangodb``
            backend; defaults to ``wiki_{wiki_name}`` when omitted.
        arango_credentials_env: Env var prefix used to resolve ArangoDB
            credentials (e.g. ``ARANGODB`` -> ``ARANGODB_HOST``,
            ``ARANGODB_PASSWORD``, ...).
        arango_text_analyzer: ArangoSearch text analyzer used for the
            pages view's full-text search (e.g. ``"text_en"``).
    """

    wiki_name: str = Field(default="codebase")
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")
    include_suffixes: list[str] = Field(default_factory=list)
    exclude_dirs: list[str] = Field(default_factory=list)
    body_max_chars: int = Field(default=16_000, ge=1_000)
    max_file_kb: int = Field(default=512, ge=1)
    claude: ClaudeIntegrationConfig = Field(
        default_factory=ClaudeIntegrationConfig
    )
    sync_graph: bool = Field(default=False)
    arango_database: Optional[str] = Field(
        default=None,
        description="ArangoDB database name; defaults to wiki_{wiki_name}",
    )
    arango_credentials_env: str = Field(
        default="ARANGODB",
        description=(
            "Env var prefix for credentials (e.g. ARANGODB -> "
            "ARANGODB_HOST, ARANGODB_PASSWORD)"
        ),
    )
    arango_text_analyzer: str = Field(
        default="text_en",
        description="ArangoSearch text analyzer for FTS",
    )

    def graph_path(self, root: Path) -> Path:
        """Directory of the project's GraphIndex plane (``.parrot/graph``)."""
        return root / PARROT_DIR / "graph"

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


def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]:
    """Resolve ArangoDB connection params from environment variables.

    Credentials are never hardcoded in ``wiki.json`` — only the env var
    prefix (:attr:`WikiProjectConfig.arango_credentials_env`, default
    ``"ARANGODB"``) and the database name are configurable there. This
    mirrors the established ``ARANGODB_*`` convention used elsewhere in
    the codebase (e.g. ``graphindex/loader.py``).

    Args:
        config: Project config carrying the ArangoDB backend settings.

    Returns:
        Connection params dict for ``AsyncDB("arangodb", params=...)``:
        ``host``, ``port``, ``protocol``, ``username``, ``password``,
        ``database``.
    """
    prefix = config.arango_credentials_env
    return {
        "host": os.environ.get(f"{prefix}_HOST", "127.0.0.1"),
        "port": int(os.environ.get(f"{prefix}_PORT", "8529")),
        "protocol": os.environ.get(f"{prefix}_PROTOCOL", "http"),
        "username": os.environ.get(f"{prefix}_USERNAME", "root"),
        "password": os.environ.get(f"{prefix}_PASSWORD", ""),
        "database": config.arango_database or f"wiki_{config.wiki_name}",
    }


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
