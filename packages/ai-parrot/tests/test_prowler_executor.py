"""Unit tests for the Prowler executor."""

import pytest

from parrot.tools.security.prowler.config import ProwlerConfig
from parrot.tools.security.prowler.executor import ProwlerExecutor


class TestProwlerConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = ProwlerConfig()
        assert config.provider == "aws"
        assert config.docker_image == "toniblyx/prowler:latest"
        assert "json-ocsf" in config.output_modes
        assert config.use_docker is True
        assert config.timeout == 600

    def test_inherits_base_config(self):
        """Config inherits from BaseExecutorConfig."""
        config = ProwlerConfig(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret123",
        )
        assert config.aws_access_key_id == "AKIATEST"
        assert config.aws_secret_access_key == "secret123"

    def test_aws_config(self):
        """AWS-specific configuration."""
        config = ProwlerConfig(
            provider="aws",
            filter_regions=["us-east-1", "eu-west-1"],
            services=["s3", "iam"],
            compliance_framework="soc2",
        )
        assert config.filter_regions == ["us-east-1", "eu-west-1"]
        assert config.services == ["s3", "iam"]
        assert config.compliance_framework == "soc2"

    def test_azure_config(self):
        """Azure-specific configuration."""
        config = ProwlerConfig(
            provider="azure",
            azure_auth_method="sp-env-auth",
            subscription_ids=["sub-123", "sub-456"],
        )
        assert config.azure_auth_method == "sp-env-auth"
        assert config.subscription_ids == ["sub-123", "sub-456"]

    def test_gcp_config(self):
        """GCP-specific configuration."""
        config = ProwlerConfig(
            provider="gcp",
            gcp_project_ids=["project-1", "project-2"],
        )
        assert len(config.gcp_project_ids) == 2
        assert config.gcp_project_ids[0] == "project-1"

    def test_kubernetes_config(self):
        """Kubernetes-specific configuration."""
        config = ProwlerConfig(
            provider="kubernetes",
            kubernetes_context="my-cluster",
            kubernetes_namespace="default",
        )
        assert config.kubernetes_context == "my-cluster"
        assert config.kubernetes_namespace == "default"

    def test_scan_filtering(self):
        """Scan filtering options."""
        config = ProwlerConfig(
            checks=["check1", "check2"],
            excluded_checks=["check3"],
            excluded_services=["cloudtrail"],
            severity=["critical", "high"],
        )
        assert config.checks == ["check1", "check2"]
        assert config.excluded_checks == ["check3"]
        assert config.excluded_services == ["cloudtrail"]
        assert config.severity == ["critical", "high"]


class TestProwlerExecutor:
    @pytest.fixture
    def aws_executor(self):
        config = ProwlerConfig(
            provider="aws",
            filter_regions=["us-east-1"],
            services=["s3", "iam"],
            severity=["critical", "high"],
        )
        return ProwlerExecutor(config)

    @pytest.fixture
    def azure_executor(self):
        config = ProwlerConfig(
            provider="azure",
            azure_auth_method="sp-env-auth",
            subscription_ids=["sub-123"],
        )
        return ProwlerExecutor(config)

    @pytest.fixture
    def gcp_executor(self):
        config = ProwlerConfig(
            provider="gcp",
            gcp_project_ids=["project-1", "project-2"],
        )
        return ProwlerExecutor(config)

    @pytest.fixture
    def k8s_executor(self):
        config = ProwlerConfig(
            provider="kubernetes",
            kubernetes_context="my-cluster",
            kubernetes_namespace="kube-system",
        )
        return ProwlerExecutor(config)

    def test_default_cli_name(self, aws_executor):
        """Default CLI name is 'prowler'."""
        assert aws_executor._default_cli_name() == "prowler"

    def test_build_aws_args(self, aws_executor):
        """AWS CLI args are built correctly (Prowler v4+ format)."""
        args = aws_executor._build_cli_args()
        assert args[0] == "aws"
        assert "--output-formats" in args
        assert "json-ocsf" in args
        assert "--region" in args
        assert "us-east-1" in args
        assert "--service" in args
        assert "s3,iam" in args
        assert "--severity" in args
        assert "critical,high" in args

    def test_build_azure_args(self, azure_executor):
        """Azure CLI args are built correctly."""
        args = azure_executor._build_cli_args()
        assert args[0] == "azure"
        assert "--sp-env-auth" in args
        assert "--subscription-ids" in args
        assert "sub-123" in args

    def test_build_gcp_args(self, gcp_executor):
        """GCP CLI args are built correctly."""
        args = gcp_executor._build_cli_args()
        assert args[0] == "gcp"
        assert "--project-ids" in args
        assert "project-1,project-2" in args

    def test_build_kubernetes_args(self, k8s_executor):
        """Kubernetes CLI args are built correctly."""
        args = k8s_executor._build_cli_args()
        assert args[0] == "kubernetes"
        assert "--context" in args
        assert "my-cluster" in args
        assert "--namespace" in args
        assert "kube-system" in args

    def test_build_args_with_compliance(self):
        """Compliance framework flag is included (Prowler v4+ adds provider suffix)."""
        config = ProwlerConfig(
            provider="aws",
            compliance_framework="hipaa",
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--compliance" in args
        assert "hipaa_aws" in args  # Prowler v4+ requires provider suffix

    def test_build_args_with_exclusions(self):
        """Exclusion flags are included (Prowler v4+ format)."""
        config = ProwlerConfig(
            provider="aws",
            excluded_checks=["check1", "check2"],
            excluded_services=["cloudtrail"],
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--excluded-check" in args
        assert "check1,check2" in args
        assert "--excluded-service" in args
        assert "cloudtrail" in args

    def test_build_args_with_specific_checks(self):
        """Specific check flags are included (Prowler v4+ format)."""
        config = ProwlerConfig(
            provider="aws",
            checks=["s3_bucket_public_access", "iam_root_mfa"],
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--check" in args
        assert "s3_bucket_public_access,iam_root_mfa" in args

    def test_override_provider_in_kwargs(self, aws_executor):
        """Provider can be overridden via kwargs."""
        args = aws_executor._build_cli_args(provider="gcp")
        assert args[0] == "gcp"

    def test_override_services_in_kwargs(self, aws_executor):
        """Services can be overridden via kwargs (Prowler v4+ format)."""
        args = aws_executor._build_cli_args(services=["ec2"])
        assert "ec2" in args
        # Original services should be replaced
        assert args.count("--service") == 1  # Only one service flag set

    def test_output_modes(self):
        """Multiple output modes are supported (Prowler v4+ format)."""
        config = ProwlerConfig(
            provider="aws",
            output_modes=["json-ocsf", "html", "csv"],
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--output-formats" in args
        idx = args.index("--output-formats")
        assert args[idx + 1] == "json-ocsf,html,csv"

    def test_output_directory(self):
        """Output directory is included when set (Prowler v4+ format)."""
        config = ProwlerConfig(
            provider="aws",
            output_directory="/tmp/prowler-results",
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--output-directory" in args
        assert "/tmp/prowler-results" in args

    def test_mutelist_file(self):
        """Mutelist file is included when set (Prowler v4+ format)."""
        config = ProwlerConfig(
            provider="aws",
            mutelist_file="/path/to/mutelist.yaml",
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--mutelist-file" in args
        assert "/path/to/mutelist.yaml" in args

    def test_scan_unused_services(self):
        """Scan unused services flag is included."""
        config = ProwlerConfig(
            provider="aws",
            scan_unused_services=True,
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--scan-unused-services" in args

    def test_aws_profile(self):
        """AWS profile is included when set (Prowler v4+ format)."""
        config = ProwlerConfig(
            provider="aws",
            aws_profile="my-profile",
        )
        executor = ProwlerExecutor(config)
        args = executor._build_cli_args()
        assert "--profile" in args
        assert "my-profile" in args

    def test_default_config(self):
        """Executor works with default config (Prowler v4+ format)."""
        executor = ProwlerExecutor()
        args = executor._build_cli_args()
        assert args[0] == "aws"
        assert "--output-formats" in args


class TestImports:
    def test_import_from_prowler_package(self):
        """Components can be imported from prowler package."""
        from parrot.tools.security.prowler import ProwlerConfig, ProwlerExecutor

        assert ProwlerConfig is not None
        assert ProwlerExecutor is not None

    def test_import_from_security_package(self):
        """Components can be imported from security package."""
        from parrot.tools.security import ProwlerConfig, ProwlerExecutor

        config = ProwlerConfig(provider="aws")
        executor = ProwlerExecutor(config)
        assert executor is not None
