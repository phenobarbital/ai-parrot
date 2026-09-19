# SDD LSP research pilot (FEAT-580)

Optional Python semantic evidence — go-to-definition, find-references, and
saved-edit diagnostics — for SDD research/coding/review CLI seats, exposed
through the existing local MCP toolkit mechanism as `parrot_tools.lsp.toolkit.LSPToolkit`.

This is a **research pilot**, not a general capability. It stays opt-in
until the approved 12-task / 3-repetition / five-arm evaluation (spec
`sdd/specs/sdd-research-lsp.spec.md` §2 "Evaluation contract") reaches a
`go` decision. The brainstorm's reported 13% cost / 12% token / 24% call
reductions are workload-specific external observations, not a claim about
this codebase or this pilot's local result.

Wiki/AST discovery remains the default for broad code search. Reach for LSP
only when a task needs a verified semantic resolution (which exact
definition, every static reference) or a checkpoint diagnostic delta after a
saved edit.

## Provisioning (operator/CI step, done once per environment)

Nothing here is automatic. The maintainer or CI provisions, before any
`lsp_*` tool call can succeed:

1. **Pyright 1.1.414**, pinned — the package that ships `pyright-langserver`.
   No later/latest version is selected automatically; a version pin change
   requires a spec revision and a rerun of the real-server fixtures.
2. A **supported Node.js runtime** on `PATH` (Pyright's own requirement).
   The exact Node patch version is environment-specific and is recorded in
   the run manifest, not pinned by this pilot.
3. A bounded companion version check: `pyright --version` (configurable via
   `version_command`), compared against `expected_server_version` and any
   `serverInfo.version` the server itself reports.
4. A real, immutable **`environment_id`** — see "Environment identity"
   below. There is no installer step that derives or writes this for you.

Installing/listing the toolkit template performs none of the above and
never starts a process — see "No hidden startup" below.

## Installing per worktree

Configuration is **per worktree, always explicit** — nothing is inherited
implicitly from a parent checkout or another worktree.

```bash
# Preferred: host-aware installer, run from inside the worktree that needs it
parrot toolkits install lsp

# Manual alternative (see examples/lsp-mcp.yaml for the full annotated version)
sed -n '/^toolkits:/,$p' examples/lsp-mcp.yaml | tail -n +2 >> .parrot/mcp-toolkits.yaml
```

Both paths render the packaged `lsp` template
(`packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml`) into
`.parrot/mcp-toolkits.yaml`, substituting `{{repo_root}}` with **this
worktree's own absolute path**. An installed absolute `repo_root` copied
from a parent checkout into a child worktree is wrong by construction — the
worktree has a different path. Re-render the config (re-run the installer,
or hand-edit `repo_root`) inside every new worktree; never copy
`.parrot/mcp-toolkits.yaml` wholesale between worktrees.

Installing this template does not touch any other toolkit's section, does
not rewrite host-managed SDD skills, and does not enable itself in a host
beyond the explicit install action itself (`parrot toolkits install lsp` or
the manual append above).

### Seat-specific visibility checks

A server-level `tools/list` success (`parrot mcp-local lsp --list`) proves
the toolkit resolves and its four tools are declared — it does **not**
prove a delegated research/coding/review seat can actually see them. Verify
through the real CLI host for **every** seat you expect to use LSP evidence:

- Confirm the host's own MCP configuration (`.mcp.json`, `.codex/config.toml`,
  or the host-specific equivalent) lists the `lsp` server with an absolute
  `command`/`args` and an explicit `cwd`.
- Ask the seat itself to list its available tools and look for
  `lsp_definition`, `lsp_references`, `lsp_diagnostics`,
  `lsp_diagnostic_delta` (the exact host-prefixed tool name depends on the
  host's own naming, e.g. `mcp__parrot-lsp__lsp_definition`).
- A seat that cannot see the tools, or one without a provisioned
  environment, is recorded as **fallback-only** for that run rather than
  assumed unavailable-by-omission.

Do not generalize one host's successful visibility check to every host or
every worktree — each is checked independently.

## Configuration reference (`kwargs.config`, an `LSPConfig`)

| Field | Default | Notes |
|---|---|---|
| `repo_root` | required, absolute | Canonicalized once; the instance is bound to it permanently. Rendered from `{{repo_root}}` by the installer/template mechanism. |
| `environment_id` | required, non-empty | See "Environment identity" below. The packaged template ships the `operator-unconfigured` sentinel. |
| `server_command` | `["pyright-langserver", "--stdio"]` | Trusted operator configuration; never a tool-call input. |
| `version_command` | `["pyright", "--version"]` | Bounded companion check run alongside startup. |
| `expected_server_version` | `"1.1.414"` | Pinned pilot backend. |
| `python_path` | current interpreter | The interpreter Pyright analyzes against (`python.pythonPath`). |
| `source_roots` | `[]` | Additional **PEP 420 namespace roots** inside `repo_root` — e.g. a satellite distribution's `src/parrot/` that merges into the core `parrot.*` namespace. Every entry must be absolute and inside `repo_root`; used to populate `python.analysis.extraPaths` so cross-distribution imports resolve. |
| `startup_timeout_s` | `20` (max `60`) | Server initialize/configure budget. |
| `request_timeout_s` | `10` (max `30`) | Per navigation request budget. |
| `diagnostics_timeout_s` | `20` (max `60`) | Per diagnostics/delta request budget. |
| `idle_timeout_s` | `120` (30-600) | Owned Pyright process shuts down after this much call inactivity. |
| `node_heap_mb` | `1024` (max `2048`) | Node old-space cap — **not** an RSS guarantee; RSS is tracked as a separate measured metric. |

Additional fixed pilot bounds that are **not** configurable: total call
deadline 90s (covers startup/checks/cleanup), one server and one in-flight
semantic operation per instance (no internal retry), file limit 1 MiB,
manifest limit 10,000 files / 128 MiB, 200 rendered items, 2,000 raw
diagnostics per snapshot, 32 KiB JSON result cap.

### Environment identity

`environment_id` names one **immutable** dependency environment: the exact
pinned Pyright build, Node runtime, and interpreter/dependency set the
toolkit assumes are stable for as long as that ID is used. It is *not*
derived automatically — the operator picks it (for example, a hash of the
resolved interpreter path plus the pinned Pyright version plus the
effective `pyrightconfig.json`/`pyproject.toml` settings).

- Left at the packaged sentinel `operator-unconfigured`, every `lsp_*` call
  returns `status="unavailable", code="invalid_request"` **before any
  process is spawned**.
- Changing `environment_id` — because the pinned Pyright version, Node
  runtime, or dependency environment changed — invalidates every stored
  diagnostic baseline (`lsp_diagnostic_delta` rejects a baseline captured
  under a different environment/config/server identity as
  `baseline_incompatible`, never silently treating it as still valid).
- Mutating the underlying dependency environment mid-run without rotating
  `environment_id` breaks the evidence's provenance guarantee; treat the
  environment as read-only for the lifetime of one `environment_id`.

## No hidden startup

Importing `parrot_tools.lsp.toolkit`, constructing `LSPToolkit(config=...)`,
listing its tools (`get_tools()`, `parrot mcp-local lsp --list`), and
installing the packaged template (`parrot toolkits install lsp`,
`parrot toolkits list`) never spawn Pyright, never scan the workspace, and
never touch the network. Construction only validates the trusted
`LSPConfig` in memory. The first process spawn and the first workspace
snapshot happen lazily, inside a call to one of the four tools below, and
only once `environment_id` is a real (non-sentinel) value.

## The four tools

| Tool | Purpose |
|---|---|
| `lsp_definition(path, line, column, expected_sha256)` | Resolve a verified expression to its definition location(s). |
| `lsp_references(path, line, column, expected_sha256, include_declaration=False, limit=50)` | Find static references; `limit` is 1-200, truncation is always explicit. |
| `lsp_diagnostics(paths)` | Analyze 1-20 saved Python files; returns a `snapshot_id` baseline when the underlying publication was complete. |
| `lsp_diagnostic_delta(baseline_id, paths)` | Compare the same file set against a prior baseline after saved edits. |

### Hash and column convention

Every navigation call requires the caller's own `expected_sha256` — the
SHA-256 hex digest of the exact on-disk file content the caller believes it
is querying against. The toolkit verifies this against the real file before
doing anything else and fails explicitly (`source_changed`) on a mismatch;
it never infers freshness from a missing or stale hash. Every returned
location carries its own file's `sha256` for the same reason.

Positions and ranges are **one-based** and count **Unicode code points**,
not bytes, UTF-16 code units, or display cells (the toolkit converts to/from
the wire protocol's UTF-16 internally). Ranges are end-exclusive.

## Baseline / delta workflow

1. Call `lsp_diagnostics(paths)` for the files you are about to touch. On a
   complete publication, the result carries a `snapshot_id` — record it.
2. Make and save your edit.
3. Call `lsp_diagnostic_delta(baseline_id=<snapshot_id>, paths=<same paths>)`.
   The result reports `added`/`removed` diagnostics, computed as a multiset
   comparison over `(path, source, code, severity, full_message)` —
   **ranges are excluded from matching** on purpose, so a pure line shift
   never reads as "fixed one, introduced another."
4. Every successful `lsp_diagnostics`/`lsp_diagnostic_delta` call also
   retains its own complete result as a fresh baseline, so you can chain
   further deltas from the latest checkpoint.

Baselines are held in a bounded, in-memory, per-instance store: at most
eight entries, LRU-evicted, each expiring after 30 minutes. A baseline
request against a missing, expired, scope-mismatched (different file set),
or environment/config/server-incompatible baseline fails explicitly
(`baseline_missing`, `baseline_scope_mismatch`, `baseline_incompatible`) —
it is never silently treated as "no prior baseline, so nothing changed."

## Fallbacks and unknown diagnostics

The toolkit never edits files and never automatically invokes another tool
on failure. Every typed `LSPResult` that cannot report a normal `ok` carries
a deterministic `fallback` message recommending wiki/AST/source inspection
for navigation questions, or the project's existing tests/lint for
diagnostic questions. Seats are expected to make **at most one** fallback
attempt per failed operation and must not repeatedly restart an unavailable
server within the same turn.

**Unknown coverage is never reported as clean.** A `lsp_diagnostics`/
`lsp_diagnostic_delta` call whose underlying publication is incomplete
(missing or unversioned per-file publications within the timeout budget)
fails with `diagnostics_timeout` or `diagnostics_unversioned` rather than
returning an empty-but-successful diagnostic list — an empty successful
result means "no issues found," not "coverage unknown." Likewise, an empty
successful `lsp_references`/`lsp_definition` result means no static match
was found, not proof that no callers exist (dynamic dispatch is invisible
to static analysis — see "Known limitations" below).

Any workspace change detected between the "before" and "after" snapshot of
one call discards that call's result as `workspace_changed` rather than
serving a cross-file answer computed against an invalid checkpoint. A
manifest/config change (including a dependency file the request did not
directly touch) always triggers a session restart before the next call —
this conservative-invalidation cost is deliberate and is measured, not
hidden, by the pilot's evaluation harness.

## Known limitations

- **Saved edits only.** This pilot synchronizes on-disk content; there is
  no unsaved/in-memory editor-buffer API. Diagnostics and navigation always
  reflect the last saved state of a file.
- **Dynamic Python is invisible to static analysis.** Registry-driven
  dispatch (e.g. `@register_agent("name")` resolving a class at runtime),
  `getattr`-based indirection, and other non-statically-resolvable call
  sites will not appear in `lsp_references`/`lsp_definition` results and
  will not be flagged missing — the fixed benchmark tasks that exercise
  this pattern require supplementary text search, and the same applies to
  any ordinary use of the toolkit.
- **External dependency locations are not read back.** Pyright may use
  installed dependencies for analysis, but any resolved location outside
  `repo_root` is omitted from results (counted in `omitted_count`), never
  returned to the caller.
- **Whole-workspace conservative restart.** A saved edit anywhere in the
  tracked manifest — not just the file you touched — can trigger a session
  restart before your next call. This may eliminate some of the pilot's
  hoped-for savings; that is itself a measured pilot outcome, not a defect.
- **One in-flight operation per instance.** Calls to the same `lsp` toolkit
  instance are serialized; there is no internal retry of a semantic
  request, and the total call deadline (90s, including startup) applies
  even to a cold start.
- **`SIGKILL` cannot guarantee cleanup.** The local MCP factory closes the
  owned Pyright session on stdin EOF, normal `stop()`, and `SIGTERM`
  (bounded by a cleanup timeout); a `SIGKILL`-level termination of the host
  process cannot run any application-level cleanup and is an explicit,
  accepted limitation, not a bug to be fixed by this pilot.
- **No implicit host wiring.** This spec adds a template and an installer
  action only. It does not add LSP tools to wiki MCP, does not wire
  in-process dev-loop agents, and does not modify any host configuration or
  managed SDD skill outside the explicit `parrot toolkits install lsp`
  action described above.

## Operator run checklist (pre-M6)

Spec §8 "Open Questions" leaves one item explicitly unresolved: *"Which
concrete CLI/model versions, immutable environment IDs, real task
commits, price basis, and spending ceiling should the live run manifest
use?"* — an execution prerequisite for the M6 live run, not a blocker on
the deterministic toolkit/harness contracts (M1–M5, all implemented).
Before running `python -m benchmarks.sdd_lsp --manifest <path>
--output-dir <dir> --live`, the operator must fill in every item below in
a real `PilotManifest` JSON file — none of these has a safe default, and
none is invented by the toolkit or the CLI:

- **Immutable environment IDs.** One per arm's seat, matching the
  `LSPConfig.environment_id` convention above (never the
  `operator-unconfigured` sentinel for a live run) — an environment
  change invalidates baselines and requires a new ID, never a reused one.
- **Pinned task commit.** `PilotManifest.pinned_commit`: the exact
  repository commit the pilot measures, reviewed against the 12 fixed
  tasks in `benchmarks/sdd_lsp/tasks.yaml` and their pinned
  `fixture_sha256` values.
- **Actual prices and cache semantics.** `PilotManifest.price_provenance`
  (console, contract, or published rate card — never invented) and
  `cache_semantics` (how each seat's provider reports cache read/write
  classes). `benchmarks.sdd_lsp.models.PriceBook` ships empty on purpose;
  an operator-supplied price file is required for a priced gate — see
  `--prices` on the CLI.
- **Spending ceiling and per-attempt reservation.**
  `spending_ceiling_usd` and `per_attempt_cost_reservation_usd` — the
  runner (`benchmarks/sdd_lsp/runner.py`) stops launching further
  attempts once the remaining budget cannot cover the next reservation,
  or once any attempt's cost comes back unknown; every already-launched
  attempt stays in the report, every skipped one is recorded explicitly
  as `not_launched`, never silently dropped.
- **Reviewed ground-truth checklist for the 180-attempt matrix.** Before
  launching: (1) `task_ids` is exactly the fixed 12-task set from
  `benchmarks/sdd_lsp/fixtures/scenarios.py::SCENARIO_IDS`; (2)
  `repetitions == 3` and `arms` is exactly the five fixed arms; (3) every
  arm has a `SeatSpec` with a real, reviewed `argv` (never a placeholder)
  and a bounded `timeout_s`; (4) seat visibility for **every**
  research/coding/review role has been independently verified through the
  real CLI host (see "Seat-specific visibility checks" above) — a
  server-level `tools/list` success is not sufficient proof; a role that
  cannot see the tools, or has no provisioned environment, is recorded as
  **fallback-only**, not silently treated as available.

### Opting into the live seat-readiness check

`packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py`'s default
tests use fake CLI hosts and the scripted `fake_server.py` fixture only —
they spend nothing and never require a real host. To additionally verify
**real** research/coding/review CLI hosts (their actual tool access, root
isolation, and fallback behavior — never a real Pyright/paid run by
itself), set `PARROT_LSP_LIVE_MANIFEST` to the path of an operator-authored
JSON file before running the suite:

```json
{
  "seats": {
    "research": {"argv": ["<real-cli>", "..."], "timeout_s": 30.0},
    "coding":   {"argv": ["<real-cli>", "..."], "timeout_s": 30.0},
    "review":   {"argv": ["<real-cli>", "..."], "timeout_s": 30.0}
  }
}
```

Absence of `PARROT_LSP_LIVE_MANIFEST` means the live seat check is **not
executed** — it is never silently reported as passing. Only an explicit,
reviewed manifest exercises the real hosts.

## Evaluation status

The approved five-arm (`current`, `wiki_ast`, `lsp_navigation`,
`lsp_diagnostics`, `lsp_combined`) live evaluation — 12 tasks × 3 paired
repetitions × 5 arms — is tracked separately (spec §2 "Evaluation contract",
Module 6). Until that run completes with a recorded `go`/`no_go`/
`inconclusive` decision, this toolkit remains opt-in and unproven locally:
install and use it deliberately, not by default.
