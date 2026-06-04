"""FlowExecutor — orchestration engine for ScrapingFlow execution.

Ties together the FEAT-222 layers: topological ordering (:class:`ScrapingFlow`),
template binding (:class:`TemplatePlan`), session/page management
(:class:`SessionManager` + :class:`PageDriver`), per-node execution
(``execute_plan_steps``), data-dependency input resolution, fan-out, per-node
error policies, and checkpoint persistence/resumption (FEAT-222, Module 8).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
from bs4 import BeautifulSoup

from .base_registry import BasePlanRegistry
from .drivers.page_driver import PageDriver
from .executor import execute_plan_steps
from .flow_models import FlowNode, FlowResult, ScrapingFlow
from .models import ScrapingResult
from .plan import ScrapingPlan
from .plan_io import load_plan_from_disk
from .session_manager import SessionManager
from .template_plan import TemplatePlan
from .toolkit_models import DriverConfig

# Parses a field reference like ``field``, ``field[3]``, or ``field[*]``.
_FIELD_REF_RE = re.compile(r"^(\w+)(?:\[(\d+|\*)\])?$")

# Sentinel used by input resolution to mark a fan-out (``[*]``) reference.
_FANOUT = object()


class FlowExecutor:
    """Orchestrate end-to-end execution of a :class:`ScrapingFlow`.

    Args:
        browser: A live Playwright ``Browser`` instance.
        registry: Optional plan registry used to resolve ``plan_ref`` values
            that are stored ``ScrapingPlan`` names/fingerprints.
        config: Driver configuration forwarded to ``execute_plan_steps``.
        concurrency: Maximum concurrent fan-out executions.
        checkpoint_dir: Directory for per-flow checkpoint files. When
            ``None``, checkpointing/resume are disabled.
        logger: Optional logger.
        templates: Optional mapping of ``template_name -> TemplatePlan`` used
            to resolve and bind ``plan_ref`` values. (The dedicated
            ``TemplatePlanRegistry`` is deferred per the spec; this mapping is
            the template source in the meantime.)
    """

    def __init__(
        self,
        browser: Any,
        registry: Optional[BasePlanRegistry] = None,
        config: Optional[DriverConfig] = None,
        concurrency: int = 1,
        checkpoint_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
        templates: Optional[Dict[str, TemplatePlan]] = None,
    ) -> None:
        self._browser = browser
        self._registry = registry
        self._config = config
        self._concurrency = max(1, concurrency)
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        self.logger = logger or logging.getLogger(__name__)
        self._templates = templates or {}

    # ── Input resolution ─────────────────────────────────────────────

    @staticmethod
    def _resolve_input(
        ref: str, node_results: Dict[str, ScrapingResult]
    ) -> Tuple[Any, bool]:
        """Resolve a single ``"node_id.field[...]"`` reference.

        Returns:
            ``(value, is_fanout)`` — ``is_fanout`` is ``True`` for a ``[*]``
            reference (the value is then the full list to fan out over).

        Raises:
            ValueError: For malformed references or unknown source nodes.
        """
        node_id, _, field_ref = ref.partition(".")
        if not field_ref:
            raise ValueError(f"Invalid input reference (no field): '{ref}'")

        if node_id not in node_results:
            raise ValueError(
                f"Input reference '{ref}' points to node '{node_id}' which has "
                "no recorded result"
            )
        source = node_results[node_id]

        match = _FIELD_REF_RE.match(field_ref)
        if not match:
            raise ValueError(f"Malformed field reference: '{field_ref}' in '{ref}'")

        field_name, index_token = match.group(1), match.group(2)
        base = source.extracted_data.get(field_name)

        if index_token is None:
            return base, False
        if index_token == "*":
            return (base if base is not None else []), True
        # Numeric index.
        idx = int(index_token)
        if not isinstance(base, list):
            raise ValueError(
                f"Reference '{ref}' uses an index but field '{field_name}' is "
                f"not a list"
            )
        return base[idx], False

    def _resolve_node_inputs(
        self, node: FlowNode, node_results: Dict[str, ScrapingResult]
    ) -> Tuple[Dict[str, Any], Optional[str], List[Any]]:
        """Resolve all of *node*'s inputs.

        Returns ``(resolved_params, fanout_key, fanout_items)``. When a
        ``[*]`` input is present, ``fanout_key`` names the parameter and
        ``fanout_items`` is the list to fan out over.
        """
        resolved: Dict[str, Any] = {}
        fanout_key: Optional[str] = None
        fanout_items: List[Any] = []

        for param, ref in node.inputs.items():
            value, is_fanout = self._resolve_input(ref, node_results)
            if is_fanout:
                if fanout_key is not None:
                    raise ValueError(
                        f"Node '{node.id}' declares more than one fan-out input"
                    )
                fanout_key = param
                fanout_items = value
            else:
                resolved[param] = value
        return resolved, fanout_key, fanout_items

    # ── Plan resolution ──────────────────────────────────────────────

    async def _resolve_plan(
        self, node: FlowNode, params: Dict[str, Any]
    ) -> ScrapingPlan:
        """Resolve *node*'s ``plan_ref`` into a concrete :class:`ScrapingPlan`.

        Prefers a registered :class:`TemplatePlan` (bound with *params*);
        falls back to a stored plan loaded from the registry.
        """
        if node.plan_ref in self._templates:
            return self._templates[node.plan_ref].bind(**params)

        if self._registry is not None:
            entry = self._registry.get_by_name(node.plan_ref)
            if entry is not None:
                return await load_plan_from_disk(
                    self._registry.plans_dir / entry.path
                )

        raise ValueError(
            f"Cannot resolve plan_ref '{node.plan_ref}' for node '{node.id}': "
            "not found in templates or registry"
        )

    # ── Node execution ───────────────────────────────────────────────

    async def _run_single(
        self, node: FlowNode, plan: ScrapingPlan, session: SessionManager
    ) -> Tuple[Optional[ScrapingResult], Optional[str]]:
        """Execute a single (non-fanned) node, honouring retry on a fresh page.

        Returns ``(result, error_message)``. ``error_message`` is ``None`` on
        success.
        """
        attempts = node.max_retries if node.on_error == "retry" else 1
        last_result: Optional[ScrapingResult] = None
        last_error: Optional[str] = None

        for attempt in range(1, attempts + 1):
            page = await session.new_page(node.session)
            driver = PageDriver(page)
            try:
                result = await execute_plan_steps(
                    driver, plan, config=self._config, base_url=plan.url
                )
            except Exception as exc:  # noqa: BLE001
                result = None
                last_error = str(exc)
                self.logger.error("Node '%s' raised: %s", node.id, exc)
            finally:
                try:
                    await driver.quit()
                except Exception:  # noqa: BLE001
                    pass

            if result is not None and result.success:
                return result, None

            last_result = result
            if result is not None:
                last_error = result.error_message or "step execution failed"
            if attempt < attempts:
                self.logger.warning(
                    "Retrying node '%s' (attempt %d/%d)", node.id, attempt + 1, attempts
                )

        return last_result, last_error or "node execution failed"

    async def _run_fanout(
        self,
        node: FlowNode,
        base_params: Dict[str, Any],
        fanout_key: str,
        items: List[Any],
        session: SessionManager,
    ) -> Tuple[Optional[ScrapingResult], Optional[str]]:
        """Execute a fan-out node once per item with bounded concurrency.

        Note: fan-out items of the same node share one session/BrowserContext;
        concurrent pages in a single context may race on cookies/storage. This
        is documented deferred debt (spec §Non-Goals) and is safe at the
        default ``concurrency=1``.
        """
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _bounded(item: Any) -> Tuple[Optional[ScrapingResult], Optional[str]]:
            async with semaphore:
                params = {**base_params, fanout_key: item}
                plan = await self._resolve_plan(node, params)
                return await self._run_single(node, plan, session)

        outcomes = await asyncio.gather(
            *[_bounded(it) for it in items], return_exceptions=True
        )

        sub_results: List[ScrapingResult] = []
        errors: List[str] = []
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                errors.append(str(outcome))
                continue
            result, err = outcome
            if err is None and result is not None:
                sub_results.append(result)
            else:
                errors.append(err or "fan-out item failed")

        aggregate = ScrapingResult(
            # No single URL represents a fan-out; leave empty rather than
            # misrepresenting the plan reference as a URL.
            url="",
            content="",
            bs_soup=BeautifulSoup("", "html.parser"),
            extracted_data={"items": [r.extracted_data for r in sub_results]},
            success=not errors,
            error_message="; ".join(errors) if errors else None,
        )
        return aggregate, (aggregate.error_message if errors else None)

    # ── Checkpointing ────────────────────────────────────────────────

    @staticmethod
    def _checkpoint_token(global_params: Dict[str, Any]) -> str:
        """Stable 8-char key identifying a run by its parameter set.

        Distinct parameter sets get distinct checkpoint files (so concurrent
        runs of the same flow with different params do not clobber each other),
        while an identical parameter set resolves deterministically — which is
        what ``resume_from`` relies on to locate the prior run.
        """
        blob = json.dumps(global_params, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]

    def _checkpoint_path(
        self, flow: ScrapingFlow, token: str
    ) -> Optional[Path]:
        """Return the checkpoint file path for *flow*/*token* (``None`` if off)."""
        if self._checkpoint_dir is None:
            return None
        return self._checkpoint_dir / f"{flow.name}.{token}.checkpoint.json"

    async def _write_checkpoint(
        self,
        flow: ScrapingFlow,
        token: str,
        node_results: Dict[str, ScrapingResult],
    ) -> Optional[str]:
        """Persist completed-node ``extracted_data``; return the checkpoint path.

        Only ``extracted_data`` is persisted (not the full ``ScrapingResult``),
        since ``bs_soup`` is not JSON-serializable and ``content`` is large.
        Nodes restored on resume therefore expose ``extracted_data`` only —
        ``content``/``metadata`` come back empty.
        """
        path = self._checkpoint_path(flow, token)
        if path is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            node_id: result.extracted_data
            for node_id, result in node_results.items()
        }
        async with aiofiles.open(path, "w") as f:
            await f.write(json.dumps(payload))
        return str(path)

    async def _load_checkpoint(
        self, flow: ScrapingFlow, token: str
    ) -> Dict[str, Any]:
        """Load a previously persisted checkpoint (empty dict if none)."""
        path = self._checkpoint_path(flow, token)
        if path is None or not path.exists():
            return {}
        async with aiofiles.open(path, "r") as f:
            return json.loads(await f.read())

    @staticmethod
    def _result_from_checkpoint(extracted_data: Dict[str, Any]) -> ScrapingResult:
        """Reconstruct a minimal ScrapingResult from checkpointed data."""
        return ScrapingResult(
            url="",
            content="",
            bs_soup=BeautifulSoup("", "html.parser"),
            extracted_data=extracted_data,
            success=True,
        )

    # ── Public API ───────────────────────────────────────────────────

    async def run(
        self,
        flow: ScrapingFlow,
        params: Optional[Dict[str, Any]] = None,
        resume_from: Optional[str] = None,
    ) -> FlowResult:
        """Execute *flow* end-to-end and return an aggregated :class:`FlowResult`.

        Args:
            flow: The flow to execute.
            params: Extra global parameters merged with ``flow.global_params``
                and passed to template binding.
            resume_from: If set, nodes before this node id are loaded from the
                checkpoint (treated as already completed) and execution begins
                at ``resume_from``.

        Returns:
            A ``FlowResult`` with per-node results and run metadata.
        """
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        order = flow.topological_order()
        global_params = {**flow.global_params, **(params or {})}
        checkpoint_token = self._checkpoint_token(global_params)

        # Session lifecycle is local to this run() invocation, so the same
        # FlowExecutor instance can drive multiple flows without cross-talk.
        session = SessionManager(self._browser)
        session.precompute_last_use(order)

        node_results: Dict[str, ScrapingResult] = {}
        skipped: set[str] = set()
        nodes_completed = 0
        flow_success = True
        flow_error: Optional[str] = None
        checkpoint_path: Optional[str] = None

        # ── Resume: pre-populate completed nodes from checkpoint ──────
        if resume_from is not None:
            checkpoint = await self._load_checkpoint(flow, checkpoint_token)
            for node in order:
                if node.id == resume_from:
                    break
                if node.id in checkpoint:
                    node_results[node.id] = self._result_from_checkpoint(
                        checkpoint[node.id]
                    )
                    nodes_completed += 1

        try:
            for node in order:
                # Skip nodes already satisfied by a resume checkpoint.
                if node.id in node_results:
                    continue

                # Cascade skips: if any input source was skipped, skip too.
                dep_sources = {
                    ref.partition(".")[0] for ref in node.inputs.values()
                }
                if dep_sources & skipped:
                    self.logger.info(
                        "Skipping node '%s' (depends on skipped node)", node.id
                    )
                    skipped.add(node.id)
                    continue

                # Resolve inputs (data dependencies).
                try:
                    resolved, fanout_key, fanout_items = self._resolve_node_inputs(
                        node, node_results
                    )
                except ValueError as exc:
                    flow_success = False
                    flow_error = str(exc)
                    self.logger.error("Input resolution failed: %s", exc)
                    break

                base_params = {**global_params, **resolved}

                # Execute (fan-out or single).
                if fanout_key is not None:
                    result, error = await self._run_fanout(
                        node, base_params, fanout_key, fanout_items, session
                    )
                else:
                    plan = await self._resolve_plan(node, base_params)
                    result, error = await self._run_single(node, plan, session)

                if error is None:
                    node_results[node.id] = result
                    nodes_completed += 1
                    checkpoint_path = await self._write_checkpoint(
                        flow, checkpoint_token, node_results
                    )
                    await session.close_if_last(node.session, node.id)
                    continue

                # ── Failure handling per node policy ──────────────────
                if node.on_error == "skip":
                    self.logger.warning(
                        "Node '%s' failed; skipping (on_error=skip): %s",
                        node.id, error,
                    )
                    skipped.add(node.id)
                    await session.close_if_last(node.session, node.id)
                    continue

                # "abort" and exhausted "retry" both stop the flow.
                flow_success = False
                flow_error = f"Node '{node.id}' failed: {error}"
                self.logger.error(flow_error)
                if result is not None:
                    node_results[node.id] = result
                break
        finally:
            await session.close_all()

        elapsed = loop.time() - start_time
        return FlowResult(
            flow_name=flow.name,
            node_results={k: v.extracted_data for k, v in node_results.items()},
            success=flow_success,
            error_message=flow_error,
            elapsed_seconds=elapsed,
            nodes_completed=nodes_completed,
            nodes_total=len(order),
            checkpoint_path=checkpoint_path,
            resumed_from=resume_from,
        )
