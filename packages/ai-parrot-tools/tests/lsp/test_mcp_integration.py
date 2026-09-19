"""Raw local MCP protocol integration for the LSP toolkit (FEAT-580, TASK-3508).

Drives ``parrot mcp-local lsp`` as a real subprocess over its raw
stdin/stdout JSON-RPC transport — never the in-process ``LSPToolkit`` API
directly — configured with the deterministic, scripted ``fake_server.py``
fixture as the LSP backend (never a live Pyright). Asserts pure-JSON stdout
(no stray prints corrupting the protocol channel) and that the fake-server
child process the toolkit spawns is fully reaped after a clean stdin EOF,
never left orphaned.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Two source roots: the core `parrot` CLI/MCP machinery, and `parrot_tools`
# for `parrot_tools.lsp.toolkit.LSPToolkit` — the spawned subprocess needs
# both on its sys.path since this test lives in the ai-parrot-tools package.
_CORE_SRC = Path(__file__).resolve().parents[4] / "ai-parrot" / "src"
_TOOLS_SRC = Path(__file__).resolve().parents[2] / "src"
FAKE_SERVER = Path(__file__).parent / "fake_server.py"

_BOOTSTRAP = textwrap.dedent(f"""
    import sys, types
    sys.path.insert(0, {str(_TOOLS_SRC)!r})
    sys.path.insert(0, {str(_CORE_SRC)!r})

    try:
        import parrot.utils.types  # noqa: F401 -- prefer the real compiled extension
    except ImportError:
        _m = types.ModuleType("parrot.utils.types")
        class SafeDict(dict):
            def __missing__(self, key):
                return None
        _m.SafeDict = SafeDict
        sys.modules["parrot.utils.types"] = _m

    try:
        import parrot.utils.parsers.toml  # noqa: F401
    except ImportError:
        _pkg = types.ModuleType("parrot.utils.parsers")
        _mod = types.ModuleType("parrot.utils.parsers.toml")
        class TOMLParser:
            def __init__(self, *a, **kw):
                pass
            def parse(self, content):
                import tomllib
                return tomllib.loads(content)
        _mod.TOMLParser = TOMLParser
        _pkg.TOMLParser = TOMLParser
        sys.modules["parrot.utils.parsers"] = _pkg
        sys.modules["parrot.utils.parsers.toml"] = _mod

    from parrot.cli import cli
    cli(prog_name="parrot")
    """)

_EXPECTED_TOOL_NAMES = {"lsp_definition", "lsp_references", "lsp_diagnostics", "lsp_diagnostic_delta"}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _spawn(cwd: Path, *args: str) -> subprocess.Popen:
    """Start `parrot <args>` as a real subprocess rooted at `cwd`."""
    return subprocess.Popen(
        [sys.executable, "-c", _BOOTSTRAP, *args],
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _recv(proc: subprocess.Popen) -> dict:
    """Read one line from stdout and parse it as JSON-RPC -- never anything else."""
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read()
        raise AssertionError(f"subprocess produced no output (exit={proc.poll()}); stderr:\n{stderr}")
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"non-JSON-RPC line polluted stdout: {line!r}") from exc


def _shutdown(proc: subprocess.Popen, timeout: float = 10.0) -> None:
    """Close stdin (clean EOF shutdown) and reap the process."""
    try:
        proc.stdin.close()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _write_lsp_config(root: Path, *, scenario: str = "happy_path", environment_id: str = "test-env") -> None:
    """Declare an `lsp:` section pointed at the scripted fake server, never a live Pyright."""
    server_command = [sys.executable, str(FAKE_SERVER), scenario]
    version_command = [sys.executable, "-c", "print('pyright 1.1.414')"]
    parrot_dir = root / ".parrot"
    parrot_dir.mkdir(exist_ok=True)
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  lsp:\n"
        "    class: parrot_tools.lsp.toolkit.LSPToolkit\n"
        "    kwargs:\n"
        "      config:\n"
        f"        repo_root: {json.dumps(str(root))}\n"
        f"        environment_id: {json.dumps(environment_id)}\n"
        f"        server_command: {json.dumps(server_command)}\n"
        f"        version_command: {json.dumps(version_command)}\n",
        encoding="utf-8",
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A small, real Git worktree with one tracked Python file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "mod.py").write_text("def foo():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _write_lsp_config(repo)
    return repo


def _pid_exists(pid: int) -> bool:
    """True if ``pid`` is still a live process, stdlib-only (no ``psutil``)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    return True


def _child_pids(pid: int) -> list[int]:
    """Direct children of ``pid``, via Linux's ``/proc/<pid>/task/<pid>/children``."""
    try:
        text = Path(f"/proc/{pid}/task/{pid}/children").read_text(encoding="utf-8")
    except OSError:
        return []
    return [int(token) for token in text.split()]


def _all_gone(pids: list[int]) -> bool:
    return not any(_pid_exists(pid) for pid in pids)


# ---------------------------------------------------------------------------
# test_fake_server_stdio_end_to_end
# ---------------------------------------------------------------------------


def test_fake_server_stdio_end_to_end(git_repo: Path) -> None:
    """initialize -> tools/list -> tools/call -> EOF, all over raw JSON-RPC stdio.

    Every response the server writes must be a clean JSON-RPC line (no stray
    prints from any dependency corrupting the stdout channel, matching the
    stdout-purity guarantee `create_toolkit_mcp_server` documents), tool
    listing must expose exactly the four documented LSP tools, and a real
    tool call must round-trip through the actual raw MCP transport -> the
    real `LSPToolkit` -> a real (fake-server-backed) `PyrightSession`
    without ever crashing the server process.
    """
    proc = _spawn(git_repo, "mcp-local", "lsp")
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        init_resp = _recv(proc)
        assert init_resp["id"] == 1
        assert "error" not in init_resp

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        list_resp = _recv(proc)
        tool_names = {tool["name"] for tool in list_resp["result"]["tools"]}
        assert tool_names == _EXPECTED_TOOL_NAMES

        mod_text = (git_repo / "pkg" / "mod.py").read_text()
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "lsp_definition",
                    "arguments": {
                        "path": "pkg/mod.py",
                        "line": 1,
                        "column": 1,
                        "expected_sha256": _sha256(mod_text),
                    },
                },
            },
        )
        call_resp = _recv(proc)
        assert call_resp["id"] == 3
        assert "error" not in call_resp
        # The fake server's happy-path echo loop is not a real LSP shape, so
        # the toolkit resolves zero locations -- what matters here is that
        # the real MCP transport -> LSPToolkit -> PyrightSession round trip
        # completed without corrupting the protocol or crashing the server.
        assert call_resp["result"]["isError"] is False

        child_pids = _child_pids(proc.pid)
        assert child_pids, "expected the fake_server.py backend to be a real child process by now"
    finally:
        _shutdown(proc)

    assert proc.returncode == 0, proc.stderr.read()
    assert _all_gone(child_pids), "fake_server.py backend was not reaped after EOF shutdown"


# ---------------------------------------------------------------------------
# test_mcp_eof_reaps_child
# ---------------------------------------------------------------------------


def test_mcp_eof_reaps_child(git_repo: Path) -> None:
    """A clean stdin EOF always reaps the owned LSP backend child -- explicit focus test."""
    proc = _spawn(git_repo, "mcp-local", "lsp")
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _recv(proc)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        mod_text = (git_repo / "pkg" / "mod.py").read_text()
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "lsp_definition",
                    "arguments": {
                        "path": "pkg/mod.py",
                        "line": 1,
                        "column": 1,
                        "expected_sha256": _sha256(mod_text),
                    },
                },
            },
        )
        _recv(proc)

        child_pids = _child_pids(proc.pid)
        assert child_pids
        assert all(_pid_exists(pid) for pid in child_pids)
    finally:
        _shutdown(proc)

    assert proc.returncode == 0, proc.stderr.read()
    assert _all_gone(child_pids)
