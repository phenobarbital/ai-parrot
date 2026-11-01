"""Tests for scripts/install/probe_mcp_env.py (FEAT-633 spike S3)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "probe_mcp_env.py"


def _run(tmp_path: Path, extra_env: dict[str, str]) -> tuple[list[dict], Path]:
    log = tmp_path / "probe.jsonl"
    env = {**os.environ, "PARROT_PROBE_LOG": str(log), **extra_env}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--marker"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        capture_output=True, text=True, cwd=tmp_path, env=env, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()], log


def test_handshake_and_empty_tool_list(tmp_path):
    responses, _ = _run(tmp_path, {})
    assert [r["id"] for r in responses] == [1, 2]          # notification got no response
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert responses[1]["result"] == {"tools": []}


def test_log_record_contents(tmp_path):
    _, log = _run(tmp_path, {"CLAUDE_PROJECT_DIR": "/x", "GEMINI_FOO": "bar", "PARROT_PROJECT": "/p"})
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert Path(record["cwd"]).resolve() == tmp_path.resolve()
    assert record["argv"][-1] == "--marker"
    assert record["env"]["CLAUDE_PROJECT_DIR"] == "/x"
    assert record["env"]["GEMINI_FOO"] == "bar"
    assert record["env"]["PARROT_PROJECT"] == "/p"
    assert "executable" in record and "pid" in record


def test_secret_valued_vars_are_redacted_everywhere(tmp_path, capfd):
    """GEMINI_API_KEY-style values never reach the JSONL log (nor stderr)."""
    _, log = _run(tmp_path, {"GEMINI_API_KEY": "s3cr3t-value", "GEMINI_DB_PASSWORD": "hunter2", "GEMINI_REGION": "eu"})
    text = log.read_text(encoding="utf-8")
    assert "s3cr3t-value" not in text and "hunter2" not in text
    record = json.loads(text.splitlines()[-1])
    assert record["env"]["GEMINI_API_KEY"] == "<redacted>"
    assert record["env"]["GEMINI_DB_PASSWORD"] == "<redacted>"
    assert record["env"]["GEMINI_REGION"] == "eu"
