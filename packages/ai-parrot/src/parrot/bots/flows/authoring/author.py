"""The node-by-node authoring loop.

Generalises ``parrot.tools.execution_plan.planner.PlanPlanner`` from "one
call writes the whole plan" to "one call writes one node", which is what
makes workflow size independent of prompt size.

Each stage is a single LLM call with a bounded prompt:

======================  ==================================================
stage                   what the prompt carries
======================  ==================================================
``skeleton``            the request + the legal node kinds
``author_node`` (× N)   the skeleton *digest* (one line per node), this
                        node's stub, this kind's JSON Schema, and the
                        catalog slice this kind needs
``author_transitions``  the skeleton digest + the authored node ids
``repair``              the rejected document + the validation report
======================  ==================================================

A per-node call never sees another node's full definition, so a
twenty-node workflow costs twenty small prompts rather than one enormous
one — the property the whole design exists to obtain.

Responses are parsed here rather than through
``AbstractClient.ask(structured_output=...)``. That path calls
``_parse_structured_output``, which falls back to returning raw text when
parsing fails; it would silently swallow exactly the failures a repair round
needs to detect. Same decision, and the same reasoning, as ``PlanPlanner``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Type, Union

from pydantic import BaseModel, ValidationError

from .blueprint import (
    BlueprintNode,
    BlueprintSkeleton,
    BlueprintTransition,
    NodeStub,
)
from .catalog import ComponentCatalog
from .schemas import (
    node_json_schema,
    skeleton_json_schema,
    transitions_json_schema,
)

__all__ = ("FlowAuthor", "FlowAuthoringError", "resolve_planner_client")

logger = logging.getLogger(__name__)


_AUTHORING_RULES = """\
You are authoring a multi-agent workflow. Rules that the JSON Schema cannot
express:

- NEVER invent a tool, agent or node-type name. Use only names from the
  catalog you are given. If nothing fits, leave the field out and say so in
  the node's purpose — a missing capability is reported to the user; an
  invented name is a workflow that fails at run time.
- Node ids are lower_snake_case, unique, and contain no dots.
- kind="agent" is an LLM worker. Its `tools` are tools it MAY call.
- kind="tool" runs one catalog tool directly with fixed args — no LLM, no
  reasoning. Use it for deterministic steps (publishing, fetching, writing).
- engine="crew" builds new agents inline: every agent node needs a
  `system_prompt`. engine="flow" wires agents that already exist: every
  agent node needs an `agent_ref` from the catalog.
- Keep the workflow as small as the request allows. Every node costs a
  model call at run time."""

_TRANSITION_RULES = """\
Now declare the transitions between the nodes.

- Reference nodes only by the ids listed. Every node except the first should
  be reachable.
- The graph must be acyclic; only an `on_condition` edge may loop back, and
  only for engine="flow".
- condition="on_success" is the default and is almost always right.
- A predicate is a CEL expression and may read ONLY `result` (the source
  node's output), `error` (its error string) and `ctx` (shared context).
  A predicate that reads anything else silently evaluates to false, and the
  branch never fires — so do not guess field names.
- For engine="crew" only `always` and `on_success` are meaningful: a crew
  has no conditional routing."""


class FlowAuthoringError(RuntimeError):
    """Raised when a response cannot be parsed into the expected model."""


def resolve_planner_client(
    planner_llm: Union[str, Dict[str, Any], Type[Any], Any],
) -> Any:
    """Resolve ``planner_llm`` into a live client.

    Accepts exactly the formats bots accept for ``llm``/``secondary_llm``, by
    delegating to the implementation ``PlanPlanner`` already uses — there is
    no second notion of "how you name a model" in this codebase.

    Args:
        planner_llm: ``"provider:model"`` string, an ``AbstractClient``
            subclass or instance, or a ``model_config`` dict.

    Returns:
        A live, not-yet-entered ``AbstractClient``.
    """
    from parrot.tools.execution_plan.planner import (  # noqa: PLC0415
        resolve_planner_client as _resolve,
    )

    return _resolve(planner_llm)


def _extract_json_text(text: str) -> str:
    """Strip a leading/trailing markdown code fence, if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def _response_text(response: Any) -> str:
    """Extract the text payload of a client response, defensively."""
    output = getattr(response, "output", None)
    if output:
        return str(output)
    content = getattr(response, "content", None)
    if content:
        return str(content)
    return str(response)


class FlowAuthor:
    """Authors a workflow one component at a time.

    Attributes:
        client: The resolved planner client.
        catalog: The component catalog every prompt is bounded by.
    """

    def __init__(
        self,
        planner_llm: Optional[Union[str, Dict[str, Any], Type[Any], Any]],
        catalog: ComponentCatalog,
        *,
        client: Any = None,
        max_nodes: int = 12,
        concurrency: int = 4,
    ) -> None:
        """Bind a client and the catalog.

        Args:
            planner_llm: See :func:`resolve_planner_client`. Ignored when
                ``client`` is supplied.
            catalog: Catalog built from the live registries.
            client: A pre-built client, used as-is. The seam that lets the
                authoring loop be exercised without a provider — anything
                implementing ``async ask(prompt, **kwargs)`` and the async
                context-manager protocol works.
            max_nodes: Upper bound on skeleton size — one call per node.
            concurrency: How many nodes to author at once. Nodes are
                independent (dependencies are declared later, by the
                transition stage), so this is safe to raise.

        Raises:
            ValueError: If neither ``planner_llm`` nor ``client`` is given.
        """
        if client is None and planner_llm is None:
            raise ValueError("FlowAuthor needs either 'planner_llm' or 'client'.")
        self.client = client if client is not None else resolve_planner_client(
            planner_llm
        )
        self.catalog = catalog
        self.max_nodes = max_nodes
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        # Entering an AbstractClient assigns it a fresh aiohttp session and
        # exiting closes it, so the context manager is NOT reentrant on one
        # shared instance: with N nodes authored concurrently, the first to
        # finish would close the session the other N-1 are still using. Refcount
        # instead — one enter for the first concurrent caller, one exit for the
        # last. See _client_session().
        self._client_lock = asyncio.Lock()
        self._client_depth = 0
        self._entered_client: Any = None
        self.logger = logging.getLogger(f"{__name__}.FlowAuthor")

    # ── stage 1: skeleton ────────────────────────────────────────────────

    async def skeleton(
        self, description: str, *, engine: str, name: Optional[str] = None
    ) -> BlueprintSkeleton:
        """Author the workflow's shape: ids, kinds and one-line purposes.

        Args:
            description: The natural-language request.
            engine: ``"crew"`` or ``"flow"``.
            name: Optional workflow name; the model picks one when unset.

        Returns:
            The parsed skeleton.

        Raises:
            FlowAuthoringError: If the response does not parse.
        """
        schema = skeleton_json_schema(self.catalog, engine=engine)
        prompt = (
            f"{_AUTHORING_RULES}\n\n"
            f"Engine: {engine}\n"
            f"Available node kinds: {self.catalog.kinds_for(engine)}\n\n"
            f"Request: {description}\n\n"
            f"Produce ONLY the workflow skeleton: at most {self.max_nodes} "
            "nodes, each with an id, a kind and a one-or-two sentence "
            "purpose. Do not write prompts, tools or configuration yet.\n"
            + (f"Use the workflow name {name!r}.\n" if name else "")
            + f"\nJSON Schema:\n{json.dumps(schema)}\n\n"
            "Respond with ONLY the JSON document — no prose, no code fences."
        )
        skeleton = await self._call_model(prompt, BlueprintSkeleton)
        if len(skeleton.nodes) > self.max_nodes:
            self.logger.warning(
                "Skeleton has %d nodes, truncating to max_nodes=%d",
                len(skeleton.nodes), self.max_nodes,
            )
            skeleton = skeleton.model_copy(
                update={"nodes": skeleton.nodes[: self.max_nodes]}
            )
        # The model may pick a different engine label; the caller's choice wins.
        return skeleton.model_copy(update={"engine": engine})

    # ── stage 2: one node per call ───────────────────────────────────────

    async def author_node(
        self, stub: NodeStub, skeleton: BlueprintSkeleton
    ) -> BlueprintNode:
        """Author one node in its own bounded call.

        The prompt carries the skeleton *digest* — one line per node — never
        the other nodes' authored definitions. That is what keeps the
        context flat as the workflow grows.

        Args:
            stub: The node to author.
            skeleton: The skeleton, for neighbour context.

        Returns:
            The authored node.

        Raises:
            FlowAuthoringError: If the response does not parse.
        """
        schema = node_json_schema(
            self.catalog, engine=skeleton.engine, kind=stub.kind
        )
        catalog_slice = self.catalog.render_for(stub.kind, engine=skeleton.engine)
        prompt = (
            f"{_AUTHORING_RULES}\n\n"
            f"{skeleton.summarize()}\n\n"
            f"{catalog_slice}\n\n"
            f"Author ONLY the node {stub.id!r} (kind={stub.kind!r}). Its "
            f"purpose is: {stub.purpose}\n"
            "Do not author any other node. Keep 'id' and 'kind' exactly as "
            "given.\n\n"
            f"JSON Schema:\n{json.dumps(schema)}\n\n"
            "Respond with ONLY the JSON document — no prose, no code fences."
        )
        node = await self._call_model(prompt, BlueprintNode)
        return self._pin_identity(node, stub)

    async def author_nodes(
        self, skeleton: BlueprintSkeleton
    ) -> tuple[List[BlueprintNode], List[str]]:
        """Author every node concurrently.

        A node that fails after its repair round is dropped rather than
        failing the run: a workflow missing one step, with that step named,
        is more useful than no workflow at all — and the caller reports it as
        ``DEGRADED``, never as success.

        Args:
            skeleton: The skeleton to fill in.

        Returns:
            ``(authored_nodes, failed_node_ids)``.
        """

        async def _one(stub: NodeStub) -> Optional[BlueprintNode]:
            async with self._semaphore:
                try:
                    return await self.author_node(stub, skeleton)
                except Exception:
                    self.logger.exception("Failed to author node %r", stub.id)
                    return None

        results = await asyncio.gather(*(_one(stub) for stub in skeleton.nodes))
        nodes = [node for node in results if node is not None]
        failed = [
            stub.id for stub, node in zip(skeleton.nodes, results) if node is None
        ]
        return nodes, failed

    # ── stage 3: transitions ─────────────────────────────────────────────

    async def author_transitions(
        self, skeleton: BlueprintSkeleton, nodes: Sequence[BlueprintNode]
    ) -> List[BlueprintTransition]:
        """Author the edges between the authored nodes.

        Args:
            skeleton: The skeleton, for purposes and ordering.
            nodes: The nodes that were successfully authored — transitions
                are constrained to these ids, so a dropped node cannot be
                referenced.

        Returns:
            The transition list, empty when the workflow has a single node.

        Raises:
            FlowAuthoringError: If the response does not parse.
        """
        node_ids = [node.id for node in nodes]
        if len(node_ids) < 2:
            return []

        schema = transitions_json_schema(node_ids)
        prompt = (
            f"{_TRANSITION_RULES}\n\n"
            f"{skeleton.summarize()}\n\n"
            f"Engine: {skeleton.engine}\n"
            f"Authored nodes (use only these ids): {node_ids}\n\n"
            f"JSON Schema:\n{json.dumps(schema)}\n\n"
            "Respond with ONLY the JSON document — no prose, no code fences."
        )
        document = await self._call_json(prompt)
        return self._parse_transitions(document)

    # ── repair ───────────────────────────────────────────────────────────

    async def repair_transitions(
        self,
        skeleton: BlueprintSkeleton,
        nodes: Sequence[BlueprintNode],
        report: Any,
    ) -> List[BlueprintTransition]:
        """Re-author transitions with the validation report embedded verbatim.

        Transitions are the repair target because that is where cross-node
        mistakes land — a dangling reference, a cycle, a predicate reading a
        field that does not exist. Per-node errors are repaired by re-running
        that node alone.

        Args:
            skeleton: The skeleton.
            nodes: The authored nodes.
            report: The failing :class:`ValidationReport`.

        Returns:
            The corrected transitions.

        Raises:
            FlowAuthoringError: If the repaired response does not parse.
        """
        node_ids = [node.id for node in nodes]
        schema = transitions_json_schema(node_ids)
        prompt = (
            f"{_TRANSITION_RULES}\n\n"
            f"{skeleton.summarize()}\n\n"
            f"Authored nodes (use only these ids): {node_ids}\n\n"
            f"Your previous transitions failed validation:\n{report}\n\n"
            f"JSON Schema:\n{json.dumps(schema)}\n\n"
            "Correct them and respond with ONLY the JSON document — no "
            "prose, no code fences."
        )
        document = await self._call_json(prompt)
        return self._parse_transitions(document)

    async def repair_node(
        self,
        stub: NodeStub,
        skeleton: BlueprintSkeleton,
        issues: Sequence[Any],
    ) -> BlueprintNode:
        """Re-author one node with its validation issues embedded.

        Args:
            stub: The node's skeleton stub.
            skeleton: The skeleton, for neighbour context.
            issues: The issues raised against this node.

        Returns:
            The corrected node.

        Raises:
            FlowAuthoringError: If the repaired response does not parse.
        """
        schema = node_json_schema(
            self.catalog, engine=skeleton.engine, kind=stub.kind
        )
        catalog_slice = self.catalog.render_for(stub.kind, engine=skeleton.engine)
        rendered = "\n".join(str(issue) for issue in issues)
        prompt = (
            f"{_AUTHORING_RULES}\n\n"
            f"{skeleton.summarize()}\n\n"
            f"{catalog_slice}\n\n"
            f"Your node {stub.id!r} failed validation:\n{rendered}\n\n"
            f"JSON Schema:\n{json.dumps(schema)}\n\n"
            "Correct the node and respond with ONLY the JSON document — no "
            "prose, no code fences."
        )
        node = await self._call_model(prompt, BlueprintNode)
        return self._pin_identity(node, stub)

    # ── plumbing ─────────────────────────────────────────────────────────

    @staticmethod
    def _pin_identity(node: BlueprintNode, stub: NodeStub) -> BlueprintNode:
        """Force ``node``'s identity back to its stub, re-validating the result.

        The skeleton is authoritative for id and kind: a drifted id breaks
        assembly, and a drifted kind means the model answered a different
        question than it was asked.

        Re-validation is the point. ``model_copy(update=...)`` does not re-run
        validators, so overwriting ``kind`` on a node authored as another kind
        would produce a combination ``BlueprintNode`` rejects outright — an
        ``agent`` still carrying a ``tool``, say. That node would then compile
        down the agent branch with its tool silently discarded. Rebuilding
        through ``model_validate`` makes the contradiction raise here, where
        the repair round can still see it.

        Args:
            node: The authored node.
            stub: The stub it was supposed to author.

        Returns:
            The node with its stub identity applied.

        Raises:
            FlowAuthoringError: If the response cannot be reconciled with the
                stub's kind.
        """
        if node.id == stub.id and node.kind == stub.kind:
            return node

        payload = node.model_dump()
        payload["id"] = stub.id
        payload["kind"] = stub.kind
        try:
            return BlueprintNode.model_validate(payload)
        except ValidationError as exc:
            raise FlowAuthoringError(
                f"Node {stub.id!r} was authored as kind {node.kind!r} but the "
                f"skeleton declares {stub.kind!r}, and the two cannot be "
                f"reconciled: {exc}"
            ) from exc

    def _parse_transitions(self, document: Any) -> List[BlueprintTransition]:
        """Coerce a transitions response into models.

        Accepts either ``{"transitions": [...]}`` or a bare array, since both
        are natural readings of the request and rejecting one would fail a
        response that is materially correct.

        Args:
            document: The parsed JSON.

        Returns:
            The transition models.

        Raises:
            FlowAuthoringError: If the payload is neither shape, or an entry
                fails validation.
        """
        if isinstance(document, dict):
            raw = document.get("transitions", [])
        elif isinstance(document, list):
            raw = document
        else:
            raise FlowAuthoringError(
                f"Expected an object with 'transitions' or a JSON array, got "
                f"{type(document).__name__}."
            )
        try:
            return [BlueprintTransition.model_validate(item) for item in raw]
        except ValidationError as exc:
            raise FlowAuthoringError(f"Invalid transition: {exc}") from exc

    async def _call_json(self, prompt: str) -> Any:
        """Make one call and parse the response as JSON."""
        text = await self._call(prompt)
        cleaned = _extract_json_text(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise FlowAuthoringError(
                f"Response was not valid JSON: {exc}. Response started with: "
                f"{text[:200]!r}"
            ) from exc

    async def _call_model(self, prompt: str, model: Type[BaseModel]) -> Any:
        """Make one call and validate the response into ``model``."""
        document = await self._call_json(prompt)
        try:
            return model.model_validate(document)
        except ValidationError as exc:
            raise FlowAuthoringError(
                f"Response failed {model.__name__} validation: {exc}"
            ) from exc

    @asynccontextmanager
    async def _client_session(self) -> AsyncIterator[Any]:
        """Yield the entered client, entering it once for all concurrent users.

        ``AbstractClient.__aenter__`` creates a new ``aiohttp.ClientSession``
        and ``__aexit__`` closes it, so nesting ``async with self.client`` on
        one instance is unsafe: concurrent authoring calls would each replace
        the session (leaking the previous one) and the first to exit would
        close the session still in use by the rest, failing them with "Session
        is closed".

        The lock guards only the depth transitions, never the model call, so
        node authoring stays as concurrent as ``concurrency`` allows.

        Yields:
            The entered client.
        """
        async with self._client_lock:
            if self._client_depth == 0:
                self._entered_client = await self.client.__aenter__()
            self._client_depth += 1
            entered = self._entered_client
        try:
            yield entered
        finally:
            async with self._client_lock:
                self._client_depth -= 1
                if self._client_depth == 0:
                    self._entered_client = None
                    await self.client.__aexit__(None, None, None)

    async def _call(self, prompt: str) -> str:
        """Make exactly one call to the resolved client and return its text."""
        async with self._client_session() as entered:
            response = await entered.ask(
                prompt=prompt,
                model=getattr(entered, "model", None),
                temperature=0.0,
            )
        return _response_text(response)
