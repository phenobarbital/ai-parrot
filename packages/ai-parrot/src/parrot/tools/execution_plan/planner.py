"""``PlanPlanner`` — ``objective`` mode: one structured LLM call authors an
``ExecutionPlan``, with at most one bounded repair round on validation
failure (spec §3 Module 4).

``resolve_planner_client`` accepts the exact same ``planner_llm`` formats
bots accept for ``llm``/``secondary_llm``
(``ModelSwitchingMixin.secondary_llm``, ``model_switching.py:92``): a
``"provider:model"`` string, an ``AbstractClient`` subclass or instance, or
a ``model_config`` dict. There is no implicit default model anywhere in
this module — ``objective`` mode without a configured ``planner_llm`` is a
structural error the toolkit (TASK-2184) raises before ``PlanPlanner`` is
ever constructed.

Parsing is done here rather than through ``AbstractClient.ask(structured_
output=...)``: that base-class path silently falls back to returning the
raw response text on a parse/validation failure (see
``AbstractClient._parse_structured_output``), which would hide exactly the
failures a repair round needs to detect. Instead the schema is embedded in
the prompt and the response is parsed/validated here, raising a typed
:class:`PlanAuthoringError` on failure.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Type, Union

from pydantic import ValidationError

from parrot.bots.flows.plan import ExecutionManifest, ExecutionPlan
from parrot.bots.flows.plan.validator import ValidationReport
from parrot.clients.base import AbstractClient
from parrot.clients.factory import SUPPORTED_CLIENTS, LLMFactory

from .catalog import ToolCatalogEntry
from .models import PlanDelta

__all__ = ("PlanAuthoringError", "PlanPlanner", "resolve_planner_client")

_PLANNING_RULES = """\
You are authoring an ExecutionPlan: a tool-only, deterministic DAG. Rules:
- Every node names a `tool` from the catalog below and a `store_as` key.
- Nodes may reference prior nodes ONLY via these placeholder families:
  `{nodes.<id>.output}` (the small published ArtifactRef), `{artifacts.<id>}`
  (the full stored body — legal only inside `for_each.source` and node
  `args`), and inside a `for_each` node: `{item}` / `{item.<field>}` /
  `{index}`.
- Every node referenced by a placeholder or by `for_each.source` MUST also
  appear in that node's `depends_on`.
- A `for_each` node's `store_as` MUST vary per item (contain `{index}` or
  an `{item...}` reference); a non-`for_each` node's `store_as` MUST NOT.
- Never invent a tool not in the catalog. Never add an `agent` node — plans
  are tool-only by construction."""


_DELEGATE_RULES = """\
Delegate nodes (`"type": "delegate"`) — a tiny local model picks ONE tool call at run time:
- Use one ONLY when the arguments cannot be written as templates at plan time (choose among
  a few tools from an upstream result, derive args from a short text, per-item triage).
  If args are known now, use a normal tool node — it is cheaper and cannot fail.
- Fields: `instruction` (short text; same placeholders as `args`), optional `facts`
  (string-to-string map), `tools` (1..{max_tools} names from the list below), optional `min_confidence`
  (0..1; when set, proposals without a confidence score are REJECTED), optional `accept_when`
  (CEL over `ctx.proposal.name` / `ctx.proposal.arguments`), `on_reject`
  (`fail` | `retry_backend` | `escalate`), optional `allow_side_effects`, and `store_as` /
  `depends_on` / `for_each` as usual.
- Delegate-safe tools: {safe_tools}. Any other tool needs `allow_side_effects: true` AND host permission.
- Never put a delegate node's `tools` above {max_tools}; split the step instead."""


_DELTA_RULES = """\
You are repairing a FAILED ExecutionPlan at runtime. Respond with a PlanDelta: ONLY the
replacement nodes, keyed by their EXISTING ids. Rules:
- You may replace ONLY the node ids listed as eligible. Never add a node, never rename one,
  never return a node whose id is not eligible.
- For each replacement keep `id`, `store_as`, `depends_on` and any `for_each`
  source/select/skip_existing EXACTLY as in the original. You may change `tool`, `args`,
  `facets`, `when`, `timeout`, `retry`, `description`.
- Successful nodes are NOT re-executed; a replacement may still depend on them.
- Never invent a tool not in the catalog."""


class PlanAuthoringError(RuntimeError):
    """Raised when a planner response cannot be parsed into an ExecutionPlan."""


def resolve_planner_client(
    planner_llm: Union[str, Dict[str, Any], Type[AbstractClient], AbstractClient],
) -> AbstractClient:
    """Resolve ``planner_llm`` into a live, not-yet-entered ``AbstractClient``.

    Args:
        planner_llm: ``"provider:model"`` string, an ``AbstractClient``
            subclass or instance, or a ``model_config`` dict (same keys as
            ``AbstractBot._parse_model_config``: ``name``/``llm``/
            ``provider``, ``model``, ``temperature``, ``top_k``, ``top_p``,
            ``max_tokens``, plus any extra client kwargs).

    Returns:
        A live ``AbstractClient``.

    Raises:
        ValueError: If ``planner_llm`` is none of the accepted formats, or
            a dict/string names an unsupported provider.
    """
    if isinstance(planner_llm, AbstractClient):
        return planner_llm
    if isinstance(planner_llm, type) and issubclass(planner_llm, AbstractClient):
        return planner_llm()
    if isinstance(planner_llm, dict):
        return _client_from_model_config(planner_llm)
    if isinstance(planner_llm, str):
        return LLMFactory.create(planner_llm)

    raise ValueError(
        "planner_llm must be one of: a 'provider:model' string, an "
        "AbstractClient instance or subclass, or a model_config dict "
        f"(name/llm/provider + model + params). Got {type(planner_llm).__name__}."
    )


def _client_from_model_config(model_config: Dict[str, Any]) -> AbstractClient:
    """Build a client from a ``model_config`` dict (navigator.bots-style)."""
    cfg = dict(model_config)
    provider = cfg.pop("name", None) or cfg.pop("llm", None) or cfg.pop("provider", None)
    if not provider:
        raise ValueError("planner_llm model_config dict must set one of 'name'/'llm'/'provider'.")
    if isinstance(provider, str) and ":" in provider:
        provider, parsed_model = LLMFactory.parse_llm_string(provider)
        cfg.setdefault("model", parsed_model)
    provider = provider.lower()

    if provider not in SUPPORTED_CLIENTS:
        raise ValueError(
            f"Unsupported LLM provider in planner_llm model_config: {provider!r}. "
            f"Supported: {list(SUPPORTED_CLIENTS.keys())}"
        )
    client_class = SUPPORTED_CLIENTS[provider]
    if callable(client_class) and not isinstance(client_class, type):
        client_class = client_class()  # resolve lazy loader

    return client_class(
        model=cfg.pop("model", None),
        temperature=cfg.pop("temperature", 0.1),
        top_k=cfg.pop("top_k", 41),
        top_p=cfg.pop("top_p", 0.9),
        max_tokens=cfg.pop("max_tokens", None),
        **cfg,
    )


class PlanPlanner:
    """Authors/repairs an :class:`ExecutionPlan` via exactly one LLM call
    per round.

    Attributes:
        client: The resolved planner client.
        catalog: Allowlist-scoped tool catalog embedded in every prompt.
    """

    def __init__(
        self,
        planner_llm: Union[str, Dict[str, Any], Type[AbstractClient], AbstractClient],
        catalog: Sequence[ToolCatalogEntry],
        *,
        delegate_safe_tools: Optional[Sequence[str]] = None,
        delegate_max_tools: int = 5,
    ) -> None:
        """Resolve the planner client and bind the tool catalog.

        Args:
            planner_llm: See :func:`resolve_planner_client`.
            catalog: The allowlist-scoped catalog (TASK-2182's
                ``build_catalog``) embedded in every prompt.
            delegate_safe_tools: Tool names safe for delegate nodes. ``None``
                disables delegate rules and leaves prompts unchanged.
            delegate_max_tools: Maximum tools a delegate node may choose from.
        """
        self.client = resolve_planner_client(planner_llm)
        self.catalog: List[ToolCatalogEntry] = list(catalog)
        self._delegate_safe_tools = delegate_safe_tools
        self._delegate_max_tools = delegate_max_tools
        self.logger = logging.getLogger(f"{__name__}.PlanPlanner")

    async def author(self, objective: str) -> ExecutionPlan:
        """Author a plan for ``objective`` in one LLM call.

        Args:
            objective: The natural-language objective to plan for.

        Returns:
            The parsed :class:`ExecutionPlan` (not yet validated against a
            live ``ToolManager`` — the caller runs ``validate_plan``).

        Raises:
            PlanAuthoringError: If the response is not valid JSON, or does
                not validate as an ``ExecutionPlan``.
        """
        self.logger.info(
            "Authoring plan: objective_len=%d catalog_size=%d",
            len(objective),
            len(self.catalog),
        )
        response_text = await self._call(self._authoring_prompt(objective))
        plan = self._parse_plan(response_text)
        self.logger.info("Authoring round produced plan %r", plan.name)
        return plan

    async def repair(self, plan_json: Dict[str, Any], report: ValidationReport) -> ExecutionPlan:
        """Re-prompt once with ``report``'s text embedded verbatim.

        Args:
            plan_json: The invalid plan's JSON document.
            report: The validation failure to repair from.

        Returns:
            The corrected :class:`ExecutionPlan`.

        Raises:
            PlanAuthoringError: If the repaired response still fails to
                parse/validate.
        """
        self.logger.info("Repairing plan: %d issue(s)", len(report.issues))
        response_text = await self._call(self._repair_prompt(plan_json, report))
        plan = self._parse_plan(response_text)
        self.logger.info("Repair round produced plan %r", plan.name)
        return plan

    async def replan(
        self, plan: ExecutionPlan, manifest: ExecutionManifest, *, eligible_node_ids: FrozenSet[str]
    ) -> PlanDelta:
        """Make one planner call for replacements only; raise on malformed output.

        Args:
            plan: The original, previously-accepted plan.
            manifest: The failed run's bounded manifest (per-node statuses/errors only).
            eligible_node_ids: Node ids the planner is allowed to replace.

        Returns:
            The parsed :class:`PlanDelta`, restricted to ``eligible_node_ids``.

        Raises:
            PlanAuthoringError: If the response is not valid JSON, does not validate
                as a ``PlanDelta``, or names a non-eligible node id.
        """
        self.logger.info("Replanning %r: %d eligible node(s)", plan.name, len(eligible_node_ids))
        text = await self._call(self._delta_prompt(plan, manifest, eligible_node_ids))
        return self._parse_delta(text, eligible_node_ids)

    async def repair_delta(
        self,
        delta_json: Dict[str, Any],
        report: ValidationReport,
        *,
        plan: ExecutionPlan,
        eligible_node_ids: FrozenSet[str],
    ) -> PlanDelta:
        """Make one structural correction call, retaining runtime delta restrictions.

        Args:
            delta_json: The invalid delta's JSON document.
            report: The validation failure to repair from.
            plan: The original, previously-accepted plan.
            eligible_node_ids: Node ids the planner is allowed to replace.

        Returns:
            The corrected :class:`PlanDelta`, restricted to ``eligible_node_ids``.

        Raises:
            PlanAuthoringError: If the corrected response still fails to parse/validate.
        """
        self.logger.info("Correcting delta for %r: %d issue(s)", plan.name, len(report.issues))
        text = await self._call(self._delta_repair_prompt(plan, delta_json, report, eligible_node_ids))
        return self._parse_delta(text, eligible_node_ids)

    def _delta_prompt(self, plan: ExecutionPlan, manifest: ExecutionManifest, eligible: FrozenSet[str]) -> str:
        return (
            f"{_DELTA_RULES}\n\nTool catalog:\n{self._render_catalog()}\n\n"
            f"PlanDelta JSON Schema:\n{json.dumps(PlanDelta.model_json_schema())}\n\n"
            f"Original plan:\n{json.dumps(plan.model_dump(mode='json'))}\n\n"
            f"Eligible node ids: {sorted(eligible)}\n\nFailures:\n{self._render_failures(manifest)}\n\n"
            "Respond with ONLY the PlanDelta JSON document — no prose, no markdown code fences."
        )

    def _delta_repair_prompt(
        self,
        plan: ExecutionPlan,
        delta_json: Dict[str, Any],
        report: ValidationReport,
        eligible: FrozenSet[str],
    ) -> str:
        return (
            f"{_DELTA_RULES}\n\nTool catalog:\n{self._render_catalog()}\n\n"
            f"PlanDelta JSON Schema:\n{json.dumps(PlanDelta.model_json_schema())}\n\n"
            f"Original plan:\n{json.dumps(plan.model_dump(mode='json'))}\n\n"
            f"Eligible node ids: {sorted(eligible)}\n\n"
            f"The following delta failed validation:\n{json.dumps(delta_json)}\n\n"
            f"Validation report:\n{report}\n\n"
            "Correct the delta, keeping the same eligible node ids and validation rules, and "
            "respond with ONLY the corrected PlanDelta JSON document — no prose, no markdown "
            "code fences."
        )

    def _render_failures(self, manifest: ExecutionManifest) -> str:
        """Bounded per-node failure summary — statuses and truncated messages, never bodies."""
        lines = [
            f"- {ref.node_id}: {ref.status}" + (f" — {ref.errors[0][:300]}" if ref.errors else "")
            for ref in manifest.artifacts
            if ref.status != "ok"
        ]
        return "\n".join(lines[:20]) or "(no per-node failures recorded)"

    def _parse_delta(self, response_text: str, eligible: FrozenSet[str]) -> PlanDelta:
        """Parse+validate one planner response into a ``PlanDelta`` restricted to ``eligible``."""
        text = _extract_json_text(response_text)
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanAuthoringError(
                f"Planner delta was not valid JSON: {exc}. " f"Response started with: {response_text[:200]!r}"
            ) from exc
        try:
            delta = PlanDelta.model_validate(document)
        except ValidationError as exc:
            raise PlanAuthoringError(f"Planner delta failed PlanDelta validation: {exc}") from exc
        stray = {node.id for node in delta.nodes} - eligible
        if stray:
            raise PlanAuthoringError(f"Planner delta names non-eligible node ids: {sorted(stray)}")
        return delta

    # ── LLM call ─────────────────────────────────────────────────────────

    async def _call(self, prompt: str) -> str:
        """Make exactly one call to the resolved client and return its text."""
        async with self.client as entered:
            response = await entered.ask(
                prompt=prompt,
                model=getattr(entered, "model", None),
                temperature=0.0,
            )
        return _response_text(response)

    # ── Prompt construction ──────────────────────────────────────────────

    def _rules(self) -> str:
        """Planning rules, plus delegate rules when delegates are enabled."""
        if self._delegate_safe_tools is None:
            return _PLANNING_RULES
        safe_tools = ", ".join(sorted(self._delegate_safe_tools)) or "(none)"
        delegate_rules = _DELEGATE_RULES.format(
            max_tools=self._delegate_max_tools,
            safe_tools=safe_tools,
        )
        return f"{_PLANNING_RULES}\n\n{delegate_rules}"

    def _authoring_prompt(self, objective: str) -> str:
        return (
            f"{self._rules()}\n\n"
            f"Tool catalog:\n{self._render_catalog()}\n\n"
            f"ExecutionPlan JSON Schema:\n{json.dumps(ExecutionPlan.model_json_schema())}\n\n"
            f"Objective: {objective}\n\n"
            "Respond with ONLY the ExecutionPlan JSON document — no prose, "
            "no markdown code fences."
        )

    def _repair_prompt(self, plan_json: Dict[str, Any], report: ValidationReport) -> str:
        return (
            f"{self._rules()}\n\n"
            f"Tool catalog:\n{self._render_catalog()}\n\n"
            f"ExecutionPlan JSON Schema:\n{json.dumps(ExecutionPlan.model_json_schema())}\n\n"
            f"The following plan failed validation:\n{json.dumps(plan_json)}\n\n"
            f"Validation report:\n{report}\n\n"
            "Correct the plan and respond with ONLY the corrected "
            "ExecutionPlan JSON document — no prose, no markdown code fences."
        )

    def _render_catalog(self) -> str:
        if not self.catalog:
            return "(no tools in catalog)"
        lines = []
        for entry in self.catalog:
            args = ", ".join(f"{arg.name}:{arg.type}{'' if arg.required else '?'}" for arg in entry.args_summary)
            lines.append(f"- {entry.name}({args}): {entry.description}")
        return "\n".join(lines)

    # ── Response parsing ─────────────────────────────────────────────────

    def _parse_plan(self, response_text: str) -> ExecutionPlan:
        """Parse+validate one planner response into an ``ExecutionPlan``."""
        text = _extract_json_text(response_text)
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanAuthoringError(
                f"Planner response was not valid JSON: {exc}. " f"Response started with: {response_text[:200]!r}"
            ) from exc
        try:
            return ExecutionPlan.model_validate(document)
        except ValidationError as exc:
            raise PlanAuthoringError(f"Planner response failed ExecutionPlan validation: {exc}") from exc


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
