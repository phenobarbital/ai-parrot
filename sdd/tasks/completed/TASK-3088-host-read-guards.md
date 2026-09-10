# TASK-3088: Host read guards — PreToolUse policy for Claude Code and Codex (structured Read + shell subset)

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3079
**Assigned-to**: unassigned

---

## Context

Spec §2 "Host Guards and SDD Workflow" (paragraphs 1–3), §3 Module M7
(`hooks.py`), AC13 (policy half). The guard is a `PreToolUse` hook that
denies unbounded reads of large files and points the assistant to the
bounded reader tool with a valid range. It is **opt-in**, uses the same
thresholds as the MCP reader, and covers only a documented subset;
unrecognised forms make no decision. Missing hooks never weaken the MCP
reader's own limits (TASK-3082).

Verified host contracts (fetched 2026-09-10; re-check against the
installed versions — locally `claude 2.1.267`, `codex-cli 0.154.0`):

- **Claude Code** (https://code.claude.com/docs/en/hooks): stdin JSON has
  `hook_event_name`, `tool_name`, `tool_input` (`Read`: `file_path`,
  optional `offset`/`limit`; `Bash`: `command`), `cwd`. Deny by printing
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`
  and exiting 0. Exit 2 also blocks (stderr = reason). Other non-zero
  exit codes are ignored. `matcher` is a regex/pipe list of tool names.
- **Codex** (https://learn.chatgpt.com/docs/hooks): hooks live in
  `<repo>/.codex/hooks.json` (or `~/.codex/hooks.json` / `config.toml`);
  same `hookSpecificOutput.permissionDecision` deny shape (legacy
  `{"decision": "block", "reason"}` also accepted); supported tools
  `Bash`, `apply_patch` (aliased Edit/Write), MCP tools; feature flag
  `[features] hooks = true` (default true); **`write_stdin` does not
  re-run `PreToolUse`** and hosted tools are not hookable — both are
  documented coverage gaps.

The existing wiki nudge hook (`parrot/knowledge/wiki/claude_code/hook.py`)
is the in-repo precedent for a stdin→stdout hook that never crashes the
session and parses simple shell commands.

**Decisions fixed here:**

1. Runtime entry point: `python -m parrot_tools.tool_optimizations.hooks --host claude|codex`
   (module `__main__` guard). The installer (TASK-3089) writes the
   absolute venv python path. No new console script, no CLI group.
2. Thresholds come from `<repo>/.parrot/tool-guards.json`
   (`{"max_lines": 350, "large_file_bytes": 64000, "reader_server": "parrot-bounded-source", "tool": "source_read"}`),
   written by the installer from the `bounded-source` section's kwargs;
   defaults apply when the file is missing. The hook must stay
   **stdlib-only at import** (no pydantic, no `parrot.*` imports) so it
   runs in < 100 ms.
3. Intercepted forms (v1): Claude `Read` (`file_path`, honour a `limit`
   ≤ `max_lines` as bounded); shell `cat`, `head`, `tail`, `less`, `more`
   with literal file operands. Bounded flags: `head -n N`/`-N`/`-c N`,
   `tail -n N`/`-N`/`-c N` with `N ≤ max_lines` (or bytes ≤
   `large_file_bytes`). Pipelines (`|`) are parsed segment by segment;
   the reading segment decides — a pipe never makes a large read safe.
   Any of `;`, `&&`, `||`, `$(`, backtick, `<`, `>`, `>>`, newline, `&`,
   glob characters, `$VAR`, `~user`, heredoc, or an unrecognised program
   → no decision (exit 0, no output).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py`
  (stdlib only: `json, os, re, shlex, sys, stat, pathlib, dataclasses, argparse`):
  - `@dataclass(frozen=True) class GuardPolicy`: `max_lines=350`,
    `large_file_bytes=64000`, `reader_server="parrot-bounded-source"`,
    `tool="source_read"`; `classmethod load(root: Path) -> GuardPolicy`
    reading `.parrot/tool-guards.json` (any error → defaults).
  - `@dataclass class GuardDecision`: `deny: bool`, `reason: str = ""`,
    `path: str | None`, `lines: int | None`, `size: int | None`,
    `coverage: Literal["structured", "shell", "unrecognized", "not_applicable"]`.
  - `def count_lines_bounded(path: Path, stop_after: int) -> tuple[int, bool]`
    — duplicate of TASK-3082's helper (documented copy; keeping the hook
    import-light beats sharing 20 lines; a test asserts both
    implementations agree on the fixtures).
  - `def is_large(path: Path, policy) -> tuple[bool, int | None, int]`:
    regular file only (`os.stat`, follow symlinks is fine here — the host
    already resolved the path), returns `(large, line_count_or_None, size)`.
  - `def evaluate_read(tool_input: dict, cwd: Path, policy) -> GuardDecision`
    (Claude `Read`): resolve `file_path` (absolute or relative to `cwd`);
    non-existent / non-regular → `not_applicable`; `limit` present and
    `≤ max_lines` → allow (no decision); else deny when large.
  - `def parse_shell_subset(command: str) -> list[list[str]] | None`:
    reject on any Decision-3 character before `shlex.split(posix=True)`;
    split on `|` tokens into segments; return `None` for anything
    unrecognised.
  - `def evaluate_shell(command: str, cwd: Path, policy) -> GuardDecision`:
    find the first segment whose argv[0] basename ∈ {cat, head, tail,
    less, more}; extract file operands (non-dash tokens; `-` stdin →
    `not_applicable`); multiple files → evaluate each, deny on the first
    large one; bounded flags per Decision 3 → allow.
  - `def build_reason(decision, policy) -> str`:
    `"<path> is <N> lines / <S> bytes (> 350 lines or 64,000 bytes). Use the bounded reader instead: MCP server '<reader_server>' tool '<tool>' with {\"path\": \"<relative path>\", \"start_line\": 1, \"end_line\": 350}; continue with the returned next_line and expected_sha256."`
    (relative to `cwd` when inside it).
  - `def render_output(decision, host) -> str | None`: Claude and Codex
    both get the `hookSpecificOutput` JSON (Codex also accepts it per
    the doc); `None` when no decision.
  - `def main(argv=None, stdin=sys.stdin, stdout=sys.stdout) -> int`:
    parse `--host`, read JSON from stdin, dispatch on `tool_name`
    (`Read` → structured; `Bash` → shell; anything else → 0 with no
    output), print output, return 0. **Any exception → return 0 with
    no output** (never break the session). `if __name__ == "__main__": sys.exit(main())`.
  - `def coverage_matrix() -> list[dict]`: the machine-readable table of
    covered / not-covered forms used by docs (TASK-3092) and tests:
    each row `{"form": "...", "covered": bool, "note": "..."}` — include
    `sed -n`, `awk`, `python -c open().read()`, heredocs, `xargs cat`,
    Codex `write_stdin`, `Grep`, `Glob`, `WebFetch` as NOT covered.
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py`
  — drive `main()` with `io.StringIO` payloads for both hosts; fixtures
  generate a 400-line file and a 100-line file.

**NOT in scope**: writing `settings.json` / `hooks.json` (TASK-3089);
docs page (TASK-3092).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py` | CREATE | Guard policy, parsers, decision rendering, `main` |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py` | CREATE | Host payload tests + coverage matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# stdlib only inside hooks.py. Tests may import:
from parrot_tools.tool_optimizations.hooks import GuardPolicy, GuardDecision, evaluate_read, evaluate_shell, parse_shell_subset, main, coverage_matrix
from parrot_tools.tool_optimizations.reader import count_lines_bounded as reader_count   # TASK-3082 (for the agreement test)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py — precedent (read, do not import)
#   :1-20  design constraints: never blocks (nudge only), any error exits 0, throttled, dependency-light
#   :48-52 _should_nudge_read(tool_input) reads tool_input["file_path"]
#   :73-90 _leading_exe(tokens) skips VAR=value and wrappers (sudo/command/time/nice/xargs/env)
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
HOOK_COMMAND = "wikitoolkit claude-hook"   # :33
HOOK_MATCHER = "Grep|Glob|Read|Bash"       # :39
# .claude/settings.json — this repo already has PreToolUse entries with matcher "Grep|Glob|Read|Bash" (wiki nudge)
#   and "Bash|Edit|Write|MultiEdit" (.claude/hooks/dangerous-actions-blocker.sh) — the guard is a THIRD, independent entry.
```

### Does NOT Exist
- ~~`parrot tool-guard` CLI command~~ — not created; entry is `python -m parrot_tools.tool_optimizations.hooks`.
- ~~Codex `Read` tool~~ — Codex reads through shell; only `Bash`-shaped payloads apply there. Do not assume a `tool_input.file_path` on Codex.
- ~~`.parrot/tool-guards.json`~~ — created by TASK-3089's installer; the hook tolerates its absence.
- ~~Executing the command to inspect it~~ — parsing only (spec: "do not execute commands to inspect them").
- ~~Guarding `Grep`/`Glob`~~ — out of scope; matcher for the guard entry (TASK-3089) is `Read|Bash`.
- ~~A blocking decision for unrecognised shell forms~~ — no decision; normal host behaviour (spec).

---

## Implementation Notes

### Pattern to Follow
```python
_UNSAFE = re.compile(r"[;&<>`$*?\[\]{}~\n]|\|\||&&")     # any hit → unrecognised (pipes handled separately)
_READERS = frozenset({"cat", "head", "tail", "less", "more"})

def parse_shell_subset(command: str) -> list[list[str]] | None:
    if _UNSAFE.search(command.replace("||", ";")):
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    segments, cur = [], []
    for tok in tokens:
        if tok == "|": segments.append(cur); cur = []
        else: cur.append(tok)
    segments.append(cur)
    return segments if all(segments) else None

def _bounded(argv: list[str], policy: GuardPolicy) -> bool:
    prog = os.path.basename(argv[0])
    if prog not in {"head", "tail"}: return False
    for i, tok in enumerate(argv[1:], 1):
        m = re.fullmatch(r"-(\d+)", tok)
        if m: return int(m.group(1)) <= policy.max_lines
        if tok in ("-n", "--lines") and i + 1 < len(argv) and argv[i + 1].isdigit(): return int(argv[i + 1]) <= policy.max_lines
        if tok in ("-c", "--bytes") and i + 1 < len(argv) and argv[i + 1].isdigit(): return int(argv[i + 1]) <= policy.large_file_bytes
    return False   # head/tail without a bound default to 10 lines — treat as bounded ONLY when no file is large? No: bare `head f` is 10 lines → bounded=True
```
(Refine: bare `head file`/`tail file` default to 10 lines → bounded.)

```python
def main(argv=None, stdin=sys.stdin, stdout=sys.stdout) -> int:
    try:
        args = _parse_args(argv); payload = json.load(stdin)
        cwd = Path(payload.get("cwd") or os.getcwd()); policy = GuardPolicy.load(cwd)
        tool = payload.get("tool_name"); ti = payload.get("tool_input") or {}
        decision = evaluate_read(ti, cwd, policy) if tool == "Read" else evaluate_shell(str(ti.get("command", "")), cwd, policy) if tool == "Bash" else None
        out = render_output(decision, args.host) if decision else None
        if out: stdout.write(out); stdout.flush()
    except Exception:  # noqa: BLE001 — never break the host session
        pass
    return 0
```

### Key Constraints
- Import time budget: `python -X importtime -m parrot_tools.tool_optimizations.hooks` must not import pydantic/parrot core (test with subprocess and `sys.modules`).
- The deny reason must name the reader server, tool, and a valid range.
- Never read the file contents into memory; only count newlines / stat.
- Do not throttle denials (unlike the nudge) — a denial is a hard limit.
- Keep `coverage_matrix()` in sync with docs; TASK-3092 renders it.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py` — full precedent.
- `.claude/hooks/dangerous-actions-blocker.sh` — the repo's existing Bash deny hook (shape of a blocking hook in this project).

---

## Acceptance Criteria

- [ ] Claude `Read` of a 400-line file → deny JSON with server/tool/range in the reason; with `limit: 200` → no output; 100-line file → no output.
- [ ] Bash `cat big.py` → deny; `head -n 50 big.py` → no output; `head -400 big.py` → deny; `tail -c 1000 big.py` → no output; `cat big.py | head -20` → deny (pipe not safe); `cat small.py` → no output.
- [ ] `cat big.py; rm x`, `cat $(echo big.py)`, `cat *.py`, `sed -n '1,500p' big.py`, `python -c "open('big.py').read()"` → no output (coverage gaps, exit 0).
- [ ] Non-JSON stdin, missing file, directory path, unknown tool → exit 0, no output.
- [ ] Codex host: same Bash payload → same deny JSON; no `Read` handling assumed.
- [ ] `.parrot/tool-guards.json` with `max_lines: 100` changes the verdict for a 200-line file.
- [ ] Hook module import does not load `pydantic` or `parrot` core (subprocess assertion).
- [ ] `count_lines_bounded` agrees with `reader.count_lines_bounded` on 349/350/351-line and no-final-newline fixtures.
- [ ] `coverage_matrix()` lists every form tested above with the correct `covered` flag.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py -v`; lint clean; log in `artifacts/logs/TASK-3088-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py
import io, json, subprocess, sys
from pathlib import Path
import pytest
from parrot_tools.tool_optimizations.hooks import main, coverage_matrix

@pytest.fixture
def files(tmp_path):
    big = tmp_path / "big.py"; big.write_text("\n".join(f"x{i}" for i in range(400)) + "\n")
    small = tmp_path / "small.py"; small.write_text("\n".join(f"x{i}" for i in range(100)) + "\n")
    return tmp_path, big, small

def run(host, payload):
    out = io.StringIO(); rc = main(["--host", host], stdin=io.StringIO(json.dumps(payload)), stdout=out)
    return rc, out.getvalue()

def test_read_large_denied(files):
    root, big, _ = files
    rc, out = run("claude", {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": str(big)}, "cwd": str(root)})
    d = json.loads(out)["hookSpecificOutput"]
    assert rc == 0 and d["permissionDecision"] == "deny" and "source_read" in d["permissionDecisionReason"] and '"end_line": 350' in d["permissionDecisionReason"]

def test_read_with_limit_allowed(files):
    root, big, _ = files
    assert run("claude", {"tool_name": "Read", "tool_input": {"file_path": str(big), "limit": 200}, "cwd": str(root)}) == (0, "")

@pytest.mark.parametrize("cmd,denied", [
    ("cat big.py", True), ("head -n 50 big.py", False), ("head -400 big.py", True), ("tail -c 1000 big.py", False),
    ("cat big.py | head -20", True), ("cat small.py", False), ("cat big.py; rm x", False), ("cat $(echo big.py)", False),
    ("cat *.py", False), ("sed -n '1,500p' big.py", False), ("less big.py", True), ("more small.py", False),
])
def test_shell_subset(files, cmd, denied):
    root, *_ = files
    rc, out = run("codex", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(root)})
    assert rc == 0 and (bool(out) is denied)

def test_garbage_never_fails():
    out = io.StringIO(); assert main(["--host", "claude"], stdin=io.StringIO("not json"), stdout=out) == 0 and out.getvalue() == ""

def test_import_is_light():
    code = "import sys, parrot_tools.tool_optimizations.hooks; print(any(m.startswith(('pydantic','parrot.')) for m in sys.modules))"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip() == "False"

def test_coverage_matrix_mentions_gaps():
    forms = {row["form"]: row["covered"] for row in coverage_matrix()}
    assert forms["sed -n"] is False and forms["cat FILE"] is True and forms["codex write_stdin"] is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3079 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3088-host-read-guards.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Created `hooks.py` (stdlib-only) with `GuardPolicy`, `GuardDecision`,
`evaluate_read`, `evaluate_shell`, `parse_shell_subset`, `build_reason`,
`render_output`, `coverage_matrix` and `main`. 54 tests in
`test_hooks.py`, 273 across the feature suite.

**A real parsing bug found by the coverage-gap tests.** `cat big.py || true`
was being *denied* instead of ignored. `shlex.split` returns `||` as a
single token, not two `|` separators, so the segment splitter (which only
matched a token equal to `"|"`) treated `||` as an ordinary operand of
`cat` — swallowing a compound statement into the parsed subset. Any token
*containing* a pipe that is not exactly `"|"` now aborts parsing. This
mattered: the guard's honesty depends on never claiming to understand a
command it does not, and a compound statement is exactly the case where a
confident-looking decision would be wrong.

Properties the tests pin:

- **A pipe never makes a large read safe**: `cat big.py | head -20` is
  denied, because the *reading* segment decides.
- **Coverage gaps produce silence, never a denial** — 14 parametrized
  forms (`;`, `&&`, `||`, command substitution, globs, redirection, `sed`,
  `awk`, `python -c`, `xargs`, `~`, `$VAR`) all yield empty output.
- **`test_coverage_matrix_is_honest_and_complete`** cross-checks the
  published matrix against the behaviour the other tests demonstrate: every
  form asserted as a gap above must appear with `covered: False`. This is
  what stops the matrix drifting into a false claim of enforcement.
- **The guard can never break a session**: malformed JSON, empty payloads,
  missing files, directories and unknown tools all exit 0 with no output,
  and `main()` returns 0 unconditionally.
- **Import weight is enforced by a subprocess assertion**: importing the
  module loads neither `pydantic` nor any `parrot.*` module.
- **The duplicated `count_lines_bounded` is held to the reader's
  behaviour** by a parametrized agreement test (0/1/349/350/351 lines plus
  a no-final-newline fixture), so the documented copy cannot drift.
- Bare `head FILE` / `tail FILE` are treated as bounded (10-line default),
  while `head -400` is denied.

**Testing**: 273 tests pass; ruff and black clean. Log at
`artifacts/logs/TASK-3088-pytest.log`.

**Deviations from spec**: none. Note the host versions in the task's
Context (`claude 2.1.267`, `codex-cli 0.154.0`) were not re-verified
against live binaries here — this task implements and unit-tests the
policy; pinning and recording installed host versions is TASK-3091's
host-smoke work.
