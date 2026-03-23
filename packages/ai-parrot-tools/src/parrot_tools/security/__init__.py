"""AI-Parrot Security Toolkits Suite.

Provides agent-callable tools for cloud security scanning, compliance reporting,
and vulnerability management. Wraps Prowler, Trivy, and Checkov.

Usage:
    # Import toolkits for agent integration
    from parrot.tools.security import (
        CloudPostureToolkit,
        ContainerSecurityToolkit,
        SecretsIaCToolkit,
        ComplianceReportToolkit,
    )

    # Run a full compliance scan
    toolkit = ComplianceReportToolkit()
    report = await toolkit.compliance_full_scan(
        provider="aws",
        target_image="nginx:latest",
        iac_path="./terraform"
    )
    path = await toolkit.compliance_soc2_report()

    # Or import specific components
    from parrot.tools.security.models import SecurityFinding, ScanResult
    from parrot.tools.security.prowler import ProwlerExecutor, ProwlerConfig
    from parrot.tools.security.reports import ComplianceMapper, ReportGenerator
"""

from .base_executor import BaseExecutor, BaseExecutorConfig
from .base_parser import BaseParser
from .checkov import CheckovConfig, CheckovExecutor, CheckovParser
from .cloud_posture_toolkit import CloudPostureToolkit
from .compliance_report_toolkit import ComplianceReportToolkit
from .container_security_toolkit import ContainerSecurityToolkit
from .models import (
    CloudProvider,
    ComparisonDelta,
    ComplianceFramework,
    ConsolidatedReport,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)
from .prowler import ProwlerConfig, ProwlerExecutor, ProwlerParser
from .reports import ComplianceMapper, ReportGenerator
from .secrets_iac_toolkit import SecretsIaCToolkit
from .trivy import TrivyConfig, TrivyExecutor, TrivyParser

__all__ = [
    # Enums
    "SeverityLevel",
    "FindingSource",
    "ComplianceFramework",
    "CloudProvider",
    # Models
    "SecurityFinding",
    "ScanSummary",
    "ScanResult",
    "ComparisonDelta",
    "ConsolidatedReport",
    # Base classes
    "BaseExecutor",
    "BaseExecutorConfig",
    "BaseParser",
    # Prowler
    "ProwlerConfig",
    "ProwlerExecutor",
    "ProwlerParser",
    # Trivy
    "TrivyConfig",
    "TrivyExecutor",
    "TrivyParser",
    # Checkov
    "CheckovConfig",
    "CheckovExecutor",
    "CheckovParser",
    # Reports
    "ComplianceMapper",
    "ReportGenerator",
    # Toolkits
    "CloudPostureToolkit",
    "ComplianceReportToolkit",
    "ContainerSecurityToolkit",
    "SecretsIaCToolkit",
]
