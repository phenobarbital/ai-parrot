"""
WebScrapingToolkit — AbstractToolkit-based entry point for scraping.

Each public async method is automatically exposed as an individual tool
for agents and chatbots via ``AbstractToolkit``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from parrot.tools.toolkit import AbstractToolkit

from .driver_context import DriverRegistry, driver_context, _quit_driver
from .executor import execute_plan_steps
from .models import ScrapingResult
from .page_snapshot import PageSnapshot, snapshot_from_driver
from .plan import ScrapingPlan
from .plan_generator import PlanGenerator
from .plan_io import load_plan_from_disk, save_plan_to_disk
from .registry import PlanRegistry
from .toolkit_models import DriverConfig, PlanSaveResult, PlanSummary

logger = logging.getLogger(__name__)


# ── Refinement scoring ────────────────────────────────────────────────

# Minimum score below which we trigger an LLM refinement pass.
REFINEMENT_TRIGGER_SCORE = 0.6


class ExtractionScore:
    """Heuristic quality score for a ``ScrapingResult``.

    Attributes:
        value: 0.0 = nothing useful came out, 1.0 = every extract name
            has rows with fully-populated fields.
        reasons: Human-readable diagnostic lines (empty rows, null-field
            rates, step errors). Passed verbatim into the refinement
            prompt so the LLM knows exactly what to fix.
        needs_refinement: True if the result is weak enough that a
            second LLM pass is likely to improve it.
    """

    __slots__ = ("value", "reasons", "needs_refinement")

    def __init__(
        self,
        value: float,
        reasons: List[str],
        needs_refinement: bool,
    ) -> None:
        self.value = value
        self.reasons = reasons
        self.needs_refinement = needs_refinement

    def summary(self) -> str:
        if not self.reasons:
            return f"score={self.value:.2f}"
        return f"score={self.value:.2f}: " + "; ".join(self.reasons)


def _score_extraction(result: Any) -> ExtractionScore:
    """Score a ``ScrapingResult`` on a 0..1 scale.

    Conservative heuristics — we'd rather over-trigger refinement than
    accept a broken extraction:

    - Empty extract_name (list with 0 rows, or scalar None) → 0.0
      contribution plus a reason line.
    - Row list where rows are dicts: average "non-empty field" ratio
      across all rows. If < 0.6 average, flag it.
    - Scalar string value: 1.0 if non-empty, else 0.0.
    - Step errors halve the final score — something failed that
      probably affected the result.
    """
    reasons: List[str] = []
    extracted = getattr(result, "extracted_data", None) or {}

    if not extracted:
        reasons.append("no extracted_data produced")
        return ExtractionScore(0.0, reasons, needs_refinement=True)

    per_key_scores: List[float] = []
    for name, value in extracted.items():
        if value is None:
            reasons.append(f"{name!r}: null")
            per_key_scores.append(0.0)
            continue

        if isinstance(value, list):
            if not value:
                reasons.append(f"{name!r}: 0 rows")
                per_key_scores.append(0.0)
                continue
            row_scores: List[float] = []
            for row in value:
                if isinstance(row, dict):
                    if not row:
                        row_scores.append(0.0)
                        continue
                    non_empty = 0
                    for v in row.values():
                        if v is None:
                            continue
                        if isinstance(v, str) and not v.strip():
                            continue
                        if isinstance(v, list) and not v:
                            continue
                        non_empty += 1
                    row_scores.append(non_empty / len(row))
                elif isinstance(row, str):
                    row_scores.append(1.0 if row.strip() else 0.0)
                else:
                    row_scores.append(1.0 if row else 0.0)
            avg = sum(row_scores) / len(row_scores)
            if avg < 0.6:
                empty_ratio = sum(1 for s in row_scores if s < 0.2) / len(row_scores)
                reasons.append(
                    f"{name!r}: {len(value)} rows, avg field completeness "
                    f"{avg:.0%} (empty-row rate {empty_ratio:.0%})"
                )
            per_key_scores.append(avg)
            continue

        if isinstance(value, dict):
            non_empty = sum(
                1 for v in value.values()
                if v is not None and (
                    not isinstance(v, str) or v.strip()
                ) and v != []
            )
            ratio = non_empty / max(1, len(value))
            if ratio < 0.6:
                reasons.append(
                    f"{name!r}: single dict, {ratio:.0%} fields populated"
                )
            per_key_scores.append(ratio)
            continue

        # scalar
        populated = bool(str(value).strip()) if isinstance(value, str) else bool(value)
        per_key_scores.append(1.0 if populated else 0.0)
        if not populated:
            reasons.append(f"{name!r}: empty scalar")

    base = sum(per_key_scores) / len(per_key_scores) if per_key_scores else 0.0

    # Step errors penalize heavily
    step_errors = []
    md = getattr(result, "metadata", None) or {}
    if md.get("step_errors"):
        step_errors = md["step_errors"]
        reasons.append(
            f"{len(step_errors)} step error(s): "
            + "; ".join(
                f"step {e.get('step_index')} ({e.get('action')}): "
                f"{str(e.get('error'))[:80]}"
                for e in step_errors[:3]
            )
        )
        base *= 0.5

    needs = base < REFINEMENT_TRIGGER_SCORE or bool(step_errors)
    return ExtractionScore(base, reasons, needs)


def _format_extraction_summary(result: Any) -> str:
    """Render a compact text summary of what came out.

    Meant for the refinement prompt — shows row counts and a peek at
    the first row so the LLM can see the shape of what it produced.
    """
    lines: List[str] = []
    extracted = getattr(result, "extracted_data", None) or {}
    if not extracted:
        return "(no extracted_data)"
    for name, value in extracted.items():
        if value is None:
            lines.append(f"- {name}: null")
        elif isinstance(value, list):
            lines.append(f"- {name}: {len(value)} row(s)")
            for i, row in enumerate(value[:2]):
                if isinstance(row, dict):
                    fields = ", ".join(
                        f"{k}={_short(v)}" for k, v in list(row.items())[:6]
                    )
                    lines.append(f"    row[{i}]: {fields}")
                else:
                    lines.append(f"    row[{i}]: {_short(row)}")
            if len(value) > 2:
                lines.append(f"    ... ({len(value) - 2} more rows)")
        elif isinstance(value, dict):
            fields = ", ".join(
                f"{k}={_short(v)}" for k, v in list(value.items())[:6]
            )
            lines.append(f"- {name}: {{ {fields} }}")
        else:
            lines.append(f"- {name}: {_short(value)}")
    return "\n".join(lines)


def _format_step_errors(result: Any) -> str:
    md = getattr(result, "metadata", None) or {}
    errors = md.get("step_errors") or []
    if not errors:
        return ""
    lines: List[str] = []
    for e in errors:
        idx = e.get("step_index", "?")
        action = e.get("action", "?")
        err = str(e.get("error", "")).replace("\n", " ")[:200]
        lines.append(f"- step {idx} ({action}): {err}")
    return "\n".join(lines)


def _short(v: Any, limit: int = 60) -> str:
    s = str(v)
    s = s.replace("\n", " ").strip()
    if len(s) > limit:
        return s[:limit] + "…"
    return s


def _has_non_empty_values(extracted: Dict[str, Any]) -> bool:
    """Return True when at least one key has a truthy value.

    A ``selector`` row counts as empty when every field in it is None
    or blank — i.e. the plan matched elements but extracted nothing
    meaningful. Saving such a plan would poison the cache.
    """
    if not extracted:
        return False
    for value in extracted.values():
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        if isinstance(value, list):
            for item in value:
                if item is None:
                    continue
                if isinstance(item, dict):
                    if any(
                        (isinstance(v, str) and v.strip())
                        or (isinstance(v, list) and v)
                        or (v is not None and not isinstance(v, (str, list)))
                        for v in item.values()
                    ):
                        return True
                elif isinstance(item, str):
                    if item.strip():
                        return True
                elif item is not None:
                    return True
            continue
        if isinstance(value, dict):
            if any(
                (isinstance(v, str) and v.strip()) or v not in (None, "", [])
                for v in value.values()
            ):
                return True
            continue
        # Scalars (int, bool, etc.)
        return True
    return False


class WebScrapingToolkit(AbstractToolkit):
    """Toolkit for intelligent web scraping and crawling with plan caching.

    Inherits from ``AbstractToolkit`` so that every public async method is
    auto-discovered as a tool.  Coordinates plan inference (LLM), single-page
    scraping, multi-page crawling, and plan persistence.

    Args:
        driver_type: Browser driver backend to use.
        browser: Browser to launch.
        headless: Run headless.
        session_based: Reuse driver across calls (sequential only).
        mobile: Enable mobile emulation.
        mobile_device: Specific mobile device name.
        auto_install: Auto-install/update browser driver.
        default_timeout: Default timeout in seconds.
        retry_attempts: Retries for failed operations.
        delay_between_actions: Seconds between plan steps.
        overlay_housekeeping: Dismiss overlays between actions.
        disable_images: Block image loading.
        custom_user_agent: Override user agent.
        plans_dir: Root directory for plan storage.
        llm_client: LLM client with ``async complete(prompt) -> str``.
        **kwargs: Passed through to ``AbstractToolkit``.
    """

    def __init__(
        self,
        driver_type: Literal["selenium", "playwright"] = "selenium",
        browser: Literal[
            "chrome", "firefox", "edge", "safari", "undetected", "webkit"
        ] = "chrome",
        headless: bool = True,
        session_based: bool = False,
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        auto_install: bool = True,
        default_timeout: int = 10,
        retry_attempts: int = 3,
        delay_between_actions: float = 1.0,
        overlay_housekeeping: bool = True,
        disable_images: bool = False,
        custom_user_agent: Optional[str] = None,
        plans_dir: Optional[Union[str, Path]] = None,
        llm_client: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self._config = DriverConfig(
            driver_type=driver_type,
            browser=browser,
            headless=headless,
            mobile=mobile,
            mobile_device=mobile_device,
            auto_install=auto_install,
            default_timeout=default_timeout,
            retry_attempts=retry_attempts,
            delay_between_actions=delay_between_actions,
            overlay_housekeeping=overlay_housekeeping,
            disable_images=disable_images,
            custom_user_agent=custom_user_agent,
        )
        self._session_based = session_based
        self._session_driver: Optional[Any] = None
        self._registry: Optional[PlanRegistry] = None
        self._llm_client = llm_client
        self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")
        self.logger = logging.getLogger(__name__)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise session driver when ``session_based=True``.

        In session mode a single browser instance is created and reused
        across all ``scrape()`` / ``crawl()`` calls until ``stop()`` is invoked.

        .. note:: Session mode is for **sequential** use only.
        """
        if self._session_based and self._session_driver is None:
            factory = DriverRegistry.get(self._config.driver_type)
            setup = factory(self._config)
            self._session_driver = await setup.get_driver()
            self.logger.info("Session driver started (%s)", self._config.driver_type)

    async def stop(self) -> None:
        """Shut down the session driver if active."""
        if self._session_driver is not None:
            await _quit_driver(self._session_driver)
            self._session_driver = None
            self.logger.info("Session driver stopped")

    # ── Internal helpers ──────────────────────────────────────────────

    async def _ensure_registry(self) -> PlanRegistry:
        """Lazy-load the ``PlanRegistry`` from disk."""
        if self._registry is None:
            self._registry = PlanRegistry(plans_dir=self._plans_dir)
            await self._registry.load()
        return self._registry

    def _get_llm_client(self) -> Any:
        """Resolve an LLM client or raise."""
        if self._llm_client is not None:
            return self._llm_client
        raise RuntimeError(
            "No LLM client available.  Pass llm_client= to the constructor "
            "or set the AIPARROT_DEFAULT_MODEL environment variable."
        )

    async def _try_resolve_cached_plan(
        self,
        url: str,
        plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
    ) -> Optional[ScrapingPlan]:
        """Return an explicit or cached plan WITHOUT calling the LLM.

        Used by ``scrape()`` so we know upfront whether plan generation
        is needed (in which case we capture a driver-based DOM snapshot
        before invoking the LLM). Returns ``None`` when the LLM would be
        needed, so the caller can handle that case explicitly.
        """
        if plan is not None:
            if isinstance(plan, dict):
                return ScrapingPlan.model_validate(plan)
            return plan

        registry = await self._ensure_registry()
        entry = registry.lookup(url)
        if entry is None:
            return None

        plan_path = self._plans_dir / entry.path
        try:
            cached = await load_plan_from_disk(plan_path)
            await registry.touch(entry.fingerprint)
            self.logger.info("Plan cache hit for %s", url)
            return cached
        except (FileNotFoundError, OSError) as exc:
            self.logger.warning(
                "Cached plan file missing: %s (%s); evicting stale entry",
                plan_path, exc,
            )
            await registry.invalidate(entry.fingerprint)
            return None

    async def _resolve_plan(
        self,
        url: str,
        plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
        objective: Optional[str] = None,
    ) -> ScrapingPlan:
        """Plan resolution chain: explicit -> cached -> auto-generate -> error.

        Args:
            url: Target URL.
            plan: Explicit plan (highest priority).
            objective: Scraping objective for auto-generation.

        Returns:
            A resolved ``ScrapingPlan``.

        Raises:
            ValueError: If no plan can be resolved.
        """
        # 1. Explicit plan argument
        if plan is not None:
            if isinstance(plan, dict):
                return ScrapingPlan.model_validate(plan)
            return plan

        # 2. Registry cache lookup
        registry = await self._ensure_registry()
        entry = registry.lookup(url)
        if entry is not None:
            plan_path = self._plans_dir / entry.path
            try:
                cached = await load_plan_from_disk(plan_path)
                await registry.touch(entry.fingerprint)
                self.logger.info("Plan cache hit for %s", url)
                return cached
            except (FileNotFoundError, OSError) as exc:
                self.logger.warning(
                    "Cached plan file missing: %s (%s); evicting stale "
                    "registry entry and falling through to regeneration",
                    plan_path, exc,
                )
                await registry.invalidate(entry.fingerprint)

        # 3. Auto-generate via LLM if objective provided
        if objective:
            return await self.plan_create(url, objective)

        # 4. Error
        raise ValueError(
            f"No plan available for {url!r}. Provide an explicit plan, "
            "a cached plan must exist, or pass objective= to auto-generate."
        )

    # ── Tool methods (7 public async methods -> 7 tools) ──────────────

    async def plan_create(
        self,
        url: str,
        objective: str,
        hints: Optional[Dict[str, Any]] = None,
        force_regenerate: bool = False,
        snapshot: Optional[PageSnapshot] = None,
        auto_snapshot: bool = True,
    ) -> ScrapingPlan:
        """Create a scraping plan for a URL via LLM or cache.

        Returns a cached plan if one exists for the URL (unless
        ``force_regenerate=True``), otherwise generates a new one via the
        configured LLM client. When neither ``snapshot`` is supplied nor
        ``auto_snapshot`` disabled, the page is fetched via aiohttp and
        summarized for the LLM so it can pick real selectors.

        Args:
            url: Target URL.
            objective: What to extract.
            hints: Optional hints for the LLM (e.g. auth_required, pagination).
            force_regenerate: Bypass cache and always call the LLM.
            snapshot: Pre-built ``PageSnapshot`` (e.g. captured via the
                browser driver for JS-rendered pages). Skips auto-fetch.
            auto_snapshot: If True, fetch a snapshot via aiohttp when one
                is not supplied. Disable for offline plan generation or
                when the page is not reachable without a browser.

        Returns:
            A ``ScrapingPlan`` ready for execution.
        """
        if not force_regenerate:
            registry = await self._ensure_registry()
            entry = registry.lookup(url)
            if entry is not None:
                plan_path = self._plans_dir / entry.path
                try:
                    cached = await load_plan_from_disk(plan_path)
                    await registry.touch(entry.fingerprint)
                    self.logger.info("plan_create: cache hit for %s", url)
                    return cached
                except (FileNotFoundError, OSError) as exc:
                    self.logger.warning(
                        "Cached plan file missing: %s; evicting stale "
                        "registry entry and regenerating via LLM",
                        exc,
                    )
                    await registry.invalidate(entry.fingerprint)

        client = self._get_llm_client()
        gen = PlanGenerator(client)
        plan = await gen.generate(
            url,
            objective,
            snapshot=snapshot,
            hints=hints,
            auto_snapshot=auto_snapshot,
        )
        self.logger.info("plan_create: generated new plan for %s", url)
        return plan

    async def plan_save(
        self,
        plan: ScrapingPlan,
        overwrite: bool = False,
    ) -> PlanSaveResult:
        """Save a scraping plan to disk and register it.

        Args:
            plan: Plan to save.
            overwrite: Replace an existing file if it exists.

        Returns:
            ``PlanSaveResult`` with save status and file path.
        """
        registry = await self._ensure_registry()

        # Check for existing entry
        if not overwrite:
            existing = registry.lookup(plan.url)
            if existing is not None:
                return PlanSaveResult(
                    success=False,
                    path=existing.path,
                    name=existing.name,
                    version=existing.plan_version,
                    registered=True,
                    message="Plan already exists. Use overwrite=True to replace.",
                )

        try:
            saved_path = await save_plan_to_disk(plan, self._plans_dir)
            relative = str(saved_path.relative_to(self._plans_dir))
            await registry.register(plan, relative)
            return PlanSaveResult(
                success=True,
                path=relative,
                name=plan.name,
                version=plan.version,
                registered=True,
                message="Plan saved and registered successfully.",
            )
        except Exception as exc:
            self.logger.error("plan_save failed: %s", exc)
            return PlanSaveResult(
                success=False,
                path="",
                name=plan.name or "",
                version=plan.version,
                registered=False,
                message=f"Save failed: {exc}",
            )

    async def plan_load(self, url_or_name: str) -> Optional[ScrapingPlan]:
        """Load a plan by URL (registry lookup) or by name.

        Args:
            url_or_name: A URL to look up or a plan name.

        Returns:
            The loaded ``ScrapingPlan`` or ``None`` if not found.
        """
        registry = await self._ensure_registry()

        # Try URL lookup first
        entry = registry.lookup(url_or_name)
        if entry is None:
            # Try name lookup
            entry = registry.get_by_name(url_or_name)

        if entry is None:
            return None

        plan_path = self._plans_dir / entry.path
        try:
            plan = await load_plan_from_disk(plan_path)
            await registry.touch(entry.fingerprint)
            return plan
        except (FileNotFoundError, OSError) as exc:
            self.logger.warning(
                "Plan file missing: %s (%s); evicting stale registry entry",
                plan_path, exc,
            )
            await registry.invalidate(entry.fingerprint)
            return None

    async def plan_list(
        self,
        domain_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
    ) -> List[PlanSummary]:
        """List registered plans with optional filtering.

        Args:
            domain_filter: Only include plans matching this domain.
            tag_filter: Only include plans containing this tag.

        Returns:
            List of ``PlanSummary`` objects.
        """
        registry = await self._ensure_registry()
        entries = registry.list_all()
        results: List[PlanSummary] = []

        for entry in entries:
            if domain_filter and entry.domain != domain_filter:
                continue
            if tag_filter and tag_filter not in entry.tags:
                continue
            results.append(PlanSummary.from_registry_entry(entry))

        return results

    async def plan_delete(
        self,
        name: str,
        delete_file: bool = True,
    ) -> bool:
        """Delete a plan from the registry and optionally from disk.

        Args:
            name: Plan name to delete.
            delete_file: Also remove the plan file from disk.

        Returns:
            ``True`` if the plan was found and removed.
        """
        registry = await self._ensure_registry()

        # Find the entry before removing
        entry = registry.get_by_name(name)
        if entry is None:
            return False

        # Remove file if requested
        if delete_file:
            plan_path = self._plans_dir / entry.path
            try:
                plan_path.unlink(missing_ok=True)
                self.logger.info("Deleted plan file: %s", plan_path)
            except OSError as exc:
                self.logger.warning("Could not delete file %s: %s", plan_path, exc)

        # Remove from registry
        return await registry.remove(name)

    async def scrape(
        self,
        url: str,
        plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
        objective: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        selectors: Optional[List[Dict[str, Any]]] = None,
        save_plan: bool = False,
        browser_config_override: Optional[Dict[str, Any]] = None,
        max_refinement_attempts: int = 1,
    ) -> ScrapingResult:
        """Scrape a single page using a plan, raw steps, or auto-generation.

        Plan resolution priority (when ``steps`` is not provided):
        1. Explicit ``plan`` argument
        2. Registry cache lookup by ``url``
        3. Auto-generate via LLM if ``objective`` is provided
        4. Raise ``ValueError``

        When ``steps`` is provided, they are executed directly without
        plan resolution.

        **Refinement loop**: when an ``objective`` is supplied and the
        initial plan's extraction quality scores below
        ``REFINEMENT_TRIGGER_SCORE`` (empty rows, mostly-null fields, or
        step errors), we capture a fresh post-execution DOM snapshot and
        ask the LLM to produce a revised plan, then re-execute. Controlled
        by ``max_refinement_attempts`` (default 1 — so at most 2 LLM
        calls total). Disabled when the plan came from cache/explicit
        input, since we don't own that plan to refine it.

        Args:
            url: Target URL.
            plan: Explicit ScrapingPlan or dict.
            objective: Scraping objective (for auto-generation).
            steps: Raw steps list for ad-hoc execution (bypasses plan resolution).
            selectors: Content extraction selectors (used with raw steps).
            save_plan: Save the resolved/generated plan after scraping.
            browser_config_override: Per-call driver config overrides.
            max_refinement_attempts: How many LLM refinement passes to
                allow when the first extraction scores poorly. Set to 0
                to disable. Default 1.

        Returns:
            ``ScrapingResult`` with extracted data and metadata. When
            refinement ran, returns the result of the FINAL pass (not
            the initial one), regardless of whether it scored higher.
        """
        config = self._config.merge(browser_config_override)

        # Raw steps mode — bypass plan resolution
        if steps is not None:
            async with driver_context(config, session_driver=self._session_driver) as drv:
                return await execute_plan_steps(
                    drv,
                    steps=steps,
                    selectors=selectors,
                    config=config,
                    base_url=url,
                )

        # Try resolving from cache / explicit plan FIRST — no driver needed.
        resolved = await self._try_resolve_cached_plan(url, plan)
        plan_was_generated = resolved is None

        async with driver_context(config, session_driver=self._session_driver) as drv:
            # If we still need to generate the plan via LLM, capture a
            # live DOM snapshot from the driver BEFORE execution so the
            # LLM sees the post-hydration structure. SPAs (React/Next.js/
            # Vue) render most content client-side; an aiohttp snapshot
            # would only see the empty shell.
            if resolved is None:
                if not objective:
                    raise ValueError(
                        f"No plan available for {url!r}. Provide an explicit "
                        "plan, a cached plan must exist, or pass objective= "
                        "to auto-generate."
                    )
                self.logger.info(
                    "Capturing DOM snapshot via driver before plan generation"
                )
                snapshot = await snapshot_from_driver(drv, url=url)
                resolved = await self.plan_create(
                    url, objective,
                    snapshot=snapshot,
                    auto_snapshot=False,  # we already captured via driver
                )

            result = await execute_plan_steps(
                drv,
                plan=resolved,
                config=config,
                base_url=url,
            )

            # Refinement loop — only when the plan came from LLM and the
            # user provided an objective to re-prompt against. Explicit /
            # cached plans are owned by the caller, not ours to revise.
            if (
                plan_was_generated
                and objective
                and max_refinement_attempts > 0
            ):
                attempt = 0
                while attempt < max_refinement_attempts:
                    score = _score_extraction(result)
                    self.logger.info(
                        "Extraction quality %s", score.summary()
                    )
                    if not score.needs_refinement:
                        break
                    attempt += 1
                    self.logger.warning(
                        "Refinement pass %d/%d — weak extraction: %s",
                        attempt, max_refinement_attempts, score.summary(),
                    )
                    try:
                        post_snapshot = await snapshot_from_driver(
                            drv, scroll_sweep=False,
                        )
                        client = self._get_llm_client()
                        gen = PlanGenerator(client)
                        resolved = await gen.refine(
                            url=url,
                            objective=objective,
                            prior_plan=resolved,
                            extraction_summary=_format_extraction_summary(result),
                            step_errors=_format_step_errors(result),
                            diagnosis="; ".join(score.reasons),
                            snapshot=post_snapshot,
                        )
                    except Exception as exc:  # noqa: BLE001
                        self.logger.error(
                            "Refinement pass %d failed to produce a plan: %s; "
                            "keeping prior result",
                            attempt, exc,
                        )
                        break
                    # Re-execute against the same driver. The refined
                    # plan starts with its own navigate step so the page
                    # state resets cleanly.
                    result = await execute_plan_steps(
                        drv,
                        plan=resolved,
                        config=config,
                        base_url=url,
                    )

        # Auto-save if requested — only if the plan actually produced data.
        # Saving empty-result plans poisons the cache: subsequent runs hit
        # the cache instead of regenerating, locking in a broken plan.
        if save_plan:
            if not result.success:
                self.logger.info(
                    "Skipping plan auto-save: scrape did not succeed"
                )
            elif not result.extracted_data or not _has_non_empty_values(result.extracted_data):
                self.logger.info(
                    "Skipping plan auto-save: extracted_data is empty — "
                    "the plan ran but matched no content"
                )
            else:
                try:
                    await self.plan_save(resolved)
                except Exception as exc:
                    self.logger.warning("Auto-save plan failed: %s", exc)

        return result

    async def crawl(
        self,
        start_url: str,
        depth: int = 1,
        max_pages: Optional[int] = None,
        follow_selector: Optional[str] = None,
        follow_pattern: Optional[str] = None,
        plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
        objective: Optional[str] = None,
        save_plan: bool = False,
        concurrency: int = 1,
    ) -> Any:
        """Crawl multiple pages starting from a URL.

        Delegates to ``CrawlEngine`` (FEAT-013).  If the engine is not
        available, raises ``NotImplementedError``.

        Args:
            start_url: Entry point URL.
            depth: Maximum crawl depth.
            max_pages: Maximum number of pages to visit.
            follow_selector: CSS selector for links to follow.
            follow_pattern: URL regex pattern for links to follow.
            plan: Explicit scraping plan for each page.
            objective: Scraping objective for auto-generation.
            save_plan: Persist the plan after first scrape.
            concurrency: Number of concurrent page fetches.

        Returns:
            CrawlResult from the engine.

        Raises:
            NotImplementedError: If CrawlEngine is not available.
        """
        try:
            from .crawl_engine import CrawlEngine
        except ImportError:
            raise NotImplementedError(
                "CrawlEngine is not available. Install FEAT-013 to enable crawling."
            )

        # Resolve the per-page plan
        resolved = await self._resolve_plan(start_url, plan, objective)

        engine = CrawlEngine(
            start_url=start_url,
            plan=resolved,
            depth=depth,
            max_pages=max_pages,
            follow_selector=follow_selector,
            follow_pattern=follow_pattern,
            concurrency=concurrency,
            driver_config=self._config,
        )

        result = await engine.run()

        if save_plan and resolved:
            crawl_has_data = any(
                _has_non_empty_values(getattr(page, "extracted_data", {}) or {})
                for page in result.pages
            )
            if not crawl_has_data:
                self.logger.info(
                    "Skipping crawl plan auto-save: no page produced data"
                )
            else:
                try:
                    await self.plan_save(resolved)
                except Exception as exc:
                    self.logger.warning("Auto-save plan failed: %s", exc)

        return result
