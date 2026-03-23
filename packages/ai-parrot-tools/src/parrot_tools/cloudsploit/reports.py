"""Report generator for CloudSploit scan results.

Produces HTML and PDF reports from scan results and comparison data.
Uses Jinja2 for templating and xhtml2pdf for PDF generation.
"""
import io
from pathlib import Path
from typing import Optional

from navconfig.logging import logging
from jinja2 import Environment, FileSystemLoader

from .models import ScanResult, ComparisonReport

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
