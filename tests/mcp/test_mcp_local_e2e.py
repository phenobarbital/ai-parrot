"""End-to-end integration tests for `parrot mcp-local` (FEAT-485 TASK-2650).

Spawns the CLI as a REAL subprocess and drives it over line-delimited
JSON-RPC on stdin/stdout — the same transport a real MCP host (Claude
Code, Codex) uses. No mocking of the server, the toolkit, or the
transport: this is the closing proof that the whole path (CLI ->
toolkit_server factory -> StdioMCPServer -> MCPToolAdapter -> tool)
works together.

The subprocess is spawned via ``sys.executable -c <bootstrap>`` rather
than the installed ``parrot`` console script so these tests exercise
whatever ai-parrot checkout they run against (this repo clone or a
worktree) rather than a possibly-stale editable install elsewhere on
``$PATH``. The bootstrap:

1. Prepends this checkout's ``packages/ai-parrot/src`` to ``sys.path``.
2. Falls back to lightweight pure-Python stand-ins for
   ``parrot.utils.types``/``parrot.utils.parsers.toml`` ONLY if the real
   compiled Cython extensions are not importable (e.g. a git worktree
   that never ran a build step) — mirrors the repo's own root
   ``conftest.py``. When the real extensions ARE importable (normal
   checkout, CI), they are used unmodified.
3. Runs ``parrot.cli.cli()`` with the real CLI argv.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_SRC = _REPO_ROOT / "packages" / "ai-parrot" / "src"

_BOOTSTRAP = textwrap.dedent(f"""
    import sys, types
    sys.path.insert(0, {str(_CORE_SRC)!r})

    try:
        import parrot.utils.types  # noqa: F401 — prefer the real compiled extension
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


def _spawn(cwd: Path, *args: str) -> subprocess.Popen:
    """Start `parrot <args>` as a subprocess rooted at ``cwd``."""
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


def _recv(proc: subprocess.Popen, timeout: float = 10.0) -> dict:
    """Read one line from stdout and parse it as JSON-RPC.

    Fails loudly (rather than hanging forever) if the process exits
    without producing a line, or produces a non-JSON line — either is a
    stdout-purity violation or a crashed server.
    """
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read()
        raise AssertionError(f"subprocess produced no output (exit={proc.poll()}); stderr:\n{stderr}")
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"non-JSON-RPC line on stdout: {line!r}") from exc


def _shutdown(proc: subprocess.Popen) -> None:
    """Close stdin (clean EOF shutdown) and reap the process."""
    try:
        proc.stdin.close()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_mcp_local_memory_e2e(tmp_path):
    """initialize -> tools/list -> store_result -> get_result round-trip."""
    proc = _spawn(tmp_path, "mcp-local", "memory")
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        init_resp = _recv(proc)
        assert init_resp["id"] == 1
        assert init_resp["result"]["serverInfo"]["name"] == "parrot-memory"

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        list_resp = _recv(proc)
        names = {t["name"] for t in list_resp["result"]["tools"]}
        assert {"wm_store_result", "wm_get_result", "wm_list_stored"} <= names

        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "wm_store_result", "arguments": {"key": "greeting", "data": "hello"}},
            },
        )
        store_resp = _recv(proc)
        assert store_resp["id"] == 3
        assert store_resp["result"]["isError"] is False

        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "wm_get_result", "arguments": {"key": "greeting"}},
            },
        )
        get_resp = _recv(proc)
        assert get_resp["id"] == 4
        assert get_resp["result"]["isError"] is False
        assert "hello" in get_resp["result"]["content"][0]["text"]
    finally:
        _shutdown(proc)

    assert proc.returncode == 0


def test_memory_is_per_process(tmp_path):
    """Two consecutive server processes share no WorkingMemory state."""
    first = _spawn(tmp_path, "mcp-local", "memory")
    try:
        _send(first, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _recv(first)
        _send(
            first,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "wm_store_result", "arguments": {"key": "shared", "data": "only-in-first"}},
            },
        )
        resp = _recv(first)
        assert resp["result"]["isError"] is False
    finally:
        _shutdown(first)

    second = _spawn(tmp_path, "mcp-local", "memory")
    try:
        _send(second, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _recv(second)
        _send(
            second,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "wm_get_result", "arguments": {"key": "shared"}},
            },
        )
        resp = _recv(second)
        # The key from the first process must NOT be visible here.
        assert resp["result"]["isError"] is True
    finally:
        _shutdown(second)


def test_stdout_purity_with_printing_toolkit(tmp_path):
    """Import-time prints from a stub toolkit land on stderr, never stdout."""
    (tmp_path / "printing_toolkit.py").write_text(
        "print('import-time noise from a badly-behaved toolkit module')\n"
        "\n"
        "from parrot.tools.toolkit import AbstractToolkit\n"
        "\n"
        "\n"
        "class PrintingToolkit(AbstractToolkit):\n"
        "    async def echo(self, x: str) -> str:\n"
        '        """Echo the input back."""\n'
        "        return x\n",
        encoding="utf-8",
    )
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n" "  printer:\n" "    class: printing_toolkit.PrintingToolkit\n" "    kwargs: {}\n",
        encoding="utf-8",
    )

    proc = _spawn(tmp_path, "mcp-local", "printer")
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        resp = _recv(proc)  # raises AssertionError if stdout isn't clean JSON-RPC
        assert resp["id"] == 1
    finally:
        _shutdown(proc)

    stderr = proc.stderr.read()
    assert "import-time noise from a badly-behaved toolkit module" in stderr


def test_example_config_parses():
    """`examples/mcp-toolkits.yaml` parses via `load_toolkits_config`."""
    from parrot.mcp.toolkit_config import load_toolkits_config

    example = _REPO_ROOT / "examples" / "mcp-toolkits.yaml"
    assert example.exists(), f"missing {example}"

    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".parrot").mkdir()
        shutil.copy(example, root / ".parrot" / "mcp-toolkits.yaml")

        cfg = load_toolkits_config(root)

    assert "memory" in cfg.toolkits
    assert "scraping" in cfg.toolkits
    assert "browsing" in cfg.toolkits


@pytest.mark.parametrize("name", ["memory"])
def test_mcp_local_list_shows_builtin(tmp_path, name):
    """Sanity check that `--list` (a fast, non-serving path) still works
    over the same subprocess bootstrap used by the serving tests above."""
    proc = subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP, "mcp-local", "--list"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert name in proc.stdout
    assert proc.stderr == ""
