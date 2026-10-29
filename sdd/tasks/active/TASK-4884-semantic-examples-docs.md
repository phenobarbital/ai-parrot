# TASK-4884: README and documentation for the semantic examples

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4880, TASK-4881, TASK-4882, TASK-4883
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7. It documents all four new examples, so it runs last. The
per-directory README merges the relocated example's README (moved by TASK-4877) with an
entry for each new example, **preserving its "For production, replace…" paragraph** — that
paragraph is the only place the repository tells an adopter how to swap
`ExamplePolicyEvaluator` for the navigator-auth `PolicyEvaluator`.

**The documentation's fenced blocks are an API (S6).** `test_mcp_local.py:32-50,78-107`
parses `docs/tools/semantic-layer.md` with uniqueness selectors:

- exactly **one** ```yaml block whose top-level key is `toolkits`
- exactly **one** ```yaml block starting `# orders.yml`
- exactly **one** ```yaml block starting `# orders.policy.yaml`
- every ```json block must parse, with `mcpServers` equal to exactly one entry

The file currently holds 3 yaml fences, 1 json fence and 1 bash fence. Adding a yaml or
json fence that matches any selector breaks those tests. The new section is therefore
**prose-only**, plus a ```bash fence if one is genuinely useful — bash is unconstrained.

---

## Scope

- Rewrite `examples/agents/semantic/README.md` to cover all five examples in the directory,
  preserving the relocated README's "For production, replace…" paragraph verbatim.
- Append a **prose-only** section to `docs/tools/semantic-layer.md` pointing at the
  examples and naming what each one proves.
- Add **no** yaml and **no** json fence to the doc.

**NOT in scope**: any example module or pin test (TASK-4880..4883 own them); the fixtures
(TASK-4878); `_common.py` (TASK-4879); editing any existing section of
`docs/tools/semantic-layer.md`; any change under `packages/ai-parrot-semantic/src/**`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/README.md` | MODIFY | Merge the relocated README with entries for the four new examples |
| `docs/tools/semantic-layer.md` | MODIFY | Append one prose-only section |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

Documentation only — this task writes no Python and adds no import.

### Existing Signatures to Use

```python
# packages/ai-parrot-semantic/tests/test_mcp_local.py:32-50 — the fence parser the doc must satisfy
_FENCE = re.compile(r"^```(?P<lang>[a-z]+)\n(?P<body>.*?)^```$", re.MULTILINE | re.DOTALL)
def _doc_blocks(lang: str) -> list[str]: ...
def _doc_yaml(first_line: str | None = None, *, key: str | None = None) -> str: ...
    # asserts EXACTLY ONE matching block; a second match fails the test
# test_mcp_local.py:78-107 — test_documented_yaml_and_json_parse / test_documented_model_loads_through_real_loader
```

Current fence census of `docs/tools/semantic-layer.md`, measured at `e00c8de82`:

```
3  ```yaml      (toolkits · # orders.yml · # orders.policy.yaml)
1  ```json      (mcpServers, exactly one entry)
1  ```bash      (unconstrained)
```

Edit site — the file has **157 lines** and `## MCP-local configuration` is its **last**
section, so the new section is **appended at the end of file**:

```
# occurrences: 1 (verified: grep -c '## MCP-local configuration' docs/tools/semantic-layer.md)
# anchor: `## MCP-local configuration` at docs/tools/semantic-layer.md:114 — the LAST heading
# file length at planning time: 157 lines; last line reads:
the configured PBAC guard binds the static identity around tool execution.
```

File digests at planning time (re-verify before editing):

```
7a475269bb1fd2b95eae5886c2f115fdec63aa1da2cca67b3e49213f805c5443  docs/tools/semantic-layer.md
8e2945401a662a8f2ed644c987177c199480a034d4e9c1c9586e75ee73e69ce9  examples/semantic/README.md   (pre-move; TASK-4877 moves and edits line 3)
```

The paragraph that must survive the merge, from the relocated README's final paragraph:

> For production, replace `ExamplePolicyEvaluator` with the navigator-auth
> `PolicyEvaluator` loaded from your PBAC policies, and configure connections through the
> host environment. Bind `PermissionContext` and `SemanticRequestIdentity` at the
> HTTP/MCP/Agent boundary, create facades through a per-owner host factory, and send
> semantic audit records to durable storage. Never attach raw DatasetManager tools after a
> semantic hand-off.

### Does NOT Exist

- ~~a second ```yaml block with top-level key `toolkits`~~ — adding one fails
  `test_documented_yaml_and_json_parse`. The same holds for a second `# orders.yml` or
  `# orders.policy.yaml` block.
- ~~a second ```json block~~ — every json block is parsed and must carry exactly one
  `mcpServers` entry; a second block that does not is a failure.
- ~~a cross-connection refusal to document~~ — the second connection demonstrates per-model
  **isolation**. Do not write that the layer refuses a cross-connection query; it does not
  implement such a check.
- ~~"the SQL as executed" as a description of `compile_query`~~ — it returns **pre-RLS**
  SQL (closed `issue:22fbd14d96a9`).
- ~~`reload()` as a way to drop an RLS rule~~ — it cannot (closed `issue:e3ff9bfb4a83`).
- ~~a claim that a governed cross-model join works~~ — spec AC12 forbids it; the governed
  path denies it and the README must say so plainly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/README.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/tools/semantic-layer.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- Prose-only in `docs/`. A ```bash fence is permitted (bash is unconstrained by the
  parser); yaml and json are not.
- Do not edit any existing section of `docs/tools/semantic-layer.md` — append only. The
  three yaml blocks and the one json block must stay exactly as they are.
- Run `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py -q` after the doc edit.
  It is the AC8 gate and it is the test that catches a stray fence.
- The README describes five files: the relocated example plus the four new ones. Each entry
  names what the example **proves**, not just what it does.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read the relocated `examples/agents/semantic/README.md` — *why*: TASK-4877 moved it and changed its line-3 run command; the merge starts from that version, not from the pre-move file.
2. Rewrite it with a per-example section, keeping the "For production, replace…" paragraph verbatim as the closing paragraph — *why*: it is the only production-handover guidance in the repository and spec §3 M7 requires it preserved.
3. Append the prose-only section to `docs/tools/semantic-layer.md` — *why*: spec §3 M7 and S6.
4. Count the fences again and run `test_mcp_local.py` — *why*: AC8; a stray yaml or json fence silently breaks four assertions.

### `examples/agents/semantic/README.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^# Semantic Agent example' examples/agents/semantic/README.md)
# REWRITE the whole file, keeping its final "For production, replace ..." paragraph verbatim.

# Governed Semantic Layer — example agents

Five runnable examples over one committed model fixture. Every example runs offline with
`--smoke`: no LLM call, no network, and nothing written outside a temporary directory.

| Example | What it proves |
|---|---|
| `agent_semantic_example.py` | The guarded dataset hand-off: a result is published and read only through a per-owner facade. |
| `llm_metrics_agent.py` | An LLM really drives the `sl_*` tools through `ask(permission_context=...)`; omitting either binding fails closed. |
| `mcp_local_agent.py` | The MCP-local path executes a real allow AND a real deny through `create_toolkit_mcp_server`. |
| `masked_policy_agent.py` | `masks:` redacts a projected column for roles that are not exempt, and `saved_queries:` runs a reviewed query by name. |
| `governed_joins_agent.py` | Time grains work; a governed cross-model query is DENIED; the same join compiles only under an explicitly ungoverned model. |

# FILL IN: a short "Fixtures" paragraph describing models/ and models_ungoverned/ and the
#          two named connections — bounded by: state that one policy side-file per model is
#          required, and that the second connection demonstrates per-model isolation, NOT a
#          cross-connection refusal.

# FILL IN: a "Run them" section with a ```bash fence listing the five commands and the
#          pytest invocations — bounded by: bash fences are unconstrained, but add no yaml
#          and no json fence anywhere in this feature.

For production, replace `ExamplePolicyEvaluator` with the navigator-auth `PolicyEvaluator` loaded from your PBAC policies, and configure connections through the host environment. Bind `PermissionContext` and `SemanticRequestIdentity` at the HTTP/MCP/Agent boundary, create facades through a per-owner host factory, and send semantic audit records to durable storage. Never attach raw DatasetManager tools after a semantic hand-off.
```
**Why this shape**: the table is the fastest way for an adopter to find the example that
matches their problem, and phrasing each row as what it *proves* is what keeps the README
honest about the governed-join denial (AC12). The production paragraph is reproduced
verbatim because it is load-bearing guidance that survived review `issue:f0da823294fb`.

### `docs/tools/semantic-layer.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '## MCP-local configuration' docs/tools/semantic-layer.md)
# APPEND at end of file (verified: docs/tools/semantic-layer.md has 157 lines; the
# `## MCP-local configuration` section at :114 is the last one).
# PROSE ONLY — no ```yaml and no ```json fence may be added (test_mcp_local.py:32-50).

## Example agents

Runnable examples live in `examples/agents/semantic/`, over one committed model fixture
and a DuckDB warehouse built at run time. Each has a `--smoke` mode that runs offline:
no LLM call, no network, nothing written outside a temporary directory. A pin test in
`packages/ai-parrot-semantic/tests/` keeps each one honest, and CI already runs them.

# FILL IN: one short paragraph per example — the LLM-driven catalog walk, the MCP-local
#          allow and deny, masking with saved queries, and grains with the governed
#          cross-model denial — bounded by AC12: say plainly that the governed path DENIES
#          a cross-model query and that the ungoverned model is the compiler surface, and
#          by S6: no yaml or json fence.
```
**Why**: the section is appended rather than inserted so no existing fence moves, and it is
prose because the parser's uniqueness selectors turn any new yaml or json block into four
failing assertions in `test_mcp_local.py` (AC8).

### FILL IN checklist
- [ ] `README.md` — the "Fixtures" paragraph; bounded by: one policy per model; the second connection is isolation, not a refusal.
- [ ] `README.md` — the "Run them" bash section; bounded by: bash only, no yaml/json fence.
- [ ] `semantic-layer.md` — one paragraph per example; bounded by AC12 and S6.

---

## Acceptance Criteria

- [ ] The README covers all five examples and preserves the "For production, replace…"
      paragraph verbatim (spec §3 M7).
- [ ] The appended doc section is prose-only: the file's yaml fence count is still 3 and its
      json fence count is still 1 (spec §7, S6).
- [ ] `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py` passes after the doc edit
      (spec AC8).
- [ ] No existing section of `docs/tools/semantic-layer.md` is modified.
- [ ] Nothing presents a cross-model join as a working governed query, a cross-connection
      refusal as a real behaviour, `compile_query` output as executed SQL, or `reload()` as
      a way to drop an RLS rule (spec AC12, §7).
- [ ] The only files this task changes are the two listed above (spec AC2).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q`

---

## Test Specification

No new test. `test_mcp_local.py` is the pin: its `test_documented_yaml_and_json_parse`
(`:78`) and `test_documented_model_loads_through_real_loader` (`:93`) both parse this doc's
fences with uniqueness selectors and are the gate for AC8. Before committing, confirm the
fence census by hand:

```bash
grep -c '^```yaml' docs/tools/semantic-layer.md   # must still print 3
grep -c '^```json' docs/tools/semantic-layer.md   # must still print 1
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above — especially §7 "The documentation's fences
   are an API"
3. **Check dependencies** — TASK-4880, TASK-4881, TASK-4882 and TASK-4883 must all be
   `"done"`; this task documents what they built, so read the four example modules first
4. **Verify the Codebase Contract** — re-run the two fence-count commands and re-read
   `test_mcp_local.py:32-50` before adding anything to the doc
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4884 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
