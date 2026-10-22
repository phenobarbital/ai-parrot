"""Native build artifacts a worktree cannot carry, because they are gitignored (FEAT-722).

Every compiled artifact in this repository is ignored by git, so a fresh
``git worktree add`` produces a tree in which ``import parrot.utils`` fails
(``parrot/utils/__init__.py`` imports the Cython ``.types`` module). The
artifacts are therefore DECLARED in the root ``pyproject.toml`` under
``[tool.parrot.worktree]`` and copied from the main checkout into each new
worktree.

This module imports only the standard library and pydantic: ``ensure_worktree``,
``worktree_manager`` and ``test_scope.baseline`` all import it, so it must not
pull in the rest of ``parrot``.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Directory (relative to the main checkout) holding the per-group build locks.
LOCK_DIRNAME: str = ".parrot/locks"
#: Set to "0" to disable the whole native sync.
SYNC_ENV_VAR: str = "PARROT_WORKTREE_SYNC_NATIVE"
#: Set to "0" to copy what exists but never build what is missing.
AUTOBUILD_ENV_VAR: str = "PARROT_WORKTREE_AUTOBUILD"
#: Replaced with ``sys.executable`` in a group's ``build`` argv (TASK-4608).
PYTHON_PLACEHOLDER: str = "{python}"


class NativeGroup(BaseModel):
    """One family of native build artifacts declared in ``[tool.parrot.worktree]``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    copy_globs: list[str] = Field(default_factory=list)
    pair_sources: list[str] = Field(default_factory=list)
    required: bool = True
    abi_scoped: bool = False
    autobuild: bool = False
    build: list[str] = Field(default_factory=list)
    build_cwd: str = "."
    build_timeout_s: int = 900
    manual_hint: str | None = None


class NativeManifest(BaseModel):
    """The parsed ``[tool.parrot.worktree]`` table."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    groups: list[NativeGroup] = Field(default_factory=list)


class MissingArtifact(BaseModel):
    """A declared artifact that is absent from the main checkout."""

    model_config = ConfigDict(extra="forbid")

    group: str
    reason: Literal["no_match", "unpaired_source", "abi_mismatch"]
    detail: str


class NativeSyncReport(BaseModel):
    """Outcome of one sync. Never an exception carrier — callers decide severity."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    copied: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    built: list[str] = Field(default_factory=list)
    missing: list[MissingArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def env_flag_disabled(name: str) -> bool:
    """True when environment variable ``name`` is explicitly set to "0"."""
    return os.environ.get(name, "").strip() == "0"


def load_manifest(repo_root: Path) -> NativeManifest:
    """Parse ``[tool.parrot.worktree]`` from ``repo_root/pyproject.toml``.

    Returns an EMPTY manifest (``groups=[]``, so a sync is a no-op) when the
    file or the table is absent — the declaration is the single source of truth
    and is never duplicated here.

    Raises:
        ValueError: The table exists but is malformed (unknown key, wrong type).
    """
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.is_file():
        return NativeManifest()
    with pyproject.open("rb") as handle:
        table = tomllib.load(handle).get("tool", {}).get("parrot", {}).get("worktree")
    if not table:
        return NativeManifest()

    manifest_data = dict(table)
    manifest_data["groups"] = manifest_data.pop("native_group", [])
    try:
        return NativeManifest.model_validate(manifest_data)
    except ValueError as exc:
        raise ValueError(f"invalid [tool.parrot.worktree] in {pyproject}: {exc}") from exc
