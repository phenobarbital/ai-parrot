---
id: F024
query_id: Q021
type: tree
intent: Survey examples/ for aiohttp servers serving static HTML/JS, auth, or A2UI
executed_at: 2026-09-28T18:23:00Z
parent_id: null
depth: 0
---
# F024 — Example servers with static clients: voice, dev_loop, forms; A2UI examples are file-serving only
## Summary
Tracked aiohttp servers with a `static/` dir: `examples/clients/voice/server.py` (`add_static("/static/", STATIC_DIR)`, `web.run_app(..., host=args.host, port=args.port)`) and `examples/dev_loop/server.py` (`FileResponse(STATIC_DIR/"index.html")` for `/`, `add_static`). Auth-enabled examples: forms/form_server.py (tracked), autonomous/quickstart.py and advisors/voice.py (untracked). The existing A2UI examples (`examples/agents/a2ui/*.py`, tracked + whitelisted) render HTML to `artifacts/a2ui_dashboard/` and use stdlib `http.server` + `webbrowser.open` under an `--open` flag — no aiohttp server, no auth, no QuerySource.
## Citations
- path: `examples/clients/voice/server.py`
  lines: 820,882
  symbol: `-`
  excerpt: |
    app.router.add_static("/static/", path=STATIC_DIR, name="static")
    web.run_app(app, host=args.host, port=args.port, print=None)
- path: `examples/dev_loop/server.py`
  lines: 1231-1232,1808
  symbol: `handle_index`
  excerpt: |
    async def handle_index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")
    app.router.add_static("/static/", STATIC_DIR, show_index=False)
- path: `examples/agents/a2ui/a2ui_dashboard_walkthrough.py`
  lines: 753-759,842-846
  symbol: `-`
  excerpt: |
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    opener = threading.Timer(0.5, lambda: webbrowser.open(url))
    parser.add_argument("--port", type=int, default=8080, help="port for --open (default: 8080).")
- path: `examples/agents/a2ui/README.md`
  lines: 1-20
  symbol: `-`
  excerpt: |
    python examples/agents/a2ui/a2ui_dashboard_walkthrough.py --open    # + serve and open it
    python examples/agents/a2ui/a2ui_dashboard_walkthrough.py --live    # let the LLM drive
## Implications
- Follow the voice/dev_loop pattern: `STATIC_DIR = Path(__file__).parent / "static"`, `/` → FileResponse(index.html), `add_static("/static/", ...)` (default-excluded from auth), argparse `--host/--port`, `web.run_app`.
- Consider placing the new example under `examples/agents/a2ui/` (already whitelisted, sits next to the related walkthroughs) instead of `examples/a2ui/` — see F025.
