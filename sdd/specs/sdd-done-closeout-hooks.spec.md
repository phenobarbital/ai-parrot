---
type: feature
base_branch: dev
projects: [sdd-tooling]
tags: [sdd-done, hooks, e2e, closeout, notifications, portability]
---

# Feature Specification: `/sdd-done` closeout hooks (event → subscribed actions)

**Feature ID**: FEAT-764
**Date**: 2026-10-28
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: next minor
**Source**: `sdd/proposals/sdd-done-closeout-hooks.proposal.md` (research: `sdd/state/FEAT-764/`)

---

## 1. Motivation & Business Requirements

### Problem Statement
`/sdd-done` is generic: the SDD installer ships it to other repositories, such as
`navigator-frontend-next` (TypeScript + Svelte). Today it runs a fixed pipeline:
E2E evidence gate (§4.6), test report (§4.7), report (§5), push (§8),
PR/merge (§9.2), Jira (§10), and cleanup (§11). A repository has no way to add
its own work at closeout. Examples:

- run extra gating tests before the PR is built, such as Playwright, or
  `e2e-ui-tester` driven by parrot-browsing and a pre-built plan, producing
  screenshots and screencasts;
- run side effects after the PR exists, such as transitioning a Jira ticket
  or sending a Telegram or push notification.

The only side effect today, Jira, is hard-wired behind `--resolve-jira`.

### Goals
- G1. A per-repository, declarative registry, `.parrot/sdd_hooks.toml`, that
  subscribes **hooks** to named closeout **events** (`pre_pr`, `post_pr`, `on_failure`).
- G2. One code-enforced dispatcher, `scripts/sdd/run_closeout_hooks.py`, that
  both host twins (Claude command and Codex skill) call. Its exit code is the
  contract (FEAT-703 pattern).
- G3. Three hook kinds:
  - `command`: a shell command;
  - `agent`: a host subagent such as `e2e-ui-tester`, dispatched by the host;
  - `builtin`: in-repo actions `jira.transition`, `telegram.send`, `push.send`, `webhook.post`.
- G4. `blocking` `pre_pr` hooks abort closeout before any stamp, push or PR,
  and `--force` cannot bypass them. `post_pr` / `on_failure` hooks never block.
- G5. Artifacts (screenshots, screencasts, logs) are **never committed**. They
  go under `/tmp` and are listed with their paths in the PR `## Evidence`
  section and the final output. Keeping them is the operator's job.
- G6. **Hard cut:** `--resolve-jira` and spec Step 10 are removed. Jira becomes
  the opt-in `post_pr` builtin `jira.transition`, which skips with a note when
  the spec has no linked Jira key.

### Non-Goals (explicitly out of scope)
- `/sdd-brief` hotfix closeouts. Deferred to a follow-up (proposal U5).
- A general event bus or navigator-eventbus emission (FEAT-710). A later
  `builtin` could target it.
- Uploading or persisting artifacts anywhere other than `/tmp`.
- Configuring hooks via a `CLAUDE.md` section. TOML only (proposal U1).
- Letting exploratory `e2e-*` runs satisfy the FEAT-581 E2E gate. Hooks are
  additive and never feed `check_e2e_closeout`.

---

## 2. Architectural Design

### Overview
`/sdd-done` gains three event points:

| Event | When | Blocking allowed | Runs under `--dry-run` |
|---|---|---|---|
| `pre_pr` | new Step **4.8**: after the 4.7 test report, before the §5 report, so results appear in the report | yes (`blocking = true`) | **yes** |
| `post_pr` | after §9.2, once the PR URL or merge SHA is known | no (forced false) | no |
| `on_failure` | whenever closeout aborts (E2E gate, blocking pre_pr failure, merge blocker) | no | no |

At each point the host runs:

```
python -m scripts.sdd.run_closeout_hooks --event <e> --context <ctx.json> [--dry-run]
```

The dispatcher works through the hooks in this order:

1. It loads `.parrot/sdd_hooks.toml`. If the file is absent, it exits 0 with
   "no hooks". If the file is malformed, it exits 2 (fail closed; never a silent no-op).
2. It runs each hook **in declaration order**, sequentially:
   - `command`: runs through a subprocess with `timeout_s`, in the worktree as
     cwd. The JSON context is passed in the env as `SDD_HOOK_CONTEXT=<path>`,
     with `SDD_HOOK_ARTIFACT_DIR`, `SDD_FEAT_ID` and `SDD_PR_URL`.
   - `builtin`: runs in-process (module M3).
   - `agent`: cannot run in Python. The dispatcher marks it `pending` and puts a
     dispatch entry (agent name, rendered prompt, artifact dir) in the result
     JSON. The host launches the subagent and then records the outcome with
     `run_closeout_hooks --event <e> --record <hook-name> --status pass|fail
     [--summary ...]`. This mirrors the sdd-coder native-seat split.
3. It writes `/tmp/claude-<uid>/sdd-hooks/<FEAT-ID>/<event>.json` with the
   per-hook status, duration and artifacts. Each hook gets its own artifact dir
   `/tmp/claude-<uid>/sdd-hooks/<FEAT-ID>/<hook-name>/`; the root can be
   overridden with `SDD_HOOKS_ARTIFACT_ROOT`. Artifacts are globbed by the
   hook's `artifacts` pattern, relative to its dir.
4. It prints one JSON object on stdout, with the keys `event`, `results[]`,
   `pending_agents[]`, `blocking_failed` and `evidence_md`.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | all done (non-blocking failures allowed) |
| 1 | a `blocking` hook failed |
| 2 | config or usage error |
| 3 | agent hooks are pending; the host must dispatch them and `--record` them, then re-run `--finalize` |

`--finalize` re-reads `<event>.json` and returns the final 0 or 1.

### Component Diagram
```
sdd-done twin (Claude cmd / Codex skill)
   │  4.8 pre_pr ─┐          9.2 → post_pr ─┐        abort → on_failure ─┐
   ▼              ▼                         ▼                            ▼
run_closeout_hooks.py ──→ closeout_hooks_config.load_hooks(.parrot/sdd_hooks.toml)
   ├─ command  → subprocess (timeout, env context)
   ├─ builtin  → closeout_builtins: jira.transition | telegram.send | webhook.post
   └─ agent    → pending → host Agent(e2e-ui-tester…) → --record → --finalize
   └─ writes /tmp/claude-<uid>/sdd-hooks/<FEAT>/<event>.json + evidence_md
```

### Integration Points
| Component | Change |
|---|---|
| `.claude/commands/sdd-done.md` | add 4.8, the post_pr step after 9.2, and on_failure wording on every abort; remove Step 10 and `--resolve-jira` from Usage/Guardrails/Output; add an `## Evidence` block to the PR body and the Step 12 output |
| `.agents/skills/sdd-done/SKILL.md` | same, in its numbered list (steps 4.6→new 4.8, 12, 14 removed) |
| `.parrot/test_runners.toml` | untouched; this is a precedent only |
| `scripts/sdd/check_e2e_closeout.py` | untouched; the gate stays independent |

### Data Models
Pydantic v2 (in M1):
```python
class HookKind(str, Enum): COMMAND="command"; AGENT="agent"; BUILTIN="builtin"
class HookSpec(BaseModel):
    name: str                      # unique per event, [a-z0-9-]+
    kind: HookKind
    run: str | None = None         # command
    agent: str | None = None       # agent
    prompt: str | None = None      # agent; str.format with context keys
    builtin: str | None = None     # builtin id
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")
    blocking: bool = False         # forced False for post_pr/on_failure (validation error if set True)
    timeout_s: int = 600
    artifacts: str | None = None   # glob relative to the hook artifact dir
    enabled: bool = True
class HooksConfig(BaseModel):
    pre_pr: list[HookSpec] = []
    post_pr: list[HookSpec] = []
    on_failure: list[HookSpec] = []
class HookContext(BaseModel):
    feat_id: str; spec_path: str; branch: str; base_branch: str; worktree: str
    pr_url: str | None = None; merge_sha: str | None = None
    test_report_md: str | None = None; e2e_gate: dict | None = None
    abort_reason: str | None = None; dry_run: bool = False
class HookResult(BaseModel):
    name: str; kind: HookKind; status: Literal["pass","fail","skipped","pending","timeout"]
    blocking: bool; duration_s: float; summary: str = ""; artifacts: list[str] = []
```

### New Public Interfaces
- CLI `python -m scripts.sdd.run_closeout_hooks` with the flags `--event`,
  `--context`, `--dry-run`, `--record NAME --status S [--summary T]`,
  `--finalize` and `--root`.
- Config file `.parrot/sdd_hooks.toml`. Example:
```toml
[[hooks.pre_pr]]
name = "frontend-e2e"
kind = "agent"
agent = "e2e-ui-tester"
prompt = "Run plan e2e/plans/checkout.yaml for {feat_id}; save a screencast to {artifact_dir}"
blocking = true
artifacts = "**/*.{png,webm,mp4}"

[[hooks.pre_pr]]
name = "playwright"
kind = "command"
run = "pnpm exec playwright test --output $SDD_HOOK_ARTIFACT_DIR"
blocking = true
timeout_s = 1200

[[hooks.post_pr]]
name = "jira"
kind = "builtin"
builtin = "jira.transition"
with = { status = "In Review" }

[[hooks.post_pr]]
name = "notify"
kind = "builtin"
builtin = "telegram.send"
with = { chat_id_env = "SDD_TELEGRAM_CHAT_ID", template = "{feat_id} PR ready: {pr_url}" }
```

---

## 3. Module Breakdown

### Module 1: Hooks config model + loader
- **Path**: `scripts/sdd/closeout_hooks_config.py` (new)
- **Responsibility**: Pydantic models above, plus `load_hooks(root)`. Uses
  `tomllib`, like the runner registry. Validation:
  - name uniqueness per event;
  - per-kind required fields;
  - `blocking` rejected on `post_pr`/`on_failure`;
  - `builtin` id must be known.
- **Depends on**: —
```python
CONFIG_PATH: str = ".parrot/sdd_hooks.toml"
class HooksConfigError(ValueError): """Raised when .parrot/sdd_hooks.toml is malformed."""
def load_hooks(root: Path) -> HooksConfig:
    """Load and validate hooks; return an empty HooksConfig when the file is absent.

    Raises:
        HooksConfigError: invalid TOML or schema violation (never a silent default).
    """
```

### Module 2: Dispatcher CLI
- **Path**: `scripts/sdd/run_closeout_hooks.py` (new)
- **Responsibility**:
  - event execution, the agent pending/record/finalize protocol, the
    artifact dir layout, the result JSON, and the exit-code contract;
  - `evidence_md` rendering (a `## Evidence` markdown list of hook → status →
    artifact paths).
- **Depends on**: M1, M3
```python
def run_event(event: str, ctx: HookContext, cfg: HooksConfig, artifact_root: Path) -> EventOutcome: ...
def record(event: str, feat_id: str, name: str, status: str, summary: str, artifact_root: Path) -> None: ...
def finalize(event: str, feat_id: str, artifact_root: Path) -> EventOutcome: ...
def render_evidence(outcome: EventOutcome) -> str: ...
def main(argv: Sequence[str] | None = None) -> int: """Exit 0 ok · 1 blocking failure · 2 config/usage · 3 agents pending."""
```

### Module 3: Builtins
- **Path**: `scripts/sdd/closeout_builtins.py` (new)
- **Responsibility**: a registry `BUILTINS: dict[str, Callable[[HookContext, dict, Path], HookResult]]`.
  - `jira.transition`: absorbs current Step 10.
    - Finds the key in the spec (`**Jira**: [KEY]`), falling back to the
      `jira:` frontmatter field.
    - If there is no key, it returns `skipped` with "No Jira key in spec".
    - It loads `JIRA_*` from env/navconfig, lists the transitions, and picks
      `with.status` (default "Done"). It adds a PR-link comment.
  - `telegram.send`: Bot API `sendMessage`. The token comes from
    `with.token_env` (default `SDD_TELEGRAM_BOT_TOKEN`) and the chat from
    `with.chat_id_env`.
  - `push.send`: a dedicated push notification with `with.title` and
    `with.template`, plus an optional `with.priority`. `with.provider` selects
    the backend from a small provider registry:
    - `ntfy` (default): POST to `${with.url_env:-SDD_NTFY_URL}/<topic>`, where
      the topic comes from `with.topic_env` (default `SDD_NTFY_TOPIC`) and an
      optional token from `SDD_NTFY_TOKEN`;
    - `gotify`: POST `/message` with the `X-Gotify-Key` header from `SDD_GOTIFY_TOKEN`.
    An unknown provider is a config error (M1 validation), never a runtime skip.
  - `webhook.post`: posts the JSON context to the URL in `with.url_env`,
    with optional `with.headers_env` for auth. This is the generic escape hatch.
  - HTTP goes through **aiohttp** via `asyncio.run`, never requests or httpx.
    Secrets come only from env; a missing secret gives `skipped`, never `fail`.
- **Depends on**: M1 (`HookContext`, `HookResult`)

### Module 4: Twin integration (both host files)
- **Paths**: `.claude/commands/sdd-done.md`, `.agents/skills/sdd-done/SKILL.md`
- **Responsibility**: wire the three events. Remove `--resolve-jira` and
  Step 10 / twin step 14 (hard cut). Add the `## Evidence` section to the PR
  body and the `Hooks:` lines to the output. Document the agent-hook loop:
  exit 3 → for each `pending_agents[]`, dispatch `Agent(subagent_type=<agent>,
  prompt=<rendered>)` (Codex: run inline or report as unsupported → `--record
  --status fail --summary "agent hooks unsupported on this host"`) → `--record` → `--finalize`.
- **Depends on**: M2 CLI contract

### Module 5: Docs + example config
- **Paths**: `docs/sdd/closeout-hooks.md` (new); `sdd/templates/sdd_hooks.example.toml`
  (new; needs `git add -f`, because `templates/` is gitignored).
- **Depends on**: M1–M3

#### Delegation-eligible modules
| Module | Eligible | Decided patterns / contract |
|---|---|---|
| M1 | yes | models and errors above; `tomllib`; empty config when absent |
| M2 | yes | exit-code table §2; artifact layout §2; `--record/--finalize` |
| M3 | yes | builtin signature; aiohttp; env-only secrets; missing secret → skipped |
| M4 | no | prose in two twins must stay consistent; keep with the thinking model |
| M5 | yes | — |

---

## 4. Test Specification

### Unit Tests (`tests/sdd_scripts/`)
| Test file | Covers |
|---|---|
| `test_closeout_hooks_config.py` | absent file → empty; malformed TOML → error; blocking on post_pr → error; unknown builtin → error; duplicate name → error; per-kind required fields |
| `test_run_closeout_hooks.py` | command pass/fail/timeout; blocking fail → exit 1; non-blocking fail → exit 0; agent → exit 3 + pending; record+finalize; `--dry-run` runs pre_pr and refuses post_pr (exit 0, all skipped); artifacts globbed under the `/tmp` root (tmp_path override); evidence_md lists paths; env vars passed to command |
| `test_closeout_builtins.py` | jira: no key → skipped, key found → transition called (aiohttp mocked); telegram/push/webhook: missing env → skipped; payload shape; push.send ntfy + gotify request shape; unknown push provider → config error |
| `test_sdd_done_hooks_contract.py` | both twins reference `run_closeout_hooks` for all three events, contain no `--resolve-jira`, and place 4.8 before the §5 report (text-contract test, same style as `test_sdd_done_brief_contract.py`) |

### Integration Tests
| Test | Description |
|---|---|
| `test_run_closeout_hooks.py::test_end_to_end_pre_pr_with_agent_record` | real subprocess command + agent record → finalize |

### Validation Contract
```yaml
tests:
  - tests/sdd_scripts/test_closeout_hooks_config.py
  - tests/sdd_scripts/test_run_closeout_hooks.py
  - tests/sdd_scripts/test_closeout_builtins.py
  - tests/sdd_scripts/test_sdd_done_hooks_contract.py
  - tests/sdd_scripts/test_e2e_closeout_contract.py
  - tests/sdd_scripts/test_sdd_done_brief_contract.py
```

### Test Data / Fixtures
- `tmp_path` repo root holding `.parrot/sdd_hooks.toml`; `SDD_HOOKS_ARTIFACT_ROOT=tmp_path/art`.

---

## 5. Acceptance Criteria
- [ ] AC1: Without `.parrot/sdd_hooks.toml`, `/sdd-done` behaves exactly as before, minus Step 10 (dispatcher exit 0, "no hooks").
- [ ] AC2: A malformed config makes the dispatcher exit 2, and `/sdd-done` aborts before any stamp or push.
- [ ] AC3: A failing `blocking` `pre_pr` hook aborts closeout before Step 7. `--force` does not bypass it. `on_failure` hooks then run.
- [ ] AC4: `pre_pr` hooks run under `--dry-run`. `post_pr` and `on_failure` hooks do not.
- [ ] AC5: `post_pr` hooks receive `pr_url` (or `merge_sha`). Their failures are reported, never fatal.
- [ ] AC6: Agent hooks follow exit 3 → host dispatch → `--record` → `--finalize`. An unrecorded pending hook at finalize counts as `fail`.
- [ ] AC7: Artifacts live only under `/tmp/claude-<uid>/sdd-hooks/<FEAT-ID>/`, and nothing under it is staged. Their absolute paths appear in the PR `## Evidence` section and the Step 12 output.
- [ ] AC8: `--resolve-jira` and Step 10 are removed from both twins. `jira.transition` skips with a note when the spec has no Jira key.
- [ ] AC9: Secrets are read only from env/navconfig. A missing secret gives `skipped`.
- [ ] AC10: Both twins invoke the same CLI. The contract test passes.
- [ ] AC11: No `requests`/`httpx`; `ruff check` is clean on the new scripts.

---

## 6. Codebase Contract
Verified against `dev` @ merge of origin/dev on 2026-10-28.

### Verified Imports
```python
import tomllib                                    # stdlib (used the same way in registry.py:6)
from pydantic import BaseModel, Field             # project-wide Pydantic v2
import aiohttp                                    # core dependency
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py
CONFIG_PATH: str = ".parrot/test_runners.toml"     # line 14 — naming precedent for M1
def load_registry(worktree: Path) -> RunnerRegistry: ...   # line 125 — loader precedent
# scripts/sdd/check_e2e_closeout.py
def main(argv: Optional[Sequence[str]] = None) -> int: ...  # line 201 — exit-code-as-contract precedent
#   --spec / --feat-id / --worktree                           # lines 211-213
```

### Integration Points
| New component | Attaches to | Where |
|---|---|---|
| 4.8 pre_pr | after Test Report | `.claude/commands/sdd-done.md:245` (`### 4.7. Test Report (FEAT-695)`) |
| post_pr | after Integrate | `.claude/commands/sdd-done.md:543` (`### 9.2. Integrate Feature Branch …`) |
| Jira removal | Step 10 | `.claude/commands/sdd-done.md:765` |
| twin pre_pr | after step 4.6 block | `.agents/skills/sdd-done/SKILL.md:98` |
| twin post_pr | step 12 Integrate | `.agents/skills/sdd-done/SKILL.md:206` |
| twin Jira removal | step 14 | `.agents/skills/sdd-done/SKILL.md:221` |

### Does NOT Exist (Anti-Hallucination)
- `.parrot/sdd_hooks.toml`, `scripts/sdd/run_closeout_hooks.py`, `closeout_hooks_config.py`, `closeout_builtins.py`: all new.
- There is no existing hook/event mechanism in `/sdd-done`. Do not look for a `parrot.sdd.hooks` module.
- There is no Telegram helper usable from `scripts/sdd/`. Do not import `parrot.integrations.telegram` (wrong layer; scripts must stay light).
- `check_e2e_closeout.py` takes **no** `--force`, and hooks must not add one.

### Edit Sites (Blueprint Anchors)
Base: `dev` after the 2026-10-28 merge of origin/dev.
| File | Op | Anchor (verbatim) | Line | Count |
|---|---|---|---|---|
| `.claude/commands/sdd-done.md` | modify | `### 4.7. Test Report (FEAT-695)` | 245 | 1 |
| `.claude/commands/sdd-done.md` | modify | `### 9.2. Integrate Feature Branch (FEAT-145, flow-aware)` | 543 | 1 |
| `.claude/commands/sdd-done.md` | modify | `### 10. Transition Jira Ticket (if --resolve-jira)` | 765 | 1 |
| `.claude/commands/sdd-done.md` | modify | `/sdd-done FEAT-014 --resolve-jira` | 27 | 1 |
| `.claude/commands/sdd-done.md` | modify | `### 12. Output` | 892 | 1 |
| `.agents/skills/sdd-done/SKILL.md` | modify | `4.6. Verify E2E evidence (FEAT-581/FEAT-703), before any stamp/push/` | 98 | 1 |
| `.agents/skills/sdd-done/SKILL.md` | modify | `12. Integrate:` | 206 | 1 |
| `.agents/skills/sdd-done/SKILL.md` | modify | `14. Resolve Jira if requested:` | 221 | 1 |
| `.agents/skills/sdd-done/SKILL.md` | modify | `--resolve-jira` (Codex invocation line) | 19 | 1 |
| `scripts/sdd/closeout_hooks_config.py` | create | — | — | — |
| `scripts/sdd/run_closeout_hooks.py` | create | — | — | — |
| `scripts/sdd/closeout_builtins.py` | create | — | — | — |
| `docs/sdd/closeout-hooks.md` | create | — | — | — |
| `sdd/templates/sdd_hooks.example.toml` | create (`git add -f`) | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Exit code = contract; the twins never re-derive the decision table (FEAT-703 `check_e2e_closeout.py`).
- Config under `.parrot/`, `tomllib`, and fail closed on malformed input (FEAT-709 runner registry).
- `.claude/` files may need `git add -f` (memory: FEAT-703). Edit **both** twins.

### Known Risks / Gotchas
- **Portability:** FEAT-633 moves `scripts/` into the package (§8 Q1). The new
  modules must use only package-relative/stdlib imports and no
  `Path(__file__).parents[...]` checkout lookups, so that they relocate unchanged.
- **Agent hooks on Codex:** there is no native subagent dispatch. The twin
  records `fail` with "unsupported on this host" for blocking agent hooks,
  rather than silently passing them.
- **Big screencasts in `/tmp`:** the private-tmp bwrap sandbox. The worktree
  rules say Claude's scratch root `/tmp/claude-<uid>` is bound back in, which is
  why that root is the default. Other hosts must set `SDD_HOOKS_ARTIFACT_ROOT`.
- **Hook commands run arbitrary shell** from a repo-committed file. This is the
  same trust level as `test_runners.toml` and Makefiles. Document it, and do
  not run hooks from an unmerged base config. The config is read from the
  **feature worktree**.
- The test report and E2E gate JSON are passed in the context, so hooks can
  short-circuit.

### External Dependencies
None new (`aiohttp`, `pydantic` already core; `tomllib` stdlib).

---

## 8. Open Questions
- [x] Q1: How do the scripts reach consumer repos? — *Resolved 2026-10-28*: FEAT-633 (branch `feat-FEAT-633-parrot-installer`) moves `scripts/` into the installable package. This feature writes its three modules under `scripts/sdd/` like their siblings, and they migrate with the rest. They stay self-contained (no checkout-relative imports) so the move is mechanical.
- [x] Q2: push vs webhook — *Resolved 2026-10-28*: ship BOTH. A dedicated `push.send` (providers `ntfy`, `gotify`) and a generic `webhook.post`.
- [x] Config location: TOML only — *Resolved in proposal*: `.parrot/sdd_hooks.toml` (more control), no CLAUDE.md section.
- [x] `--resolve-jira` — *Resolved in proposal*: remove the flag; Jira becomes an opt-in `post_pr` hook that checks for a spec-linked ticket.
- [x] Artifacts — *Resolved in proposal*: never committed; written to /tmp, path served; preserving them is the operator's job.
- [x] Dry-run — *Resolved in proposal*: `pre_pr` hooks run under `--dry-run`.
- [x] `/sdd-brief` hotfix closeouts — *Resolved in proposal*: out of scope, follow-up.

---

## 9. Design Research Cross-Check
Status: skipped (proposal status is `review`, not `accepted`)

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy
- Isolation: one feature worktree `feat-FEAT-764-sdd-done-closeout-hooks`.
- Module graph: M2 → M1 (models), M2 → M3 (BUILTINS), M3 → M1 (HookContext/HookResult), M4 → M2 (CLI contract), M5 → M1–M3.
- Shared files: none between modules. M4 alone edits both twins.
- Exclusive resources: none.
- Cross-feature dependencies: none blocking. FEAT-633 will later relocate these scripts into the package; keep them self-contained. Keep in mind FEAT-758, which also edits sdd-done; the merge order is whichever lands first.

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-28 | Claude | Initial spec from proposal |
| 0.2 | 2026-10-28 | Claude | Q1/Q2 resolved: FEAT-633 packaging; add push.send (ntfy, gotify); approved |
