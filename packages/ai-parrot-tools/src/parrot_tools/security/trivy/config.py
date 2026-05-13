"""Trivy configuration model.

Defines configuration options for running Trivy security scans including
severity filters, scanner types, output formats, and cache settings.
"""

from typing import Optional

from pydantic import Field

from ..base_executor import BaseExecutorConfig


class TrivyConfig(BaseExecutorConfig):
    """Configuration for Trivy security scanner.

    Extends BaseExecutorConfig with Trivy-specific options for vulnerability
    scanning, misconfiguration detection, secret scanning, and SBOM generation.

    Example:
        config = TrivyConfig(
            severity_filter=["CRITICAL", "HIGH"],
            scanners=["vuln", "secret"],
            ignore_unfixed=True,
        )
    """

    # Docker image for Trivy
    docker_image: str = Field(
        default="aquasec/trivy:latest",
        description="Docker image for Trivy execution",
    )

    # Required so Trivy (running inside the aquasec/trivy container) can
    # access locally-built images via the host Docker daemon. Without this,
    # `trivy image <local-tag>` fails with "Cannot connect to the Docker
    # daemon" / "UNAUTHORIZED" when it falls back to docker.io.
    mount_docker_socket: bool = Field(
        default=True,
        description=(
            "Mount the host Docker socket into the Trivy container "
            "(required to scan locally-built images via `trivy image`)"
        ),
    )
    docker_socket_path: str = Field(
        default="/var/run/docker.sock",
        description="Host path to the Docker socket to mount",
    )

    # Pre-flight check: verify a `trivy image` target exists on the host
    # Docker daemon before invoking Trivy. Saves the ~10s DB download
    # round-trip when the image is missing or mistyped.
    preflight_image_check: bool = Field(
        default=True,
        description=(
            "Run `docker image inspect <image>` before `trivy image` "
            "scans and raise ImageNotFoundError if the image is missing"
        ),
    )

    # Cache settings
    cache_dir: Optional[str] = Field(
        default=None,
        description="Local directory for Trivy cache (vulnerability DB, etc.)",
    )
    db_skip_update: bool = Field(
        default=False,
        description="Skip vulnerability database update (use cached DB)",
    )

    # Scan filtering
    severity_filter: list[str] = Field(
        default_factory=lambda: ["CRITICAL", "HIGH"],
        description="Severity levels to include: CRITICAL, HIGH, MEDIUM, LOW, UNKNOWN",
    )
    ignore_unfixed: bool = Field(
        default=False,
        description="Ignore vulnerabilities without available fixes",
    )

    # Scanner types
    scanners: list[str] = Field(
        default_factory=lambda: ["vuln", "secret"],
        description="Scanner types: vuln, misconfig, secret, license",
    )

    # Output format
    output_format: str = Field(
        default="json",
        description="Output format: json, table, sarif, cyclonedx, spdx, github",
    )
    output_file: Optional[str] = Field(
        default=None,
        description="Output file path (defaults to stdout)",
    )

    # Vulnerability scanning options
    vuln_type: list[str] = Field(
        default_factory=lambda: ["os", "library"],
        description="Vulnerability types: os, library",
    )

    # Image scanning options
    image_config_scanners: list[str] = Field(
        default_factory=list,
        description="Enable image config scanners: config, secret",
    )

    # Kubernetes options
    k8s_context: Optional[str] = Field(
        default=None,
        description="Kubernetes context name",
    )
    k8s_namespace: Optional[str] = Field(
        default=None,
        description="Kubernetes namespace (default: all)",
    )
    k8s_components: list[str] = Field(
        default_factory=lambda: ["workload", "infra"],
        description="K8s components to scan: workload, infra, rbac",
    )

    # Compliance options
    compliance: Optional[str] = Field(
        default=None,
        description="Compliance spec: docker-cis-1.6.0, k8s-cis-1.23, etc.",
    )

    # Misconfiguration options
    config_policy: Optional[str] = Field(
        default=None,
        description="Path to custom policy directory",
    )
    config_data: Optional[str] = Field(
        default=None,
        description="Path to custom data directory for policies",
    )

    # Secret scanning options
    secret_config: Optional[str] = Field(
        default=None,
        description="Path to secret scanning config file",
    )

    # Skip options
    skip_dirs: list[str] = Field(
        default_factory=list,
        description="Directories to skip during scanning",
    )
    skip_files: list[str] = Field(
        default_factory=list,
        description="Files to skip during scanning",
    )

    # Exit code behavior
    exit_code: int = Field(
        default=0,
        description="Exit code when vulnerabilities are found (0 = always success)",
    )

    model_config = {"extra": "ignore"}
