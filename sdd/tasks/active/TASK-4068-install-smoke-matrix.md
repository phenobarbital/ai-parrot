# TASK-4068: Spike S1: clean-install smoke script + cross-platform install-matrix workflow

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0, spike **S1**: before building the `--global` bootstrap (M2), prove that
`uv venv --python 3.12` + `uv pip install ai-parrot` works on a clean, compiler-free machine
(macOS arm64 / Windows x64 / Ubuntu x64) and that `wikitoolkit mcp` then answers an MCP
`initialize`, recording every sdist fallback. The compiled dependency chain
(navigator-api[uvloop], navigator-auth, asyncdb, ormsgpack, brotli, numexpr, faiss-cpu,
pyarrow, the two in-repo Cython extensions — spec §7 "Wheel availability is the gating risk")
is the unproven part.

**Gate (spec §3 M0)**: S1 fail ⇒ the core wheel matrix (TASK-4094, M8) ships BEFORE the
bootstrap tasks (TASK-4074/4075). The smoke harness built here is deliberately reusable:
TASK-4094 calls the same workflow (`workflow_call`) as the per-platform clean-install gate
codex S11 requires ("build success is not the gate").

---

## Scope

- Implement `scripts/install/smoke_install.py`, a stdlib-only CLI that creates a throwaway
  uv venv, installs ai-parrot (from a requirement or a local wheel) with `--no-build` by
  default, runs the three console scripts' `--help`, builds a wiki in a temp git repo and
  performs a JSON-RPC `initialize` against `wikitoolkit mcp` over stdio, and writes a
  JSON `SmokeReport`.
- Add `.github/workflows/install-matrix.yml` (`workflow_dispatch` + `workflow_call`) running
  the script on ubuntu/macos/windows with a uv-managed Python only.
- Write unit tests for `mcp_initialize` (fake stdio server) and `venv_script` (both platforms).
- Write the S1 spike report skeleton with trigger instructions, a per-OS results table to
  fill from the run, and the decision rule.

**NOT in scope**: running the workflow on GitHub (a human triggers it; results are pasted
into the report); changing `release.yml` or `[tool.cibuildwheel]` (TASK-4094); the
`--global` bootstrap (TASK-4074/4075); any launcher code (TASK-4071/4072).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/smoke_install.py` | CREATE | Stdlib-only clean-install smoke harness + `SmokeReport` JSON |
| `.github/workflows/install-matrix.yml` | CREATE | 3-OS matrix, `workflow_dispatch` + reusable `workflow_call` |
| `packages/ai-parrot/tests/docs/test_smoke_install.py` | CREATE | Unit tests: `mcp_initialize` vs a fake stdio server, `venv_script` |
| `sdd/state/FEAT-633/spikes/S1-install-matrix.md` | CREATE | Spike report: how to trigger, results table, decision rule |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# The script is stdlib-only and imports NOTHING from parrot. The test loads it by path:
import importlib.util  # stdlib — scripts/install/ is NOT a package (no __init__.py; verified: ls scripts/install/)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml:199-206 — the three console scripts the smoke runs
# parrot = "parrot.cli:cli"                                  # line 200
# wikitoolkit = "parrot.knowledge.wiki.entry:main"           # line 204
# bookstore = "parrot.knowledge.bookstore.cli:main"          # line 206

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def mcp() -> None:            # line 1464 — `wikitoolkit mcp` → parrot.knowledge.wiki.mcp_server.main
def build(...):               # line 1515 — options --quiet (1488), --no-export (1490), --no-graph (1495), --no-git (1487)

# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
def main() -> None:           # line 313 — exits 1 on stderr "Error: not inside a git repository with a wiki"
#   when find_project_root(cwd) is None (lines 321-327) AND exits 1 with
#   "wiki not built yet ... Run `wikitoolkit build` first." when not config.is_built(root) (lines 335-340)
#   ⇒ the smoke MUST `git init` + `wikitoolkit build` in the temp dir before `wikitoolkit mcp`.

# packages/ai-parrot/src/parrot/mcp/local_server.py — the wire format mcp_initialize must speak
class StdioMCPServer(LocalMCPServerBase):          # line 54
    async def start(self): ...                      # line 70 — ONE JSON-RPC message per line on stdin (readline, line 87)
    def _send(self, response): ...                  # line 187 — sys.stdout.write(json.dumps(response) + "\n") (line 193)
    async def _handle_request(self, request): ...   # line 198 — "initialize" (205) → {"jsonrpc":"2.0","id":<id>,"result":...} (225-229)
                                                    #   "notifications/initialized" (213) → no response

# packages/ai-parrot/src/parrot/mcp/server_base.py
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")   # lines 17-21
def negotiate_protocol_version(requested: str | None) -> str:              # line 29
async def handle_initialize(self, params) -> dict:                         # line 80 — result keys:
#   "protocolVersion", "capabilities" {"tools": {"listChanged": False}}, "serverInfo" {name, version, description}

# .github/workflows/release.yml:90 — `uses: astral-sh/setup-uv@v10.2.0` (the pinned action version to reuse)
# packages/ai-parrot/tests/docs/test_install_posix.py:11-12 — REPO_ROOT = Path(__file__).resolve().parents[4]; script-by-path pattern
```

### Does NOT Exist
- ~~`scripts/install/__init__.py`~~ — `scripts/install/` holds only `install-parrot.sh` / `install-parrot.ps1`; never `import scripts.install...`.
- ~~`packages/ai-parrot/tests/docs/__init__.py` / `conftest.py`~~ — the dir has neither; do not create them.
- ~~`.github/workflows/install-matrix.yml`~~ — new here; no existing workflow uses `workflow_call`.
- ~~Content-Length (LSP-style) framing in the parrot stdio server~~ — it is newline-delimited JSON only.
- ~~a `wikitoolkit mcp` that serves an unbuilt repo~~ — it exits 1 (see above).
- ~~`uv pip install --only-binary`~~ — use uv's `--no-build` (refuses every sdist build).
- ~~macOS core wheels~~ — only `parrot-codec` builds them today (spec §6); an S1 failure on macOS is expected evidence, not a script bug.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/install/smoke_install.py", "action": "CREATE"},
    {"path": ".github/workflows/install-matrix.yml", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/docs/test_smoke_install.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-633/spikes/S1-install-matrix.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#mcp",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#main",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer._send",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer._handle_request",
    "sym:packages/ai-parrot/src/parrot/mcp/server_base.py#negotiate_protocol_version"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/tests/docs/test_install_posix.py — repo-root-relative script path
REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.sh"
```

### Key Constraints
- **Stdlib only** — the script runs under a bare uv-managed Python BEFORE ai-parrot exists
  (`uv run --no-project`); no click, no pydantic, no parrot imports.
- **Clean-machine semantics**: the workflow must NOT use `actions/setup-python`; set
  `UV_PYTHON_PREFERENCE: only-managed` so uv never picks up the runner's system Python.
- **`--no-build` is the evidence**: an sdist fallback must FAIL the install and be listed
  in `sdist_failures` — silently compiling on a runner that has a compiler would hide the
  very problem S1 exists to find.
- **stdout discipline (spec §5 AC4)**: the first stdout line of `wikitoolkit mcp` must be the
  JSON-RPC response; any earlier byte is a failure (`mcp_ok = false`).
- Windows: console scripts live in `<venv>\Scripts\<name>.exe`; use the `.exe` path in argv.
- Read the child's stdout line on a helper thread with a deadline — `select()` does not
  work on pipes on Windows.
- Diagnostics to stderr via `sys.stderr.write` (stdlib-only script; no `print`).

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/local_server.py` — stdio framing
- `packages/ai-parrot/src/parrot/mcp/server_base.py` — initialize result shape
- `.github/workflows/release.yml` — setup-uv pin, artifact upload conventions

---

## Implementation Blueprint

### Steps (in order)
1. Write `smoke_install.py` dataclass + `venv_script` + `mcp_initialize` first — *why*: they are the unit-testable core.
2. Write the test file and make it pass locally — *why*: proves the JSON-RPC client before any CI run.
3. Write `run_smoke` + `main` — *why*: the orchestration only shells out to uv/console scripts.
4. Write `install-matrix.yml` with both triggers — *why*: TASK-4094 reuses it via `workflow_call`.
5. Write the S1 report skeleton — *why*: a human pastes per-OS results after triggering the workflow.

### `scripts/install/smoke_install.py` (CREATE)
```python
#!/usr/bin/env python3
"""Clean-install smoke harness for ai-parrot (FEAT-633 spike S1; reused by TASK-4094).

Stdlib only: runs under a bare uv-managed interpreter before ai-parrot exists.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCRIPTS: tuple[str, ...] = ("parrot", "wikitoolkit", "bookstore")
INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "parrot-smoke", "version": "0"}},
}


class SmokeError(RuntimeError):
    """Raised when a smoke step fails; the message is recorded in ``SmokeReport.errors``."""


@dataclass
class SmokeReport:
    """JSON-serialisable outcome of one smoke run."""

    platform: str
    python: str
    install_ok: bool = False
    sdist_failures: list[str] = field(default_factory=list)
    scripts_ok: dict[str, bool] = field(default_factory=dict)
    mcp_ok: bool = False
    errors: list[str] = field(default_factory=list)


def venv_script(venv: Path, name: str, *, os_name: str | None = None) -> Path:
    """Return ``venv/bin/<name>`` on POSIX, ``venv/Scripts/<name>.exe`` on Windows."""
    if (os_name or os.name) == "nt":
        return venv / "Scripts" / f"{name}.exe"   # build via `/` — never Path(...) (WindowsPath fails on POSIX)
    return venv / "bin" / name


def mcp_initialize(cmd: list[str], cwd: Path, timeout: float = 30.0) -> dict:
    """Spawn ``cmd`` as a stdio MCP server, send ``initialize``, return the parsed response.

    Raises:
        SmokeError: on timeout, a non-JSON first stdout line (stdout pollution), a
            response without ``result.protocolVersion``, or a mismatched ``id``.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
    try:
        proc.stdin.write(json.dumps(INITIALIZE) + "\n")
        proc.stdin.flush()
        try:
            first = lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise SmokeError(f"no initialize response within {timeout}s") from exc
        # FILL IN: parse `first` with json.loads; non-JSON or empty ⇒ SmokeError naming the
        #   leaked bytes (AC4: nothing on stdout before the handshake); assert id == 1 and
        #   "protocolVersion" in result — bounded by local_server.py:193/225-229, server_base.py:84-98
        raise NotImplementedError
    finally:
        # FILL IN: close stdin (server loop ends on EOF, local_server.py:88-89), wait up to 10s,
        #   then kill; attach the stderr tail to any SmokeError — bounded by no orphaned children
        raise NotImplementedError


def run_smoke(spec: str | None, wheel: Path | None, python: str, no_build: bool) -> SmokeReport:
    """Create a temp uv venv, install, run the three scripts' ``--help`` and the MCP handshake."""
    report = SmokeReport(platform=f"{platform.system()}-{platform.machine()}", python=python)
    uv = shutil.which("uv")
    if uv is None:
        report.errors.append("uv not found on PATH")
        return report
    with tempfile.TemporaryDirectory(prefix="parrot-smoke-") as tmp:
        venv, repo = Path(tmp) / "venv", Path(tmp) / "repo"
        # FILL IN: `uv venv <venv> --python <python>`; `uv pip install --python <venv> [--no-build]
        #   <spec | wheel>`; on failure parse stderr for each package uv refused to build into
        #   sdist_failures — bounded by "every sdist fallback recorded" (spec §3 M0)
        # FILL IN: for each SCRIPTS run venv_script(venv, name) --help → scripts_ok[name]
        # FILL IN: git init <repo>, write one tracked file, `wikitoolkit build --quiet --no-export
        #   --no-graph` (exact flags/needs of a fresh repo decided by running it — bounded by
        #   mcp_server.py:335-340), then mcp_initialize([wikitoolkit, "mcp"], repo) → mcp_ok
        raise NotImplementedError
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry: exit 0 iff install, all scripts and the MCP handshake succeeded."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--spec", default=None, help="pip requirement (default: ai-parrot)")
    source.add_argument("--wheel", type=Path, default=None, help="local wheel to install instead")
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--no-build", dest="no_build", action="store_true", default=True)
    parser.add_argument("--allow-build", dest="no_build", action="store_false")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_smoke(args.spec or (None if args.wheel else "ai-parrot"), args.wheel, args.python, args.no_build)
    payload = json.dumps(asdict(report), indent=2)
    if args.json_out:
        args.json_out.write_text(payload, encoding="utf-8")
    sys.stderr.write(payload + "\n")
    return 0 if report.install_ok and all(report.scripts_ok.values()) and report.mcp_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: functions named by the brief stay importable for the unit test; `os_name`
keyword avoids monkeypatching the global `os.name` (which breaks `pathlib.Path()` creation on
POSIX). The JSON goes to stderr + file so stdout stays free for GitHub step logs only.

### `.github/workflows/install-matrix.yml` (CREATE)
```yaml
name: install-matrix
on:
  workflow_dispatch:
    inputs:
      spec: {description: "pip requirement to install", default: "ai-parrot", type: string}
      python: {description: "uv-managed Python", default: "3.12", type: string}
  workflow_call:
    inputs:
      spec: {type: string, default: "ai-parrot", required: false}
      wheel-artifact: {type: string, default: "", required: false}   # TASK-4094: name of an uploaded wheel artifact
      python: {type: string, default: "3.12", required: false}

jobs:
  smoke:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    env:
      UV_PYTHON_PREFERENCE: only-managed     # clean-machine semantics: never the runner's Python
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v10.2.0     # verified pin: release.yml:90
      # NO actions/setup-python — uv supplies Python
      - if: ${{ inputs.wheel-artifact != '' }}
        uses: actions/download-artifact@v8   # verified: release.yml:541
        with: {name: "${{ inputs.wheel-artifact }}", path: dist}
      - name: Smoke
        shell: bash
        run: |
          # FILL IN: when dist/ holds a wheel for this platform pass --wheel <it>, else --spec "${{ inputs.spec }}"
          #   — bounded by one uv invocation per leg and the report path below
          uv run --no-project --python "${{ inputs.python }}" scripts/install/smoke_install.py \
            --spec "${{ inputs.spec }}" --json-out "smoke-${{ matrix.os }}.json"
      - if: always()
        uses: actions/upload-artifact@v7     # verified: release.yml:77
        with: {name: "smoke-${{ matrix.os }}", path: "smoke-${{ matrix.os }}.json"}
```
**Why this shape**: both triggers share one job so TASK-4094's release gate runs exactly what
S1 validated. `fail-fast: false` — S1 needs every OS's evidence even when one leg fails.
Artifact action majors match `release.yml` (upload@v7 :77, download@v8 :541).

### `packages/ai-parrot/tests/docs/test_smoke_install.py` (CREATE)
```python
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
    sys.modules["smoke_install"] = module   # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


def _fake_server(tmp_path: Path, *, banner: str = "") -> Path:
    """Write a newline-JSON stdio server answering initialize like StdioMCPServer."""
    path = tmp_path / "fake_server.py"
    path.write_text(textwrap.dedent(f"""
        import json, sys
        {"sys.stdout.write(" + repr(banner) + "); sys.stdout.flush()" if banner else ""}
        req = json.loads(sys.stdin.readline())
        sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": req["id"], "result": {{
            "protocolVersion": req["params"]["protocolVersion"], "capabilities": {{}},
            "serverInfo": {{"name": "fake", "version": "0"}}}}}}) + "\\n")
        sys.stdout.flush()
        sys.stdin.read()
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


def test_venv_script_posix_and_windows(smoke, tmp_path):
    assert smoke.venv_script(tmp_path, "wikitoolkit", os_name="posix") == tmp_path / "bin" / "wikitoolkit"
    win = smoke.venv_script(tmp_path, "wikitoolkit", os_name="nt")
    assert win.parts[-2:] == ("Scripts", "wikitoolkit.exe")


def test_venv_script_reads_os_name(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(smoke.os, "name", "nt")
    parts = smoke.venv_script(tmp_path, "parrot").parts[-2:]
    monkeypatch.undo()                       # restore before pytest builds any Path
    assert parts == ("Scripts", "parrot.exe")
```

### `sdd/state/FEAT-633/spikes/S1-install-matrix.md` (CREATE)
```markdown
# Spike S1 — clean-machine install matrix (FEAT-633)

## How to run
- GitHub → Actions → **install-matrix** → Run workflow (inputs: `spec`, default `ai-parrot`;
  `python`, default `3.12`), or `gh workflow run install-matrix.yml -f spec=ai-parrot -f python=3.12`.
- Each leg uploads `smoke-<os>.json` (`SmokeReport`). Local: `uv run --no-project --python 3.12
  scripts/install/smoke_install.py --json-out smoke.json`.

## Results (fill from the run)
| OS | Run URL | install_ok | sdist_failures | parrot | wikitoolkit | bookstore | mcp_ok |
|---|---|---|---|---|---|---|---|
| ubuntu-latest (x64) | | | | | | | |
| macos-latest (arm64) | | | | | | | |
| windows-latest (x64) | | | | | | | |

## Decision rule (spec §3 M0)
- All three legs green ⇒ S1 passes; bootstrap (TASK-4074/4075) may proceed in any order vs TASK-4094.
- Any leg with `sdist_failures` or `install_ok=false` ⇒ S1 FAILS: TASK-4094 (core wheel matrix)
  ships BEFORE the bootstrap; list each failing package and its proposed remedy (marker-guarded
  extra, upstream wheel, in-repo wheel build) here.
- `mcp_ok=false` with install green ⇒ file a ledger issue (stdio/stdout pollution) — blocks M1/M2.

## Verdict
<!-- pass | fail — with date and run URLs -->
```

### FILL IN checklist
- [ ] `smoke_install.py::mcp_initialize` — response validation + teardown; bounded by AC4 and local_server.py framing
- [ ] `smoke_install.py::run_smoke` — uv invocations, sdist-failure parsing, fresh-repo build flags; bounded by spec §3 M0
- [ ] `install-matrix.yml` — wheel-vs-spec selection when `wheel-artifact` is set; bounded by TASK-4094 reuse

---

## Acceptance Criteria

- [ ] `scripts/install/smoke_install.py` imports only the stdlib (`grep -E '^(import|from) ' ` shows no third-party or parrot module).
- [ ] `mcp_initialize` returns the response for a well-behaved server and raises `SmokeError` on stdout pollution and on timeout (spec §5 AC4: nothing on stdout before the handshake).
- [ ] `venv_script` returns `bin/<name>` on POSIX and `Scripts/<name>.exe` on Windows.
- [ ] `--no-build` is on by default; an sdist fallback makes `install_ok` false and is listed in `sdist_failures`.
- [ ] `install-matrix.yml` has `workflow_dispatch` and `workflow_call` triggers, 3-OS matrix, `astral-sh/setup-uv@v10.2.0`, no `setup-python`, `UV_PYTHON_PREFERENCE: only-managed`, and uploads the JSON report even on failure.
- [ ] `S1-install-matrix.md` contains trigger instructions, the per-OS table and the spec §3 M0 decision rule.
- [ ] A local run `uv run --no-project --python 3.12 scripts/install/smoke_install.py --allow-build` on Linux reports `mcp_ok: true` (evidence pasted into the Completion Note).
- [ ] `ruff check scripts/install/smoke_install.py packages/ai-parrot/tests/docs/test_smoke_install.py` passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_smoke_install.py -q`
- `pytest packages/ai-parrot/tests/docs/test_install_posix.py -q`

---

## Test Specification

The full test file is the `test_smoke_install.py` blueprint block above (fake stdio server
tests: OK / stdout pollution / timeout; `venv_script` POSIX + Windows by keyword and by
patched `os.name`). No network, no uv, no ai-parrot import.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4068 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
