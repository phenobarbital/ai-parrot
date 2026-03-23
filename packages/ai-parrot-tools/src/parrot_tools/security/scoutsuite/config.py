"""ScoutSuite-specific configuration.

ScoutSuite is an open source multi-cloud security-auditing tool.
"""

from typing import Optional

from pydantic import Field

from ..base_executor import BaseExecutorConfig


class ScoutSuiteConfig(BaseExecutorConfig):
    """Configuration for ScoutSuite security scanner.

    Extends BaseExecutorConfig with ScoutSuite-specific options.
    """

    # Execution overrides (ScoutSuite usually runs directly via CLI)
    use_docker: bool = Field(
        default=False,
        description="Run via Docker or direct CLI (usually False for ScoutSuite)",
    )

    # Provider selection
    provider: str = Field(
        default="aws",
        description="Cloud provider: aws, azure, gcp, aliyun, oracle",
    )

    # Output configuration
    result_format: str = Field(
        default="json",
        description="Output result format, e.g json",
    )
    report_name: Optional[str] = Field(
        default="scoutsuite-report",
        description="Name of the generated report file without extension",
    )
    report_dir: Optional[str] = Field(
        default=None,
        description="Custom directory for the report (maps to output_directory or results_dir if none)",
    )

    # Filtering Options
    regions: list[str] = Field(
        default_factory=list,
        description="Specific regions to scan",
    )
    services: list[str] = Field(
        default_factory=list,
        description="Specific services to scan",
    )

    model_config = {"extra": "ignore"}
