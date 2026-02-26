"""Base parser for normalizing security scanner output.

Provides an abstract interface for parsing scanner-specific output
into the unified SecurityFinding and ScanResult models.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from navconfig.logging import logging

from .models import ScanResult, SecurityFinding


class BaseParser(ABC):
    """Abstract parser for security scanner output.

    Each scanner (Prowler, Trivy, Checkov) implements its own parser
    that normalizes raw output into the unified ScanResult format.

    Subclasses must implement:
    - parse(): Parse raw scanner stdout into a normalized ScanResult
    - normalize_finding(): Convert a single raw finding into SecurityFinding
    """

    def __init__(self) -> None:
        """Initialize the parser with a logger."""
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def parse(self, raw_output: str) -> ScanResult:
        """Parse raw scanner stdout into a normalized ScanResult.

        Implementations should:
        - Handle empty or malformed input gracefully
        - Extract findings and build a ScanSummary
        - Return an empty ScanResult on parse errors, not raise exceptions

        Args:
            raw_output: Raw string output from the scanner (usually JSON).

        Returns:
            Normalized ScanResult with findings and summary.
        """
        ...

    @abstractmethod
    def normalize_finding(self, raw_finding: dict) -> SecurityFinding:
        """Convert a single raw finding into a unified SecurityFinding.

        Implementations should:
        - Map scanner-specific severity levels to SeverityLevel enum
        - Extract resource, region, and other metadata
        - Preserve original data in the 'raw' field

        Args:
            raw_finding: Dictionary from scanner output representing one finding.

        Returns:
            Normalized SecurityFinding instance.
        """
        ...

    def save_result(self, result: ScanResult, path: str) -> str:
        """Persist scan result to a JSON file.

        Creates parent directories if they don't exist.

        Args:
            result: The ScanResult to save.
            path: Destination file path.

        Returns:
            Absolute path of the saved file.
        """
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        self.logger.info("Saved scan result to %s", dest)
        return str(dest.resolve())

    def load_result(self, path: str) -> ScanResult:
        """Load a previously saved scan result from JSON file.

        Args:
            path: Path to the JSON file.

        Returns:
            Deserialized ScanResult.

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Scan result file not found: {path}")
        content = file_path.read_text(encoding="utf-8")
        return ScanResult.model_validate_json(content)
