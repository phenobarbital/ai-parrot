"""Dev Workflow Recovery Adapter — DevCheckpointCoordinator (spec §3 Module 3).

Implements the dev-workflow-specific glue between the generic checkpoint
engine (``bots/flows/core/checkpoint``, TASK-2622..2624) and the explicit-edge
graphs built by ``dev_loop``/``dev_flow``:

* A stable, namespaced checkpoint identity — ``"<workflow>/<run_id>"`` —
  inside the existing ``flowckpt:{flow_id}:*`` Redis key family (the slash
  never collides with the store's colon-delimited key parsing).
* A deterministic SHA-256 input fingerprint over the normalized brief,
  repository identity, and routing-relevant execution policy, carried as
  ``CheckpointInputMetadata`` (TASK-2623) and checked on every resume
  attempt (spec §2 step 2).
* Fresh-vs-resume selection: a checkpoint miss builds a new checkpoint-
  enabled flow via the caller's factory; a hit resumes it through
  ``AgentsFlow.resume(flow_factory=..., seed_context=..., expected_input=...)``
  (TASK-2622/2623), never ``from_definition()``.
* Shared-state projection: the allowlisted checkpoint_shared_data
  projector used on the WRITE side (``project_shared_data``, passed as
  ``AgentsFlow(checkpoint_shared_data=...)``), and the matching decode-and-
  restore step used on the READ side after a successful resume
  (``_restore_shared_data``) — never the full live ``shared_data`` mapping,
  which may hold a ``SessionHost``, dispatchers, or toolkits.
* Recovered-artifact validation: a restored ``research_output``/
  ``planner_output`` worktree must still be registered on the expected
  branch, and the spec/task-index files it references must exist.
* Structured recovery events/logs (spec §5): ``cache_miss``,
  ``checkpoint_committed``, ``resume_started``, ``node_restored``,
  ``node_rerun``, ``artifact_validation_failure``, ``fingerprint_mismatch``,
  ``lease_conflict``, ``checkpoint_persistence_failure``.

Wiring this coordinator into ``dev_loop``/``dev_flow``'s actual flow
construction and runner (per-run flow factories, registering the dev-loop
result types with ``register_checkpoint_type()``) is TASK-2626/2627 — this
module is deliberately self-contained and does not import or modify
``dev_loop/flow.py`` or ``dev_loop/runner.py``.

``flow_factory`` contract (spec §2 New Public Interfaces uses the loose
``Callable[..., AgentsFlow]``; this module pins it down): a callable
``(definition: FlowDefinition | None) -> AgentsFlow`` that always builds
the SAME programmatic explicit-edge graph — via ``add_node``/``add_edge``,
never ``from_definition()`` — with ``checkpoint=True``,
``checkpoint_required=True``, and a ``checkpoint_store``/
``checkpoint_shared_data`` already bound by the caller (TASK-2626/2627).
This exactly matches ``AgentsFlow.resume()``'s own calling convention
(``flow_factory(checkpoint.definition)``), so the SAME closure passed to
``DevCheckpointCoordinator.prepare()`` is also handed straight through to
``resume()`` unmodified. The factory cannot know this run's stable
``flow_id`` or its computed ``CheckpointInputMetadata`` in advance (the
coordinator computes the fingerprint); ``prepare()`` therefore binds both
onto the freshly-built flow directly (``flow.flow_id``,
``flow._checkpoint_input_arg``) before returning it — both are read
lazily by ``AgentsFlow._ensure_checkpointer()``, only when the first
checkpoint is about to be built, so setting them post-construction (before
any ``run_flow()`` call) is safe and has no other side effect.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from parrot.bots.flows import AgentsFlow, FlowContext
from parrot.bots.flows.core.checkpoint import (
    CheckpointFingerprintMismatchError,
    CheckpointInputMetadata,
    CheckpointPersistenceError,
    CheckpointStore,
    FlowCheckpoint,
    FlowLockedError,
    FlowStateSerializer,
    get_checkpoint_store,
)
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    PlannerOutput,
    ResearchOutput,
)

if TYPE_CHECKING:
    from parrot.bots.flows.flow.definition import FlowDefinition

logger = logging.getLogger("parrot.flows.dev_loop.checkpoint")

#: Topology version tag embedded in every fingerprint (spec §2). Bump this
#: whenever a dev-loop/dev-flow graph's node/edge shape changes in a way
#: that would make an old checkpoint's completed-node ids meaningless —
#: reusing a run_id against the old topology should be a cache miss, not
#: a silently-wrong resume.
TOPOLOGY_VERSION = "1"

#: shared_data keys the dev workflows read/write, and the ONLY keys ever
#: persisted by the checkpoint_shared_data projector or restored on resume
#: (spec §3 Module 3 scope bullet). Anything else in live shared_data (a
#: SessionHost, dispatchers, toolkits, trace context) never reaches the
#: store and is never restored from it. Shared by BOTH workflows this
#: coordinator serves (spec §3 Module 5: "reuse DevCheckpointCoordinator
#: with workflow='dev-flow'; do not fork it") — dev-loop only ever
#: populates the first five keys, dev-flow only the last three
#: (``dev_brief``/``feature_brief``/``ideation_output``), plus the shared
#: ``planner_output``/``research_output`` (the derived bridge PlannerNode
#: projects, spec §3 Module 5) and ``development_output`` bridge.
_SHARED_DATA_ALLOWLIST: tuple[str, ...] = (
    "bug_brief",
    "bug_findings",
    "research_output",
    "planner_output",
    "development_output",
    "dev_brief",
    "feature_brief",
    "ideation_output",
)

#: Registered result types whose values, when found in a resumed node's
#: results, get projected onto their corresponding shared_data key.
#: ``IdeationOutput`` is added lazily by ``_result_key_by_type()`` below
#: (NOT a module-level import: `parrot.flows.dev_flow.models` imports
#: `dev_loop.models`, which triggers EAGER execution of `dev_loop/
#: __init__.py` -> ... -> this module — a module-level import here would
#: be a genuine import cycle, not just a style preference).
_RESULT_KEY_BY_TYPE: dict[type, str] = {
    ResearchOutput: "research_output",
    PlannerOutput: "planner_output",
    DevelopmentOutput: "development_output",
}


def _result_key_by_type() -> dict[type, str]:
    """``_RESULT_KEY_BY_TYPE`` plus the dev-flow-only entry, resolved lazily."""
    from parrot.flows.dev_flow.models import (
        IdeationOutput,
    )

    return {**_RESULT_KEY_BY_TYPE, IdeationOutput: "ideation_output"}


class RecoveredArtifactError(RuntimeError):
    """A recovered checkpoint's referenced artifacts are invalid.

    Raised when a restored ``research_output``/``planner_output``'s
    worktree is missing, unregistered, or on the wrong branch, or when a
    referenced spec/task-index file no longer exists on disk. Recovery
    must fail explicitly rather than dispatch development/QA against
    invalid state (spec §2 step 5).
    """


def compute_input_fingerprint(
    *,
    workflow: Literal["dev-loop", "dev-flow"],
    brief: BaseModel,
    repository: str,
    execution_policy: dict[str, Any],
    document_identity: str = "",
) -> str:
    """SHA-256 digest over deterministic JSON (spec §2).

    Includes: workflow kind, topology version, the normalized brief
    (``model_dump(mode="json")``), repository identity, routing-relevant
    execution policy, and the referenced SDD document identity (feature/
    document runs). Excludes timestamps, hostnames, trace ids, Redis
    clients, dispatcher instances — anything volatile or live.

    Args:
        workflow: ``"dev-loop"`` or ``"dev-flow"``.
        brief: The run's input brief (``WorkBrief``/``FeatureBrief``/...).
        repository: Repository identity/base path this run operates on.
        execution_policy: Routing-relevant policy (QA/approval/pool
            settings, ...). Caller-defined shape; only its own keys/values
            participate in the digest, so an unrelated key never changes
            it — but adding a NEW routing-relevant key without updating
            existing callers is a behavior change for them (a previously
            stable fingerprint would now differ), so callers should keep
            this dict's shape stable across a deployment.
        document_identity: Optional referenced SDD document identity
            (spec/proposal path) for feature/document-driven runs. ``""``
            (default) for bug-triage runs, which reference no such
            document until ``ResearchNode`` creates one.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    payload = {
        "workflow": workflow,
        "topology_version": TOPOLOGY_VERSION,
        "brief": brief.model_dump(mode="json"),
        "repository": repository,
        "execution_policy": execution_policy,
        "document_identity": document_identity,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_shared_data(ctx: FlowContext) -> dict[str, Any]:
    """``checkpoint_shared_data`` projector (write side, spec §3 Module 3).

    Returns only the allowlisted keys present in ``ctx.shared_data`` — the
    dev workflows' typed results/briefs — never the full live mapping.
    Passed as ``AgentsFlow(checkpoint_shared_data=project_shared_data)``
    by the flow factory (TASK-2626/2627).

    Args:
        ctx: The live ``FlowContext`` being checkpointed.

    Returns:
        The allowlisted subset of ``ctx.shared_data``.
    """
    return {key: ctx.shared_data[key] for key in _SHARED_DATA_ALLOWLIST if key in ctx.shared_data}


def _find_worktree_entry(porcelain: str, abs_path: str) -> dict[str, str] | None:
    """Parse ``git worktree list --porcelain`` output for one path.

    Adapted from ``ResearchNode._find_worktree_entry`` (same algorithm,
    reused here as a standalone function since the coordinator has no
    ``ResearchNode`` instance to call it on).

    Args:
        porcelain: Raw ``git worktree list --porcelain`` stdout.
        abs_path: Absolute path to look up.

    Returns:
        The entry's fields (notably ``branch``, without the
        ``refs/heads/`` prefix), or ``None`` if not registered.
    """
    current: dict[str, str] = {}
    for line in porcelain.splitlines():
        if not line:
            if current.get("worktree") == abs_path:
                return current
            current = {}
            continue
        if " " in line:
            key, _, value = line.partition(" ")
        else:
            key, value = line, ""
        if key == "branch" and value.startswith("refs/heads/"):
            value = value[len("refs/heads/") :]
        current[key] = value
    if current.get("worktree") == abs_path:
        return current
    return None


async def _verify_recovered_worktree(worktree_path: str, expected_branch: str) -> None:
    """Verify a recovered worktree is registered, exists, and on the expected branch.

    Adapted from ``ResearchNode._ensure_worktree_safe`` — but recovery
    semantics differ from fresh-research semantics: a MISSING worktree is
    not "the subagent will create it", it is a hard failure (the
    development/QA state this run is resuming into assumes the worktree
    already exists).

    Args:
        worktree_path: Absolute on-disk worktree path to verify.
        expected_branch: The branch this run's checkpoint recorded.

    Raises:
        RecoveredArtifactError: If the path is missing, ``git worktree
            list`` fails, the path is not a registered worktree, or it is
            registered on a different branch.
    """
    if not worktree_path or not os.path.exists(worktree_path):
        raise RecoveredArtifactError(
            f"Recovered worktree path {worktree_path!r} does not exist; "
            "cannot resume development/QA against it."
        )

    try:
        # cwd=worktree_path (not the caller's process cwd, which has no
        # guaranteed relationship to this repository) — `git worktree
        # list` run from inside any linked worktree sees the whole
        # worktree family regardless of which one you're in.
        proc = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "list",
            "--porcelain",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git exited with code {proc.returncode}")
        stdout = stdout_bytes.decode()
    except Exception as exc:
        raise RecoveredArtifactError(
            f"Recovered worktree {worktree_path!r}: `git worktree list` failed: {exc}"
        ) from exc

    info = _find_worktree_entry(stdout, os.path.abspath(worktree_path))
    if info is None:
        raise RecoveredArtifactError(
            f"Recovered worktree path {worktree_path!r} exists but is not a "
            "registered git worktree."
        )
    actual_branch = info.get("branch")
    if actual_branch != expected_branch:
        raise RecoveredArtifactError(
            f"Recovered worktree {worktree_path!r} is on branch "
            f"{actual_branch!r}, expected {expected_branch!r}."
        )


def _verify_recovered_file(path: str, description: str) -> None:
    """Verify a recovered artifact file exists on disk.

    Args:
        path: Absolute (or already-resolved) path to check.
        description: Human-readable label used in the error message.

    Raises:
        RecoveredArtifactError: If ``path`` is empty or not a file.
    """
    if not path or not os.path.isfile(path):
        raise RecoveredArtifactError(f"Recovered {description} {path!r} does not exist.")


class DevCheckpointCoordinator:
    """Dev workflow recovery adapter (spec §3 Module 3).

    One instance is shared across runs of the same workflow; it carries no
    per-run mutable state beyond the resolved checkpoint stores. See the
    module docstring for the ``flow_factory`` contract and the shared-data
    projection/restoration split.

    Args:
        store: Ephemeral ``CheckpointStore`` name/instance/None (env
            fallback) — resolved via ``get_checkpoint_store()``.
        durable_store: Durable ``CheckpointStore`` name/instance/None.
            Checked first when given, mirroring ``AgentsFlow.resume()``.
    """

    def __init__(
        self,
        *,
        store: Any | None = None,
        durable_store: Any | None = None,
    ) -> None:
        self._store_arg = store
        self._durable_store_arg = durable_store
        self.logger = logger

    # ── Structured recovery events (spec §5) ────────────────────────────

    def emit_recovery_event(self, event: str, **payload: Any) -> None:
        """Log one structured recovery event.

        Public so callers outside ``prepare()``'s own control flow
        (TASK-2626/2627's per-run flow wiring, e.g. from an
        ``on_node_event`` hook) can emit the events ``prepare()`` itself
        has no visibility into — ``checkpoint_committed`` (a mid-run
        required-barrier success) and ``node_rerun`` (the scheduler
        re-executing an incomplete frontier node) — through the same
        structured shape as the ones ``prepare()`` emits directly
        (``cache_miss``, ``resume_started``, ``node_restored``,
        ``fingerprint_mismatch``, ``lease_conflict``,
        ``artifact_validation_failure``, ``checkpoint_persistence_failure``).

        Args:
            event: One of the spec §5 recovery event kinds.
            **payload: Event-specific structured fields (``flow_id``,
                ``workflow``, ``run_id``, ...).
        """
        self.logger.info("dev_loop.checkpoint.%s", event, extra={"event": event, **payload})

    # ── Shared-state projection (read side) ─────────────────────────────

    @staticmethod
    def _restore_shared_data(checkpoint: FlowCheckpoint, live_context: FlowContext) -> None:
        """Decode the checkpoint's allowlisted shared_data into ``live_context``.

        ``AgentsFlow.resume(seed_context=...)`` deliberately never touches
        ``shared_data`` (TASK-2622: the caller's live objects must never be
        overwritten by checkpoint data) — restoring the dev workflows'
        typed briefs/outputs back into shared_data is this coordinator's
        job, not the generic engine's.

        Args:
            checkpoint: The loaded ``FlowCheckpoint`` (its
                ``context.shared_data`` was written by
                ``project_shared_data`` through the same
                ``FlowStateSerializer`` type registry as node results).
            live_context: The caller's fresh, live context to restore into
                — only allowlisted keys ABSENT from it already are set, so
                a live value the caller pre-seeded is never clobbered.
        """
        serializer = FlowStateSerializer()
        raw = checkpoint.context.shared_data or {}
        for key in _SHARED_DATA_ALLOWLIST:
            if key not in raw or key in live_context.shared_data:
                continue
            live_context.shared_data[key] = serializer.from_safe(raw[key])

    @staticmethod
    def _project_results(live_context: FlowContext) -> None:
        """Project resumed typed node RESULTS onto their shared_data key.

        Complements ``_restore_shared_data``: ``bug_findings``/
        ``bug_brief`` never appear as any node's *result* (only in
        shared_data, handled above), but ``research_output``/
        ``planner_output``/``development_output`` are BOTH a node's typed
        result (restored into ``live_context.results`` by
        ``AgentsFlow.resume()``'s ``mark_completed()`` seeding) AND a
        shared_data key downstream nodes read directly. A value already
        present (e.g. restored by ``_restore_shared_data``) is never
        overwritten.

        Args:
            live_context: The context ``AgentsFlow.resume()`` just seeded
                with typed per-node results.
        """
        for result in live_context.results.values():
            for model_cls, key in _result_key_by_type().items():
                if isinstance(result, model_cls) and key not in live_context.shared_data:
                    live_context.shared_data[key] = result

    def _validate_recovered_artifacts(self, live_context: FlowContext) -> Callable[[], asyncio.Future[None]] | None:
        """Build the artifact-validation coroutine for a resumed run's shared_data.

        Validates ``research_output``/``planner_output`` when present:
        the worktree they reference must be a registered git worktree on
        the expected branch, and their referenced spec/task-index files
        must exist. A run that never got that far (fresh, or resumed
        before research/planning completed) has neither key — nothing to
        validate, a no-op.

        Args:
            live_context: The context to read ``research_output``/
                ``planner_output`` from (already restored).

        Returns:
            A zero-arg coroutine function performing the validation, or
            ``None`` if there is nothing to validate.
        """
        research_candidate = live_context.shared_data.get("research_output")
        research_output = research_candidate if isinstance(research_candidate, ResearchOutput) else None
        planner_candidate = live_context.shared_data.get("planner_output")
        planner_output = planner_candidate if isinstance(planner_candidate, PlannerOutput) else None
        if research_output is None and planner_output is None:
            return None

        async def _validate() -> None:
            for output in (research_output, planner_output):
                if output is None:
                    continue
                await _verify_recovered_worktree(output.worktree_path, output.branch_name)
                spec_path = getattr(output, "spec_path", "")
                if spec_path:
                    resolved = spec_path if os.path.isabs(spec_path) else os.path.join(output.worktree_path, spec_path)
                    _verify_recovered_file(resolved, "spec")
            if planner_output is not None and getattr(planner_output, "task_index_path", ""):
                task_index_path = planner_output.task_index_path
                resolved = (
                    task_index_path
                    if os.path.isabs(task_index_path)
                    else os.path.join(planner_output.worktree_path, task_index_path)
                )
                _verify_recovered_file(resolved, "task index")

        return _validate

    # ── Fresh vs. resume selection (spec §2 steps 1-4) ──────────────────

    async def prepare(
        self,
        *,
        workflow: Literal["dev-loop", "dev-flow"],
        run_id: str,
        brief: BaseModel,
        live_context: FlowContext,
        flow_factory: Callable[[FlowDefinition | None], AgentsFlow],
        execution_policy: dict[str, Any],
    ) -> tuple[AgentsFlow, Literal["fresh", "resumed"]]:
        """Select fresh vs. resumed execution for one dev-workflow run.

        See the module docstring for the ``flow_factory`` contract.

        Args:
            workflow: ``"dev-loop"`` or ``"dev-flow"``.
            run_id: The caller's stable run identity. A generated new id
                is intentionally always a cache miss (spec §8 OQ1).
            brief: The run's input brief, fingerprinted alongside
                ``execution_policy``.
            live_context: The caller's fresh, live ``FlowContext`` (already
                bound to a fresh ``SessionHost``, dispatchers, trace
                context for THIS process) — seeded in place on resume,
                never replaced.
            flow_factory: ``(definition) -> AgentsFlow``. See module
                docstring.
            execution_policy: Routing-relevant policy dict fingerprinted
                alongside the brief. May include ``"repository"`` and
                ``"document_identity"`` string keys, read here for the
                fingerprint (both default to ``""`` when absent).

        Returns:
            ``(flow, "fresh")`` on a cache miss, or ``(flow, "resumed")``
            after a successful resume with ``live_context`` seeded and
            validated.

        Raises:
            CheckpointFingerprintMismatchError: If a checkpoint exists for
                ``run_id`` but its recorded input no longer matches.
            FlowLockedError: If another process already holds the resume
                lease for this flow identity.
            RecoveredArtifactError: If a resumed run's worktree/spec/task
                artifacts are missing, unregistered, on the wrong branch,
                or otherwise invalid.
            CheckpointPersistenceError: If the initial checkpoint lookup
                itself fails (e.g. Redis unavailable).
        """
        flow_id = f"{workflow}/{run_id}"
        ephemeral = get_checkpoint_store(self._store_arg)
        durable: CheckpointStore | None = (
            get_checkpoint_store(self._durable_store_arg) if self._durable_store_arg is not None else None
        )

        repository = str(execution_policy.get("repository", ""))
        document_identity = str(execution_policy.get("document_identity", ""))
        fingerprint = compute_input_fingerprint(
            workflow=workflow,
            brief=brief,
            repository=repository,
            execution_policy=execution_policy,
            document_identity=document_identity,
        )
        input_metadata = CheckpointInputMetadata(
            workflow=workflow,
            topology_version=TOPOLOGY_VERSION,
            input_fingerprint=fingerprint,
        )

        try:
            existing: FlowCheckpoint | None = None
            if durable is not None:
                existing = await durable.latest(flow_id)
            if existing is None:
                existing = await ephemeral.latest(flow_id)
        except Exception as exc:
            self.emit_recovery_event(
                "checkpoint_persistence_failure", flow_id=flow_id, workflow=workflow, run_id=run_id
            )
            raise CheckpointPersistenceError(
                f"DevCheckpointCoordinator.prepare(): checkpoint lookup failed "
                f"for flow_id={flow_id!r}: {exc}"
            ) from exc

        if existing is None:
            self.emit_recovery_event("cache_miss", flow_id=flow_id, workflow=workflow, run_id=run_id)
            flow = flow_factory(None)
            flow.flow_id = flow_id
            flow._checkpoint_input_arg = input_metadata
            return flow, "fresh"

        self.emit_recovery_event("resume_started", flow_id=flow_id, workflow=workflow, run_id=run_id)
        try:
            resumed = await AgentsFlow.resume(
                flow_id,
                agent_registry=None,  # type: ignore[arg-type]
                # dev-loop/dev-flow graphs carry no agent-typed nodes and a
                # non-None seed_context is always supplied below, so
                # resume()'s agent_registry parameter is never actually
                # read on this call path (only its from_definition()
                # fallback — never reached when flow_factory is given —
                # and its internal-context-construction branch — never
                # reached when seed_context is given — use it).
                store=self._store_arg,
                durable_store=self._durable_store_arg,
                flow_factory=flow_factory,
                seed_context=live_context,
                expected_input=input_metadata,
            )
        except CheckpointFingerprintMismatchError:
            self.emit_recovery_event("fingerprint_mismatch", flow_id=flow_id, workflow=workflow, run_id=run_id)
            raise
        except FlowLockedError:
            self.emit_recovery_event("lease_conflict", flow_id=flow_id, workflow=workflow, run_id=run_id)
            raise

        self._restore_shared_data(existing, live_context)
        self._project_results(live_context)

        validate = self._validate_recovered_artifacts(live_context)
        if validate is not None:
            try:
                await validate()
            except RecoveredArtifactError:
                self.emit_recovery_event(
                    "artifact_validation_failure", flow_id=flow_id, workflow=workflow, run_id=run_id
                )
                raise

        self.emit_recovery_event(
            "node_restored",
            flow_id=flow_id,
            workflow=workflow,
            run_id=run_id,
            completed_nodes=sorted(live_context.completed_tasks),
        )
        return resumed, "resumed"
