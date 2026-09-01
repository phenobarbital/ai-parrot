"""IdeationNode — natural language → committed SDD document (FEAT-412).

Implements the normative Open-Questions HITL round-trip of spec §2. This is
the node that makes the dev-flow *interactive*: it turns a
:class:`DevRequestBrief` into a committed ``sdd/proposals/<slug>.*.md`` by
dispatching the ``sdd-ideation`` subagent, and resolves the document's Open
Questions with the human through ``open_questions`` gates before handing a
:class:`FeatureBrief` to the (reused) ``PlannerNode``.

Sequence::

    1. mode  = "brainstorm" (new_feature) | "proposal" (enhancement)
    2. dispatch sdd-ideation           → IdeationOutput
    3. while output.open_questions and rounds_used < DEV_FLOW_IDEATION_MAX_ROUNDS:
           ONE gate carrying ALL of this round's questions
           await wait_gate  →  approved ? re-dispatch with answers : raise
    4. committed is False  → raise (the planner's worktree would not see it)
    5. publish ctx["feature_brief"] = FeatureBrief(...) and return it

Design notes:

* **Gate expiry is fail-closed** (``on_expiry="fail"``): silence is not
  consent for spec decisions, so an expired gate reaches ``wait_gate`` with
  status ``"expired"`` and raises into ``failure_handler``.
* **Rounds are bounded.** Questions still ``[ ]`` when the budget is spent
  stay in the document and flow into the spec's §8 via the planner — they do
  NOT block the run.
* **"Re-dispatch" is a NEW dispatch**, not a dispatcher-side resume: the
  payload carries the prior ``document_path`` plus the ``answers`` mapping,
  and the subagent resumes/extends the document in place.
* **No ``session_host``** in shared state → the node logs a warning and runs
  gatelessly (autonomous mode), mirroring ``DevelopmentNode``'s plan-gate
  fallback. Any open questions are simply left in the document.
* Park/resume (``DEV_LOOP_GATE_PARK``) is entirely runner-side: waiting here
  is a plain ``await``, which is what lets a parked run release its
  concurrency slot while a human takes hours to answer.
* The subagent is dispatched via ``system_prompt_override``, NOT
  ``profile.subagent``: the latter resolves prompts through ``dev_loop``'s
  own loader, which deliberately does not know the dev-flow-owned
  ``sdd-ideation`` prompt (spec §3 Module 3 — the dev_flow package owns its
  prompts). This keeps shared ``dev_loop`` code untouched.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_flow._subagent_defs import load_subagent_definition
from parrot.flows.dev_flow.complementary_research import (
    ComplementaryResearchCoordinator,
)
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow.research_partner import ComplementaryFindings
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher
from parrot.flows.dev_loop.mcp_profiles import (
    WIKI_MCP_TOOLS,
    derive_mcp_tool_names,
    resolve_wikitoolkit_command,
    wikitoolkit_mcp_entry,
)
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile, FeatureBrief
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch

# Mode ⇄ intent mapping (spec §2 / §8): the intent is user-selected, and it
# alone decides which document the subagent writes.
_MODE_FOR_KIND: dict[str, str] = {
    "new_feature": "brainstorm",
    "enhancement": "proposal",
}


# Backward-compat aliases: these lived here (private) before moving to the
# shared ``parrot.flows.dev_loop.mcp_profiles`` module so ``ResearchNode``
# could reuse them. Kept so existing imports/monkeypatches keep working.
_WIKI_MCP_TOOLS = WIKI_MCP_TOOLS
_resolve_wikitoolkit_command = resolve_wikitoolkit_command


def _slugify(title: str) -> str:
    """Kebab-case a title, mirroring the ``sdd-ideation`` prompt's own Step 1
    algorithm ("lowercase, non-alphanumerics -> single hyphens, no leading
    or trailing hyphen") so the coordinator's provisional
    ``sdd/proposals/<slug>.research.md`` name matches the document the
    subagent independently derives from the SAME title, without waiting
    for the subagent's own dispatch to report it (FEAT-482 Module 5 — the
    coordinator must run BEFORE the first dispatch, so the real
    ``IdeationOutput.slug`` is not available yet).
    """
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


class _IdeationBrief(BaseModel):
    """Local dispatch payload for the ``sdd-ideation`` subagent.

    Not a shared model: like ``planner.py``'s ``_PlannerBrief``, this exists
    only for the lifetime of a single dispatch, so it lives next to its
    consumer instead of growing the shared models module. Field names match
    the input table documented in the ``sdd-ideation`` prompt.
    """

    mode: Literal["brainstorm", "proposal"]
    title: str
    description: str
    context: str = ""
    graph_context: str = ""
    # Prior-round answers; empty on the first dispatch.
    answers: dict[str, str] = Field(default_factory=dict)
    # Set on resume rounds so the subagent extends the same document.
    document_path: str = ""
    round: int = 1
    # FEAT-482 Module 5: the complementary research partner's findings,
    # rendered markdown (already truncation-bounded) and its
    # `.research.md` sidecar path. Populated on round 1 only — resume
    # rounds pass both empty (the findings are already folded into the
    # document by then). Both default to "" so a run with no coordinator
    # injected, or with the research-partner seat disabled/degraded,
    # carries an inert, empty partner section.
    partner_findings: str = ""
    partner_findings_path: str = ""


@register_dev_loop_node("dev_flow.ideation")
class IdeationNode(DevLoopNode):
    """Turns a natural-language request into a committed SDD document.

    Args:
        dispatcher: A :class:`ClaudeCodeDispatcher` shared by every node in
            the flow.
        wiki_search: Optional :class:`DevLoopWikiSearch` used to inject
            ranked repo context into the dispatch. Best-effort — a ``None``
            search, or a search that finds nothing, simply yields no context.
        ideation_max_rounds: Override for ``conf.DEV_FLOW_IDEATION_MAX_ROUNDS``.
            ``None`` (default) reads the conf key at execute time.
        model: FEAT-486 — model for this (research-primary) seat, replacing
            the ``claude-sonnet-4-6`` literal this node used to hardcode in
            its dispatch profile. ``None`` (default) reads
            ``conf.DEV_FLOW_IDEATION_MODEL`` at dispatch time, itself
            defaulting to ``claude-opus-5``. Normally supplied by
            ``DevFlowModelPlan.research_primary`` through the factory.
        coordinator: Optional :class:`ComplementaryResearchCoordinator`
            (FEAT-482). ``None`` (default) means no complementary research
            partner ever runs — the dispatch payload's partner fields stay
            empty, matching pre-feature behavior exactly. When provided,
            it is called on round 1 only; it never raises (it owns its own
            degradation), so a disabled/degraded/timed-out partner simply
            yields empty partner fields too.
        extra_mcp_servers: Optional extra MCP server configs (same shape as
            ``ClaudeCodeDispatchProfile.mcp_servers``) merged UNDER the
            built-in ``wikitoolkit`` entry — on a key collision the
            built-in wins (with a warning). Use this to expose the
            FEAT-485 ``parrot mcp-local <toolkit>`` servers to the
            research-primary seat. ``None`` (default) keeps the dispatch
            profile byte-identical to pre-seam behavior.
        extra_mcp_tools: Optional explicit ``mcp__...`` allow rules for the
            extra servers, appended to ``allowed_tools``. ``None``
            (default) derives one server-level ``mcp__<name>`` rule per
            extra server. Ignored when ``extra_mcp_servers`` is unset.
        name: Node id, default ``"ideation"``.
    """

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        wiki_search: DevLoopWikiSearch | None = None,
        ideation_max_rounds: int | None = None,
        model: str | None = None,
        coordinator: ComplementaryResearchCoordinator | None = None,
        extra_mcp_servers: dict[str, Any] | None = None,
        extra_mcp_tools: list[str] | None = None,
        name: str = "ideation",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_wiki_search", wiki_search)
        object.__setattr__(self, "_max_rounds", ideation_max_rounds)
        # FEAT-486: the research-primary seat's model. `None` (default)
        # resolves `conf.DEV_FLOW_IDEATION_MODEL` at dispatch time — read
        # late, not at import, so a test (or a per-deployment env change)
        # can monkeypatch it, matching how `_max_rounds` treats
        # DEV_FLOW_IDEATION_MAX_ROUNDS.
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_coordinator", coordinator)
        object.__setattr__(self, "_extra_mcp_servers", extra_mcp_servers)
        object.__setattr__(self, "_extra_mcp_tools", extra_mcp_tools)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: FlowContext | dict[str, Any],
        deps: DependencyResults | None = None,
        **kwargs: Any,
    ) -> FeatureBrief:
        """Run the ideation phase and return the resulting :class:`FeatureBrief`.

        Reads ``dev_brief`` / ``run_id`` / ``session_host`` from the shared
        state; writes ``ideation_output`` and ``feature_brief``.

        Args:
            ctx: Flow context (``FlowContext`` or plain dict in tests).
            deps: Dependency results (unused — routing is edge-driven).
            **kwargs: Extra execution context (ignored).

        Returns:
            The :class:`FeatureBrief` pointing at the committed document,
            also published to ``ctx["feature_brief"]`` — the exact key
            ``PlannerNode`` reads.

        Raises:
            ValueError: ``ctx["dev_brief"]`` is missing or is not a
                natural-language :class:`DevRequestBrief` (this node is only
                reachable for the ``enhancement``/``new_feature`` intents).
            RuntimeError: An Open-Questions gate was rejected or expired, the
                subagent reported ``committed=False``, or the document it
                reported cannot be read.
        """
        shared = self.shared_state(ctx)
        brief = self._load_request_brief(shared)
        mode = _MODE_FOR_KIND[brief.kind]

        # FEAT-482: the complementary research partner (if any) runs
        # concurrently with the existing best-effort wiki-context build —
        # both feed the FIRST dispatch only, neither delays the other.
        graph_context, partner_findings = await asyncio.gather(
            self._build_wiki_context(brief),
            self._run_coordinator(brief=brief, shared=shared),
        )
        max_rounds = self._resolve_max_rounds()

        self.logger.info(
            "Ideation starting: kind=%s -> mode=%s, title=%s, max_rounds=%d",
            brief.kind,
            mode,
            brief.title,
            max_rounds,
        )

        output = await self._dispatch(
            shared=shared,
            brief=brief,
            mode=mode,
            graph_context=graph_context,
            answers={},
            document_path="",
            round_=1,
            partner_findings=partner_findings.rendered if partner_findings else "",
            partner_findings_path=partner_findings.document_path if partner_findings else "",
        )

        host = shared.get("session_host")
        if output.open_questions and host is None:
            self.logger.warning(
                "IdeationNode: %d open question(s) but no session_host in "
                "shared state (autonomous construction) — proceeding WITHOUT "
                "an open_questions gate; the questions stay in %s and are "
                "carried into the spec by the planner.",
                len(output.open_questions),
                output.document_path,
            )

        rounds_used = 0
        while output.open_questions and host is not None and rounds_used < max_rounds:
            rounds_used += 1
            answers = await self._run_question_round(
                host=host,
                output=output,
                round_=rounds_used,
                max_rounds=max_rounds,
            )
            output = await self._dispatch(
                shared=shared,
                brief=brief,
                mode=mode,
                graph_context=graph_context,
                answers=answers,
                document_path=output.document_path,
                round_=rounds_used + 1,
                # Round 1 only (spec §1 Non-Goals, D8): the partner's
                # findings are already folded into the document by now.
                partner_findings="",
                partner_findings_path="",
            )

        if output.open_questions:
            self.logger.info(
                "Ideation finished with %d unresolved question(s) after %d "
                "round(s) — they remain '[ ]' in %s and flow into the spec's "
                "§8 via the planner (not a failure).",
                len(output.open_questions),
                rounds_used,
                output.document_path,
            )

        # Fail fast: sdd-planner creates its worktree from base_branch HEAD,
        # so an uncommitted document is invisible there (spec §7).
        if not output.committed:
            raise RuntimeError(
                "sdd-ideation did not commit "
                f"{output.document_path!r} (committed=False): "
                f"{output.summary or 'no summary reported'}. The planner's "
                "worktree would not see the document, so the run stops here."
            )

        document_path = self._resolve_document_path(output.document_path)
        feature_brief = FeatureBrief(
            document_path=document_path,
            document_kind=output.document_kind,
            # Passthrough — dev-flow never creates a Jira issue, and an
            # explicit pool/panel from the intake must survive ideation.
            jira_issue_key=brief.jira_issue_key,
            dev_agents=brief.dev_agents,
            judge_panel=brief.judge_panel,
        )

        shared["ideation_output"] = output
        shared["feature_brief"] = feature_brief
        self.logger.info(
            "Ideation complete: %s (kind=%s, resumed_existing=%s, rounds=%d)",
            document_path,
            output.document_kind,
            output.resumed_existing,
            rounds_used,
        )
        return feature_brief

    # ------------------------------------------------------------------
    # Internal — input
    # ------------------------------------------------------------------

    def _load_request_brief(self, shared: dict[str, Any]) -> DevRequestBrief:
        """Return the natural-language brief this node operates on.

        Args:
            shared: The flow's shared state.

        Returns:
            The :class:`DevRequestBrief` published by ``DevIntakeNode``.

        Raises:
            ValueError: The brief is absent, or is not a
                :class:`DevRequestBrief` — a ``feature`` intake routes
                straight to the planner and must never reach this node.
        """
        brief = shared.get("dev_brief")
        if isinstance(brief, DevRequestBrief):
            return brief
        raise ValueError(
            "IdeationNode requires ctx['dev_brief'] to be a DevRequestBrief "
            f"(enhancement/new_feature); got {type(brief).__name__}. A "
            "'feature' intake routes directly to the planner."
        )

    def _resolve_max_rounds(self) -> int:
        """Resolve the HITL round budget (constructor override > conf key)."""
        if self._max_rounds is not None:
            return max(0, int(self._max_rounds))
        return max(0, int(getattr(conf, "DEV_FLOW_IDEATION_MAX_ROUNDS", 2)))

    def _resolve_model(self) -> str:
        """Resolve this seat's model (constructor override > conf key).

        FEAT-486: same late-binding shape as :meth:`_resolve_max_rounds` —
        the conf key is read at dispatch time, not import time, so a
        deployment (or a test) can change it without rebuilding the flow.
        A blank override falls through to the conf key rather than
        dispatching with an empty model id.

        Returns:
            The model id for the ideation dispatch profile.
        """
        if self._model:
            return str(self._model)
        return str(getattr(conf, "DEV_FLOW_IDEATION_MODEL", "claude-opus-5") or "claude-opus-5")

    async def _build_wiki_context(self, brief: DevRequestBrief) -> str:
        """Best-effort ranked repo context for the dispatch.

        Args:
            brief: The natural-language request.

        Returns:
            Markdown context text, or ``""`` when no wiki is wired, nothing
            relevant was found, or the search degraded.
        """
        if self._wiki_search is None:
            return ""
        query = f"{brief.title} {brief.description}"
        try:
            context = await self._wiki_search.build_research_context(query)
        except Exception as exc:  # noqa: BLE001 — context injection is best-effort
            self.logger.debug("Wiki context degraded: %s", exc)
            return ""
        return context or ""

    async def _run_coordinator(self, *, brief: DevRequestBrief, shared: dict[str, Any]) -> ComplementaryFindings | None:
        """Run the complementary research partner, or skip if not wired.

        FEAT-482: no defensive try/except here — the coordinator already
        owns degradation end-to-end (spec §3 Module 4) and is contracted
        to never raise; wrapping it again would only risk masking a
        genuine bug in that contract.

        Args:
            brief: The natural-language request driving this ideation run.
            shared: The flow's shared state (supplies ``run_id`` and the
                optional ``session_host``).

        Returns:
            ``ComplementaryFindings`` on success, or ``None`` when no
            coordinator is wired, the seat is disabled, or it degraded.
        """
        if self._coordinator is None:
            return None
        slug = _slugify(brief.title)
        question = f"{brief.title}\n\n{brief.description}".strip()
        return await self._coordinator.research(
            brief=brief,
            question=question,
            cwd=self._dispatch_cwd(),
            slug=slug,
            run_id=shared.get("run_id", ""),
            node_id=self.name,
            session_host=shared.get("session_host"),
        )

    # ------------------------------------------------------------------
    # Internal — dispatch
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        *,
        shared: dict[str, Any],
        brief: DevRequestBrief,
        mode: str,
        graph_context: str,
        answers: dict[str, str],
        document_path: str,
        round_: int,
        partner_findings: str = "",
        partner_findings_path: str = "",
    ) -> IdeationOutput:
        """Dispatch ``sdd-ideation`` once and validate its final JSON.

        Args:
            shared: The flow's shared state (supplies ``run_id`` and the
                optional ``session_host`` for dispatch telemetry folding).
            brief: The natural-language request.
            mode: ``"brainstorm"`` or ``"proposal"``.
            graph_context: Optional pre-fetched repo context.
            answers: Prior-round answers (empty on round 1).
            document_path: The document to resume (empty on round 1).
            round_: 1-based round counter, for the subagent's own logging.
            partner_findings: FEAT-482 — the complementary research
                partner's rendered findings. Non-empty only on round 1's
                call; resume rounds must pass ``""``.
            partner_findings_path: FEAT-482 — the partner's
                ``.research.md`` sidecar path, or ``""``.

        Returns:
            The validated :class:`IdeationOutput`.
        """
        dispatch_brief = _IdeationBrief(
            mode=mode,  # type: ignore[arg-type]
            title=brief.title,
            description=brief.description,
            context=brief.context,
            graph_context=graph_context,
            answers=dict(answers),
            document_path=document_path,
            round=round_,
            partner_findings=partner_findings,
            partner_findings_path=partner_findings_path,
        )
        # Extra caller-supplied servers (e.g. FEAT-485 `parrot mcp-local`
        # toolkits) merge UNDER the built-in wikitoolkit entry: with no
        # extras the dict is exactly {"wikitoolkit": ...}, byte-identical
        # to pre-seam behavior.
        mcp_servers: dict[str, Any] = dict(self._extra_mcp_servers or {})
        if "wikitoolkit" in mcp_servers:
            self.logger.warning(
                "extra_mcp_servers supplied a 'wikitoolkit' entry; the built-in one takes precedence."
            )
        mcp_servers["wikitoolkit"] = wikitoolkit_mcp_entry()
        allowed_tools = ["Read", "Grep", "Glob", "Bash", "Write", "Edit", *WIKI_MCP_TOOLS]
        if self._extra_mcp_servers:
            allowed_tools.extend(
                self._extra_mcp_tools
                if self._extra_mcp_tools is not None
                else derive_mcp_tool_names(self._extra_mcp_servers)
            )
        profile = ClaudeCodeDispatchProfile(
            # NOT profile.subagent: that path resolves the prompt through
            # dev_loop's loader, which does not know the dev_flow-owned
            # sdd-ideation prompt. Passing the body as a system prompt keeps
            # shared dev_loop code untouched (see module docstring).
            subagent=None,
            system_prompt_override=load_subagent_definition("sdd-ideation"),
            permission_mode="acceptEdits",
            # Read/Grep/Glob to verify Code Context claims, Write/Edit for
            # the document itself, Bash for the explicit-path git commit.
            # FEAT-482 Module 6 (§8 Q11): plus the three read-only wiki
            # graph-search tools — the primary seat does the deepest
            # research in the pipeline and benefits most from it.
            allowed_tools=allowed_tools,
            # The dispatch is write-capable AND runs at the base checkout
            # (see _dispatch_cwd), so it needs the dispatcher's narrow
            # PROJECT_ROOT waiver of the WORKTREE_BASE_PATH confinement —
            # ideation predates the feature worktree by construction.
            allow_project_root_cwd=True,
            # FEAT-486 supersedes FEAT-482's direct
            # `conf.DEV_FLOW_IDEATION_MODEL` read here: _resolve_model()
            # falls back to that SAME key, but first honours an explicit
            # constructor argument (i.e. DevFlowModelPlan.research_primary).
            model=self._resolve_model(),
            # FEAT-482 Module 6: strict_mcp_config stays at its True
            # default (NOT overridden here) — the field's own docstring
            # records that flipping it makes non-interactive runs exit
            # with an empty error result. Passing the servers explicitly
            # is the correct way to reach them under that isolation.
            mcp_servers=mcp_servers,
        )
        return await self._dispatcher.dispatch(
            brief=dispatch_brief,
            profile=profile,
            output_model=IdeationOutput,
            run_id=shared.get("run_id", ""),
            node_id=self.name,
            # The document is committed to base_branch, so the dispatch runs
            # against the base checkout — the feature worktree does not exist
            # yet at ideation time (sdd-planner creates it later).
            cwd=self._dispatch_cwd(),
            session_host=shared.get("session_host"),
        )

    @staticmethod
    def _dispatch_cwd() -> str:
        """Absolute working directory for the ideation dispatch."""
        return str(Path(conf.PROJECT_ROOT).resolve())

    # ------------------------------------------------------------------
    # Internal — the HITL round
    # ------------------------------------------------------------------

    async def _run_question_round(
        self,
        *,
        host: Any,
        output: IdeationOutput,
        round_: int,
        max_rounds: int,
    ) -> dict[str, str]:
        """Open ONE gate carrying all of this round's questions and await it.

        Args:
            host: The run's ``SessionHost``.
            output: The subagent output whose ``open_questions`` to ask.
            round_: 1-based index of this HITL round.
            max_rounds: The round budget, surfaced in the gate instructions.

        Returns:
            The human's ``question -> answer`` mapping (possibly partial —
            unanswered questions stay open in the document).

        Raises:
            RuntimeError: The gate was rejected (the user aborted the
                ideation) or expired (fail-closed policy).
        """
        questions: list[str] = list(output.open_questions)
        # The resolved document path goes in the TITLE so the user can spot —
        # and reject — an unintended resume of a slug-colliding document
        # (spec §7 Known Risks).
        title = f"Open questions — {output.document_path}"
        instructions = (
            f"Round {round_} of {max_rounds} for "
            f"{output.document_path} "
            f"({'resumed an existing document' if output.resumed_existing else 'new document'}).\n"
            f"{output.summary}\n\n"
            "Answer what you can — partial answers are fine, unanswered "
            "questions stay open in the document. Rejecting this gate aborts "
            "the ideation."
        )
        gate_id, _ = host.open_gate(
            kind="open_questions",
            node_id=self.name,
            title=title,
            instructions=instructions,
            questions=questions,
            ttl_seconds=int(getattr(conf, "DEV_FLOW_GATE_TTL_QUESTIONS", 86400)),
            # Fail-closed: silence is not consent for spec decisions.
            on_expiry="fail",
        )
        self.logger.info(
            "Ideation round %d/%d: opened open_questions gate %s with %d " "question(s) for %s",
            round_,
            max_rounds,
            gate_id,
            len(questions),
            output.document_path,
        )

        gate = await host.wait_gate(gate_id)
        if gate.status != "approved":
            raise RuntimeError(
                f"open_questions gate {gate.status} by "
                f"{gate.resolved_by or 'ttl'} — ideation aborted for "
                f"{output.document_path}"
            )

        answers = dict(gate.answers or {})
        self.logger.info(
            "Ideation round %d/%d: %d of %d question(s) answered by %s",
            round_,
            max_rounds,
            len(answers),
            len(questions),
            gate.resolved_by or "unknown",
        )
        return answers

    # ------------------------------------------------------------------
    # Internal — output
    # ------------------------------------------------------------------

    def _resolve_document_path(self, raw: str) -> str:
        """Resolve the subagent's reported document path to a readable file.

        ``FeatureBrief`` validates ``document_path`` readability eagerly, and
        the subagent reports a repo-relative path (``sdd/proposals/...``). The
        hosting process' CWD is not guaranteed to be the repo root, so try the
        path as given first, then anchored at the project root — and raise a
        node-level error (rather than letting a confusing ``ValidationError``
        escape) when neither resolves.

        Args:
            raw: ``IdeationOutput.document_path``.

        Returns:
            A path string that resolves to a readable file.

        Raises:
            RuntimeError: Neither candidate is a readable file — i.e. the
                subagent reported ``committed=True`` for a document that
                is not there.
        """
        candidates = [Path(raw)]
        if not Path(raw).is_absolute():
            candidates.append(Path(conf.PROJECT_ROOT) / raw)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        raise RuntimeError(
            f"sdd-ideation reported committed=True for {raw!r}, but no "
            f"readable document was found (tried: "
            f"{', '.join(str(c) for c in candidates)})."
        )


__all__ = ["IdeationNode"]
