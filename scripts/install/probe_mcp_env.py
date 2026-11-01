#!/usr/bin/env python3
"""Stdio MCP probe: records what a host gives an MCP server (FEAT-633 spike S3).

Register it in Claude Code / Codex / Gemini like any stdio server; it answers
``initialize`` and ``tools/list`` (no tools) and logs cwd, argv, interpreter and
selected env vars to stderr and to ``$PARROT_PROBE_LOG`` (JSON lines).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_KEYS: tuple[str, ...] = ("CLAUDE_PROJECT_DIR", "VIRTUAL_ENV", "PARROT_PROJECT", "PWD", "CODEX_HOME")
ENV_PREFIXES: tuple[str, ...] = ("GEMINI_",)
LOG_ENV = "PARROT_PROBE_LOG"
SECRET_MARKERS: tuple[str, ...] = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PWD")
REDACTED = "<redacted>"
SUPPORTED = ("2024-11-05", "2025-03-26", "2025-06-18")   # mirrors server_base.py:17-21


def log_path(env: Mapping[str, str]) -> Path:
    """``$PARROT_PROBE_LOG`` or ``<tempdir>/parrot-probe-mcp-env.jsonl``."""
    return Path(env.get(LOG_ENV) or Path(tempfile.gettempdir()) / "parrot-probe-mcp-env.jsonl")


def _redact(name: str, value: str) -> str:
    """Mask the value of any variable whose name looks secret-bearing (kept: that it is set)."""
    upper = name.upper()
    # PWD is the working directory, not a password: only mask names that merely *contain* a marker.
    if name == "PWD":
        return value
    return REDACTED if any(m in upper for m in SECRET_MARKERS) else value


def collect_snapshot(env: Mapping[str, str], argv: list[str], cwd: str) -> dict[str, Any]:
    """Return the record: timestamp, pid, cwd, argv, executable and the selected env vars."""
    selected = {k: env[k] for k in ENV_KEYS if k in env}
    selected.update({k: v for k, v in env.items() if k.startswith(ENV_PREFIXES)})
    selected = {k: _redact(k, v) for k, v in selected.items()}
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "cwd": cwd,
        "argv": argv,
        "executable": sys.executable,
        "env": selected,
    }


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    """Answer one JSON-RPC request; ``None`` for notifications (no response)."""
    method, req_id = request.get("method"), request.get("id")
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "initialize":
        requested = (request.get("params") or {}).get("protocolVersion")
        version = requested if requested in SUPPORTED else SUPPORTED[-1]
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "parrot-probe", "version": "0"},
        }
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main() -> int:
    """Log the snapshot, then serve newline-delimited JSON-RPC until stdin EOF."""
    snapshot = collect_snapshot(os.environ, sys.argv, os.getcwd())
    line = json.dumps(snapshot, sort_keys=True)
    sys.stderr.write(f"parrot-probe: {line}\n")
    try:
        with log_path(os.environ).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        sys.stderr.write(f"parrot-probe: cannot append log: {exc}\n")
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"parrot-probe: skipping invalid JSON: {exc}\n")
            continue
        response = handle(request) if isinstance(request, dict) else None
        if response:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
