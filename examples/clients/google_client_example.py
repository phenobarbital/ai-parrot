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
    service_account_path = Path("env/google/google-service.json")

    if service_account_path.exists():
        client = GoogleClient(
            credentials=service_account_path,
            scopes=["drive"],
            redis_url="redis://localhost:6379/2",
            user_creds_cache_file="~/.config/parrot/google/user_creds.json",
        )

        await client.interactive_login(open_browser=True, port=5050)

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

if __name__ == "__main__":
    asyncio.run(run_example())
