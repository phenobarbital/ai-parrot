"""CLI runner for WebAgent QA tests.

Provides a zero-code entry point for running `WebAgent` QA test suites
from CI/CD pipelines (CircleCI, GitHub Actions, GitLab CI).

Usage:
    python -m parrot.bots.chrome_runner --test-file tests.json --headless

    CHROME_HEADLESS=1 TARGET_URL=http://app:3000 QA_TAGS=smoke \\
        python -m parrot.bots.chrome_runner --test-file tests.json \\
        --junit-output results.xml --screenshot-dir qa-screenshots/
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from .chrome import ChromeConfig, QATestCase, WebAgent

logger = logging.getLogger(__name__)


def load_test_cases(test_file: str) -> list[QATestCase]:
    """Load `QATestCase` definitions from a JSON or YAML file.

    Args:
        test_file: Path to a `.json`, `.yaml`, or `.yml` file containing
            either a single test case object or a list of test case
            objects.

    Returns:
        list[QATestCase]: The parsed and validated test cases.

    Raises:
        SystemExit: With code 2 if the file cannot be read, is not valid
            JSON/YAML, or (for YAML) PyYAML is not installed.
    """
    path = Path(test_file)
    if not path.is_file():
        print(f"ERROR: test file not found: {test_file}", file=sys.stderr)
        sys.exit(2)

    text = path.read_text(encoding="utf-8")

    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            print(
                "ERROR: PyYAML is required for YAML test files. "
                "Install with: uv pip install pyyaml",
                file=sys.stderr,
            )
            sys.exit(2)
        raw = yaml.safe_load(text)
    else:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid JSON in {test_file}: {exc}", file=sys.stderr)
            sys.exit(2)

    if not isinstance(raw, list):
        raw = [raw]
    return [QATestCase.model_validate(item) for item in raw]


def build_parser() -> argparse.ArgumentParser:
    """Build the `argparse.ArgumentParser` for the CLI runner.

    Returns:
        argparse.ArgumentParser: Configured parser with all CLI flags.
    """
    parser = argparse.ArgumentParser(
        prog="parrot.bots.chrome_runner",
        description="Run WebAgent QA tests from a definition file.",
    )
    parser.add_argument(
        "--test-file", required=True, help="Path to JSON/YAML test definitions"
    )
    parser.add_argument("--url", default=None, help="Base URL override")
    parser.add_argument(
        "--headless", action="store_true", default=False, help="Run Chrome headless"
    )
    parser.add_argument("--tags", default=None, help="Comma-separated tag filter")
    parser.add_argument(
        "--junit-output", default=None, help="Path to write JUnit XML"
    )
    parser.add_argument(
        "--screenshot-dir", default=None, help="Directory for failure screenshots"
    )
    parser.add_argument(
        "--default-timeout",
        type=int,
        default=60_000,
        help="Default per-test timeout in ms",
    )
    parser.add_argument(
        "--port", type=int, default=9222, help="Chrome debugging port"
    )
    parser.add_argument(
        "--viewport", default=None, help="Viewport size (e.g. 1920x1080)"
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False, help="Enable DEBUG logging"
    )
    return parser


async def run_qa(
    test_file: str,
    url: str | None = None,
    headless: bool = True,
    tags: list[str] | None = None,
    junit_output: str | None = None,
    screenshot_dir: str | None = None,
    default_timeout_ms: int = 60_000,
    port: int = 9222,
    viewport: str | None = None,
) -> int:
    """Execute QA tests from a file and return an exit code.

    Args:
        test_file: Path to the JSON/YAML file with `QATestCase` definitions.
        url: Base URL override (defaults to the first test case's URL).
        headless: Whether to launch Chrome headless.
        tags: Optional tag filter — only cases whose `tags` intersect
            this list are executed.
        junit_output: If set, path to write the JUnit XML report to.
        screenshot_dir: If set, directory for failure screenshots
            (created if missing).
        default_timeout_ms: Default per-test timeout in milliseconds.
        port: Chrome debugging port.
        viewport: Initial viewport size (e.g. `"1920x1080"`).

    Returns:
        int: `0` if all tests passed, `1` if any failed/errored.
    """
    if screenshot_dir:
        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)

    test_cases = load_test_cases(test_file)

    agent = WebAgent(
        name="CI-QA-Agent",
        chrome_config=ChromeConfig(
            headless=headless,
            port=port,
            viewport=viewport,
        ),
        default_timeout_ms=default_timeout_ms,
        screenshot_dir=screenshot_dir,
    )

    await agent.configure()
    async with agent:
        result = await agent.run_tests(test_cases, url=url, tags=tags)

    report = result.output

    print(f"\n{'=' * 60}")
    print(f"QA Report: {report.url}")
    print(f"{'=' * 60}")
    print(f"Summary: {report.summary}")
    print(
        f"Total: {report.total} | Passed: {report.passed} | "
        f"Failed: {report.failed} | Errors: {report.errors} | "
        f"Skipped: {report.skipped}"
    )
    for finding in report.findings:
        print(f"  [{finding.status.upper()}] {finding.test_name}: {finding.detail}")

    if junit_output:
        Path(junit_output).write_text(report.to_junit_xml(), encoding="utf-8")
        print(f"\nJUnit XML written to: {junit_output}")

    return report.exit_code


def main() -> None:
    """CLI entry point: `python -m parrot.bots.chrome_runner`."""
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    # Environment variable overrides — CLI flags take precedence.
    headless = args.headless or os.getenv("CHROME_HEADLESS", "0") == "1"
    url = args.url or os.getenv("TARGET_URL")
    tags_str = args.tags or os.getenv("QA_TAGS")
    tags = tags_str.split(",") if tags_str else None

    exit_code = asyncio.run(
        run_qa(
            test_file=args.test_file,
            url=url,
            headless=headless,
            tags=tags,
            junit_output=args.junit_output,
            screenshot_dir=args.screenshot_dir,
            default_timeout_ms=args.default_timeout,
            port=args.port,
            viewport=args.viewport,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
