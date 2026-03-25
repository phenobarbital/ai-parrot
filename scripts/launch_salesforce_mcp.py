#!/usr/bin/env python3
"""Launch the Salesforce MCP Server.

The server runs as a stdio-based MCP server. It requires Salesforce
credentials via environment variables or a .env file.

Authentication methods (choose one):
  1. OAuth token:    SALESFORCE_ACCESS_TOKEN + SALESFORCE_INSTANCE_URL
  2. Salesforce CLI: auto-detects default org (set SALESFORCE_CLI_TARGET_ORG for a specific one)
  3. Username/password: SALESFORCE_USERNAME + SALESFORCE_PASSWORD + SALESFORCE_SECURITY_TOKEN

Optional:
  SALESFORCE_DOMAIN  -- set to "test" for sandbox environments (default: production)

Usage:
    python scripts/launch_salesforce_mcp.py
    python scripts/launch_salesforce_mcp.py --env-file .env.salesforce
    python scripts/launch_salesforce_mcp.py --method uvx
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def load_env_file(env_file: str) -> None:
    """Load environment variables from a dotenv-style file."""
    path = Path(env_file)
    if not path.exists():
        print(f"[WARN] Env file not found: {env_file}")
        return
    print(f"Loading environment from {env_file}")
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ[key] = value


def check_credentials() -> str:
    """Check which authentication method is configured and return its name."""
    if os.environ.get("SALESFORCE_ACCESS_TOKEN") and os.environ.get("SALESFORCE_INSTANCE_URL"):
        return "oauth_token"
    if os.environ.get("SALESFORCE_USERNAME") and os.environ.get("SALESFORCE_PASSWORD"):
        return "username_password"
    # Salesforce CLI method doesn't require env vars
    return "salesforce_cli"


def launch_uvx() -> int:
    """Launch via uvx (recommended)."""
    return subprocess.call(["uvx", "--from", "mcp-salesforce-connector", "salesforce"])


def launch_python() -> int:
    """Launch via the installed Python package directly."""
    return subprocess.call([sys.executable, "-m", "salesforce"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the Salesforce MCP Server")
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to .env file with Salesforce credentials",
    )
    parser.add_argument(
        "--method",
        choices=["uvx", "python"],
        default="python",
        help="Launch method: uvx (isolated) or python (current venv, default)",
    )
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    auth_method = check_credentials()
    print(f"Auth method detected: {auth_method}")

    if auth_method == "salesforce_cli":
        print(
            "[INFO] No explicit credentials found. "
            "Will attempt Salesforce CLI authentication (default org)."
        )

    print(f"Starting Salesforce MCP Server (method={args.method})...\n")

    if args.method == "uvx":
        rc = launch_uvx()
    else:
        rc = launch_python()

    sys.exit(rc)


if __name__ == "__main__":
    main()
