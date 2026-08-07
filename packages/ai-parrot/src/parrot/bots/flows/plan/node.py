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
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from pydantic import Field, PrivateAttr

from .facets import estimate_bytes, extract_facets, merge_facets
from .guards import PlanGuard, compile_guard
from .models import ARTIFACT_REF_RE, NODE_REF_RE, ArtifactRef, PlanNode
from .paths import render_key, select

__all__ = ("MAX_RECORDED_ERRORS", "PlanToolNode", "make_tool_node_factory")

# Per-node cap on error strings kept in the manifest. Unbounded error lists
# are the classic way a "small" manifest stops being small.
MAX_RECORDED_ERRORS = 20
_MAX_ERROR_CHARS = 300

from parrot.bots.flows.core.node import Node as _BaseNode


class ToolExecutionError(RuntimeError):
    """A plan node's tool call failed after exhausting its retries."""


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
    """

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    plan_node: PlanNode
    tool_manager: Any
    working_memory: Any
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    permission_context: Optional[Any] = None
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
            self.logger.debug(
                "Node %r finished in %.3fs", self.node_id, time.monotonic() - started
            )

        await self.run_post_actions(result=ref, **kwargs)
        return ref

    # ── Single call ───────────────────────────────────────────────────────

    async def _run_single(self, prior: Mapping[str, ArtifactRef]) -> ArtifactRef:
        """Execute the node's tool once."""
        args = self._resolve_args(self.plan_node.args, prior)
        payload = await self._call_with_retry(args)
        key = self.plan_node.store_as
        size = await self._store(key, payload, index=None)
        return ArtifactRef(
            node_id=self.node_id,
            keys=[key],
            entry_type=_entry_type(payload),
            facets=extract_facets(payload, self.plan_node.facets),
            status="ok",
            bytes_stored=size,
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

        source_body = self._read_artifact(spec.source_node)
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
        errors: List[str] = []
        entry_types: List[str] = []

        async def run_item(index: int, item: Any) -> None:
            async with semaphore:
                key = render_key(self.plan_node.store_as, item=item, index=index)
                if spec.skip_existing and self._has_key(key):
                    # Idempotent re-run: this is what gives per-item resume
                    # without any scheduler involvement.
                    keys[index] = key
                    self.logger.debug("Node %r: key %r exists, skipping", self.node_id, key)
                    return
                args = self._resolve_args(
                    self.plan_node.args, prior, item=item, index=index
                )
                payload = await self._call_with_retry(args)
                sizes[index] = await self._store(key, payload, index=index)
                keys[index] = key
                facets[index] = extract_facets(payload, self.plan_node.facets)
                entry_types.append(_entry_type(payload))

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

        Args:
            value: The (possibly nested) argument structure.
            prior: Completed nodes' artifact refs.
            item: Current item, inside a ``for_each`` node.
            index: Current item position, inside a ``for_each`` node.

        Returns:
            The resolved structure.
        """
        if isinstance(value, dict):
            return {
                key: self._resolve_args(inner, prior, item=item, index=index)
                for key, inner in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                self._resolve_args(inner, prior, item=item, index=index)
                for inner in value
            ]
        if not isinstance(value, str):
            return value

        exact_artifact = ARTIFACT_REF_RE.fullmatch(value)
        if exact_artifact:
            return self._read_artifact(exact_artifact.group(1))
        exact_node = NODE_REF_RE.fullmatch(value)
        if exact_node:
            ref = prior.get(exact_node.group(1))
            return ref.model_dump(mode="json") if ref is not None else None

        text = value
        if index is not None:
            text = render_key(text, item=item, index=index)
        text = NODE_REF_RE.sub(
            lambda m: str(_ref_summary(prior.get(m.group(1)))), text
        )
        text = ARTIFACT_REF_RE.sub(
            lambda m: str(self._read_artifact(m.group(1))), text
        )
        return text

    # ── Working memory ────────────────────────────────────────────────────

    async def _store(self, key: str, payload: Any, *, index: Optional[int]) -> int:
        """Write ``payload`` to working memory and return its size in bytes."""
        suffix = "" if index is None else f"[{index}]"
        await self.working_memory.store_result(
            key=key,
            data=payload,
            data_type="auto",
            description=f"{self.node_id}{suffix} via {self.plan_node.tool}",
            metadata={
                "plan_node": self.node_id,
                "tool": self.plan_node.tool,
                "index": index,
            },
        )
        return estimate_bytes(payload)

    def _read_artifact(self, node_id: str) -> Any:
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
                f"Node {self.node_id!r}: no working-memory artifact for "
                f"{node_id!r}. Did it run and store a result?"
            )
        bodies = [self._read_key(key) for key in keys]
        return bodies[0] if len(bodies) == 1 else bodies

    def _keys_for(self, node_id: str) -> List[str]:
        """Return the working-memory keys a completed node published."""
        ref = self._refs_cache.get(node_id)
        return list(ref.keys) if ref is not None else []

    def _read_key(self, key: str) -> Any:
        """Read one working-memory entry by key.

        The catalog is the documented programmatic access point — the toolkit
        exposes only summarising *tools*, which is exactly what we must not
        go through here.
        """
        catalog = getattr(self.working_memory, "_catalog", None)
        if catalog is None:  # pragma: no cover - defensive
            raise ToolExecutionError(
                "WorkingMemoryToolkit exposes no catalog to read artifacts from."
            )
        entry = catalog.get(key)
        return getattr(entry, "data", None) if not hasattr(entry, "df") else entry.df

    def _has_key(self, key: str) -> bool:
        """Whether ``key`` already exists in the catalog."""
        catalog = getattr(self.working_memory, "_catalog", None)
        return bool(catalog is not None and key in catalog)

    # ── Tool dispatch ─────────────────────────────────────────────────────

    async def _call_with_retry(self, args: Dict[str, Any]) -> Any:
        """Dispatch the tool, retrying transient failures per ``retry``.

        Args:
            args: Fully resolved keyword arguments.

        Returns:
            The tool's payload.

        Raises:
            ToolExecutionError: If every attempt failed.
        """
        policy = self.plan_node.retry
        last: Optional[BaseException] = None

        for attempt in range(1, policy.max_attempts + 1):
            try:
                coro = self.tool_manager.execute_tool(
                    self.plan_node.tool,
                    args,
                    permission_context=self.permission_context,
                )
                payload = (
                    await asyncio.wait_for(coro, self.plan_node.timeout)
                    if self.plan_node.timeout
                    else await coro
                )
                # execute_tool returns a ToolResult (rather than raising) when
                # the tool is not registered — the one path where a failure
                # arrives as a value.
                if _is_failed_tool_result(payload):
                    raise ToolExecutionError(
                        f"Tool {self.plan_node.tool!r} failed: "
                        f"{getattr(payload, 'error', payload)}"
                    )
                return payload
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < policy.max_attempts:
                    self.logger.warning(
                        "Node %r attempt %d/%d failed (%s); retrying",
                        self.node_id, attempt, policy.max_attempts, exc,
                    )
                    if policy.backoff_seconds:
                        await asyncio.sleep(policy.backoff_seconds * attempt)

        raise ToolExecutionError(
            f"Node {self.node_id!r}: tool {self.plan_node.tool!r} failed after "
            f"{policy.max_attempts} attempt(s): {last}"
        ) from last

    # ── Internal caches ───────────────────────────────────────────────────

    def _remember(self, refs: Mapping[str, ArtifactRef]) -> None:
        """Cache the run's artifact refs for ``{artifacts.*}`` resolution."""
        self._refs_cache.clear()
        self._refs_cache.update(refs)


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
    return (
        hasattr(payload, "success")
        and hasattr(payload, "status")
        and payload.success is False
    )


def make_tool_node_factory(
    tool_manager: Any,
    working_memory: Any,
    *,
    permission_context: Optional[Any] = None,
) -> Callable[[Any, Set[str], Set[str]], PlanToolNode]:
    """Build the ``node_factories["tool"]`` callable for ``from_definition``.

    The live ``ToolManager`` and ``WorkingMemoryToolkit`` reach each node
    through this closure rather than through ``NodeDefinition.config``, which
    is a plain JSON dict — that is exactly the case ``node_factories`` exists
    for, and it is what lets the analyst agent read the same catalog the
    executor wrote.

    Args:
        tool_manager: The agent's manager; nodes dispatch through it.
        working_memory: The shared ``WorkingMemoryToolkit`` instance.
        permission_context: Optional context forwarded to ``execute_tool``.

    Returns:
        A factory called as ``factory(node_def, deps, succs) -> PlanToolNode``
        once per ``run_flow()``.
    """

    def factory(node_def: Any, deps: Set[str], succs: Set[str]) -> PlanToolNode:
        return PlanToolNode(
            node_id=node_def.id,
            plan_node=PlanNode.model_validate(node_def.config),
            tool_manager=tool_manager,
            working_memory=working_memory,
            dependencies=set(deps or ()),
            successors=set(succs or ()),
            permission_context=permission_context,
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
