"""Content-addressed green cache across merges within one feature (FEAT-699, spec §3 Module 4).

Stdlib-only. Stored in the per-worktree git dir next to the FEAT-604 escalation ledger. Every unknown or
unresolvable input is a cache MISS — the cache may only ever skip work it can prove unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .context import _atomic_write_json, _blob, worktree_git_dir
from .datatypes import GreenCacheEntry, ScopePlan, TestContract, TestTarget
from .impact import ImportIndex
from .planner import build_plan
from .policy import ScopePolicy

try:  # POSIX only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

CACHE_FILENAME: str = "parrot-test-scope-green.json"
CACHE_SCHEMA: int = 1
SELECTOR_VERSION: str = "feat-699.1"

_GREEN_STATUSES = frozenset({"passed", "skipped"})


def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str:
    """Namespace for one feature/base/contract; any change invalidates the whole store."""
    raw = json.dumps([CACHE_SCHEMA, SELECTOR_VERSION, feature_id, base_ref, contract_digest])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_part(target: str) -> str:
    """The file portion of a ``file`` or ``file::node`` operand."""
    return target.split("::", 1)[0]


def _is_cacheable(target: str) -> bool:
    """Only files and nodes are cacheable — never directory operands."""
    return _file_part(target).endswith(".py")


def _imported_sources(index: ImportIndex) -> dict[str, list[str]]:
    """Invert ``by_module``: test file -> real source modules it imports (prefix keys excluded)."""
    result: dict[str, list[str]] = {}
    for module, files in index.by_module.items():
        if module not in index.module_dist:
            continue
        for test_file in files:
            result.setdefault(test_file, []).append(module)
    return result


def _module_paths(worktree: Path, module: str) -> list[str]:
    """Repo-relative source files implementing ``module`` across every distribution."""
    rel = PurePosixPath(*module.split("."))
    found: list[str] = []
    for pkg in sorted((worktree / "packages").glob("*/src")):
        for candidate in (pkg / f"{rel}.py", pkg / rel / "__init__.py"):
            if candidate.is_file():
                found.append(str(candidate.relative_to(worktree)))
    return found


def _manifest(
    worktree: Path, target: str, marker_expression: str, imports: Mapping[str, list[str]]
) -> dict[str, str] | None:
    file_path = _file_part(target)
    if not file_path.endswith(".py"):
        return None
    manifest: dict[str, str] = {}

    def add(label: str, path: str) -> bool:
        blob = _blob(worktree, path)
        if blob is None:
            return False
        manifest[label] = blob
        return True

    if not add(f"file:{file_path}", file_path):
        return None
    parts = PurePosixPath(file_path).parts
    for depth in range(len(parts) - 1, -1, -1):
        conftest = str(PurePosixPath(*parts[:depth], "conftest.py"))
        if (worktree / conftest).is_file() and not add(f"conftest:{conftest}", conftest):
            return None
    if not add("pyproject:root", "pyproject.toml"):
        return None
    if len(parts) > 1 and parts[0] == "packages" and not add(f"pyproject:{parts[1]}", f"packages/{parts[1]}/pyproject.toml"):
        return None
    for module in sorted(imports.get(file_path, ())):
        paths = _module_paths(worktree, module)
        if not paths:
            return None
        for path in paths:
            if not add(f"src:{path}", path):
                return None
    manifest["python"] = f"{sys.version_info.major}.{sys.version_info.minor}"
    manifest["markers"] = marker_expression
    return manifest


def execution_manifest(
    worktree: Path, target: str, *, marker_expression: str, index: ImportIndex
) -> dict[str, str] | None:
    """Inputs deciding ``target``'s outcome as ``{label: blob}``; None when any input is unresolvable."""
    return _manifest(worktree, target, marker_expression, _imported_sources(index))


def target_key(manifest: Mapping[str, str]) -> str:
    """sha256 of the sorted manifest."""
    return hashlib.sha256(json.dumps(dict(manifest), sort_keys=True).encode("utf-8")).hexdigest()


def _read_store(path: Path, namespace: str) -> dict[str, dict[str, str]]:
    """Entries of the store when schema and namespace match; empty on any problem."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA or data.get("namespace") != namespace:
        return {}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("key"), str)}


def _planned_targets(plan: ScopePlan) -> list[tuple[TestTarget, str]]:
    """Each planned target with the ``-m`` expression of its invocation."""
    out: list[tuple[TestTarget, str]] = []
    for invocation in plan.invocations:
        argv = list(invocation.argv)
        expression = argv[argv.index("-m") + 1] if "-m" in argv and argv.index("-m") + 1 < len(argv) else ""
        out.extend((target, expression) for target in invocation.targets)
    return out


def filter_cached(
    worktree: Path,
    plan: ScopePlan,
    *,
    namespace: str,
    contract: TestContract | None = None,
    policy: ScopePolicy | None = None,
    index: ImportIndex | None = None,
) -> ScopePlan:
    """Drop targets whose stored key equals their current key; rebuild the plan; report them in ``cached``."""
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        return plan
    planned = _planned_targets(plan)
    if not planned:
        return plan
    entries = _read_store(git_dir / CACHE_FILENAME, namespace)
    if not entries:
        return plan
    imports = _imported_sources(index if index is not None else ImportIndex.load_or_build(worktree))
    dropped: list[str] = []
    survivors: list[TestTarget] = []
    for target, expression in planned:
        entry = entries.get(target.path)
        if entry is not None and _is_cacheable(target.path):
            manifest = _manifest(worktree, target.path, expression, imports)
            if manifest is not None and target_key(manifest) == entry["key"]:
                dropped.append(target.path)
                continue
        if target.reason == "contract" and not _is_cacheable(target.path) and contract is not None and contract.markers:
            continue  # the marker sweep is regenerated by build_plan from the contract
        survivors.append(target)
    if not dropped:
        return plan
    rebuilt = build_plan(
        survivors,
        tier=plan.tier,
        worktree=worktree,
        policy=policy or ScopePolicy(),
        escalated=plan.escalated,
        core_hits=plan.core_hits,
        skipped_escalations=plan.skipped_escalations,
        cap_hits=dict(plan.cap_hits),
        cap_impacted=dict(plan.cap_impacted),
        notes=(*plan.notes, f"green cache: skipped {len(dropped)} unchanged target(s)"),
        contract=contract,
        mode=plan.mode,
    )
    return replace(rebuilt, cached=tuple(sorted(dropped)))


def _locked_update(path: Path, namespace: str, mutate) -> None:
    """Read-modify-write the store under an exclusive lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".json.lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            entries = _read_store(path, namespace)
            mutate(entries)
            _atomic_write_json(path, {"schema": CACHE_SCHEMA, "namespace": namespace, "entries": entries})
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def record_green(
    worktree: Path,
    *,
    namespace: str,
    plan: ScopePlan,
    nodes: Sequence[tuple[str, str]],
    unmapped: int = 0,
    baseline_reds: Collection[str] = (),
    index: ImportIndex | None = None,
) -> None:
    """Record green targets / remove re-red ones, under an exclusive file lock. Never raises."""
    try:
        git_dir = worktree_git_dir(worktree)
        if git_dir is None:
            return
        planned = [(t, e) for t, e in _planned_targets(plan) if _is_cacheable(t.path)]
        if not planned:
            return
        reds = set(baseline_reds)
        imports = _imported_sources(index if index is not None else ImportIndex.load_or_build(worktree))
        now = datetime.now(timezone.utc).isoformat()
        new: dict[str, GreenCacheEntry] = {}
        removed: set[str] = set()
        for target, expression in planned:
            own = [(nid, st) for nid, st in nodes if nid == target.path or nid.startswith(target.path + "::")]
            green = (
                unmapped == 0
                and bool(own)
                and all(st in _GREEN_STATUSES or nid in reds for nid, st in own)
            )
            manifest = _manifest(worktree, target.path, expression, imports) if green else None
            if manifest is None:
                removed.add(target.path)
            else:
                new[target.path] = GreenCacheEntry(target=target.path, key=target_key(manifest), recorded_at=now)

        def mutate(entries: dict[str, dict[str, str]]) -> None:
            for name in removed:
                entries.pop(name, None)
            for name, entry in new.items():
                entries[name] = {"key": entry.key, "recorded_at": entry.recorded_at}

        _locked_update(git_dir / CACHE_FILENAME, namespace, mutate)
    except Exception as exc:  # noqa: BLE001 - the cache must never break a run
        logger.warning("Unable to record green cache: %s", exc)


def invalidate(worktree: Path) -> None:
    """Delete the store (no-op outside git or when absent)."""
    git_dir = worktree_git_dir(worktree)
    if git_dir is not None:
        (git_dir / CACHE_FILENAME).unlink(missing_ok=True)
