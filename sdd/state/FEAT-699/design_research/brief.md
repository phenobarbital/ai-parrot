<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
`sdd-worker` (merge tier, after every chunk merge), every `sdd-coder` seat
(task tier) and `/sdd-done` (feature tier re-run and lint-fix checks) each run
pytest through the FEAT-563 test-scope kernel. For a real feature the
accumulated cost is very large. `/sdd-done` for FEAT-698
(`feat-FEAT-698-sdd-brief-hotfix-flow`, 15 tasks, PR #1715) reported:

```
Suite      Tests   Passed  Failed  Skipped  Errors  Duration
ai-parrot  11096   10948   100     48       0       1302.67s
root       176     176     0       0        0       36.56s
Total (per-task invocation totals)  11272 ... 1339.24s
re-run skipped (15 tasks > 10)
```

**What actually happened (measured 2026-10-18, this brainstorm):** the full
suite was *never* run, and no escalation fired. Reproducing the plans on the
FEAT-698 tip (`d7e03cb93`) against its fork point (`49806c49f`) with
`python -m scripts.sdd.select_tests --tier merge|feature --no-ledger --json`:

| tier | escalated | core_hits | cap_hits | ai-parrot targets | ai-parrot tests collected |
|---|---|---|---|---|---:|
| merge (cumulative diff) | [] | [] | {} | 22 files/dirs (mirror + depth-1 import) | **2990** |
| feature | [] | [] | {} | 1 dir: `packages/ai-parrot/tests/flows/dev_loop` | **2562** |

None of FEAT-698's 47 changed files is in `CORE_PATHS`. The 11,096 figure is
the **sum of 15 per-chunk merge-tier runs** (≈740 tests / ≈87 s each) that
re-executed largely the *same* `flows/dev_loop` tests over and over. The
feature-tier plan picks a whole test *directory* because the mirror rule
(`mirror.deepest_existing_dir`) walks up to the deepest existing tests dir.

So the root causes are:

1. **Breadth by heuristic** — mirror (directory-level) + depth-1 import
   impact select thousands of tests that the feature's author never declared
   relevant. Nothing lets the spec say "these are the integration tests that
   matter for this feature".
2. **Redundancy across merges** — each merge re-runs tests whose test file and
   imported source are unchanged since a previous green run in the same
   feature. The FEAT-604 escalation ledger dedupes only *suite escalations*,
   not ordinary selected tests.
3. **Verdict noise** — ~100 tests are red on the `dev` baseline; they fail every
   merge and every feature run, so a red table does not mean the feature broke
   anything.
4. **No real safety net** — `.github/workflows/ci.yml` runs only the repo-root
   `tests/` (`--ignore=tests/tools`); **no `packages/*/tests` runs in CI at
   all**, and `e2e.yml` is nightly e2e only. Narrowing local selection without
   a net would hide regressions.

Affected: everyone running `sdd-worker` / `/sdd-done` (wall clock, tokens in
seat outputs, retry multipliers) and reviewers reading an always-red table.

### Constraints and goals
Decisions from discovery (2026-10-18):
  - Flow: `type: feature`, `base_branch: dev`.
  - The spec-declared set **replaces** heuristic escalation/breadth when present;
    full-suite runs move out of the local SDD loop.
  - Applies to **all** phases: task (`sdd-coder`), merge (`sdd-worker`),
    feature (`/sdd-done`), and `qa-runner` / autopilot QA.
  - Expressed as **both** explicit pytest paths/nodeids **and** optional markers.
  - Merge tier = the chunk's tasks' `## Validation Commands` ∪ the spec contract
    (no import-impact selection when a contract exists).
  - When a spec declares **no** contract: bounded fallback — tasks' own tests +
    file-level direct (depth-1) importers, **never** escalate to a whole suite;
    a note in the report says so.
  - **Dedupe across merges is in scope**: a test file already green in this
    feature, whose own blob and imported-source blobs are unchanged, is skipped.
  - **Baseline-aware verdict**: the gate fails only on tests that pass on
    `origin/<base_branch>` and fail on the branch (new reds).
  - Safety net: a **nightly full-suite workflow on `dev`** covering every
    `packages/*/tests`.
- Targets: merge-tier validation **< 2 min**, `/sdd-done` feature tier **< 5 min**.
- Decisions from spec kickoff (2026-10-18):
  - Contract lives in spec §4 as a `### Validation Contract` body subsection,
    cached by `/sdd-task` into the per-spec index header; the kernel reads only
    the index.
  - Baseline re-run happens in a temporary detached checkout of
    `origin/<base_branch>` with the compiled Cython `.so` copied from the main
    checkout (same mechanism as sub-worktrees); an unbuildable checkout ⇒
    *unknown*, treated as failure.
  - Explicit contract operands override the `integration`/`e2e` marker
    exclusions (declaring is the opt-in); `real_llm` stays excluded and is
    lint-flagged by `check_task_graph.py`.
- Deterministic, stdlib-only kernel (the `test_scope` package is imported by
  path from the system-python native hook — no Pydantic in `__init__`).
- Backward compatible: specs/task files written before this feature keep
  working (fallback path); the guard (`guard.py`) keeps rewriting broad pytest.
- Never run a full suite from an agent-issued command (unchanged FEAT-563 rule).

### Recommended option / probable scope
Recommendation:
**Option A, combined with Option B's cache**, plus two cross-cutting pieces the
discovery made mandatory: a baseline-aware verdict and a nightly full-suite net.

- A fixes **breadth** (the 2,990 / 2,562 plans) by letting the spec name what
  matters, and by demoting mirror to file level; B fixes **redundancy** (15×
  re-runs) with no author burden. Each alone misses a target: A without B still
  re-runs the contract every merge; B without A still pays ~3k tests on the
  first merge and the directory at closeout.
- C is the most precise but adds a stateful, opaque dependency that fights the
  multi-worktree + shared-venv setup; it stays a possible future replacement
  for the fallback heuristic, not for the contract.
- D is the cheap interim, but it misses the `/sdd-done` target and adds no
  signal quality.

What we trade off: local runs no longer prove "nothing else in the package
broke". That guarantee moves to the nightly full-suite workflow (new), which
today does not exist for `packages/*/tests` at all — so the net actually
*improves* coverage of package suites versus today, just later (≤ 24 h).

Option A: Spec-declared Validation Contract
Spec-declared Validation Contract (authoritative selection)

`/sdd-spec` gains a mandatory-but-skippable `### Validation Contract`
subsection in §4 (Test Specification) listing the feature's critical
integration tests as explicit pytest operands (`path` or `path::node`) plus
optional marker names. `/sdd-task` caches the contract into the per-spec index
header (like `type`/`base_branch`) and makes each task's `## Validation
Commands` reference its own tests. The kernel's `plan_tests()` gains a
`contract` input: when present, merge = chunk tasks' declared tests ∪
contract; feature = all tasks' declared tests ∪ contract; mirror is used only
at **file** level (a changed `foo.py` → an existing `test_foo.py`), never a
directory; no impact selection, no core/cap suite escalation. Without a
contract, the bounded fallback applies. `check_task_graph.py` lints that every
contract operand exists.

✅ **Pros:**
- Puts the decision where the knowledge is — the spec author knows which
  integration paths the feature touches.
- Deterministic, reviewable, diffable; plans shrink from thousands to
  tens/hundreds of tests.
- Same contract drives all four phases → one source of truth.

❌ **Cons:**
- Quality depends on the spec author; an under-declared contract silently
  narrows coverage (mitigated by the nightly net and file-level mirror).
- Does not remove re-execution of the same declared tests on every merge.
- Touches several command/agent docs (`sdd-spec`, `sdd-task`, `sdd-done`,
  `sdd-worker`, `qa-runner`) plus their `.agent/` twins.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pytest` | runner | 9.1.1 installed; `-m` marker expressions, nodeid operands |
| `pytest-xdist` | parallelism | 3.3.1 installed; only for `XDIST_SAFE_DISTRIBUTIONS` (ai-parrot is NOT in it) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` — `plan_tests()` tier entry point (extend with `contract`)
- `.../test_scope/contract.py` — `parse_validation_commands()`, `_pytest_operands()` (reuse to parse contract operands)
- `.../test_scope/mirror.py` — `pytest_target_for()` (restrict to file level)
- `scripts/sdd/check_task_graph.py` — `_check_validation_contract()` (extend to the spec contract)
- `sdd/templates/spec.md` §4 — add the subsection next to "Integration Tests"

Option B: Content-addressed green cache across merges
Content-addressed green cache across merges (dedupe)

Extend the FEAT-604 ledger idea from "suite escalations" to **every selected
test file**: after a green (or baseline-red-only) run, record per test file a
key = hash(test file blob, conftest chain blobs, blobs of the source modules
it imports at depth ≤ N via `ImportIndex`, marker expression, Python version).
On the next merge in the same feature, a selected test whose key matches is
skipped and reported as `cached`. Stored in the worktree git dir next to the
existing escalation ledger (`context.py`). No spec change.

✅ **Pros:**
- Directly removes the 15× re-execution measured on FEAT-698, whatever the
  selection rule is.
- Zero author burden; pure kernel change; reuses `ImportIndex` and blob helpers.

❌ **Cons:**
- Alone it does not shrink breadth: the first merge still runs ~3k tests, the
  feature tier still runs a directory.
- Key correctness matters: dynamic imports, fixtures in shared conftests, data
  files and env-driven behavior can invalidate a cache hit; depth bound is a
  tradeoff (FEAT-620 showed transitive closure saturates).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib `hashlib`, `json` | key + store | same style as `LedgerEntry.impacted_hash` |

🔗 **Existing Code to Reuse:**
- `.../test_scope/context.py` — `read_ledger()`, `record_green_escalation()`, `pending_escalations()`, `_blob()`, `_atomic_write_json()`
- `.../test_scope/impact.py` — `ImportIndex.load_or_build()`, `_expand_modules()`
- `.../test_scope/report.py` — `parse_junit()` (per-file outcome to decide what is green)

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py
scripts/sdd/select_tests.py
scripts/sdd/test_report.py
scripts/sdd/check_task_graph.py
.claude/commands/sdd-done.md
.claude/agents/sdd-worker.md
.claude/agents/qa-runner.md
.github/workflows/ci.yml
.github/workflows/e2e.yml
packages/ai-parrot/pyproject.toml
packages/ai-parrot/tests/conftest.py
tests/conftest.py
sdd/templates/spec.md

### Questions still open in the exploration document
- [ ] Should the `/sdd-done` feature tier bypass the green cache so the closeout table is a fresh end-to-end run of the contract? — *Owner: Jesus Lara*
- [ ] Once the feature tier is cheap, drop `RERUN_TASK_THRESHOLD` (> 10 tasks ⇒ skip) or raise it? — *Owner: Jesus Lara*
- [ ] Nightly new reds: open a GitHub issue, or write a `wikitoolkit ledger` issue (needs a commit from CI)? — *Owner: Jesus Lara*
- [ ] Should `/sdd-brief` (hotfix/fix briefs, FEAT-698) also carry an optional contract? — *Owner: Jesus Lara*
- [ ] Retry-once for flaky tests before classifying as new red? — *Owner: Jesus Lara*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
