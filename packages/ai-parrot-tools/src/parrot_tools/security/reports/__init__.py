"""Security Reports Package.

Provides compliance mapping and report generation functionality
for security scan results.

Usage:
    from parrot.tools.security.reports import ComplianceMapper, ReportGenerator

    mapper = ComplianceMapper()
    controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)

    generator = ReportGenerator(output_dir="/tmp/reports")
    path = await generator.generate_compliance_report(report, ComplianceFramework.SOC2)
"""

from .compliance_mapper import ComplianceMapper
from .generator import ReportGenerator

__all__ = [
    "ComplianceMapper",
    "ReportGenerator",
]
