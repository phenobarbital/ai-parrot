"""Import-impact selector and core detector (FEAT-563, spec Module 2).

Stdlib-only: one AST pass builds a reverse import index for test modules and
for source modules, used by the merge tier (impacted tests) and by the merge
and feature tiers (core detection by transitive source fan-in).
"""

from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Sequence

from .datatypes import CoreHit
from .mirror import distribution_of
from .policy import ScopePolicy

INDEX_CACHE_PREFIX: str = "parrot-test-scope-index-"
_TOOLS_SRC_PREFIX: str = "packages/ai-parrot/src/parrot/tools/"


def module_name_for(path: str) -> str | None:
    """Map `packages/<dist>/src/<top>/a/b.py` to `<top>.a.b` (`__init__.py` → package).

    A `parrot/tools/<x>` source path yields its dotted name; callers that need the
    `parrot_tools.<x>` alias use `module_aliases`. Returns None for non-source paths.
    """
    parts = PurePosixPath(path).parts
    if len(parts) < 5 or parts[0] != "packages" or parts[2] != "src" or not path.endswith(".py"):
        return None
    dotted = list(parts[3:])
    dotted[-1] = dotted[-1][:-3]
    if dotted[-1] == "__init__":
        dotted.pop()
    return ".".join(dotted) or None


def module_aliases(module: str) -> tuple[str, ...]:
    """Return `module` plus its meta_path alias (`parrot.tools.x` ↔ `parrot_tools.x`)."""
    if module == "parrot.tools" or module.startswith("parrot.tools."):
        return (module, "parrot_tools" + module[len("parrot.tools") :])
    if module == "parrot_tools" or module.startswith("parrot_tools."):
        return (module, "parrot.tools" + module[len("parrot_tools") :])
    return (module,)


def _prefixes(module: str) -> list[str]:
    """`module` and every ancestor prefix, deepest first (e.g. 'a.b.c' -> ['a.b.c', 'a.b', 'a'])."""
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _own_package(module: str, is_init: bool) -> str:
    """The package a relative import inside `module` is resolved against."""
    if is_init:
        return module
    parts = module.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else module


def _resolve_from(base: str, names: Sequence[str], known_modules: set[str]) -> set[str]:
    """Resolve `from base import name1, name2, ...` to full dotted targets.

    Each name is treated as a submodule of `base` when `base.name` is a known
    source module; otherwise the import is an attribute pull and `base` itself
    is the dependency.
    """
    targets: set[str] = set()
    for name in names:
        candidate = f"{base}.{name}"
        targets.add(candidate if candidate in known_modules else base)
    return targets


def _extract_targets(tree: ast.AST, *, own_package: str | None, known_modules: set[str]) -> set[str]:
    """Every module dotted-name referenced by `import`/`from ... import` in `tree`.

    Args:
        tree: A parsed module.
        own_package: The importing file's own package for relative-import
            resolution, or None to skip relative imports entirely (test files).
        known_modules: Recognised source module names, for from-import
            submodule disambiguation.
    """
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                if own_package is None:
                    continue
                base_parts = own_package.split(".")
                up = node.level - 1
                base_parts = base_parts[: len(base_parts) - up] if up < len(base_parts) else []
                base = ".".join(base_parts)
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
                if not base:
                    continue
                targets |= _resolve_from(base, [a.name for a in node.names], known_modules)
            elif node.module:
                targets |= _resolve_from(node.module, [a.name for a in node.names], known_modules)
    return targets


@dataclass
class ImportIndex:
    """Reverse import index over one worktree."""

    by_module: dict[str, set[str]] = field(default_factory=dict)
    src_importers: dict[str, set[str]] = field(default_factory=dict)
    module_dist: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, worktree: Path) -> "ImportIndex":
        """Parse every test and source module under `worktree` once."""
        index = cls()

        source_files: list[tuple[Path, str, str]] = []
        for src_file in sorted(worktree.glob("packages/*/src/**/*.py")):
            rel = str(src_file.relative_to(worktree))
            module = module_name_for(rel)
            if module is None:
                continue
            index.module_dist[module] = distribution_of(rel)
            source_files.append((src_file, rel, module))
        known_modules = set(index.module_dist)

        for src_file, rel, module in source_files:
            try:
                tree = ast.parse(src_file.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, UnicodeDecodeError, OSError):
                index.skipped.append(rel)
                continue
            is_init = PurePosixPath(rel).name == "__init__.py"
            own_package = _own_package(module, is_init)
            targets = _extract_targets(tree, own_package=own_package, known_modules=known_modules)
            for target in targets:
                # Exact target only — NOT ancestor prefixes (FEAT-563 fix, TASK-3318 S4 finding):
                # unlike `by_module` (where "imports a submodule" should also match a lookup on
                # the parent, for test-impact purposes), expanding source-to-source edges to
                # every ancestor floods `src_importers["parrot"]` with nearly every file in the
                # tree (every satellite package imports *something* under the bare `parrot`
                # namespace), which then inflates `source_fanin`'s transitive BFS for almost any
                # module to a number close to the total file count. `source_fanin` must only
                # follow exact import edges.
                index.src_importers.setdefault(target, set()).add(module)

        test_files: set[Path] = set()
        for pattern in ("tests/**/test_*.py", "packages/*/tests/**/test_*.py"):
            test_files |= set(worktree.glob(pattern))
        for test_file in sorted(test_files):
            rel = str(test_file.relative_to(worktree))
            try:
                tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, UnicodeDecodeError, OSError):
                index.skipped.append(rel)
                continue
            targets = _extract_targets(tree, own_package=None, known_modules=known_modules)
            for target in targets:
                for prefix in _prefixes(target):
                    index.by_module.setdefault(prefix, set()).add(rel)
        return index

    @classmethod
    def load_or_build(cls, worktree: Path) -> "ImportIndex":
        """Reuse a cache keyed by `git rev-parse HEAD^{tree}` in the per-worktree git dir."""
        try:
            git_dir_proc = subprocess.run(
                ["git", "rev-parse", "--absolute-git-dir"], cwd=worktree, capture_output=True, text=True, check=False
            )
            tree_proc = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=worktree, capture_output=True, text=True, check=False
            )
        except OSError:
            return cls.build(worktree)
        if git_dir_proc.returncode != 0 or tree_proc.returncode != 0:
            return cls.build(worktree)
        git_dir = Path(git_dir_proc.stdout.strip())
        tree_id = tree_proc.stdout.strip()
        cache_path = git_dir / f"{INDEX_CACHE_PREFIX}{tree_id}.json"
        if cache_path.is_file():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                return cls(
                    by_module={k: set(v) for k, v in data["by_module"].items()},
                    src_importers={k: set(v) for k, v in data["src_importers"].items()},
                    module_dist=dict(data["module_dist"]),
                    skipped=list(data["skipped"]),
                )
            except (OSError, ValueError, KeyError, TypeError):
                pass  # corrupt cache: fall through and rebuild
        index = cls.build(worktree)
        try:
            payload = {
                "by_module": {k: sorted(v) for k, v in index.by_module.items()},
                "src_importers": {k: sorted(v) for k, v in index.src_importers.items()},
                "module_dist": index.module_dist,
                "skipped": index.skipped,
            }
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass  # cache write failure never fails planning
        return index


def _expand_modules(index: ImportIndex, start: set[str], depth: int) -> set[str]:
    """`start` plus every module within `depth` `src_importers` hops (aliases included)."""
    reached: set[str] = set()
    frontier: set[str] = set()
    for module in start:
        frontier |= set(module_aliases(module))
    reached |= frontier
    for _ in range(depth):
        next_frontier: set[str] = set()
        for module in frontier:
            for importer in index.src_importers.get(module, ()):
                if importer not in reached:
                    next_frontier |= set(module_aliases(importer))
        next_frontier -= reached
        if not next_frontier:
            break
        reached |= next_frontier
        frontier = next_frontier
    return reached


def impacted_tests(index: ImportIndex, changed: Sequence[str], *, worktree: Path, depth: int) -> list[str]:
    """Test files importing a changed module directly, or via ≤ `depth` source-module hops. Sorted."""
    start = {module for path in changed if (module := module_name_for(path)) is not None}
    modules = _expand_modules(index, start, depth)
    tests: set[str] = set()
    for module in modules:
        tests |= index.by_module.get(module, set())
    return sorted(t for t in tests if (worktree / t).exists())


def source_fanin(index: ImportIndex, module: str) -> tuple[int, frozenset[str]]:
    """Transitive count of source modules importing `module`, and their distributions (incl. the module's own)."""
    visited: set[str] = set()
    seen: set[str] = {module}  # never re-count `module` itself even if a cycle loops back to it
    queue: list[str] = [module]
    while queue:
        current = queue.pop()
        importers: set[str] = set()
        for alias in module_aliases(current):
            importers |= index.src_importers.get(alias, set())
        for importer in importers:
            if importer not in seen:
                seen.add(importer)
                visited.add(importer)
                queue.append(importer)
    dists = frozenset(index.module_dist[m] for m in visited if m in index.module_dist)
    return len(visited), dists


def detect_core(index: ImportIndex, changed: Sequence[str], *, policy: ScopePolicy) -> list[CoreHit]:
    """CoreHit per changed source file with fan-in ≥ threshold or listed in `policy.core_paths`."""
    hits: list[CoreHit] = []
    for path in changed:
        module = module_name_for(path)
        if module is None:
            continue
        fanin, dists = source_fanin(index, module)
        forced = path in policy.core_paths
        if forced or fanin >= policy.core_fanin_threshold:
            own = distribution_of(path)
            hits.append(
                CoreHit(
                    path=path, module=module, fanin=fanin, forced=forced, distributions=tuple(sorted(dists | {own}))
                )
            )
    return hits
