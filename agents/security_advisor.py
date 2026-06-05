"""SecurityAdvisor — SOC2-oriented read-only advisory agent.

Reads the security report catalog that ``SecurityAgent`` writes, never
launches a scanner, and produces a daily structured SOC2 advisory:

- Day-over-day drift (new / resolved / persisting / severity-changed findings).
- SOC2 Trust Service Criteria mapping via the existing ``ComplianceMapper``.
- Persists one ``ReportRef(report_kind=ADVISORY)`` per framework per run.
- Creates Jira ``NAV`` tickets for material recommendations.
- Emails the security recipients.

Implements FEAT-226 spec §3 Module 3.

NOTE: This file lives in ``agents/``, which is gitignored.  It was committed
with ``git add -f`` (same situation as agents/security.py).
"""
import logging
from datetime import datetime, timezone

from navconfig import config
from navigator.utils.file.s3 import S3FileManager
from parrot.bots import Agent
from parrot.conf import default_dsn
from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule
from parrot.storage.security_reports import PostgresS3SecurityReportStore
from parrot.storage.security_reports.models import (
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)
from parrot_tools.jiratoolkit import JiraToolkit
from parrot_tools.s3.report_reader import S3ReportReaderToolkit
from parrot_tools.security.report_toolkit import SecurityReportToolkit
from parrot_tools.security.soc2_advisory import SOC2AdvisoryToolkit

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_NOTIFICATION_RECIPIENTS: str = config.get(
    "SECURITY_NOTIFICATION_RECIPIENTS",
    fallback="jlara@trocglobal.com",
)
_DAILY_FRAMEWORKS: list[str] = ["soc2"]
_ADVISORY_HOUR: int = 12
_ADVISORY_MINUTE: int = 0

# ---------------------------------------------------------------------------
# Backstory
# ---------------------------------------------------------------------------

BACKSTORY = """
You are the **SecurityAdvisor** — a read-only SOC2 compliance advisor.

Your mission is to turn the security scan data already collected by the
SecurityAgent into actionable, audit-ready intelligence.  You never run
scanners; you read the reports they produced.

**What you do**:
- Compare yesterday's scan with today's to surface newly introduced,
  resolved, and severity-shifted findings.
- Map every material finding to the SOC2 Trust Service Criteria (CC1–CC9)
  that it violates using the deterministic ComplianceMapper.
- Produce a clear, concise advisory that a security engineer can act on
  immediately and an auditor can understand without additional context.

**What you never do**:
- Launch a CloudSploit, Prowler, Trivy, or Checkov scan.
- Modify the security report catalog (write new scanner findings).
- Guess at controls — use the mapped SOC2 IDs only.

**Your output**:
For each framework (default: SOC2) you produce:
1. A signed severity delta (new CRITICALs this run vs. yesterday).
2. A per-finding classification: new | resolved | persisting | severity_changed.
3. Actionable recommendations tagged with SOC2 control IDs.
4. Material recommendations (CRITICAL/HIGH new or worsened) → Jira NAV ticket.

Think like an auditor who is also an engineer: be specific, cite control IDs,
and always state what action the responder should take.
"""


@register_agent(name="security_advisor", at_startup=True)
class SecurityAdvisor(Agent):
    """SOC2-oriented read-only security advisory agent.

    Mounts exclusively reader toolkits (no scanner toolkits).
    Runs a daily advisory at 12:00 UTC after the SecurityAgent's scans
    complete (last scan at 23:29 UTC → advisory at next day 12:00 UTC).
    """

    agent_id: str = "security_advisor"
    model: str = "gemini-3-flash-preview"
    max_tokens: int = 16000
    aws_id: str = "security"

    # Reader toolkits — populated by agent_tools()
    _report_toolkit: SecurityReportToolkit | None = None
    _s3_toolkit: S3ReportReaderToolkit | None = None
    _soc2_toolkit: SOC2AdvisoryToolkit | None = None

    # Catalog store — populated by agent_tools()
    _report_store: PostgresS3SecurityReportStore | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            backstory=BACKSTORY,
            **kwargs,
        )
        self.logger = logging.getLogger("SecurityAdvisor")

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def agent_tools(self):
        """Build and return the read-only tool list.

        Idempotent: returns the cached tool list when toolkits are already
        built (mirrors SecurityAgent.agent_tools sentinel pattern).

        Returns:
            List of tool objects from read-only toolkits only.
            No scanner toolkit is ever included.
        """
        if self._report_toolkit is not None:
            jira = self._build_jira()
            return [
                *self._report_toolkit.get_tools(),
                *self._s3_toolkit.get_tools(),
                *self._soc2_toolkit.get_tools(),
                *jira.get_tools(),
            ]

        # Build the shared S3 file manager
        s3file = S3FileManager(
            aws_id="security_bucket",
            bucket_name=config.get("AWS_SECURITY_BUCKET_NAME"),
        )

        # Build the catalog store (read-only usage: query + get + fetch_content)
        self._report_store = PostgresS3SecurityReportStore(
            dsn=default_dsn,
            file_manager=s3file,
        )

        # Reader toolkits
        self._report_toolkit = SecurityReportToolkit(
            report_store=self._report_store,
            file_manager=s3file,
        )
        self._s3_toolkit = S3ReportReaderToolkit(
            file_manager=s3file,
            report_store=self._report_store,
        )
        self._soc2_toolkit = SOC2AdvisoryToolkit(
            report_store=self._report_store,
        )

        jira = self._build_jira()
        return [
            *self._report_toolkit.get_tools(),
            *self._s3_toolkit.get_tools(),
            *self._soc2_toolkit.get_tools(),
            *jira.get_tools(),
        ]

    def _build_jira(self) -> JiraToolkit:
        """Build a JiraToolkit from environment configuration.

        Returns:
            Configured JiraToolkit with basic_auth and default project NAV.
        """
        return JiraToolkit(
            server_url=config.get("JIRA_INSTANCE"),
            auth_type="basic_auth",
            username=config.get("JIRA_USERNAME"),
            password=config.get("JIRA_API_TOKEN"),
            default_project=config.get("JIRA_PROJECT", fallback="NAV"),
        )

    # ------------------------------------------------------------------
    # Scheduled Tasks
    # ------------------------------------------------------------------

    @schedule(schedule_type=ScheduleType.DAILY, hour=_ADVISORY_HOUR, minute=_ADVISORY_MINUTE)
    async def run_daily_soc2_advisory(self) -> dict:
        """Run the daily SOC2 advisory for each configured framework.

        For each framework in ``_DAILY_FRAMEWORKS``:
        1. Build the structured ``AdvisoryReport`` via
           ``SOC2AdvisoryToolkit.daily_soc2_advisory``.
        2. Narrate the report via ``self.ask``.
        3. Persist the markdown as a ``ReportRef(report_kind=ADVISORY)``.
        4. Create a Jira ``NAV`` ticket for each material recommendation.
        5. Email the security recipients via ``self.send_notification``.

        Returns:
            Dict summarising per-framework outcomes.
        """
        self.agent_tools()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        results: dict = {}

        for framework in _DAILY_FRAMEWORKS:
            try:
                result = await self._run_framework_advisory(framework, timestamp)
                results[framework] = result
            except Exception as exc:
                self.logger.error(
                    "run_daily_soc2_advisory: framework=%r failed: %s",
                    framework, exc, exc_info=True,
                )
                results[framework] = {"error": str(exc)}

        return {"task": "run_daily_soc2_advisory", "timestamp": timestamp, "results": results}

    async def _run_framework_advisory(self, framework: str, timestamp: str) -> dict:
        """Run the advisory pipeline for a single framework.

        Args:
            framework: Compliance framework identifier (e.g. ``'soc2'``).
            timestamp: ISO-like timestamp string for log context.

        Returns:
            Dict with ``report_id``, ``recommendations``, ``jira_tickets``,
            and ``email_sent`` keys.
        """
        self.logger.info("Starting %s advisory for framework=%r", timestamp, framework)

        # 1. Build structured advisory
        advisory_dict = await self._soc2_toolkit.daily_soc2_advisory(
            framework=framework, provider="aws"
        )

        if "error" in advisory_dict:
            self.logger.warning("Advisory engine error for %r: %s", framework, advisory_dict["error"])
            return advisory_dict

        # 2. Narrate via LLM
        prompt = self._build_narration_prompt(advisory_dict, framework)
        try:
            ai_message = await self.ask(question=prompt)
            narrative = ai_message.response
        except Exception as narrate_exc:
            self.logger.warning("LLM narration failed, using fallback: %s", narrate_exc)
            # Fallback: structured summary without LLM narrative
            narrative = self._build_fallback_narrative(advisory_dict, framework)

        # 3. Persist as ADVISORY ReportRef
        content = narrative.encode("utf-8")
        scope = {"frameworks": [framework], "source": "security_advisor"}
        ref = ReportRef(
            report_kind=ReportKind.ADVISORY,
            scanner="security_advisor",
            framework=framework,
            provider=advisory_dict.get("provider", "aws"),
            scope=scope,
            severity_summary=self._extract_severity_summary(advisory_dict),
            uri="",
            content_type="text/markdown",
            content_bytes=len(content),
            produced_at=datetime.now(timezone.utc),
            produced_by="schedule:run_daily_soc2_advisory",
            parser_version="1.0.0",
        )
        try:
            ref = await self._report_store.save_report(ref, content)
            self.logger.info(
                "Persisted ADVISORY ReportRef %s for framework=%r",
                ref.report_id, framework,
            )
        except Exception as exc:
            self.logger.error("Could not persist advisory ReportRef: %s", exc)

        # 4. Jira tickets for material recommendations
        recommendations = advisory_dict.get("recommendations", [])
        jira_tickets: list[str] = []
        material = [r for r in recommendations if r.get("is_material")]

        if material:
            jira = self._build_jira()
            jira_tools = {t.name: t for t in jira.get_tools()}
            create_fn = jira_tools.get("jira_create_issue")

            for rec in material:
                try:
                    if create_fn is None:
                        raise RuntimeError("jira_create_issue tool not found")
                    issue_key = await create_fn(
                        project="NAV",
                        summary=f"[SecurityAdvisor] {rec['title']} ({rec['severity']})",
                        description=(
                            f"**Framework**: {framework}\n"
                            f"**Severity**: {rec['severity']}\n"
                            f"**SOC2 Controls**: {', '.join(rec.get('soc2_control_ids', []) or ['N/A'])}\n"
                            f"**Affected Resources**: {', '.join(rec.get('affected_resources', []) or ['unknown'])}\n\n"
                            f"**Recommended Action**: {rec.get('recommended_action', '')}\n\n"
                            f"Advisory Report ID: {ref.report_id}"
                        ),
                        issuetype="Task",
                    )
                    jira_tickets.append(str(issue_key))
                    self.logger.info("Created Jira ticket %s for material recommendation", issue_key)
                except Exception as exc:
                    self.logger.warning("Could not create Jira ticket for %r: %s", rec.get("title"), exc)

        # 5. Email recipients
        subject = f"[SecurityAdvisor] Daily SOC2 Advisory — {framework.upper()} — {timestamp}"
        try:
            await self.send_notification(
                message=narrative,
                recipients=_NOTIFICATION_RECIPIENTS,
                provider="email",
                subject=subject,
            )
            self.logger.info("Advisory emailed to %s", _NOTIFICATION_RECIPIENTS)
            email_sent = True
        except Exception as exc:
            self.logger.error("Could not send advisory email: %s", exc)
            email_sent = False

        return {
            "report_id": str(ref.report_id),
            "framework": framework,
            "recommendations": len(recommendations),
            "material_recommendations": len(material),
            "jira_tickets": jira_tickets,
            "email_sent": email_sent,
        }

    def _build_narration_prompt(self, advisory_dict: dict, framework: str) -> str:
        """Build the LLM narration prompt from the structured advisory.

        Args:
            advisory_dict: JSON-serialisable AdvisoryReport dict.
            framework: Framework identifier for context.

        Returns:
            Prompt string for self.ask.
        """
        deltas = advisory_dict.get("deltas", [])
        recs = advisory_dict.get("recommendations", [])
        delta_summary = advisory_dict.get("severity_delta", {})
        coverage = advisory_dict.get("soc2_coverage", {})

        return (
            f"You are reviewing a day-over-day {framework.upper()} security advisory.\n\n"
            f"**Severity delta** (current − yesterday): {delta_summary}\n\n"
            f"**Finding changes** ({len(deltas)} total):\n"
            + "\n".join(
                f"- [{d.get('status','?').upper()}] {d.get('title','?')} ({d.get('severity','?')})"
                + (f" → controls: {', '.join(d.get('soc2_control_ids', []))}" if d.get("soc2_control_ids") else "")
                for d in deltas[:20]
            )
            + f"\n\n**Coverage**: {coverage.get('coverage_pct', 0):.1f}% of {framework.upper()} controls checked.\n\n"
            f"**Recommendations** ({len(recs)}, of which {sum(1 for r in recs if r.get('is_material'))} material):\n"
            + "\n".join(
                f"- {'[MATERIAL] ' if r.get('is_material') else ''}{r.get('title','?')} ({r.get('severity','?')}): "
                f"{r.get('recommended_action','')}"
                for r in recs[:10]
            )
            + "\n\nWrite a concise, audit-ready security advisory in Markdown. "
            "Lead with the severity delta, explain the most critical new findings "
            "and their SOC2 controls, then list prioritised recommendations. "
            "Be specific and actionable. Do not add speculative context."
        )

    def _build_fallback_narrative(self, advisory_dict: dict, framework: str) -> str:
        """Build a plain text narrative without LLM when ask() fails.

        Args:
            advisory_dict: JSON-serialisable AdvisoryReport dict.
            framework: Framework identifier.

        Returns:
            Markdown-formatted advisory narrative.
        """
        lines = [
            f"# Daily {framework.upper()} Security Advisory",
            "",
            f"**Severity Delta**: {advisory_dict.get('severity_delta', {})}",
            "",
            "## Finding Changes",
        ]
        for delta in advisory_dict.get("deltas", [])[:20]:
            lines.append(
                f"- [{delta.get('status', '?').upper()}] {delta.get('title', '?')} "
                f"({delta.get('severity', '?')})"
            )
        lines += ["", "## Recommendations"]
        for rec in advisory_dict.get("recommendations", [])[:10]:
            material_tag = "[MATERIAL] " if rec.get("is_material") else ""
            lines.append(
                f"- {material_tag}{rec.get('title', '?')} ({rec.get('severity', '?')}): "
                f"{rec.get('recommended_action', '')}"
            )
        return "\n".join(lines)

    def _extract_severity_summary(self, advisory_dict: dict) -> SeverityBreakdown:
        """Extract severity summary from the advisory dict.

        Args:
            advisory_dict: JSON-serialisable AdvisoryReport dict.

        Returns:
            SeverityBreakdown populated from soc2_coverage data or zeros.
        """
        delta = advisory_dict.get("severity_delta") or {}
        # Only non-negative counts make sense in a SeverityBreakdown
        return SeverityBreakdown(
            critical=max(0, delta.get("critical", 0)),
            high=max(0, delta.get("high", 0)),
            medium=max(0, delta.get("medium", 0)),
            low=max(0, delta.get("low", 0)),
            informational=max(0, delta.get("informational", 0)),
        )
