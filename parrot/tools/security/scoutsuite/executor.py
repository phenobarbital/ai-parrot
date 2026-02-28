"""ScoutSuite executor for running cloud security scans.

Extends BaseExecutor to provide ScoutSuite-specific CLI argument building
and scan execution methods.
"""

from typing import Optional
import tempfile
from pathlib import Path

from ..base_executor import BaseExecutor
from .config import ScoutSuiteConfig


class ScoutSuiteExecutor(BaseExecutor):
    """Executes ScoutSuite security scans.

    ScoutSuite CLI pattern: `scout <provider> [options]`
    
    Example:
        scout aws --report-dir ./aws-scan-2023-12-18 \\
                  --report-name aws-report \\
                  --result-format json \\
                  --access-key-id ACCESS_KEY_ID \\
                  --secret-access-key SECRET_KEY
    """

    def __init__(self, config: Optional[ScoutSuiteConfig] = None):
        """Initialize the ScoutSuite executor.

        Args:
            config: ScoutSuite configuration. Uses defaults if not provided.
        """
        super().__init__(config or ScoutSuiteConfig())
        self.config: ScoutSuiteConfig = self.config  # type narrowing
        self.expected_exit_codes = [0, 1]  # Scout returned 1 on findings sometimes

    def _default_cli_name(self) -> str:
        """Return the default ScoutSuite CLI binary name."""
        return "scout"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build ScoutSuite CLI arguments from configuration.

        Args:
            **kwargs: Override config values for this invocation.

        Returns:
            List of CLI argument strings.
        """
        provider = kwargs.get("provider", self.config.provider)
        args = [provider]

        # Region filtering
        regions = kwargs.get("regions", self.config.regions)
        if regions:
            args.extend(["--regions", ",".join(regions)])

        # Services to scan
        services = kwargs.get("services", self.config.services)
        if services:
            args.extend(["--services", ",".join(services)])

        # Output options
        report_dir = kwargs.get("report_dir", self.config.report_dir or self.config.results_dir)
        if report_dir:
            args.extend(["--report-dir", str(report_dir)])

        report_name = kwargs.get("report_name", self.config.report_name)
        if report_name:
            args.extend(["--report-name", str(report_name)])
            
        result_format = kwargs.get("result_format", self.config.result_format)
        if result_format:
            args.extend(["--result-format", result_format])

        # Passing credentials explicitly if needed by the AWS provider, though 
        # BaseExecutor already injects these effectively as environment vars.
        # However, the user explicitly requested `--access-key-id` and `--secret-access-key`.
        if provider == "aws":
            aws_access_key_id = self.config.aws_access_key_id
            if aws_access_key_id:
                args.extend(["--access-key-id", aws_access_key_id])
                
            aws_secret_access_key = self.config.aws_secret_access_key
            if aws_secret_access_key:
                args.extend(["--secret-access-key", aws_secret_access_key])
                
            aws_session_token = self.config.aws_session_token
            if aws_session_token:
                args.extend(["--session-token", aws_session_token])
                
            aws_profile = self.config.aws_profile
            if aws_profile:
                args.extend(["--profile", aws_profile])

        return args

    def _build_scan_kwargs(
        self,
        provider: Optional[str] = None,
        services: Optional[list[str]] = None,
        regions: Optional[list[str]] = None,
        report_name: Optional[str] = None,
        report_dir: Optional[str] = None,
    ) -> dict:
        """Build kwargs dict from scan parameters."""
        kwargs: dict = {}
        if provider:
            kwargs["provider"] = provider
        if services:
            kwargs["services"] = services
        if regions:
            kwargs["regions"] = regions
        if report_name:
            kwargs["report_name"] = report_name
        if report_dir:
            kwargs["report_dir"] = report_dir
        return kwargs

    async def run_scan(
        self,
        provider: Optional[str] = None,
        services: Optional[list[str]] = None,
        regions: Optional[list[str]] = None,
        report_name: Optional[str] = None,
        report_dir: Optional[str] = None,
    ) -> tuple[str, str, int]:
        """Run a ScoutSuite security scan.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        kwargs = self._build_scan_kwargs(
            provider, services, regions, report_name, report_dir
        )
        return await self._execute_with_json_capture(self.execute, **kwargs)

    async def run_scan_streaming(
        self,
        progress_callback=None,
        provider: Optional[str] = None,
        services: Optional[list[str]] = None,
        regions: Optional[list[str]] = None,
        report_name: Optional[str] = None,
        report_dir: Optional[str] = None,
    ) -> tuple[str, str, int]:
        """Run a ScoutSuite scan with real-time stderr streaming."""
        kwargs = self._build_scan_kwargs(
            provider, services, regions, report_name, report_dir
        )
        return await self._execute_with_json_capture(
            self.execute_streaming, progress_callback=progress_callback, **kwargs
        )

    async def _execute_with_json_capture(self, execute_func, *args, **kwargs) -> tuple[str, str, int]:
        """Run execution and capture JSON output.
        
        Uses a temporary directory to manage reports if the user doesn't pass one explicitly.
        """
        # If user provided a report directory, use it directly
        explicit_report_dir = kwargs.get("report_dir", self.config.report_dir or self.config.results_dir)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            active_report_dir = explicit_report_dir or str(temp_path)
            kwargs["report_dir"] = active_report_dir
            
            # Make sure we use JSON format to parse results
            if "result_format" not in kwargs:
                kwargs["result_format"] = "json"

            # Run the scan
            stdout, stderr, exit_code = await execute_func(*args, **kwargs)

            # Find the generated JSON result in the scoutsuite-report directory
            report_name = kwargs.get("report_name", self.config.report_name)
            report_filename = f"{report_name}.js" if kwargs.get("result_format") == "json" else f"{report_name}.json"
            
            # ScoutSuite typically generates JSON inside an HTML wrapper called scoutsuite_results_...js
            # Let's search broadly for .js or .json in the output dir
            target_dir = Path(active_report_dir)
            
            # Scout creates scoutsuite-report/scoutsuite-results by default if report_name is not fully mapping
            results_files = list(target_dir.rglob("scoutsuite_results*.js"))
            if not results_files:
                results_files = list(target_dir.rglob("*.json"))
                
            if results_files:
                # Read the latest file found
                json_content = results_files[-1].read_text(encoding="utf-8")
                # ScoutSuite .js files start with `scoutsuite_results = { ... }` which needs to be cleaned for pure JSON
                if json_content.startswith("scoutsuite_results ="):
                    json_content = json_content.replace("scoutsuite_results =", "", 1).strip().strip(";")
                return json_content, stderr, exit_code
            else:
                self.logger.warning("No JSON result file found in ScoutSuite output")
                return stdout, stderr, exit_code
