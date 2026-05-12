---
id: F001
query_id: Q001
type: read
intent: Locate the SecurityAgent class and capture its current __init__, agent_tools, schedule wiring, and BACKSTORY block.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — SecurityAgent: BACKSTORY already mentions find_security_report; consolidate_weekly_security_summary already partially implemented (uncommitted)

## Summary

`agents/security.py` is **untracked / gitignored** (see `.gitignore` line 245 area:
`/agents/`), so it lives only locally. The file is partially modified vs. the
brainstorm baseline: the BACKSTORY already contains a "WARNING — EXPENSIVE
OPERATIONS" block that mentions `find_security_report` (lines 56-63) but
that tool does NOT yet exist anywhere in the codebase. The agent also has a
**half-written** `consolidate_weekly_security_summary` method at line 445 that
references `self._report_store`, `ReportFilter`, and `self._build_weekly_summary`
— all undefined symbols. This will currently fail at runtime. There is NO
existing `_file_manager`/`_report_store` attribute on the agent.

## Citations

- path: `agents/security.py`
  lines: 1-25
  symbol: imports
  excerpt: |
    import logging
    from datetime import datetime, timezone, timedelta
    from navconfig import config
    from parrot.bots import Agent
    from parrot.registry import register_agent
    from parrot.scheduler import ScheduleType, schedule
    from parrot_tools.cloudsploit import CloudSploitConfig, CloudSploitToolkit
    from parrot_tools.security import (..., ComplianceReportToolkit, ContainerSecurityToolkit, ...)
    from parrot_tools.aws import (RDSToolkit, EKSToolkit, ECSToolkit, EC2Toolkit, SecurityHubToolkit, InspectorToolkit)

- path: `agents/security.py`
  lines: 80-130
  symbol: SecurityAgent.__init__
  excerpt: |
    NOTIFICATION_RECIPIENTS = "jlara@trocglobal.com"
    REPORTS_DIR = "/tmp/security-reports"

    @register_agent(name="security_agent", at_startup=True)
    class SecurityAgent(Agent):
        agent_id: str = "security_agent"
        model: str = "gemini-3.1-pro-preview"
        max_tokens: int = 16000
        def __init__(self, *args, **kwargs):
            super().__init__(*args, backstory=BACKSTORY, **kwargs)
            self._logger = logging.getLogger("SecurityAgent")
            aws_access_key_id = config.get("aws_security", "AWS_ACCESS_SECURITY_KEY_ID")
            aws_secret_access_key = config.get("aws_security", "AWS_SECRET_SECURITY_KEY")

- path: `agents/security.py`
  lines: 131-201
  symbol: SecurityAgent.agent_tools
  excerpt: |
    def agent_tools(self):
        creds = self._aws_credentials
        toolkit_kwargs = self._aws_toolkit_kwargs()
        self._cloudsploit_toolkit = CloudSploitToolkit(config=CloudSploitConfig(...))
        self._compliance_toolkit = ComplianceReportToolkit(prowler_config=..., trivy_config=..., checkov_config=..., report_output_dir=REPORTS_DIR)
        self._container_toolkit = ContainerSecurityToolkit(config=TrivyConfig(...))
        # ... AWS toolkits ...
        return [*self._cloudsploit_toolkit.get_tools(), *self._compliance_toolkit.get_tools(), ...]

- path: `agents/security.py`
  lines: 55-78
  symbol: BACKSTORY excerpt (freshness policy)
  excerpt: |
    ⚠️  WARNING — EXPENSIVE OPERATIONS:
      ALL scanner tools (CloudSploit, Prowler, Trivy, Checkov) launch Docker
      containers and each scan takes approximately 10–20 minutes to complete.
      NEVER launch a scan unless:
        1. ``find_security_report`` returned no recent report for the requested
           framework / target, OR
        2. The user explicitly asked for a **fresh** or **new** scan.

- path: `agents/security.py`
  lines: 445-471
  symbol: consolidate_weekly_security_summary (BROKEN — references undefined symbols)
  excerpt: |
    @schedule(schedule_type=ScheduleType.WEEKLY, day_of_week=0, hour=6, minute=0)
    async def consolidate_weekly_security_summary(self) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        for framework in (ComplianceFramework.HIPAA, ComplianceFramework.PCI_DSS, ComplianceFramework.SOC2):
            scans = await self._report_store.query(ReportFilter(...))     # undefined
            summary = await self._build_weekly_summary(scans, framework)  # undefined
            ref = await self._report_store.save_report(...)               # undefined

- path: `.gitignore`
  lines: 1-1
  symbol: gitignore rule
  excerpt: |
    `git check-ignore agents/security.py` → matches `/agents/`

## Notes

- The existing daily `@schedule` tasks are: `run_hipaa_pci_compliance`,
  `run_vulnerability_scan`, `run_cloud_posture_report`, `run_inspector_report`,
  `run_container_security_scan` — all `ScheduleType.DAILY`, hour=8, minute=0.
- `REPORTS_DIR = "/tmp/security-reports"` is the only path constant.
- `aws_access_key_id`/`aws_secret_access_key` resolve via `config.get("aws_security", "AWS_ACCESS_SECURITY_KEY_ID")` —
  the brainstorm's `config.AWS_ACCESS_KEY` would not work here; aws_security is a
  separate ini section, not the global aws_key. See F014.
- Hard-coded `aws_region = "us-east-2"`. The brainstorm assumed `config.AWS_REGION_NAME`.
