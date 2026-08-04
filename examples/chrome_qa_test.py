"""WebAgent QA testing example.

Usage:
    # Visible Chrome (default):
    python examples/chrome_qa_test.py

    # Headless (CI mode):
    CHROME_HEADLESS=1 python examples/chrome_qa_test.py

    # Custom URL:
    TARGET_URL=http://myapp:3000 python examples/chrome_qa_test.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parrot.bots.chrome import (
    ChromeConfig,
    QAAssertion,
    QATestCase,
    WebAgent,
)

logging.basicConfig(level=logging.INFO)


async def main():
    target = os.getenv("TARGET_URL", "https://concierge.trocdigital.io/")
    headless = os.getenv("CHROME_HEADLESS", "0") == "1"

    agent = WebAgent(
        name="QA-Agent",
        chrome_config=ChromeConfig(
            headless=headless,
            viewport="1920x1080",
            no_usage_statistics=True,
        ),
    )

    test_cases = [
        QATestCase(
            name="homepage-loads",
            url=target,
            steps=["Wait for the page to fully load"],
            expected="Page loads without errors",
            assertions=[
                QAAssertion(check="no_console_errors"),
                QAAssertion(check="no_network_failures"),
            ],
            tags=["smoke"],
        ),
        QATestCase(
            name="login-validation",
            url=f"{target}/login",
            steps=[
                "Leave the email field empty",
                "Type '123' in the password field",
                "Click the submit/login button",
            ],
            expected="Validation errors appear for required fields",
            assertions=[
                QAAssertion(check="url_matches", target="/login"),
                QAAssertion(check="element_visible", target=".error-message"),
            ],
            tags=["regression"],
        ),
    ]

    await agent.configure()
    async with agent:
        result = await agent.run_tests(test_cases, url=target)

    report = result.output
    print(f"\n{'='*60}")
    print(f"QA Report: {report.url}")
    print(f"{'='*60}")
    print(f"Summary: {report.summary}")
    print(f"Total: {report.total} | Passed: {report.passed} | Failed: {report.failed}")
    for finding in report.findings:
        icon = "PASS" if finding.status == "pass" else "FAIL"
        print(f"  [{icon}] {finding.test_name}: {finding.detail}")
        if finding.console_errors:
            for err in finding.console_errors:
                print(f"        Console: {err}")


if __name__ == "__main__":
    asyncio.run(main())
