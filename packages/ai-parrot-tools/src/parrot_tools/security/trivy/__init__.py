"""Trivy security scanner integration.

Trivy is a comprehensive vulnerability scanner for containers, filesystems,
Git repositories, Kubernetes clusters, and IaC configurations.

Usage:
    from parrot.tools.security.trivy import TrivyConfig, TrivyExecutor, TrivyParser

    config = TrivyConfig(severity_filter=["CRITICAL", "HIGH"])
    executor = TrivyExecutor(config)
    parser = TrivyParser()

    stdout, stderr, code = await executor.scan_image("nginx:latest")
    result = parser.parse(stdout)
"""

from .config import TrivyConfig
from .executor import TrivyExecutor
from .parser import TrivyParser

__all__ = [
    "TrivyConfig",
    "TrivyExecutor",
    "TrivyParser",
]
