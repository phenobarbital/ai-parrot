"""FEAT-129 / FEAT-250 — Dev-Loop Orchestration: real-mode quickstart.

Wires the eight-node ``AgentsFlow`` (IntentClassifier → [BugIntake →]
Research → Development → QA → DeploymentHandoff → Close, with a
FailureHandler ``on_error`` fan-in) with a real
:class:`ClaudeCodeDispatcher`, a service-account ``JiraToolkit``, and the
CloudWatch / Elasticsearch log toolkits, then runs it end-to-end against a
sample :class:`BugBrief` via :class:`DevLoopRunner`.

To update an existing PR instead of opening a new one, build the runner
with ``dispatcher=``, ``jira_toolkit=``, ``git_toolkit=`` and ``redis_url=``
and call ``DevLoopRunner.run_revision(RevisionBrief(...))`` — see
``e2e_demo.py`` scenario 6 and the README's "What FEAT-250 changed".

Use ``e2e_demo.py`` (next to this file) for a self-contained demo that does
not need Claude / Jira / GitHub credentials.

Run::

    source .venv/bin/activate
    python examples/dev_loop/quickstart.py

Required environment / navconfig settings:

* ``ANTHROPIC_API_KEY``           — for the Claude Agent SDK
* ``REDIS_URL``                   — defaults to ``redis://localhost:6379/0``
* ``JIRA_INSTANCE``               — Jira base URL
* ``JIRA_USERNAME``               — service-account username (basic_auth)
* ``JIRA_API_TOKEN``              — service-account API token / password
* ``JIRA_PROJECT``                — default Jira project key (e.g. ``NAV``)
* ``FLOW_BOT_JIRA_ACCOUNT_ID``    — accountId (or email) of the bot user;
  used as the fallback reporter / escalation identity
* ``JIRA_REPORTER_ACCOUNT_ID``    — reporter accountId or email (resolved to
  an accountId via ``jira_find_user``); falls back to the bot account
* ``JIRA_ESCALATION_ACCOUNT_ID``  — escalation assignee accountId or email;
  falls back to the bot account
* ``AWS_PROFILE``                 — boto3 profile (default ``cloudwatch``)
* ``CLOUDWATCH_LOG_GROUP``        — default log group (default
  ``fluent-bit-cloudwatch``); also used as the sample brief's log source
* ``WORKTREE_BASE_PATH``          — defaults to ``.claude/worktrees``
* ``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`` — defaults to ``3``
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from parrot import conf
from parrot.flows.dev_loop import (
    BugBrief,
    ClaudeCodeDispatcher,
    DevLoopRunner,
    FlowtaskCriterion,
    LogSource,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot_tools.aws.cloudwatch import CloudWatchToolkit
from parrot_tools.jiratoolkit import JiraToolkit


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dev_loop.quickstart")


def _build_jira_toolkit() -> JiraToolkit:
    """Service-account JiraToolkit (flow-bot, basic_auth)."""
    return JiraToolkit(
        server_url=conf.config.get("JIRA_INSTANCE"),
        auth_type="basic_auth",
        username=conf.config.get("JIRA_USERNAME"),
        password=conf.config.get("JIRA_API_TOKEN"),
        default_project=conf.config.get("JIRA_PROJECT"),
    )


def _build_log_toolkits() -> dict[str, object]:
    """Real-mode CloudWatch toolkit. Add Elasticsearch here if needed."""
    return {
        "cloudwatch": CloudWatchToolkit(
            aws_id=conf.config.get("AWS_PROFILE", fallback="cloudwatch"),
            default_log_group=conf.config.get(
                "CLOUDWATCH_LOG_GROUP", fallback="fluent-bit-cloudwatch"
            ),
        ),
    }


async def _resolve_identity(jira: JiraToolkit, value: str) -> str:
    """Resolve an email (or accountId) to a Jira accountId.

    The dev-loop sends ``reporter`` verbatim as ``{"accountId": ...}`` when
    creating the ticket, and Jira Cloud rejects an email in that slot
    (``400 Specify a valid value for reporter``). We resolve emails here via
    the toolkit's public ``jira_find_user`` so the brief always carries a
    real accountId.

    Args:
        jira: The service-account toolkit used for the lookup.
        value: An accountId (returned as-is) or an email to resolve.

    Returns:
        The resolved accountId, or ``""`` when ``value`` is empty or cannot
        be resolved — in which case the flow omits the reporter field and
        Jira falls back to the authenticated service account.
    """
    if not value:
        return ""
    if "@" not in value:
        return value  # already an accountId
    try:
        result = await jira.jira_find_user(value)
    except Exception as exc:  # noqa: BLE001 — example resilience
        logger.warning("Could not resolve Jira user %r: %s", value, exc)
        return ""
    matches = result.get("matches") or []
    if not result.get("found") or not matches:
        logger.warning("No Jira user found for %r; omitting it", value)
        return ""
    for match in matches:
        if (match.get("emailAddress") or "").lower() == value.lower():
            return match["accountId"]
    return matches[0]["accountId"]


def make_sample_brief(
    *, reporter: str, escalation_assignee: str, log_group: str
) -> BugBrief:
    """A realistic bug the dev-loop can resolve.

    Args:
        reporter: Resolved Jira accountId for the reporter (may be ``""``).
        escalation_assignee: Resolved Jira accountId for escalation on
            failure (may be ``""``).
        log_group: CloudWatch log group the ``ResearchNode`` should query.
    """
    return BugBrief(
        summary=(
            "Customer sync flowtask drops the last row when input has "
            ">1000 records. Reproduce: run etl/customers/sync.yaml against a "
            "1500-row CSV; the resulting Postgres table has 1499 rows."
        ),
        affected_component="etl/customers/sync.yaml",
        log_sources=[
            LogSource(
                kind="cloudwatch",
                locator=log_group,
                time_window_minutes=120,
            ),
        ],
        acceptance_criteria=[
            FlowtaskCriterion(
                name="customers-sync-no-row-drop",
                task_path="etl/customers/sync.yaml",
                args=["--input", "tests/fixtures/customers_1500.csv"],
                expected_exit_code=0,
                timeout_seconds=600,
            ),
            ShellCriterion(name="ruff-clean", command="ruff check ."),
            ShellCriterion(name="mypy-clean", command="mypy --no-incremental"),
        ],
        reporter=reporter,
        escalation_assignee=escalation_assignee,
    )


async def main() -> None:
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

    # Build the toolkit once and reuse it for both identity resolution and
    # the flow, so the lookup and the ticket creation share one client.
    jira_toolkit = _build_jira_toolkit()

    flow = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        log_toolkits=_build_log_toolkits(),
        redis_url=redis_url,
        name="dev-loop-customers-sync",
    )

    # Resolve reporter / escalation from the environment (accountId or email),
    # falling back to the bot account and finally to "" (omit → service
    # account). Avoids the hard-coded placeholder IDs that Jira rejects.
    bot_account = getattr(conf, "FLOW_BOT_JIRA_ACCOUNT_ID", "") or ""
    reporter = await _resolve_identity(
        jira_toolkit,
        conf.config.get("JIRA_REPORTER_ACCOUNT_ID") or bot_account,
    )
    escalation_assignee = await _resolve_identity(
        jira_toolkit,
        conf.config.get("JIRA_ESCALATION_ACCOUNT_ID") or bot_account,
    )
    log_group = conf.config.get(
        "CLOUDWATCH_LOG_GROUP", fallback="fluent-bit-cloudwatch"
    )

    brief = make_sample_brief(
        reporter=reporter,
        escalation_assignee=escalation_assignee,
        log_group=log_group,
    )
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    logger.info("Starting flow run_id=%s", run_id)

    runner = DevLoopRunner(flow)
    result = await runner.run(
        brief,
        run_id=run_id,
        initial_task="resolve customer sync bug",
    )

    logger.info("Flow run %s finished status=%s", run_id, result.status)
    for node_id, response in result.responses.items():
        logger.info("  %-22s -> %r", node_id, response)
    if result.errors:
        for node_id, error in result.errors.items():
            logger.error("  %-22s !! %s", node_id, error)


if __name__ == "__main__":
    asyncio.run(main())
