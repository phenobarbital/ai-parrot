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

import logging
import os
import shutil
import subprocess
import sys
import sysconfig
import time
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

try:  # POSIX only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

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


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in ``cwd`` capturing text output; never raises on a non-zero exit."""
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


def main_checkout_root(worktree: Path) -> Path | None:
    """Root of the primary checkout that owns ``worktree``'s git common dir."""
    try:
        proc = _git(Path(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir")
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).parent


def _ext_suffix() -> str:
    """Return the running interpreter's extension suffix."""
    return sysconfig.get_config_var("EXT_SUFFIX") or ".so"


def _matches(root: Path, patterns: list[str]) -> list[Path]:
    """Return existing files below ``root`` matching any pattern, sorted and deduplicated."""
    found: set[Path] = set()
    root_resolved = root.resolve()
    for pattern in patterns:
        found.update(
            path
            for path in root.glob(pattern)
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root_resolved)
        )
    return sorted(found)


def missing_artifacts(main_root: Path, manifest: NativeManifest) -> list[MissingArtifact]:
    """Return declared artifacts that are absent from ``main_root``."""
    missing: list[MissingArtifact] = []
    for group in manifest.groups:
        matches = _matches(main_root, group.copy_globs)
        sources = _matches(main_root, group.pair_sources)
        if group.required and not matches and not sources:
            missing.append(MissingArtifact(group=group.name, reason="no_match", detail=", ".join(group.copy_globs)))
            continue

        for source in sources:
            stem = source.stem
            siblings = list(source.parent.glob(f"{stem}.*.so"))
            direct_sibling = source.parent / f"{stem}.so"
            if direct_sibling.is_file():
                siblings.append(direct_sibling)
            detail = source.relative_to(main_root).as_posix()
            if not siblings:
                missing.append(MissingArtifact(group=group.name, reason="unpaired_source", detail=detail))
            elif group.abi_scoped and not any(sibling.name.endswith(_ext_suffix()) for sibling in siblings):
                missing.append(MissingArtifact(group=group.name, reason="abi_mismatch", detail=detail))

        if (
            group.abi_scoped
            and matches
            and not sources
            and not any(path.name.endswith(_ext_suffix()) for path in matches)
        ):
            missing.append(
                MissingArtifact(
                    group=group.name,
                    reason="abi_mismatch",
                    detail=matches[0].relative_to(main_root).as_posix(),
                )
            )
    return missing


@contextmanager
def _build_lock(main_root: Path, group: NativeGroup) -> Iterator[bool]:
    """Hold an exclusive build lock for ``group``; yield False when unavailable.

    The lock lives below the main checkout so every process capable of building
    shares it. Lock acquisition failures and timeout are deliberately soft:
    native syncing must never prevent worktree creation.
    """
    if fcntl is None:  # pragma: no cover - exercised on non-POSIX platforms
        yield False
        return

    # The `except OSError` arms below deliberately cover ONLY the setup and the
    # release. Wrapping the `yield` in them would catch an OSError raised by the
    # caller's own block, thrown back in at the yield point, and yield a second
    # time — which contextlib turns into "generator didn't stop after throw()".
    try:
        lock_dir = main_root / LOCK_DIRNAME
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (lock_dir / f"native-{group.name}.lock").open("a+", encoding="utf-8")
    except OSError:
        yield False
        return

    try:
        deadline = time.monotonic() + max(group.build_timeout_s, 0)
        acquired = False
        while not acquired:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.05, remaining))
            except OSError:
                break

        if not acquired:
            yield False
            return

        try:
            yield True
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - the fd is closed right after
                pass
    finally:
        lock_file.close()


def build_missing(
    main_root: Path,
    manifest: NativeManifest,
    missing: Sequence[MissingArtifact],
) -> tuple[list[str], list[str]]:
    """Build missing artifact groups and return their names with warnings.

    Each group is checked again after its exclusive lock is acquired, allowing
    a concurrent sync to reuse another process's successful build.
    """
    built: list[str] = []
    warnings: list[str] = []
    pending_groups = {artifact.group for artifact in missing}
    processed_groups: set[str] = set()

    for group in manifest.groups:
        if group.name not in pending_groups or group.name in processed_groups:
            continue
        processed_groups.add(group.name)

        manual_hint = group.manual_hint or "no manual command declared"

        def warn(reason: str, *, name: str = group.name, hint: str = manual_hint) -> None:
            # Default args bind the loop variables at definition time (ruff B023):
            # `warn` is called inside this iteration, but a late-bound closure over
            # `group` would silently attribute a warning to the wrong group if this
            # ever gained a deferred call path.
            warnings.append(f"{name}: {reason}; build it manually with: {hint}")

        try:
            if env_flag_disabled(AUTOBUILD_ENV_VAR):
                warn(f"{AUTOBUILD_ENV_VAR}=0")
                continue
            if not group.autobuild:
                warn("autobuild is disabled")
                continue
            if not group.build:
                warn("no build command declared")
                continue

            with _build_lock(main_root, group) as acquired:
                if not acquired:
                    warn("build lock is unavailable")
                    continue
                if not any(artifact.group == group.name for artifact in missing_artifacts(main_root, manifest)):
                    continue

                argv = [sys.executable if item == PYTHON_PLACEHOLDER else item for item in group.build]
                try:
                    result = subprocess.run(
                        argv,
                        cwd=str(main_root / group.build_cwd),
                        timeout=group.build_timeout_s,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                except subprocess.TimeoutExpired:
                    warn(f"build timed out after {group.build_timeout_s}s")
                    continue
                except OSError as exc:
                    warn(f"build could not start: {exc}")
                    continue

                if result.returncode != 0:
                    stderr = "\n".join(result.stderr.strip().splitlines()[-10:])
                    reason = f"build exited with status {result.returncode}"
                    warn(f"{reason}: {stderr}" if stderr else reason)
                    continue
                built.append(group.name)
        except Exception as exc:
            warn(f"build failed unexpectedly: {exc}")

    return built, warnings


def sync_native_artifacts(
    *,
    main_root: Path,
    target: Path,
    manifest: NativeManifest | None = None,
    autobuild: bool = True,
) -> NativeSyncReport:
    """Copy declared native artifacts into ``target`` and report missing entries.

    Existing destinations with matching size and mtime are left untouched, so
    calls are safe when a worktree is reused.

    Args:
        autobuild: Build declared artifacts missing from the main checkout
            before copying, subject to each group's build policy.
    """
    resolved = manifest if manifest is not None else load_manifest(main_root)
    if not resolved.enabled or env_flag_disabled(SYNC_ENV_VAR):
        return NativeSyncReport(enabled=False)

    report = NativeSyncReport(enabled=True)
    pending = missing_artifacts(main_root, resolved)
    if pending:
        if autobuild:
            report.built, report.warnings = build_missing(main_root, resolved, pending)
        else:
            groups = {group.name: group for group in resolved.groups}
            for artifact in pending:
                hint = groups[artifact.group].manual_hint or "no manual command declared"
                report.warnings.append(f"{artifact.group}: autobuild is disabled; build it manually with: {hint}")

    for group in resolved.groups:
        for source in _matches(main_root, group.copy_globs):
            relative_path = source.relative_to(main_root)
            destination = target / relative_path
            report_path = relative_path.as_posix()
            if destination.is_file():
                source_stat = source.stat()
                destination_stat = destination.stat()
                if (source_stat.st_size, source_stat.st_mtime_ns) == (
                    destination_stat.st_size,
                    destination_stat.st_mtime_ns,
                ):
                    report.skipped.append(report_path)
                    continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            logger.debug("copied native artifact %s to %s", source, destination)
            report.copied.append(report_path)

    report.missing.extend(missing_artifacts(main_root, resolved))
    groups = {group.name: group for group in resolved.groups}
    for missing in report.missing:
        manual_hint = groups[missing.group].manual_hint
        if manual_hint:
            report.warnings.append(f"missing native artifact for {missing.group}: {manual_hint}")
    return report
