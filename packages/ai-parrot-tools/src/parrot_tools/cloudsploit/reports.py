"""Report generator for CloudSploit scan results.

Produces HTML and PDF reports from scan results and comparison data.
Uses Jinja2 for templating and xhtml2pdf for PDF generation.
"""
import io
from pathlib import Path
from typing import Optional

from navconfig.logging import logging
from jinja2 import Environment, FileSystemLoader

from .models import (
    ComparisonReport,
    EcrCollectionResult,
    EcrSeverity,
    ScanResult,
)

# Default maximum findings to include in HTML table
DEFAULT_MAX_FINDINGS = 1000


class ReportGenerator:
    """Generates HTML and PDF reports from CloudSploit scan results.

    Reports include executive summary, severity breakdown charts,
    category breakdown, and detailed findings tables.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )

    def _compute_pass_rate(self, result: ScanResult) -> str:
        """Compute pass rate percentage.

        Args:
            result: Scan result to compute pass rate for.

        Returns:
            Pass rate as formatted string (e.g., "85.7").
        """
        if result.summary.total_findings == 0:
            return "0.0"
        rate = (result.summary.ok_count / result.summary.total_findings) * 100
        return f"{rate:.1f}"

    def _sorted_categories(self, result: ScanResult) -> list[tuple[str, int]]:
        """Sort categories by count descending.

        Args:
            result: Scan result with category data.

        Returns:
            List of (category_name, count) tuples sorted by count desc.
        """
        return sorted(
            result.summary.categories.items(),
            key=lambda x: x[1],
            reverse=True,
        )

    async def generate_html(
        self,
        result: ScanResult,
        output_path: Optional[str] = None,
        max_findings: int = DEFAULT_MAX_FINDINGS,
    ) -> str:
        """Generate HTML report from scan results.

        Args:
            result: CloudSploit scan result.
            output_path: File path to save report. If None, returns HTML string.
            max_findings: Maximum findings to include in the table.

        Returns:
            HTML string if output_path is None, otherwise the file path.
        """
        template = self.env.get_template("scan_report.html")

        # Paginate findings if needed
        findings = result.findings[:max_findings]
        has_more = len(result.findings) > max_findings

        html = template.render(
            summary=result.summary,
            findings=findings,
            has_more_findings=has_more,
            pass_rate=self._compute_pass_rate(result),
            categories_sorted=self._sorted_categories(result),
        )

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(html, encoding="utf-8")
            self.logger.info("HTML report saved to %s", output_path)
            return output_path
        return html

    async def generate_pdf(
        self,
        result: ScanResult,
        output_path: str,
        max_findings: int = DEFAULT_MAX_FINDINGS,
    ) -> str:
        """Generate PDF report from scan results.

        Args:
            result: CloudSploit scan result.
            output_path: File path to save the PDF.
            max_findings: Maximum findings to include in the table.

        Returns:
            The file path of the generated PDF.
        """
        from xhtml2pdf import pisa

        html = await self.generate_html(result, max_findings=max_findings)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as pdf_file:
            pisa_status = pisa.CreatePDF(
                io.StringIO(html),
                dest=pdf_file,
            )
            if pisa_status.err:
                self.logger.error(
                    "PDF generation errors: %d", pisa_status.err
                )

        self.logger.info("PDF report saved to %s", output_path)
        return output_path

    async def generate_comparison_html(
        self,
        comparison: ComparisonReport,
        output_path: Optional[str] = None,
    ) -> str:
        """Generate HTML comparison report.

        Args:
            comparison: Comparison between two scan results.
            output_path: File path to save report. If None, returns HTML string.

        Returns:
            HTML string if output_path is None, otherwise the file path.
        """
        template = self.env.get_template("comparison_report.html")

        html = template.render(comparison=comparison)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(html, encoding="utf-8")
            self.logger.info("Comparison report saved to %s", output_path)
            return output_path
        return html

    async def generate_comparison_pdf(
        self,
        comparison: ComparisonReport,
        output_path: str,
    ) -> str:
        """Generate PDF comparison report.

        Args:
            comparison: Comparison between two scan results.
            output_path: File path to save the PDF.

        Returns:
            The file path of the generated PDF.
        """
        from xhtml2pdf import pisa

        html = await self.generate_comparison_html(comparison)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as pdf_file:
            pisa_status = pisa.CreatePDF(
                io.StringIO(html),
                dest=pdf_file,
            )
            if pisa_status.err:
                self.logger.error(
                    "PDF generation errors: %d", pisa_status.err
                )

        self.logger.info("Comparison PDF saved to %s", output_path)
        return output_path

    # -- ECR image-scan report (FEAT-165) ----------------------------------

    # Severity ordering for sorting (lower number = higher priority)
    _SEV_ORDER: dict[EcrSeverity, int] = {
        EcrSeverity.CRITICAL: 1,
        EcrSeverity.HIGH: 2,
        EcrSeverity.MEDIUM: 3,
        EcrSeverity.LOW: 4,
        EcrSeverity.INFORMATIONAL: 5,
        EcrSeverity.UNTRIAGED: 6,
    }

    # Severity colour palette (background, foreground) for inline badges
    _SEV_COLOR: dict[EcrSeverity, tuple[str, str]] = {
        EcrSeverity.CRITICAL: ("#dc3545", "white"),
        EcrSeverity.HIGH: ("#fd7e14", "white"),
        EcrSeverity.MEDIUM: ("#ffc107", "#000"),
        EcrSeverity.LOW: ("#6c757d", "white"),
        EcrSeverity.INFORMATIONAL: ("#adb5bd", "white"),
        EcrSeverity.UNTRIAGED: ("#adb5bd", "white"),
    }

    @staticmethod
    def _repo_priority(name: str) -> int:
        """Return a sort key that pins ``navigator-api-tf`` first.

        Args:
            name: Repository name.

        Returns:
            0 for ``navigator-api-tf``, 1 for other ``navigator-*``, 2 for rest.
        """
        if name == "navigator-api-tf":
            return 0
        if name.startswith("navigator-"):
            return 1
        return 2

    async def generate_ecr_html(
        self,
        result: EcrCollectionResult,
        output_path: Optional[str] = None,
    ) -> str:
        """Render an interactive HTML vulnerability report from ECR scan data.

        Builds a view-model from ``result`` — sorting repos, grouping CVEs by
        package, truncating descriptions, resolving severity colours — then
        renders ``ecr_scan_report.html`` via the existing Jinja2 env.

        Args:
            result: Collected ECR scan findings.
            output_path: File path to write the HTML to.  Parent directories
                are created automatically.  When ``None``, the rendered HTML
                string is returned instead.

        Returns:
            Rendered HTML string when ``output_path`` is ``None``, otherwise
            the absolute path of the written file (as a ``str``).
        """
        template = self.env.get_template("ecr_scan_report.html")

        # Global severity totals across all repos
        total_counts: dict[str, int] = {}
        for repo in result.repos:
            for sev, n in repo.counts.items():
                total_counts[sev.value] = total_counts.get(sev.value, 0) + n

        # Sort repos: navigator-api-tf first, other navigator-* by severity,
        # then the rest alphabetically
        def _repo_sort_key(repo):  # type: ignore[return]
            return (
                self._repo_priority(repo.repo),
                -repo.counts.get(EcrSeverity.CRITICAL, 0),
                -repo.counts.get(EcrSeverity.HIGH, 0),
                -repo.counts.get(EcrSeverity.MEDIUM, 0),
                -repo.counts.get(EcrSeverity.LOW, 0),
                repo.repo,
            )

        repos_sorted = [
            self._build_repo_view(r)
            for r in sorted(result.repos, key=_repo_sort_key)
        ]

        html = template.render(
            generated_at=result.generated_at.isoformat(),
            region=result.region,
            total_counts=total_counts,
            repo_count=len(result.repos),
            repos_sorted=repos_sorted,
        )

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html, encoding="utf-8")
            self.logger.info("ECR HTML report saved to %s", output_path)
            return output_path
        return html

    def _build_repo_view(self, repo) -> dict:  # type: ignore[return]
        """Build the per-repo view-model consumed by ``ecr_scan_report.html``.

        Groups findings by ``(package_name, package_version)``, sorts packages
        by worst severity, pre-truncates descriptions to 180 chars, and
        resolves severity colours for inline CSS badges.

        Args:
            repo: ``EcrRepoFindings`` instance.

        Returns:
            Dict with keys matching the template context vars.
        """
        from collections import defaultdict

        sev_order = self._SEV_ORDER
        sev_color = self._SEV_COLOR

        # --- 1. Group findings by (package_name, package_version) ----------
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for f in repo.findings:
            key = (f.package_name or "?", f.package_version or "")
            groups[key].append(f)

        # --- 2. Build sorted package blocks ---------------------------------
        pkg_groups = []
        for (pkg, ver), findings in groups.items():
            # Sort CVEs within the package by severity (worst first)
            findings.sort(key=lambda f: sev_order.get(f.severity, 99))

            worst_sev = findings[0].severity if findings else EcrSeverity.UNTRIAGED
            worst_order = sev_order.get(worst_sev, 99)

            cves = []
            for f in findings:
                bg, fg = sev_color.get(f.severity, ("#adb5bd", "white"))
                desc = f.description or ""
                if len(desc) > 180:
                    desc = desc[:180] + "…"  # ellipsis
                cves.append({
                    "name": f.name,
                    "severity": f.severity.value,
                    "description_short": desc,
                    "uri": f.uri or "",
                    "fixed_in_versions": f.fixed_in_versions,
                    "cvss": f.cvss,
                    "sev_bg": bg,
                    "sev_fg": fg,
                })

            pkg_groups.append({
                "pkg": pkg,
                "ver": ver,
                "worst_severity": worst_sev.value,
                "_worst_order": worst_order,
                "pkg_open": worst_sev in (EcrSeverity.CRITICAL, EcrSeverity.HIGH),
                "cves": cves,
            })

        # Sort packages by worst severity
        pkg_groups.sort(key=lambda g: g["_worst_order"])

        # --- 3. Compute boolean flags for the template ----------------------
        counts_str: dict[str, int] = {k.value: v for k, v in repo.counts.items()}
        has_critical = EcrSeverity.CRITICAL in repo.counts and repo.counts[EcrSeverity.CRITICAL] > 0
        has_high = EcrSeverity.HIGH in repo.counts and repo.counts[EcrSeverity.HIGH] > 0
        has_medium = EcrSeverity.MEDIUM in repo.counts and repo.counts[EcrSeverity.MEDIUM] > 0
        has_low = EcrSeverity.LOW in repo.counts and repo.counts[EcrSeverity.LOW] > 0

        # Worst severity for border colour
        for sev in (EcrSeverity.CRITICAL, EcrSeverity.HIGH, EcrSeverity.MEDIUM,
                    EcrSeverity.LOW, EcrSeverity.INFORMATIONAL):
            if sev in repo.counts and repo.counts[sev] > 0:
                worst = sev
                break
        else:
            worst = EcrSeverity.UNTRIAGED

        # Scan time formatting
        if repo.scan_time:
            try:
                scan_time_formatted = repo.scan_time.strftime("%Y-%m-%d %H:%M")
            except Exception:
                scan_time_formatted = "N/A"
        else:
            scan_time_formatted = "N/A"

        return {
            "repo": repo.repo,
            "tag": repo.tag,
            "counts": counts_str,
            "has_critical": has_critical,
            "has_high": has_high,
            "has_medium": has_medium,
            "has_low": has_low,
            "worst_severity": worst.value,
            "repo_open": has_critical or has_high,
            "scan_time_formatted": scan_time_formatted,
            "pkg_groups": pkg_groups,
            "total_findings": len(repo.findings),
        }
