"""
WebBrowsingToolkit — catalogued, deterministic web navigation for agents.

Extends :class:`~parrot_tools.scraping.toolkit.WebScrapingToolkit` with a
per-site **action catalog**: named scripts ("guiones") written in the same
BrowserAction DSL, stored on disk (one folder per site, one JSON file per
action). An agent resolves a natural-language request ("inicia sesión en
Hooba") to a catalogued site + action and replays it deterministically —
optionally composing several actions (login -> dashboard -> CRM -> ...)
into one sequence over a single persistent browser session.

Key traits:

- **Driver fixed at construction**: Selenium or Playwright is chosen when
  the toolkit is instantiated and never switched on the fly.
- **Persistent session**: one browser/driver instance serves every
  ``run_*`` call until :meth:`close_browser` (or ``stop()``) is called,
  so a register-customer-then-invoice flow shares its login.
- **Chrome profile access**: pass ``user_data_dir`` (and optionally
  ``profile_directory`` / ``browser_channel``) to run against a real
  Google Chrome user profile — session cookies, saved logins, keyring.
- **Bounded loops only**: every ``loop`` step is capped by
  ``max_loop_iterations`` at save time (strict) and clamped again at run
  time (defense in depth).
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.models import ScrapingResult
from parrot_tools.scraping.toolkit import WebScrapingToolkit

from .catalog import ActionCatalog
from .composer import ResolvedAction, expand_sequence
from .models import (
    ActionParam,
    ActionRunSummary,
    ComposedRef,
    SequenceRunResult,
    SiteAction,
    SiteInfo,
)
from .templating import (
    collect_placeholders,
    collect_value_placeholders,
    find_literal_credentials,
    render_steps,
    validate_loop_bounds,
)

logger = logging.getLogger(__name__)

#: Default per-loop iteration cap for catalogued scripts.
DEFAULT_MAX_LOOP_ITERATIONS = 50


class WebBrowsingToolkit(WebScrapingToolkit):
    """Toolkit for catalogued, deterministic site automation.

    Every public async method is auto-exposed as an agent tool by
    ``AbstractToolkit``. On top of the inherited scraping tools
    (``scrape``, ``crawl``, ``plan_*``), this toolkit adds catalog
    management (``register_site``, ``save_site_action``, ...) and
    deterministic execution (``run_site_action``, ``run_site_sequence``).

    Args:
        catalog_dir: Root directory of the action catalog (one folder per
            site, one JSON file per action).
        user_data_dir: Path to a Google Chrome user-data directory. When
            set, the browser launches against that profile, giving the
            agent access to its session cookies, saved logins and
            passwords. Use a dedicated profile copy for automation when
            possible — Chrome locks a profile directory that is already
            open.
        profile_directory: Chrome profile folder inside *user_data_dir*
            (e.g. ``"Default"``, ``"Profile 1"``).
        browser_channel: Playwright browser channel (e.g. ``"chrome"``,
            ``"msedge"``) so a real installed Chrome — not bundled
            Chromium — opens the profile. Ignored by Selenium.
        max_loop_iterations: Hard cap applied to every ``loop`` step of a
            catalogued script.
        credential_resolver: Optional async resolver forwarded to
            ``authenticate`` steps using ``credential_provider`` (broker
            based credentials — never literal passwords in scripts).
        human_channel: Optional ``HumanChannel`` for ``await_human``
            steps (e.g. MFA challenges mid-script).
        session_based: Reuse a single browser session across every run
            (default ``True`` here, unlike the scraping parent). Note:
            catalogued runs (``run_site_action`` / ``run_site_sequence``)
            ALWAYS use session mode regardless of this flag — the
            persistent session is the point of the toolkit — so this
            only influences the inherited ``scrape``/``crawl`` behaviour
            before the first catalogued run.
        headless: Run headless. Defaults to ``False`` — catalogued flows
            typically operate real, logged-in user sessions.
        confirm_runs: Mark ``run_site_action`` / ``run_site_sequence``
            with ``requires_confirmation`` routing metadata (HITL
            confirmation where the surface supports it). Default
            ``True``: these tools act on a real, possibly authenticated
            browser session (form submissions, account changes), which
            is a larger blast radius than any catalog edit. Set to
            ``False`` only for trusted, fully-automated pipelines.
        **kwargs: Everything ``WebScrapingToolkit`` accepts
            (``driver_type``, ``browser``, ``plans_dir``, ``llm_client``,
            timeouts, ...). The driver backend is fixed at construction.
    """

    confirming_tools: frozenset = frozenset(
        {"delete_site_action", "run_site_action", "run_site_sequence"}
    )

    def __init__(
        self,
        catalog_dir: Union[str, Path] = "browsing_catalog",
        user_data_dir: Optional[Union[str, Path]] = None,
        profile_directory: Optional[str] = None,
        browser_channel: Optional[str] = None,
        max_loop_iterations: int = DEFAULT_MAX_LOOP_ITERATIONS,
        credential_resolver: Optional[Any] = None,
        human_channel: Optional[Any] = None,
        session_based: bool = True,
        headless: bool = False,
        confirm_runs: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            session_based=session_based, headless=headless, **kwargs
        )
        self._config = self._config.merge(
            {
                "user_data_dir": str(user_data_dir) if user_data_dir else None,
                "profile_directory": profile_directory,
                "browser_channel": browser_channel,
            }
        )
        self._catalog = ActionCatalog(catalog_dir)
        self._max_loop_iterations = max(1, int(max_loop_iterations))
        self._credential_resolver = credential_resolver
        self._human_channel = human_channel
        if not confirm_runs:
            # Instance-level shadow: keep only the destructive catalog
            # edit under confirmation for trusted automated pipelines.
            self.confirming_tools = frozenset({"delete_site_action"})
        #: Serializes catalogued runs — the persistent browser session is
        #: a single page/tab; concurrent sequences would interleave their
        #: navigations and fills.
        self._run_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def _ensure_session_driver(self) -> AbstractDriver:
        """Return the persistent browser driver, starting it lazily.

        The toolkit always runs catalogued actions in session mode: one
        driver serves every ``run_*`` call so authentication survives
        across actions.
        """
        self._session_based = True
        if self._session_driver is None:
            await self.start()
        return self._session_driver

    async def close_browser(self) -> Dict[str, Any]:
        """Close the persistent browser session.

        The next ``run_site_action`` / ``run_site_sequence`` call starts
        a fresh browser (fresh session, unless a Chrome profile keeps
        cookies on disk).

        Returns:
            Dict with ``closed`` indicating whether a session was open.
        """
        was_open = self._session_driver is not None
        await self.stop()
        return {"closed": was_open}

    # ── Catalog: sites ────────────────────────────────────────────────

    async def register_site(
        self,
        base_url: str,
        name: Optional[str] = None,
        title: str = "",
        description: str = "",
        aliases: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Register (or update) a site in the browsing catalog.

        Args:
            base_url: Root URL of the site (e.g. ``https://hooba.es``).
            name: Optional explicit slug; derived from the domain when
                omitted.
            title: Human-friendly site name ("Hooba").
            description: What the site is, to aid natural-language
                matching.
            aliases: Alternative names users may employ ("hooba").

        Returns:
            The stored site metadata as a dict.
        """
        info = SiteInfo(
            site=name or "",
            base_url=base_url,
            title=title,
            description=description,
            aliases=aliases or [],
        )
        stored = await self._catalog.register_site(info)
        return stored.model_dump(mode="json")

    async def list_sites(self) -> List[Dict[str, Any]]:
        """List every site registered in the browsing catalog.

        Returns:
            One dict per site: slug, base URL, title, description and
            aliases — enough for the agent to resolve user references.
        """
        return [
            info.model_dump(mode="json")
            for info in await self._catalog.list_sites()
        ]

    # ── Catalog: actions ──────────────────────────────────────────────

    async def list_site_actions(self, site: str) -> List[Dict[str, Any]]:
        """List the catalogued actions available for a site.

        Use this to match a natural-language request against the site's
        capabilities: each entry carries the action's name, kind
        (``navigation`` / ``operation`` / ``composite``), description,
        declared parameters and prerequisites.

        Args:
            site: Site reference — slug, alias, domain or title
                (e.g. ``"hooba"``).

        Returns:
            Compact summaries of every catalogued action.
        """
        actions = await self._catalog.list_actions(site)
        return [action.summary() for action in actions]

    async def get_site_action(self, site: str, action: str) -> Dict[str, Any]:
        """Fetch a catalogued action's full script.

        Args:
            site: Site reference (slug, alias, domain or title).
            action: Action name.

        Returns:
            The complete stored script, DSL steps included.
        """
        stored = await self._catalog.get_action(site, action)
        return stored.model_dump(mode="json")

    async def save_site_action(
        self,
        site: str,
        name: str,
        description: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        kind: str = "operation",
        params: Optional[Dict[str, Dict[str, Any]]] = None,
        compose: Optional[List[Dict[str, Any]]] = None,
        requires: Optional[List[str]] = None,
        title: str = "",
        tags: Optional[List[str]] = None,
        version: str = "1.0",
        source: str = "llm",
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Validate and store an action script in the site's catalog.

        The script is checked before anything is written: steps must be
        valid BrowserAction DSL, every ``{{placeholder}}`` must be a
        declared parameter, and every loop must be bounded by
        ``max_loop_iterations``.

        Args:
            site: Site reference (must already be registered).
            name: Action name (slugified; unique within the site).
            description: Natural-language description — what the action
                does and when to use it.
            steps: BrowserAction DSL steps (required unless
                ``kind='composite'``).
            kind: ``navigation``, ``operation`` or ``composite``.
            params: Declared parameters:
                ``{name: {description, required, default, example}}``.
            compose: For composites — ordered references
                ``[{action, params}]`` to sibling actions.
            requires: Prerequisite action names (e.g. ``["login"]``).
            title: Human-friendly action title.
            tags: Categorization tags.
            version: Script version string.
            source: Origin marker (``user``, ``llm``, ``recorded``).
            overwrite: Replace an existing action of the same name.

        Returns:
            Dict with ``saved``, the storage ``path`` and the action
            summary.
        """
        action = SiteAction(
            name=name,
            title=title,
            description=description,
            kind=kind,  # type: ignore[arg-type]
            params={
                key: ActionParam(**spec) for key, spec in (params or {}).items()
            },
            steps=steps or [],
            compose=[ComposedRef(**ref) for ref in (compose or [])],
            requires=requires or [],
            tags=tags or [],
            version=version,
            source=source,
        )

        if action.steps:
            undeclared = collect_placeholders(action.steps) - set(action.params)
            if undeclared:
                raise ValueError(
                    "Steps use undeclared placeholder(s): "
                    f"{', '.join(sorted(undeclared))}. Declare them in "
                    "'params' so callers know what to provide."
                )
            credential_leaks = find_literal_credentials(action.steps)
            if credential_leaks:
                raise ValueError(
                    "Refusing to save a script with literal credentials:\n"
                    + "\n".join(credential_leaks)
                )
            action.steps = validate_loop_bounds(
                action.steps, self._max_loop_iterations, strict=True
            )
        if action.compose:
            bound_placeholders = set()
            for ref in action.compose:
                bound_placeholders |= collect_value_placeholders(ref.params)
            undeclared = bound_placeholders - set(action.params)
            if undeclared:
                raise ValueError(
                    "Composite bindings use undeclared placeholder(s): "
                    f"{', '.join(sorted(undeclared))}. Declare them in "
                    "'params' so callers know what to provide."
                )

        path = await self._catalog.save_action(site, action, overwrite=overwrite)
        return {
            "saved": True,
            "path": str(path),
            "action": action.summary(),
        }

    async def delete_site_action(self, site: str, action: str) -> Dict[str, Any]:
        """Delete a catalogued action from a site.

        Args:
            site: Site reference.
            action: Action name.

        Returns:
            Dict with ``deleted`` indicating whether the file existed.
        """
        deleted = await self._catalog.delete_action(site, action)
        return {"deleted": deleted, "site": site, "action": action}

    # ── Execution ─────────────────────────────────────────────────────

    async def run_site_action(
        self,
        site: str,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        include_requires: bool = True,
        stop_on_error: bool = True,
    ) -> Dict[str, Any]:
        """Deterministically execute one catalogued action on a site.

        Prerequisites (``requires``, e.g. ``login``) are injected
        automatically and composite actions are expanded, so a single
        call can drive a full flow. Everything runs on the toolkit's
        persistent browser session.

        Args:
            site: Site reference — slug, alias, domain or title
                (e.g. ``"hooba"``).
            action: Action name from the site's catalog.
            params: Values for the action's declared parameters.
            include_requires: Auto-run prerequisite actions first.
            stop_on_error: Abort the remaining sequence when an action
                fails.

        Returns:
            A :class:`SequenceRunResult` as a dict: per-action outcomes
            plus merged extracted data.
        """
        sequence = await expand_sequence(
            self._catalog,
            site,
            [{"action": action, "params": params or {}}],
            include_requires=include_requires,
        )
        return await self._run_resolved_sequence(
            site, [action], sequence, stop_on_error=stop_on_error
        )

    async def run_site_sequence(
        self,
        site: str,
        plan: List[Union[str, Dict[str, Any]]],
        params: Optional[Dict[str, Any]] = None,
        include_requires: bool = True,
        stop_on_error: bool = True,
    ) -> Dict[str, Any]:
        """Execute an ordered plan of catalogued actions on one session.

        Use this to fulfil multi-step requests ("login, luego ir al
        Dashboard, luego crear el draft de factura"): build the plan from
        the site's catalog and run it — prerequisites are deduplicated
        across the whole plan, so ``login`` runs at most once.

        Args:
            site: Site reference (slug, alias, domain or title).
            plan: Ordered entries — an action name, or
                ``{"action": name, "params": {...}}``.
            params: Shared parameter values applied to every entry
                (entry-level params win).
            include_requires: Auto-run prerequisite actions.
            stop_on_error: Abort remaining actions when one fails.

        Returns:
            A :class:`SequenceRunResult` as a dict.
        """
        requested = [
            entry if isinstance(entry, str) else str(entry.get("action"))
            for entry in plan
        ]
        sequence = await expand_sequence(
            self._catalog,
            site,
            plan,
            shared_params=params,
            include_requires=include_requires,
        )
        return await self._run_resolved_sequence(
            site, requested, sequence, stop_on_error=stop_on_error
        )

    # ── Internal execution helpers ────────────────────────────────────

    async def _run_resolved_sequence(
        self,
        site: str,
        requested: List[str],
        sequence: List[ResolvedAction],
        *,
        stop_on_error: bool,
    ) -> Dict[str, Any]:
        """Execute an expanded sequence against the session driver.

        The whole sequence runs under ``self._run_lock``: the persistent
        browser session drives a single page, so concurrent sequences
        must not interleave their navigations.
        """
        site_info = await self._catalog.resolve_site(site)

        executed: List[ActionRunSummary] = []
        merged: Dict[str, Any] = {}
        writers: Dict[str, str] = {}
        stopped_early = False

        async with self._run_lock:
            driver = await self._ensure_session_driver()
            for resolved in sequence:
                summary = await self._run_one(driver, site_info, resolved)
                executed.append(summary)
                for key, value in summary.extracted_data.items():
                    # Later actions win the bare key; a displaced earlier
                    # value stays reachable under "{earlier_action}.{key}".
                    if key in merged and merged[key] != value:
                        merged[f"{writers[key]}.{key}"] = merged[key]
                    merged[key] = value
                    writers[key] = summary.action
                if not summary.success and stop_on_error:
                    stopped_early = len(executed) < len(sequence)
                    break

        result = SequenceRunResult(
            success=all(item.success for item in executed) and not stopped_early,
            site=site_info.site,
            requested=requested,
            executed=executed,
            extracted_data=merged,
            stopped_early=stopped_early,
        )
        return result.model_dump(mode="json")

    async def _run_one(
        self,
        driver: AbstractDriver,
        site_info: SiteInfo,
        resolved: ResolvedAction,
    ) -> ActionRunSummary:
        """Render, bound and execute one resolved action's steps."""
        action = resolved.action
        started = time.monotonic()
        try:
            steps = render_steps(action.steps, resolved.params)
            steps = validate_loop_bounds(
                steps, self._max_loop_iterations, strict=False
            )
            result: ScrapingResult = await execute_plan_steps(
                driver,
                steps=steps,
                config=self._config,
                base_url=site_info.base_url,
                credential_resolver=self._credential_resolver,
                channel=self._human_channel,
            )
            step_errors = (result.metadata or {}).get("step_errors") or []
            error: Optional[str] = result.error_message
            if not error and step_errors:
                first = step_errors[0]
                error = (
                    f"step {first.get('step_index')} "
                    f"({first.get('action')}): {first.get('error')}"
                )
            return ActionRunSummary(
                action=action.name,
                kind=action.kind,
                success=bool(result.success) and not step_errors,
                error=error,
                extracted_data=result.extracted_data or {},
                elapsed_ms=int((time.monotonic() - started) * 1000),
                injected=resolved.injected,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "Action %s/%s failed: %s", site_info.site, action.name, exc
            )
            return ActionRunSummary(
                action=action.name,
                kind=action.kind,
                success=False,
                error=str(exc),
                elapsed_ms=int((time.monotonic() - started) * 1000),
                injected=resolved.injected,
            )
