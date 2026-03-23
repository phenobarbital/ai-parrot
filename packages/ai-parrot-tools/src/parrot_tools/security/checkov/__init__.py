"""Checkov IaC security scanner integration.

Checkov is a static code analysis tool for infrastructure-as-code (IaC),
scanning Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, and more
for security misconfigurations and secrets.

Usage:
    from parrot.tools.security.checkov import CheckovConfig, CheckovExecutor

    config = CheckovConfig(frameworks=["terraform"])
    executor = CheckovExecutor(config)

    stdout, stderr, code = await executor.scan_directory("./terraform")
"""

from .config import CheckovConfig
from .executor import CheckovExecutor
from .parser import CheckovParser

__all__ = [
    "CheckovConfig",
    "CheckovExecutor",
    "CheckovParser",
]
