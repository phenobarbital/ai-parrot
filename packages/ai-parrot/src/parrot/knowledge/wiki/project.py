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
import logging
import os
import re
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

#: Filename of the global (per-user) namespace registry inside ``PARROT_HOME``.
GLOBAL_REGISTRY_FILENAME = "wikis.json"

#: Separator between a namespace name and a page id (``ns::id``).
#: Mirrors :data:`parrot.knowledge.wiki.context.NS_SEPARATOR`; duplicated
#: here because ``project.py`` must stay importable on its own (hook path).
NS_SEPARATOR = "::"

#: Namespace names reserved by the routing surface (``--ns``).
RESERVED_NAMESPACE_NAMES = frozenset({"all", "local"})

#: Grammar for a namespace name. A single ``:`` is allowed (so ``legal:civil``
#: can mirror a GraphIndex namespace) but ``::`` never is — it is the id
#: separator.
_NAMESPACE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")

#: Poll interval while waiting for a contended lock.
_LOCK_POLL_SECONDS = 0.05

logger = logging.getLogger(__name__)


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


def validate_namespace_name(name: str) -> str:
    """Validate a federated namespace name.

    Names address a whole wiki plane on the CLI (``--ns <name>``) and
    prefix foreign page ids (``<name>::<id>``), so they must be free of
    the ``::`` separator and must not collide with the routing keywords
    ``all`` / ``local``.

    Args:
        name: Candidate namespace name.

    Returns:
        The validated name, unchanged.

    Raises:
        ValueError: When the name is empty, reserved, contains ``::``,
            or does not match ``^[A-Za-z0-9][A-Za-z0-9_.:-]*$``.
    """
    if not name:
        raise ValueError("Namespace name must not be empty")
    if name in RESERVED_NAMESPACE_NAMES:
        raise ValueError(
            f"Namespace name {name!r} is reserved "
            f"(reserved: {', '.join(sorted(RESERVED_NAMESPACE_NAMES))})"
        )
    if NS_SEPARATOR in name:
        raise ValueError(
            f"Namespace name {name!r} must not contain {NS_SEPARATOR!r} "
            "— it separates the namespace from the page id"
        )
    if not _NAMESPACE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid namespace name {name!r}: must match "
            f"{_NAMESPACE_NAME_RE.pattern}"
        )
    return name


class WikiNamespaceConfig(BaseModel):
    """One federated namespace: a named pointer to another wiki plane.

    Exactly one of :attr:`path`, :attr:`store`, :attr:`database` or
    :attr:`vault` must be set — that choice is the entry's :attr:`kind`
    and decides how :func:`parrot.knowledge.wiki.federation.resolve_namespaces`
    opens it.

    Relative ``path`` / ``store`` / ``vault`` values are resolved against
    the directory of the registry that declares them: the repo root for
    entries in ``.parrot/wiki.json``, and ``PARROT_HOME`` (``~/.parrot``)
    for entries in the global ``wikis.json`` — see
    :func:`resolve_entry_base`.

    Attributes:
        path: Root of another wiki project (its ``.parrot/wiki.json`` is
            loaded to find the plane).
        store: Pre-built store directory (holds ``wiki.db`` for sqlite).
        backend: Backend used for a ``store`` entry; forced to
            ``arangodb`` when :attr:`database` is set.
        database: ArangoDB database name holding the plane.
        credentials_env: Env var prefix for ArangoDB credentials.
        vault: Obsidian vault root; resolved exactly like :attr:`path`.
        description: Human-readable purpose, shown by ``ns list`` and
            reserved for v2 intent routing.
        weight: Multiplier applied to this namespace's normalised scores
            when merging broadcast results.
    """

    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(
        default=None, description="Another wiki project root"
    )
    store: str | None = Field(
        default=None, description="Pre-built store directory"
    )
    backend: Literal["sqlite", "memory", "arangodb"] = Field(
        default="sqlite", description="Backend for a `store` entry"
    )
    database: str | None = Field(
        default=None, description="ArangoDB database name"
    )
    credentials_env: str = Field(
        default="ARANGODB",
        description="Env var prefix for ArangoDB credentials",
    )
    vault: str | None = Field(
        default=None, description="Obsidian vault root"
    )
    description: str = Field(
        default="", description="Shown by `wikitoolkit ns list`"
    )
    weight: float = Field(default=1.0, ge=0.0, le=1.0)

    #: Source fields, in :attr:`kind` resolution order.
    _SOURCE_FIELDS = ("path", "store", "database", "vault")

    @model_validator(mode="after")
    def _check_exactly_one_source(self) -> WikiNamespaceConfig:
        """Enforce exactly one source field and derive the backend."""
        present = [
            name
            for name in ("path", "store", "database", "vault")
            if getattr(self, name)
        ]
        if len(present) != 1:
            raise ValueError(
                "Exactly one of path / store / database / vault must be set "
                f"(got: {', '.join(present) or 'none'})"
            )
        if self.database:
            # A `database` entry is ArangoDB by construction.
            object.__setattr__(self, "backend", "arangodb")
        return self

    @property
    def kind(self) -> Literal["path", "store", "database", "vault"]:
        """Which source field this entry uses."""
        for name in ("path", "store", "database", "vault"):
            if getattr(self, name):
                return name  # type: ignore[return-value]
        # Unreachable: the model validator guarantees exactly one.
        raise ValueError("Namespace entry has no source field")

    @property
    def target(self) -> str:
        """The value of the active source field (path / store / db / vault)."""
        return str(getattr(self, self.kind))


class GlobalWikiRegistry(BaseModel):
    """The per-user namespace registry stored at ``PARROT_HOME/wikis.json``.

    Attributes:
        version: Schema version of the registry file.
        namespaces: Namespace name -> entry.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    namespaces: dict[str, WikiNamespaceConfig] = Field(default_factory=dict)

    @field_validator("namespaces")
    @classmethod
    def _validate_names(
        cls, value: dict[str, WikiNamespaceConfig]
    ) -> dict[str, WikiNamespaceConfig]:
        for name in value:
            validate_namespace_name(name)
        return value


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
        namespaces: Federated namespaces declared by this repository,
            keyed by namespace name. Merged with the global registry
            (repo entries win) by :func:`merge_namespaces`. Written only
            by ``wikitoolkit ns add``.
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
    arango_database: str | None = Field(
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
    vault_dir: str | None = Field(
        default=None,
        description=(
            "Obsidian vault directory served by the wiki MCP server; "
            "absolute, or relative to the project root. When omitted, the "
            "project root itself is used if it is a vault (.obsidian/)."
        ),
    )
    namespaces: dict[str, WikiNamespaceConfig] = Field(
        default_factory=dict,
        description=(
            "Federated namespaces declared by this repo, keyed by name. "
            "Repo entries override same-named global registry entries."
        ),
    )

    @field_validator("namespaces")
    @classmethod
    def _validate_namespace_names(
        cls, value: dict[str, WikiNamespaceConfig]
    ) -> dict[str, WikiNamespaceConfig]:
        """Reject reserved/invalid namespace names at load time."""
        for name in value:
            validate_namespace_name(name)
        return value

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
        """Whether the retrieval plane exists for this repo.

        ``sqlite``/``memory`` are on-disk backends, so this is a cheap
        local file/directory probe. ``arangodb`` is server-hosted — there
        is no local artifact to check, and probing the server here would
        turn a synchronous config check into a network round-trip. The
        real "is it built" signal for ``arangodb`` is deferred to the
        store's own (idempotent) ``initialize()`` connection, which
        creates the database/collections/view on first use if missing.
        """
        if self.backend == "sqlite":
            return self.db_path(root).exists()
        if self.backend == "arangodb":
            return True
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


def resolve_vault_dir(
    root: Path,
    config: WikiProjectConfig,
    override: str | Path | None = None,
) -> Path | None:
    """Resolve the Obsidian vault directory for a wiki project.

    Precedence: explicit ``override`` > ``config.vault_dir`` (resolved
    against ``root`` when relative) > ``root`` itself when it is a vault
    (contains an ``.obsidian/`` directory).

    Args:
        root: Project root directory.
        config: Project configuration.
        override: Optional per-call vault path (e.g. a tool argument).

    Returns:
        The resolved, existing vault directory, or ``None`` when no vault
        is configured/detected (a configured-but-missing directory is
        logged and treated as absent).
    """
    from parrot.knowledge.wiki.vault_scan import is_obsidian_vault

    candidate: Path | None = None
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
    elif config.vault_dir:
        candidate = Path(config.vault_dir).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
    elif is_obsidian_vault(root):
        candidate = root

    if candidate is None:
        return None
    candidate = candidate.resolve()
    if not candidate.is_dir():
        logger.warning(
            "Configured Obsidian vault directory does not exist: %s", candidate
        )
        return None
    return candidate


def config_path(root: Path) -> Path:
    """Return the config file path for a repo root."""
    return root / PARROT_DIR / CONFIG_FILENAME


def find_project_root(start: Path | None = None) -> Path | None:
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
    git_root: Path | None = None
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


def parrot_home() -> Path:
    """Directory holding per-user parrot state (``~/.parrot``).

    Honours the ``PARROT_HOME`` environment variable so tests (and users
    with an unusual home layout) can relocate the global registry. The
    value is read on every call — never cached at import time — so a
    ``monkeypatch.setenv`` in a test is always seen.

    Returns:
        The expanded, absolute parrot home directory.
    """
    raw = os.environ.get("PARROT_HOME") or f"~/{PARROT_DIR}"
    return Path(raw).expanduser()


def global_registry_path() -> Path:
    """Path of the global namespace registry (``PARROT_HOME/wikis.json``)."""
    return parrot_home() / GLOBAL_REGISTRY_FILENAME


def load_global_registry(path: Path | None = None) -> GlobalWikiRegistry:
    """Load the per-user namespace registry.

    Args:
        path: Registry file; defaults to :func:`global_registry_path`.

    Returns:
        The parsed registry, or an empty one when the file does not
        exist (the common case — the file is created only by
        ``wikitoolkit ns add --global``).

    Raises:
        WikiConfigError: When the file exists but is not valid JSON or
            does not match the schema. Substituting an empty registry
            would silently drop the user's namespaces on the next save.
    """
    target = path or global_registry_path()
    if not target.exists():
        return GlobalWikiRegistry()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return GlobalWikiRegistry.model_validate(data)
    except (OSError, ValueError) as exc:
        raise WikiConfigError(
            f"Invalid global wiki registry at {target} — fix or remove it: {exc}"
        ) from exc


def save_global_registry(
    registry: GlobalWikiRegistry, path: Path | None = None
) -> Path:
    """Persist the per-user namespace registry atomically.

    The file may name private ArangoDB databases and paths outside the
    repo, so it is written ``0o600``. The write goes to a temp file in
    the same directory and is then ``os.replace``-d into place, so a
    crash mid-write can never leave a truncated registry behind.

    Args:
        registry: Registry to write.
        path: Destination; defaults to :func:`global_registry_path`.

    Returns:
        The path written.
    """
    target = path or global_registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(registry.model_dump(mode="json"), indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".wikis-", suffix=".json"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def merge_namespaces(
    repo: dict[str, WikiNamespaceConfig],
    global_: dict[str, WikiNamespaceConfig],
) -> dict[str, tuple[WikiNamespaceConfig, str]]:
    """Merge repo and global namespace declarations.

    A repository is the more specific context, so a name declared in
    both registries resolves to the repo entry (spec G2).

    Args:
        repo: Namespaces from ``.parrot/wiki.json``.
        global_: Namespaces from ``PARROT_HOME/wikis.json``.

    Returns:
        Mapping ``name -> (config, origin)`` where ``origin`` is
        ``"repo"`` or ``"global"``.
    """
    merged: dict[str, tuple[WikiNamespaceConfig, str]] = {
        name: (cfg, "global") for name, cfg in global_.items()
    }
    merged.update({name: (cfg, "repo") for name, cfg in repo.items()})
    return merged


def resolve_entry_base(origin: str, root: Path) -> Path:
    """Directory a namespace entry's relative paths resolve against.

    Args:
        origin: ``"repo"`` or ``"global"`` (as returned by
            :func:`merge_namespaces`).
        root: The repository root, used for ``"repo"`` entries.

    Returns:
        The repo root for repo entries, :func:`parrot_home` for global
        ones.
    """
    return root if origin == "repo" else parrot_home()
