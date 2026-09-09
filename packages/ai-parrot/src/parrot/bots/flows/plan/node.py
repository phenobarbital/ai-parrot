"""``PlanToolNode`` — the executor for a plan node inside ``AgentsFlow``.

This is where the architecture's central invariant is actually enforced: a
tool payload goes **to working memory**, and what enters ``FlowContext`` — and
therefore anything a model can ever see — is an :class:`~.models.ArtifactRef`.

Differences from the stock ``parrot.bots.flows.crew.tool_node.ToolNode``, all
deliberate:

``execute_tool`` instead of ``tool.execute``
    ``ToolNode._invoke`` calls the tool object directly, bypassing
    ``ToolManager.execute_tool`` and with it ``_postprocess_result``, the
    result hooks, and permission/credential propagation. A plan node goes
    through the manager.

``ArtifactRef`` instead of ``extract_tool_output``
    ``extract_tool_output`` JSON-encodes the payload into ``ctx.results``.
    For a 40 MB scanner report that is precisely the failure this design
    exists to prevent.

fan-out and guards
    ``for_each`` expands *inside* this node, so the DAG stays static and
    exportable; ``when`` is evaluated here against accumulated facets.

The node is constructed by a ``node_factories["tool"]`` closure (see
:func:`make_tool_node_factory`) so the live ``ToolManager`` and
``WorkingMemoryToolkit`` reach it without being serialised into
``NodeDefinition.config``.

Task-memory correlation (FEAT-538)
----------------------------------

When task memory is enabled the node carries the plan's
run/node/item/attempt identifiers into each dispatch and keeps its attempt
receipt alive across the post-dispatch boundary. That boundary is the whole
problem: :meth:`PlanToolNode._store` runs *after* :meth:`_call_with_retry`
has returned, by which time the dispatcher has reset its per-invocation
context, so an artifact stored there would otherwise have no producer at
all. :meth:`TurnTaskSession.retained_producer` pins the producing attempt
for exactly that window.

Three deliberate refusals to guess:

* A plan node id is **not** a domain step id. Without an explicit
  ``step_mapping`` entry the call keeps ``plan`` provenance and stays
  task-level, and nothing creates a task or a step on a plan's behalf.
* The node's own receipt is the *aggregate* over whatever the manager
  dispatched underneath it. It is distinguishable from those physical
  attempts (they name it as parent) and is never counted as a second
  execution of each of them.
* An attempt whose outcome could not be established is **not** retried.
  An unknown external effect may already have happened; running it again
  because we cannot tell is how a plan performs a side effect twice.
  Ordinary configured transient retries are untouched.

Every one of these is inert when task memory is absent: with no turn
session there is no receipt, no version, and the legacy alias-only
behaviour is preserved exactly (AC13).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Set

from pydantic import Field, PrivateAttr

from .facets import estimate_bytes, extract_facets, merge_facets
from .guards import PlanGuard, compile_guard
from .models import ARTIFACT_REF_RE, NODE_REF_RE, ArtifactRef, PlanNode, _iter_strings
from .paths import render_key, select

__all__ = (
    "MAX_RECORDED_ERRORS",
    "PlanToolNode",
    "ToolExecutionError",
    "UnknownToolOutcomeError",
    "make_tool_node_factory",
)

# Per-node cap on error strings kept in the manifest. Unbounded error lists
# are the classic way a "small" manifest stops being small.
MAX_RECORDED_ERRORS = 20
_MAX_ERROR_CHARS = 300

from parrot.bots.flows.core.node import Node as _BaseNode


class ToolExecutionError(RuntimeError):
    """A plan node's tool call failed after exhausting its retries."""


class UnknownToolOutcomeError(ToolExecutionError):
    """A dispatch whose terminal outcome could not be established.

    The typed non-retryable outcome the specification requires (§ Failure
    Modes). It is raised *instead of* a retry, never after one: the tool's
    external effect may already have happened, and repeating it because
    the runtime could not read its own record is precisely the duplicate
    side effect the plan retry policy must not cause.

    Subclasses :class:`ToolExecutionError` so existing per-item error
    handling (``for_each.on_item_error``) keeps working unchanged.
    """


class PlanToolNode(_BaseNode):
    """Execute one :class:`~.models.PlanNode`, storing payloads out of context.

    Frozen Pydantic, like every ``Node``: mutable per-run state lives in
    private attributes. The FSM lifecycle is driven by the scheduler — this
    class must not touch it.

    Attributes:
        plan_node: The node specification being executed.
        tool_manager: Live manager used to dispatch the tool.
        working_memory: Toolkit whose catalog receives the payloads.
        dependencies: Node ids that must complete first.
        successors: Node ids dispatched afterwards.
        permission_context: Optional context forwarded to ``execute_tool``.
        plan_run_id: Identity of the plan run this node belongs to,
            recorded on every attempt receipt. ``None`` when the executor
            did not supply one.
        step_mapping: Explicit ``{plan_node_id: domain_step_id}`` mapping.
            Supplying an entry is the ONLY way a plan call is attributed
            to a specific task step; an unmapped node stays task-level
            with ``plan`` provenance rather than borrowing its own id as a
            step id.
    """

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    plan_node: PlanNode
    tool_manager: Any
    working_memory: Any
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    permission_context: Optional[Any] = None
    plan_run_id: Optional[str] = None
    step_mapping: Dict[str, str] = Field(default_factory=dict)
    is_configured: bool = True
    fsm: Optional[Any] = None

    _guard: Optional[PlanGuard] = PrivateAttr(default=None)
    _refs_cache: Dict[str, ArtifactRef] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Compile the guard and create the FSM if the base class did not."""
        super().model_post_init(__context)
        if self.fsm is None:
            from parrot.bots.flows.core.fsm import (  # noqa: PLC0415
                AgentTaskMachine,
            )

            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))
        # Compiling here rather than at first use keeps a broken guard from
        # surfacing mid-flight; validate_plan() already compiled it once, so
        # this is belt-and-braces for programmatically built plans.
        object.__setattr__(self, "_guard", compile_guard(self.plan_node.when))

    # ── Node contract ─────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Node identity."""
        return self.node_id

    @property
    def agent(self) -> "PlanToolNode":
        """Self-reference for flow plumbing that reads ``node.agent``."""
        return self

    async def configure(self) -> None:
        """No-op — a tool node needs no LLM configuration."""

    # ── Execution ─────────────────────────────────────────────────────────

    async def execute(self, ctx: Any, deps: Any = None, **kwargs: Any) -> ArtifactRef:
        """Run this node and return its :class:`~.models.ArtifactRef`.

        The return value becomes ``ctx.results[node_id]``, so it must stay
        small: no payload, no unbounded error list.

        Args:
            ctx: The live ``FlowContext``.
            deps: Dependency results (unused; state is read from ``ctx``).
            **kwargs: Forwarded to pre/post actions.

        Returns:
            An :class:`~.models.ArtifactRef` describing what was stored.
        """
        started = time.monotonic()
        prior = _artifact_refs(ctx)
        # {artifacts.<id>} resolution needs the published keys; cache them
        # before any argument is resolved.
        self._remember(prior)

        if not self._guard_allows(prior):
            ref = ArtifactRef(
                node_id=self.node_id,
                status="skipped",
                facets={},
            )
            self.logger.info(
                "Node %r skipped: guard %r evaluated false",
                self.node_id,
                self.plan_node.when,
            )
            await self.run_post_actions(result=ref, **kwargs)
            return ref

        await self.run_pre_actions(prompt=self.plan_node.tool, **kwargs)
        try:
            if self.plan_node.for_each is None:
                ref = await self._run_single(prior)
            else:
                ref = await self._run_fan_out(prior)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            self.logger.error("Node %r failed: %s", self.node_id, exc)
            raise
        finally:
            self.logger.debug("Node %r finished in %.3fs", self.node_id, time.monotonic() - started)

        await self.run_post_actions(result=ref, **kwargs)
        return ref

    # ── Single call ───────────────────────────────────────────────────────

    async def _run_single(self, prior: Mapping[str, ArtifactRef]) -> ArtifactRef:
        """Execute the node's tool once."""
        bodies = await self._artifact_bodies(self.plan_node.args)
        args = self._resolve_args(self.plan_node.args, prior, bodies)
        attempt = await self._call_with_retry(args)
        key = self.plan_node.store_as
        stored = await self._store(key, attempt.payload, index=None, producer_call_id=attempt.producer_call_id)
        return ArtifactRef(
            node_id=self.node_id,
            keys=[key],
            entry_type=_entry_type(attempt.payload),
            facets=extract_facets(attempt.payload, self.plan_node.facets),
            status="ok",
            bytes_stored=stored.byte_size,
            versions=[stored.version] if stored.version else [],
            tracking_degraded=attempt.degraded or stored.degraded,
        )

    # ── Fan-out ───────────────────────────────────────────────────────────

    async def _run_fan_out(self, prior: Mapping[str, ArtifactRef]) -> ArtifactRef:
        """Execute the node's tool once per item of ``for_each.source``.

        Expansion happens inside this single DAG node so the graph stays
        static. Concurrency is bounded by ``for_each.max_concurrency``;
        per-item failures are handled per ``for_each.on_item_error``.

        Returns:
            One :class:`~.models.ArtifactRef` covering every item.

        Raises:
            ToolExecutionError: If expansion exceeds ``max_items``, or an item
                fails under ``on_item_error="fail"``.
        """
        spec = self.plan_node.for_each
        assert spec is not None  # guaranteed by the caller

        source_body = await self._read_artifact(spec.source_node)
        items = select(source_body, spec.select, default=[])
        if not isinstance(items, (list, tuple)):
            items = [items]

        if len(items) > spec.max_items:
            # Never truncate silently: a plan that quietly processed 1.000 of
            # 5.000 reports would read as a complete run.
            raise ToolExecutionError(
                f"Node {self.node_id!r}: for_each expanded to {len(items)} items, "
                f"above max_items={spec.max_items}. Raise the cap or narrow "
                "'select'."
            )

        semaphore = asyncio.Semaphore(spec.max_concurrency)
        keys: List[Optional[str]] = [None] * len(items)
        facets: List[Optional[Dict[str, Any]]] = [None] * len(items)
        sizes: List[int] = [0] * len(items)
        versions: List[Optional[str]] = [None] * len(items)
        degraded: List[bool] = [False] * len(items)
        errors: List[str] = []
        entry_types: List[str] = []
        # Read once, before fan-out: every item resolves the same
        # {artifacts.<id>} bodies, and re-reading them per item would
        # multiply an enabled catalog's awaited reads by the item count.
        bodies = await self._artifact_bodies(self.plan_node.args)

        async def run_item(index: int, item: Any) -> None:
            async with semaphore:
                key = render_key(self.plan_node.store_as, item=item, index=index)
                if spec.skip_existing and await self._has_key(key):
                    # Idempotent re-run: this is what gives per-item resume
                    # without any scheduler involvement.
                    keys[index] = key
                    self.logger.debug("Node %r: key %r exists, skipping", self.node_id, key)
                    return
                args = self._resolve_args(self.plan_node.args, prior, bodies, item=item, index=index)
                attempt = await self._call_with_retry(args, index=index)
                written = await self._store(
                    key,
                    attempt.payload,
                    index=index,
                    producer_call_id=attempt.producer_call_id,
                )
                sizes[index] = written.byte_size
                versions[index] = written.version
                degraded[index] = attempt.degraded or written.degraded
                keys[index] = key
                facets[index] = extract_facets(attempt.payload, self.plan_node.facets)
                entry_types.append(_entry_type(attempt.payload))

        async def guarded(index: int, item: Any) -> None:
            try:
                await run_item(index, item)
            except Exception as exc:  # noqa: BLE001
                if spec.on_item_error == "fail":
                    raise
                if spec.on_item_error == "collect" and len(errors) < MAX_RECORDED_ERRORS:
                    errors.append(f"[{index}] {str(exc)[:_MAX_ERROR_CHARS]}")

        await asyncio.gather(*(guarded(i, item) for i, item in enumerate(items)))

        stored = [key for key in keys if key is not None]
        collected = [entry for entry in facets if entry is not None]
        status = "ok" if not errors else "partial"
        if items and not stored:
            status = "error"

        return ArtifactRef(
            node_id=self.node_id,
            keys=stored,
            entry_type=entry_types[0] if entry_types else None,
            facets=merge_facets(collected, self.plan_node.facets),
            status=status,
            item_count=len(items),
            errors=errors,
            bytes_stored=sum(sizes),
            versions=[version for version in versions if version is not None],
            tracking_degraded=any(degraded),
        )

    # ── Guard ─────────────────────────────────────────────────────────────

    def _guard_allows(self, prior: Mapping[str, ArtifactRef]) -> bool:
        """Evaluate ``when`` against accumulated facets and statuses."""
        if self._guard is None:
            return True
        artifacts = {nid: ref.facets for nid, ref in prior.items()}
        statuses = {nid: ref.status for nid, ref in prior.items()}
        failures = sum(1 for ref in prior.values() if ref.status == "error")
        return self._guard.evaluate(artifacts, statuses, failures)

    # ── Argument resolution ───────────────────────────────────────────────

    def _resolve_args(
        self,
        value: Any,
        prior: Mapping[str, ArtifactRef],
        bodies: Mapping[str, Any],
        *,
        item: Any = None,
        index: Optional[int] = None,
    ) -> Any:
        """Resolve every placeholder inside ``value``.

        Three substitutions, with different costs made deliberately visible in
        the plan text:

        * ``{nodes.<id>.output}`` → that node's :class:`ArtifactRef` (small).
        * ``{artifacts.<id>}`` → the stored body, read from working memory.
        * ``{item}`` / ``{item.<field>}`` / ``{index}`` → the current item.

        A string that is *exactly* one placeholder resolves to the native
        value; an embedded one is interpolated as text.

        Substitution stays synchronous — it is a pure tree walk over already
        materialised values. The bodies it needs were awaited once by
        :meth:`_artifact_bodies` beforehand, which is what lets an enabled
        catalog be read through its awaited API without turning every
        recursive branch of this walk into a coroutine.

        Args:
            value: The (possibly nested) argument structure.
            prior: Completed nodes' artifact refs.
            bodies: ``{node_id: body}`` pre-read by :meth:`_artifact_bodies`.
            item: Current item, inside a ``for_each`` node.
            index: Current item position, inside a ``for_each`` node.

        Returns:
            The resolved structure.
        """
        if isinstance(value, dict):
            return {
                key: self._resolve_args(inner, prior, bodies, item=item, index=index) for key, inner in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._resolve_args(inner, prior, bodies, item=item, index=index) for inner in value]
        if not isinstance(value, str):
            return value

        exact_artifact = ARTIFACT_REF_RE.fullmatch(value)
        if exact_artifact:
            return bodies[exact_artifact.group(1)]
        exact_node = NODE_REF_RE.fullmatch(value)
        if exact_node:
            ref = prior.get(exact_node.group(1))
            return ref.model_dump(mode="json") if ref is not None else None

        text = value
        if index is not None:
            text = render_key(text, item=item, index=index)
        text = NODE_REF_RE.sub(lambda m: str(_ref_summary(prior.get(m.group(1)))), text)
        text = ARTIFACT_REF_RE.sub(lambda m: str(bodies[m.group(1)]), text)
        return text

    async def _artifact_bodies(self, value: Any) -> Dict[str, Any]:
        """Read every ``{artifacts.<id>}`` body ``value`` refers to, once.

        Args:
            value: The (possibly nested) argument structure.

        Returns:
            ``{node_id: body}`` for every referenced node.

        Raises:
            ToolExecutionError: If a referenced node stored nothing.
        """
        wanted: List[str] = []
        for text in _iter_strings(value):
            for node_id in ARTIFACT_REF_RE.findall(text):
                if node_id not in wanted:
                    wanted.append(node_id)
        return {node_id: await self._read_artifact(node_id) for node_id in wanted}

    # ── Working memory ────────────────────────────────────────────────────

    async def _store(
        self,
        key: str,
        payload: Any,
        *,
        index: Optional[int],
        producer_call_id: Optional[str] = None,
    ) -> "_Written":
        """Write ``payload`` to working memory, preserving its provenance.

        This runs **after** :meth:`_call_with_retry` returned, so the
        dispatcher's per-invocation context has already been reset. When a
        turn session is live, the producing attempt is therefore pinned
        explicitly across this window rather than read from an ambient
        value that no longer exists.

        Args:
            key: Working-memory alias to publish under.
            payload: The tool's payload.
            index: Fan-out position, or ``None`` for a single call.
            producer_call_id: The attempt receipt that produced ``payload``.
                ``None`` when task memory is disabled, or when no receipt
                could be established — in which case the legacy path runs
                and nothing pretends to know the producer.

        Returns:
            What was written: byte size, evidence version (enabled only)
            and whether provenance had to be degraded.
        """
        suffix = "" if index is None else f"[{index}]"
        description = f"{self.node_id}{suffix} via {self.plan_node.tool}"
        metadata = {
            "plan_node": self.node_id,
            "tool": self.plan_node.tool,
            "index": index,
        }

        session = _current_session()
        catalog = self._enabled_catalog()
        if session is None or catalog is None or producer_call_id is None:
            # Legacy path, byte-identical to the pre-FEAT-538 behaviour.
            await self.working_memory.store_result(
                key=key,
                data=payload,
                data_type="auto",
                description=description,
                metadata=metadata,
            )
            return _Written(estimate_bytes(payload), None, False)

        with session.retained_producer(producer_call_id):
            return await self._store_versioned(
                session,
                catalog,
                key,
                payload,
                description=description,
                metadata=metadata,
            )

    async def _store_versioned(
        self,
        session: Any,
        catalog: Any,
        key: str,
        payload: Any,
        *,
        description: str,
        metadata: Dict[str, Any],
    ) -> "_Written":
        """Register ``payload`` as an exact version attributed to its producer.

        Must be called inside :meth:`TurnTaskSession.retained_producer`: the
        producer is read back from the retained context rather than passed
        around, which is what proves the retention actually spans the write.

        Args:
            session: The live turn session.
            catalog: The enabled working-memory catalog.
            key: Alias to publish under.
            payload: The tool's payload.
            description: Human-readable description.
            metadata: Caller metadata for the entry.

        Returns:
            The write receipt, including ``artifact_id@version``.
        """
        context = _task_memory_context()
        producer = context.producer_call_id()
        receipt = session.receipt(producer) if producer is not None else None
        attribution = receipt.context.attribution if receipt is not None else None

        entry = await catalog.aput_generic(
            key,
            payload,
            description=description,
            metadata=metadata,
            producer_call_id=producer,
            attribution=attribution,
        )
        version = getattr(entry, "version_metadata", None)
        if version is None:  # pragma: no cover - an enabled write always versions
            return _Written(estimate_bytes(payload), None, True)

        evidence = _evidence_ref(version.artifact_id, version.version)
        attached = producer is not None and session.add_artifact_receipt(producer, evidence)
        return _Written(estimate_bytes(payload), str(evidence), not attached)

    async def _read_artifact(self, node_id: str) -> Any:
        """Read a stored body back out of working memory.

        Reading is free here: this is code, not a model, so the payload never
        touches a context window.

        Args:
            node_id: The producing plan node.

        Returns:
            The stored payload, or a list of them for a fan-out node.

        Raises:
            ToolExecutionError: If nothing was stored under that node.
        """
        keys = self._keys_for(node_id)
        if not keys:
            raise ToolExecutionError(
                f"Node {self.node_id!r}: no working-memory artifact for " f"{node_id!r}. Did it run and store a result?"
            )
        bodies = [await self._read_key(key) for key in keys]
        return bodies[0] if len(bodies) == 1 else bodies

    def _keys_for(self, node_id: str) -> List[str]:
        """Return the working-memory keys a completed node published."""
        ref = self._refs_cache.get(node_id)
        return list(ref.keys) if ref is not None else []

    def _catalog(self) -> Any:
        """Return the working memory's catalog, or ``None`` when it has none."""
        return getattr(self.working_memory, "_catalog", None)

    def _enabled_catalog(self) -> Any:
        """Return the catalog only when task memory is enabled on it.

        Returns:
            The catalog when it has a versioned artifact-store backend
            attached, otherwise ``None`` — which routes every caller back
            to the legacy synchronous behaviour.
        """
        catalog = self._catalog()
        return catalog if getattr(catalog, "is_enabled", False) else None

    async def _read_key(self, key: str) -> Any:
        """Read one working-memory entry by key.

        The catalog is the documented programmatic access point — the toolkit
        exposes only summarising *tools*, which is exactly what we must not
        go through here.

        An enabled catalog is read through its awaited API so the read is
        serialised against concurrent versioned writes under the same lock;
        the legacy configuration keeps its synchronous read.

        Args:
            key: The alias to read.

        Returns:
            The stored body.

        Raises:
            ToolExecutionError: If the toolkit exposes no catalog at all.
        """
        catalog = getattr(self.working_memory, "_catalog", None)
        if catalog is None:  # pragma: no cover - defensive
            raise ToolExecutionError("WorkingMemoryToolkit exposes no catalog to read artifacts from.")
        if getattr(catalog, "is_enabled", False):
            entry = await catalog.aget(key)
        else:
            entry = catalog.get(key)
        return getattr(entry, "data", None) if not hasattr(entry, "df") else entry.df

    async def _has_key(self, key: str) -> bool:
        """Whether ``key`` already exists in the catalog.

        Args:
            key: The alias to probe.

        Returns:
            ``True`` when an entry is already published under ``key``.
        """
        catalog = getattr(self.working_memory, "_catalog", None)
        if catalog is None:  # pragma: no cover - defensive
            return False
        if getattr(catalog, "is_enabled", False):
            try:
                await catalog.aget(key)
            except KeyError:
                return False
            return True
        return bool(key in catalog)

    # ── Tool dispatch ─────────────────────────────────────────────────────

    async def _call_with_retry(self, args: Dict[str, Any], *, index: Optional[int] = None) -> "_Attempt":
        """Dispatch the tool, retrying transient failures per ``retry``.

        Each loop iteration is ONE physical attempt and opens exactly one
        receipt for it. An attempt whose outcome could not be established
        (unknown, or cancelled) ends the loop immediately with
        :class:`UnknownToolOutcomeError`: its external effect may already
        have happened, and a retry policy is not licence to repeat it.
        Ordinary failures keep retrying exactly as they always did.

        Args:
            args: Fully resolved keyword arguments.
            index: Fan-out position, recorded on the receipt.

        Returns:
            The payload plus the receipt that produced it.

        Raises:
            UnknownToolOutcomeError: If an attempt's outcome is unresolved.
            ToolExecutionError: If every attempt failed.
        """
        policy = self.plan_node.retry
        last: Optional[BaseException] = None
        session = _current_session()

        for attempt in range(1, policy.max_attempts + 1):
            receipt = self._begin_attempt(session, attempt=attempt, index=index)
            try:
                payload = await self._dispatch(args)
                # execute_tool returns a ToolResult (rather than raising) when
                # the tool is not registered — the one path where a failure
                # arrives as a value.
                if _is_failed_tool_result(payload):
                    raise ToolExecutionError(
                        f"Tool {self.plan_node.tool!r} failed: " f"{getattr(payload, 'error', payload)}"
                    )
            except asyncio.CancelledError:
                self._end_attempt(session, receipt, error=None, cancelled=True)
                raise
            except Exception as exc:  # noqa: BLE001
                self._end_attempt(session, receipt, error=exc, cancelled=False)
                self._refuse_unknown_retry(session, receipt, exc)
                last = exc
                if attempt < policy.max_attempts:
                    self.logger.warning(
                        "Node %r attempt %d/%d failed (%s); retrying",
                        self.node_id,
                        attempt,
                        policy.max_attempts,
                        exc,
                    )
                    if policy.backoff_seconds:
                        await asyncio.sleep(policy.backoff_seconds * attempt)
                continue
            finally:
                # Belt and braces for a BaseException the branches above do
                # not name (KeyboardInterrupt, SystemExit): the ContextVar
                # must not stay bound, or the next dispatch in this context
                # would be recorded as this attempt's child.
                self._release_attempt(receipt)
            self._end_attempt(session, receipt, error=None, cancelled=False)
            return _Attempt(
                payload=payload,
                producer_call_id=None if receipt is None else receipt.record.call_id,
                degraded=self._attempt_degraded(session, receipt),
            )

        raise ToolExecutionError(
            f"Node {self.node_id!r}: tool {self.plan_node.tool!r} failed after "
            f"{policy.max_attempts} attempt(s): {last}"
        ) from last

    async def _dispatch(self, args: Dict[str, Any]) -> Any:
        """Perform one dispatch through the manager, honouring ``timeout``.

        Args:
            args: Fully resolved keyword arguments.

        Returns:
            Whatever ``execute_tool`` returned.
        """
        coro = self.tool_manager.execute_tool(
            self.plan_node.tool,
            args,
            permission_context=self.permission_context,
        )
        return await asyncio.wait_for(coro, self.plan_node.timeout) if self.plan_node.timeout else await coro

    # ── Attempt receipts (FEAT-538) ───────────────────────────────────────

    def _begin_attempt(self, session: Any, *, attempt: int, index: Optional[int]) -> Optional["_Receipt"]:
        """Open this node's receipt for one physical attempt.

        The receipt carries the plan's run/node/item/attempt identifiers
        and, when one was configured, the domain step the node maps to.
        Publishing its call id as the current call is what makes anything
        the manager dispatches underneath it a *child* of this attempt, so
        the aggregate stays distinguishable from the physical work.

        Args:
            session: The live turn session, or ``None`` when disabled.
            attempt: 1-based attempt number.
            index: Fan-out position, or ``None``.

        Returns:
            The open receipt, or ``None`` when task memory is disabled.
        """
        if session is None:
            return None
        context = _task_memory_context()
        record = session.begin_invocation(
            self.plan_node.tool,
            attempt=attempt,
            plan_run_id=self.plan_run_id,
            plan_node_id=self.node_id,
            plan_item_index=index,
            plan_attempt=attempt,
            # A plan node id is NOT a step id. Only an explicit mapping
            # attributes this call to a step; without one it keeps `plan`
            # provenance and stays task-level.
            mapped_step_id=self.step_mapping.get(self.node_id),
        )
        return _Receipt(record=record, token=context.CURRENT_CALL.set(record.call_id))

    def _end_attempt(
        self,
        session: Any,
        receipt: Optional["_Receipt"],
        *,
        error: Optional[BaseException],
        cancelled: bool,
    ) -> None:
        """Close an attempt receipt with a truthful terminal outcome.

        Resetting :data:`CURRENT_CALL` here — rather than after the whole
        retry loop — is deliberate: the next attempt must be a sibling of
        this one, not its child.

        Args:
            session: The live turn session, or ``None``.
            receipt: The open receipt, or ``None``.
            error: The exception that ended the attempt, when there was one.
            cancelled: Whether the attempt was cancelled.
        """
        if session is None or receipt is None:
            return
        models = _task_memory_models()
        self._release_attempt(receipt)
        if receipt.record.outcome is not None:
            return
        if cancelled:
            outcome = models.CallOutcome.CANCELLED
        elif error is not None:
            outcome = models.CallOutcome.ERROR
        else:
            outcome = models.CallOutcome.SUCCESS
        session.complete_invocation(
            receipt.record,
            outcome=outcome,
            executed=True,
            error=None if error is None else f"{type(error).__name__}: {error}"[:_MAX_ERROR_CHARS],
        )

    def _release_attempt(self, receipt: Optional["_Receipt"]) -> None:
        """Unbind :data:`CURRENT_CALL` for an attempt, exactly once.

        Idempotent, because it is called both on the normal path (from
        :meth:`_end_attempt`) and from the retry loop's ``finally``.

        Args:
            receipt: The receipt whose token to reset, or ``None``.
        """
        if receipt is None or receipt.token is None:
            return
        _task_memory_context().CURRENT_CALL.reset(receipt.token)
        receipt.token = None

    def _physical_attempts(self, session: Any, receipt: Any) -> List[Any]:
        """Return the physical dispatches made under one attempt receipt.

        Args:
            session: The live turn session.
            receipt: This node's attempt receipt.

        Returns:
            Child records naming ``receipt`` as their parent. Empty when no
            observer is installed on the manager, in which case the node's
            own receipt *is* the physical attempt.
        """
        return [r for r in session.records if r.parent_call_id == receipt.record.call_id]

    def _refuse_unknown_retry(self, session: Any, receipt: Any, exc: BaseException) -> None:
        """Raise instead of retrying when an attempt's outcome is unresolved.

        Args:
            session: The live turn session, or ``None``.
            receipt: This node's attempt receipt, or ``None``.
            exc: The exception that ended the attempt.

        Raises:
            UnknownToolOutcomeError: If any physical attempt underneath this
                receipt ended ``unknown`` or ``cancelled``.
        """
        if session is None or receipt is None:
            return
        for record in self._physical_attempts(session, receipt):
            outcome = record.outcome
            if outcome is not None and not outcome.is_resolved:
                raise UnknownToolOutcomeError(
                    f"Node {self.node_id!r}: tool {self.plan_node.tool!r} ended with an "
                    f"unresolved outcome ({outcome.value}); its external effect may "
                    "already have happened, so it is not retried automatically"
                ) from exc

    def _attempt_degraded(self, session: Any, receipt: Any) -> bool:
        """Whether a *successful* attempt's tracking is nevertheless degraded.

        Args:
            session: The live turn session, or ``None``.
            receipt: This node's attempt receipt, or ``None``.

        Returns:
            ``True`` when a physical attempt reported degraded tracking or an
            unresolved outcome even though a payload came back.
        """
        if session is None or receipt is None:
            return False
        for record in self._physical_attempts(session, receipt):
            if record.degraded:
                return True
            if record.outcome is not None and not record.outcome.is_resolved:
                return True
        return False

    # ── Internal caches ───────────────────────────────────────────────────

    def _remember(self, refs: Mapping[str, ArtifactRef]) -> None:
        """Cache the run's artifact refs for ``{artifacts.*}`` resolution."""
        self._refs_cache.clear()
        self._refs_cache.update(refs)


class _Attempt(NamedTuple):
    """What one successful dispatch attempt yielded.

    Attributes:
        payload: The tool's return value.
        producer_call_id: The attempt receipt that produced it, or ``None``
            when task memory is disabled.
        degraded: Whether that attempt's tracking is degraded.
    """

    payload: Any
    producer_call_id: Optional[str]
    degraded: bool


class _Written(NamedTuple):
    """What one working-memory write produced.

    Attributes:
        byte_size: Estimated payload size.
        version: ``artifact_id@version`` when the write was versioned,
            ``None`` in the legacy configuration.
        degraded: Whether provenance could not be recorded for it.
    """

    byte_size: int
    version: Optional[str]
    degraded: bool


class _Receipt:
    """An open attempt receipt plus the ContextVar token that scopes it.

    A plain mutable holder rather than a tuple: the token must be cleared
    once reset, and stashing it on the (``extra="forbid"``) Pydantic
    record would smuggle a non-field attribute into a serialisable model.

    Attributes:
        record: The open ``InvocationRecord``.
        token: The :data:`CURRENT_CALL` token, until it is reset.
    """

    __slots__ = ("record", "token")

    def __init__(self, record: Any, token: Any) -> None:
        """Initialize the holder.

        Args:
            record: The open invocation record.
            token: The ``CURRENT_CALL`` reset token.
        """
        self.record = record
        self.token = token


#: Cached ``parrot.tools.working_memory.task_memory`` modules, or ``False``
#: once the import has been shown to be unavailable. ``None`` means "not
#: looked up yet" — the three states are distinct on purpose so a disabled
#: deployment pays for the failed import exactly once.
_TASK_MEMORY: Any = None


def _task_memory() -> Any:
    """Return the task-memory ``(context, models)`` modules, or ``False``.

    Imported lazily and cached. Task memory is opt-in (FEAT-538): a
    deployment without it must not pay this import at module load, and
    must keep working if the package is absent entirely.

    Returns:
        A ``(context, models)`` tuple, or ``False`` when unavailable.
    """
    global _TASK_MEMORY  # noqa: PLW0603 - module-level import cache
    if _TASK_MEMORY is None:
        try:
            from parrot.tools.working_memory.task_memory import (  # noqa: PLC0415
                context as tm_context,
            )
            from parrot.tools.working_memory.task_memory import (  # noqa: PLC0415
                models as tm_models,
            )
        except Exception:  # noqa: BLE001 - absence is a supported configuration
            _TASK_MEMORY = False
        else:
            _TASK_MEMORY = (tm_context, tm_models)
    return _TASK_MEMORY


def _task_memory_context() -> Any:
    """Return the task-memory context module.

    Returns:
        The module. Only called once a live session has been found, which
        is itself proof the import succeeded.
    """
    return _task_memory()[0]


def _task_memory_models() -> Any:
    """Return the task-memory models module.

    Returns:
        The module. Only called once a live session has been found.
    """
    return _task_memory()[1]


def _current_session() -> Any:
    """Return the turn session bound to this context, if any.

    Returns:
        The ``TurnTaskSession``, or ``None`` when task memory is disabled,
        absent, or no turn is open. ``None`` is a truthful answer and is
        never replaced with a guess.
    """
    modules = _task_memory()
    if modules is False:
        return None
    return modules[0].current_session()


def _evidence_ref(artifact_id: str, version: int) -> Any:
    """Build an immutable ``artifact_id@version`` evidence reference.

    Args:
        artifact_id: Stable artifact identity.
        version: 1-based version within that identity.

    Returns:
        The ``EvidenceRef``.
    """
    return _task_memory_models().EvidenceRef(artifact_id=artifact_id, version=version)


def _artifact_refs(ctx: Any) -> Dict[str, ArtifactRef]:
    """Recover ``{node_id: ArtifactRef}`` from a ``FlowContext``.

    Entries that are not artifact refs (a ``start`` node's output, say) are
    ignored rather than coerced.

    Args:
        ctx: The live ``FlowContext``.

    Returns:
        Artifact refs for every completed plan node.
    """
    refs: Dict[str, ArtifactRef] = {}
    for node_id, value in (getattr(ctx, "results", None) or {}).items():
        if isinstance(value, ArtifactRef):
            refs[node_id] = value
        elif isinstance(value, Mapping) and "node_id" in value and "keys" in value:
            try:
                refs[node_id] = ArtifactRef.model_validate(value)
            except Exception:  # noqa: BLE001 - not an artifact; skip
                continue
    return refs


def _ref_summary(ref: Optional[ArtifactRef]) -> Any:
    """Render an artifact ref for interpolation into a string argument."""
    if ref is None:
        return ""
    return ref.model_dump(mode="json")


def _entry_type(payload: Any) -> str:
    """Mirror ``WorkingMemory``'s type detection for the manifest."""
    if isinstance(payload, str):
        return "text"
    if isinstance(payload, (bytes, bytearray)):
        return "binary"
    if isinstance(payload, (dict, list)):
        return "json"
    if hasattr(payload, "content") and hasattr(payload, "role"):
        return "message"
    if type(payload).__name__ == "DataFrame":
        return "dataframe"
    return "object"


def _is_failed_tool_result(payload: Any) -> bool:
    """Whether ``payload`` is a ``ToolResult`` reporting failure."""
    return hasattr(payload, "success") and hasattr(payload, "status") and payload.success is False


def make_tool_node_factory(
    tool_manager: Any,
    working_memory: Any,
    *,
    permission_context: Optional[Any] = None,
    plan_run_id: Optional[str] = None,
    step_mapping: Optional[Mapping[str, str]] = None,
) -> Callable[[Any, Set[str], Set[str]], PlanToolNode]:
    """Build the ``node_factories["tool"]`` callable for ``from_definition``.

    The live ``ToolManager`` and ``WorkingMemoryToolkit`` reach each node
    through this closure rather than through ``NodeDefinition.config``, which
    is a plain JSON dict — that is exactly the case ``node_factories`` exists
    for, and it is what lets the analyst agent read the same catalog the
    executor wrote.

    The plan-run correlation travels the same way and for the same reason:
    ``plan_run_id`` and ``step_mapping`` are runtime bindings, not plan
    text, so a plan file can never author its own step attribution.

    Args:
        tool_manager: The agent's manager; nodes dispatch through it.
        working_memory: The shared ``WorkingMemoryToolkit`` instance.
        permission_context: Optional context forwarded to ``execute_tool``.
        plan_run_id: Identity of this plan run, recorded on every attempt
            receipt when task memory is enabled.
        step_mapping: Explicit ``{plan_node_id: domain_step_id}`` mapping.
            Unmapped nodes stay task-level with ``plan`` provenance; a plan
            node id is never used as a step id by default.

    Returns:
        A factory called as ``factory(node_def, deps, succs) -> PlanToolNode``
        once per ``run_flow()``.
    """
    mapping = dict(step_mapping or {})

    def factory(node_def: Any, deps: Set[str], succs: Set[str]) -> PlanToolNode:
        return PlanToolNode(
            node_id=node_def.id,
            plan_node=PlanNode.model_validate(node_def.config),
            tool_manager=tool_manager,
            working_memory=working_memory,
            dependencies=set(deps or ()),
            successors=set(succs or ()),
            permission_context=permission_context,
            plan_run_id=plan_run_id,
            step_mapping=mapping,
        )

    return factory


def build_manifest(
    plan: Any,
    refs: Sequence[ArtifactRef],
    *,
    session_id: Optional[str] = None,
    duration_seconds: float = 0.0,
) -> Any:
    """Project a run's artifact refs into an :class:`ExecutionManifest`.

    This is the projection the ``run_execution_plan`` tool must apply instead
    of returning ``FlowContext.results`` — which, for a flow of ordinary
    nodes, would carry payload bodies straight back into the agent's context.

    Args:
        plan: The executed :class:`~.models.ExecutionPlan`.
        refs: Artifact refs produced by the run.
        session_id: Optional session identifier.
        duration_seconds: Wall-clock duration of the run.

    Returns:
        The populated :class:`~.models.ExecutionManifest`.
    """
    from .models import ExecutionManifest  # noqa: PLC0415

    ordered = list(refs)
    return ExecutionManifest(
        plan_name=plan.name,
        objective=plan.objective,
        session_id=session_id,
        artifacts=ordered,
        nodes_total=len(plan.nodes),
        nodes_ok=sum(1 for r in ordered if r.status == "ok"),
        nodes_skipped=sum(1 for r in ordered if r.status == "skipped"),
        nodes_failed=sum(1 for r in ordered if r.status in ("error", "partial")),
        duration_seconds=duration_seconds,
        total_bytes_stored=sum(r.bytes_stored for r in ordered),
    )
