---
id: F026
query_id: Q024
type: glob
intent: Is there a repo convention for client.py (python opener/static server) vs pure static HTML client?
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F026 — No "client.py" convention; browser clients are static HTML served by the server itself
## Summary
No `examples/**/client.py` exists; the only Python "clients" are protocol clients (`examples/a2a_examples/a2a_client.py`, `examples/mcp_websocket_client.py`, `examples/agents/test_mcp_client.py`). Browser clients are always static HTML/JS served by the example's own aiohttp server (`examples/clients/voice/static/`, `examples/dev_loop/static/`) or loose HTML files (`examples/stream_client.html`, `examples/user_websocket_client.html`). The "python script that opens a browser" idiom exists only as the `--open` flag of the A2UI walkthroughs (stdlib http.server + webbrowser, F024).
## Citations
- path: `examples/a2a_examples/a2a_client.py`
  lines: -
  symbol: `-`
  excerpt: |
    (file exists; protocol client, not a browser client)
- path: `examples/agents/a2ui/deterministic_refresh_dashboard.py`
  lines: 726-738
  symbol: `_serve_and_open`
  excerpt: |
    def _serve_and_open(directory: Path, port: int = 8091) -> None:
        httpd = socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler)
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
## Implications
- Serving the HTML client from server.py (same origin) avoids CORS for /api/v1/login, QuerySource and surface fetches; a separate client.py static server on another port would need CORS config on the auth'd API.
- If client.py is kept, the least surprising shape is a thin launcher (`webbrowser.open(server_url)`) or a headless Python smoke client (login → fetch surface → call QS) rather than a second static server.
