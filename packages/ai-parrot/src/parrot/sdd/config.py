"""Per-repository SDD configuration (`sdd/config.json`) — FEAT-633 rev 0.2, amendment C6."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

CONFIG_PATH = Path("sdd/config.json")
_BRANCH_FIELDS = ("base_branch", "staging_branch", "hotfix_base")


class SddConfigError(ValueError):
    """Raised when ``sdd/config.json`` exists but cannot be used."""


class SddConfig(BaseModel):
    """Team-owned SDD settings. Secrets never belong here."""

    model_config = ConfigDict(extra="forbid")

    base_branch: str = "dev"
    staging_branch: str | None = None
    hotfix_base: str = "main"
    issue_tracker: Literal["jira", "none"] = "none"
    jira_host: str | None = None
    reviewer: Literal["codex", "none"] = "none"
    #: Shell string its consumers run once with cwd = the repo root (rev 0.5 C21). Stored and validated only.
    test_command: str | None = None
    #: When set, replaces ``sdd_meta.KNOWN_PROJECTS`` as the project vocabulary (rev 0.5 C22).
    projects: list[str] | None = None

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
