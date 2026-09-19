"""Capture verifiable source/environment identity for E2E evidence (FEAT-581, M2).

``capture_identity()`` is the single entry point every caller (the M3 runner,
before and after execution; the M2 evidence verifier landing in TASK-3523) uses
to snapshot exactly what a run was validated against, per spec §2 "Evidence
Identity and Gate Evaluation":

    Before and after execution, hash a canonical sorted manifest of tracked
    files plus nonignored untracked files, including modes and relevant
    symlink targets. Exclude only declared generated artifacts
    (``artifacts/logs/e2e/``, this feature's run evidence/candidates, pytest
    caches, bytecode) and SDD task bookkeeping (``sdd/tasks/``,
    ``sdd/ledger/``). Do not exclude arbitrary source, templates, specs,
    plans or dependencies. Hash the plan/spec separately. Any relevant
    mutation invalidates the run. Environment fingerprint includes
    interpreter version/path, installed distribution versions, ``uv.lock``,
    selected model, target/tool versions, nonsecret fixture configuration
    and opt-in settings; exclude credential values.

This module lists tracked/untracked files via async Git subprocesses (never
``subprocess.run``/``Popen`` blocking the event loop) and hashes their
content with the standard library. It has no target/provider imports of its
own (target adapters land in M4) and never persists or logs a credential
value — only whether an opt-in secret is *configured*, never its content.

Manifest entries never carry raw file bytes, only ``path``, ``mode`` (a
git-style octal mode: ``100644`` regular, ``100755`` executable,
``120000`` symlink) and a ``content`` marker (a ``sha256:<hex>`` digest for
regular files, or ``symlink:<target>`` recording the *raw* ``readlink()``
target string — never the dereferenced target's content, since a dangling
or escaping symlink target must still be captured as identity data without
resolving it).

``TargetConfig.options`` is deliberately excluded from the environment
fingerprint: per-adapter option-key allow-listing is deferred to M4 (see
``parrot.e2e.plan`` module docstring), so this module cannot yet tell a
nonsecret fixture toggle from a credential-shaped value placed there ahead
of that validation. Only each target's ``kind``/``profile`` (fixed,
schema-validated enums) are folded into the fingerprint as a target/tool
identity signal.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import E2EPlan, SourceIdentity

__all__ = ["capture_identity"]

_GIT_BINARY = "git"

# spec §2: exclude only declared generated E2E artifacts/caches and SDD
# task/ledger bookkeeping. Every other tracked/nonignored-untracked path --
# source, templates, specs, plans, uv.lock, config -- is included.
_EXCLUDED_PREFIXES = (
    "artifacts/logs/e2e/",
    "sdd/tasks/",
    "sdd/ledger/",
)
_EXCLUDED_PATH_SEGMENTS = frozenset({"__pycache__", ".pytest_cache"})
_EXCLUDED_SUFFIXES = (".pyc", ".pyo")


async def capture_identity(plan: E2EPlan, *, worktree: Path) -> SourceIdentity:
    """Hash the normative source manifest and nonsecret environment inputs.

    Args:
        plan: The already-validated :class:`E2EPlan` (e.g. from
            :func:`parrot.e2e.plan.load_plan`) whose ``feature_id`` scopes
            the excluded run-evidence directory, whose ``spec_path`` is
            hashed separately, and whose content (including
            ``budget.model``) is hashed as ``plan_sha256``.
        worktree: Candidate worktree root; must already exist and be a Git
            checkout with at least one commit.

    Returns:
        A fully validated :class:`SourceIdentity` snapshot.

    Raises:
        E2EConfigError: If ``worktree`` does not exist or is not a
            directory, the ``git`` executable is unavailable, any Git
            command fails (e.g. ``worktree`` is not a Git repository, or has
            no commits), ``plan.spec_path`` escapes ``worktree`` or does not
            resolve to a file, or a manifest-listed path vanishes or becomes
            unreadable while being hashed.
    """
    resolved_worktree = _resolve_root(worktree)

    commit = await _capture_commit(resolved_worktree)
    manifest_entries = await _capture_manifest(resolved_worktree, feature_id=plan.feature_id)
    manifest_sha256 = _hash_canonical(manifest_entries)

    resolved_spec_path = _resolve_spec_path(resolved_worktree, plan.spec_path)
    spec_sha256 = _hash_file(resolved_spec_path)

    plan_sha256 = _hash_canonical(plan.model_dump(mode="json"))

    environment_fingerprint = await asyncio.to_thread(_capture_environment, resolved_worktree, plan)
    environment_sha256 = _hash_canonical(environment_fingerprint)

    return SourceIdentity(
        commit=commit,
        manifest_sha256=manifest_sha256,
        spec_sha256=spec_sha256,
        plan_sha256=plan_sha256,
        environment_sha256=environment_sha256,
        worktree=str(resolved_worktree),
    )


# ---------------------------------------------------------------------------
# Path resolution (mirrors parrot.e2e.plan's containment policy; kept local
# and private since that module's helpers are not part of its public API)
# ---------------------------------------------------------------------------


def _resolve_root(worktree: Path) -> Path:
    """Resolve the worktree root, requiring it to already exist.

    Args:
        worktree: Candidate worktree root.

    Returns:
        The canonical (symlink-resolved, absolute) worktree path.

    Raises:
        E2EConfigError: If ``worktree`` cannot be resolved or does not exist.
    """
    try:
        resolved = worktree.resolve(strict=True)
    except OSError as exc:
        raise E2EConfigError(
            f"worktree root does not exist or is unreadable: {worktree}: {exc}", reason_code="worktree_missing"
        ) from exc
    if not resolved.is_dir():
        raise E2EConfigError(f"worktree root is not a directory: {worktree}", reason_code="worktree_not_directory")
    return resolved


def _resolve_spec_path(worktree: Path, spec_path: str) -> Path:
    """Resolve ``plan.spec_path`` against ``worktree`` and require it exists.

    Resolution follows symlinks, so a symlink whose target lies outside
    ``worktree`` is rejected the same way a literal ``..`` traversal would
    be (spec §2 "reject traversal and escaping symlinks").

    Args:
        worktree: Canonical worktree root the spec must resolve inside of.
        spec_path: The plan's worktree-relative spec path.

    Returns:
        The resolved, contained spec file path.

    Raises:
        E2EConfigError: If the path cannot be resolved, escapes ``worktree``,
            or does not resolve to an existing file.
    """
    candidate = worktree / spec_path
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise E2EConfigError(
            f"spec_path could not be resolved: {spec_path}: {exc}", reason_code="path_unresolvable"
        ) from exc

    if resolved != worktree and worktree not in resolved.parents:
        raise E2EConfigError(
            f"spec_path escapes worktree (traversal or symlink escape): {spec_path} resolves to {resolved}, "
            f"outside {worktree}",
            reason_code="path_escape",
        )
    if not resolved.is_file():
        raise E2EConfigError(
            f"E2E plan references a missing spec file: {spec_path!r}", reason_code="spec_path_missing"
        )
    return resolved


# ---------------------------------------------------------------------------
# Async Git subprocesses
# ---------------------------------------------------------------------------


async def _run_git(worktree: Path, *args: str) -> bytes:
    """Run one Git subcommand asynchronously and return its raw stdout.

    Args:
        worktree: Git checkout the command runs against (``git -C``).
        *args: Git subcommand and its arguments.

    Returns:
        The command's raw stdout bytes.

    Raises:
        E2EConfigError: If the ``git`` executable is unavailable, or the
            command exits with a nonzero status.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            _GIT_BINARY,
            "-C",
            str(worktree),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
    except OSError as exc:
        raise E2EConfigError(
            f"git executable is unavailable to capture source identity: {exc}", reason_code="git_unavailable"
        ) from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise E2EConfigError(
            f"git {' '.join(args)} failed in {worktree} (exit {process.returncode}): {detail}",
            reason_code="git_command_failed",
        )
    return stdout


async def _capture_commit(worktree: Path) -> str:
    """Return the checkout's current commit SHA via ``git rev-parse HEAD``.

    Args:
        worktree: Resolved Git checkout root.

    Returns:
        The full commit SHA, stripped of surrounding whitespace.

    Raises:
        E2EConfigError: If Git is unavailable, fails, or reports no commit
            (e.g. an empty repository with no ``HEAD``).
    """
    stdout = await _run_git(worktree, "rev-parse", "HEAD")
    commit = stdout.decode("utf-8", errors="strict").strip()
    if not commit:
        raise E2EConfigError(f"git rev-parse HEAD returned no commit in {worktree}", reason_code="git_command_failed")
    return commit


async def _list_manifest_paths(worktree: Path) -> list[str]:
    """List every tracked file plus nonignored untracked file, sorted.

    Uses ``git ls-files -z --cached --others --exclude-standard``: ``--cached``
    lists tracked (indexed) paths, ``--others`` adds untracked paths, and
    ``--exclude-standard`` applies the checkout's own ``.gitignore``/
    ``.git/info/exclude``/``core.excludesFile`` rules so ignored untracked
    files never enter the manifest. ``-z`` null-terminates entries so exotic
    filenames survive intact.

    Args:
        worktree: Resolved Git checkout root.

    Returns:
        A sorted list of worktree-relative paths (POSIX separators, as Git
        reports them).

    Raises:
        E2EConfigError: If Git is unavailable or the command fails.
    """
    stdout = await _run_git(worktree, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return sorted({path for path in paths if path})


# ---------------------------------------------------------------------------
# Manifest construction and exclusions
# ---------------------------------------------------------------------------


def _is_excluded(path: str, *, feature_id: str) -> bool:
    """Return whether ``path`` matches a spec §2 declared manifest exclusion.

    Args:
        path: A worktree-relative, POSIX-separated candidate path.
        feature_id: The owning plan's ``feature_id``, scoping the excluded
            per-feature run-evidence/candidates directory
            (``sdd/state/<feature_id>/e2e/``).

    Returns:
        ``True`` if ``path`` is a declared generated artifact/cache or SDD
        task/ledger bookkeeping path; ``False`` otherwise (the default —
        arbitrary source, templates, specs, plans and dependencies are never
        excluded).
    """
    if path.startswith(_EXCLUDED_PREFIXES):
        return True
    if path.startswith(f"sdd/state/{feature_id}/e2e/"):
        return True
    if any(segment in _EXCLUDED_PATH_SEGMENTS for segment in path.split("/")):
        return True
    if path.endswith(_EXCLUDED_SUFFIXES):
        return True
    return False


def _build_manifest_entries(worktree: Path, paths: list[str]) -> list[dict[str, str]]:
    """Build the canonical manifest entries for ``paths`` (blocking; run off-thread).

    Args:
        worktree: Resolved Git checkout root ``paths`` are relative to.
        paths: Already-filtered, worktree-relative candidate paths.

    Returns:
        A list of ``{"path", "mode", "content"}`` mappings, sorted by path.

    Raises:
        E2EConfigError: If a listed path vanishes or is unreadable while
            being hashed (a benign race with a concurrent mutation, treated
            as a manifest capture failure rather than silently skipped).
    """
    entries: list[dict[str, str]] = []
    for relative_path in paths:
        absolute_path = worktree / relative_path
        try:
            file_stat = absolute_path.lstat()
        except OSError as exc:
            raise E2EConfigError(
                f"manifest path vanished while capturing source identity: {relative_path}: {exc}",
                reason_code="manifest_path_missing",
            ) from exc

        if stat.S_ISLNK(file_stat.st_mode):
            mode = "120000"
            content = f"symlink:{os.readlink(absolute_path)}"
        else:
            mode = "100755" if file_stat.st_mode & stat.S_IXUSR else "100644"
            try:
                digest = hashlib.sha256(absolute_path.read_bytes()).hexdigest()
            except OSError as exc:
                raise E2EConfigError(
                    f"manifest path could not be read while capturing source identity: {relative_path}: {exc}",
                    reason_code="manifest_path_unreadable",
                ) from exc
            content = f"sha256:{digest}"
        entries.append({"path": relative_path, "mode": mode, "content": content})

    entries.sort(key=lambda entry: entry["path"])
    return entries


async def _capture_manifest(worktree: Path, *, feature_id: str) -> list[dict[str, str]]:
    """List, filter and hash the checkout's canonical source manifest.

    Args:
        worktree: Resolved Git checkout root.
        feature_id: The owning plan's ``feature_id``, scoping the excluded
            per-feature run-evidence directory.

    Returns:
        The canonical sorted manifest entries (never raw file contents).
    """
    paths = await _list_manifest_paths(worktree)
    included_paths = [path for path in paths if not _is_excluded(path, feature_id=feature_id)]
    return await asyncio.to_thread(_build_manifest_entries, worktree, included_paths)


# ---------------------------------------------------------------------------
# Environment fingerprint
# ---------------------------------------------------------------------------


def _capture_environment(worktree: Path, plan: E2EPlan) -> dict[str, Any]:
    """Build the nonsecret environment fingerprint (blocking; run off-thread).

    Args:
        worktree: Resolved Git checkout root (used to locate ``uv.lock``).
        plan: The plan being captured; ``budget.model`` and each target's
            ``kind``/``profile`` are folded in as identity signals.

    Returns:
        A JSON-serializable mapping. Every value is nonsecret: opt-in
        environment variables are recorded only as a boolean "configured"
        flag or their own nonsecret content (model name, call count), never
        a credential value.
    """
    distributions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.version
        if not name or not version:
            continue
        distributions[name.lower()] = version

    lock_path = worktree / "uv.lock"
    uv_lock_sha256 = _hash_file(lock_path) if lock_path.is_file() else None

    resolved_executable = Path(sys.executable).resolve() if sys.executable else None

    return {
        "python_version": sys.version,
        "python_executable": str(resolved_executable) if resolved_executable else None,
        "distributions": distributions,
        "uv_lock_sha256": uv_lock_sha256,
        "model": plan.budget.model,
        "targets": sorted(f"{target_id}:{config.kind}:{config.profile}" for target_id, config in plan.targets.items()),
        "opt_ins": {
            "PARROT_TEST_E2E": os.environ.get("PARROT_TEST_E2E"),
            "PARROT_TEST_REAL_LLM": os.environ.get("PARROT_TEST_REAL_LLM"),
            "E2E_MODEL": os.environ.get("E2E_MODEL"),
            "E2E_MAX_LLM_CALLS": os.environ.get("E2E_MAX_LLM_CALLS"),
            "google_api_key_configured": bool(os.environ.get("GOOGLE_API_KEY")),
        },
    }


# ---------------------------------------------------------------------------
# Canonical hashing
# ---------------------------------------------------------------------------


def _hash_canonical(payload: Any) -> str:
    """Hash ``payload`` as canonical (sorted-key, whitespace-free) JSON.

    Args:
        payload: A JSON-serializable value (list/dict of primitives).

    Returns:
        The lowercase hex SHA-256 digest of the canonical JSON encoding.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    """Hash one file's raw bytes.

    Args:
        path: File to hash.

    Returns:
        The lowercase hex SHA-256 digest of the file's content.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()
