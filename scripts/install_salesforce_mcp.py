#!/usr/bin/env python3
"""Install the Salesforce MCP Server (mcp-salesforce-connector).

Usage:
    python scripts/install_salesforce_mcp.py [--method uv|pip]

Requires: uv (preferred) or pip.
"""
import argparse
import subprocess
import sys


PACKAGE_NAME = "mcp-salesforce-connector"


def run(cmd: list[str]) -> int:
    """Run a command, streaming output to the terminal."""
    print(f"  -> {' '.join(cmd)}")
    return subprocess.call(cmd)


def install_with_uv() -> int:
    """Install using uv pip (preferred)."""
    return run(["uv", "pip", "install", PACKAGE_NAME])


def install_with_pip() -> int:
    """Install using pip."""
    return run([sys.executable, "-m", "pip", "install", PACKAGE_NAME])


def verify_installation() -> bool:
    """Check that the package is importable after install."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import importlib; importlib.import_module('salesforce')"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"\n[OK] {PACKAGE_NAME} installed successfully.")
            return True
    except Exception:
        pass

    # Fallback: check via pip list
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", PACKAGE_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"\n[OK] {PACKAGE_NAME} installed successfully.")
        for line in result.stdout.splitlines():
            if line.startswith(("Name:", "Version:", "Location:")):
                print(f"  {line}")
        return True

    print(f"\n[ERROR] {PACKAGE_NAME} does not appear to be installed.")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the Salesforce MCP Server")
    parser.add_argument(
        "--method",
        choices=["uv", "pip"],
        default="uv",
        help="Installation method (default: uv)",
    )
    args = parser.parse_args()

    print(f"Installing {PACKAGE_NAME} via {args.method}...\n")

    if args.method == "uv":
        rc = install_with_uv()
    else:
        rc = install_with_pip()

    if rc != 0:
        print(f"\n[ERROR] Installation failed (exit code {rc}).")
        sys.exit(rc)

    verify_installation()


if __name__ == "__main__":
    main()
