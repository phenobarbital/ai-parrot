---
id: F002
query_id: Q002
type: read
intent: Verify python_repl current state and in-tree modifications
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F002 — python_repl is now a DENYLIST gate (diverges from allowlist design)

## Summary
The committed work (commit `0f76129b1`) hardened `python_repl` but as a
**denylist**, the opposite of the brainstorm's allowlist-first thesis (§3.3).
`BLOCKED_IMPORTS` is now populated (os, socket, subprocess, builtins, pathlib,
requests, urllib, …); `BLOCKED_NAMES` (eval, exec, open, globals, locals, vars,
__import__, …) and `BLOCKED_ATTRIBUTES` added. `_check_ast_security(tree)` walks
the AST and rejects nodes **on the block lists**; anything not listed passes.
Output is scrubbed via `_redact_execution_output → redact_text`. Exec stays
in-process (`run_in_executor(None, self._execute_code, …)`). No
`PythonCodeSanitizer`/`PythonExecutionPolicy` classes, no allowlist, no
`SecurityLevel` reuse.

## Citations
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 106-143
  symbol: `BLOCKED_IMPORTS, BLOCKED_NAMES, BLOCKED_ATTRIBUTES`
  excerpt: |
    BLOCKED_IMPORTS = {"builtins","ctypes",...,"os","pathlib",...,"subprocess","sys",...}
    BLOCKED_NAMES = {"__builtins__","__import__","compile","eval","exec","open",
                     "globals","locals","vars",...}
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 504-525
  symbol: `_check_ast_security, _redact_execution_output`
  excerpt: |
    def _check_ast_security(self, tree):  # DENYLIST: reject if root in BLOCKED_*
        for node in ast.walk(tree): ...   # else allow
    def _redact_execution_output(self, output): return redact_text(output)
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 43, 766-783
  symbol: `sanitize_input, _execute`
  excerpt: |
    async def _execute(...): return await loop.run_in_executor(None, self._execute_code, code, debug)

## Notes
Denylist closes the *known* incident vector (os.environ blocked) but not the
*arbitrariness* class the brainstorm targets. No allowlist, no profiles, no
PythonExecutionPolicy. This is the central WS1 gap.
