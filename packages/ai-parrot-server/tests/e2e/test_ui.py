"""Real Obscura/DevTools admin-UI browser scenario for FEAT-581 (M5/M8, TASK-3548).

Starts three real, owned targets under one :class:`E2ESupervisor` --
``botmanager`` (the isolated, authenticated fixture backend TASK-3530
implemented), ``ui`` (TASK-3531's real ``pnpm build``/``pnpm preview``
build/serve two-step, pointed at that backend via ``PUBLIC_API_URL``) and
``browser`` (TASK-3531's owned, isolated Obscura instance) -- then drives
the *real* Obscura CDP endpoint with Playwright's own
``chromium.connect_over_cdp()`` (the exact attachment pattern
``parrot.mcp.obscura``'s own module docstring documents) to perform a fixed
navigation between this app's two real, already-shipped routes (``/admin/``
and ``/admin/login``, per ``Login.svelte``'s own routing comment) and assert
the declared console/network invariants: no console message of severity
``error``, and no network response with a server-error (5xx) status.
"Health alone is not browser evidence" (spec §2): only this real
DevTools-observed navigation counts as this scenario's own evidence.

Codified/deterministic browser checks require an *owned* isolated instance
(TASK-3531's own contract, reasserted as this task's own acceptance
evidence in ``test_browser_prerequisites.py``); this scenario never passes
``options={"adopt": True}`` to the ``browser`` target. A genuinely missing
prerequisite anywhere in this chain (``obscura``, ``pnpm``/``node``, this
worktree's own currently-uninstalled admin-UI ``node_modules``) surfaces as
a visible, typed :class:`~parrot.e2e.errors.E2EPrerequisiteError` (BLOCKED)
straight out of :meth:`E2ESupervisor.start` -- never a silently skipped or
swallowed scenario.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EPrerequisiteError
from parrot.e2e.models import TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets.botmanager import build_botmanager_adapter
from parrot.e2e.targets.browser import build_browser_adapter
from parrot.e2e.targets.ui import build_ui_adapter

_ADMIN_TITLE = "AI-Parrot Admin"
_ADMIN_HOME_PATH = "/admin/"
_ADMIN_LOGIN_PATH = "/admin/login"
_NAVIGATION_TIMEOUT_MS = 20_000


def _require_playwright() -> Any:
    """Import Playwright's async API, or raise a typed BLOCKED prerequisite error.

    A codified/deterministic browser check requires the real, owned
    DevTools-attach client this scenario drives -- never a silent
    ``pytest.importorskip``. This is this scenario's own harness
    prerequisite (never a `browser`/`ui` target adapter concern; TASK-3548
    owns no source file that could raise this from inside either adapter).

    Returns:
        The imported ``playwright.async_api`` module.

    Raises:
        E2EPrerequisiteError: If ``playwright`` is not installed in this
            environment (spec §2: "Missing binary/version or host
            capability produces visible BLOCKED").
    """
    try:
        import playwright.async_api as async_api
    except ImportError as exc:
        raise E2EPrerequisiteError(
            f"'playwright' is not installed; the owned browser/DevTools scenario is blocked: {exc}",
            reason_code="playwright_missing",
        ) from exc
    return async_api


@pytest.mark.e2e
async def test_ui_browser_console_network(e2e_supervisor_factory) -> None:
    """Navigate the built admin UI over an owned CDP endpoint against a real fixture backend."""
    async_api = _require_playwright()

    botmanager_adapter = build_botmanager_adapter()
    ui_adapter = build_ui_adapter()
    browser_adapter = build_browser_adapter()
    adapters = {"botmanager": botmanager_adapter, "ui": ui_adapter, "browser": browser_adapter}
    supervisor: E2ESupervisor = e2e_supervisor_factory(lambda kind: adapters[kind])

    # 1. The isolated, authenticated fixture backend (TASK-3530).
    backend_state = await supervisor.start("ui-backend", TargetConfig(kind="botmanager", startup_timeout_s=30))
    backend_endpoint = botmanager_adapter._endpoints[backend_state.run_id]
    backend_url = f"http://{backend_endpoint.host}:{backend_endpoint.port}"

    # 2. The owned, isolated Obscura instance (deterministic default:
    #    profile="minimal", never options={"adopt": True}).
    browser_state = await supervisor.start("ui-browser", TargetConfig(kind="browser", startup_timeout_s=15))
    browser_endpoint = browser_adapter._endpoints[browser_state.run_id]

    # 3. The admin UI's real pnpm build/preview, pointed at the fixture backend.
    ui_state = await supervisor.start(
        "ui-frontend",
        TargetConfig(kind="ui", startup_timeout_s=120, options={"backend_url": backend_url}),
    )
    ui_endpoint = ui_adapter._endpoints[ui_state.run_id]
    admin_base_url = f"http://{ui_endpoint.host}:{ui_endpoint.port}"

    console_messages: list[dict[str, str]] = []
    network_responses: list[dict[str, Any]] = []

    def _on_console(message: Any) -> None:
        console_messages.append({"type": message.type, "text": message.text})

    def _on_response(response: Any) -> None:
        network_responses.append({"status": response.status, "url": response.url})

    try:
        async with async_api.async_playwright() as playwright:
            cdp_browser = await playwright.chromium.connect_over_cdp(browser_endpoint.manager.endpoint)
            try:
                context = cdp_browser.contexts[0] if cdp_browser.contexts else await cdp_browser.new_context()
                page = await context.new_page()
                page.on("console", _on_console)
                page.on("response", _on_response)

                # Fixed navigation/interaction: load the admin shell, then
                # navigate to the app's own real login route -- exercising
                # the client-side router, not just a single static load.
                await page.goto(
                    f"{admin_base_url}{_ADMIN_HOME_PATH}", wait_until="networkidle", timeout=_NAVIGATION_TIMEOUT_MS
                )
                title = await page.title()
                await page.goto(
                    f"{admin_base_url}{_ADMIN_LOGIN_PATH}", wait_until="networkidle", timeout=_NAVIGATION_TIMEOUT_MS
                )

                console_errors = [entry for entry in console_messages if entry["type"] == "error"]
                server_errors = [entry for entry in network_responses if entry["status"] >= 500]

                try:
                    assert title == _ADMIN_TITLE
                    assert console_errors == []
                    assert server_errors == []
                except AssertionError:
                    _capture_failure_diagnostics(
                        page,
                        run_id=ui_state.run_id,
                        worktree=supervisor.worktree,
                        console_messages=console_messages,
                        network_responses=network_responses,
                    )
                    raise
            finally:
                await cdp_browser.close()
    finally:
        for run_id in (ui_state.run_id, browser_state.run_id, backend_state.run_id):
            final_state = await supervisor.stop(run_id)
            assert final_state.cleanup_complete, f"supervisor did not clean up owned run {run_id}"


async def _capture_failure_diagnostics(
    page: Any,
    *,
    run_id: str,
    worktree: Path,
    console_messages: list[dict[str, str]],
    network_responses: list[dict[str, Any]],
) -> None:
    """Persist a screenshot and the captured console/network diagnostics on assertion failure.

    Args:
        page: The Playwright page under test at the moment of failure.
        run_id: The ``ui`` target's own run ID -- diagnostics are filed
            alongside its private run directory.
        worktree: The owning worktree root.
        console_messages: Every console message observed during this scenario.
        network_responses: Every network response observed during this scenario.
    """
    run_directory = e2e_state.run_dir(run_id, worktree=worktree)
    screenshot_path = run_directory / "failure-screenshot.png"
    diagnostics_path = run_directory / "failure-diagnostics.json"
    await page.screenshot(path=str(screenshot_path))
    diagnostics_path.write_text(
        json.dumps({"console_messages": console_messages, "network_responses": network_responses}, indent=2)
    )
