"""Checkov configuration model.

Defines configuration options for running Checkov IaC security scans including
framework selection, check filters, output format, and external policies.
"""

from typing import Optional

from pydantic import Field

from ..base_executor import BaseExecutorConfig


class CheckovConfig(BaseExecutorConfig):
    """Configuration for Checkov IaC security scanner.

    Extends BaseExecutorConfig with Checkov-specific options for scanning
    Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, and other
    IaC configurations.

    Example:
        config = CheckovConfig(
            frameworks=["terraform", "cloudformation"],
            run_checks=["CKV_AWS_18", "CKV_AWS_21"],
            compact=True,
        )
    """

    # Docker image for Checkov
    docker_image: str = Field(
        default="bridgecrew/checkov:latest",
        description="Docker image for Checkov execution",
    )

    # Framework selection
    frameworks: list[str] = Field(
        default_factory=list,
        description="IaC frameworks to scan: terraform, cloudformation, kubernetes, "
        "helm, dockerfile, arm, bicep, serverless, github_actions, "
        "gitlab_ci, bitbucket_pipelines, circleci_pipelines, argo_workflows",
    )

    # Check filters
    run_checks: list[str] = Field(
        default_factory=list,
        description="Only run these specific check IDs (e.g., CKV_AWS_18)",
    )
    skip_checks: list[str] = Field(
        default_factory=list,
        description="Check IDs to skip (e.g., CKV_AWS_1)",
    )

    # Output options
    output_format: str = Field(
        default="json",
        description="Output format: json, cli, sarif, junitxml, cyclonedx, csv",
    )
    compact: bool = Field(
        default=True,
        description="Only show failed checks (omit passed/skipped)",
    )
    output_file: Optional[str] = Field(
        default=None,
        description="Output file path (defaults to stdout)",
    )

    # External policies
    external_checks_dir: Optional[str] = Field(
        default=None,
        description="Directory containing custom policy files",
    )
    external_checks_git: Optional[str] = Field(
        default=None,
        description="Git URL for external policies (branch@url format)",
    )

    # Secrets scanning
    enable_secret_scan: bool = Field(
        default=True,
        description="Enable secrets scanning (entropy-based detection)",
    )

    # Skip options
    skip_paths: list[str] = Field(
        default_factory=list,
        description="Paths to skip during scanning (glob patterns supported)",
    )
    skip_frameworks: list[str] = Field(
        default_factory=list,
        description="Frameworks to skip",
    )

    # Behavior options
    soft_fail: bool = Field(
        default=False,
        description="Always return exit code 0 (useful for CI)",
    )
    download_external_modules: bool = Field(
        default=True,
        description="Download external Terraform modules (requires internet)",
    )

    # Baseline
    baseline: Optional[str] = Field(
        default=None,
        description="Path to baseline file for suppressing known issues",
    )

    model_config = {"extra": "ignore"}
