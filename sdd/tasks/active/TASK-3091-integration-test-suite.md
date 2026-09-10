# TASK-3091: Integration test suite — stdio protocol, raw MCP validation, Git/writer lifecycles, cross-process coordination, client configuration, host smoke

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3081, TASK-3082, TASK-3086, TASK-3087, TASK-3089
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests" (all seven rows) and "Test Data / Fixtures",
§3 Module M9 (tests half), AC1, AC2, AC10, AC13, AC14. The unit suites
prove each module; this task proves the whole path a host actually
uses: `parrot mcp-local <name>` → `create_toolkit_mcp_server` →
`StdioMCPServer` → `MCPToolAdapter` → toolkit. It also records the
evidence artefacts under `artifacts/logs/` that AC14 requires.

---

## Scope

Create `packages/ai-parrot-tools/tests/tool_optimizations/integration/`
with `__init__.py`, `conftest.py` and these modules:

- `test_stdio_protocol.py` (spec row "Stdio protocol"): for each of
  `local-git`, `bounded-source`, `targeted-writer` (writer configured
  WITHOUT `llm:` so only `writer_apply` is exposed, and once WITH a
  monkeypatched `LLMFactory.create` returning the `FakeClient` from
  `test_writer.py`):
  - in-process: `create_toolkit_mcp_server(name, root=tmp_repo, config_path=<yaml>)`,
    then `initialize` / `tools/list` / `tools/call` via `_handle_request`
    (`local_server.py:84`); assert every registered adapter's `.tool` is
    an `AbstractTool` (`server.tools` values are `MCPToolAdapter`s,
    `server_base.py:68-78`), names are exactly the spec's method names
    (no prefix), mutations carry `confirm` in `required`.
  - subprocess: reuse the bootstrap from `tests/mcp/test_mcp_local_e2e.py`
    (`_BOOTSTRAP`, `_REPO_ROOT`) to run `parrot mcp-local bounded-source --config <yaml>`
    as a real process; send `initialize`, `tools/list`, one
    `tools/call` over stdin; assert **every stdout line is valid
    JSON-RPC** (stdout purity) and stderr may carry logs.
- `test_raw_mcp_validation.py` (row "Raw MCP validation"): over
  `tools/call` only (never the Python API): unknown argument key,
  `limit: 999`, `start_line` without `end_line`, `paths: []`,
  `paths: ["../x"]`, `artifact_id: "not-hex"`, `confirm` missing on a
  mutation → each returns `isError: true` and NO side effect (index
  bytes unchanged, no artifact dir). This proves policy does not depend
  on `AbstractTool.execute` (spec §6 "Does NOT Exist").
- `test_git_lifecycle.py` (row "Git lifecycle"): temp repo + local bare
  remote + linked worktree (fixtures from `../conftest.py`); run
  `git_fetch → git_preflight → git_prepare_files → (commit by the TEST,
  via subprocess, never by the toolkit) → git_push → git_pull` in the
  main tree and in the linked worktree; after each step compare
  `refs`, working files and **index bytes** against expectations for
  success AND for an injected failure (whitespace error, diverged
  remote, foreign `index.lock`).
- `test_writer_lifecycle.py` (row "Writer lifecycle"): complete TASK
  (fixture `make_valid_task`) → fake model → `writer_generate` →
  bounded hunk review via `BoundedSourceToolkit.source_read` on the
  patch path → `writer_apply` → then the TEST runs the real acceptance
  test from the packet (`pytest tests/test_greeter.py -q` inside the
  temp repo via subprocess) and records its exit code separately from
  the manifest ("record evidence separately from model claims").
- `test_cross_process.py` (row "Cross-process coordination"): spawn two
  Python subprocesses that each construct `LocalGitToolkit` on the same
  worktree and call `git_prepare_files` on different files concurrently
  (barrier via a shared file); assert exactly one wins per moment (no
  lost update: both files end up staged after both complete, index
  fingerprints monotonic), and that neither deletes the other's lock.
  Same shape for two `writer_apply` calls on the same artifact → one
  `ok`, the other `already_applied` or `lock_timeout`, never a corrupt
  file.
- `test_client_configuration.py` (row "Client configuration"): load
  `examples/tool-optimizations-mcp.yaml`; monkeypatch `LLMFactory.create`
  to a recording fake and assert the Bedrock alias string, explicit
  `fallback_model=None`, `max_retries=1`, `read_timeout=120`, and
  `expected_model_ids` reaching the constructor. Add
  `@pytest.mark.real_llm` optional smoke test (marker exists in root
  `pyproject.toml:236`) that only runs when `AWS_PROFILE`/credentials AND
  `PARROT_TOOL_OPT_SMOKE=1` are set: construct via the real factory,
  call `writer_generate` on the fixture task, and only assert that a
  patch artifact was produced (no correctness claim). Skipped by default.
- `test_host_smoke.py` (row "Host smoke tests"): skip unless `claude`
  and/or `codex` binaries are on PATH. Record their `--version` into
  `artifacts/logs/host-versions.txt`. For Claude: run the guard hook
  module directly with a synthetic `Read` payload (the binary's hook
  runner is not driven headlessly) AND validate that `.claude/settings.json`
  produced by `install_guards` parses with the documented schema
  (matcher + command + timeout). For Codex 0.154.0: install into a temp
  root and run `codex exec --sandbox read-only -C <root> "cat big.py"`
  with a 60 s timeout ONLY when `PARROT_TOOL_OPT_HOST_SMOKE=1`; assert the
  denial reason appears in the transcript, otherwise mark the host
  configuration `unsupported` in `artifacts/logs/host-smoke.json`
  (explicit report, per spec "report unsupported configurations
  explicitly"). Never fail the suite because a host is absent.
- `conftest.py`: `tmp_repo_with_yaml(tmp_path)` writing a
  `.parrot/mcp-toolkits.yaml` for the three toolkits with
  `repo_root: <abs tmp repo>`; a `log_evidence` autouse fixture that
  appends each test's outcome to `artifacts/logs/TASK-3091-integration.log`
  (create the dir; `artifacts/` is gitignored).
- Run the FULL existing regression set once and save the log:
  `pytest tests/mcp packages/ai-parrot-tools/tests/tool_optimizations -q | tee artifacts/logs/TASK-3091-regression.log`
  plus `ruff check` and `black --check` on `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations`
  (AC14 "formatting checks").

**NOT in scope**: benchmarks and docs (TASK-3092); fixing product code
(open a Completion Note deviation and, if a defect is found, fix it in
the owning module WITH a regression test and mention it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/__init__.py` | CREATE | Package |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/conftest.py` | CREATE | YAML/repo fixtures, evidence log |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py` | CREATE | In-process + subprocess protocol tests |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py` | CREATE | Invalid `tools/call` arguments |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_git_lifecycle.py` | CREATE | End-to-end Git flow incl. linked worktree |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_writer_lifecycle.py` | CREATE | Generate → review → apply → real pytest |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_cross_process.py` | CREATE | Two-process contention |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_client_configuration.py` | CREATE | Factory kwargs + optional real smoke |
| `packages/ai-parrot-tools/tests/tool_optimizations/integration/test_host_smoke.py` | CREATE | Host version pin + guard smoke |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_server import create_toolkit_mcp_server        # toolkit_server.py:29 (overrides: config_path/include/exclude)
from parrot.mcp.local_server import StdioMCPServer                     # local_server.py:36 ; _handle_request :84
from parrot.mcp.server_base import LocalServerConfig, MCPServerBase    # server_base.py:48, :57 (register_tools :75, handle_tools_call :111)
from parrot.mcp.adapter import MCPToolAdapter                          # adapter.py:8
from parrot.tools.abstract import AbstractTool                         # abstract.py:281
from parrot.mcp.toolkit_config import load_toolkits_config             # toolkit_config.py:80
from parrot.clients.factory import LLMFactory                          # factory.py (create :257) — import lazily inside tests
from parrot_tools.tool_optimizations.git import LocalGitToolkit
from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit
from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit
from parrot_tools.tool_optimizations.installation import install_guards
from parrot_tools.tool_optimizations.hooks import main as hook_main
```

### Existing Signatures to Use
```python
# tests/mcp/test_mcp_local_e2e.py  (root tests dir)
_REPO_ROOT = Path(__file__).resolve().parents[2]   # :34
_CORE_SRC = _REPO_ROOT / "packages" / "ai-parrot" / "src"
_BOOTSTRAP = textwrap.dedent(...)                  # :37-…  runs parrot.cli.cli() with real argv via `sys.executable -c`
# NOTE: from packages/ai-parrot-tools/tests/... the repo root is parents[4]; also prepend packages/ai-parrot-tools/src to sys.path in the bootstrap.
# tests/mcp/test_toolkit_server.py:114-140 — LLMFactory.create monkeypatch pattern (force-import first, then setattr staticmethod)
# packages/ai-parrot/src/parrot/mcp/local_cli.py:57-…  `parrot mcp-local NAME --config PATH [--include/--exclude] [--list]`
# root pyproject.toml:236  markers = ["asyncio: ...", "real_llm: mark a test as requiring a live LLM provider"]  (--strict-markers is on: only these two custom markers exist)
# pytest.ini:3 asyncio_mode = auto
```

### Does NOT Exist
- ~~A `host_smoke` / `integration` pytest marker~~ — `--strict-markers` is on; use `pytest.skip`/`skipif` with env vars, or register a marker in the package's own `pyproject.toml` only if you also add it there (prefer skipif).
- ~~`server.tools` as a list~~ — it is a dict name → `MCPToolAdapter`.
- ~~Driving Claude Code's hook runner headlessly~~ — not attempted; the hook is exercised directly and the settings schema is validated.
- ~~Live AWS in CI~~ — the real smoke test is opt-in via env vars and `real_llm` marker; CI never sets them.
- ~~The toolkit committing during the Git lifecycle~~ — commits are made by the test harness via subprocess.

---

## Implementation Notes

### Pattern to Follow
```python
# In-process protocol check
server = create_toolkit_mcp_server("local-git", root=repo, config_path=yaml_path)
assert all(isinstance(a.tool, AbstractTool) for a in server.tools.values())
listed = await server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
names = {t["name"] for t in listed["result"]["tools"]}
assert names == {"git_recent", "git_fetch", "git_preflight", "git_prepare_files", "git_pull", "git_push"}
prep = next(t for t in listed["result"]["tools"] if t["name"] == "git_prepare_files")
assert "confirm" in prep["inputSchema"]["required"]
```

```python
# Two-process contention driver (test_cross_process.py)
WORKER = """
import asyncio, sys, time
from pathlib import Path
from parrot_tools.tool_optimizations.git import LocalGitToolkit
repo, path, barrier = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
while not barrier.exists(): time.sleep(0.01)
res = asyncio.run(LocalGitToolkit(repo_root=repo).git_prepare_files([path]))
print(res.status, res.error.code if res.error else "")
"""
```

### Key Constraints
- Every `tools/call` in the raw-validation module goes through
  `_handle_request` (or the subprocess), never `toolkit.method(...)`.
- Evidence: every module writes to `artifacts/logs/`; the Completion
  Note lists the produced log files.
- The suite must pass offline; anything needing network/AWS/host
  binaries is skipped with an explicit reason string that names the env
  var to enable it.
- Do not raise the default timeouts to make tests pass — investigate.

### References in Codebase
- `tests/mcp/test_mcp_local_e2e.py` — subprocess JSON-RPC harness.
- `tests/mcp/test_adapter_confirm.py` — confirm-guard assertions.
- `packages/ai-parrot-tools/tests/tool_optimizations/conftest.py` (TASK-3080) — repo fixtures.

---

## Acceptance Criteria

- [ ] Three servers initialize/list/call in-process; the subprocess run of `bounded-source` produces only JSON-RPC lines on stdout.
- [ ] Every raw invalid `tools/call` case returns `isError: true` with no side effect.
- [ ] Git lifecycle passes in main tree and linked worktree; injected failures leave refs/files/index bytes unchanged.
- [ ] Writer lifecycle ends with the real `pytest` acceptance run exit code recorded in the log, separate from the manifest.
- [ ] Cross-process: both files staged, no lock deletion, no corruption; two applies → one `ok`, the other `already_applied`/`lock_timeout`.
- [ ] Client configuration test asserts the exact factory kwargs from the example YAML; `real_llm` smoke skipped by default.
- [ ] Host smoke writes `artifacts/logs/host-versions.txt` and `host-smoke.json`, skipping (not failing) when hosts are absent.
- [ ] Regression: `pytest tests/mcp packages/ai-parrot-tools/tests/tool_optimizations -q` green; `ruff` + `black --check` clean; logs in `artifacts/logs/TASK-3091-*.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py (excerpt)
import pytest
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

@pytest.mark.parametrize("name,tool,args", [
    ("local-git", "git_recent", {"limit": 999}),
    ("local-git", "git_recent", {"limit": 1, "bogus": True}),
    ("local-git", "git_prepare_files", {"paths": [], "confirm": True}),
    ("local-git", "git_prepare_files", {"paths": ["../x"], "confirm": True}),
    ("local-git", "git_prepare_files", {"paths": ["a.py"]}),            # missing confirm
    ("bounded-source", "source_read", {"path": "a.py", "start_line": 1}),
    ("targeted-writer", "writer_apply", {"artifact_id": "nope", "reviewed_sha256": "0" * 64, "confirm": True}),
])
async def test_raw_invalid_arguments_have_no_side_effects(tmp_repo_with_yaml, name, tool, args):
    repo, yaml_path = tmp_repo_with_yaml
    index_before = (repo / ".git" / "index").read_bytes()
    server = create_toolkit_mcp_server(name, root=repo, config_path=yaml_path)
    res = await server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    assert res["result"]["isError"] is True
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert not list((repo / "artifacts").glob("tool-optimizations/*")) if (repo / "artifacts").exists() else True
```

```python
# test_writer_lifecycle.py (excerpt)
async def test_generate_review_apply_then_real_tests(tmp_repo_with_yaml, monkeypatch):
    repo, _ = tmp_repo_with_yaml; task = make_valid_task(repo)   # fixture also writes tests/test_greeter.py into the temp repo
    writer = TargetedWriterToolkit(repo_root=repo, llm_client=FakeClient([GOOD_PATCH]))
    gen = await writer.writer_generate(task.relative_to(repo).as_posix()); assert gen.status == "ok"
    reader = BoundedSourceToolkit(repo_root=repo)
    hunks = await reader.source_read(gen.data["patch_path"], 1, 350); assert "@@" in hunks.content
    applied = await writer.writer_apply(gen.data["artifact_id"], gen.data["patch_sha256"]); assert applied.status == "ok"
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/test_greeter.py", "-q"], cwd=repo, capture_output=True, text=True)
    Path("artifacts/logs").mkdir(parents=True, exist_ok=True)
    Path("artifacts/logs/TASK-3091-writer-acceptance.log").write_text(proc.stdout + proc.stderr)
    assert proc.returncode == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3081, TASK-3082, TASK-3086, TASK-3087 and TASK-3089 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3091-integration-test-suite.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
