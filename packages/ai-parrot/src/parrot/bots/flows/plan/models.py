"""ExecutionPlan — declarative, tool-only DAG authored by a thinking model.

A plan is written **once** by a long-context model (planner phase), validated
statically against the live ``ToolManager``, and then executed by
``AgentsFlow`` with **zero LLM tokens in the loop**. Tool payloads are stored
in ``WorkingMemory`` under keys the planner itself chose; only small
``facets`` travel back through ``FlowContext.results``.

Design invariants
-----------------

1. **Tool-only by construction.** ``PlanNode`` carries a ``tool`` name and has
   no ``agent_ref``. A plan therefore cannot contain an agent node, which
   makes the agent → tool → flow → agent recursion structurally impossible
   rather than merely forbidden by a validator.
2. **Payloads never enter a context.** Every node writes its result to
   working memory under ``store_as``; the value published to
   ``FlowContext.results`` is an :class:`ArtifactRef`, not the body.
3. **Guards read facets, never bodies.** ``when`` is a CEL expression
   evaluated against the accumulated facet map, so branching costs nothing.
4. **Cardinality is discovered at run time.** ``for_each`` fans out *inside*
   a single DAG node, so the graph stays static and exportable/checkpointable
   while the item count is only known once the source node has run.

Placeholder conventions (two, deliberately distinct)
----------------------------------------------------

``{nodes.<id>.output}``
    The *small* published value of a prior node — its :class:`ArtifactRef`.
    This is the placeholder syntax already understood by
    ``parrot.bots.flows.crew.tool_node.resolve_templates``.

``{artifacts.<id>}``
    The *full body* stored in working memory. Resolved by the executor
    reading the catalog directly (code, zero token cost). Only legal inside
    ``ForEach.source`` and ``PlanNode.args`` — never published anywhere a
    model can see it.

Keeping the two syntaxes separate makes the expensive reference visible in
the plan text itself.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = (
    "ARTIFACT_REF_RE",
    "NODE_REF_RE",
    "ArtifactRef",
    "ExecutionManifest",
    "ExecutionPlan",
    "FacetSpec",
    "ForEach",
    "PlanNode",
    "PlanMetadata",
    "RetryPolicy",
)

# ``{artifacts.<node_id>}`` — the full body in working memory.
ARTIFACT_REF_RE = re.compile(r"\{artifacts\.([A-Za-z0-9_\-]+)\}")
# ``{nodes.<node_id>.output}`` — the published ArtifactRef (crew convention).
NODE_REF_RE = re.compile(r"\{nodes\.([A-Za-z0-9_\-]+)\.output\}")
# Substitutions legal inside ``store_as`` for a for_each node.
_STORE_KEY_VAR_RE = re.compile(r"\{(index|item(?:\.[A-Za-z0-9_]+)*)\}")

_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


class RetryPolicy(BaseModel):
    """Per-node retry behaviour for transient tool failures."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=10)
    backoff_seconds: float = Field(default=0.0, ge=0.0, le=60.0)


class FacetSpec(BaseModel):
    """What the executor extracts from a payload into the manifest.

    Facets are the *only* thing a model ever sees about a stored payload, so
    they must be small, structural and cheap to compute. They are what
    ``when`` guards read.

    Attributes:
        paths: Dotted paths whose values are copied verbatim. Use for scalars
            and short strings, e.g. ``"metadata.scanner"``.
        counts: ``{facet_name: dotted_path}`` where the path resolves to a
            list; the facet holds its length. e.g. ``{"n_findings":
            "findings[]"}``.
        group_counts: ``{facet_name: dotted_path}`` where the path resolves to
            a list of scalars; the facet holds a ``{value: occurrences}`` map.
            e.g. ``{"by_severity": "findings[].severity"}`` →
            ``{"critical": 12, "high": 341}``.
        max_group_keys: Cap on distinct keys retained per group count, so a
            high-cardinality field cannot blow up the manifest.
    """

    model_config = ConfigDict(extra="forbid")

    paths: Dict[str, str] = Field(default_factory=dict)
    counts: Dict[str, str] = Field(default_factory=dict)
    group_counts: Dict[str, str] = Field(default_factory=dict)
    max_group_keys: int = Field(default=25, ge=1, le=200)


class ForEach(BaseModel):
    """Fan-out spec: run this node's tool once per item of ``source``.

    The expansion happens **inside** one DAG node, not by mutating the graph.
    That keeps ``FlowDefinition`` static — so ``to_definition()`` export and
    checkpointing keep working — while the item count stays unknown until the
    source node has actually run.

    Per-item resumability comes from idempotence rather than from
    checkpointing: when ``skip_existing`` is set, an item whose ``store_as``
    key is already present in working memory is not re-executed, so a
    re-run after a crash only does the missing work.

    Attributes:
        source: ``{artifacts.<node_id>}`` — the working-memory body to
            iterate. Must reference a node listed in ``depends_on``.
        select: Optional dotted path into the source, with ``[]`` marking a
            list to flatten. ``"findings[].id"`` yields the list of ids.
            Omit to iterate the source itself (it must then be a list).
        max_items: Hard ceiling on expansion. Exceeding it is an execution
            error, never a silent truncation.
        max_concurrency: Concurrent in-flight tool calls for this node.
        on_item_error: ``fail`` aborts the node on the first item error;
            ``collect`` records per-item errors and continues (default);
            ``skip`` drops failed items without recording them.
        skip_existing: Skip items whose ``store_as`` key already exists.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(
        ...,
        description="'{artifacts.<node_id>}' reference to the body to iterate",
    )
    select: Optional[str] = Field(
        default=None,
        description="Dotted path with '[]' list markers, e.g. 'findings[].id'",
    )
    alias: str = Field(
        default="item",
        alias="as",
        description="Name bound to the current item inside args templates",
    )
    max_items: int = Field(default=1000, ge=1, le=100_000)
    max_concurrency: int = Field(default=8, ge=1, le=64)
    on_item_error: Literal["fail", "collect", "skip"] = "collect"
    skip_existing: bool = True

    @model_validator(mode="after")
    def _check_source(self) -> "ForEach":
        if not ARTIFACT_REF_RE.fullmatch(self.source.strip()):
            raise ValueError(
                f"ForEach.source must be exactly '{{artifacts.<node_id>}}', "
                f"got {self.source!r}"
            )
        return self

    @property
    def source_node(self) -> str:
        """The node id referenced by ``source``."""
        match = ARTIFACT_REF_RE.fullmatch(self.source.strip())
        assert match is not None  # guaranteed by the validator
        return match.group(1)


class PlanNode(BaseModel):
    """A single deterministic tool invocation (or fan-out of invocations).

    Attributes:
        id: Unique node identifier; also the handle used by
            ``{nodes.<id>.output}`` and ``{artifacts.<id>}``.
        tool: Registered tool name. Validated against the live ``ToolManager``
            at plan-validation time, not at execution time.
        args: Keyword arguments for the tool. String leaves may contain
            ``{nodes.<id>.output}``, ``{artifacts.<id>}`` and — inside a
            ``for_each`` node — ``{item}`` / ``{item.<field>}`` / ``{index}``.
        store_as: Working-memory key template for the result. For a
            ``for_each`` node it MUST vary per item (contain ``{index}`` or an
            ``{item...}`` reference), otherwise every item would overwrite the
            previous one — ``WorkingMemoryCatalog.put_generic`` overwrites
            silently.
        depends_on: Node ids that must complete first. Every id referenced by
            a placeholder or by ``for_each.source`` must appear here; the
            validator enforces it rather than inferring edges silently.
        when: Optional CEL guard. Evaluated against
            ``ctx.artifacts.<node_id>.<facet>`` and ``ctx.errors``. When it
            evaluates false the node is skipped and publishes a skipped
            :class:`ArtifactRef`.
        facets: What to extract into the manifest. Defaults to a structural
            summary when omitted.
        timeout: Per-call timeout in seconds (per item under ``for_each``).
        retry: Retry policy for transient failures.
        description: Free text for auditability; ignored at run time.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    store_as: str
    depends_on: List[str] = Field(default_factory=list)
    when: Optional[str] = None
    for_each: Optional[ForEach] = None
    facets: FacetSpec = Field(default_factory=FacetSpec)
    timeout: Optional[float] = Field(default=None, gt=0.0)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    description: Optional[str] = None

    @model_validator(mode="after")
    def _check_node(self) -> "PlanNode":
        if not _IDENT_RE.match(self.id):
            raise ValueError(
                f"PlanNode.id {self.id!r} must match {_IDENT_RE.pattern}"
            )
        if not self.store_as.strip():
            raise ValueError(f"Node {self.id!r}: store_as must be non-empty")

        has_var = bool(_STORE_KEY_VAR_RE.search(self.store_as))
        if self.for_each is not None and not has_var:
            raise ValueError(
                f"Node {self.id!r}: store_as {self.store_as!r} is constant but "
                "the node fans out with for_each — every item would overwrite "
                "the previous one. Include '{index}' or '{item.<field>}'."
            )
        if self.for_each is None and has_var:
            raise ValueError(
                f"Node {self.id!r}: store_as {self.store_as!r} uses a per-item "
                "variable but the node has no for_each."
            )
        if self.id in self.depends_on:
            raise ValueError(f"Node {self.id!r} cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"Node {self.id!r}: duplicate ids in depends_on")
        return self

    def referenced_nodes(self) -> set[str]:
        """Node ids this node references through placeholders or ``for_each``.

        Returns:
            The set of referenced node ids (excluding ``depends_on`` itself).
        """
        found: set[str] = set()
        for text in _iter_strings(self.args):
            found.update(ARTIFACT_REF_RE.findall(text))
            found.update(NODE_REF_RE.findall(text))
        if self.for_each is not None:
            found.add(self.for_each.source_node)
        return found


class PlanMetadata(BaseModel):
    """Flow-level execution defaults carried into ``FlowMetadata``."""

    model_config = ConfigDict(extra="forbid")

    max_parallel_tasks: int = Field(default=10, ge=1, le=128)
    execution_timeout: Optional[float] = Field(default=None, gt=0.0)
    checkpoint: bool = True
    durable: bool = False


class ExecutionPlan(BaseModel):
    """A validated, tool-only DAG ready to compile into a ``FlowDefinition``.

    Example:
        >>> plan = ExecutionPlan(
        ...     name="daily_security_sweep",
        ...     objective="Ingest yesterday's scanner reports and diff them.",
        ...     nodes=[
        ...         PlanNode(id="list", tool="s3_filter_reports",
        ...                  args={"prefix": "prowler/"}, store_as="listing",
        ...                  facets=FacetSpec(counts={"n": "keys[]"})),
        ...         PlanNode(id="fetch", tool="s3_get_latest_report",
        ...                  args={"key": "{item}"}, store_as="report_{index}",
        ...                  depends_on=["list"],
        ...                  when="ctx.artifacts.list.n > 0",
        ...                  for_each=ForEach(source="{artifacts.list}",
        ...                                   select="keys[]")),
        ...     ],
        ... )
        >>> plan.topological_order()
        ['list', 'fetch']
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    objective: str = Field(
        ...,
        description="What this plan achieves; carried into the manifest for audit",
    )
    nodes: List[PlanNode] = Field(..., min_length=1)
    metadata: PlanMetadata = Field(default_factory=PlanMetadata)

    @model_validator(mode="after")
    def _check_plan(self) -> "ExecutionPlan":
        ids = [node.id for node in self.nodes]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"Duplicate node ids: {sorted(duplicates)}")
        known = set(ids)

        # Every dependency and every placeholder target must exist, and every
        # placeholder target must be declared as a dependency. Inferring the
        # edge silently would let a plan read an artifact that has not been
        # scheduled yet.
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in known:
                    raise ValueError(
                        f"Node {node.id!r} depends on unknown node {dep!r}"
                    )
            undeclared = node.referenced_nodes() - set(node.depends_on)
            if undeclared:
                raise ValueError(
                    f"Node {node.id!r} references {sorted(undeclared)} but does "
                    "not list them in depends_on"
                )

        # Static artifact keys must be unique. Templated keys (for_each) are
        # checked for a distinct prefix instead, since their expansion is
        # unknown until run time.
        static: dict[str, str] = {}
        for node in self.nodes:
            if node.for_each is not None:
                continue
            owner = static.get(node.store_as)
            if owner is not None:
                raise ValueError(
                    f"Nodes {owner!r} and {node.id!r} both store to key "
                    f"{node.store_as!r}; working memory would overwrite silently"
                )
            static[node.store_as] = node.id

        self._assert_acyclic()
        return self

    def _assert_acyclic(self) -> None:
        """Raise ``ValueError`` naming a cycle if the dependency graph has one."""
        deps = {node.id: set(node.depends_on) for node in self.nodes}
        state: dict[str, int] = {}  # 0 = visiting, 1 = done
        stack: list[str] = []

        def visit(node_id: str) -> None:
            mark = state.get(node_id)
            if mark == 1:
                return
            if mark == 0:
                cycle = stack[stack.index(node_id):] + [node_id]
                raise ValueError(f"Dependency cycle: {' -> '.join(cycle)}")
            state[node_id] = 0
            stack.append(node_id)
            for dep in sorted(deps[node_id]):
                visit(dep)
            stack.pop()
            state[node_id] = 1

        for node_id in sorted(deps):
            visit(node_id)

    def topological_order(self) -> List[str]:
        """Return node ids in a stable dependency-respecting order.

        Ties are broken by the order nodes appear in the plan, so the result
        is deterministic and diffable.

        Returns:
            Node ids, dependencies before dependents.
        """
        deps = {node.id: set(node.depends_on) for node in self.nodes}
        position = {node.id: index for index, node in enumerate(self.nodes)}
        ordered: List[str] = []
        done: set[str] = set()
        while len(ordered) < len(deps):
            ready = sorted(
                (nid for nid, d in deps.items() if nid not in done and d <= done),
                key=position.__getitem__,
            )
            if not ready:  # pragma: no cover — _assert_acyclic prevents this
                raise ValueError("Dependency cycle detected during ordering")
            ordered.extend(ready)
            done.update(ready)
        return ordered

    def node(self, node_id: str) -> PlanNode:
        """Look up a node by id.

        Args:
            node_id: The node identifier.

        Returns:
            The matching :class:`PlanNode`.

        Raises:
            KeyError: If no node has that id.
        """
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"No node {node_id!r} in plan {self.name!r}")


class ArtifactRef(BaseModel):
    """What a node publishes to ``FlowContext.results`` — never the body.

    Attributes:
        node_id: The producing node.
        keys: Working-memory keys written by this node (one, or many under
            ``for_each``).
        entry_type: ``WorkingMemory`` entry type of the payload(s).
        facets: Small structural values extracted per :class:`FacetSpec`;
            what ``when`` guards read.
        status: ``ok``, ``skipped`` (guard was false), ``partial`` (some
            items failed under ``on_item_error="collect"``) or ``error``.
        item_count: Items expanded, for ``for_each`` nodes.
        errors: Per-item or node-level error messages, truncated by the
            executor.
        bytes_stored: Total payload bytes written to working memory — the
            number that makes rehydration cost visible before it is paid.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    keys: List[str] = Field(default_factory=list)
    entry_type: Optional[str] = None
    facets: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "skipped", "partial", "error"] = "ok"
    item_count: Optional[int] = None
    errors: List[str] = Field(default_factory=list)
    bytes_stored: int = 0


class ExecutionManifest(BaseModel):
    """The complete, context-safe result of running a plan.

    This is what the ``run_execution_plan`` tool returns to the agent. It is
    bounded by construction: facets are capped, errors are truncated and no
    payload body appears anywhere.
    """

    model_config = ConfigDict(extra="forbid")

    plan_name: str
    objective: str
    session_id: Optional[str] = None
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    nodes_total: int = 0
    nodes_ok: int = 0
    nodes_skipped: int = 0
    nodes_failed: int = 0
    duration_seconds: float = 0.0
    total_bytes_stored: int = 0

    def artifact(self, node_id: str) -> Optional[ArtifactRef]:
        """Return the artifact produced by ``node_id``, if any."""
        for ref in self.artifacts:
            if ref.node_id == node_id:
                return ref
        return None

    def facet_map(self) -> Dict[str, Dict[str, Any]]:
        """Return ``{node_id: facets}`` — the activation for ``when`` guards."""
        return {ref.node_id: dict(ref.facets) for ref in self.artifacts}


def _iter_strings(value: Any):
    """Yield every string leaf inside a nested structure.

    Args:
        value: Any nested combination of dicts, lists, tuples and scalars.

    Yields:
        Each string leaf encountered.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)
