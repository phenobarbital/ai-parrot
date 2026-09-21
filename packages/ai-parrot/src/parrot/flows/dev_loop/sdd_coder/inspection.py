"""Read-only SDD context and delivery projections using existing fidelity rules.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584) M1b/R1b:
replace repeated exploratory reads ("cadenas conocidas") with two
purpose-built, side-effect-free operations. Both functions here are pure
PROJECTIONS over already-durable state (the per-spec task index, a task's
markdown contract, and git refs a coder attempt already created) -- neither
ever mutates the SDD index, runs tests, lints, merges or approves a
delivery, and neither duplicates `check_fidelity`'s policy -- it is reused
verbatim from `fidelity.py`.

`SddCoderEngine.task_context`/`delivery_report` are the only intended
callers (spec: "pasar contexto validado del engine"): they perform
feature/execution ownership checks with `_resolve_feature` BEFORE calling
into this module, so `feature`/`worktree`/`execution_id` are trusted here to
already be legitimate for the caller. `worktree` is always the FEATURE
worktree (the same one every other `coder_*` tool takes) -- never a task's
own sub-worktree -- matching the established `(feature, worktree, task_id,
execution_id)` idiom used throughout `toolkit.py`/`engine.py`.

Both snapshots are bounded to a small inline excerpt (spec AC4/AC5: "16KiB")
of any potentially large text (a task's full markdown body, a full diff);
the complete content is always durably published via `store.put_artifact`
first, so a caller that needs more than the excerpt can page through it with
`store.read_artifact` using the returned `EvidenceRef`. Nothing here invents
a second bounding policy: `evidence.py`'s `MAX_READ_LIMIT` already bounds a
single `read_artifact` page.

Attempt/branch discovery (`delivery_report` only) mirrors
`SddCoderEngine._orphan_branches`' own, already-established precedent:
enumerate real branches matching the engine's own `_worker_id`/`_branch_for`
naming convention, verify each candidate actually exists in git, and reject
(never adopt) anything whose embedded `execution_id` hex does not match the
execution making the request -- this is discovery-and-verification, not a
blind guess, and it never mutates anything (`_parse_orphan_suffix`'s own
docstring: "this is parsing for reporting only"). A tiny private `_git`
helper is defined locally (mirroring `engine.py`'s own) rather than imported
from `engine.py`, since `engine.py` calls into this module lazily from
inside its own methods -- keeping this module's own imports independent of
`engine.py` avoids any import-cycle risk entirely.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler

#: Spec AC4/AC5: keep every returned snapshot's own (non-referenced) content small.
_MAX_INLINE_EXCERPT_BYTES = 4096
_ORPHANS_INDEX_NAME = "_orphans.json"

#: Mirrors `SddCoderEngine._EXEC_HEX_BRANCH_SUFFIX` (engine.py) -- a trailing
#: 32-lowercase-hex-char execution suffix, appended by `_worker_id` whenever
#: an execution_id is bound to the attempt.
_EXEC_HEX_BRANCH_SUFFIX = re.compile(r"-([0-9a-f]{32})$")


class _TextArtifact(BaseModel):
    """Raw text payload, published via `store.put_artifact` only to page large content.

    Never exported outside this module -- a minimal wrapper so
    `ExecutionEvidenceStore.put_artifact` (which only accepts a `BaseModel`
    payload) can durably persist plain text (a task's full markdown body, a
    full diff) without inventing a new shared schema for it.
    """

    model_config = ConfigDict(extra="forbid")

    text: str


async def _git(*args: str, cwd: Path) -> Tuple[int, str, str]:
    """Run git read-only in *cwd*. Local, minimal mirror of `engine.py`'s own `_git` helper."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _excerpt(text: str, *, limit: int = _MAX_INLINE_EXCERPT_BYTES) -> Tuple[str, bool]:
    """Return `(excerpt, truncated)`; `excerpt` never exceeds *limit* encoded bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


async def _publish_text(store: ExecutionEvidenceStore, execution_id: str, text: str) -> Dict[str, object]:
    """Durably publish *text* and return its `EvidenceRef` as a plain dict."""
    ref = await store.put_artifact(execution_id, _TextArtifact(text=text))
    return ref.model_dump()


def _resolve_index_path(worktree: Path, feature: str) -> Path:
    """The per-spec index path `TaskScheduler.from_worktree` itself resolves to (FEAT-145)."""
    return worktree / "sdd" / "tasks" / "index" / f"{feature}.json"


def _load_scheduler(worktree: Path, feature: str) -> TaskScheduler:
    """Load the per-spec `TaskScheduler` for *feature* under *worktree*.

    Raises:
        FileNotFoundError: the per-spec index is missing or unreadable.
    """
    sched = TaskScheduler.from_worktree(str(worktree), feature)
    if sched is None:
        raise FileNotFoundError(f"per-spec index unreadable or missing for feature {feature!r} under {worktree}")
    return sched


def _find_task(sched: TaskScheduler, task_id: str) -> TaskRef:
    """Look up *task_id* in *sched*.

    Raises:
        LookupError: no such task in the per-spec index.
    """
    for task_ref in sched.all_tasks():
        if task_ref.id == task_id:
            return task_ref
    raise LookupError(f"{task_id} is not declared in this feature's per-spec index")


def _confined_read_text(worktree: Path, relative_path: str) -> str:
    """Read *relative_path* under *worktree*, refusing any escape (mirrors `_consolidate`'s own check)."""
    candidate = (worktree / relative_path).resolve()
    root = worktree.resolve()
    if not (candidate == root or str(candidate).startswith(str(root) + "/")):
        raise ValueError(f"path {relative_path!r} resolves outside the feature worktree")
    return candidate.read_text(encoding="utf-8")


async def task_context(
    *, feature: str, worktree: Path, task_id: str, execution_id: str, store: ExecutionEvidenceStore
) -> dict[str, object]:
    """Resolve index, task, dependencies and contract into a bounded snapshot.

    Never marks a task ready on trust: `ready` only reflects the SAME
    dependency-graph state `TaskScheduler.next_wave()` itself computes, and
    an unmet (not-yet-`done`) dependency is always surfaced in `blockers`,
    never silently treated as satisfied.

    Raises:
        FileNotFoundError: the per-spec index is missing or unreadable.
        LookupError: *task_id* is not declared in the index.
        ValueError: the task's declared file resolves outside *worktree*.
    """
    sched = _load_scheduler(worktree, feature)
    task_ref = _find_task(sched, task_id)

    done_ids = {t.id for t in sched.done()}
    blockers = [dep for dep in task_ref.depends_on if dep not in done_ids]
    dependency_status = {dep: ("done" if dep in done_ids else "blocked") for dep in task_ref.depends_on}
    ready = not blockers and task_ref.id in {t.id for t in sched.next_wave()}

    index_path = _resolve_index_path(worktree, feature)
    index_bytes = index_path.read_bytes()
    index_sha256 = hashlib.sha256(index_bytes).hexdigest()

    contract: List[str] = []
    task_md_excerpt = ""
    task_md_truncated = False
    task_md_sha256 = ""
    task_md_ref: Optional[Dict[str, object]] = None
    if task_ref.file:
        task_md = _confined_read_text(worktree, task_ref.file)
        task_md_sha256 = hashlib.sha256(task_md.encode("utf-8")).hexdigest()
        contract = parse_task_files(task_md)
        task_md_excerpt, task_md_truncated = _excerpt(task_md)
        task_md_ref = await _publish_text(store, execution_id, task_md)

    return {
        "feature": feature,
        "task_id": task_id,
        "execution_id": execution_id,
        "status": task_ref.status,
        "title": task_ref.title,
        "ready": ready,
        "depends_on": list(task_ref.depends_on),
        "blockers": blockers,
        "dependency_status": dependency_status,
        "task_file": task_ref.file,
        "contract": contract,
        "index_path": str(index_path.relative_to(worktree)),
        "index_sha256": index_sha256,
        "task_file_sha256": task_md_sha256,
        "task_md_excerpt": task_md_excerpt,
        "task_md_truncated": task_md_truncated,
        "task_md_ref": task_md_ref,
    }


def _parse_attempt_branch(branch: str, *, prefix: str) -> Optional[Tuple[int, str]]:
    """Parse `<prefix><attempt>[-<32-hex execution suffix>]`, or `None` if unparseable.

    *prefix* already ends in `-a` (see `_discover_attempt_branch`), so the
    remaining `core` is just the attempt digits. Reporting-only parse of the
    engine's own `_worker_id`/`_branch_for` convention (mirrors
    `SddCoderEngine._parse_orphan_suffix`) -- never used to adopt or mutate
    anything, only to discover which already-existing branch (verified live
    against git, below) corresponds to *task_id*.
    """
    if not branch.startswith(prefix):
        return None
    suffix = branch[len(prefix) :]
    hex_match = _EXEC_HEX_BRANCH_SUFFIX.search(suffix)
    exec_hex = hex_match.group(1) if hex_match else ""
    core = suffix[: hex_match.start()] if hex_match else suffix
    if not core.isdigit():
        return None
    return int(core), exec_hex


async def _discover_attempt_branch(
    worktree: Path, *, feature_branch: str, task_id: str, execution_id: str
) -> Optional[Tuple[str, int]]:
    """Return `(branch, attempt)` for the highest verified, execution-owned attempt, or `None`.

    Every candidate is a REAL branch (`git branch --list`), never assumed;
    a candidate whose embedded execution hex does not match *execution_id*
    is rejected outright -- a foreign or stale execution can never produce
    a trustworthy match here (spec: never yield a delivery snapshot for a
    foreign worktree/execution).
    """
    prefix = f"{feature_branch}--{task_id}-a"
    rc, out, _err = await _git("branch", "--list", f"{prefix}*", "--format=%(refname:short)", cwd=worktree)
    if rc != 0:
        return None
    exec_hex = execution_id.replace("-", "")
    best: Optional[Tuple[str, int]] = None
    for branch in (b.strip() for b in out.splitlines() if b.strip()):
        parsed = _parse_attempt_branch(branch, prefix=prefix)
        if parsed is None:
            continue
        attempt, branch_hex = parsed
        if branch_hex != exec_hex:
            continue  # a different execution's attempt -- never adopted here
        if best is None or attempt > best[1]:
            best = (branch, attempt)
    return best


async def delivery_report(
    *, feature: str, worktree: Path, task_id: str, execution_id: str, store: ExecutionEvidenceStore
) -> dict[str, object]:
    """Report issued attempt, immutable diff, scope and known verification refs.

    Never runs `git merge`, lint, tests or a fresh validation -- every fact
    here is either a plain `git` read against already-committed refs or an
    absent-therefore-`"unknown"` evidence field (spec: "Evidencia ausente
    aparece como unknown"). The whole snapshot is pinned to one resolved
    commit (`branch_head_sha`, captured up front) so a concurrent commit to
    the attempt branch mid-computation cannot produce a torn, inconsistent
    report.

    Raises:
        FileNotFoundError: the per-spec index is missing or unreadable.
        LookupError: *task_id* is not declared in the index, or no
            execution-owned attempt branch exists for it.
        ValueError: the task's declared file resolves outside *worktree*.
    """
    sched = _load_scheduler(worktree, feature)
    task_ref = _find_task(sched, task_id)

    rc, head_out, _err = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    if rc != 0:
        raise FileNotFoundError(f"could not determine the current branch of {worktree}")
    feature_branch = head_out.strip()

    found = await _discover_attempt_branch(
        worktree, feature_branch=feature_branch, task_id=task_id, execution_id=execution_id
    )
    if found is None:
        raise LookupError(f"no execution-owned attempt branch found for {task_id} in execution {execution_id}")
    branch, attempt = found

    rc, sha_out, _err = await _git("rev-parse", branch, cwd=worktree)
    branch_head_sha = sha_out.strip() if rc == 0 else ""

    rc, commits_out, _err = await _git("rev-list", "--count", f"{feature_branch}..{branch_head_sha}", cwd=worktree)
    commits = int(commits_out.strip() or 0) if rc == 0 else 0

    rc, diff_stat, _err = await _git("diff", "--stat", f"{feature_branch}...{branch_head_sha}", cwd=worktree)
    diff_stat = diff_stat if rc == 0 else ""

    rc, diff_names, _err = await _git("diff", "--name-only", f"{feature_branch}...{branch_head_sha}", cwd=worktree)
    changed = [p for p in diff_names.splitlines() if p.strip()] if rc == 0 else []

    contract: List[str] = []
    if task_ref.file:
        task_md = _confined_read_text(worktree, task_ref.file)
        contract = parse_task_files(task_md)
    fidelity = check_fidelity(contract, changed)

    diff_stat_excerpt, diff_stat_truncated = _excerpt(diff_stat)
    diff_stat_ref = await _publish_text(store, execution_id, diff_stat) if diff_stat_truncated else None
    changed_files_ref: Optional[Dict[str, object]] = None
    changed_preview = changed
    if len(changed) > 200:
        changed_files_ref = await _publish_text(store, execution_id, "\n".join(changed))
        changed_preview = changed[:200]

    # Best-effort only (spec: "estado del sub-worktree"): the sub-worktree
    # directory follows the same documented layout `SubWorktreeManager`
    # itself creates (`<worktree base>/<feature_branch>--pool/<suffix>`),
    # but it may already be gone (`coder_cleanup` ran) -- absent is
    # "unknown", never an error, since the diff/fidelity facts above remain
    # valid and durable regardless of the sub-worktree's own lifecycle.
    branch_suffix = branch[len(f"{feature_branch}--") :]
    sub_worktree_path = worktree.parent / f"{feature_branch}--pool" / branch_suffix
    sub_worktree_present = sub_worktree_path.is_dir()
    sub_worktree_dirty: Optional[bool] = None
    sub_worktree_untracked: Optional[List[str]] = None
    if sub_worktree_present:
        rc, status_out, _err = await _git("status", "--porcelain", "--untracked-files=all", cwd=sub_worktree_path)
        if rc == 0:
            lines = [line for line in status_out.splitlines() if line.strip()]
            sub_worktree_dirty = bool(lines)
            sub_worktree_untracked = [line[3:] for line in lines if line.startswith("??")]

    return {
        "feature": feature,
        "task_id": task_id,
        "execution_id": execution_id,
        "branch": branch,
        "attempt": attempt,
        "feature_branch": feature_branch,
        "branch_head_sha": branch_head_sha,
        "commits": commits,
        "changed_files": changed_preview,
        "changed_files_total": len(changed),
        "changed_files_ref": changed_files_ref,
        "unexpected_files": fidelity.unexpected,
        "sdd_touched": fidelity.sdd_touched,
        "fidelity_ok": fidelity.ok,
        "diff_stat_excerpt": diff_stat_excerpt,
        "diff_stat_truncated": diff_stat_truncated,
        "diff_stat_ref": diff_stat_ref,
        "sub_worktree_path": str(sub_worktree_path) if sub_worktree_present else None,
        "sub_worktree_present": sub_worktree_present,
        "sub_worktree_dirty": sub_worktree_dirty,
        "sub_worktree_untracked": sub_worktree_untracked,
        # No producer in this task's scope yet publishes lint/test/review
        # evidence into the durable store under a discoverable key,
        # so these are unconditionally "unknown" -- never fabricated as a
        # pass, and never silently reinterpreted as a merge/validation.
        "lint_evidence": "unknown",
        "test_evidence": "unknown",
        "review_evidence": "unknown",
    }
