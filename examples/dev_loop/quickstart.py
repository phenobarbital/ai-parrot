"""FEAT-129 — Dev-Loop Orchestration: real-mode quickstart.

Wires the five-node ``AgentsFlow`` (BugIntake → Research → Development →
QA → DeploymentHandoff) with a real :class:`ClaudeCodeDispatcher`, a
service-account ``JiraToolkit``, and the CloudWatch / Elasticsearch log
toolkits, then runs it end-to-end against a sample :class:`BugBrief`.

Use ``server.py`` (next to this file) for a self-contained demo that does
not need Claude / Jira / GitHub credentials.

Run::

    source .venv/bin/activate
    python examples/dev_loop/quickstart.py

Required environment / navconfig settings:

* ``ANTHROPIC_API_KEY``           — for the Claude Agent SDK
* ``REDIS_URL``                   — defaults to ``redis://localhost:6379/0``
* ``JIRA_SERVER_URL``             — Jira Cloud / Server base URL
* ``FLOW_BOT_JIRA_TOKEN``         — service-account API token
* ``FLOW_BOT_JIRA_ACCOUNT_ID``    — accountId of the bot user
* ``AWS_REGION``                  — for CloudWatch (default ``us-east-1``)
* ``ELASTICSEARCH_URL``           — for the ES log toolkit
* ``WORKTREE_BASE_PATH``          — defaults to ``.claude/worktrees``
* ``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`` — defaults to ``3``
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from parrot import conf
from parrot.auth.credentials import StaticCredentialResolver, StaticCredentials
from parrot.flows.dev_loop import (
    BugBrief,
    ClaudeCodeDispatcher,
    FlowtaskCriterion,
    LogSource,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot_tools.aws.cloudwatch import CloudWatchToolkit
from parrot_tools.elasticsearch import ElasticsearchTool
from parrot_tools.jiratoolkit import JiraToolkit


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dev_loop.quickstart")


def _build_jira_toolkit() -> JiraToolkit:
    """Service-account JiraToolkit (flow-bot)."""
    resolver = StaticCredentialResolver(
        credentials=StaticCredentials(
            token=conf.config.get("FLOW_BOT_JIRA_TOKEN"),
            user_id="flow-bot",
        ),
    )
    return JiraToolkit(
        server_url=conf.config.get("JIRA_SERVER_URL"),
        auth_type="bearer",
        user_id="flow-bot",
        credential_resolver=resolver,
    )


def _build_log_toolkits() -> dict[str, object]:
    return {
        "cloudwatch": CloudWatchToolkit(
            region_name=conf.config.get("AWS_REGION", default="us-east-1"),
        ),
        "elasticsearch": ElasticsearchTool(
            host=conf.config.get("ELASTICSEARCH_HOST"),
            port=conf.config.get("ELASTICSEARCH_PORT", default=9200),
        ),
    }


def make_sample_brief() -> BugBrief:
    """A realistic bug the dev-loop can resolve."""
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
                locator="/etl/prod/customers",
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
        # Real Jira accountIds in your environment:
        reporter="557058:original-human",
        escalation_assignee="557058:on-call-engineer",
    )


async def main() -> None:
    redis_url = conf.config.get("REDIS_URL", default="redis://localhost:6379/0")

    dispatcher = ClaudeCodeDispatcher(
        max_concurrent=conf.config.get(
            "CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", default=3
        ),
        redis_url=redis_url,
        stream_ttl_seconds=conf.config.get(
            "FLOW_STREAM_TTL_SECONDS", default=604800
        ),
    )

    flow = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=_build_jira_toolkit(),
        log_toolkits=_build_log_toolkits(),
        redis_url=redis_url,
        name="dev-loop-customers-sync",
    )

    brief = make_sample_brief()
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    logger.info("Starting flow run_id=%s", run_id)

    result = await flow.run_flow(
        initial_task="resolve customer sync bug",
        bug_brief=brief,
        run_id=run_id,
    )

    logger.info("Flow run %s finished status=%s", run_id, result.status)
    for agent_name, output in result.outputs.items():
        logger.info("  %-22s -> %r", agent_name, output)


if __name__ == "__main__":
    asyncio.run(main())
