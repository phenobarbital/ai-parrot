"""Prowler-specific configuration.

Prowler is a cloud security posture assessment tool supporting
AWS, Azure, GCP, and Kubernetes.
"""

from typing import Optional

from pydantic import Field

from ..base_executor import BaseExecutorConfig


class ProwlerConfig(BaseExecutorConfig):
    """Configuration for Prowler security scanner.

    Extends BaseExecutorConfig with Prowler-specific options for
    provider selection, scan filtering, and compliance frameworks.
    """

    # Docker image
    docker_image: str = Field(
        default="toniblyx/prowler:latest",
        description="Docker image for Prowler",
    )

    # Provider selection
    provider: str = Field(
        default="aws",
        description="Cloud provider: aws, azure, gcp, kubernetes",
    )

    # Output configuration
    output_modes: list[str] = Field(
        default_factory=lambda: ["json-ocsf"],
        description="Output formats: csv, json, json-ocsf, json-asff, html",
    )
    output_directory: Optional[str] = Field(
        default=None,
        description="Custom output directory for scan results",
    )

    # AWS-specific options
    filter_regions: list[str] = Field(
        default_factory=list,
        description="AWS regions to scan (empty = all regions)",
    )

    # Azure-specific options
    azure_auth_method: Optional[str] = Field(
        default=None,
        description="Azure auth method: sp-env-auth, browser-auth, managed-identity-auth",
    )
    subscription_ids: list[str] = Field(
        default_factory=list,
        description="Azure subscription IDs to scan",
    )

    # GCP-specific options
    gcp_project_ids: list[str] = Field(
        default_factory=list,
        description="GCP project IDs to scan",
    )

    # Kubernetes-specific options
    kubernetes_context: Optional[str] = Field(
        default=None,
        description="Kubernetes context to use",
    )

    kubernetes_namespace: Optional[str] = Field(
        default=None,
        description="Kubernetes namespace to scan",
    )

    # Scan filtering
    services: list[str] = Field(
        default_factory=list,
        description="Specific services to scan (e.g., s3, iam, ec2)",
    )
    checks: list[str] = Field(
        default_factory=list,
        description="Specific check IDs to run",
    )
    excluded_checks: list[str] = Field(
        default_factory=list,
        description="Check IDs to exclude from scan",
    )
    excluded_services: list[str] = Field(
        default_factory=list,
        description="Services to exclude from scan",
    )
    severity: list[str] = Field(
        default_factory=list,
        description="Severity levels to include: critical, high, medium, low, informational",
    )

    # Compliance
    compliance_framework: Optional[str] = Field(
        default=None,
        description="Compliance framework filter: soc2, hipaa, pci_dss, gdpr, etc.",
    )

    # Scan behavior
    mutelist_file: Optional[str] = Field(
        default=None,
        description="Path to mutelist file for suppressing findings",
    )
    scan_unused_services: bool = Field(
        default=False,
        description="Scan unused services (slower but more comprehensive)",
    )

    model_config = {"extra": "ignore"}
