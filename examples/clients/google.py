"""Example usage for the GoogleClient interface.

Before running this script, ensure one of the following is available:

* A Google service-account JSON file located next to the script (named
  ``service-account.json`` by default) for server-to-server access.
* An OAuth client configuration JSON available at the path pointed to by the
  ``GOOGLE_CREDENTIALS_FILE`` setting or passed directly to ``GoogleClient``.

The example demonstrates both flows and persists user credentials in the
default cache location so subsequent runs reuse the previously granted tokens.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from parrot.interfaces.google import GoogleClient


async def run_example() -> None:
    """Demonstrate service-account and user OAuth2 flows."""
    logging.basicConfig(level=logging.INFO)

    # Update this path to point at a service-account JSON file if desired
    service_account_path = Path("service-account.json")

    if service_account_path.exists():
        client = GoogleClient(credentials=service_account_path, scopes=["drive"])
        async with client:
            files = await client.execute_api_call(
                "drive",
                "files",
                "list",
                pageSize=5,
                fields="files(id, name)",
            )
        print("Service account mode results:")
        for file_info in files.get("files", []):
            print(f" - {file_info['name']} ({file_info['id']})")

    print("\nStarting user OAuth2 login flow...")
    user_client = GoogleClient(credentials="user", scopes=["drive"])

    if not user_client.load_cached_user_credentials():
        await user_client.interactive_login(open_browser=False)

    async with user_client:
        files = await user_client.execute_api_call(
            "drive",
            "files",
            "list",
            pageSize=5,
            fields="files(id, name)",
        )

    print("User OAuth mode results:")
    for file_info in files.get("files", []):
        print(f" - {file_info['name']} ({file_info['id']})")


if __name__ == "__main__":
    asyncio.run(run_example())
