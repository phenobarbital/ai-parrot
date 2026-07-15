---
type: Concept
title: create_netsuite_m2m_mcp_server()
id: func:parrot.mcp.integration.create_netsuite_m2m_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create a NetSuite MCP server using OAuth2 Client Credentials (M2M) with certificate.
---

# create_netsuite_m2m_mcp_server

```python
def create_netsuite_m2m_mcp_server(*, account_id: str, client_id: str, certificate_id: str, private_key_path: str, name: str='netsuite', token_store: Optional[TokenStore]=None, headers: Optional[Dict[str, Any]]=None) -> MCPServerConfig
```

Create a NetSuite MCP server using OAuth2 Client Credentials (M2M) with certificate.

This is the machine-to-machine variant — no browser login required.
Authentication uses a JWT ``client_assertion`` signed with the private key
whose matching X.509 certificate was uploaded to the NetSuite Integration Record.

Args:
    account_id: NetSuite account ID (e.g. ``"4984231"``).
    client_id: OAuth2 client ID from the NetSuite integration record.
    certificate_id: Certificate ID shown in NetSuite after uploading the
        public certificate (Mapping Key field).
    private_key_path: Path to a PEM-encoded RSA private key file.
    name: Server name (default ``"netsuite"``).
    token_store: Optional :class:`~parrot.mcp.oauth.TokenStore`.
    headers: Extra HTTP headers.

Returns:
    :class:`MCPServerConfig` configured for NetSuite M2M.

Example:
    >>> cfg = create_netsuite_m2m_mcp_server(
    ...     account_id="4984231",
    ...     client_id="abc...",
    ...     certificate_id="XYZ123",
    ...     private_key_path="/path/to/private.pem",
    ... )
