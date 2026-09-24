---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wikitoolkit, claude-code, hook, performance, startup]
---

# Feature Specification: Lightweight wikitoolkit hook entry point

**Feature ID**: FEAT-595
**Date**: 2026-09-23
**Author**: Jesús Lara / Claude (via `/sdd-fix`)
**Status**: approved
**Target version**: next patch
**Source issue**: `issue:f0a40d0853f2` (ledger, `feature_gap`, minor), discovered from TASK-3569 (FEAT-584)

---

## 1. Motivation & Business Requirements

### Problem Statement

The Claude Code `PreToolUse` hook (`.claude/settings.json` → `<venv>/bin/wikitoolkit claude-hook`,
matcher `Grep|Glob|Read|Bash`) runs as a fresh Python process before **every** matching tool
call, so its startup cost is paid many times per turn. FEAT-584 AC23b set a warm-start target of
**p50 < 300 ms**; TASK-3569 measured **~415–425 ms** in the sandbox and documented that the cause
is the CLI/interpreter startup itself, not the ADR registration it deferred. Reaching the target
"requires a separate lightweight entry point" — this spec delivers it.

### Measured cost (dev `cbae68a28`, this machine, `python -X importtime`)

| Import | Cumulative |
|---|---|
| bare interpreter (`python -c pass`) | ~27 ms wall |
| `parrot.knowledge.wiki` (package + `parrot/__init__`) | ~9 ms |
| `pydantic` | ~29 ms |
| `parrot.knowledge.wiki.project` (pulls `decisions.models`, ~142 ms) | ~157 ms |
| `parrot.knowledge.wiki.claude_code.hook` (via `claude_code/__init__` → `installer`, and `repo_scan` → `languages`/`store`) | ~218 ms |
| `parrot.knowledge.wiki.cli` (what the console script imports first) | ~240 ms |

Findings:

1. The console script (`wikitoolkit = "parrot.knowledge.wiki.cli:main"`) imports the whole click
   CLI (~240 ms) before it can dispatch `claude-hook`.
2. `claude_code/__init__.py` eagerly imports `installer` (and through it `project`) — any import of
   `claude_code.hook` pays for the installer.
3. `hook.py` imports `repo_scan` only for the constants `CODE_SUFFIXES`/`DOC_SUFFIXES`; `repo_scan`
   imports `languages`, `store`, `symbols` (heavy).
4. `hook.py` imports `project` (pydantic + `decisions.models`) at module level, yet the most common
   hook payloads — `Bash` commands that are not searches (`git`, `ls`, `pytest`, …) and `Read` of
   non-source files — are rejected by pure-stdlib predicates that never need the config.

### Goals

- G1: `wikitoolkit claude-hook` warm start **p50 < 300 ms** on the common (prefilter-rejected)
  payload, measured over 20 warm fresh-process launches of the real console entry point.
- G2: The config-requiring path (`Grep`/`Glob`, search-like `Bash`, source-file `Read`) no longer
  imports the click CLI, the installer, or `repo_scan`; its p50/p95 are measured and reported.
- G3: Zero behavioural change: identical stdout protocol, identical nudge decisions, always exit 0.
- G4: No change to the installed hook command spelling — the three writers of the command
  (`claude_code/assets.hook_command`, `parrot_tools.tool_optimizations.installation.hook_command`,
  `flows/dev_loop/dispatchers/claude.py`) stay untouched.

### Non-Goals

- Rewriting `WikiProjectConfig` / `decisions.models` for import speed (config path keeps pydantic).
- Changing hook matchers, nudge text, throttle semantics or config schema.
- A native (non-Python) hook binary.

---

## 2. Architectural Design

### Overview

Retarget the `wikitoolkit` console script at a new, stdlib-only dispatcher module. When
`argv[1] == "claude-hook"` it calls the hook runtime directly; every other invocation falls through
to the existing click CLI unchanged. The hook runtime gains a stdlib-only prefilter that runs
**before** any config import, and its heavy imports become lazy.

```
<venv>/bin/wikitoolkit claude-hook
  └─ parrot.knowledge.wiki.entry:main           (stdlib only)
       ├─ argv == ["claude-hook"] → claude_code.hook.run_pre_tool_use_hook()
       │     ├─ json.load(stdin)
       │     ├─ prefilter (stdlib): event / Read suffix / Bash search-ness  → reject = exit 0, no config import
       │     └─ lazy import project → find_project_root / load_effective_config / is_built / throttle
       └─ otherwise → parrot.knowledge.wiki.cli:main()   (unchanged)
```

### Semantics preservation of the prefilter

`build_nudge` currently evaluates, all AND-ed: event is `PreToolUse`; project root exists;
`tool_name in config.claude.nudge_tools`; `config.is_built(root)`; for `Read` →
`_should_nudge_read`; for `Bash` → `_should_nudge_bash`; not throttled. The Read/Bash predicates
depend only on the payload, so evaluating them (and the event check) first yields exactly the same
decision set. Tools other than `Read`/`Bash` are never rejected by the prefilter (config may list
arbitrary tool names). Throttling stays last, so a rejected payload never consumes a nudge window.

### Modules

#### Module 1: `parrot/knowledge/wiki/file_suffixes.py` (CREATE)
Stdlib-only home for `CODE_SUFFIXES` and `DOC_SUFFIXES` (moved verbatim from `repo_scan.py`).
`repo_scan.py` re-imports them from here so `repo_scan.CODE_SUFFIXES is file_suffixes.CODE_SUFFIXES`
and every existing importer keeps working.

#### Module 2: `parrot/knowledge/wiki/claude_code/hook.py` (MODIFY)
- Suffix constants from `file_suffixes`, not `repo_scan`.
- `project` import (`WikiProjectConfig`, `find_project_root`, `load_effective_config`) moved inside
  `build_nudge` (and under `TYPE_CHECKING` for annotations).
- New stdlib predicate `_prefilter_rejects(payload) -> bool` evaluated at the top of `build_nudge`.
- `build_nudge` signature, return values and `run_pre_tool_use_hook` contract unchanged.

#### Module 3: `parrot/knowledge/wiki/claude_code/__init__.py` (MODIFY)
Replace the eager `installer` import with a PEP 562 `__getattr__` that lazily resolves the three
names in `__all__`; public API (`from parrot.knowledge.wiki.claude_code import install_claude_integration`)
unchanged.

#### Module 4: `parrot/knowledge/wiki/entry.py` (CREATE)
`main() -> None`: if `sys.argv[1:] == ["claude-hook"]`, `sys.exit(run_pre_tool_use_hook())` via a
local import of `claude_code.hook`; otherwise import and call `parrot.knowledge.wiki.cli.main`.
Module-level imports: stdlib only.

#### Module 5: `packages/ai-parrot/pyproject.toml` (MODIFY)
`wikitoolkit = "parrot.knowledge.wiki.entry:main"`. The `claude-hook` click subcommand in `cli.py`
stays (still reachable via `python -m parrot.knowledge.wiki.cli claude-hook` and `parrot claude hook`).

**Rollout note**: console-script shims are generated at install time. The new entry takes effect in
an existing venv only after the main-checkout operator re-runs the editable install
(`uv pip install -e packages/ai-parrot`); until then the old shim keeps working unchanged.

#### Module 6: tests
- `packages/ai-parrot/tests/knowledge/wiki/test_hook_prefilter.py` (CREATE): decision-equivalence
  table (prefilter + `build_nudge`) over Read/Bash/Grep/Glob/other payloads against a built fixture
  repo and an unbuilt one; `repo_scan` suffix identity; lazy `claude_code.__getattr__`.
- `packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py` (MODIFY): measure through
  `parrot.knowledge.wiki.entry` in fresh subprocesses; import-trace assertions that the hook path
  loads neither `parrot.knowledge.wiki.cli`, `claude_code.installer`, `repo_scan` nor (for a
  prefilter-rejected payload) `project`/`pydantic`; `entry` falls through to the CLI for
  `--help`; p50 on the prefilter path asserted `< 300 ms`, config path p50/p95 recorded to
  `artifacts/logs/hook_startup_benchmark.json` and warned (not failed) when ≥ 300 ms.

---

## 3. Acceptance Criteria

- [ ] AC1: `python -c "import parrot.knowledge.wiki.entry"` imports no `click`, `pydantic`, or
      `parrot.knowledge.wiki.cli` (import trace).
- [ ] AC2: A `claude-hook` run with a non-search `Bash` payload imports neither
      `parrot.knowledge.wiki.project`, `pydantic`, `parrot.knowledge.wiki.cli`,
      `claude_code.installer` nor `repo_scan`; stdout empty; exit 0.
- [ ] AC3: A `claude-hook` run with a `Grep` payload in a built fixture repo emits the same JSON
      nudge as before (byte-equal to the `python -m parrot.knowledge.wiki.cli claude-hook` output
      for a fresh throttle window) and does not import `parrot.knowledge.wiki.cli`,
      `claude_code.installer` or `repo_scan`.
- [ ] AC4: 20 warm fresh-process launches through `entry` on the prefilter path: p50 < 300 ms
      (hard assertion); cold + p95 reported; config-path p50/p95 reported.
- [ ] AC5: Decision equivalence: for every payload in the test table, `build_nudge` returns the
      same result as the pre-change logic (same inputs, same config, same clock).
- [ ] AC6: `wikitoolkit --help` / any non-hook subcommand via `entry.main` behaves exactly as
      `cli.main` (help text equal); `from parrot.knowledge.wiki.claude_code import
      install_claude_integration` still works; `repo_scan.CODE_SUFFIXES` is the same object as
      `file_suffixes.CODE_SUFFIXES`.
- [ ] AC7: Existing suites pass unchanged: `packages/ai-parrot/tests/knowledge/wiki/test_cli.py`,
      `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py`,
      `packages/ai-parrot-tools/tests/tool_optimizations/test_installation.py`.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| Prefilter drifts from the in-config checks | Prefilter reuses the exact same `_should_nudge_read/_bash` helpers; AC5 equivalence table |
| Timing assertion flaky on slow CI | Hard assert only on the prefilter path (expected ≪ 300 ms); config path is warn-only |
| Shim not regenerated in existing venvs | Old shim still valid; rollout note in §2 Module 5 and completion note |
| A hidden importer of `claude_code.<name>` relied on the eager `installer` import side effect | `__getattr__` resolves the same names; submodule imports are explicit everywhere (verified via grep during TASK) |

---

## 5. Open Questions

None — design decisions were made from the measurements in §1.
