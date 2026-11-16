---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd-tooling, experience-memory, pitfalls, hooks, sandbox, wikitoolkit]
---

# Brainstorm: SDD Experience Memory (`experience.pitfall`)

**Date**: 2026-11-13
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

SDD agents (`sdd-worker`, `sdd-coder`, `/sdd-start` sessions and the non-Claude coder seats) keep
hitting the same operational stones. The motivating case: `gh pr edit` fails on this repository
with a GraphQL "Projects (classic)" deprecation error. Every fresh agent tried it, failed, and
rediscovered the `gh api -X PATCH` workaround — until a human wrote the workaround by hand into
`worktree-management.md`. Nothing an agent learns by trial and error survives its session.

Who is affected: every agent in the SDD flow (wasted turns and tokens, sometimes a failed task),
and the maintainer, who is today the only channel through which a discovery becomes durable.

What we want: when an agent's trial-and-error finds how to get past a failure, that discovery is
recorded without relying on the agent remembering to do it, and the next agent — its "other self"
— is told about it at the moment it matters, not through an ever-growing always-loaded list.

## Constraints & Requirements

Decisions already taken by the owner during discovery (not to be re-litigated by `/sdd-spec`):

- **Substrate is wikitoolkit**, not `WorkingMemoryToolkit`. Own plane/namespace `experience`,
  first category `pitfall`; the schema must admit further categories later (for example a
  fortuitous discovery such as a wiki query result that keeps recurring).
- **Fixed lesson schema**: triggers (command + literal error text), symptom, solution, scope
  (files / tool), state (`candidate` | `confirmed` | `retired`), hit counter.
- **Retrieval is lexical first** (BM25 over a triggers field); hybrid BM25 + embeddings is a
  later, optional step.
- **Deterministic hook points**:
  - A. `/sdd-start`: a deterministic process queries the plane with the task title and files and
    builds a 5-entry bullet briefing.
  - B. `PostToolUse`: records the failure and injects the lesson about that failure.
  - B2. `PreToolUse`: looks up lessons about the command about to run (to learn from syntax
    mistakes with that tool) before it runs. **Advisory only** — it never blocks and never
    rewrites the command.
  - C. Task close: the coder returns `lessons[]`; they are stored as `candidate`.
- **Promotion** `candidate → confirmed` is automatic: recurrence across independent sessions
  **and** evidence that the recorded solution worked after the failure. No human in the path.
- **Candidates are shown only after a failure**, labeled as unverified. Never in the briefing,
  never in `PreToolUse`.
- **Two tiers**: a user-global plane for tool-level lessons (`gh`, `git`, `uv`, …) and a per-repo
  plane for code-specific lessons. Routing is decided **by scope at write time** (a trigger with
  no repo paths goes to the global tier).
- **Graduation**: a confirmed lesson that keeps firing past a threshold opens a ledger issue
  proposing a rule or guard; closing that issue retires the lesson.
- **Full seat parity in v1**: in-process seats intercept in parrot's own tool loop; external CLI
  seats use their native hooks where they exist, and prompt briefing plus transcript mining where
  they do not.
- **Sandbox**: the owner prefers that a sandboxed agent writes lessons directly, over a
  "coder output that the worker reconciles" design.

Hard constraints from the codebase:

- Hooks run on every tool call: a miss must cost a few milliseconds (stdlib-only prefilter, no
  pydantic import, no SQLite open) — the existing wiki nudge hook sets the pattern (FEAT-595).
- A hook that emits `updatedInput` must be idempotent and can displace the sandbox wrapper; the
  new hooks must emit `additionalContext` only.
- Sandboxed worker sessions do not load project `.claude/settings.json` (worktrees have none and
  the launcher passes `--setting-sources project,local`); they only get hooks injected through
  `--settings` and agent frontmatter.
- `$HOME` (including `~/.parrot`) is read-only in both sandbox backends.
- Lesson text is written by one agent and read by another: it is an injection and
  error-amplification channel and must be treated as data (bounded, templated, redacted).
- Literal error text may contain secrets or tokens; it must be redacted before it is stored,
  especially if any part of the plane is git-tracked.

---

## Options Explored

### Option A: Lessons as pages in the main wiki plane

Store each lesson as a memory page in the existing project wiki (`.parrot/wiki/wiki.db`) with
`category="pitfall"`, structured fields in `page_attrs`, and triggers duplicated into the body so
FTS finds them. Hooks and the briefing call the existing `search_fts(category="pitfall")`. The
sandbox is changed to make `<primary>/.parrot/wiki` writable so agents call
`wikitoolkit remember` directly. The global tier is a second wiki registered in
`~/.parrot/wikis.json`.

✅ **Pros:**
- Smallest amount of new machinery: `remember`, `query --category`, `page_attrs`, namespaces and
  the global registry all exist.
- One query surface: `wikitoolkit query` returns lessons next to code pages.
- Matches the owner's literal preference ("open the wiki in the sandbox").

❌ **Cons:**
- Opens a ~920 MB SQLite file that holds the whole code knowledge graph to writes from a
  sandboxed worker; the code states the opposite intent today ("the wiki plane and the rest of
  `.parrot` stay read-only").
- Hit counters and state changes are in-place row updates from several parallel coders: SQLite
  write contention on the same database the wiki build and every `query` use.
- No history: a lesson overwritten or wrongly confirmed leaves no trail to audit or revert.
- Worktrees reach the primary wiki only because they live under `.parrot/worktrees/`; wiki root
  resolution does not use the shared root.
- Nothing is shareable with the team (the plane is gitignored) without a new export path.
- `wikitoolkit build` and lint rules would have to learn to leave these pages alone.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlite3` (stdlib, FTS5) | storage and BM25 | already the wiki backend |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — `remember`, `query --category/--ns`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — `WikiPageRecord.attrs`, `upsert_attrs`, `list_by_attrs`, `search_fts`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — `WikiNamespaceConfig`, `GlobalWikiRegistry`

---

### Option B: Dedicated event-sourced experience plane on the wiki engine

A separate, small plane with its own directory (`<shared-root>/.parrot/experience/`), built from
the same wikitoolkit parts but not inside the code graph:

- **Source of truth is an append-only event log** (same primitive the work ledger uses):
  `lesson.recorded`, `failure.observed`, `lesson.injected`, `lesson.validated`,
  `lesson.refuted`, `lesson.confirmed`, `lesson.graduated`, `lesson.retired`.
- **A reducer** folds the log into a small wiki store (pages with `category="pitfall"`, attrs for
  the structured fields, triggers in the FTS-indexed body) and into a tiny **trigger index** file
  (executable → lesson ids) that hooks read without opening SQLite.
- Hit counts, recurrence and promotion are **derived from events**, never stored as mutable
  counters: "confirmed" means the log holds validations from N distinct sessions.
- One CLI noun, `parrot sdd experience <verb>` (`brief`, `hook`, `record`, `mine`, `sync`,
  `list`, `show`, `retire`), is the single entry point behind every host's hook, the briefing,
  the in-process dispatcher and the transcript miner.
- The sandbox gains exactly one writable directory, `.parrot/experience/`; the code wiki stays
  read-only.

✅ **Pros:**
- Append-only writes are safe under parallel coders (`O_APPEND` + `fsync`), with no contention on
  the code wiki.
- Full audit trail: who recorded a lesson, where it was injected, whether it helped; a wrong
  lesson can be refuted and retired by events, and the store rebuilt.
- Recurrence + evidence promotion and the graduation threshold are plain reductions over events.
- Narrow sandbox change: one small directory instead of the whole wiki plane.
- A share path exists by construction: definition events can be exported to a git-tracked log
  the way the ledger does, keeping noisy hit events local.
- Extensible to other categories without touching the schema of the code wiki.

❌ **Cons:**
- More new code than A: event model, reducer, trigger index, CLI noun.
- Lessons are not returned by a plain `wikitoolkit query` unless the plane is also registered as
  a read-only namespace (cheap, but one more moving part).
- A second place under `.parrot/` to explain, back up and migrate.
- Still requires touching the pinned sandbox path tests and policy docs.

📊 **Effort:** High (dominated by full seat parity, not by the store)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlite3` (stdlib, FTS5) | reduced store and BM25 | same backend as the wiki |
| `pydantic` v2 | event and lesson models | already a core dependency; kept out of the hook fast path |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` — `LedgerLog` append-only primitive
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` — event id/shape conventions (`LedgerEvent`, `InsightRecordedPayload`)
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — `SQLiteWikiStore`, `page_attrs`, `search_fts`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — `find_shared_root`, `GlobalWikiRegistry`
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py` — stdlib prefilter + stamp-file cooldown pattern
- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` — `shared_ledger_dirs` / `coder_evidence_dirs` as the template for one more writable directory
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` — `_run_tool` / `_tool_run_command` choke point for in-process seats

---

### Option C: No runtime plane — offline transcript mining compiled into a digest

Do nothing while agents run. After the fact (at `/sdd-done`, or on a schedule) a miner reads the
session transcripts and dispatcher event streams, detects "command failed → later variant
succeeded" pairs, and proposes lessons. Accepted lessons are compiled into a static, scoped
digest file that is pasted into every coder brief and `/sdd-start` context; lessons that recur
are turned straight into rule/guard pull requests.

✅ **Pros:**
- Zero runtime latency and zero new hooks; no sandbox change at all.
- Uniform across every seat, including external CLIs, because it never needs to intercept.
- Detection is fully deterministic and does not depend on the agent noticing it learned anything.

❌ **Cons:**
- No injection at the point of failure — the one mechanism that would have fixed `gh pr edit`
  for an agent whose task did not obviously involve pull requests.
- The digest is an always-loaded list again: it recreates the "90 entries in every session"
  problem this feature is meant to avoid.
- Slow loop: a lesson helps nobody until the next mining run.
- No durable per-command log exists today for most seats (the per-tool events live in a Redis
  stream capped at about 60 entries), so the miner would first need new logging.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | stdlib JSONL parsing |

🔗 **Existing Code to Reuse:**
- `scripts/sdd/token_audit.py` — already walks `~/.claude/projects/**` transcripts, subagents included
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` — `command_execution` items carrying `exit_code`

---

## Recommendation

**Option B** is recommended because:

- The owner's decisions (automatic promotion by recurrence + evidence, candidates shown only
  after a failure, graduation by hit threshold, retirement) are all statements about *history*.
  An event log gives them for free; Option A would have to emulate history with mutable counters
  in a shared SQLite file written by parallel coders.
- It honors the intent of "let the sandboxed agent write directly" while keeping the code wiki
  read-only: one small writable directory instead of the 920 MB graph. This is a deliberate
  deviation from the literal "open the wiki" preference and is flagged as an open question.
- Option C's miner is not discarded: it becomes the fallback capture path for external CLI seats
  that cannot run a post-tool hook, which is exactly the parity rule the owner chose.

What is traded off: more new code than A and a second plane under `.parrot/`. Acceptable because
the store itself is small; the real cost of the feature is seat parity, which every option that
injects at the point of failure pays equally.

---

## Feature Description

### User-Facing Behavior

For the maintainer:

- Nothing to do in the normal case. Agents stop repeating known failures.
- `parrot sdd experience list|show <id>` shows lessons with state, hit count, validations and the
  sessions that produced them; `retire <id>` removes a wrong one.
- When a lesson keeps firing, a `tech_debt` issue appears in the work ledger proposing a rule or
  guard; `/sdd-fix` drains it like any other issue.

For an agent:

- **At task start** it receives a "Known pitfalls" block of at most 5 bullets relevant to its
  task (confirmed lessons only), in its brief or `/sdd-start` context.
- **Before a command** matching a confirmed lesson, it sees a short advisory ("known pitfall for
  `gh pr edit` in this repository: … use …"). The command still runs as written.
- **After a failed command** it sees the matching lesson, if one exists; a `candidate` is shown
  labeled as unverified.
- **At task close** it may return `lessons[]`; it can also record one directly with
  `parrot sdd experience record`.

### Internal Behavior

**Lesson record.** Identity is a hash of the normalized trigger signature, so the same stone
recorded twice merges instead of duplicating. Fields: category (`pitfall` in v1), triggers
(executable, subcommand, normalized error signature, literal excerpts), symptom, solution, scope
(tool-level or a list of repo paths), tier (`repo` | `global`), state, provenance (seat, model,
session/run id, task). A schema version is carried so new categories can be added.

**Failure signature.** Built deterministically from the leading executable, its subcommand and
the error text with volatile parts removed (absolute paths, hashes, numbers, timestamps, temp
names). Secrets are redacted before anything is stored.

**Capture — three sources, all landing as `candidate`:**

1. *Deterministic pairing.* The post-tool hook appends `failure.observed`. When a later command
   in the same session with the same executable and subcommand family succeeds, the pair
   (failed command, error signature, succeeding command) becomes a drafted lesson. This needs no
   cooperation from the model.
2. *Agent-authored.* `lessons[]` in the coder's final output, or a direct
   `parrot sdd experience record`. These carry the prose (symptom, solution) the pairing cannot
   write. An authored lesson whose signature matches a drafted one enriches it.
3. *Mining.* For seats with no post-tool hook, the dispatcher's own stream of command results
   (or the session transcript) is replayed through the same pairing logic when the attempt ends.

**Retrieval — three injection points behind one command:**

- *Briefing (A).* `parrot sdd experience brief --task-file <task.md>` queries with the task
  title and the files the task lists, keeps confirmed lessons, and prints at most 5 bullets
  under a token budget. `/sdd-start` calls it at its context-priming step; the coder engine puts
  the same text in a dedicated field of the task brief — not in the coder-feedback text, whose
  size is measured for the with/without-feedback comparison.
- *Pre-tool (B2).* A stdlib prefilter looks up the leading executable in the trigger index. On a
  miss it exits immediately. On a hit it loads the confirmed lessons for that executable, matches
  subcommand and flags, and emits advisory context. A per-session, per-lesson cooldown prevents
  repeating the same advice.
- *Post-tool (B).* Runs only for failed calls: builds the signature, searches both tiers,
  injects the best match above a score threshold (confirmed, or candidate labeled unverified),
  and appends `failure.observed` and `lesson.injected`.

**Evidence and promotion.** After a lesson is injected for a failure, the next command of the
same family in that session decides: success appends `lesson.validated`, failure appends
`lesson.refuted`. The reducer marks a lesson `confirmed` once it has validations from N distinct
sessions (default 2) and no unresolved refutation; enough refutations quarantine it. Independent
rediscovery (a second session drafting the same signature and fix) counts as a validation.

**Two tiers.** The repo plane lives at `<shared-root>/.parrot/experience/`, resolved through the
shared root so every linked worktree sees the primary's plane regardless of where the worktree
sits. The global plane lives under `PARROT_HOME`. A lesson whose triggers mention no repo path
and whose executable is a general tool is tagged `global`. Because `$HOME` is read-only in the
sandbox, a sandboxed session appends global-tagged lessons to the repo log; a host-side
`parrot sdd experience sync` (run by the launcher entry point and by `/sdd-done`) moves them to
the global plane. Reads always consult both tiers.

**Graduation and retirement.** When a confirmed lesson passes the hit threshold, the reducer
opens one ledger issue (idempotent per lesson) proposing the rule or guard and records
`lesson.graduated` with the issue id. When that issue is closed the lesson is retired and stops
being injected.

**Seat parity.**

| Seat | Loop owner | Pre | Post | Capture |
|---|---|---|---|---|
| native Claude coder, `claude-code` dispatcher, `sdd-worker` | Claude Code | native hook (via `--settings` and agent frontmatter) | native hook | pairing + `lessons[]`/`record` |
| `nova`, `google-compat`, other in-process seats | parrot | in the dispatcher's tool choke point | same choke point, where failure is already observed | pairing + `lessons[]` |
| `codex` | codex CLI | existing `.codex/hooks.json` hook chain | native hook if codex supports one; otherwise none | dispatcher replays `command_execution` items at attempt end |
| `agy` / `google_coding`, `gemini` | external CLI | existing `.agents/hooks.json` hook chain | native after-tool hook where supported | stream replay at attempt end |

**Sandbox.** One more writable directory in both backends, modelled on the existing ledger and
coder-evidence directories. The directory, not a file, is bound (SQLite sidecar files), and it
must exist before the bind.

### Edge Cases & Error Handling

- **Hooks never fail a tool call.** Any error in lookup, reduction or logging is swallowed and
  the hook exits silently, as the wiki nudge hook does.
- **Plane missing or not built**: hooks are no-ops; the briefing prints nothing.
- **Wrong or malicious lesson**: text is rendered inside a fixed template as quoted data with a
  length cap; a lesson can never change a permission decision or rewrite a command; candidates
  are never shown proactively; refutations quarantine it; `retire` removes it.
- **Self-reinforcement**: a validation only counts when it comes from a different session than
  the one that recorded the lesson.
- **Noise**: failures that are the task's own work (a failing test under development, a lint
  error) must not become lessons — pairing is limited to an allowlist of tool executables or
  excludes the validation runners; the exact rule is an open question.
- **Parallel coders**: all writes are appends; the reducer is idempotent and can run
  concurrently behind a lock file.
- **Oversized error text**: the log line cap applies; excerpts are truncated after redaction.
- **Cross-machine**: hit and validation events stay local; only lesson definitions would be
  shared if the repo tier is git-tracked (open question).
- **Lesson fixed upstream**: a retired lesson's signature is remembered so the same failure is
  not re-learned while its ledger issue is still being worked.

---

## Capabilities

### New Capabilities
- `experience-plane`: event log, reducer, reduced store and trigger index for lessons, two tiers.
- `experience-cli`: `parrot sdd experience` noun (`brief`, `hook`, `record`, `mine`, `sync`, `list`, `show`, `retire`).
- `experience-briefing`: deterministic 5-entry pitfall briefing at task start.
- `experience-hooks-claude`: advisory `PreToolUse` and failure-driven `PostToolUse` hooks for Claude Code sessions.
- `experience-inprocess-interception`: pre/post interception in the in-process coder dispatcher.
- `experience-cli-seat-adapters`: native hook wiring and end-of-attempt replay for codex / agy / gemini seats.
- `experience-promotion`: recurrence + evidence promotion, refutation and quarantine.
- `experience-graduation`: ledger issue on hit threshold, retirement on close.

### Modified Capabilities
- `sdd-worktree-sandbox`: one more writable directory in the Bubblewrap and native backends.
- `sdd-coder-orchestrator` (FEAT-549): new briefing field on the task brief; `lessons` on the coder output; codex strict output schema.
- `sdd-start` command: deterministic briefing call at context priming.
- `sdd-worker` / `sdd-coder` agent definitions: hook registration and the `lessons[]` contract.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/` (new `experience/` subpackage) | extends | event model, reducer, store wiring; reuses `LedgerLog` and `SQLiteWikiStore` |
| `parrot/sdd/cli.py` | extends | new `experience` noun; release smoke scenarios need an entry for new `parrot sdd` helpers |
| `parrot/sdd/scripts/worktree_environment.py`, `native_claude_sandbox.py` | modifies | one writable directory; about ten tests pin the exact path lists |
| `.claude/rules/worktree-management.md` + asset twin, `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` | modifies | sandbox policy text |
| launcher `--settings` hook injection, `sdd-worker.md` / `sdd-coder.md` frontmatter | modifies | first `PostToolUse` hook in the repository |
| `parrot/flows/dev_loop/dispatchers/llm.py` | modifies | interception at `_run_tool` / `_tool_run_command` |
| `parrot/flows/dev_loop/dispatchers/codex.py`, `google_coding.py`, `gemini.py` | modifies | end-of-attempt replay; codex output schema is `additionalProperties: false` |
| `parrot/flows/dev_loop/models/base.py` | modifies | `TaskScopedBrief` briefing field, `DevelopmentOutput.lessons` (unknown keys are dropped today) |
| `parrot/flows/dev_loop/sdd_coder/engine.py`, `models.py` | modifies | brief assembly for MCP and native seats |
| `.codex/hooks.json`, `.agents/hooks.json`, `parrot/sdd/installer.py` | modifies | hook chains installed for other hosts |
| `.claude/commands/sdd-start.md` + asset twin and Codex/agy skill twins | modifies | briefing step |
| work ledger | depends on | graduation issues; no schema change if issues are opened through the public CLI |

No new third-party dependency. No breaking change: with the plane absent every hook is a no-op.

---

## Code Context

### User-Provided Code

None. The owner provided requirements and decisions only (see Constraints & Requirements).

### Verified Codebase References

Paths are relative to `packages/ai-parrot/src/parrot/` unless they start with `.` or `scripts/`.

#### Classes & Signatures
```python
# knowledge/wiki/operations.py:351
async def op_remember(store: BaseWikiStore, params: WikiRememberInput, **context: Any) -> OperationResult: ...

# knowledge/wiki/store.py:606
class WikiPageRecord(BaseModel):
    # concept_id, node_id, title, category, summary, body, source_id, token_count,
    # origin, asserted_by, updated_at, content_hash, attrs: dict[str, str]

# Each of the four below is declared twice in store.py: on the abstract base
# (:907, :895, :949, :952) and on the SQLite implementation (lines given here).
# knowledge/wiki/store.py:2506
async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int: ...
# knowledge/wiki/store.py:2566
async def list_by_attrs(...): ...
# knowledge/wiki/store.py:2938
async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...
# knowledge/wiki/store.py:2989
async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]: ...  # not used by `query`

# knowledge/wiki/search.py:32
class WikiCombinedSearch: ...          # lexical + vector merge, only when an embedder is passed

# knowledge/wiki/project.py:187
class WikiNamespaceConfig(BaseModel): ...   # extra="forbid"; one of path/store/database/vault
# knowledge/wiki/project.py:437
class GlobalWikiRegistry(BaseModel): ...    # $PARROT_HOME/wikis.json
# knowledge/wiki/project.py:1050
def find_project_root(start: Path | None = None) -> Path | None: ...   # nearest .parrot/wiki.json, else nearest .git
# knowledge/wiki/project.py:1563
def find_shared_root(start: Path | None = None) -> Path | None: ...    # used by the ledger, NOT by wiki store resolution

# knowledge/wiki/ledger/log.py:10
class LedgerLog: ...                        # append: O_APPEND + fsync, 4 KiB line cap
# knowledge/wiki/ledger/events.py:103
class LedgerEvent(BaseModel): ...           # event_id, kind (closed list), subject, actor, ts, payload
# knowledge/wiki/ledger/events.py:75
class InsightRecordedPayload(BaseModel): ...   # fact, title, category, derived_from, about

# knowledge/wiki/ledger/coder_feedback.py:24
class CoderFeedback(BaseModel): ...         # extra="forbid"; lesson_scope: Literal["model"]

# knowledge/wiki/claude_code/hook.py:250
def run_pre_tool_use_hook(stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> int: ...
# knowledge/wiki/claude_code/hook.py:193
def build_nudge(payload: dict[str, Any], root: Optional[Path] = None,
                config: Optional[WikiProjectConfig] = None, now: Optional[float] = None) -> Optional[dict[str, Any]]: ...

# sdd/scripts/worktree_environment.py:299
def protected_argv(cwd: Path, argv: Sequence[str], *, derive_pythonpath: bool = False) -> list[str]: ...
# sdd/scripts/worktree_environment.py:214 / :243
def shared_ledger_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]: ...    # <primary>/.parrot/ledger, bound only if it exists
def coder_evidence_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]: ...   # <primary>/artifacts/logs/sdd-coder-usage
# sdd/scripts/worktree_environment.py:1026
def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]: ...   # emits updatedInput or deny

# sdd/scripts/native_claude_sandbox.py:410
def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = (),
                            include_sandbox: bool = True) -> dict[str, Any]: ...
# sdd/scripts/native_claude_sandbox.py:922
def _prefix_writable_roots(cwd: Path) -> tuple[Path, ...]: ...     # refusal list, not a mount list

# flows/dev_loop/dispatchers/llm.py:1520
async def _run_tool(self, *, tool_name: str, tool_args: Dict[str, Any], cwd: str,
                    profile: LLMCodeDispatchProfile) -> Dict[str, Any]: ...
# flows/dev_loop/dispatchers/llm.py:1956
async def _tool_run_command(self, cwd: str, args: Dict[str, Any],
                            profile: LLMCodeDispatchProfile) -> Dict[str, Any]: ...   # ok = exit_code == 0
# flows/dev_loop/dispatchers/llm.py:2199
async def _run_argv(self, argv: Sequence[str], *, cwd: str, timeout: int,
                    stdin: Optional[str] = None) -> Dict[str, Any]: ...

# flows/dev_loop/models/base.py:527
class DevelopmentOutput(BaseModel):
    files_changed: List[str]
    commit_shas: List[str]
    summary: str
    incomplete_tasks: List[str] = []
    worker_summaries: List[WorkerSummary] = []
    merge_performed: bool = False
# flows/dev_loop/models/base.py:478
class TaskScopedBrief(BaseModel): ...       # research, task_id, task_file, coder_feedback, validation_verdict

# flows/dev_loop/sdd_coder/engine.py:2743
async def _feedback_for(self, ctx: _FeatureCtx, task: PlannedTask, backend: str, model: str) -> str: ...
# flows/dev_loop/sdd_coder/toolkit.py:427
async def coder_task_context(self, feature: str, worktree: str, task_id: str, execution_id: str) -> CoderResult: ...
```

#### Verified Imports
```python
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.project import find_shared_root, GlobalWikiRegistry
from parrot.knowledge.wiki.store import WikiPageRecord
from parrot.flows.dev_loop.models.base import DevelopmentOutput, TaskScopedBrief
```

#### Key Attributes & Constants
- Memory page id → `"mem-" + sha1(f"{title}::{category}")[:12]` (`knowledge/wiki/cli.py:4904`, `operations.py:377`)
- Memory `category` → free text, no enum, no `click.Choice` (`knowledge/wiki/cli.py:4817`)
- FTS index columns → `pages_fts(title, summary, body)`; attrs are **not** indexed (`knowledge/wiki/store.py:209`)
- `page_attrs(concept_id, key, value)` table with a `(key, value)` index (`knowledge/wiki/store.py:74`)
- Wiki plane path → `.parrot/wiki/wiki.db` (`knowledge/wiki/project.py:776`); gitignored
- Ledger local state → `<shared>/.parrot/ledger/` (`knowledge/wiki/ledger/service.py:186`)
- Native sandbox `allowWrite` → worktree, common `.git`, scratch root, worktree admin dirs, ledger dir, coder-evidence dir (`sdd/scripts/native_claude_sandbox.py:424`)
- Sandbox intent → "the wiki plane and the rest of `.parrot` stay read-only" (`sdd/scripts/worktree_environment.py:219`)
- Nudge hook output → `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ...}, "suppressOutput": true}` (`knowledge/wiki/claude_code/hook.py:241`)
- `SeatKind = Literal["mcp", "native"]` (`flows/dev_loop/sdd_coder/models.py:30`)
- In-process failure observation → `tool_result.get("ok") is False` (`flows/dev_loop/dispatchers/llm.py:595`)
- codex command results → `command_execution` items with `exit_code` (`flows/dev_loop/dispatchers/codex.py:783`)
- codex final-output schema → `additionalProperties: false` (`flows/dev_loop/dispatchers/codex.py:81`)
- `parrot sdd task` verbs → `close, finalize, heal, graph, state, review` (`sdd/cli.py:275`)
- `/sdd-start` ledger priming is prose executed by the model (`.claude/commands/sdd-start.md:167`)
- Other hosts' hook files → `.codex/hooks.json` (PreToolUse Bash), `.agents/hooks.json` (PreToolUse `run_command|write_file|edit_file`)
- Dormant multi-host nudge installer incl. Gemini `AfterTool` → `knowledge/wiki/coding_agents.py:44`

### Does NOT Exist (Anti-Hallucination)
- ~~any `PostToolUse` hook~~ — none registered for any host; the string appears only in tests
- ~~page hit / access counter in the wiki~~ — `usage_operations.py` reports per-FEAT token cost, not page hits
- ~~`DevelopmentOutput.lessons` / notes / findings field~~ — only `summary` is free-form; unknown keys are silently dropped
- ~~`parrot sdd task start`~~ — no task-start verb exists
- ~~`parrot sdd experience`~~ — the noun does not exist yet
- ~~namespace argument on MCP `wiki_remember`~~ — it always writes the local plane
- ~~per-field BM25 boosts~~ — plain `bm25(pages_fts)` with no column weights
- ~~embeddings on the `query` / `remember` path~~ — vector code exists but is wired only for execution-run pages
- ~~writable `<primary>/.parrot/wiki` or any `$HOME` path in the sandbox~~ — read-only in both backends
- ~~in-process hook callbacks for the `claude-code` seat~~ — `ClaudeAgentRunOptions` has no `hooks` field; only settings-JSON command hooks
- ~~durable per-command log for any seat~~ — per-tool events go to a Redis stream capped at about 60 entries
- ~~open-ended `kind` on `LedgerEvent`~~ — the kind list is closed
- ~~insights in `wikitoolkit ledger context` output~~ — it returns open/claimed issues only
- ~~a coder-facing `coder_task_context`~~ — only the orchestrator can call it; coders have no MCP tools

---

## Parallelism Assessment

- **Internal parallelism**: good after a short sequential core. The plane (events, reducer,
  store, CLI noun) must land first. After it, five streams are independent: Claude hooks and
  launcher wiring; in-process dispatcher interception; codex/agy/gemini adapters; sandbox
  writable directory; briefing integration (`/sdd-start` + engine brief). Promotion and
  graduation depend only on the core.
- **Cross-feature independence**: touches hot files — `sdd_coder/engine.py`,
  `dispatchers/llm.py`, `worktree_environment.py`, `native_claude_sandbox.py`, `sdd/cli.py` and
  the `sdd-worker` / `sdd-coder` agent definitions (three identical copies of conventions and
  asset twins). Any in-flight SDD-tooling fix on those files will conflict; FEAT-886
  (`durable-conversation-memory`) is unrelated (`parrot.memory`).
- **Recommended isolation**: mixed.
- **Rationale**: one worktree for the core, then parallel sub-worktrees per stream; the streams
  share only the core's public CLI, so they merge cleanly if the agent-definition edits are
  owned by a single task.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] What promotes `candidate → confirmed` — *Owner: Jesus Lara*: recurrence across independent sessions plus evidence that the fix worked; no human in the path.
- [x] Are candidates visible to agents — *Owner: Jesus Lara*: only after a matching failure, labeled unverified.
- [x] Where the plane lives — *Owner: Jesus Lara*: two tiers, user-global for tools and per-repo for code.
- [x] How a lesson reaches the global tier — *Owner: Jesus Lara*: by scope at write time.
- [x] `PreToolUse` behavior on a match — *Owner: Jesus Lara*: advisory only; never blocks or rewrites.
- [x] Graduation — *Owner: Jesus Lara*: opens a ledger issue past a hit threshold; closing it retires the lesson.
- [x] Non-Claude seats in v1 — *Owner: Jesus Lara*: full parity; native hooks where the CLI has them, briefing plus transcript mining where it does not.
- [ ] Dedicated `.parrot/experience/` directory (recommended) versus opening `.parrot/wiki` itself as the owner first preferred — *Owner: Jesus Lara*
- [ ] Global tier writes from a sandbox: repo-side outbox moved by a host `sync` (recommended, `$HOME` stays read-only) versus binding one `PARROT_HOME` subdirectory writable — *Owner: Jesus Lara*
- [ ] Is the repo tier shared through git (definition events exported like the ledger's shared log, hit events local) or local-only in v1 — *Owner: Jesus Lara*
- [ ] Thresholds: N distinct sessions to confirm (proposed 2), refutations to quarantine (proposed 2), hits to graduate (proposed 5 across 3 sessions) — *Owner: Jesus Lara*
- [ ] Which failures are eligible for pairing: an allowlist of tool executables, or everything except validation runners (pytest, ruff, …) — *Owner: spec author*
- [ ] Does Claude Code fire `PostToolUse` for a Bash call with a non-zero exit, or a separate failure event, and what does the payload carry (exit code, stderr) — *Owner: spec author (verify against Claude Code hook docs before the spec)*
- [ ] Do codex and agy expose a post-tool hook today; if not, confirm end-of-attempt replay is accepted as parity for them — *Owner: spec author*
- [ ] Is `parrot` on the allowlisted binaries of in-process seats, so they can call `experience record`, or is `lessons[]` their only path — *Owner: spec author*
- [ ] Native Claude coder output is never parsed by parrot: are its `lessons[]` relayed by the worker, or does it only use `experience record` — *Owner: spec author*
- [ ] Should the experience plane also be registered as a read-only wiki namespace so `wikitoolkit query --ns experience` returns lessons — *Owner: Jesus Lara*
- [ ] Hybrid retrieval (existing `WikiCombinedSearch`) for write-time deduplication: in v1 or deferred — *Owner: Jesus Lara*
