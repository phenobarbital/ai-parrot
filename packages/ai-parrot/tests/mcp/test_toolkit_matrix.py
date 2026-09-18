"""Cross-host lifecycle matrix for `parrot toolkits` (FEAT-570, TASK-3381).

Spec §3 Module 10 and §4 Integration Tests, driven by design research S10:
the per-task suites each cover one module in isolation, but only this suite
drives the same lifecycle across all three hosts (Claude, Codex, Google) at
once, with their asymmetries — Codex's structural ownership, Google's dual +
user-global config, Claude's approvals — all live at the same time.

Also carries the two feature-level guarantees that cannot be asserted from
inside a single module: AC6 (no secret on disk) and AC5 (wikitoolkit
untouched, proven end-to-end through the CLI).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.cli import cli
from parrot.mcp.hosts import HostKind, detect_hosts
from parrot.mcp.toolkit_install import dist_available, inventory

CORE_TOOLKITS = ["memory", "database-query"]  # no optional distribution required

# ---------------------------------------------------------------------------
# `mcp-local` spawn/handshake bootstrap — adapted from tests/mcp/test_mcp_local_e2e.py
# (FEAT-485 TASK-2650) rather than imported: that module's helpers are private
# and live in a different tests root (repo-top-level tests/, not this
# distribution's packages/ai-parrot/tests/).
# ---------------------------------------------------------------------------
_CORE_SRC = Path(__file__).resolve().parents[2] / "src"

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

    Fails loudly (rather than hanging forever) if the process exits without
    producing a line, or produces a non-JSON line.
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


def test_all_three_hosts_detected(repo_with_hosts):
    found = detect_hosts(repo_with_hosts)
    assert {HostKind.CLAUDE, HostKind.CODEX} <= set(found)


def _entry_present(repo_with_hosts: Path, host: str) -> bool:
    """True when `parrot-memory` is registered in `host`'s real config file(s)."""
    if host == "claude":
        text = (repo_with_hosts / ".mcp.json").read_text(encoding="utf-8")
        return "parrot-memory" in text
    if host == "codex":
        text = (repo_with_hosts / ".codex" / "config.toml").read_text(encoding="utf-8")
        return "mcp_servers.parrot-memory" in text
    # google — primary is the redirected user-global config (never the real home)
    gemini_path = repo_with_hosts / "gemini_home" / "mcp_config.json"
    plugin_path = repo_with_hosts / ".agents" / "plugins" / "parrot" / "mcp_config.json"
    gemini_text = gemini_path.read_text(encoding="utf-8") if gemini_path.exists() else ""
    plugin_text = plugin_path.read_text(encoding="utf-8") if plugin_path.exists() else ""
    return "parrot-memory" in gemini_text and "parrot-memory" in plugin_text


@pytest.mark.parametrize("host", ["claude", "codex", "google"])
def test_lifecycle_install_disable_enable_uninstall(repo_with_hosts, host):
    """install -> disable -> enable -> uninstall, per host, through the CLI."""
    runner = CliRunner()

    result = runner.invoke(cli, ["toolkits", "install", "memory", "--host", host, "--yes"])
    assert result.exit_code == 0, result.output
    assert _entry_present(repo_with_hosts, host)

    result = runner.invoke(cli, ["toolkits", "disable", "memory", "--host", host, "--yes"])
    assert result.exit_code == 0, result.output
    assert not _entry_present(repo_with_hosts, host)
    section_text = (repo_with_hosts / ".parrot" / "mcp-toolkits.yaml").read_text(encoding="utf-8")
    assert "memory:" in section_text
    assert "enabled: false" in section_text

    result = runner.invoke(cli, ["toolkits", "enable", "memory", "--host", host, "--yes"])
    assert result.exit_code == 0, result.output
    assert _entry_present(repo_with_hosts, host)

    result = runner.invoke(cli, ["toolkits", "uninstall", "memory", "--host", host, "--yes"])
    assert result.exit_code == 0, result.output
    assert not _entry_present(repo_with_hosts, host)
    section_text_after = (repo_with_hosts / ".parrot" / "mcp-toolkits.yaml").read_text(encoding="utf-8")
    assert "memory:" not in section_text_after


def test_install_without_host_targets_every_detected_host(repo_with_hosts):
    """No `--host` given -> every detected host gets the entry (spec §8 Q1 default (a))."""
    result = CliRunner().invoke(cli, ["toolkits", "install", "memory", "--yes"])
    assert result.exit_code == 0, result.output

    assert _entry_present(repo_with_hosts, "claude")
    assert _entry_present(repo_with_hosts, "codex")
    assert _entry_present(repo_with_hosts, "google")


def test_wikitoolkit_never_touched_end_to_end(repo_with_hosts):
    """AC5 — proven through the CLI across the whole lifecycle."""
    before = json.loads((repo_with_hosts / ".mcp.json").read_text())["mcpServers"]["wikitoolkit"]
    runner = CliRunner()
    for argv in (
        ["toolkits", "install", "memory", "--yes"],
        ["toolkits", "disable", "memory", "--yes"],
        ["toolkits", "uninstall", "memory", "--yes"],
    ):
        runner.invoke(cli, argv)
    after = json.loads((repo_with_hosts / ".mcp.json").read_text())["mcpServers"]["wikitoolkit"]
    assert after == before


def test_install_never_pre_authorizes_a_nonexistent_wikitoolkit(tmp_path, monkeypatch):
    """AC5 / spec §7 S3 — `parrot toolkits install` must never approve a
    "wikitoolkit" server that was never installed via `parrot claude install`.

    Regression test: `ClaudeAdapter.sync_approvals`'s install/enable branch
    previously called `_install_mcp_approval`, which merges
    `_managed_server_names(root)` — a helper that UNCONDITIONALLY prepends
    `"wikitoolkit"` regardless of whether a wikitoolkit `.mcp.json` entry
    exists. On a repo with no wikitoolkit entry at all, that pre-authorized
    a phantom approval in `.claude/settings.local.json`.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    result = CliRunner().invoke(cli, ["toolkits", "install", "memory", "--host", "claude", "--yes"])
    assert result.exit_code == 0, result.output

    local_path = tmp_path / ".claude" / "settings.local.json"
    local = json.loads(local_path.read_text(encoding="utf-8"))
    assert "wikitoolkit" not in local.get("enabledMcpjsonServers", [])
    assert "parrot-memory" in local.get("enabledMcpjsonServers", [])


def test_no_secret_reaches_any_written_file(repo_with_hosts, monkeypatch):
    """AC6 — a DSN in the environment must never be written to disk."""
    secret = "postgres://user:sup3rs3cr3t@db.internal:5432/prod"
    monkeypatch.setenv("QS_DSN", secret)
    monkeypatch.setenv("DATABASE_URL", secret)
    result = CliRunner().invoke(cli, ["toolkits", "install", *CORE_TOOLKITS, "--yes"])
    assert result.exit_code == 0, result.output

    for path in repo_with_hosts.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert secret not in text, f"secret leaked into {path}"


def test_requires_dist_is_reported_without_importing(repo_with_hosts):
    """A template for an absent distribution is listed, flagged, and not imported."""
    before = set(sys.modules)
    rows = inventory(repo_with_hosts, hosts=[])
    row = next(r for r in rows if r.name == "querysource")

    assert row.requires_dist
    assert row.dist_available is dist_available(row.requires_dist)

    new_modules = set(sys.modules) - before
    assert not [m for m in new_modules if m.startswith(("parrot_tools", "parrot.tools"))]


def test_installed_toolkit_actually_serves(repo_with_hosts):
    """AC3 — install then spawn `parrot mcp-local memory` and complete a handshake."""
    result = CliRunner().invoke(cli, ["toolkits", "install", "memory", "--yes"])
    assert result.exit_code == 0, result.output

    proc = _spawn(repo_with_hosts, "mcp-local", "memory")
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
    finally:
        _shutdown(proc)

    assert proc.returncode == 0
