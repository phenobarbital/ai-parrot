"""SecurityAdvisor v2 — grounded, read-only security advisory agent.

Evolution of the original FEAT-226 §3 Module 3 agent. Same read-only
invariant (never launches a scanner, never writes scanner findings),
three additions:

1. **Knowledge grounding** — two knowledge bases mounted as tools:
   - Remediation KB (PgVector) via ``VectorStoreSearchTool`` — curated,
     citable remediation sources (Prowler check remediation metadata,
     AWS Security Hub control remediation docs, CIS benchmark extracts,
     internal runbooks). Populated by ``scripts/load_remediation_kb.py``.
   - Compliance graph (GraphIndex, SQLite plane) via ``GraphMemoryMixin``
     — NIST SP 800-53 (OSCAL) controls + TSC↔800-53 mapping as graph
     nodes/edges. Populated by ``scripts/load_compliance_graph.py``.
     Exposes ``find_node`` / ``traverse`` / ``ground_claim`` etc. as tools.

2. **Structured, citation-audited outputs** — every LLM-produced
   recommendation is a Pydantic ``RemediationItem`` whose ``references``
   list is mandatory; citations are re-checked against the remediation
   KB (``_audit_citations``) and unvalidated items are routed to human
   review instead of Jira.

3. **Skills** — operations are documented as composite skills
   (``agents/security_advisor/skills/security_advisor/*/SKILL.md``)
   discovered through ``SkillRegistryMixin`` (``skill_paths``), injected
   into the system prompt as an ``<available_skills>`` layer and
   triggerable on demand.

Scheduled operations (all persist a ``ReportRef(report_kind=ADVISORY)``):
- ``run_daily_soc2_advisory``   — daily 12:00 UTC (drift + remediation).
- ``run_weekly_insights``       — Monday 13:00 UTC (trend insights).
- ``run_compliance_gap``        — Friday 13:00 UTC (SOC2/NIST gap analysis).

NOTE: This file lives in ``agents/``, which is gitignored. Commit with
``git add -f`` (same situation as agents/security.py).
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from navconfig import config
from navigator.utils.file.s3 import S3FileManager
from parrot.bots import Agent
from parrot.conf import default_dsn
from parrot.knowledge.graphindex.mixin import GraphMemoryMixin
from parrot.models.stores import StoreConfig
from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule
from parrot.skills import SkillRegistryMixin
from parrot.storage.security_reports import (
    PostgresS3SecurityReportStore,
    ReportFilter,
)
from parrot.storage.security_reports.models import (
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)
from parrot.tools.vectorstoresearch import VectorStoreSearchTool
from parrot_tools.jiratoolkit import JiraToolkit
from parrot_tools.s3.report_reader import S3ReportReaderToolkit
from parrot_tools.security.report_toolkit import SecurityReportToolkit
from parrot_tools.security.soc2_advisory import SOC2AdvisoryToolkit
from parrot_tools.security.summarizer import WeeklySecuritySummarizer

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

# Remediation KB (PgVector) — table created by scripts/load_remediation_kb.py
_REMEDIATION_KB_TABLE: str = config.get(
    "SECURITY_REMEDIATION_KB_TABLE", fallback="security_remediation_kb"
)
_REMEDIATION_KB_SCHEMA: str = config.get(
    "SECURITY_REMEDIATION_KB_SCHEMA", fallback="public"
)
_REMEDIATION_KB_MODEL: str = config.get(
    "SECURITY_REMEDIATION_KB_MODEL",
    fallback="sentence-transformers/all-mpnet-base-v2",
)

# Compliance graph plane (GraphIndex / SQLite) — populated by
# scripts/load_compliance_graph.py. Must point at the SAME directory.
_COMPLIANCE_GRAPH_DIR: str = config.get(
    "SECURITY_COMPLIANCE_GRAPH_DIR", fallback=None
)

# Skills directory (composite {name}/SKILL.md layout). The default is
# anchored to this file so it works regardless of the process CWD.
_SKILLS_DIR: str = config.get(
    "SECURITY_ADVISOR_SKILLS_DIR",
    fallback=str(
        Path(__file__).resolve().parent
        / "security_advisor" / "skills" / "security_advisor"
    ),
)

# Jira tools exposed to the LLM. Read-only on purpose: ticket creation is
# programmatic (``_create_jira_ticket``) and the agent's advisory boundary
# must not let the model transition/assign/edit issues on its own.
_JIRA_LLM_TOOLS: frozenset = frozenset({
    "jira_get_issue",
    "jira_search_issues",
    "jira_count_issues",
    "jira_get_projects",
})


# ---------------------------------------------------------------------------
# Structured output contracts (grounding is enforced here)
# ---------------------------------------------------------------------------

class SourceRef(BaseModel):
    """A citation into one of the mounted knowledge bases."""

    title: str = Field(description="Title of the cited KB document/chunk")
    source: str = Field(
        description=(
            "URL or doc_id exactly as returned by remediation_kb_search "
            "or a graph node_id returned by the graph tools. Never invent."
        )
    )
    snippet: str = Field(
        description="Short verbatim excerpt from the retrieved chunk"
    )


class RemediationItem(BaseModel):
    """One actionable remediation, grounded in the remediation KB."""

    finding_ids: list[str] = Field(default_factory=list)
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    affected_resources: list[str] = Field(default_factory=list)
    control_ids: list[str] = Field(
        default_factory=list,
        description="Mapped control ids (SOC2 CC*, NIST 800-53) — only ids "
        "present in the advisory data or the compliance graph.",
    )
    steps: list[str] = Field(
        min_length=1,
        description="Concrete remediation steps (CLI / Terraform / console).",
    )
    references: list[SourceRef] = Field(
        min_length=1,
        description="MANDATORY citations. An item without at least one KB "
        "reference must not be produced — say so in `notes` instead.",
    )
    notes: Optional[str] = None
    validated: bool = Field(
        default=False,
        description="Set by the citation audit, not by the model.",
    )


class RemediationReport(BaseModel):
    """Structured remediation advisory for one framework run."""

    framework: str
    items: list[RemediationItem] = Field(default_factory=list)
    ungrounded_findings: list[str] = Field(
        default_factory=list,
        description="Finding titles for which NO KB evidence was retrieved "
        "— escalated to human review instead of guessed at.",
    )


class InsightItem(BaseModel):
    """A short/medium-term improvement derived from observed patterns."""

    title: str
    horizon: Literal["short_term", "medium_term"]
    pattern: str = Field(
        description="The recurring pattern in the scan history that "
        "motivates this insight (cite finding titles / counts)."
    )
    recommendation: str
    references: list[SourceRef] = Field(default_factory=list)


class InsightsReport(BaseModel):
    period_start: str
    period_end: str
    insights: list[InsightItem] = Field(default_factory=list)


class ComplianceGap(BaseModel):
    framework: Literal["soc2", "nist_800_53", "nist_csf"]
    control_id: str
    status: Literal["covered", "gap", "no_evidence"]
    evidence: str = Field(
        description="What scan evidence supports this status (report ids, "
        "check names). 'no_evidence' means no scanner covers the control."
    )
    missing_evidence: Optional[str] = None
    graph_refs: list[str] = Field(
        default_factory=list,
        description="Graph node_ids consulted (from find_node/traverse).",
    )


class ComplianceGapReport(BaseModel):
    framework: str
    coverage_pct: float
    gaps: list[ComplianceGap] = Field(default_factory=list)
    auditor_questions: list[str] = Field(
        default_factory=list,
        description="Questions an auditor would ask given the current gaps.",
    )


# ---------------------------------------------------------------------------
# Backstory
# ---------------------------------------------------------------------------

BACKSTORY = """
You are the **SecurityAdvisor** — a read-only, evidence-grounded security
and compliance advisor.

Your mission is to turn the security scan data already collected by the
SecurityAgent into actionable, audit-ready intelligence. You never run
scanners; you read the reports they produced.

**Grounding rules (non-negotiable)**:
- Remediation guidance MUST come from the `remediation_kb_search` tool.
  Search it BEFORE writing any remediation step. Every RemediationItem
  needs at least one reference whose `source` is a real URL/doc_id
  returned by the tool. If the KB returns nothing relevant, put the
  finding in `ungrounded_findings` — never fill the gap from memory.
- Control mappings MUST come from the advisory data (deterministic
  ComplianceMapper) or from the compliance graph tools (`find_node`,
  `traverse`, `get_neighborhood`). Use `ground_claim` to check any
  compliance assertion before you state it. Never guess control ids.
- You produce gap analyses and audit-readiness reports — you never claim
  to certify SOC2 or NIST compliance (only an auditor can).

**What you never do**:
- Launch a CloudSploit, Prowler, Trivy, or Checkov scan.
- Modify the security report catalog (write new scanner findings).
- Invent citations, control ids, or remediation steps.

Think like an auditor who is also an engineer: be specific, cite control
ids and sources, and always state what action the responder should take.
"""


@register_agent(name="security_advisor", at_startup=True)
class SecurityAdvisor(SkillRegistryMixin, GraphMemoryMixin, Agent):
    """Grounded read-only security advisory agent.

    Mounts exclusively reader toolkits and knowledge tools (no scanner
    toolkits). The read-only invariant of ``tests/test_security_advisor``
    is preserved: none of the mounted tools launches a scan.
    """

    agent_id: str = "security_advisor"
    model: str = "gemini-3-flash-preview"
    max_tokens: int = 16000
    aws_id: str = "security"

    # --- GraphMemoryMixin configuration (compliance graph) ---
    enable_graph_memory: bool = True
    graph_memory_path: Optional[str] = _COMPLIANCE_GRAPH_DIR  # None → AGENTS_DIR default
    graph_memory_tenant: str = "security"
    graph_memory_inject_context: bool = True
    graph_memory_dimension: int = 256

    # --- SkillRegistryMixin configuration ---
    enable_skill_registry: bool = True
    skill_paths: list[Path] = [Path(_SKILLS_DIR)]
    inject_skills_into_prompt: bool = True
    skill_registry_auto_extract: bool = False

    # Reader toolkits — populated by agent_tools()
    _report_toolkit: SecurityReportToolkit | None = None
    _s3_toolkit: S3ReportReaderToolkit | None = None
    _soc2_toolkit: SOC2AdvisoryToolkit | None = None
    _jira_toolkit: JiraToolkit | None = None
    _remediation_tool: VectorStoreSearchTool | None = None

    # Catalog store — populated by agent_tools()
    _report_store: PostgresS3SecurityReportStore | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            backstory=BACKSTORY,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Configuration — wire the opt-in mixins
    # ------------------------------------------------------------------

    async def configure(self, app=None) -> None:
        """Configure the agent, then its skill registry and graph memory.

        Both mixins are opt-in: their ``_configure_*`` hooks must be
        called explicitly (idempotent, safe on multi-configure hosts).
        ``_configure_graph_memory`` registers the GraphIndexToolkit tools
        (find_node/traverse/ground_claim/...) on ``self.tool_manager``.
        """
        await super().configure(app)
        await self._configure_skill_registry()
        await self._configure_graph_memory()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def agent_tools(self):
        """Build and return the read-only tool list.

        Idempotent: returns the cached tool list when toolkits are
        already built. No scanner toolkit is ever included. The
        compliance-graph tools are registered separately by
        ``_configure_graph_memory`` (they live on the tool manager).
        """
        if self._report_toolkit is not None:
            return [
                *self._report_toolkit.get_tools(),
                *self._s3_toolkit.get_tools(),  # type: ignore[union-attr]
                *self._soc2_toolkit.get_tools(),  # type: ignore[union-attr]
                *self._jira_llm_tools(),
                self._remediation_tool,
            ]

        # Shared S3 file manager
        s3file = S3FileManager(
            aws_id="security_bucket",
            bucket_name=config.get("AWS_SECURITY_BUCKET_NAME"),
        )

        # Catalog store (read-only usage: query + get + fetch_content)
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

        # Remediation KB search tool (PgVector)
        self._remediation_tool = VectorStoreSearchTool(
            store_config=StoreConfig(
                vector_store="postgres",
                table=_REMEDIATION_KB_TABLE,
                schema=_REMEDIATION_KB_SCHEMA,
                embedding_model={
                    "model_name": _REMEDIATION_KB_MODEL,
                    "model_type": "huggingface",
                },
                dimension=768,
                dsn=default_dsn,
                auto_create=False,
            ),
            name="remediation_kb_search",
            description=(
                "Similarity search over the curated remediation knowledge "
                "base (Prowler/CloudSploit check remediation metadata, AWS "
                "Security Hub control remediation docs, CIS benchmark "
                "extracts, internal runbooks). Returns documents whose "
                "metadata includes source_url, rule_id, service and "
                "framework refs. ALWAYS search here before writing "
                "remediation steps, and cite the returned source_url/doc_id."
            ),
        )

        return [
            *self._report_toolkit.get_tools(),
            *self._s3_toolkit.get_tools(),
            *self._soc2_toolkit.get_tools(),
            *self._jira_llm_tools(),
            self._remediation_tool,
        ]

    def _jira_llm_tools(self) -> list:
        """Read-only subset of Jira tools exposed to the LLM.

        Write tools (create/update/transition/assign) stay out of the
        model's reach — ticket creation happens programmatically in
        ``_create_jira_ticket`` for validated items only.
        """
        jira = self._build_jira()
        return [t for t in jira.get_tools() if t.name in _JIRA_LLM_TOOLS]

    def _build_jira(self) -> JiraToolkit:
        """Build (or return cached) JiraToolkit from environment config."""
        if self._jira_toolkit is not None:
            return self._jira_toolkit
        self._jira_toolkit = JiraToolkit(
            server_url=config.get("JIRA_INSTANCE"),
            auth_type="basic_auth",
            username=config.get("JIRA_USERNAME"),
            password=config.get("JIRA_API_TOKEN"),
            default_project=config.get("JIRA_PROJECT", fallback="NAV"),
        )
        return self._jira_toolkit

    # ------------------------------------------------------------------
    # Citation audit — programmatic anti-hallucination check
    # ------------------------------------------------------------------

    async def _audit_citations(self, report: RemediationReport) -> RemediationReport:
        """Re-query the remediation KB and validate every citation.

        For each item, runs a fresh similarity search on the item's title
        and marks ``validated=True`` only when at least one cited
        ``source`` actually appears in the retrieved corpus. Items that
        fail the audit keep ``validated=False`` and are excluded from
        automated Jira creation (human review instead).
        """
        if self._remediation_tool is None:
            return report
        for item in report.items:
            query = f"{item.title} {' '.join(item.control_ids)}".strip()
            try:
                result = await self._remediation_tool.execute(query=query, limit=8)
                corpus = str(getattr(result, "result", None) or result)
            except Exception as exc:  # noqa: BLE001 — audit is best-effort
                self.logger.warning("Citation audit search failed: %s", exc)
                continue
            item.validated = any(
                ref.source and ref.source in corpus for ref in item.references
            )
            if not item.validated:
                self.logger.warning(
                    "Citation audit FAILED for %r — routed to human review",
                    item.title,
                )
        return report

    # ------------------------------------------------------------------
    # Graph context injection
    # ------------------------------------------------------------------

    async def _with_graph_context(self, prompt: str) -> str:
        """Prepend compliance-graph context to a prompt.

        ``GraphMemoryMixin`` registers the graph tools but nothing in the
        framework calls ``_build_graph_context`` during ``ask()`` — the
        ``graph_memory_inject_context`` flag is honoured manually here for
        the compliance-relevant flows (remediation + gap analysis).
        """
        try:
            context = await self._build_graph_context(prompt)
        except Exception as exc:  # noqa: BLE001 — context is best-effort
            self.logger.warning("Graph context build failed: %s", exc)
            return prompt
        if not context:
            return prompt
        return (
            f"## Compliance graph context\n\n{context}\n\n---\n\n{prompt}"
        )

    # ------------------------------------------------------------------
    # Scheduled Task 1 — daily drift + grounded remediation
    # ------------------------------------------------------------------

    @schedule(schedule_type=ScheduleType.DAILY, hour=_ADVISORY_HOUR, minute=_ADVISORY_MINUTE)
    async def run_daily_soc2_advisory(self) -> dict:
        """Daily advisory: drift narration + grounded remediation report.

        Per framework: build the deterministic ``AdvisoryReport``,
        narrate it, then produce a structured ``RemediationReport`` for
        material recommendations (citations mandatory + audited),
        persist both as one ADVISORY ``ReportRef``, open Jira tickets
        for *validated* material items only, email the recipients.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        results: dict = {}

        for framework in _DAILY_FRAMEWORKS:
            try:
                results[framework] = await self._run_framework_advisory(
                    framework, timestamp
                )
            except Exception as exc:
                self.logger.error(
                    "run_daily_soc2_advisory: framework=%r failed: %s",
                    framework, exc, exc_info=True,
                )
                results[framework] = {"error": str(exc)}

        return {"task": "run_daily_soc2_advisory", "timestamp": timestamp, "results": results}

    async def _run_framework_advisory(self, framework: str, timestamp: str) -> dict:
        """Advisory pipeline for a single framework."""
        self.logger.info("Starting %s advisory for framework=%r", timestamp, framework)

        # 1. Deterministic advisory (drift, mapping, materiality)
        advisory_dict = await self._soc2_toolkit.daily_soc2_advisory(
            framework=framework, provider="aws"
        )
        if "error" in advisory_dict:
            self.logger.warning(
                "Advisory engine error for %r: %s", framework, advisory_dict["error"]
            )
            return advisory_dict

        # 2. Narrative (unchanged behaviour, with fallback)
        try:
            ai_message = await self.ask(
                question=self._build_narration_prompt(advisory_dict, framework)
            )
            narrative = ai_message.response
        except Exception as narrate_exc:
            self.logger.warning("LLM narration failed, using fallback: %s", narrate_exc)
            narrative = self._build_fallback_narrative(advisory_dict, framework)

        # 3. Grounded remediation report for material recommendations
        recommendations = advisory_dict.get("recommendations", [])
        material = [r for r in recommendations if r.get("is_material")]
        remediation_report: RemediationReport | None = None
        if material:
            try:
                ai_msg = await self.ask(
                    question=await self._with_graph_context(
                        self._build_remediation_prompt(material, framework)
                    ),
                    structured_output=RemediationReport,
                )
                candidate = ai_msg.structured_output
                if isinstance(candidate, RemediationReport):
                    remediation_report = await self._audit_citations(candidate)
                else:
                    # The client can fall back to raw text (or None) when
                    # structured parsing fails — never trust it blindly.
                    self.logger.error(
                        "Structured remediation returned %s instead of "
                        "RemediationReport — skipping remediation section",
                        type(candidate).__name__,
                    )
            except Exception as exc:
                self.logger.error("Structured remediation failed: %s", exc, exc_info=True)

        # 4. Persist narrative + remediation as one ADVISORY ReportRef
        body = narrative
        if remediation_report is not None:
            body += "\n\n---\n\n## Grounded Remediation Report\n\n"
            body += remediation_report.model_dump_json(indent=2)
        ref = await self._persist_advisory(
            body, framework, advisory_dict.get("provider", "aws"),
            self._extract_severity_summary(advisory_dict),
            produced_by="schedule:run_daily_soc2_advisory",
            scope_source="security_advisor.daily",
        )

        # 5. Jira tickets — validated material items only
        jira_tickets: list[str] = []
        needs_review: list[str] = []
        if remediation_report is not None:
            for item in remediation_report.items:
                if not item.validated:
                    needs_review.append(item.title)
                    continue
                key = await self._create_jira_ticket(item, framework, ref)
                if key:
                    jira_tickets.append(key)
            needs_review.extend(remediation_report.ungrounded_findings)

        # 6. Email
        subject = f"[SecurityAdvisor] Daily SOC2 Advisory — {framework.upper()} — {timestamp}"
        if needs_review:
            body += (
                "\n\n## ⚠ Needs human review (no validated KB evidence)\n"
                + "\n".join(f"- {t}" for t in needs_review)
            )
        email_sent = await self._email(subject, body)

        return {
            "report_id": str(ref.report_id) if ref else None,
            "framework": framework,
            "recommendations": len(recommendations),
            "material_recommendations": len(material),
            "validated_items": len(jira_tickets),
            "needs_human_review": needs_review,
            "jira_tickets": jira_tickets,
            "email_sent": email_sent,
        }

    # ------------------------------------------------------------------
    # Scheduled Task 2 — weekly trend insights
    # ------------------------------------------------------------------

    @schedule(schedule_type=ScheduleType.WEEKLY, day_of_week="mon", hour=13, minute=0)
    async def run_weekly_insights(self) -> dict:
        """Weekly insights: recurring patterns → short/medium-term fixes.

        Deterministic base: last 7 days of SCAN ``ReportRef``s +
        ``WeeklySecuritySummarizer``. The LLM then extracts patterns
        (recurrence, drift, time-to-resolution) into an
        ``InsightsReport``; KB references are encouraged but the value
        here is the pattern, grounded in catalog counts.
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M")

        scans = await self._report_store.query(
            ReportFilter(report_kind=ReportKind.SCAN, limit=200)
        )
        summary = None
        try:
            summarizer = WeeklySecuritySummarizer(self._llm)
            summary = await summarizer.build(scans, framework="soc2", provider="aws")
        except Exception as exc:
            self.logger.warning("Weekly summarizer failed: %s", exc)

        prompt = self._build_insights_prompt(scans, summary)
        ai_msg = await self.ask(question=prompt, structured_output=InsightsReport)
        report = ai_msg.structured_output
        if not isinstance(report, InsightsReport):
            self.logger.error(
                "run_weekly_insights: structured output returned %s instead "
                "of InsightsReport — aborting run",
                type(report).__name__,
            )
            return {
                "task": "run_weekly_insights",
                "timestamp": timestamp,
                "error": "structured output missing or invalid",
            }

        ref = await self._persist_advisory(
            report.model_dump_json(indent=2), "insights", "aws",
            SeverityBreakdown(),
            produced_by="schedule:run_weekly_insights",
            scope_source="security_advisor.insights",
        )
        subject = f"[SecurityAdvisor] Weekly Security Insights — {timestamp}"
        email_sent = await self._email(subject, self._render_insights(report))
        return {
            "report_id": str(ref.report_id) if ref else None,
            "insights": len(report.insights),
            "email_sent": email_sent,
        }

    # ------------------------------------------------------------------
    # Scheduled Task 3 — compliance gap / audit readiness
    # ------------------------------------------------------------------

    @schedule(schedule_type=ScheduleType.WEEKLY, day_of_week="fri", hour=13, minute=0)
    async def run_compliance_gap(self, framework: str = "soc2") -> dict:
        """Weekly audit-readiness gap analysis for a framework.

        Deterministic base: ``soc2_gap_analysis`` (ComplianceMapper
        coverage). The LLM enriches each gap using the compliance graph
        tools (find_node/traverse to walk TSC↔800-53 relations,
        ground_claim to check assertions) and states what evidence is
        missing — never a certification claim.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

        gap_dict = await self._soc2_toolkit.soc2_gap_analysis(framework=framework)
        if isinstance(gap_dict, dict) and "error" in gap_dict:
            return gap_dict

        ai_msg = await self.ask(
            question=await self._with_graph_context(
                self._build_gap_prompt(gap_dict, framework)
            ),
            structured_output=ComplianceGapReport,
        )
        report = ai_msg.structured_output
        if not isinstance(report, ComplianceGapReport):
            self.logger.error(
                "run_compliance_gap: structured output returned %s instead "
                "of ComplianceGapReport — aborting run",
                type(report).__name__,
            )
            return {
                "task": "run_compliance_gap",
                "timestamp": timestamp,
                "error": "structured output missing or invalid",
            }

        ref = await self._persist_advisory(
            report.model_dump_json(indent=2), framework, "aws",
            SeverityBreakdown(),
            produced_by="schedule:run_compliance_gap",
            scope_source="security_advisor.compliance_gap",
        )
        subject = (
            f"[SecurityAdvisor] {framework.upper()} Audit-Readiness Gap Report — {timestamp}"
        )
        email_sent = await self._email(subject, self._render_gaps(report))
        return {
            "report_id": str(ref.report_id) if ref else None,
            "coverage_pct": report.coverage_pct,
            "gaps": len(report.gaps),
            "email_sent": email_sent,
        }

    # ------------------------------------------------------------------
    # Persistence / notification helpers
    # ------------------------------------------------------------------

    async def _persist_advisory(
        self,
        markdown: str,
        framework: str,
        provider: str,
        severity: SeverityBreakdown,
        *,
        produced_by: str,
        scope_source: str,
    ) -> ReportRef | None:
        """Persist an advisory body as ``ReportRef(report_kind=ADVISORY)``."""
        content = markdown.encode("utf-8")
        ref = ReportRef(
            report_kind=ReportKind.ADVISORY,
            scanner="security_advisor",
            framework=framework,
            provider=provider,
            scope={"frameworks": [framework], "source": scope_source},
            severity_summary=severity,
            uri="",
            content_type="text/markdown",
            content_bytes=len(content),
            produced_at=datetime.now(timezone.utc),
            produced_by=produced_by,
            parser_version="2.0.0",
        )
        try:
            ref = await self._report_store.save_report(ref, content)
            self.logger.info("Persisted ADVISORY ReportRef %s (%s)", ref.report_id, scope_source)
            return ref
        except Exception as exc:
            self.logger.error("Could not persist advisory ReportRef: %s", exc)
            return None

    async def _create_jira_ticket(
        self, item: RemediationItem, framework: str, ref: ReportRef | None
    ) -> str | None:
        """Create a Jira ticket for one validated remediation item."""
        jira = self._build_jira()
        jira_tools = {t.name: t for t in jira.get_tools()}
        create_fn = jira_tools.get("jira_create_issue")
        if create_fn is None:
            self.logger.warning("jira_create_issue tool not found")
            return None
        refs_md = "\n".join(f"- [{r.title}|{r.source}]" for r in item.references)
        try:
            # ToolkitTool is not callable — the AbstractTool contract is
            # ``await tool.execute(**kwargs)`` returning a ToolResult whose
            # payload (the Jira response dict) lives in ``.result``.
            result = await create_fn.execute(
                project=config.get("JIRA_PROJECT", fallback="NAV"),
                summary=f"[SecurityAdvisor] {item.title} ({item.severity})",
                description=(
                    f"**Framework**: {framework}\n"
                    f"**Severity**: {item.severity}\n"
                    f"**Controls**: {', '.join(item.control_ids) or 'N/A'}\n"
                    f"**Affected Resources**: {', '.join(item.affected_resources) or 'unknown'}\n\n"
                    "**Remediation steps**:\n"
                    + "\n".join(f"# {s}" for s in item.steps)
                    + f"\n\n**References (validated against KB)**:\n{refs_md}\n\n"
                    + (f"Advisory Report ID: {ref.report_id}" if ref else "")
                ),
                issuetype="Task",
            )
            if not result.success:
                self.logger.warning(
                    "jira_create_issue failed for %r: %s", item.title, result.error
                )
                return None
            payload = result.result if isinstance(result.result, dict) else {}
            key = payload.get("key") or payload.get("id")
            if not key:
                self.logger.warning(
                    "jira_create_issue returned no issue key for %r: %s",
                    item.title, payload,
                )
                return None
            self.logger.info("Created Jira ticket %s for %r", key, item.title)
            return str(key)
        except Exception as exc:
            self.logger.warning("Could not create Jira ticket for %r: %s", item.title, exc)
            return None

    async def _email(self, subject: str, body: str) -> bool:
        """Send the advisory email; returns success flag.

        ``send_notification`` swallows provider errors and reports them as
        ``{"status": "error", ...}`` instead of raising, so the returned
        status must be inspected — a bare await always "succeeds".
        """
        try:
            result = await self.send_notification(
                message=body,
                recipients=_NOTIFICATION_RECIPIENTS,
                provider="email",
                subject=subject,
            )
        except Exception as exc:
            self.logger.error("Could not send advisory email: %s", exc)
            return False
        status = (result or {}).get("status")
        if status != "success":
            self.logger.error(
                "Could not send advisory email: %s",
                (result or {}).get("error", result),
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_narration_prompt(advisory_dict: dict, framework: str) -> str:
        """Narration prompt from the structured advisory (unchanged)."""
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

    @staticmethod
    def _build_remediation_prompt(material: list[dict], framework: str) -> str:
        """Prompt for the grounded, structured remediation report."""
        listing = "\n".join(
            f"- {r.get('title','?')} ({r.get('severity','?')}) — "
            f"controls: {', '.join(r.get('soc2_control_ids', []) or [])} — "
            f"resources: {', '.join(r.get('affected_resources', []) or [])}"
            for r in material[:15]
        )
        return (
            f"Produce a RemediationReport for these MATERIAL {framework.upper()} "
            f"findings:\n\n{listing}\n\n"
            "Process, per finding:\n"
            "1. Call `remediation_kb_search` with the finding title (and the "
            "AWS service involved). Read the retrieved chunks.\n"
            "2. If relevant chunks exist: write concrete steps taken FROM the "
            "chunks and cite them in `references` (use the exact source_url "
            "or doc_id returned by the tool — never invent one).\n"
            "3. If nothing relevant is retrieved: add the finding title to "
            "`ungrounded_findings` and do NOT produce steps for it.\n"
            "Keep control ids exactly as given above."
        )

    @staticmethod
    def _build_insights_prompt(scans: list, summary) -> str:
        """Prompt for the weekly InsightsReport."""
        scan_lines = "\n".join(
            f"- {s.produced_at:%Y-%m-%d} {s.scanner}: {s.severity_summary.critical}C/"
            f"{s.severity_summary.high}H/{s.severity_summary.medium}M — top: "
            + "; ".join(f.title for f in (s.top_findings or [])[:3])
            for s in scans[:40]
        )
        summary_txt = (
            summary.model_dump_json(indent=2) if summary is not None else "unavailable"
        )
        return (
            "Analyse the last week of security scans and produce an "
            "InsightsReport with short_term and medium_term improvements.\n\n"
            f"**Scan history**:\n{scan_lines}\n\n"
            f"**Weekly summary**:\n{summary_txt}\n\n"
            "Look for RECURRING patterns (same finding class reappearing, "
            "severity drift after deploys, services that concentrate "
            "findings). Each insight must cite the pattern with concrete "
            "counts/titles from the data above. Recommend preventive "
            "guardrails (SCPs, IaC scanning in CI, tagging policies, "
            "least-privilege baselines) — use `remediation_kb_search` to "
            "reference guidance where available. Do not invent data."
        )

    @staticmethod
    def _build_gap_prompt(gap_dict: dict, framework: str) -> str:
        """Prompt for the ComplianceGapReport."""
        return (
            f"Produce a ComplianceGapReport for {framework.upper()} from this "
            f"deterministic gap analysis:\n\n{gap_dict}\n\n"
            "For each control with failing or missing evidence:\n"
            "1. Use the compliance graph tools (`find_node`, `traverse`, "
            "`get_neighborhood`) to pull the control's description and its "
            "TSC↔NIST-800-53 relations; record consulted node ids in "
            "`graph_refs`.\n"
            "2. Verify any cross-framework assertion with `ground_claim` "
            "before stating it.\n"
            "3. Classify status: covered | gap | no_evidence, and state what "
            "evidence is missing and how to collect it.\n"
            "Finish with the questions an auditor would ask. This is an "
            "audit-READINESS report: never claim certification."
        )

    # ------------------------------------------------------------------
    # Renderers / misc
    # ------------------------------------------------------------------

    @staticmethod
    def _render_insights(report: InsightsReport) -> str:
        lines = [f"# Weekly Security Insights ({report.period_start} → {report.period_end})", ""]
        for i in report.insights:
            lines += [
                f"## [{i.horizon}] {i.title}",
                f"**Pattern**: {i.pattern}",
                f"**Recommendation**: {i.recommendation}",
                "",
            ]
        return "\n".join(lines)

    @staticmethod
    def _render_gaps(report: ComplianceGapReport) -> str:
        lines = [
            f"# {report.framework.upper()} Audit-Readiness Gap Report",
            f"**Deterministic coverage**: {report.coverage_pct:.1f}%",
            "",
        ]
        for g in report.gaps:
            lines.append(
                f"- **{g.control_id}** [{g.status}] — {g.evidence}"
                + (f" | missing: {g.missing_evidence}" if g.missing_evidence else "")
            )
        if report.auditor_questions:
            lines += ["", "## Questions an auditor would ask"]
            lines += [f"- {q}" for q in report.auditor_questions]
        return "\n".join(lines)

    @staticmethod
    def _build_fallback_narrative(advisory_dict: dict, framework: str) -> str:
        """Plain narrative without LLM when ask() fails (unchanged)."""
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

    @staticmethod
    def _extract_severity_summary(advisory_dict: dict) -> SeverityBreakdown:
        """Extract severity summary from the advisory dict (unchanged)."""
        delta = advisory_dict.get("severity_delta") or {}
        return SeverityBreakdown(
            critical=max(0, delta.get("critical", 0)),
            high=max(0, delta.get("high", 0)),
            medium=max(0, delta.get("medium", 0)),
            low=max(0, delta.get("low", 0)),
            informational=max(0, delta.get("informational", 0)),
        )
