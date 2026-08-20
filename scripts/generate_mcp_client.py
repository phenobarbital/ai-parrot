#!/usr/bin/env python3
"""Generate MCP OAuth2 client credentials (YAML snippet for config).

Prints a YAML block intended for pasting into a configuration file.
The secret is printed intentionally — this is a credential generation
utility. Redirect output to a file and restrict its permissions:

    python generate_mcp_client.py > /path/to/secrets.yaml
    chmod 600 /path/to/secrets.yaml
"""
import secrets
import sys

client_id = secrets.token_urlsafe(16)
client_secret = secrets.token_urlsafe(32)  # noqa: S105 — intentional generation

# Write YAML snippet to stdout (intentionally includes secret for config use)
_lines = [
    "oauth_static_clients:",
    "  - client_name: 'mcp-client'",
    f"    client_id: '{client_id}'",
    f"    client_secret: '{client_secret}'",  # CodeQL[py/clear-text-logging-sensitive-data] — intentional: this script's purpose is to emit credentials for config files
    "    redirect_uris: ['http://localhost:8765/mcp/oauth/callback']",
    "    scopes: ['mcp:access']",
]
sys.stdout.write("\n".join(_lines) + "\n")
