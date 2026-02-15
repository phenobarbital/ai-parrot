#!/usr/bin/env python3
import secrets
client_id = secrets.token_urlsafe(16)
client_secret = secrets.token_urlsafe(32)
print("oauth_static_clients:")
print(f"  - client_name: 'mcp-client'")
print(f"    client_id: '{client_id}'")
print(f"    client_secret: '{client_secret}'")
print(f"    redirect_uris: ['http://localhost:8765/mcp/oauth/callback']")
print(f"    scopes: ['mcp:access']")
