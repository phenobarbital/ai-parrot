"""Integration test for the agent-browser driver.

Drives the real CLI as a subprocess (the way an agent uses it) against a
throwaway local HTTP server and a headless Chromium. Skipped automatically
when Playwright/Chromium is not available, so it is safe in any environment.

Run just this file with::

    pytest .agent/skills/agent-browser/tests/test_agent_browser_integration.py -v
"""
import functools
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright")

DRIVER = Path(__file__).resolve().parent.parent / "scripts" / "agent_browser.py"

PAGE_HTML = """<!doctype html><title>Driver Test</title>
<input id="in" placeholder="Email">
<select id="sel"><option value="a">A</option><option value="b">B</option></select>
<div id="hov">hover me</div>
<script src="app.js"></script>
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def chromium_available():
    """Skip the whole module if Chromium cannot launch."""
    check = (
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    b = p.chromium.launch(); b.close()\n"
    )
    r = subprocess.run([sys.executable, "-c", check], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"Chromium not launchable: {r.stderr.strip()[-200:]}")


@pytest.fixture
def web(tmp_path):
    """A local HTTP server serving a page with an input, select, and script."""
    root = tmp_path / "www"
    root.mkdir()
    (root / "index.html").write_text(PAGE_HTML)
    (root / "app.js").write_text("window.__loaded = true;")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    srv = ThreadingHTTPServer(("127.0.0.1", _free_port()), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()


@pytest.fixture
def env(tmp_path):
    e = dict(os.environ)
    e["AGENT_BROWSER_HOME"] = str(tmp_path / "ab-home")
    return e


@pytest.fixture
def daemon(env, chromium_available):
    """Start the persistent browser daemon; tear it down afterwards."""
    proc = subprocess.Popen(
        [sys.executable, str(DRIVER), "daemon", "start"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    state = Path(env["AGENT_BROWSER_HOME"]) / "default" / "state.json"
    for _ in range(50):
        if state.exists():
            break
        time.sleep(0.2)
    else:
        proc.terminate()
        out = proc.stdout.read() if proc.stdout else ""
        pytest.fail(f"daemon did not start. Output:\n{out}")
    try:
        yield env
    finally:
        subprocess.run(
            [sys.executable, str(DRIVER), "daemon", "stop"],
            env=env,
            capture_output=True,
        )
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def run(env, *args, check=True):
    """Invoke the driver CLI and return stripped stdout."""
    r = subprocess.run(
        [sys.executable, str(DRIVER), *args],
        env=env,
        capture_output=True,
        text=True,
    )
    if check:
        assert r.returncode == 0, f"{args} failed:\n{r.stderr or r.stdout}"
    return r.stdout.strip()


def _poll_eval(env, expr, tries=25):
    """Eval until a non-null JSON value appears (for async page side effects)."""
    val = "null"
    for _ in range(tries):
        val = run(env, "eval", expr, "--json")
        if val != "null":
            return val
        time.sleep(0.2)
    return val


@pytest.mark.integration
def test_navigate_snapshot_and_interact(daemon, web):
    env = daemon
    run(env, "open", f"{web}/index.html")
    assert run(env, "get", "title") == "Driver Test"

    snap = run(env, "snapshot", "-i")
    assert "@e" in snap  # at least one interactive ref surfaced

    # fill + read back via CSS selector
    run(env, "fill", "#in", "user@test.com")
    assert run(env, "get", "value", "#in") == "user@test.com"

    # select an <option>
    run(env, "select", "#sel", "b")
    assert run(env, "eval", "document.getElementById('sel').value", "--json") == '"b"'

    # hover should not raise
    run(env, "hover", "#hov")


@pytest.mark.integration
def test_snapshot_refs_resolve_across_invocations(daemon, web):
    env = daemon
    run(env, "open", f"{web}/index.html")
    snap = run(env, "snapshot", "-i", "--json")
    elements = json.loads(snap)
    assert elements, "snapshot returned no elements"
    first = elements[0]["ref"]
    # A ref produced by one process is usable by the next (cached on disk).
    out = run(env, "get", "value", f"@{first}", check=False)
    # @ref must resolve (no "Unknown ref" error)
    assert "Unknown ref" not in out


@pytest.mark.integration
def test_network_logging_and_routing(daemon, web):
    env = daemon
    run(env, "open", f"{web}/index.html")

    # Every request during the load was logged.
    reqs = run(env, "network", "requests")
    assert "index.html" in reqs and "app.js" in reqs
    assert run(env, "network", "requests", "--filter", "app.js")  # non-empty

    # Block app.js, reload → the script no longer executes.
    run(env, "network", "route", "**/app.js", "--abort")
    run(env, "open", f"{web}/index.html")
    assert run(env, "eval", "window.__loaded === true", "--json") == "false"

    # Mock a JSON endpoint that does not exist on the server.
    run(env, "network", "unroute")
    run(env, "network", "route", "**/mock.json", "--body", '{"ok":true}', "--status", "200")
    run(
        env,
        "eval",
        f"fetch('{web}/mock.json').then(r=>r.json()).then(j=>{{window.__m=JSON.stringify(j)}})",
    )
    got = _poll_eval(env, "window.__m")
    assert json.loads(got) == '{"ok":true}'


@pytest.mark.integration
def test_screenshot_written(daemon, web, tmp_path):
    env = daemon
    run(env, "open", f"{web}/index.html")
    out_png = tmp_path / "shot.png"
    run(env, "screenshot", str(out_png))
    assert out_png.exists() and out_png.stat().st_size > 0
