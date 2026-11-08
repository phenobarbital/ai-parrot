"""Per-repository SDD configuration (`sdd/config.json`) — FEAT-633 rev 0.2, amendment C6."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from parrot.sdd.techwiki.config import TechwikiConfig

CONFIG_PATH = Path("sdd/config.json")
_BRANCH_FIELDS = ("base_branch", "staging_branch", "hotfix_base", "ledger_branch")


class SddConfigError(ValueError):
    """Raised when ``sdd/config.json`` exists but cannot be used."""


class SddConfig(BaseModel):
    """Team-owned SDD settings. Secrets never belong here."""

    model_config = ConfigDict(extra="forbid")

    base_branch: str = "dev"
    staging_branch: str | None = None
    hotfix_base: str = "main"
    #: Destination of ledger-event delivery (FEAT-758 outbox); ``None`` follows ``base_branch``.
    ledger_branch: str | None = None
    issue_tracker: Literal["jira", "none"] = "none"
    jira_host: str | None = None
    reviewer: Literal["codex", "none"] = "none"
    #: Shell string its consumers run once with cwd = the repo root (rev 0.5 C21). Stored and validated only.
    test_command: str | None = None
    #: When set, replaces ``sdd_meta.KNOWN_PROJECTS`` as the project vocabulary (rev 0.5 C22).
    projects: list[str] | None = None
    #: FEAT-801 — technical-wiki pipeline settings; ``None`` means defaults.
    techwiki: TechwikiConfig | None = None

    @field_validator("test_command")
    @classmethod
    def _non_blank_command(cls, value: str | None) -> str | None:
        """Reject a blank or whitespace-only command; keep any other value unchanged."""
        if value is not None and not value.strip():
            raise ValueError("test_command must not be blank")
        return value

    @field_validator(*_BRANCH_FIELDS)
    @classmethod
    def _branch_name(cls, value: str | None) -> str | None:
        """Reject blank names, inner whitespace and a leading ``origin/``."""
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("branch name must not be blank")
        if any(ch.isspace() for ch in value):
            raise ValueError(f"branch name must not contain whitespace: {value!r}")
        if value.startswith("origin/"):
            raise ValueError(f"branch name must not start with 'origin/': {value!r}")
        return value

    @field_validator("jira_host")
    @classmethod
    def _bare_hostname(cls, value: str | None) -> str | None:
        """Require a bare hostname (no scheme, path or whitespace); lower-case it."""
        if value is None:
            return None
        value = value.strip()
        if not value or "://" in value or "/" in value or any(ch.isspace() for ch in value):
            raise ValueError(f"jira_host must be a bare hostname (no scheme or path): {value!r}")
        return value.lower()

    @model_validator(mode="after")
    def _lanes(self) -> "SddConfig":
        """Cross-field rules: distinct lanes, and a Jira host when Jira is the tracker."""
        if self.base_branch == self.hotfix_base:
            raise ValueError(f"base_branch and hotfix_base must differ (both {self.base_branch!r})")
        if self.staging_branch is not None and self.staging_branch in {self.base_branch, self.hotfix_base}:
            raise ValueError(f"staging_branch {self.staging_branch!r} must differ from base_branch and hotfix_base")
        if self.issue_tracker == "jira" and not self.jira_host:
            raise ValueError("issue_tracker='jira' requires jira_host")
        return self


def ledger_destination(config: SddConfig) -> str:
    """Return the branch the ledger outbox delivers to: ``ledger_branch``, else ``base_branch``."""
    return config.ledger_branch or config.base_branch


def default_sdd_config() -> SddConfig:
    """Return the configuration used when a repository has no ``sdd/config.json``."""
    return SddConfig()


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default cwd) to the first directory holding ``.git`` (dir or file).

    Returns:
        The repository root, or ``None`` when ``start`` is not inside a repository.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


DEFAULT_WORKTREE_ROOT: str = ".parrot/worktrees"
LEGACY_WORKTREE_ROOT: str = ".claude/worktrees"
WORKTREE_ROOT_ENV: str = "WORKTREE_BASE_PATH"


class LegacyWorktreesError(RuntimeError):
    """Registered git worktrees still live under ``.claude/worktrees/``; the message is the recipe."""


def worktree_root_setting(override: str | None = None) -> str:
    """Return the configured raw worktree root without consulting application configuration.

    Args:
        override: Explicit root setting that takes precedence over the environment.

    Returns:
        The normalized absolute setting, or a normalized repository-relative setting.
    """
    candidates = (override, os.environ.get(WORKTREE_ROOT_ENV))
    value = next(
        (candidate.strip() for candidate in candidates if candidate and candidate.strip()),
        DEFAULT_WORKTREE_ROOT,
    )
    normalized = os.path.normpath(value)
    if os.path.isabs(normalized):
        return normalized
    return normalized.removeprefix(f".{os.sep}")


def worktree_root(repo_root: Path, override: str | None = None) -> Path:
    """Return the absolute, normalized worktree root for ``repo_root``.

    Args:
        repo_root: Primary repository root used for relative settings.
        override: Explicit root setting that takes precedence over the environment.

    Returns:
        The normalized absolute worktree root.
    """
    setting = worktree_root_setting(override)
    root = Path(setting) if os.path.isabs(setting) else Path(repo_root) / setting
    return Path(os.path.normpath(root.absolute()))


def legacy_worktrees(repo_root: Path) -> list[Path]:
    """Return registered worktrees inside the legacy root, sorted by resolved path.

    Args:
        repo_root: Primary repository root passed to git.

    Returns:
        Registered legacy worktree paths, or an empty list when git is unavailable or fails.
    """
    legacy_root = (Path(repo_root) / LEGACY_WORKTREE_ROOT).resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []

    paths: list[Path] = []
    for line in proc.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line.removeprefix("worktree ")).resolve()
        if path == legacy_root:
            continue
        try:
            path.relative_to(legacy_root)
        except ValueError:
            continue
        paths.append(path)
    return sorted(paths)


def legacy_migration_recipe(repo_root: Path, paths: Sequence[Path]) -> list[str]:
    """Return shell lines that move legacy worktrees and repair Git registrations.

    Args:
        repo_root: Primary repository root.
        paths: Registered legacy worktree paths to move.

    Returns:
        A fail-fast shell recipe, or an empty list when there are no paths.

    Raises:
        ValueError: When a mapping is unsafe, a destination is already occupied, or a legacy worktree has a
            live process inside it.
    """
    if not paths:
        return []

    root = Path(repo_root).resolve()
    legacy_root = (root / LEGACY_WORKTREE_ROOT).resolve()
    new_root = worktree_root(root)
    resolved_new_root = new_root.resolve()
    if resolved_new_root.is_relative_to(legacy_root) or legacy_root.is_relative_to(resolved_new_root):
        raise ValueError(f"legacy and new worktree roots overlap: {legacy_root} and {new_root}")

    mappings: list[tuple[Path, Path]] = []
    destinations: set[Path] = set()
    for path in paths:
        old_path = Path(path).resolve()
        try:
            relative_path = old_path.relative_to(legacy_root)
        except ValueError as exc:
            raise ValueError(f"legacy worktree is outside {legacy_root}: {old_path}") from exc
        destination = new_root / relative_path
        if destination in destinations:
            raise ValueError(f"duplicate migration destination: {destination}")
        destinations.add(destination)
        mappings.append((old_path, destination))

    mappings.sort(key=lambda item: str(item[0]))
    old_paths = {old_path for old_path, _ in mappings}
    topmost = [
        mapping
        for mapping in mappings
        if not any(ancestor != mapping[0] and mapping[0].is_relative_to(ancestor) for ancestor in old_paths)
    ]
    for _, destination in topmost:
        if os.path.lexists(destination):
            raise ValueError(f"migration destination already exists: {destination}")

    from parrot.sdd.scripts import remove_worktree  # lazy: remove_worktree imports this module

    for old_path, _ in topmost:
        live = remove_worktree.live_processes_in(old_path)
        if live:
            pids = ", ".join(str(pid) for pid, _ in live)
            raise ValueError(
                f"legacy worktree has {len(live)} live process(es) inside, wait for them to exit: "
                f"{old_path} (pids: {pids})"
            )

    quote = shlex.quote
    lines = ["(", "set -e"]
    for _, destination in topmost:
        rendered_destination = quote(str(destination))
        message = quote(f"error: migration destination already exists: {destination}")
        lines.append(
            f"[ ! -e {rendered_destination} ] && [ ! -L {rendered_destination} ] || "
            f"{{ echo {message} >&2; exit 1; }}"
        )
    for old_path, destination in topmost:
        lines.append(f"mkdir -p {quote(str(destination.parent))}")
        lines.append(f"mv {quote(str(old_path))} {quote(str(destination))}")
    repaired_paths = " ".join(quote(str(destination)) for _, destination in mappings)
    lines.append(f"git -C {quote(str(root))} worktree repair {repaired_paths}")
    for _, destination in mappings:
        message = quote(f"error: migrated worktree is not a git checkout: {destination}")
        lines.append(
            f"git -C {quote(str(destination))} rev-parse --git-dir >/dev/null || {{ echo {message} >&2; exit 1; }}"
        )
    lines.append(")")
    return lines


def load_sdd_config(root: Path | None = None) -> SddConfig:
    """Load ``<root>/sdd/config.json``; absent file or no repository means defaults.

    Raises:
        SddConfigError: When the file exists but is not valid JSON or fails validation.
    """
    base = root or find_repo_root()
    if base is None:
        return default_sdd_config()
    path = base / CONFIG_PATH
    if not path.is_file():
        return default_sdd_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SddConfigError(f"{path}: cannot read config: {exc}") from exc
    try:
        return SddConfig.model_validate(data)
    except ValidationError as exc:
        raise SddConfigError(f"{path}: invalid SDD config: {exc}") from exc


def write_default_config(root: Path) -> Path:
    """Write the default config to ``<root>/sdd/config.json``.

    Raises:
        FileExistsError: When the file already exists (never overwritten).
    """
    path = root / CONFIG_PATH
    if path.exists():
        raise FileExistsError(f"{path} already exists; refusing to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_sdd_config().model_dump(), indent=2) + "\n", encoding="utf-8")
    return path
