"""Durable neutral handoff after authoritative execution settlement.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M4
(R5 "Checkpoint antes del code reviewer"). A `scripts.sdd.review_checkpoint`
CLI is a SEPARATE process from the MCP engine, so it never has access to
the engine's own in-memory tables (`SddCoderEngine._executions`,
`_validation_handles`, ...) -- every fact this module relies on is
re-derived from durable, on-disk state:

- The execution's settlement is the `ExecutionSnapshot` `end_execution`
  (`engine.py`, TASK-3565) publishes OUTSIDE the worktree via
  `ExecutionEvidenceStore.put_artifact`, under
  `<root>/executions/<execution_id>/artifacts/<sha256>.json`. There is no
  index of which artifact IS the settlement -- this module scans that
  directory and keeps only artifacts that parse as a `closed`
  `ExecutionSnapshot` scoped to this `(feature, worktree, execution_id)`,
  picking the highest `generation` when more than one exists. A settlement
  write that failed (`end_execution`'s own `persistence_degraded` path)
  simply leaves nothing to find here -- `checkpoint_busy` follows naturally,
  never a fabricated "degraded but let's proceed".
- "Settled validations" (spec R8) are read the same way: every
  `BackgroundRegistration` of `kind == 'validation'` registered under
  `<root>/executions/<execution_id>/background/*.json` (TASK-3563/3564/3565)
  is re-checked via the PUBLIC `BackgroundRegistry.status()` API -- never a
  cached outcome. A registry record that fails to parse is treated as
  unresolved (busy), never silently skipped: an unknown state is never
  zero activity (spec R8).

`prepare_review_checkpoint` never mutates execution state or the engine's
close scripts -- it only reads the durable settlement/validations, hashes
the spec/index/conventions and git refs it can observe directly, and
publishes an immutable `ReviewCheckpoint` record under
`<root>/executions/<execution_id>/review/<checkpoint_id>.json` (spec R3
layout). `validate_review_checkpoint` re-derives the SAME facts from
scratch and rejects any drift -- it never approves the underlying code.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, ValidationError

from parrot.flows.dev_loop.sdd_coder.background import (
    BackgroundBudgetExceededError,
    BackgroundNotFoundError,
    BackgroundRegistry,
)
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.models import ExecutionSnapshot
from parrot.flows.dev_loop.sdd_coder.optimization_models import (
    BackgroundRegistration,
    EvidenceRef,
    ReviewCheckpoint,
)
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root
from parrot.flows.dev_loop.task_scheduler import TaskScheduler

logger = logging.getLogger(__name__)

#: Same shape as `optimization_models._UUID_RE`/`background._EXECUTION_ID_RE`
#: (not imported -- each module keeps its own copy of this closed shape,
#: matching the established convention in this task family).
_EXECUTION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CHECKPOINT_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: Same 8 KiB budget `ReviewCheckpoint.neutral_brief` itself enforces
#: (`optimization_models._MAX_CHECKPOINT_BRIEF_BYTES`, private to that
#: module) -- duplicated here only as a defensive pre-truncation bound so
#: the model's own validator never has to reject what this renderer built.
_MAX_CHECKPOINT_BRIEF_BYTES = 8192
_MAX_BRIEF_ITEMS = 25

#: The three byte-identical copies FEAT-553 established as the binding
#: convention set (CLAUDE.md "FEAT-553 coder conventions + turn budget").
#: Hardcoded rather than discovered by glob: a checkpoint's hash must cover
#: exactly the documents a reviewer is bound by, never an accidental extra
#: match under a worktree the caller does not fully control.
_CONVENTION_FILES: Tuple[str, ...] = (
    ".claude/rules/codebase-conventions.md",
    ".agent/rules/codebase-conventions.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md",
)

#: Mirrors `scripts.sdd.finalize_task._TELEMETRY_ROOT_ENV`: the durable root
#: override `validate_review_checkpoint` reads directly, since its blueprint
#: signature carries no `store`/root parameter of its own.
_TELEMETRY_ROOT_ENV = "SDD_CODER_TELEMETRY_DIR"

_CRITERIA_HEADING = re.compile(r"^## Acceptance Criteria\s*$", re.M)
_NEXT_HEADING = re.compile(r"^## ", re.M)


class CheckpointError(RuntimeError):
    """Base class for every domain error this module/`review_checkpoint.py` raises."""

    error_code = "operation_error"


class CheckpointBusyError(CheckpointError):
    """Execution not durably closed, or admitted work/validations not settled.

    Spec R5: "Un estado desconocido no equivale a cero actividad" -- covers
    both a genuinely in-flight execution AND one this module simply cannot
    yet observe as closed/settled.
    """

    error_code = "checkpoint_busy"


class CheckpointIncompleteError(CheckpointError):
    """Required evidence, hashes or scope binding are missing or mismatched.

    Never a partial/best-effort checkpoint: spec R5 "sin aprobación sintética".
    """

    error_code = "checkpoint_incomplete"


class CheckpointStaleError(CheckpointError):
    """HEAD, branch, spec/index/convention hashes or evidence drifted since preparation.

    Spec R5: "Si cambian, devolver checkpoint_stale y regenerar; ninguna
    aprobación anterior cubre el nuevo diff."
    """

    error_code = "checkpoint_stale"


class _TextArtifact(BaseModel):
    """Raw text payload, published only to durably reference a large excerpt.

    Never exported outside this module -- mirrors `inspection.py`'s own
    private `_TextArtifact`, kept as a separate minimal wrapper per module
    rather than a shared schema (established convention in this task family).
    """

    model_config = ConfigDict(extra="forbid")

    text: str


def _validate_execution_id(execution_id: str) -> str:
    """Reject a caller-supplied `execution_id` that is not a canonical UUID."""
    if not _EXECUTION_ID_RE.match(execution_id or ""):
        raise ValueError(f"execution_id must be a canonical UUID, got {execution_id!r}")
    return execution_id


async def _git(*args: str, cwd: Path) -> Tuple[int, str, str]:
    """Run git read-only in *cwd*. Local, minimal mirror of `inspection.py`'s own `_git`."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _confined_path(worktree: Path, relative_path: str) -> Path:
    """Resolve *relative_path* under *worktree*, refusing any escape (mirrors `inspection.py`)."""
    candidate = (worktree / relative_path).resolve()
    root = worktree.resolve()
    if not (candidate == root or str(candidate).startswith(str(root) + os.sep)):
        raise ValueError(f"path {relative_path!r} resolves outside the feature worktree")
    return candidate


def _confined_read_bytes(worktree: Path, relative_path: str) -> bytes:
    return _confined_path(worktree, relative_path).read_bytes()


def _confined_read_text(worktree: Path, relative_path: str) -> str:
    return _confined_path(worktree, relative_path).read_text(encoding="utf-8")


def _index_path(worktree: Path, feature: str) -> Path:
    """Same convention `TaskScheduler.from_worktree`/`inspection._resolve_index_path` use."""
    return worktree / "sdd" / "tasks" / "index" / f"{feature}.json"


def _load_index_sync(worktree: Path, feature: str) -> Tuple[Path, bytes, dict]:
    """Read the per-spec index header + raw bytes, or raise `CheckpointIncompleteError`."""
    path = _index_path(worktree, feature)
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CheckpointIncompleteError(f"per-spec index unreadable or missing at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckpointIncompleteError(f"per-spec index at {path} is not a JSON object")
    return path, raw, data


def _extract_criteria_section(task_md: str) -> str:
    """Return the body of '## Acceptance Criteria' up to the next '## ' heading, or ''."""
    match = _CRITERIA_HEADING.search(task_md)
    if not match:
        return ""
    rest = task_md[match.end() :]
    tail_match = _NEXT_HEADING.search(rest)
    body = rest[: tail_match.start()] if tail_match else rest
    return body.strip()


async def _publish_text(store: ExecutionEvidenceStore, execution_id: str, text: str) -> EvidenceRef:
    """Durably publish *text* and return its `EvidenceRef`."""
    return await store.put_artifact(execution_id, _TextArtifact(text=text))


def _find_settlement_snapshot_sync(root: Path, execution_id: str) -> Optional[ExecutionSnapshot]:
    """Scan the durable artifacts dir for the closed `ExecutionSnapshot` `end_execution` published.

    Other artifact kinds (task/criteria text snapshots, other durable
    payloads) share the same content-addressed directory; anything that
    does not parse as an `ExecutionSnapshot`, or is not `closed`, or is not
    scoped to *execution_id*, is silently skipped -- never adopted. When
    more than one closed snapshot exists (e.g. an idempotent re-close with
    different bookkeeping), the highest `generation` wins.
    """
    artifacts_dir = root / "executions" / execution_id / "artifacts"
    if not artifacts_dir.is_dir():
        return None
    candidates: List[ExecutionSnapshot] = []
    for path in sorted(artifacts_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            snapshot = ExecutionSnapshot.model_validate(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValidationError):
            continue
        if snapshot.execution_id != execution_id or snapshot.status != "closed":
            continue
        candidates.append(snapshot)
    if not candidates:
        return None
    candidates.sort(key=lambda s: s.generation)
    return candidates[-1]


async def _find_settlement_snapshot(store: ExecutionEvidenceStore, execution_id: str) -> Optional[ExecutionSnapshot]:
    return await asyncio.to_thread(_find_settlement_snapshot_sync, store.root, execution_id)


def _scan_validation_registrations_sync(root: Path, execution_id: str) -> List[BackgroundRegistration]:
    """Enumerate every `kind == 'validation'` registration admitted for *execution_id*.

    Reads `BackgroundRegistry`'s own durable on-disk shape directly (there is
    no public listing API -- adding one is out of this task's file scope).
    Only the nested, PUBLIC `registration` payload is parsed; an unreadable
    or malformed record is never silently skipped -- it raises
    `CheckpointBusyError` (an unknown state is never zero activity, spec
    R8), instead of risking a false "no validations pending".
    """
    background_dir = root / "executions" / execution_id / "background"
    result: List[BackgroundRegistration] = []
    if not background_dir.is_dir():
        return result
    for path in sorted(background_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CheckpointBusyError(f"unreadable background registration at {path}: {exc}") from exc
        reg_raw = raw.get("registration") if isinstance(raw, dict) else None
        if not isinstance(reg_raw, dict):
            raise CheckpointBusyError(f"background registration at {path} is missing its 'registration' payload")
        try:
            registration = BackgroundRegistration.model_validate(reg_raw)
        except ValidationError as exc:
            raise CheckpointBusyError(
                f"background registration at {path} does not match the known schema: {exc}"
            ) from exc
        if registration.execution_id != execution_id:
            continue  # a foreign/stale record never trusted here
        if registration.kind != "validation":
            continue  # only admitted VALIDATIONS gate the checkpoint (spec R8)
        result.append(registration)
    return result


async def _assert_validations_settled(store: ExecutionEvidenceStore, execution_id: str) -> List[EvidenceRef]:
    """Confirm every admitted validation has settled; return their finished log refs.

    `pending`/`running`/`unknown` all raise `CheckpointBusyError` (spec R8:
    "pending/running/unknown de validaciones admitidas bloquean checkpoint").
    Ownership is intentionally checked with a FRESH `owner_instance_id`: this
    CLI is never the process that launched a validation, so a still-running
    validation correctly degrades to `unknown` here rather than a false
    `running` inferred from anything -- `BackgroundRegistry.status()` already
    encodes that rule.
    """
    registrations = await asyncio.to_thread(_scan_validation_registrations_sync, store.root, execution_id)
    if not registrations:
        return []
    registry = BackgroundRegistry(store=store, owner_instance_id=uuid.uuid4().hex)
    refs: List[EvidenceRef] = []
    unsettled: List[str] = []
    for registration in registrations:
        try:
            status = await registry.status(execution_id, registration.handle)
        except (BackgroundNotFoundError, BackgroundBudgetExceededError):
            unsettled.append(registration.handle)
            continue
        if status.state != "finished":
            unsettled.append(registration.handle)
            continue
        if status.log_ref is not None:
            refs.append(status.log_ref)
    if unsettled:
        raise CheckpointBusyError(
            f"{len(unsettled)} admitted validation(s) for execution {execution_id} have not settled: "
            f"{sorted(unsettled)}"
        )
    return refs


def _review_checkpoint_path(root: Path, execution_id: str, checkpoint_id: str) -> Path:
    """Resolve `executions/<execution_id>/review/<checkpoint_id>.json` (spec R3 layout)."""
    _validate_execution_id(execution_id)
    if not _CHECKPOINT_ID_RE.match(checkpoint_id or ""):
        raise ValueError(f"checkpoint_id must be a sha256 hex digest, got {checkpoint_id!r}")
    return root / "executions" / execution_id / "review" / f"{checkpoint_id}.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write *payload* as canonical JSON via temp-file-then-`os.replace` (mirrors `background.py`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp_path.unlink()
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, path)


async def _publish_review_checkpoint(store: ExecutionEvidenceStore, checkpoint: ReviewCheckpoint) -> None:
    path = _review_checkpoint_path(store.root, checkpoint.execution_id, checkpoint.checkpoint_id)
    await asyncio.to_thread(_atomic_write_json, path, checkpoint.model_dump(mode="json"))


async def load_review_checkpoint(
    execution_id: str, checkpoint_id: str, *, store: ExecutionEvidenceStore
) -> ReviewCheckpoint:
    """Load a previously published checkpoint by its emitted ID -- never an arbitrary path.

    Raises:
        CheckpointIncompleteError: no such checkpoint was ever published, or
            its durable content is corrupted.
    """
    path = _review_checkpoint_path(store.root, execution_id, checkpoint_id)
    try:
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except OSError as exc:
        raise CheckpointIncompleteError(
            f"no published checkpoint {checkpoint_id!r} for execution {execution_id!r}: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
        return ReviewCheckpoint.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise CheckpointIncompleteError(f"published checkpoint {checkpoint_id!r} is corrupted: {exc}") from exc


def _render_neutral_brief(
    *,
    feature: str,
    execution_id: str,
    branch: str,
    base_sha: str,
    implementation_head: str,
    commits: List[str],
    task_refs: List[EvidenceRef],
    criteria_refs: List[EvidenceRef],
    validation_refs: List[EvidenceRef],
    pending_actions: List[str],
) -> str:
    """Render a bounded, factual pointer to the durable manifest -- no verdict.

    Only counts, identities and refs; never the implementer's own conclusion
    (spec R5: "no pega todo el patch ni conclusiones del implementador").
    """
    lines = [
        f"feature: {feature}",
        f"execution_id: {execution_id}",
        f"branch: {branch}",
        f"base_sha: {base_sha}",
        f"implementation_head: {implementation_head}",
        f"commits: {len(commits)}",
        f"task_refs: {len(task_refs)}",
        f"criteria_refs: {len(criteria_refs)}",
        f"validation_refs: {len(validation_refs)}",
        f"pending_actions: {len(pending_actions)}",
    ]
    if pending_actions:
        lines.append("pending:")
        lines.extend(f"  - {item}" for item in pending_actions[:_MAX_BRIEF_ITEMS])
        if len(pending_actions) > _MAX_BRIEF_ITEMS:
            lines.append(f"  ... ({len(pending_actions) - _MAX_BRIEF_ITEMS} more, see task_refs)")
    brief = "\n".join(lines) + "\n"
    encoded = brief.encode("utf-8")
    if len(encoded) > _MAX_CHECKPOINT_BRIEF_BYTES:
        # Defensive only -- the model's own validator enforces this budget too.
        brief = encoded[:_MAX_CHECKPOINT_BRIEF_BYTES].decode("utf-8", errors="ignore")
    return brief


def _verify_evidence_ref(root: Path, ref: EvidenceRef) -> None:
    """Reject a ref that escapes *root*, is a symlink, or no longer matches its hash/size.

    Mirrors `scripts.sdd.finalize_task._verify_one_ref`'s confinement and
    hash-verification logic (duplicated locally: `finalize_task.py` is a
    script, not a library this module may depend on).
    """
    resolved_root = root.resolve()
    candidate = (root / ref.relative_path).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise CheckpointStaleError(f"checkpoint_stale: evidence ref escapes the durable root: {ref.relative_path!r}")
    if candidate.is_symlink() or not candidate.is_file():
        raise CheckpointStaleError(
            f"checkpoint_stale: evidence ref no longer resolves to a durable artifact: {ref.relative_path!r}"
        )
    data = candidate.read_bytes()
    if len(data) != ref.size_bytes or hashlib.sha256(data).hexdigest() != ref.sha256:
        raise CheckpointStaleError(
            f"checkpoint_stale: evidence ref content no longer matches its declared hash/size: {ref.relative_path!r}"
        )


async def prepare_review_checkpoint(
    *, feature: str, worktree: Path, execution_id: str, store: ExecutionEvidenceStore
) -> ReviewCheckpoint:
    """Validate settlement and persist immutable identity, constraints and evidence.

    Raises:
        ValueError: *execution_id* is not a canonical UUID.
        CheckpointBusyError: the execution is not durably closed, still
            lists outstanding attempts/reservations/jobs, or an admitted
            validation has not settled.
        CheckpointIncompleteError: the per-spec index/spec/conventions are
            unreadable, or the durable settlement is scoped to a different
            feature/worktree than requested.
    """
    _validate_execution_id(execution_id)
    worktree = Path(worktree)
    canonical_worktree = await asyncio.to_thread(lambda: str(worktree.resolve()))

    index_path, index_bytes, header = await asyncio.to_thread(_load_index_sync, worktree, feature)
    index_hash = hashlib.sha256(index_bytes).hexdigest()
    feature_id = str(header.get("feature_id") or "")
    base_branch = str(header.get("base_branch") or "")
    spec_rel = str(header.get("spec") or "")
    if not feature_id or not base_branch or not spec_rel:
        raise CheckpointIncompleteError(f"per-spec index header at {index_path} is missing feature_id/base_branch/spec")

    scheduler = await asyncio.to_thread(TaskScheduler.from_index_file, index_path)
    if scheduler is None:
        raise CheckpointIncompleteError(f"per-spec index at {index_path} is unreadable or malformed")

    snapshot = await _find_settlement_snapshot(store, execution_id)
    if snapshot is None:
        raise CheckpointBusyError(
            f"no durable closed settlement found for execution {execution_id}; "
            "coder_end_execution has not durably published one yet (or its own "
            "publish failed -- an unknown state is never treated as settled)"
        )
    if snapshot.feature_id != feature_id or snapshot.worktree_path != canonical_worktree:
        raise CheckpointIncompleteError(
            f"settlement for execution {execution_id} is scoped to feature={snapshot.feature_id!r} "
            f"worktree={snapshot.worktree_path!r}, not {feature_id!r}/{canonical_worktree!r}"
        )
    if snapshot.admitted_attempts or snapshot.native_reservations or snapshot.outstanding_job_ids:
        raise CheckpointBusyError(
            f"settlement for execution {execution_id} still lists outstanding work: "
            f"{len(snapshot.admitted_attempts)} attempt(s), {len(snapshot.native_reservations)} "
            f"reservation(s), {len(snapshot.outstanding_job_ids)} job(s)"
        )

    validation_refs = await _assert_validations_settled(store, execution_id)
    settlement_ref = await store.put_artifact(execution_id, snapshot)

    spec_bytes = await asyncio.to_thread(_confined_read_bytes, worktree, spec_rel)
    spec_hash = hashlib.sha256(spec_bytes).hexdigest()

    convention_hashes: Dict[str, str] = {}
    for rel_path in _CONVENTION_FILES:
        data = await asyncio.to_thread(_confined_read_bytes, worktree, rel_path)
        convention_hashes[rel_path] = hashlib.sha256(data).hexdigest()

    rc, branch_out, err = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    if rc != 0:
        raise CheckpointIncompleteError(f"could not resolve the current branch of {worktree}: {err.strip()}")
    branch = branch_out.strip()

    rc, head_out, err = await _git("rev-parse", "HEAD", cwd=worktree)
    if rc != 0:
        raise CheckpointIncompleteError(f"could not resolve HEAD of {worktree}: {err.strip()}")
    implementation_head = head_out.strip()

    rc, base_out, err = await _git("merge-base", "HEAD", f"origin/{base_branch}", cwd=worktree)
    if rc != 0:
        raise CheckpointIncompleteError(
            f"could not resolve merge-base against origin/{base_branch} in {worktree}: {err.strip()}"
        )
    base_sha = base_out.strip()
    if not _FULL_SHA_RE.match(base_sha) or not _FULL_SHA_RE.match(implementation_head):
        raise CheckpointIncompleteError(f"git did not return full SHAs for {worktree} (base={base_sha!r})")

    rc, commits_out, err = await _git("rev-list", "--reverse", f"{base_sha}..{implementation_head}", cwd=worktree)
    if rc != 0:
        raise CheckpointIncompleteError(f"could not list commits {base_sha}..{implementation_head}: {err.strip()}")
    commits = [line.strip() for line in commits_out.splitlines() if line.strip()]

    task_refs: List[EvidenceRef] = []
    criteria_refs: List[EvidenceRef] = []
    pending_actions: List[str] = []
    for task_ref in scheduler.all_tasks():
        if task_ref.status != "done":
            pending_actions.append(f"{task_ref.id}: {task_ref.title or task_ref.status} ({task_ref.status})")
        if not task_ref.file:
            continue
        task_md = await asyncio.to_thread(_confined_read_text, worktree, task_ref.file)
        task_refs.append(await _publish_text(store, execution_id, task_md))
        criteria_body = _extract_criteria_section(task_md)
        if criteria_body:
            criteria_refs.append(await _publish_text(store, execution_id, criteria_body))

    # No producer in this task's scope publishes fix/feedback/review evidence
    # into the durable store under a discoverable key yet (mirrors
    # `inspection.delivery_report`'s own honest "unknown" for the same gap)
    # -- evidence_refs stays anchored to the settlement itself rather than
    # fabricating a broader set.
    evidence_refs = [settlement_ref]

    neutral_brief = _render_neutral_brief(
        feature=feature,
        execution_id=execution_id,
        branch=branch,
        base_sha=base_sha,
        implementation_head=implementation_head,
        commits=commits,
        task_refs=task_refs,
        criteria_refs=criteria_refs,
        validation_refs=validation_refs,
        pending_actions=pending_actions,
    )

    fields: dict[str, object] = dict(
        feature=feature,
        execution_id=execution_id,
        worktree=canonical_worktree,
        branch=branch,
        base_sha=base_sha,
        implementation_head=implementation_head,
        spec_hash=spec_hash,
        index_hash=index_hash,
        convention_hashes=convention_hashes,
        task_refs=task_refs,
        criteria_refs=criteria_refs,
        commits=commits,
        validation_refs=validation_refs,
        evidence_refs=evidence_refs,
        # Neither is derivable from durable state alone: this function's own
        # contract takes no user-supplied constraints parameter. Left empty
        # rather than fabricated -- never claimed as "no constraints exist".
        user_constraints=[],
        context_id="main",
        pending_actions=pending_actions,
        settlement_ref=settlement_ref,
        neutral_brief=neutral_brief,
    )
    checkpoint_id = ReviewCheckpoint.compute_checkpoint_id(**fields)
    checkpoint = ReviewCheckpoint(checkpoint_id=checkpoint_id, **fields)

    await _publish_review_checkpoint(store, checkpoint)
    return checkpoint


async def validate_review_checkpoint(checkpoint: ReviewCheckpoint, *, worktree: Path) -> None:
    """Reject stale branch, SHA, criteria, conventions or unverifiable evidence.

    Re-derives HEAD/branch/spec/index/convention hashes from scratch and
    re-verifies every durable evidence ref this checkpoint carries -- never
    trusts the checkpoint's own claims. Never approves the underlying code:
    a clean return means "still an accurate handoff", nothing more.

    Raises:
        CheckpointStaleError: branch, HEAD, spec/index/convention hashes, or
            any evidence ref has drifted since `checkpoint` was prepared.
    """
    worktree = Path(worktree)
    canonical_worktree = await asyncio.to_thread(lambda: str(worktree.resolve()))
    if checkpoint.worktree != canonical_worktree:
        raise CheckpointStaleError(
            f"checkpoint_stale: checkpoint was prepared for worktree {checkpoint.worktree!r}, "
            f"not {canonical_worktree!r}"
        )

    rc, branch_out, err = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    if rc != 0:
        raise CheckpointStaleError(
            f"checkpoint_stale: could not resolve the current branch of {worktree}: {err.strip()}"
        )
    if branch_out.strip() != checkpoint.branch:
        raise CheckpointStaleError(
            f"checkpoint_stale: branch moved from {checkpoint.branch!r} to {branch_out.strip()!r}"
        )

    rc, head_out, err = await _git("rev-parse", "HEAD", cwd=worktree)
    if rc != 0:
        raise CheckpointStaleError(f"checkpoint_stale: could not resolve HEAD of {worktree}: {err.strip()}")
    if head_out.strip() != checkpoint.implementation_head:
        raise CheckpointStaleError(
            f"checkpoint_stale: HEAD moved from {checkpoint.implementation_head!r} to {head_out.strip()!r}"
        )

    index_path, index_bytes, header = await asyncio.to_thread(_load_index_sync, worktree, checkpoint.feature)
    if hashlib.sha256(index_bytes).hexdigest() != checkpoint.index_hash:
        raise CheckpointStaleError(f"checkpoint_stale: per-spec index at {index_path} changed since the checkpoint")

    spec_rel = str(header.get("spec") or "")
    if not spec_rel:
        raise CheckpointStaleError(f"checkpoint_stale: per-spec index at {index_path} no longer declares a spec path")
    try:
        spec_bytes = await asyncio.to_thread(_confined_read_bytes, worktree, spec_rel)
    except (OSError, ValueError) as exc:
        raise CheckpointStaleError(f"checkpoint_stale: spec at {spec_rel} is unreadable: {exc}") from exc
    if hashlib.sha256(spec_bytes).hexdigest() != checkpoint.spec_hash:
        raise CheckpointStaleError(f"checkpoint_stale: spec at {spec_rel} changed since the checkpoint")

    for rel_path, expected_hash in checkpoint.convention_hashes.items():
        try:
            data = await asyncio.to_thread(_confined_read_bytes, worktree, rel_path)
        except (OSError, ValueError) as exc:
            raise CheckpointStaleError(f"checkpoint_stale: convention file {rel_path} is unreadable: {exc}") from exc
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise CheckpointStaleError(f"checkpoint_stale: convention file {rel_path} changed since the checkpoint")

    configured_root = os.environ.get(_TELEMETRY_ROOT_ENV) or None
    durable_root = resolve_durable_root(configured_root, worktree_base_path=str(worktree))

    all_refs = [
        checkpoint.settlement_ref,
        *checkpoint.task_refs,
        *checkpoint.criteria_refs,
        *checkpoint.validation_refs,
        *checkpoint.evidence_refs,
        *checkpoint.user_constraint_refs,
    ]
    for ref in all_refs:
        await asyncio.to_thread(_verify_evidence_ref, durable_root, ref)
