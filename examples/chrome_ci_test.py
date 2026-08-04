"""WebAgent CI/CD QA testing example.

Designed for CI pipelines — runs headless, filters by tags, retries
flaky tests, applies a per-test timeout, saves failure screenshots as
CI artifacts, writes JUnit XML for the test dashboard, and exits with
0 (all pass) or 1 (any failure/error) for deploy-or-block gate
decisions.

Usage:
    # In CircleCI / GitHub Actions / GitLab CI:
    CHROME_HEADLESS=1 TARGET_URL=http://localhost:3000 \\
        python examples/chrome_ci_test.py

    # With tag filtering (only run smoke tests on a PR):
    QA_TAGS=smoke CHROME_HEADLESS=1 python examples/chrome_ci_test.py

    # Or use the CLI runner directly with the sample test file:
    python -m parrot.bots.chrome_runner \\
        --test-file examples/qa-tests-sample.json \\
        --headless --tags smoke \\
        --junit-output qa-results/results.xml \\
        --screenshot-dir qa-screenshots/

Example .circleci/config.yml snippet:
    jobs:
      ui-qa:
        docker:
          - image: cimg/python:3.12-browsers
        steps:
          - checkout
          - run: uv pip install -e ".[all]"
          - run:
              command: python -m myapp serve --port 3000
              background: true
          - run: |
              CHROME_HEADLESS=1 TARGET_URL=http://localhost:3000 \\
              python examples/chrome_ci_test.py
          - store_test_results:
              path: qa-results/
          - store_artifacts:
              path: qa-screenshots/
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parrot.bots.chrome import (
    ChromeConfig,
    QAAssertion,
    QATestCase,
    WebAgent,
)

logging.basicConfig(level=logging.INFO)

QA_RESULTS_DIR = "qa-results"
QA_SCREENSHOTS_DIR = "qa-screenshots"


async def main() -> int:
    target = os.getenv("TARGET_URL", "http://localhost:3000")
    headless = os.getenv("CHROME_HEADLESS", "1") == "1"
    tags_env = os.getenv("QA_TAGS")
    tags = tags_env.split(",") if tags_env else ["smoke"]

    os.makedirs(QA_RESULTS_DIR, exist_ok=True)
    os.makedirs(QA_SCREENSHOTS_DIR, exist_ok=True)

    agent = WebAgent(
        name="CI-QA-Agent",
        chrome_config=ChromeConfig(
            headless=headless,
            viewport="1920x1080",
            no_usage_statistics=True,
        ),
        default_timeout_ms=60_000,
        screenshot_dir=QA_SCREENSHOTS_DIR,
    )

    test_cases = [
        QATestCase(
            name="homepage-smoke",
            url=target,
            steps=["Wait for the page to fully load"],
            expected="Page loads without errors",
            assertions=[
                QAAssertion(check="no_console_errors"),
                QAAssertion(check="no_network_failures"),
                QAAssertion(check="response_status", target="200"),
            ],
            tags=["smoke"],
            max_retries=1,
            timeout_ms=30_000,
        ),
        QATestCase(
            name="login-validation",
            url=f"{target}/login",
            steps=[
                "Leave the email field empty",
                "Click the submit/login button",
            ],
            expected="Validation errors appear for required fields",
            assertions=[
                QAAssertion(check="url_matches", target="/login"),
                QAAssertion(
                    check="element_visible",
                    target=".error-message",
                    wait_timeout_ms=3000,
                ),
            ],
            tags=["regression"],
        ),
    ]

    await agent.configure()
    async with agent:
        result = await agent.run_tests(test_cases, url=target, tags=tags)

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
        if finding.console_errors:
            for err in finding.console_errors:
                print(f"        Console: {err}")

    junit_path = os.path.join(QA_RESULTS_DIR, "results.xml")
    Path(junit_path).write_text(report.to_junit_xml(), encoding="utf-8")
    print(f"\nJUnit XML written to: {junit_path}")

    return report.exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
