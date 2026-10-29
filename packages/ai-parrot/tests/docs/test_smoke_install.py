"""Unit tests for scripts/install/smoke_install.py (FEAT-633 spike S1)."""
from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "smoke_install.py"


@pytest.fixture(scope="module")
def smoke():
    """Load the script by path — scripts/install is not a package."""
    spec = importlib.util.spec_from_file_location("smoke_install", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_install"] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


def _fake_server(tmp_path: Path, *, banner: str = "", tools: tuple[str, ...] = ("wiki_query",)) -> Path:
    """Write a newline-JSON stdio server answering initialize + tools/list like StdioMCPServer."""
    path = tmp_path / "fake_server.py"
    prefix = f"sys.stdout.write({banner!r}); sys.stdout.flush()" if banner else ""
    path.write_text(textwrap.dedent(f"""
        import json, sys
        {prefix}
        def send(obj):
            sys.stdout.write(json.dumps(obj) + "\\n")
            sys.stdout.flush()
        for line in sys.stdin:
            req = json.loads(line)
            if req.get("method") == "initialize":
                send({{"jsonrpc": "2.0", "id": req["id"], "result": {{
                    "protocolVersion": req["params"]["protocolVersion"], "capabilities": {{}},
                    "serverInfo": {{"name": "fake", "version": "0"}}}}}})
            elif req.get("method") == "tools/list":
                send({{"jsonrpc": "2.0", "id": req["id"], "result": {{
                    "tools": [{{"name": n}} for n in {list(tools)!r}]}}}})
    """), encoding="utf-8")
    return path


def test_mcp_initialize_ok(smoke, tmp_path):
    resp = smoke.mcp_initialize([sys.executable, str(_fake_server(tmp_path))], tmp_path, timeout=20)
    assert resp["id"] == 1 and "protocolVersion" in resp["result"]


def test_mcp_initialize_rejects_stdout_pollution(smoke, tmp_path):
    with pytest.raises(smoke.SmokeError):
        smoke.mcp_initialize([sys.executable, str(_fake_server(tmp_path, banner="hello\n"))], tmp_path, timeout=20)


def test_mcp_initialize_timeout(smoke, tmp_path):
    silent = tmp_path / "silent.py"
    silent.write_text("import sys, time\nsys.stdin.readline()\ntime.sleep(30)\n", encoding="utf-8")
    with pytest.raises(smoke.SmokeError):
        smoke.mcp_initialize([sys.executable, str(silent)], tmp_path, timeout=1)


def test_tools_list_without_wiki_tools_fails(smoke, tmp_path):
    server = _fake_server(tmp_path, tools=("other_tool",))
    with pytest.raises(smoke.SmokeError, match="wiki_query"):
        smoke.mcp_initialize([sys.executable, str(server)], tmp_path, timeout=20)


def test_venv_script_posix_and_windows(smoke, tmp_path):
    assert smoke.venv_script(tmp_path, "wikitoolkit", os_name="posix") == tmp_path / "bin" / "wikitoolkit"
    win = smoke.venv_script(tmp_path, "wikitoolkit", os_name="nt")
    assert win.parts[-2:] == ("Scripts", "wikitoolkit.exe")


def test_venv_script_reads_os_name(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(smoke.os, "name", "nt")
    parts = smoke.venv_script(tmp_path, "parrot").parts[-2:]
    monkeypatch.undo()  # restore before pytest builds any Path
    assert parts == ("Scripts", "parrot.exe")


def test_parse_sdist_failures(smoke):
    err = "error: Failed to build `faiss-cpu==1.9.0`\n  Caused by: Building source distributions is disabled (--no-build)"
    assert "faiss-cpu" in smoke.parse_sdist_failures(err)


def test_parse_sdist_failures_uv_resolver_no_wheels(smoke):
    """uv's resolver form (install-matrix, macOS arm64): the package name, never the word after "building"."""
    err = (
        "error: No solution found when resolving dependencies\n"
        "  cause: Because python-datamodel>=0.10.17 has no usable wheels and ai-parrot==1.2.5 depends on "
        "python-datamodel>=0.10.17, we can conclude that ai-parrot==1.2.5 cannot be used.\n"
        "hint: Wheels are required for `python-datamodel` because building from source is disabled for all "
        "packages (i.e., with `--no-build`)"
    )
    assert smoke.parse_sdist_failures(err) == ["python-datamodel"]
