"""Mirror-of-directories test selection, moved verbatim from QANode (FEAT-563 M1)."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import PurePosixPath


def pytest_targets(files: Sequence[str], worktree_path: str) -> list[str]:
    """Map changed files to the narrowest existing test targets (was QANode._pytest_targets, qa.py:588).

    Mapping a change to ``packages/<dist>/tests`` is correct but far too
    coarse: for ``ai-parrot`` that is the entire 1250-module core suite
    (~9 minutes), which is what the derived gate used to run for a
    three-file change. The repo mirrors its source tree under ``tests/``
    (``src/parrot/flows/dev_loop/`` -> ``tests/flows/dev_loop/``), so each
    changed file resolves instead to the deepest mirrored directory that
    actually exists, walking up towards ``packages/<dist>/tests`` until
    one does.

    Args:
        files: Changed file paths, repo-relative.
        worktree_path: Root the paths are relative to, for existence checks.

    Returns:
        Existing test paths, sorted, with any target already covered by
        an ancestor target removed; empty when nothing mapped.
    """
    targets: set[str] = set()
    for path in files:
        target = pytest_target_for(path, worktree_path)
        if target:
            targets.add(target)
    return prune_nested(targets)


def pytest_target_for(path: str, worktree_path: str) -> str | None:
    """Resolve one changed path to its narrowest existing test target (was qa.py:633).

    Args:
        path: A repo-relative changed file path.
        worktree_path: Root the path is relative to.

    Returns:
        The test path to hand pytest, or ``None`` when the file maps to
        nothing that exists on disk.
    """
    parts = PurePosixPath(path).parts
    if parts and parts[0] == "tests":
        # The repo-root ``tests/`` tree (pytest's configured ``testpaths``,
        # ~400 modules) lives outside ``packages/`` and mirrors nothing, so
        # a change there has no package to map to. Left unmapped it
        # produced NO target at all, which the caller turns into a bare
        # ``pytest`` — the entire root suite. The changed module is its
        # own target.
        if os.path.exists(os.path.join(worktree_path, path)):
            return path
        # Deleted module — fall back to the root tree, but only if it
        # exists (pytest exits 4 on a missing path).
        return "tests" if os.path.isdir(os.path.join(worktree_path, "tests")) else None
    if len(parts) < 3 or parts[0] != "packages":
        return None
    tests_root = f"packages/{parts[1]}/tests"
    if not os.path.isdir(os.path.join(worktree_path, tests_root)):
        return None

    rest = parts[2:]
    if rest[0] == "tests":
        # The changed test module itself is the tightest possible target.
        # Fall back to the package root if it was deleted.
        candidate = "/".join(parts)
        if os.path.exists(os.path.join(worktree_path, candidate)):
            return candidate
        return tests_root
    if rest[0] == "src":
        # packages/<dist>/src/<top_pkg>/<dirs...>/<file> -> <dirs...>
        inner = rest[1:]
        subdirs = inner[1:-1] if len(inner) >= 2 else ()
        return deepest_existing_dir(tests_root, subdirs, worktree_path)
    return tests_root


def deepest_existing_dir(tests_root: str, subdirs: tuple[str, ...], worktree_path: str) -> str:
    """Walk tests_root/subdirs upwards to the first existing directory (was qa.py:679).

    Args:
        tests_root: ``packages/<dist>/tests`` — verified to exist by the
            caller, so this always terminates with a real path.
        subdirs: The source-relative directory chain to mirror.
        worktree_path: Root the paths are relative to.

    Returns:
        The deepest existing mirrored directory, at worst ``tests_root``
        itself.
    """
    for depth in range(len(subdirs), 0, -1):
        candidate = "/".join((tests_root, *subdirs[:depth]))
        if os.path.isdir(os.path.join(worktree_path, candidate)):
            return candidate
    return tests_root


def prune_nested(targets: set[str]) -> list[str]:
    """Drop targets already covered by a broader target; sorted (was qa.py:703).

    Args:
        targets: Candidate test paths.

    Returns:
        The surviving paths, sorted.
    """
    return sorted(t for t in targets if not any(t.startswith(f"{other}/") for other in targets))


def distribution_of(path: str) -> str:
    """Return '<dist>' for packages/<dist>/…, 'root' for tests/…; raise ValueError otherwise.

    Args:
        path: A repo-relative path.

    Returns:
        ``"root"`` for a path under the repo-root ``tests/`` tree, or the
        distribution name for a path under ``packages/<dist>/``.

    Raises:
        ValueError: When the path is under neither tree.
    """
    parts = PurePosixPath(path).parts
    if parts and parts[0] == "tests":
        return "root"
    if len(parts) >= 2 and parts[0] == "packages":
        return parts[1]
    raise ValueError(f"not a test-bearing path: {path}")
