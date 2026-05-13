"""ECR image-scan collector for CloudSploit toolkit (FEAT-165).

Implements multi-repo / tag-priority aggregation against ECR Basic Scanning,
with bounded concurrency via ``asyncio.Semaphore``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Union

from parrot.interfaces.aws import AWSInterface
from parrot_tools.aws.ecr import ECRToolkit
from parrot_tools.cloudsploit.models import (
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrRepoFindings,
    EcrRepoPlan,
    EcrScanFinding,
    EcrSeverity,
)


class EcrScanCollector:
    """Aggregate ECR vulnerability scan findings across many repos.

    Orchestrates the multi-repo / tag-priority loop that was previously
    implemented in the JS script ``collect_ecr_findings.js``.  For each
    repo in the plan it tries the specified tags in priority order, stopping
    at the first tag whose image has scan findings (first-match-wins).
    Concurrency across repos is bounded by ``asyncio.Semaphore``.

    Attributes:
        aws: The ``AWSInterface`` instance used for all ECR API calls.
        logger: Standard Python logger named after this class.
    """

    def __init__(self, aws: AWSInterface) -> None:
        """Initialise the collector with a shared AWS interface.

        Args:
            aws: Pre-configured ``AWSInterface`` instance.  All ECR API
                calls will use the credentials and region from this instance.
        """
        self.aws = aws
        self.logger = logging.getLogger(self.__class__.__name__)

    async def collect(self, plan: EcrCollectionPlan) -> EcrCollectionResult:
        """Run the collection plan with bounded concurrency.

        For each repo in ``plan.repos``, tries its tags in priority order
        (first-match-wins).  At most ``plan.concurrency`` ECR API calls are
        in flight at any time.

        The plan's ``region`` and ``aws_id`` are honoured: when they differ
        from the collector's current ``AWSInterface``, a fresh region-scoped
        interface is built for the call so probes hit the intended region
        and account.  Otherwise ``self.aws`` is reused.

        Args:
            plan: Validated ``EcrCollectionPlan`` loaded from YAML.

        Returns:
            ``EcrCollectionResult`` with per-repo findings and a ``skipped``
            list for repos where every tag returned no results.
        """
        sem = asyncio.Semaphore(plan.concurrency)

        plan_aws = self._aws_for_plan(plan)
        ecr = ECRToolkit.__new__(ECRToolkit)
        ecr.aws = plan_aws

        repo_coros = [
            self._collect_one_repo(ecr, repo, sem) for repo in plan.repos
        ]
        outcomes = await asyncio.gather(*repo_coros, return_exceptions=False)

        found: list[EcrRepoFindings] = []
        skipped: list[dict] = []
        for repo, outcome in zip(plan.repos, outcomes):
            if isinstance(outcome, EcrRepoFindings):
                found.append(outcome)
            else:
                # outcome is a skip-reason string
                skipped.append({"repo": repo.name, "reason": str(outcome)})

        return EcrCollectionResult(
            generated_at=datetime.now(tz=timezone.utc),
            region=plan.region,
            repos=found,
            skipped=skipped,
        )

    def _aws_for_plan(self, plan: EcrCollectionPlan) -> AWSInterface:
        """Return an ``AWSInterface`` scoped to the plan's region/aws_id.

        Reuses ``self.aws`` when its region already matches ``plan.region``
        (the common case in tests and single-region deployments); otherwise
        constructs a fresh region-scoped ``AWSInterface`` so the boto3
        session targets the region declared in the plan.

        Args:
            plan: The collection plan whose ``region`` and ``aws_id`` drive
                the AWS interface selection.

        Returns:
            An ``AWSInterface`` whose region matches ``plan.region``.
        """
        current_region = getattr(self.aws, "region", None)
        if isinstance(current_region, str) and current_region == plan.region:
            return self.aws
        self.logger.debug(
            "Plan region=%s (aws_id=%s) differs from collector region=%r — "
            "rebuilding AWSInterface for this call",
            plan.region, plan.aws_id, current_region,
        )
        return AWSInterface(aws_id=plan.aws_id, region_name=plan.region)

    async def _collect_one_repo(
        self,
        ecr: ECRToolkit,
        repo: EcrRepoPlan,
        sem: asyncio.Semaphore,
    ) -> Union[EcrRepoFindings, str]:
        """Try each tag for a single repo; return findings or a skip reason.

        Args:
            ecr: ``ECRToolkit`` instance whose ``aws`` is ``self.aws``.
            repo: Repo plan with ``name`` and ``tags`` in priority order.
            sem: Semaphore that bounds concurrent ECR API calls.

        Returns:
            ``EcrRepoFindings`` on first successful match, or a skip-reason
            string when every tag returns no findings.
        """
        for tag in repo.tags:
            async with sem:
                self.logger.debug("Probing %s:%s", repo.name, tag)
                try:
                    payload = await ecr.aws_ecr_get_image_scan_findings(
                        repo.name, tag, include_attributes=True,
                    )
                except RuntimeError as exc:
                    msg = str(exc)
                    if "RepositoryNotFoundException" in msg:
                        self.logger.warning(
                            "%s — repository does not exist in registry "
                            "(skipped)", repo.name,
                        )
                        return "repository not found in registry"
                    self.logger.warning(
                        "%s:%s — ECR error, trying next tag: %s",
                        repo.name, tag, msg,
                    )
                    continue

            if payload.get("scan_status") == "NOT_FOUND":
                self.logger.debug(
                    "%s:%s — scan NOT_FOUND, trying next tag", repo.name, tag
                )
                continue

            findings_raw = payload.get("findings") or []
            if not findings_raw:
                self.logger.debug(
                    "%s:%s — 0 findings, trying next tag", repo.name, tag
                )
                continue

            self.logger.info(
                "%s:%s — %d findings collected",
                repo.name, tag, len(findings_raw),
            )
            return self._build_repo_findings(repo.name, tag, payload)

        self.logger.warning(
            "%s — no tag returned scan findings (skipped)", repo.name
        )
        return "no tag returned scan findings"

    def _build_repo_findings(
        self, repo: str, tag: str, payload: dict[str, Any],
    ) -> EcrRepoFindings:
        """Build an ``EcrRepoFindings`` from a raw ECR wrapper payload.

        Args:
            repo: ECR repository name.
            tag: Image tag that produced these findings.
            payload: Dict returned by ``aws_ecr_get_image_scan_findings``
                with ``include_attributes=True``.

        Returns:
            Validated ``EcrRepoFindings`` model.
        """
        # Build severity counts dict with EcrSeverity keys
        severity_counts_raw: dict[str, int] = payload.get(
            "severity_counts", {}
        ) or {}
        counts: dict[EcrSeverity, int] = {}
        for sev_str, n in severity_counts_raw.items():
            try:
                counts[EcrSeverity(sev_str)] = n
            except ValueError:
                self.logger.warning(
                    "Unknown severity '%s' in severity_counts for %s:%s — skipped",
                    sev_str, repo, tag,
                )

        # Build individual findings
        findings: list[EcrScanFinding] = []
        for raw_f in payload.get("findings") or []:
            findings.append(self._build_finding(raw_f, repo, tag))

        return EcrRepoFindings(
            repo=repo,
            tag=tag,
            scan_time=None,  # ECR wrapper does not expose scan timestamp
            counts=counts,
            findings=findings,
        )

    def _build_finding(
        self, raw_f: dict[str, Any], repo: str, tag: str,
    ) -> EcrScanFinding:
        """Convert one raw ECR finding dict into an ``EcrScanFinding``.

        Args:
            raw_f: Raw finding dict from the ECR API (with ``attributes``
                list when ``include_attributes=True``).
            repo: ECR repository name (used in warning logs).
            tag: Image tag (used in warning logs).

        Returns:
            Validated ``EcrScanFinding`` model.
        """
        # Parse attributes list into a key→value dict for easy lookup
        attrs: dict[str, str] = {}
        for entry in raw_f.get("attributes") or []:
            k = entry.get("key")
            v = entry.get("value")
            if k is not None:
                attrs[k] = v or ""

        # Map ECR severity string → EcrSeverity; fall back to UNTRIAGED
        raw_sev = raw_f.get("severity") or ""
        try:
            severity = EcrSeverity(raw_sev)
        except ValueError:
            self.logger.warning(
                "Unknown severity value '%s' in finding '%s' for %s:%s — "
                "remapping to UNTRIAGED",
                raw_sev, raw_f.get("name", "?"), repo, tag,
            )
            severity = EcrSeverity.UNTRIAGED

        # CVSS preference: CVSS4_SCORE > CVSS3_SCORE > None
        cvss: str | None = attrs.get("CVSS4_SCORE") or attrs.get("CVSS3_SCORE") or None

        return EcrScanFinding(
            name=raw_f.get("name") or "",
            severity=severity,
            description=raw_f.get("description") or "",
            uri=raw_f.get("uri") or "",
            package_name=attrs.get("package_name") or None,
            package_version=attrs.get("package_version") or None,
            fixed_in_versions=attrs.get("fixed_in_versions") or None,
            cvss=cvss,
        )
