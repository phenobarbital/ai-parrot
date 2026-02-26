"""AI-Parrot Security Toolkits Suite.

Provides agent-callable tools for cloud security scanning, compliance reporting,
and vulnerability management. Wraps Prowler, Trivy, and Checkov.

Usage:
    from parrot.tools.security.models import SecurityFinding, ScanResult
    from parrot.tools.security.base_executor import BaseExecutor, BaseExecutorConfig
    from parrot.tools.security.base_parser import BaseParser
    from parrot.tools.security.prowler import ProwlerExecutor, ProwlerConfig
"""

from .base_executor import BaseExecutor, BaseExecutorConfig
from .base_parser import BaseParser
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
from .checkov import CheckovConfig, CheckovExecutor, CheckovParser
from .cloud_posture_toolkit import CloudPostureToolkit
from .container_security_toolkit import ContainerSecurityToolkit
from .prowler import ProwlerConfig, ProwlerExecutor, ProwlerParser
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
    # Toolkits
    "CloudPostureToolkit",
    "ContainerSecurityToolkit",
]
