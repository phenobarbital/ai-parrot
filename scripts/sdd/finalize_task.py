"""Finalize a verified task deterministically without committing or pushing.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M4
(R4 "Cierre de tarea mecánico"). Replaces the multi-step Edit/Write/jq/mv
dance a worker performs to close a task with one verifiable call:

1. Validate identity/evidence/HEAD (never mutates on a stale or incomplete
   input) and reject a divergent active/completed twin before doing
   anything destructive.
2. Render a deterministic Completion Note + metrics table and persist a
   resumable journal, OUTSIDE the worktree, under the same durable root
   `parrot.flows.dev_loop.sdd_coder.telemetry.resolve_durable_root`
   resolves for telemetry/evidence -- a crash between phases resumes from
   observed disk/git state instead of duplicating effects.
3. Invoke the existing `scripts/sdd/close_task.sh` primitive under an
   isolated `GIT_INDEX_FILE`, so its internal `git add -u sdd/tasks/active`
   can never stage another task's pending edits, then transfer ONLY this
   task's own index entries (its active/completed `.md` file and its
   per-spec index) into the real index with a compare-and-swap guard
   against a concurrent change to those same paths.
4. Verify the close_task.sh postconditions itself (no active survivor, a
   completed copy carrying the rendered note, index status "done") before
   reporting success.

This module never runs `git add .`, `git reset`, `git commit`, `git push`
or closes any task other than the one named by the evidence. It returns
staged paths and a suggested commit message; the worker performs the
commit and any semantic review decisions.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files
from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, TaskCompletionEvidence
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root

try:  # POSIX only -- degrades to a no-op lock, matching evidence.py's convention.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NOTE_HEADING = re.compile(r"^## Completion Note\s*$", re.M)
_NEXT_HEADING = re.compile(r"^## ", re.M)
_TELEMETRY_ROOT_ENV = "SDD_CODER_TELEMETRY_DIR"
_VERIFICATION = "verified"


class FinalizeTaskError(RuntimeError):
    """Base class for every domain error `finalize_task`/`main` can raise."""

    error_code = "operation_error"


class InvalidEvidenceError(FinalizeTaskError):
    """Malformed input: bad SHA shape, missing evidence, unresolvable task file."""

    error_code = "invalid_input"


class TaskEvidenceStaleError(FinalizeTaskError):
    """HEAD moved, evidence does not match `expected_head`, or a closed task's
    journal already recorded a different operation (a new SHA/evidence
    payload requires a deliberate new operation, never a silent redo)."""

    error_code = "task_evidence_stale"


class TaskTwinConflictError(FinalizeTaskError):
    """An active and a completed copy of the same task disagree on content."""

    error_code = "task_twin_conflict"


class ConcurrentChangeError(FinalizeTaskError):
    """The real git index changed for this task's own paths mid-operation."""

    error_code = "concurrent_index_change"


class OperationError(FinalizeTaskError):
    """close_task.sh failed, or a postcondition did not hold afterward."""

    error_code = "operation_error"


# ---------------------------------------------------------------------------
# Small git/process helpers.
# ---------------------------------------------------------------------------


def _run_git(
    args: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run one `git` subcommand and capture text output."""
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=check)


def _git_toplevel(worktree: Path) -> Path:
    """Resolve the git repository root for *worktree*, or raise `InvalidEvidenceError`."""
    if not worktree.is_dir():
        raise InvalidEvidenceError(f"worktree path does not exist or is not a directory: {worktree}")
    try:
        out = _run_git(["rev-parse", "--show-toplevel"], cwd=worktree).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise InvalidEvidenceError(f"worktree is not inside a git repository: {worktree} ({exc.stderr})") from exc
    if not out:
        raise InvalidEvidenceError(f"worktree is not inside a git repository: {worktree}")
    return Path(out).resolve()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---------------------------------------------------------------------------
# Evidence/identity/HEAD validation -- never mutates anything.
# ---------------------------------------------------------------------------


def _validate_expected_head(evidence: TaskCompletionEvidence, expected_head: str, repo_root: Path) -> None:
    """Reject a malformed, mismatched or stale `expected_head` before any mutation."""
    if not _FULL_SHA_RE.match(expected_head or ""):
        raise InvalidEvidenceError(f"expected_head must be a full 40-hex-char git SHA, got {expected_head!r}")
    if evidence.implementation_sha != expected_head:
        raise TaskEvidenceStaleError(
            f"evidence.implementation_sha {evidence.implementation_sha!r} != expected_head {expected_head!r}"
        )
    current_head = _run_git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    if current_head != expected_head:
        raise TaskEvidenceStaleError(
            f"worktree HEAD {current_head!r} has moved away from expected_head {expected_head!r}"
        )


def _verify_evidence_refs(durable_root: Path, evidence: TaskCompletionEvidence) -> None:
    """Resolve every evidence reference against durable storage; never trust a claim.

    Rejects an empty `validation_refs` (no green check recorded) and any
    `EvidenceRef` whose content does not durably exist with matching hash
    and size under *durable_root* -- `review_evidence` is never fabricated.
    """
    if not evidence.validation_refs:
        raise InvalidEvidenceError("evidence.validation_refs must include at least one green validation reference")
    for ref in (evidence.review_evidence, *evidence.validation_refs):
        _verify_one_ref(durable_root, ref)


def _verify_one_ref(durable_root: Path, ref: EvidenceRef) -> None:
    resolved_root = durable_root.resolve()
    candidate = (durable_root / ref.relative_path).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise InvalidEvidenceError(f"evidence ref escapes the durable root: {ref.relative_path!r}")
    if candidate.is_symlink() or not candidate.is_file():
        raise InvalidEvidenceError(f"evidence ref does not resolve to a durable artifact: {ref.relative_path!r}")
    data = candidate.read_bytes()
    if len(data) != ref.size_bytes or hashlib.sha256(data).hexdigest() != ref.sha256:
        raise InvalidEvidenceError(f"evidence ref content does not match its declared hash/size: {ref.relative_path!r}")


def _strip_note_section(text: str) -> str:
    """Return *text* with everything from '## Completion Note' onward removed."""
    match = _NOTE_HEADING.search(text)
    return text if not match else text[: match.start()]


def _resolve_task_md(active_matches: list[Path], completed_matches: list[Path]) -> tuple[Path | None, Path | None, str]:
    """Locate the task's active/completed `.md` file(s) and reject a divergent twin.

    Returns `(active_path_or_None, completed_path_or_None, source_text)`.
    Comparison ignores each file's own '## Completion Note' section, since
    that section legitimately differs while a close is in flight.
    """
    if len(active_matches) > 1 or len(completed_matches) > 1:
        raise InvalidEvidenceError("ambiguous task file matches: more than one active/completed candidate")
    active = active_matches[0] if active_matches else None
    completed = completed_matches[0] if completed_matches else None
    if active is None and completed is None:
        raise InvalidEvidenceError("no active or completed task file found for this task_id")

    if active is not None and completed is not None:
        active_text = active.read_text(encoding="utf-8")
        completed_text = completed.read_text(encoding="utf-8")
        if _strip_note_section(active_text) != _strip_note_section(completed_text):
            raise TaskTwinConflictError(
                f"divergent active/completed twins for this task: {active} != {completed}; refusing to close"
            )
        return active, completed, completed_text

    source_path = active if active is not None else completed
    assert source_path is not None
    return active, completed, source_path.read_text(encoding="utf-8")


def _collect_changed_files(repo_root: Path, implementation_sha: str, fix_commits: Iterable[str]) -> list[str]:
    """Union of files changed by `implementation_sha` and every fix commit."""
    changed: set[str] = set()
    for sha in (implementation_sha, *fix_commits):
        out = _run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", sha], cwd=repo_root).stdout
        changed.update(line.strip() for line in out.splitlines() if line.strip())
    return sorted(changed)


# ---------------------------------------------------------------------------
# Deterministic Completion Note rendering.
# ---------------------------------------------------------------------------


def _render_completion_note(evidence: TaskCompletionEvidence, *, closed_at: str) -> str:
    """Render a stable Completion Note + metrics table from evidence alone.

    Deterministic across resumed calls: no wall-clock read here, only the
    journaled `closed_at` and sorted evidence fields.
    """
    fix_commits = ", ".join(evidence.fix_commits) if evidence.fix_commits else "none"
    lines = [
        f"- Task: {evidence.task_id}",
        f"- Feature: {evidence.feature_slug}",
        f"- Implementation SHA: {evidence.implementation_sha}",
        f"- Closed at (UTC): {closed_at}",
        f"- Fix commits: {fix_commits}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| validation_refs | {len(evidence.validation_refs)} |",
        f"| fix_commits | {len(evidence.fix_commits)} |",
    ]
    for key in sorted(evidence.completion_facts):
        lines.append(f"| {key} | {evidence.completion_facts[key]} |")
    return "\n".join(lines) + "\n"


def _apply_completion_note(task_md: str, note: str) -> str:
    """Replace the '## Completion Note' section body with *note* (idempotent)."""
    match = _NOTE_HEADING.search(task_md)
    if not match:
        sep = "" if task_md.endswith("\n") else "\n"
        return f"{task_md}{sep}\n## Completion Note\n\n{note}"
    head = task_md[: match.end()]
    rest = task_md[match.end() :]
    tail_match = _NEXT_HEADING.search(rest)
    tail = rest[tail_match.start() :] if tail_match else ""
    return f"{head}\n\n{note}{tail}"


def _ensure_note_applied(path: Path, note: str) -> None:
    """Write the rendered note into *path* only if it is not already present."""
    text = path.read_text(encoding="utf-8")
    new_text = _apply_completion_note(text, note)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Journal: resumable operation state, outside any worktree/code file.
# ---------------------------------------------------------------------------


def _hash_evidence(evidence: TaskCompletionEvidence) -> str:
    canonical = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _journal_paths(durable_root: Path, feature_slug: str, task_id: str) -> tuple[Path, Path]:
    journal_dir = durable_root / "finalize_task" / feature_slug
    return journal_dir / f"{task_id}.json", journal_dir / f".{task_id}.lock"


def _load_journal(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_journal(path: Path, **fields: object) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_journal(path) or {}
    existing.update(fields)
    existing["updated_at"] = _utcnow_iso()
    existing.setdefault("created_at", existing["updated_at"])
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(existing, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return existing


@contextlib.contextmanager
def _serialized(lock_path: Path):
    """Hold an exclusive, blocking lock on *lock_path* -- one operation per task/index at a time."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# close_task.sh, invoked under an isolated GIT_INDEX_FILE.
# ---------------------------------------------------------------------------


def _stage_snapshot(repo_root: Path, real_index_path: Path, paths: Iterable[str]) -> dict[str, str | None]:
    """One `git ls-files --stage` line per owned path in the REAL index (CAS baseline)."""
    env = {**os.environ, "GIT_INDEX_FILE": str(real_index_path)}
    snapshot: dict[str, str | None] = {}
    for path in sorted(paths):
        out = _run_git(["ls-files", "--stage", "--", path], cwd=repo_root, env=env, check=False).stdout.strip()
        snapshot[path] = out or None
    return snapshot


def _parse_name_status(diff_output: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in diff_output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0]
        entries.append((status, parts[1]))
    return entries


def _belongs_to_task(path: str, task_id: str, feature_slug: str) -> bool:
    if path == f"sdd/tasks/index/{feature_slug}.json":
        return True
    name = Path(path).name
    if path.startswith("sdd/tasks/active/") and name.startswith(f"{task_id}-"):
        return True
    if path.startswith("sdd/tasks/completed/") and name.startswith(f"{task_id}-"):
        return True
    return False


def _ls_tree_entry(repo_root: Path, tree: str, path: str) -> tuple[str, str]:
    out = _run_git(["ls-tree", tree, "--", path], cwd=repo_root).stdout.strip()
    if not out:
        raise OperationError(f"path {path!r} unexpectedly missing from tree {tree}")
    meta, _, _ = out.partition("\t")
    mode, _obj_type, blob_sha = meta.split()
    return mode, blob_sha


def _close_task_isolated(repo_root: Path, task_id: str, feature_slug: str) -> list[str]:
    """Run `close_task.sh` under a throwaway index and transfer only this task's entries.

    `close_task.sh` internally runs `git add -u sdd/tasks/active`, which
    would stage any OTHER task's pending edits if invoked directly against
    the real index. Running it with `GIT_INDEX_FILE` pointed at a private
    copy confines every index mutation there; only the entries this task
    owns (its own active/completed `.md` and its per-spec index) are then
    replayed onto the real index via targeted `git update-index` calls,
    guarded by a compare-and-swap check against a concurrent change.
    """
    close_script = repo_root / "scripts" / "sdd" / "close_task.sh"
    if not close_script.is_file():
        raise OperationError(f"close_task.sh not found at {close_script}")

    real_index_path = Path(
        _run_git(["rev-parse", "--path-format=absolute", "--git-path", "index"], cwd=repo_root).stdout.strip()
    )
    real_env = {**os.environ, "GIT_INDEX_FILE": str(real_index_path)}

    active_dir = repo_root / "sdd" / "tasks" / "active"
    completed_dir = repo_root / "sdd" / "tasks" / "completed"
    index_json = repo_root / "sdd" / "tasks" / "index" / f"{feature_slug}.json"

    owned_paths = {
        p.relative_to(repo_root).as_posix()
        for p in (*active_dir.glob(f"{task_id}-*.md"), *completed_dir.glob(f"{task_id}-*.md"))
    }
    owned_paths.add(index_json.relative_to(repo_root).as_posix())

    before_snapshot = _stage_snapshot(repo_root, real_index_path, owned_paths)
    orig_tree = _run_git(["write-tree"], cwd=repo_root, env=real_env).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="sdd-finalize-index-") as tmp_dir:
        tmp_index_path = Path(tmp_dir) / "index"
        if real_index_path.exists():
            shutil.copyfile(real_index_path, tmp_index_path)
        tmp_env = {**os.environ, "GIT_INDEX_FILE": str(tmp_index_path)}

        proc = subprocess.run(
            ["bash", str(close_script), task_id, feature_slug, _VERIFICATION],
            cwd=repo_root,
            env=tmp_env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise OperationError(f"close_task.sh failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")

        new_tree = _run_git(["write-tree"], cwd=repo_root, env=tmp_env).stdout.strip()

    diff_output = _run_git(["diff", "--no-renames", "--name-status", orig_tree, new_tree], cwd=repo_root).stdout
    changed = _parse_name_status(diff_output)
    own_changed = [(status, path) for status, path in changed if _belongs_to_task(path, task_id, feature_slug)]
    foreign_changed = [(status, path) for status, path in changed if not _belongs_to_task(path, task_id, feature_slug)]
    if foreign_changed:
        sys.stderr.write(
            "finalize_task: ignoring foreign index entries close_task.sh staged in the isolated index: "
            f"{foreign_changed}\n"
        )

    after_snapshot = _stage_snapshot(repo_root, real_index_path, owned_paths)
    if after_snapshot != before_snapshot:
        raise ConcurrentChangeError("the real git index changed concurrently for this task's own paths")

    staged: list[str] = []
    for status, path in own_changed:
        if status == "D":
            _run_git(["update-index", "--force-remove", "--", path], cwd=repo_root, env=real_env)
        else:
            mode, blob_sha = _ls_tree_entry(repo_root, new_tree, path)
            _run_git(
                ["update-index", "--add", "--cacheinfo", f"{mode},{blob_sha},{path}"],
                cwd=repo_root,
                env=real_env,
            )
            staged.append(path)
    return sorted(staged)


def _verify_postconditions(repo_root: Path, task_id: str, feature_slug: str, note: str) -> None:
    """Hard-verify no active survivor, a completed copy with the note, and index status done."""
    active_dir = repo_root / "sdd" / "tasks" / "active"
    completed_dir = repo_root / "sdd" / "tasks" / "completed"

    survivors = list(active_dir.glob(f"{task_id}-*.md"))
    if survivors:
        raise OperationError(f"postcondition failed: active copy still present: {survivors}")

    completed_matches = list(completed_dir.glob(f"{task_id}-*.md"))
    if not completed_matches:
        raise OperationError(f"postcondition failed: no completed copy found for {task_id}")
    completed_text = completed_matches[0].read_text(encoding="utf-8")
    if note.strip() not in completed_text:
        raise OperationError("postcondition failed: rendered completion note missing from completed file")

    index_path = repo_root / "sdd" / "tasks" / "index" / f"{feature_slug}.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    entry = next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
    if entry is None or entry.get("status") != "done":
        raise OperationError(f"postcondition failed: index status for {task_id} is not 'done'")


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def finalize_task(*, evidence: TaskCompletionEvidence, worktree: Path, expected_head: str) -> dict[str, object]:
    """Validate evidence, journal intent, close one task and return staged paths.

    Never `git add .`, reset, commit or push, and never closes a task other
    than `evidence.task_id`. Idempotent replay for an identical
    `task_id + implementation_sha + evidence` triple; a different SHA or
    evidence for an already-closed task raises `TaskEvidenceStaleError`
    instead of silently redoing the close.
    """
    worktree = Path(worktree)
    repo_root = _git_toplevel(worktree)
    _validate_expected_head(evidence, expected_head, repo_root)

    configured_root = os.environ.get(_TELEMETRY_ROOT_ENV) or None
    durable_root = resolve_durable_root(configured_root, worktree_base_path=str(repo_root))
    journal_path, lock_path = _journal_paths(durable_root, evidence.feature_slug, evidence.task_id)

    evidence_hash = _hash_evidence(evidence)
    operation_key = f"{evidence.task_id}:{evidence.implementation_sha}:{evidence_hash}"

    with _serialized(lock_path):
        journal = _load_journal(journal_path)

        if journal is not None and journal.get("phase") == "done":
            if journal.get("operation_key") != operation_key:
                raise TaskEvidenceStaleError(
                    f"{evidence.task_id} was already closed under a different implementation_sha/evidence; "
                    "a changed SHA or evidence requires a new, deliberate operation"
                )
            _verify_postconditions(repo_root, evidence.task_id, evidence.feature_slug, str(journal["note"]))
            result = dict(journal["result"])  # type: ignore[arg-type]
            result["replayed"] = True
            return result

        # -- validation: never mutates anything below this point until it passes. --
        _verify_evidence_refs(durable_root, evidence)

        index_path = repo_root / "sdd" / "tasks" / "index" / f"{evidence.feature_slug}.json"
        if not index_path.is_file():
            raise InvalidEvidenceError(f"no per-spec index for feature_slug {evidence.feature_slug!r}: {index_path}")

        active_dir = repo_root / "sdd" / "tasks" / "active"
        completed_dir = repo_root / "sdd" / "tasks" / "completed"
        active_matches = sorted(active_dir.glob(f"{evidence.task_id}-*.md"))
        completed_matches = sorted(completed_dir.glob(f"{evidence.task_id}-*.md"))
        active_path, completed_path, task_md_text = _resolve_task_md(active_matches, completed_matches)

        expected_files = parse_task_files(task_md_text)
        changed_files = _collect_changed_files(repo_root, evidence.implementation_sha, evidence.fix_commits)
        report = check_fidelity(expected_files, changed_files)
        if not report.ok:
            raise InvalidEvidenceError(
                f"fidelity check failed for {evidence.task_id}: unexpected={report.unexpected} "
                f"sdd_touched={report.sdd_touched}"
            )

        closed_at = journal.get("closed_at") if journal and journal.get("operation_key") == operation_key else None
        closed_at = str(closed_at) if closed_at else _utcnow_iso()
        note = _render_completion_note(evidence, closed_at=closed_at)

        journal = _write_journal(
            journal_path,
            operation_key=operation_key,
            phase="validated",
            note=note,
            closed_at=closed_at,
            feature_slug=evidence.feature_slug,
            task_id=evidence.task_id,
        )

        # -- mutation: apply the note to whichever copy currently exists. --
        source_path = active_path if active_path is not None else completed_path
        assert source_path is not None
        _ensure_note_applied(source_path, note)

        staged_paths = _close_task_isolated(repo_root, evidence.task_id, evidence.feature_slug)
        _verify_postconditions(repo_root, evidence.task_id, evidence.feature_slug, note)

        result: dict[str, object] = {
            "task_id": evidence.task_id,
            "feature_slug": evidence.feature_slug,
            "implementation_sha": evidence.implementation_sha,
            "staged_paths": staged_paths,
            "note": note,
            "message": f"sdd: complete {evidence.task_id} for {evidence.feature_slug}",
            "replayed": False,
        }
        _write_journal(
            journal_path,
            operation_key=operation_key,
            phase="done",
            note=note,
            closed_at=closed_at,
            feature_slug=evidence.feature_slug,
            task_id=evidence.task_id,
            result=result,
        )
        return result


def main(argv: list[str] | None = None) -> int:
    """Exit 0 success/replay, 1 operation error, 2 invalid input, 3 stale/busy."""
    parser = argparse.ArgumentParser(prog="python -m scripts.sdd.finalize_task", description=__doc__)
    parser.add_argument("--evidence", required=True, help="Path to a JSON file with a TaskCompletionEvidence payload")
    parser.add_argument("--worktree", required=True, help="Path to the task's git worktree")
    parser.add_argument("--expected-head", required=True, help="Full 40-hex git SHA the caller expects HEAD to be")
    args = parser.parse_args(argv)

    evidence_path = Path(args.evidence)
    try:
        raw = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence = TaskCompletionEvidence.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(json.dumps({"ok": False, "error": "invalid_input", "message": str(exc)}))
        return 2

    try:
        result = finalize_task(evidence=evidence, worktree=Path(args.worktree), expected_head=args.expected_head)
    except InvalidEvidenceError as exc:
        print(json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}))
        return 2
    except (TaskEvidenceStaleError, TaskTwinConflictError, ConcurrentChangeError) as exc:
        print(json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}))
        return 3
    except OperationError as exc:
        print(json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}))
        return 1

    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
