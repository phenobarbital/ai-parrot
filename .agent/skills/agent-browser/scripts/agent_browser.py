#!/usr/bin/env python
"""Async Playwright browser-automation CLI for AI-Parrot agents.

This is the AI-Parrot adaptation of the upstream ``agent-browser`` CLI. Instead
of a Node tool it uses **Playwright (async API)** — idiomatic to AI-Parrot's
async-first architecture — and keeps the same daemon model so a browser opened
in one invocation survives across subsequent commands.

How persistence works
----------------------
``daemon start`` launches a long-lived Chromium with a remote-debugging port and
records the CDP endpoint in a small state file
(``~/.agent-browser/<session>/state.json``). Every other subcommand connects to
that endpoint via :meth:`BrowserType.connect_over_cdp`, performs ONE action, and
disconnects — the browser itself stays alive. Element references (``@e1``,
``@e2`` …) produced by ``snapshot`` are persisted in the same state dir as a
ref→CSS-selector map so they remain valid across invocations until the next
snapshot.

Quick start
-----------
    python agent_browser.py daemon start            # launch headless Chromium
    python agent_browser.py open https://example.com
    python agent_browser.py snapshot -i             # interactive elements + refs
    python agent_browser.py click @e1
    python agent_browser.py fill @e2 "hello"
    python agent_browser.py screenshot out.png
    python agent_browser.py daemon stop

Use ``--session NAME`` (before the subcommand) to run isolated parallel browsers.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import fnmatch
import json
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import (
    Browser,
    Page,
    Playwright,
    async_playwright,
)

STATE_ROOT = Path(os.environ.get("AGENT_BROWSER_HOME", Path.home() / ".agent-browser"))


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def _session_dir(session: str) -> Path:
    d = STATE_ROOT / session
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(session: str) -> Path:
    return _session_dir(session) / "state.json"


def _refs_path(session: str) -> Path:
    return _session_dir(session) / "refs.json"


def _routes_path(session: str) -> Path:
    return _session_dir(session) / "routes.json"


def _requests_path(session: str) -> Path:
    return _session_dir(session) / "requests.jsonl"


def _read_routes(session: str) -> list[dict[str, Any]]:
    p = _routes_path(session)
    return json.loads(p.read_text()) if p.exists() else []


def _write_routes(session: str, rules: list[dict[str, Any]]) -> None:
    _routes_path(session).write_text(json.dumps(rules, indent=2))


def _read_state(session: str) -> dict[str, Any]:
    p = _state_path(session)
    if not p.exists():
        raise SystemExit(
            f"No running daemon for session '{session}'. "
            f"Run: agent_browser.py --session {session} daemon start"
        )
    return json.loads(p.read_text())


def _write_state(session: str, data: dict[str, Any]) -> None:
    _state_path(session).write_text(json.dumps(data, indent=2))


def _read_refs(session: str) -> dict[str, str]:
    p = _refs_path(session)
    return json.loads(p.read_text()) if p.exists() else {}


def _write_refs(session: str, refs: dict[str, str]) -> None:
    _refs_path(session).write_text(json.dumps(refs, indent=2))


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- #
# Connection context
# --------------------------------------------------------------------------- #
class Connection:
    """Connects to the running daemon over CDP for a single action."""

    def __init__(self, session: str):
        self.session = session
        self._pw: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> "Connection":
        state = _read_state(self.session)
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.connect_over_cdp(state["ws_endpoint"])
        contexts = self.browser.contexts
        ctx = contexts[0] if contexts else await self.browser.new_context()
        self.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await self._install_network()
        return self

    async def _install_network(self) -> None:
        """Log + route requests for the lifetime of THIS connection.

        Interception is registered on the page held by this command, so any
        request the command triggers (e.g. the ``goto`` in ``open``) is logged
        to ``requests.jsonl`` and matched against the on-disk route rules.
        Multi-client CDP does not propagate routes between connections, so this
        must live in the per-command connection rather than the daemon.
        """
        session = self.session
        requests_file = _requests_path(session)

        async def handler(route: Any) -> None:
            req = route.request
            with contextlib.suppress(OSError):
                with requests_file.open("a") as fh:
                    fh.write(json.dumps({"method": req.method, "url": req.url}) + "\n")
            for rule in _read_routes(session):
                if fnmatch.fnmatch(req.url, rule["url"]):
                    action = rule.get("action", "continue")
                    if action == "abort":
                        await route.abort()
                        return
                    if action == "mock":
                        await route.fulfill(
                            status=int(rule.get("status", 200)),
                            body=rule.get("body", ""),
                            content_type=rule.get("content_type", "application/json"),
                        )
                        return
            await route.continue_()

        await self.page.route("**/*", handler)

    async def __aexit__(self, *exc: Any) -> None:
        # Disconnect WITHOUT closing the daemon's browser.
        if self.browser is not None:
            await self.browser.close()
        if self._pw is not None:
            await self._pw.stop()


# --------------------------------------------------------------------------- #
# Snapshot / ref resolution
# --------------------------------------------------------------------------- #
# JS that walks the DOM, tags every interactive element with a stable
# data-ab-ref attribute, and returns [{ref, role, name, tag}].
_SNAPSHOT_JS = r"""
(interactiveOnly) => {
  const INTERACTIVE = new Set([
    'a','button','input','select','textarea','option','summary','label'
  ]);
  const out = [];
  let i = 0;
  const nodes = document.querySelectorAll('*');
  for (const el of nodes) {
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const clickable = el.hasAttribute('onclick') ||
      role === 'button' || role === 'link' || role === 'menuitem';
    const isInteractive = INTERACTIVE.has(tag) || clickable;
    if (interactiveOnly && !isInteractive) continue;
    // visibility check
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    i += 1;
    const ref = 'e' + i;
    el.setAttribute('data-ab-ref', ref);
    const name = (el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.getAttribute('name') ||
      (el.innerText || '').trim().slice(0, 80) ||
      el.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
    out.push({ref: ref, role: role || tag, name: name, tag: tag});
  }
  return out;
}
"""


def _resolve_selector(token: str, refs: dict[str, str]) -> str:
    """Turn a @ref token or raw CSS selector into a Playwright selector."""
    if token.startswith("@"):
        ref = token[1:]
        if ref not in refs:
            raise SystemExit(
                f"Unknown ref '{token}'. Run 'snapshot -i' to refresh refs."
            )
        return refs[ref]
    return token


# --------------------------------------------------------------------------- #
# Daemon lifecycle
# --------------------------------------------------------------------------- #
async def cmd_daemon_start(args: argparse.Namespace) -> None:
    session = args.session
    # Already running?
    if _state_path(session).exists():
        try:
            _read_state(session)
            print(f"Daemon already running for session '{session}'.")
            return
        except SystemExit:
            pass

    port = args.cdp or _free_port()
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=not args.headed,
        args=[f"--remote-debugging-port={port}"],
    )
    # The CDP ws endpoint we re-connect to.
    ws_endpoint = f"http://127.0.0.1:{port}"
    await browser.new_context()
    _write_state(
        session,
        {"ws_endpoint": ws_endpoint, "cdp_port": port, "pid": os.getpid()},
    )
    _write_refs(session, {})
    _write_routes(session, [])
    # Network log is reset per daemon lifetime; the per-command connection
    # appends to it (see Connection._install_network).
    _requests_path(session).write_text("")
    print(f"Daemon started (session='{session}', cdp={ws_endpoint}, headed={args.headed}).")
    # Keep this process alive so the browser persists.
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await browser.close()
        await pw.stop()
        with contextlib.suppress(FileNotFoundError):
            _state_path(session).unlink()


async def cmd_daemon_stop(args: argparse.Namespace) -> None:
    session = args.session
    try:
        state = _read_state(session)
    except SystemExit:
        print(f"No daemon running for session '{session}'.")
        return
    pid = state.get("pid")
    if pid:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    with contextlib.suppress(FileNotFoundError):
        _state_path(session).unlink()
    print(f"Daemon stopped (session='{session}').")


# --------------------------------------------------------------------------- #
# Page actions
# --------------------------------------------------------------------------- #
async def cmd_open(args: argparse.Namespace) -> None:
    async with Connection(args.session) as c:
        await c.page.goto(args.url, wait_until="domcontentloaded")
        print(f"Opened {c.page.url}")


async def cmd_snapshot(args: argparse.Namespace) -> None:
    async with Connection(args.session) as c:
        elements = await c.page.evaluate(_SNAPSHOT_JS, args.interactive)
        refs = {e["ref"]: f'[data-ab-ref="{e["ref"]}"]' for e in elements}
        _write_refs(args.session, refs)
        if args.json:
            print(json.dumps(elements, indent=2))
        else:
            for e in elements:
                print(f'@{e["ref"]}\t{e["role"]}\t"{e["name"]}"')


async def cmd_click(args: argparse.Namespace) -> None:
    refs = _read_refs(args.session)
    sel = _resolve_selector(args.ref, refs)
    async with Connection(args.session) as c:
        await c.page.click(sel)
        print(f"Clicked {args.ref}")


async def cmd_fill(args: argparse.Namespace) -> None:
    refs = _read_refs(args.session)
    sel = _resolve_selector(args.ref, refs)
    async with Connection(args.session) as c:
        await c.page.fill(sel, args.text)
        print(f"Filled {args.ref}")


async def cmd_type(args: argparse.Namespace) -> None:
    refs = _read_refs(args.session)
    sel = _resolve_selector(args.ref, refs)
    async with Connection(args.session) as c:
        await c.page.type(sel, args.text)
        print(f"Typed into {args.ref}")


async def cmd_press(args: argparse.Namespace) -> None:
    async with Connection(args.session) as c:
        await c.page.keyboard.press(args.key)
        print(f"Pressed {args.key}")


async def cmd_hover(args: argparse.Namespace) -> None:
    refs = _read_refs(args.session)
    sel = _resolve_selector(args.ref, refs)
    async with Connection(args.session) as c:
        await c.page.hover(sel)
        print(f"Hovered {args.ref}")


async def cmd_select(args: argparse.Namespace) -> None:
    refs = _read_refs(args.session)
    sel = _resolve_selector(args.ref, refs)
    async with Connection(args.session) as c:
        chosen = await c.page.select_option(sel, args.values)
        print(f"Selected {chosen} in {args.ref}")


async def cmd_network(args: argparse.Namespace) -> None:
    session = args.session
    if args.action == "route":
        rules = _read_routes(session)
        if args.abort:
            entry: dict[str, Any] = {"url": args.url, "action": "abort"}
        elif args.body is not None:
            entry = {
                "url": args.url,
                "action": "mock",
                "body": args.body,
                "status": args.status,
            }
        else:
            entry = {"url": args.url, "action": "continue"}  # track-only
        rules.append(entry)
        _write_routes(session, rules)
        print(f"Route added: {entry}")
    elif args.action == "unroute":
        if args.url is None:
            _write_routes(session, [])
            print("All routes removed.")
        else:
            rules = [r for r in _read_routes(session) if r["url"] != args.url]
            _write_routes(session, rules)
            print(f"Routes for '{args.url}' removed.")
    elif args.action == "requests":
        p = _requests_path(session)
        if not p.exists():
            print("No requests tracked (is the daemon running?)")
            return
        lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
        if args.filter:
            lines = [ln for ln in lines if args.filter in ln]
        for ln in lines:
            rec = json.loads(ln)
            print(f'{rec["method"]}\t{rec["url"]}')


async def cmd_get(args: argparse.Namespace) -> None:
    refs = _read_refs(args.session)
    async with Connection(args.session) as c:
        page = c.page
        if args.what == "title":
            value: Any = await page.title()
        elif args.what == "url":
            value = page.url
        elif args.what == "count":
            value = await page.locator(args.target).count()
        else:
            sel = _resolve_selector(args.target, refs)
            loc = page.locator(sel).first
            if args.what == "text":
                value = await loc.inner_text()
            elif args.what == "html":
                value = await loc.inner_html()
            elif args.what == "value":
                value = await loc.input_value()
            elif args.what == "attr":
                value = await loc.get_attribute(args.extra)
            else:  # pragma: no cover - argparse restricts choices
                raise SystemExit(f"Unknown get target: {args.what}")
        print(json.dumps(value) if args.json else value)


async def cmd_wait(args: argparse.Namespace) -> None:
    async with Connection(args.session) as c:
        page = c.page
        if args.text:
            await page.get_by_text(args.text).first.wait_for()
        elif args.url:
            await page.wait_for_url(args.url)
        elif args.load:
            await page.wait_for_load_state(args.load)
        elif args.ms is not None:
            await page.wait_for_timeout(args.ms)
        else:
            raise SystemExit("wait needs one of: <ms> | --text | --url | --load")
        print("Wait done")


async def cmd_screenshot(args: argparse.Namespace) -> None:
    async with Connection(args.session) as c:
        await c.page.screenshot(path=args.path, full_page=args.full)
        print(f"Screenshot saved to {args.path}")


async def cmd_eval(args: argparse.Namespace) -> None:
    async with Connection(args.session) as c:
        result = await c.page.evaluate(args.expression)
        print(json.dumps(result) if args.json else result)


async def cmd_state_save(args: argparse.Namespace) -> None:
    async with Connection(args.session) as c:
        ctx = c.page.context
        await ctx.storage_state(path=args.path)
        print(f"Storage state saved to {args.path}")


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent_browser", description=__doc__)
    p.add_argument("--session", default="default", help="Browser session name")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("daemon", help="Manage the persistent browser daemon")
    dsub = d.add_subparsers(dest="action", required=True)
    ds = dsub.add_parser("start")
    ds.add_argument("--headed", action="store_true", help="Show the browser window")
    ds.add_argument("--cdp", type=int, default=None, help="Fixed CDP port")
    ds.set_defaults(func=cmd_daemon_start)
    dsub.add_parser("stop").set_defaults(func=cmd_daemon_stop)

    o = sub.add_parser("open", help="Navigate to URL")
    o.add_argument("url")
    o.set_defaults(func=cmd_open)

    s = sub.add_parser("snapshot", help="List page elements (+refs)")
    s.add_argument("-i", "--interactive", action="store_true", help="Interactive only")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_snapshot)

    c = sub.add_parser("click")
    c.add_argument("ref", help="@ref or CSS selector")
    c.set_defaults(func=cmd_click)

    f = sub.add_parser("fill")
    f.add_argument("ref")
    f.add_argument("text")
    f.set_defaults(func=cmd_fill)

    t = sub.add_parser("type")
    t.add_argument("ref")
    t.add_argument("text")
    t.set_defaults(func=cmd_type)

    pr = sub.add_parser("press")
    pr.add_argument("key", help="e.g. Enter, Control+a")
    pr.set_defaults(func=cmd_press)

    h = sub.add_parser("hover")
    h.add_argument("ref", help="@ref or CSS selector")
    h.set_defaults(func=cmd_hover)

    se = sub.add_parser("select", help="Select <option> value(s) in a <select>")
    se.add_argument("ref")
    se.add_argument("values", nargs="+", help="One or more option values")
    se.set_defaults(func=cmd_select)

    n = sub.add_parser("network", help="Intercept / inspect network traffic")
    nsub = n.add_subparsers(dest="action", required=True)
    nr = nsub.add_parser("route", help="Add a route rule (glob URL)")
    nr.add_argument("url", help="URL glob, e.g. **/api/** or *.png")
    nr.add_argument("--abort", action="store_true", help="Block matching requests")
    nr.add_argument("--body", default=None, help="Mock response body")
    nr.add_argument("--status", type=int, default=200, help="Mock status (with --body)")
    nr.set_defaults(func=cmd_network)
    nu = nsub.add_parser("unroute", help="Remove route rules")
    nu.add_argument("url", nargs="?", default=None, help="Glob to remove (omit = all)")
    nu.set_defaults(func=cmd_network)
    nq = nsub.add_parser("requests", help="List tracked requests")
    nq.add_argument("--filter", default=None, help="Substring filter")
    nq.set_defaults(func=cmd_network)

    g = sub.add_parser("get")
    g.add_argument("what", choices=["text", "html", "value", "attr", "title", "url", "count"])
    g.add_argument("target", nargs="?", default=None, help="@ref / selector (or count selector)")
    g.add_argument("extra", nargs="?", default=None, help="attribute name for 'attr'")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_get)

    w = sub.add_parser("wait")
    w.add_argument("ms", nargs="?", type=int, default=None, help="Milliseconds to wait")
    w.add_argument("--text")
    w.add_argument("--url")
    w.add_argument("--load", choices=["load", "domcontentloaded", "networkidle"])
    w.set_defaults(func=cmd_wait)

    sc = sub.add_parser("screenshot")
    sc.add_argument("path")
    sc.add_argument("--full", action="store_true")
    sc.set_defaults(func=cmd_screenshot)

    e = sub.add_parser("eval")
    e.add_argument("expression")
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_eval)

    st = sub.add_parser("state")
    stsub = st.add_subparsers(dest="action", required=True)
    sts = stsub.add_parser("save")
    sts.add_argument("path")
    sts.set_defaults(func=cmd_state_save)

    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
