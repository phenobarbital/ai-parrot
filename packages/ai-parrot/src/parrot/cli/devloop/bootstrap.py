"""Embedded runtime bootstrap and preflight for ``parrot devloop``.

Checks real-mode prerequisites (Redis, claude CLI, Jira credentials,
worktree base path) and constructs the ``DevLoopRunner`` with all the
kwargs needed for both ``run()`` and ``run_revision()``.

Heavy imports (``parrot.conf``, ``parrot.flows.dev_loop.*``) are deferred
to function bodies so that ``parrot devloop --help`` stays fast.
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table


logger = logging.getLogger(__name__)


class PreflightCheck(BaseModel):
    """One preflight check result."""

    name: str
    passed: bool
    hint: str = ""


class PreflightResult(BaseModel):
    """Aggregated preflight outcome."""

    ok: bool
    checks: List[PreflightCheck] = Field(default_factory=list)


@dataclass
class DevLoopRuntime:
    """Holds the fully wired runtime components."""

    runner: Any  # DevLoopRunner
    flow: Any  # AgentsFlow
    dispatcher: Any  # ClaudeCodeDispatcher
    jira_toolkit: Any = None
    redis_url: str = ""
    reporter: str = ""
    escalation_assignee: str = ""


async def preflight(*, console: Optional[Console] = None) -> PreflightResult:
    """Run preflight checks and render results.

    Never raises — returns a PreflightResult with ``ok=False`` on failure.
    """
    checks: List[PreflightCheck] = []

    # 1. Redis URL
    try:
        from parrot import conf  # noqa: PLC0415
        redis_url = conf.config.get("REDIS_URL", fallback="")
    except Exception:
        redis_url = os.environ.get("REDIS_URL", "")

    if redis_url:
        checks.append(PreflightCheck(name="redis", passed=True))
    else:
        checks.append(PreflightCheck(
            name="redis", passed=False,
            hint="Set REDIS_URL in environment or parrot.conf",
        ))

    # 2. Claude CLI on PATH
    claude_found = shutil.which("claude") is not None
    checks.append(PreflightCheck(
        name="claude-cli", passed=claude_found,
        hint="" if claude_found else "Install Claude Code CLI: npm i -g @anthropic-ai/claude-code",
    ))

    # 3. Jira credentials
    jira_ok = False
    jira_hint = ""
    try:
        from parrot import conf  # noqa: PLC0415
        jira_url = getattr(conf, "JIRA_URL", "") or ""
        jira_user = getattr(conf, "JIRA_USERNAME", "") or ""
        jira_token = getattr(conf, "JIRA_API_TOKEN", "") or ""
        if jira_url and (jira_user or jira_token):
            jira_ok = True
        else:
            jira_hint = "Set JIRA_URL + JIRA_USERNAME/JIRA_API_TOKEN in parrot.conf"
    except Exception:
        jira_hint = "Configure Jira credentials in parrot.conf"
    checks.append(PreflightCheck(name="jira", passed=jira_ok, hint=jira_hint))

    # 4. Worktree base path
    try:
        from parrot import conf  # noqa: PLC0415
        wt_base = getattr(conf, "WORKTREE_BASE_PATH", "") or ""
    except Exception:
        wt_base = os.environ.get("WORKTREE_BASE_PATH", "")
    if wt_base:
        checks.append(PreflightCheck(name="worktree-base", passed=True))
    else:
        checks.append(PreflightCheck(
            name="worktree-base", passed=False,
            hint="Set WORKTREE_BASE_PATH in parrot.conf (e.g. /home/user/worktrees)",
        ))

    result = PreflightResult(ok=all(c.passed for c in checks), checks=checks)

    if console:
        _render_preflight(console, result)

    return result


def _render_preflight(console: Console, result: PreflightResult) -> None:
    """Render preflight results as a Rich table."""
    table = Table(title="Preflight Checks", show_lines=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Hint", style="dim")

    for check in result.checks:
        status = "[green]PASS[/green]" if check.passed else "[red]FAIL[/red]"
        table.add_row(check.name, status, check.hint)

    console.print(table)
    if result.ok:
        console.print("[green]All checks passed.[/green]\n")
    else:
        console.print("[red]Some checks failed. Fix the issues above before running.[/red]\n")


async def build_runtime(*, console: Optional[Console] = None) -> DevLoopRuntime:
    """Preflight, then construct the full DevLoopRunner.

    Mirrors the wiring from ``examples/dev_loop/quickstart.py``.

    Raises:
        SystemExit: If preflight fails.
    """
    con = console or Console()
    result = await preflight(console=con)
    if not result.ok:
        raise SystemExit(1)

    from parrot import conf  # noqa: PLC0415
    from parrot.flows.dev_loop import (  # noqa: PLC0415
        ClaudeCodeDispatcher,
        DevLoopRunner,
        build_dev_loop_flow,
    )

    redis_url = conf.config.get("REDIS_URL", fallback="redis://localhost:6379/0")

    dispatcher = ClaudeCodeDispatcher(
        max_concurrent=conf.config.get(
            "CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3
        ),
        redis_url=redis_url,
        stream_ttl_seconds=conf.config.get(
            "FLOW_STREAM_TTL_SECONDS", fallback=604800
        ),
    )

    jira_toolkit = _build_jira_toolkit()
    log_toolkits = _build_log_toolkits()

    flow = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        log_toolkits=log_toolkits,
        redis_url=redis_url,
    )

    reporter, escalation = await default_identities(jira_toolkit)

    runner = DevLoopRunner(
        flow,
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        git_toolkit=None,
        redis_url=redis_url,
        codereview_dispatcher=None,
    )

    return DevLoopRuntime(
        runner=runner,
        flow=flow,
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        redis_url=redis_url,
        reporter=reporter,
        escalation_assignee=escalation,
    )


async def default_identities(
    jira_toolkit: Any,
) -> Tuple[str, str]:
    """Resolve reporter and escalation identities.

    Falls back to ``$USER`` when Jira identity resolution is unavailable.
    """
    from parrot import conf  # noqa: PLC0415

    fallback = os.environ.get("USER", "cli-user")
    bot_account = getattr(conf, "FLOW_BOT_JIRA_ACCOUNT_ID", "") or ""

    reporter_raw = conf.config.get("JIRA_REPORTER_ACCOUNT_ID", fallback="") or bot_account
    escalation_raw = conf.config.get("JIRA_ESCALATION_ACCOUNT_ID", fallback="") or bot_account

    reporter = await _resolve_identity(jira_toolkit, reporter_raw) or fallback
    escalation = await _resolve_identity(jira_toolkit, escalation_raw) or fallback

    return reporter, escalation


async def _resolve_identity(jira_toolkit: Any, raw: str) -> str:
    """Resolve a Jira accountId or email to a usable identity string."""
    if not raw:
        return ""
    if jira_toolkit is None:
        return raw
    try:
        if hasattr(jira_toolkit, "resolve_account_id"):
            resolved = await jira_toolkit.resolve_account_id(raw)
            return resolved or raw
    except Exception:
        logger.debug("Jira identity resolution failed for %r", raw, exc_info=True)
    return raw


def _build_jira_toolkit() -> Any:
    """Build the JiraToolkit if Jira credentials are configured."""
    try:
        from parrot import conf  # noqa: PLC0415
        from parrot.tools.jira import JiraToolkit  # noqa: PLC0415

        return JiraToolkit(
            url=conf.JIRA_URL,
            username=getattr(conf, "JIRA_USERNAME", ""),
            api_token=getattr(conf, "JIRA_API_TOKEN", ""),
        )
    except Exception:
        logger.warning("JiraToolkit not available; Jira features disabled.")
        return None


def _build_log_toolkits() -> Dict[str, Any]:
    """Build log source toolkits (CloudWatch, etc.) from config."""
    toolkits: Dict[str, Any] = {}
    try:
        from parrot import conf  # noqa: PLC0415

        if hasattr(conf, "CLOUDWATCH_LOG_GROUP"):
            try:
                from parrot.tools.cloudwatch import CloudWatchToolkit  # noqa: PLC0415
                toolkits["cloudwatch"] = CloudWatchToolkit(
                    log_group=conf.CLOUDWATCH_LOG_GROUP,
                )
            except ImportError:
                pass
    except Exception:
        pass
    return toolkits
