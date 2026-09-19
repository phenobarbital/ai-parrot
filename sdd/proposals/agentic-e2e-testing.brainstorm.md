---
type: feature
base_branch: dev
---

# Brainstorm: Agentic End-to-End Testing

**Date**: 2026-09-12
**Author**: Jesus (jesuslarag@gmail.com)
**Status**: exploration — reviewed against current code on 2026-09-19
**Recommended Option**: B — deterministic process gate plus optional live checks and exploration

## Problem Statement

The repository already contains subprocess tests, live-provider tests, and
in-process integration tests. The missing capability is a shared process harness
and a feature-scoped E2E evidence contract integrated into SDD closeout.

The current SDD feature test selector deliberately excludes E2E:
`packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` sets
`AGENT_MARKER_EXPRESSION = "not e2e and not real_llm and not integration"`.
`.claude/agents/qa-runner.md` runs the feature tier and assigns full-suite/E2E
runs to CI. E2E therefore needs an explicit additional stage, not another
invocation of the ordinary feature selector or an unscoped `pytest -m e2e`.

Process tests catch CLI lifetime, stdout purity, configuration, real transport,
readiness and shutdown defects that in-process fixtures cannot establish.
Browser tests add hydration, proxy, console and network behavior for the
Svelte 5 Admin UI at `packages/ai-parrot-server/ui/`.

## Review Findings and Corrections

| Finding | Correction |
|---|---|
| Groq credentials and a floating Gemini alias were suggested as defaults | Use the existing Google client with `google:gemini-2.5-flash-lite` and `GOOGLE_API_KEY` for optional live tests. No Groq requirement or automatic provider fallback. |
| Live model tests were called deterministic | Separate credential-free deterministic process tests from live-provider checks and agent exploration. Structural assertions are deterministic; provider behavior is not. |
| `e2e` and `slow` markers were described as missing | Both already exist in root `pytest.ini`; package conftests also register/auto-mark E2E. Reuse them. |
| The QA criterion union was described as two types | It is `FlowtaskCriterion | ShellCriterion | ManualCriterion` in `flows/dev_loop/models/base.py`. No `E2ECriterion` exists. |
| Closeout could trust an agent-written boolean or a skipped pytest run | Machine-generated evidence must establish scenario coverage, successful execution, teardown and revision identity. Required skips cannot pass. |
| Only Claude command files were included | Include `.agents/skills/sdd-spec/SKILL.md` and `.agents/skills/sdd-done/SKILL.md` alongside Claude surfaces. |
| New tests were placed in the legacy root test tree | Put new harness tests under `packages/ai-parrot-server/tests/e2e/`; existing root tests remain useful references. |
| `httpx` was suggested because it is a transitive dependency | Use `aiohttp`, per project conventions. |
| All MCP targets used `/mcp/info` readiness | Toolkit HTTP and per-agent mounts have different routes. Readiness belongs to each target. |
| Fixed CDP ports and automatic browser adoption contradicted worktree isolation | Allocate a per-run port/profile; adoption is explicit and never transfers process ownership. |
| PID + TTL and host hooks were treated as sufficient cleanup | Validate process identity, persist ownership before readiness, and supervise runs independently of host hooks. |
| Historical measurements were presented as current verification | Preserve them below as reported results; this review checked source, not timings or paid API calls. |

## Constraints and Decisions

- Keep the harness in `ai-parrot-server`, exposed lazily as `parrot e2e` from
  core CLI, with the appropriate install hint. It does not exist yet.
- Real processes and real transports are required for process-boundary evidence.
  The deterministic tier needs no remote LLM or provider credentials.
- `e2e: required|optional|none` is a proposed spec frontmatter contract. Required
  scenarios block closeout unless executed successfully. Missing optional
  prerequisites may skip, but skips remain visible.
- Preserve the normal SDD test selector. Add a separate, explicitly selected
  E2E stage after feature QA and before closeout. Never run the entire repository
  E2E suite as part of an ordinary feature task.
- Exploration produces candidate tests and a separate report. Only reviewed,
  codified checks can establish gate evidence. Candidate promotion is human-only.
- Use `aiohttp`, Pydantic v2 and existing process utilities; no new runtime
  library is proposed. Dependency installation must include target-specific
  packages, including `ai-parrot-client-google` for live Google checks.
- Worktrees need independent state, ports, data namespaces, browser profiles and
  logs. Child processes must load the feature worktree's sources, not another
  checkout's editable installation.
- Keep code, artifacts and identifiers in English. Never persist credentials,
  session tokens or full environments in state or reports.

## Cheap Model and Live-Test Policy

Proposed default: **`google:gemini-2.5-flash-lite`**, resolved through
`LLMFactory`/`AbstractClient`, with credentials from
`navconfig.config.get("GOOGLE_API_KEY")`. The existing satellite package exports
`GoogleGenAIClient` through the `parrot.clients` entry point; its model catalog
already defines `GEMINI_2_5_FLASH_LITE`. No provider SDK calls belong in the harness.

Google documents function calling and structured output for this stable model.
Published standard text pricing is **$0.10 input / $0.40 output per million
tokens**. Sources checked for this review:
[model capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite),
[pricing](https://ai.google.dev/gemini-api/docs/pricing).
Pin this model ID rather than `gemini-flash-latest`; it still does not guarantee
identical provider responses or permanent availability. Recheck availability at
implementation time; a retired/unavailable model produces explicit blocked or
failed live evidence, never a silent fallback.

`e2e-plan.md` supplies `model`, call and token budgets; `E2E_MODEL` and
`E2E_MAX_LLM_CALLS` are proposed operator overrides. Proposed initial live-smoke
limits: 4 provider requests per run, 512 output tokens per request, 4096 input
tokens per request and a 60-second run deadline. Validate these limits in the
implementation spike before adoption. Count retries, agent tool-loop requests
and structured-output repair calls against the same budget. Enforce limits in
execution code, not just prompts; exhaustion is a reported failure. An explicit
larger plan/operator budget is needed for more complex scenarios.

Live tests require both explicit opt-in and a credential. Reuse `live` and
`real_llm`, with `PARROT_TEST_E2E=1` and `PARROT_TEST_REAL_LLM=1` for this new
suite. Existing real-LLM skip hooks are package-local: the server suite must
implement its own opt-in enforcement before constructing clients. Missing keys
skip optional live tests; required live scenarios block closeout. Assert schemas,
status and observable tool effects, not exact prose or an LLM judge's opinion.

This model configures the target agent or a Parrot-based exploratory call. It
does not change a host coding agent's model or bound that host's own token bill.

## Options Explored

### A. Add a dedicated QA criterion

Add `E2ECriterion` to the existing discriminated union and teach QA to execute
it. This makes E2E explicit but requires changes to models, intake validation
and execution; it does not automatically provide lifecycle management or UI
coverage. A `ShellCriterion` can instead invoke a standalone harness runner,
subject to the current command allow-list. Neither approach should put process
supervision inside an agent prompt.

### B. Shared harness with deterministic checks and optional exploration — recommended

A lazy `parrot e2e` CLI owns target startup, readiness, probes, evidence and
cleanup. Pytest, CI and SDD consume the same contracts. Three distinct classes
of runs use it:

1. **Deterministic process gate:** credential-free, fixed scenarios using real
   local toolkit/HTTP/stdio services and controlled data.
2. **Live-provider checks:** optional by default, paid opt-in, bounded calls and
   structural assertions. A spec may explicitly require selected live scenarios.
3. **Exploration:** API/MCP and browser agents discover scenarios and propose
   tests. Their reports never overwrite the machine-generated gate verdict.

This preserves the original harness and exploration decisions while making the
SDD step usable without API keys. Lifecycle and evidence handling are substantial
work; the original estimate of a roughly 200-line harness is not justified.

### C. Long-lived server agent plus client agent

Rejected: adds agent cost and host-dependent lifecycle coordination around work
that needs deterministic supervision anyway. Do not assume a server always dies
or always survives when a sub-agent returns.

### D. In-process aiohttp integration tests

Useful complementary coverage, using the already-declared `pytest-aiohttp` dev
dependency. These tests still use sockets/ports, and cannot establish CLI startup
or signal handling. They do not satisfy scenarios requiring a separate process.
No requirements-file synchronization is proposed: dependencies are managed in
`pyproject.toml` through uv.

## Proposed Harness and Evidence Contract

Commands below are new capabilities, not existing CLI commands:

- `parrot e2e run --plan <path>`: bounded lifecycle owner; executes the plan's
  reviewed pytest node IDs, collects results, always tears down, writes evidence
  atomically and exits nonzero on required failure, missing coverage or cleanup
  failure. This is the SDD/CI entry point.
- `parrot e2e up <target>`, `status`, `logs`, `down`: manual/exploratory use.
  `up` returns one JSON result when ready; diagnostics go to stderr. Detached
  runs require a watchdog/lease and an absolute deadline, not host-hook survival.
- `down <run-id>`, `down --all`, `down --stale`: scoped to the current worktree
  and owner by default. Cleanup must not kill another feature's processes.

### Targets

| Target | Readiness and scope |
|---|---|
| `mcp-toolkit` | HTTP `WorkingMemoryToolkit`; configured base path plus `/info`, then protocol/tool round-trip. No LLM. |
| `mcp-stdio` | Real `initialize` and tool round-trips over a persistent stdin/stdout channel. A supervisor or fixture must retain the pipes; a PID file cannot reconnect stdio. |
| `mcp-agent` | `AgentMCPMount` exposes `{base_path}/{agent_name}`. Use its configured endpoint and protocol handshake; do not assume `/mcp/info`. Live calls are separately gated. |
| `botmanager` | Minimal app exposes `/healthz`; initialize navigator-session plus a synthetic authenticated identity for selected API tests. Health alone is not auth evidence. |
| `ui` | `/admin/` plus explicit browser scenarios; configure `PUBLIC_API_URL` before build/start and verify backend/proxy reachability. |
| `browser` | Obscura `/json/version`, unique CDP port and profile; attach DevTools to the endpoint returned by the harness. |

`botmanager --profile minimal` remains the default. `--profile full` runs the
real application with explicitly configured readiness and services; `/healthz`
from the minimal example must not be assumed to exist in `run.py`.

### Lifecycle and isolation

Persist `RunState` in the feature worktree's `sdd/state/e2e/<run-id>.json` and
logs under `artifacts/logs/e2e/<run-id>/`. State includes a schema version,
run/owner/worktree identity, target, status, PID/PGID, process creation time,
endpoint, deadline and ownership flag. Write startup state immediately after
spawn, before waiting for readiness. Never store secrets.

Spawn a separate process group. On timeout, cancellation, probe failure or normal
completion, terminate the owned group, wait with a deadline, escalate if needed
and verify exit. Record forced shutdown; it fails a graceful-shutdown scenario.
Before signaling a PID/PGID, validate creation time and ownership to avoid PID
reuse. Do not delete state until termination is confirmed. Lock state operations
and use atomic writes; stale cleanup is idempotent and bounded.

Free-port discovery followed by binding has a race: prefer an inherited bound
socket where supported, otherwise retry a verified bind collision within a fixed
budget. Browser adoption is explicit; an adopted browser is never terminated by
cleanup. Private profiles and namespaces prevent parallel runs contaminating data.

Host stop/session hooks are additional cleanup only. Owner-scoped hooks clean
that owner's runs immediately, not only runs old enough for TTL expiry. A watchdog
handles controller death for detached runs; tests must exercise that failure path.

### Plans and gate evidence

`/sdd-spec` writes `sdd/state/<FEAT-ID>/e2e-plan.md` from the spec's **E2E
Scenarios** subsection. Each scenario has a stable ID, tier, target, reviewed
pytest node ID, prerequisites, required/optional flag, deadlines and assertions.
The plan records explicit model/budget settings for live scenarios.

The runner writes `e2e-verdict.json` with schema version, feature/run ID,
worktree identity, tested commit and relevant source digest, spec/plan hashes,
selected node IDs, command/exit code, collected/executed/pass/fail/skip counts,
per-scenario outcomes, teardown result and artifact paths. Capture identity
before and after execution; source changes during a run invalidate evidence.
The source digest excludes generated logs/state but includes relevant uncommitted
changes. Closeout must validate the implementation revision; bookkeeping-only
commits require explicit content equivalence, not blind acceptance of old evidence.

PASS requires all required scenarios to execute and pass, valid coverage and
successful cleanup. Zero collection, required skips/xfails, invalid reports,
missing artifacts or stale evidence cannot pass, even when pytest exits zero.
Reports distinguish PASS, FAIL, BLOCKED and MISSING. Optional missing prerequisites
remain visible. Exploration writes `e2e-exploration.json` separately and places
candidates under `sdd/state/<FEAT-ID>/e2e/candidates/`, outside pytest discovery.
Human review promotes them into the owning package's test tree.

## SDD and CI Integration

1. Add the frontmatter/scenario contract to `sdd/templates/spec.md` and both
   Claude/Codex spec-generation surfaces.
2. Keep feature-tier QA unchanged; invoke the additional E2E runner only for the
   feature's declared scenarios. `qa-runner` reports its separate outcome.
3. Wire the dev-loop QA path explicitly through a validated `ShellCriterion`
   or a dedicated runner integration. Update the allow-list/selection handling
   as necessary: passing the command through today's E2E-excluding selector
   would silently defeat the stage. A new criterion type is not required initially.
4. Both closeout surfaces consume current evidence before push/PR/merge/cleanup.
   `e2e: required` blocks without passing required scenarios; optional evidence
   is advisory. Preserve existing ordinary test evidence reuse. An exploratory
   report or generic `--force` must not masquerade as a successful E2E gate;
   any explicit waiver must remain recorded as a waiver.
5. Add a nightly workflow with `schedule` and manual dispatch for deterministic
   tests, using explicit package paths and `PARROT_TEST_E2E=1`. Current
   `.github/workflows/ci.yml` has push/PR triggers, not a nightly schedule.
   No provider secret is needed for this job. A separate opt-in live job uses
   `GOOGLE_API_KEY`, `PARROT_TEST_REAL_LLM=1`, protected credentials and budgets.
   Preserve logs and reports even on failure.

Suggested deterministic pytest selection for the new suite:
`pytest packages/ai-parrot-server/tests/e2e/ -m "e2e and not live and not real_llm"`.
SDD runs the narrower node IDs from the plan through the runner, not this whole
suite. Add opt-in handling locally to the new suite rather than changing the
semantics of every existing E2E test in the repository.

Exploratory `e2e-api-tester` and `e2e-ui-tester` remain proposed Claude agent
surfaces; `/e2e` can be a convenience skill. The portable gate must work without
those agents. Verify installed host capabilities before relying on nested agents,
MCP scoping or hook payloads; the historical claim of a universal nesting depth
is not a harness contract. See [Claude subagent documentation](https://code.claude.com/docs/en/sub-agents).
The root `package.json` declares `chrome-devtools-mcp` as `^1.6.0`; that range
does not prove an exact resolved version. Pin/verify the browser tool and Node
versions in the implementation spike and pass the allocated CDP endpoint.

## Historical Spike and Remaining Prerequisites

The original brainstorm reported the following warm measurements. They were
not rerun in this review and are not acceptance evidence for the current HEAD:

| Target | Reported warm readiness | Qualification |
|---|---|---|
| stdio memory toolkit | 1.36 / 1.34 s | JSON-RPC initialize; stdin EOF shutdown |
| HTTP working-memory toolkit | 1.49 / 1.44 / 1.44 s | Custom serve-forever wrapper; reported SIGTERM exit 0.02 s |
| Minimal BotManager | 3.99 / 3.44 / 3.36 s | tiktoken stubbed, no reachable DB/Redis; reported shutdown 0.7 s |

The stubbed BotManager result is not proof of an offline production boot. Retain
the previously agreed full-profile spike: admit it to the dev-loop default only
if warm readiness is ≤15 seconds and SIGTERM exit ≤10 seconds with real configured
services. Otherwise full remains nightly/opt-in. Do not extrapolate dependency
installation requirements from one historical 8.6 GB environment.

Source review confirms two prerequisite issues remain:

- **HTTP lifetime:** `_run_standalone_server()` in
  `packages/ai-parrot-server/src/parrot/mcp/cli.py` awaits `server.start()` and
  immediately reaches `finally: server.stop()`. HTTP `start()` returns after
  binding. Add HTTP-specific lifetime/signal handling and regression coverage.
  Unix `start()` already awaits `serve_forever()`; do not add a Unix fix.
- **Import-time tokenizer acquisition:**
  `packages/ai-parrot/src/parrot/skills/parsers.py` still initializes
  `tiktoken.get_encoding("cl100k_base")` at module scope. Lazy initialization
  removes that import-time fetch, but first tokenization can still need cached
  data. Verify offline boot with real imports, network disabled and a controlled
  cache. Do not claim a one-line change guarantees every boot profile works offline.

The original detached-process experiment reported survival after a main shell
call and a background-launched sub-agent returned. Foreground survival was not
proven by that experiment. Repeat lifecycle checks on supported hosts; neither
survival nor cleanup by a particular coding-agent host is a portable guarantee.

## Implementation Surfaces and Verified References

| Surface | Existing contract / proposed change |
|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/` | New harness, target adapters, supervisor and evidence writer |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | Existing lazy command/install-hint registries; add E2E |
| `packages/ai-parrot-server/src/parrot/mcp/cli.py` | HTTP lifetime prerequisite |
| `packages/ai-parrot-server/src/parrot/mcp/obscura.py` | Lifecycle reference; preserve existing API and ownership semantics |
| `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py` | Per-agent endpoint mounts |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | Tokenizer prerequisite |
| `docker/integrations/server.py` | Minimal app reference; new target needs session/auth setup |
| `packages/ai-parrot-server/tests/e2e/` | New package-local tests/opt-in fixtures; reuse existing markers |
| `tests/mcp/test_mcp_local_e2e.py` | Existing legacy subprocess bootstrap/stdio test reference |
| `tests/e2e/test_meta_live.py` | Existing credential-gated live-test reference, not default provider |
| `pytest.ini`, `tests/conftest.py`, `packages/ai-parrot-server/tests/conftest.py` | Existing E2E registration/directory marking; do not duplicate blindly |
| `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | Existing stable Flash-Lite ID |
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | Existing Google credential and token-limit handling |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | Existing criterion union including `ManualCriterion` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | Explicit dev-loop E2E integration point |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | Preserve standard agent-tier exclusions |
| `.claude/agents/qa-runner.md`, `.claude/agents/sdd-qa.md` | Additional feature-scoped E2E reporting/execution contract |
| `.claude/commands/sdd-spec.md`, `.claude/commands/sdd-done.md` | Plan and closeout contract |
| `.agents/skills/sdd-spec/SKILL.md`, `.agents/skills/sdd-done/SKILL.md` | Equivalent portable skill contracts |
| `sdd/templates/spec.md` | E2E metadata and scenarios |
| `.github/workflows/ci.yml` or a dedicated E2E workflow | New deterministic nightly/manual job; separate live opt-in |

## Delivery Order and Open Questions

1. Prerequisite fixes with focused regression tests; reproduce unmodified boot,
   offline behavior and full-profile timings. Confirm minimal session backend.
2. Define plan, state and evidence schemas; implement bounded `run`, lifecycle
   ownership, stdio handling and cleanup. Avoid extracting/refactoring Obscura
   unless sharing code is demonstrably necessary.
3. Implement deterministic package-local scenarios and SDD/CI evidence consumption.
4. Add bounded Google live checks and optional API/UI exploration; browser tooling
   and candidate review must not delay establishing the deterministic gate.

The previously agreed decisions remain: feature on `dev`, minimal default,
separate toolkit/agent targets, harness in `ai-parrot-server`, human candidate
promotion, required-only blocking and Obscura plus DevTools for exploration.

Still to settle in `/sdd-spec`: navigator-session backend and test authentication;
exact scenario schema/CLI exit-code mapping; watchdog implementation; environment
fingerprint and evidence reuse rules; validated model budgets and full-profile
measurements. Prefer a service-free session backend if supported, otherwise make
Redis an explicit prerequisite. Required scenarios with unavailable services are
BLOCKED, not passed. This review does not claim those implementation choices or
live-provider compatibility have already been exercised.
