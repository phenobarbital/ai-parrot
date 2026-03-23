"""Prowler security scanner integration.

Prowler is a cloud security posture assessment tool supporting
AWS, Azure, GCP, and Kubernetes.

Usage:
    from parrot.tools.security.prowler import ProwlerExecutor, ProwlerConfig, ProwlerParser

    config = ProwlerConfig(
        provider="aws",
        filter_regions=["us-east-1"],
        services=["s3", "iam"],
    )
    executor = ProwlerExecutor(config)
    stdout, stderr, code = await executor.run_scan()

    # Parse results
    parser = ProwlerParser()
    result = parser.parse(stdout)
"""

from .config import ProwlerConfig
from .executor import ProwlerExecutor
from .parser import ProwlerParser

__all__ = [
    "ProwlerConfig",
    "ProwlerExecutor",
    "ProwlerParser",
]
