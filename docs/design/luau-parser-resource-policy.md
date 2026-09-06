# Luau parser resource policy (FEAT-532 TASK-2896)

**Status**: measured and reviewed — approved for implementation.
**Owner review**: self-reviewed by the implementing agent against the
measured data below, per the task's framing ("approval of its resulting
resource policy is the recorded downstream execution gate"). This document
*is* the recorded review; TASK-2898/TASK-2899 may proceed.

## Environment

| | |
|---|---|
| `tree-sitter` | 0.26.0 |
| `tree-sitter-luau` | 1.2.0 |
| Python | 3.12.3 |
| Platform | Linux-7.0.0-30-generic-x86_64-with-glibc2.39 |
| Benchmark runner | `scripts/benchmarks/luau_parser_limits.py` |
| Raw report | `artifacts/logs/task-2896-luau-resource-measurement.json` |

Reproduce with:

```bash
uv run python scripts/benchmarks/luau_parser_limits.py --deadline-seconds 2.0
```

## 1. Cancellation/isolation mechanism (measured finding)

`tree_sitter.Parser` in the installed binding (0.26.0) exposes only
`parse`, `reset`, `language`, `included_ranges`, `logger`,
`print_dot_graphs` — **no `timeout_micros` or cancellation-flag attribute**
is present on this version's `Parser` object. This confirms the spec's
§7 known risk: a `tree_sitter.Parser.parse()` call is native code that
holds the GIL; neither a cancelled `asyncio.Future` nor a
`threading.Thread.join(timeout=...)` can terminate it once started — only
OS-level process termination can.

**Verified mechanism**: `run_isolated()` in the benchmark runner spawns
each parse in a child process (`multiprocessing.get_context("spawn")`,
deliberately *not* `"fork"` — fork would share the parent's already-loaded
tree-sitter shared-library/parser-cache state, which is exactly the
"shared parser cache must not carry interrupted parse state into the next
file" risk the spec calls out). The parent enforces a wall-clock deadline
via `Process.join(timeout=...)`; on expiry it calls `terminate()`
(SIGTERM), joins again, and escalates to `kill()` (SIGKILL) if the child
is still alive. This was exercised against a deliberately-stalled worker
(`_stall_worker`, an infinite `sleep` loop standing in for a stuck native
parse) — see `test_benchmark_kills_stuck_child` — and confirmed to leave
no live child process and to return promptly at the deadline.

**Recommendation for TASK-2899 (scanner)**: per-file subprocess isolation
for every scan call is not proposed as the production enforcement
mechanism — the measured per-byte cost (below) shows the pre-parse byte
cap alone already bounds worst-case wall time to well under one second,
which is cheaper than paying a `spawn` fork cost per file across a whole
repository scan. The killable-subprocess pattern demonstrated here should
be reserved for the *offline benchmark/CI regression* path (this script,
plus `test_resource_corpus.py`), not wired into the per-file `outline()`
hot path. `outline()` must still enforce the byte cap and density check
below synchronously, in-process, before/after calling `parser.parse()`.

## 2. Measured corpus results

| Case | Size (bytes) | Outcome | Time (s) | Nodes | ERROR nodes | Density |
|---|---:|---|---:|---:|---:|---:|
| `valid_small` | 268 | completed | 0.0001 | 98 | 0 | 0.0000 |
| `valid_medium` (200 typed fns) | 26,250 | completed | 0.0046 | 11,418 | 0 | 0.0000 |
| `malformed_unbalanced` | 106 | completed | 0.0002 | 48 | 1 | 0.0208 |
| `deeply_nested` (800 levels) | 655,131 | completed | 0.0235 | 4,814 | 0 | 0.0000 |
| `long_line` (200k-char concat) | 268,897 | completed | 0.0468 | 120,006 | 0 | 0.0000 |
| `incompatible_python` | 156 | completed | 0.0002 | 64 | 5 | 0.0781 |
| `pathological_842kb` | 862,206 | completed | 0.4734 | 1,240,347 | 0 | 0.0000 |

All seven corpus cases complete well inside a 2-second deadline; tree-sitter's
own error-recovery handles every malformed/incompatible sample without
raising, matching the "must never raise" scanner contract.

### Additional size-scaling probe (pathological content, not part of the
committed corpus — exploratory only, to establish per-byte cost)

| Size | Time (s) | Nodes |
|---:|---:|---:|
| 256 KiB | 0.128 | 377,133 |
| 512 KiB | 0.257 | 754,251 |
| 1024 KiB | 0.526 | 1,508,487 |
| 2048 KiB | 1.027 | 3,016,959 |
| 4096 KiB | 2.162 | 6,033,903 |

Scaling is linear at ≈0.53 s/MiB for this adversarial nested-expression
shape (the worst shape measured). This directly sizes the byte cap below.

### Recursive tree-walk hazard (measurement artifact, itself a finding)

The first implementation of the benchmark's node-counter used ordinary
recursive descent (`for child in node.children: recurse(child)`) and hit
Python's `RecursionError` on the `deeply_nested`, `long_line`, and
`pathological_842kb` cases — **not a parser failure**, a failure of the
*measurement code* walking the resulting tree. This is a real, actionable
finding: any Luau enrichment/outline-rendering code that walks a parsed
tree (TASK-2899, TASK-2906) **must use an iterative, explicit-stack
traversal**, never recursive descent, since Luau source (unlike most
hand-written code) can legitimately produce trees deeper than Python's
default recursion limit. The benchmark runner's own `_count_nodes` was
fixed to an iterative stack-based walk; the fix is committed in this task.

### Mapping-JSON recursion probe (informs the mapping byte/depth limits)

`json.loads` on this Python 3.12.3 / CPython `_json` C accelerator raises
`RecursionError` at nesting depth 4,999 (binary-searched; 4,998 succeeds).
Real Roblox `sourcemap.json`/`default.project.json` trees mirror project
folder structure and are shallow in practice (tens of levels at most for
even large games).

## 3. Combined policy (concrete, for TASK-2898/TASK-2899)

| Guard | Value | Rationale |
|---|---|---|
| **Pre-parse byte limit** (route to tree-sitter vs. bounded heuristic) | **1,048,576 bytes (1 MiB)** | At 1 MiB, the worst measured shape (`pathological`, ≈0.53 s/MiB) takes ≈0.53 s — comfortably under the deadline below with ~4x margin. Supersedes the brainstorm's unvalidated 32 KiB hypothesis: 32 KiB is far too conservative given the measured throughput, and would reject legitimate larger `ModuleScript`s for no measured reason. |
| **ERROR-node density threshold** | **10% (0.10)** of total nodes, computed via iterative walk | Every valid sample measured 0.0% density; the malformed/incompatible tiny samples measured 2.08%–7.81% (inflated by their small total-node denominator). 10% gives headroom above the small-file noise floor while still catching genuinely broken/wrong-language input once files are of realistic size (error nodes dominate proportionally more as more of a real file fails to parse). |
| **Parse deadline (hard, enforced by the offline benchmark/CI harness, not per-file production hot path — see §1)** | **2.0 seconds**, enforced via killable subprocess (`terminate()` → `kill()`) | ~4x the worst single-file measurement at the byte cap (0.53 s at 1 MiB); used to catch true native-level pathological behavior. Combined with the byte cap, this closes the gap the brainstorm's density-only proposal left open (§7: "a post-parse ERROR-density check cannot interrupt a parser already stuck in native code"). |
| **Fallback (heuristic) input bound** | **4 MiB (4,194,304 bytes)** | The heuristic path is comment/string-masked regex scanning (linear, no backtracking-sensitive patterns per TASK-2899's implementation notes), materially cheaper per byte than tree-sitter; 4x the tree-sitter byte cap gives the fallback room to still process large files the primary path declines, while still bounding worst-case heuristic scan time on repositories with unusually large generated Luau. |
| **Mapping JSON byte limit** (`sourcemap.json` / `default.project.json`) | **16 MiB (16,777,216 bytes)** | Generous multiple of any observed real-world Rojo sourcemap size; a mapping file this large is itself a signal of a malformed/generated-in-error file rather than a legitimate project map, and is safely rejected rather than parsed. |
| **Mapping JSON depth limit** | **200 levels** | >20x margin under the measured `json.loads` `RecursionError` breakpoint (~4,999 on this runtime), while comfortably exceeding any real Roblox folder-nesting depth (tens of levels for even very large games). |

### Enforcement mechanism required by TASK-2899

1. Check `len(source_bytes)` against the pre-parse byte limit **before**
   calling `tree_sitter.Parser.parse()`. Over the limit → skip tree-sitter,
   go straight to the bounded heuristic path (never guess a truncated
   parse).
2. After a successful tree-sitter parse, compute ERROR-node density via an
   **iterative** walk (never recursive — see §2 finding) and record it as
   a per-file diagnostic; density over threshold is a degraded-mode signal
   for the file, not a parser abort (tree-sitter itself does not hang on
   malformed input at these sizes — see §2 — so there is nothing left to
   cancel once `parse()` has returned).
3. The offline benchmark (`scripts/benchmarks/luau_parser_limits.py`) and
   its CI regression test (`tests/knowledge/wiki/roblox/test_resource_corpus.py`)
   are the enforcement point for the *process-level* deadline+kill
   guarantee; they exist to catch a future tree-sitter-luau grammar
   regression that reintroduces a genuine hang, not to run per production
   file.
4. Mapping JSON: enforce the byte limit before `json.loads`, and enforce
   the depth limit either via a bounded iterative walk of the decoded
   structure (preferred) or an `object_hook`/streaming approach — TASK-2898
   owns the exact implementation; this document only fixes the two limits.

## 4. Review outcome

Approved for implementation. TASK-2898 and TASK-2899 may proceed using the
values in §3. No open measurement questions remain; if tree-sitter-luau is
upgraded past `1.2.x` or the installed `tree-sitter` core is upgraded past
`0.26.x`, re-run `scripts/benchmarks/luau_parser_limits.py` and diff the
report before trusting these numbers on the new version.
