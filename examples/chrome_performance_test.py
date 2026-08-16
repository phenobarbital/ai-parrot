"""Troc360 Staging QA test using WebAgent.

Usage:
    # Visible Chrome (default):
    python examples/chrome_performance_test.py

    # Headless (CI mode):
    CHROME_HEADLESS=1 python examples/chrome_performance_test.py

    # Attach to an already-running Chrome:
    CHROME_AUTO_CONNECT=1 python examples/chrome_performance_test.py

Prerequisites:
    Chrome must be launchable or already running with:
        google-chrome --remote-debugging-port=9222
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parrot.bots.chrome import (
    ChromeConfig,
    QAAssertion,
    QAFinding,
    QATestCase,
    WebAgent,
)

logging.basicConfig(level=logging.INFO)

BASE_URL = "https://troc360.staging.trocdigital.io"


def _ensure_chrome(port: int = 9222, headless: bool = False) -> None:
    """Start Chrome with remote debugging if not already running."""
    import shutil
    import socket
    import subprocess
    import tempfile
    import time

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(f"Chrome already listening on port {port}")
            return

    chrome_bin = None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            chrome_bin = name
            break
    if not chrome_bin:
        raise RuntimeError("No Chrome/Chromium binary found in PATH")

    user_data_dir = os.path.join(tempfile.gettempdir(), "chrome-qa-profile")
    os.makedirs(user_data_dir, exist_ok=True)

    cmd = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--remote-allow-origins=*",
    ]
    if headless:
        cmd.insert(1, "--headless=new")

    print(f"Launching {chrome_bin} ({'headless' if headless else 'visible'}) on port {port}...")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    for _ in range(15):
        time.sleep(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                print("Chrome is ready.")
                return
    raise RuntimeError(f"Chrome failed to start on port {port} within 15s")


async def main():
    headless = os.getenv("CHROME_HEADLESS", "0") == "1"
    port = int(os.getenv("CHROME_PORT", "9222"))

    _ensure_chrome(port=port, headless=headless)

    agent = WebAgent(
        name="Troc360-QA",
        chrome_config=ChromeConfig(
            headless=headless,
            viewport="1920x1080",
            no_usage_statistics=True,
            auto_connect=True,
            port=port,
        ),
    )

    test_cases = [
        QATestCase(
            name="login",
            url=f"{BASE_URL}/login",
            steps=[
                'Type "jlara@trocglobal.com" into the input with id="email"',
                'Type "Welc@me3501!" into the password input field',
                'Click the "Sign In" button',
                "Wait for navigation to complete",
            ],
            expected="User is redirected to the home page after login",
            assertions=[
                QAAssertion(check="url_matches", target="/home"),
            ],
            tags=["smoke", "auth"],
        ),
        QATestCase(
            name="home-no-errors",
            url=f"{BASE_URL}/home",
            steps=[
                "Wait for the page to fully load",
                "Check the browser console for errors",
                "Check network requests for failures",
            ],
            expected="Home page loads without console or network errors",
            assertions=[
                QAAssertion(check="no_console_errors"),
                QAAssertion(check="no_network_failures"),
            ],
            tags=["smoke"],
        ),
        QATestCase(
            name="navigate-flexroc",
            url=f"{BASE_URL}/home",
            steps=[
                'Find and click the card that contains the text "FLEXROC"',
                "Wait for the page to fully load",
            ],
            expected="FLEXROC page loads successfully",
            assertions=[
                QAAssertion(check="no_console_errors"),
                QAAssertion(check="no_network_failures"),
            ],
            tags=["navigation"],
        ),
        QATestCase(
            name="flexroc-fieldsync-visible",
            url=f"{BASE_URL}/home",
            steps=[
                'Click the card that contains the text "FLEXROC"',
                "Wait for the page to fully load",
                'Verify that a card with the text "FieldSync Manager" is visible on the page',
            ],
            expected='"FieldSync Manager" card is rendered and visible',
            assertions=[
                QAAssertion(
                    check="element_visible",
                    target="FieldSync Manager",
                ),
                QAAssertion(check="no_console_errors"),
                QAAssertion(check="no_network_failures"),
            ],
            tags=["regression"],
        ),
    ]

    all_findings: list[QAFinding] = []
    total = passed = failed = 0

    await agent.configure()
    async with agent:
        for tc in test_cases:
            print(f"\n--- Running: {tc.name} ---")
            result = await agent.run_tests([tc], url=BASE_URL)
            report = result.output
            all_findings.extend(report.findings)
            total += report.total
            passed += report.passed
            failed += report.failed
            for finding in report.findings:
                icon = "PASS" if finding.status == "pass" else "FAIL"
                print(f"  [{icon}] {finding.test_name}: {finding.detail}")

    print(f"\n{'=' * 60}")
    print(f"QA Report: {BASE_URL}")
    print(f"{'=' * 60}")
    print(f"Total: {total} | Passed: {passed} | Failed: {failed}")
    for finding in all_findings:
        icon = "PASS" if finding.status == "pass" else "FAIL"
        print(f"  [{icon}] {finding.test_name}: {finding.detail}")
        if finding.console_errors:
            for err in finding.console_errors:
                print(f"        Console: {err}")


if __name__ == "__main__":
    asyncio.run(main())
