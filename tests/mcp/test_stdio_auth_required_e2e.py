"""E2E: ``parrot mcp-local`` returns an auth-required envelope over pure JSON-RPC (AC-8)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

from parrot.cli.login import LoginRecord, LoginStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_SRC = _REPO_ROOT / "packages" / "ai-parrot" / "src"

_BOOTSTRAP = textwrap.dedent(f"""
    import sys, types
    sys.path.insert(0, {str(_CORE_SRC)!r})

    try:
        import parrot.utils.types
    except ImportError:
        _types = types.ModuleType("parrot.utils.types")
        class SafeDict(dict):
            def __missing__(self, key):
                return None
        _types.SafeDict = SafeDict
        sys.modules["parrot.utils.types"] = _types

    try:
        import parrot.utils.parsers.toml
    except ImportError:
        _parsers = types.ModuleType("parrot.utils.parsers")
        _toml = types.ModuleType("parrot.utils.parsers.toml")
        class TOMLParser:
            def __init__(self, *args, **kwargs):
                pass
            def parse(self, content):
                import tomllib
                return tomllib.loads(content)
        _toml.TOMLParser = TOMLParser
        _parsers.TOMLParser = TOMLParser
        sys.modules["parrot.utils.parsers"] = _parsers
        sys.modules["parrot.utils.parsers.toml"] = _toml

    from parrot.cli import cli
    cli(prog_name="parrot")
    """)

_FAKE_SERVER = textwrap.dedent("""
    import asyncio
    import sys
    from aiohttp import web

    async def me(request):
        return web.json_response({
            "user_id": "navigator-user",
            "email": "user@example.test",
            "tenant_id": "tenant-test",
            "roles": [],
            "scopes": [],
        })

    async def token(request):
        return web.json_response({
            "provider": "fake",
            "auth_url": "https://provider.example/connect",
            "message": "connection required",
            "auth_kind": "oauth2",
        }, status=409)

    async def start(request):
        return web.json_response({
            "state": "opaque-state",
            "auth_url": "https://provider.example/connect",
            "expires_in": 600,
        })

    async def main():
        app = web.Application()
        app.router.add_get("/api/v1/connections/me", me)
        app.router.add_post("/api/v1/connections/{provider}/token", token)
        app.router.add_post("/api/v1/connections/{provider}/start", start)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        sys.stdout.write(f"{port}\\n")
        sys.stdout.flush()
        await asyncio.Event().wait()

    asyncio.run(main())
    """)


def _write_fixture_files(root: Path, server_url: str) -> Path:
    """Write the private login, toolkit module, and local toolkit config."""
    login_file = root / ".parrot" / "login.json"
    LoginStore(login_file).save(
        LoginRecord(
            server_url=server_url,
            access_token="navigator-access-token",
            refresh_token="navigator-refresh-token",
            expires_at=time.time() + 3600,
            user_id="navigator-user",
            cache_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
            issued_at=time.time(),
        )
    )
    (root / "stub_toolkit.py").write_text(
        textwrap.dedent("""
            from parrot.tools.toolkit import AbstractToolkit

            class CredentialToolkit(AbstractToolkit):
                \"\"\"Toolkit with one credential-gated operation.\"\"\"

                credential_provider = \"fake\"

                async def fetch(self) -> str:
                    \"\"\"Return a value after provider authorization.\"\"\"
                    return \"secret result\"
            """),
        encoding="utf-8",
    )
    (root / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  fake:\n    class: stub_toolkit.CredentialToolkit\n    kwargs: {}\n",
        encoding="utf-8",
    )
    return login_file


def _send(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    """Write one JSON-RPC frame to the MCP subprocess."""
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()


def _receive(process: subprocess.Popen[str], stdout_lines: list[str]) -> dict[str, Any]:
    """Read, record, and parse one JSON-RPC frame from stdout."""
    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise AssertionError(f"mcp-local produced no response (exit={process.poll()}): {stderr}")
    stdout_lines.append(line)
    return json.loads(line)


def _stop(process: subprocess.Popen[str]) -> None:
    """Close stdin and reap a subprocess, killing it only after the timeout."""
    if process.stdin is not None:
        process.stdin.close()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_e2e_stdio_toolkit_auth_required(tmp_path: Path) -> None:
    """A logged-in stdio toolkit without a connection returns the standard envelope."""
    fake_server = subprocess.Popen(
        [sys.executable, "-c", _FAKE_SERVER],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    process: subprocess.Popen[str] | None = None
    stdout_lines: list[str] = []
    try:
        assert fake_server.stdout is not None
        port_line = fake_server.stdout.readline()
        if not port_line:
            stderr = fake_server.stderr.read() if fake_server.stderr is not None else ""
            raise AssertionError(f"fake server failed to start: {stderr}")
        login_file = _write_fixture_files(tmp_path, f"http://127.0.0.1:{int(port_line)}")
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(tmp_path),
                "PARROT_LOGIN_FILE": str(login_file),
                "PYTHONPATH": os.pathsep.join([str(tmp_path), str(_CORE_SRC), environment.get("PYTHONPATH", "")]),
            }
        )
        process = subprocess.Popen(
            [sys.executable, "-c", _BOOTSTRAP, "mcp-local", "fake"],
            cwd=str(tmp_path),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        _send(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        initialized = _receive(process, stdout_lines)
        assert initialized["result"]["serverInfo"]["name"] == "parrot-fake"

        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "fetch", "arguments": {}},
            },
        )
        response = _receive(process, stdout_lines)
        result = response["result"]
        assert result["isError"] is True
        assert result["structuredContent"]["provider"] == "fake"
        assert "parrot connect fake" in result["content"][0]["text"]
    finally:
        if process is not None:
            _stop(process)
            if process.stdout is not None:
                stdout_lines.extend(process.stdout.readlines())
        fake_server.terminate()
        try:
            fake_server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            fake_server.kill()
            fake_server.wait(timeout=5)

    assert process is not None
    assert process.returncode == 0
    assert stdout_lines
    for line in stdout_lines:
        frame = json.loads(line)
        assert frame["jsonrpc"] == "2.0"
