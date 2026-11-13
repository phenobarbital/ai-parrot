---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd-tooling, experience-memory, pitfalls, hooks, sandbox, wikitoolkit]
docs:
  policy: required
  pages:
    - wiki/sdd-tooling/sdd/experience-memory.md
    - wiki/sdd-tooling/dev_loop/claude-native-sandbox.md
  api_modules:
    - parrot.knowledge.wiki.experience
---

# Feature Specification: SDD Experience Memory (`experience.pitfall`)

**Feature ID**: FEAT-887
**Date**: 2026-11-13
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

SDD agents (`sdd-worker`, `sdd-coder`, `/sdd-start` sessions and the non-Claude coder seats) keep
hitting the same operational stones. The motivating case: `gh pr edit` fails on this repository
with a GraphQL "Projects (classic)" deprecation error. Every fresh agent tried it, failed, and
rediscovered the `gh api -X PATCH` workaround — until a human wrote the workaround by hand into
`worktree-management.md`. Nothing an agent learns by trial and error survives its session.

Affected: every agent in the SDD flow (wasted turns and tokens, sometimes a failed task), and the
maintainer, who is today the only channel through which a discovery becomes durable.

Wanted: when an agent's trial and error finds how to get past a failure, the discovery is
recorded without relying on the agent remembering to do it, and the next agent is told about it
at the moment it matters — not through an ever-growing always-loaded list.

### Goals

- G1. An **experience plane** on wikitoolkit parts (not `WorkingMemoryToolkit`), with its own
  directory and namespace `experience`; first category `pitfall`, schema open to more categories.
- G2. A fixed lesson schema: triggers (command + literal error text), symptom, solution, scope,
  state, hit counter (derived).
- G3. Lexical retrieval (BM25) over a triggers-bearing body. Hybrid retrieval is deferred.
- G4. Three deterministic injection points: a 5-entry briefing at task start, an advisory before a
  matching command, and the lesson after a matching failure.
- G5. Capture that does not depend on the model: deterministic failure→success pairing, plus
  agent-authored `lessons[]` and a direct `record` command.
- G6. Automatic promotion `candidate → confirmed` by recurrence across independent sessions plus
  evidence that the fix worked. Candidates are shown only after a matching failure, labeled
  unverified.
- G7. Two tiers: user-global (tool-level lessons) and per-repo, routed by scope at write time.
- G8. Graduation: a confirmed lesson past a hit threshold opens a ledger issue; closing the issue
  retires the lesson.
- G9. Seat parity in v1 across Claude seats, in-process seats, `codex` and `agy`.
- G10. A sandboxed agent writes lessons directly into one dedicated writable directory; the code
  wiki stays read-only.
- G11. Lesson definitions are shared with the team through a git-tracked log; hit and validation
  events stay local.

### Non-Goals (explicitly out of scope)

- Storing lessons in the main wiki plane or opening `.parrot/wiki` to sandbox writes — rejected
  in brainstorm (Option A).
- An offline-only design with an always-loaded digest — rejected in brainstorm (Option C); only
  its end-of-attempt replay survives, as the capture fallback.
- Hybrid BM25 + embeddings retrieval or embedding-based deduplication.
- Categories other than `pitfall`.
- Blocking or rewriting a command from a hook. Hooks are advisory.
- Hook wiring for the Gemini CLI (not installed on the reference host); the `gemini` dispatcher
  gets end-of-attempt replay only.
- Matchers other than shell commands (`Bash` / `run_command`); file-edit tools are not observed.
- Making `$HOME` writable in the sandbox.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:f77ebe534ebbf5e8a1d39aaec6d78a6862840d3d2687a5906289da99d62d2356 evaluation_digest=sha256:db0e36abdd61832f8bca1575bb79853bbc5b6bdb5ae69aaa7821dd55b45043e8 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

A small, dedicated plane, separate from the code knowledge graph:

- **Source of truth is an append-only event log** per tier. Counters and state are never stored
  as mutable fields; they are reductions over events.
- **A reducer** folds events into (a) a small wiki store (`category="pitfall"` pages, structured
  fields in `page_attrs`, triggers repeated in the FTS-indexed body) and (b) a `triggers.json`
  file mapping executables to lesson stubs, which hooks read without opening SQLite.
- **One CLI noun**, `parrot sdd experience`, is the single entry point behind every host's hook,
  the briefing, the in-process dispatcher and the end-of-attempt replay.

Locations:

| Tier / artifact | Path | Tracked | Writable in sandbox |
|---|---|---|---|
| repo plane | `<shared-root>/.parrot/experience/` (`events.jsonl`, `wiki.db`, `triggers.json`, `sessions/`, `index.lock`) | no | yes (new) |
| global plane | `$PARROT_HOME/experience/` (same layout) | no | no (read-only) |
| shared definitions | `sdd/experience/lessons.jsonl` | yes, `merge=union` | via the worktree |

`<shared-root>` is resolved with `find_shared_root`, so every linked worktree uses the primary
checkout's plane wherever the worktree lives.

What an agent experiences:

- **Task start**: a "Known pitfalls" block of at most 5 bullets (confirmed lessons only).
- **Before a command** that matches a confirmed lesson: a short advisory. The command runs as
  written.
- **After a failed command**: the matching lesson if one exists; a candidate is labeled
  unverified.
- **Task close**: optional `lessons[]` in the final output, or `parrot sdd experience record`.

What the maintainer sees: `parrot sdd experience list|show|retire`, and a `tech_debt` ledger
issue when a lesson keeps firing.

**Lesson identity.** `lesson_id = "pit-" + sha1(signature)[:12]`, where the signature is the
normalized trigger (executable, subcommand, normalized error). The same stone recorded twice
merges.

**Failure signature.** Deterministic: leading executable, subcommand, and the error text with
volatile parts removed (absolute paths, hex hashes, numbers, timestamps, temp names). Secrets are
redacted before anything is stored.

**Capture — three sources, all landing as `candidate`:**

1. *Pairing.* The failure hook appends `failure.observed` and notes the failure in a per-session
   file. When a later command in the same session with the same executable and subcommand
   succeeds, the pair becomes a drafted lesson (`source="paired"`).
2. *Authored.* `lessons[]` in the coder output, or `parrot sdd experience record`
   (`source="authored"`). An authored lesson with a matching signature enriches the draft.
3. *Replay.* For seats whose CLI cannot run a hook, the dispatcher replays the command outcomes
   it saw on the event stream through the same pairing logic when the attempt ends
   (`source="mined"`). Replay is skipped when hooks already recorded events for that session.

Pairing ignores validation runners and read-only utilities (configurable exclusion list), so a
failing test under development does not become a lesson.

**Evidence and promotion.** After a lesson is injected for a failure, the next command of the
same family in that session decides: success → `lesson.validated`, failure → `lesson.refuted`.
A second session that independently drafts the same signature counts as a validation. A lesson
becomes `confirmed` once validations come from `confirm_sessions` distinct sessions (default 2),
none of them the recording session, with no unresolved refutation. `quarantine_refutations`
refutations (default 2) quarantine it.

**Tier routing.** A draft whose triggers contain no repo path and whose executable is not a
repo-local script is tagged `tier="global"`. Sandboxed sessions cannot write `$HOME`, so
global-tagged events are appended to the repo log; a host-side `sync` moves them to the global
plane. Reads always consult both tiers.

**Sharing.** `export` appends not-yet-exported definition events (`lesson.recorded`,
`lesson.confirmed`, `lesson.retired`, `lesson.graduated`) to `sdd/experience/lessons.jsonl` in
the current checkout, redacted. The reducer treats that file as a second event source, so no
import step exists. Hit and validation events are never exported.

**Graduation.** When a confirmed lesson passes `graduate_hits` injections across
`graduate_sessions` sessions (defaults 5 and 3), one `tech_debt` ledger issue is opened
(idempotent per lesson) and `lesson.graduated` records its id. When that issue is closed the
lesson is retired.

**Seat parity.**

| Seat | Loop owner | Before | After | Capture |
|---|---|---|---|---|
| native Claude coder, `claude-code` dispatcher, `sdd-worker`, interactive `/sdd-start` | Claude Code | `PreToolUse` hook, `additionalContext` | `PostToolUse` + `PostToolUseFailure` hooks, `additionalContext` | pairing + `lessons[]` / `record` |
| `nova`, `google-compat`, other in-process seats | parrot | interceptor at the tool call site | same site, advice attached to the tool result | pairing + `lessons[]` |
| `codex` | codex CLI | `PreToolUse` hook, `additionalContext` | `PostToolUse` hook, `additionalContext` | pairing by hook; replay as fallback |
| `agy` / `google_coding` | agy CLI | briefing only (its pre-hook must emit a decision) | `PostToolUse` records; `PostInvocation` injects the pending advice | pairing by hook; replay as fallback |
| `gemini` | gemini CLI | briefing only | none | replay |

**Design research.** Skipped: the exploration document's status was `exploration`, not
`accepted` (see §9).

### Component Diagram

```
 Claude / codex / agy hook ─┐
 in-process interceptor ────┼─→ experience_hook (stdlib fast path)
 dispatcher replay ─────────┘        │ reads                    │ appends
                                     ▼                          ▼
                              triggers.json            events.jsonl (repo tier)
                                     ▲                          │
                                     │ writes                   │ reads
                              ExperienceIndex ◄── reducer ◄─────┼── sdd/experience/lessons.jsonl
                                     │                          └── $PARROT_HOME/experience/events.jsonl
                                     ▼
                           wiki.db (FTS, category=pitfall)
                                     ▲
     parrot sdd experience brief ────┤
     ExperienceService.search ───────┘──→ promote / graduate ──→ LedgerService.open_issue
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SQLiteWikiStore` / `create_wiki_store` | uses | reduced store; `page_attrs` for structured fields, `search_fts` for BM25 |
| `find_shared_root`, `parrot_home` | uses | plane location for worktrees and the global tier |
| `WikiProjectConfig` | extends | new `experience: ExperienceConfig` section |
| `WikiNamespaceConfig` | uses | read-only namespace `experience` → `.parrot/experience` |
| `LedgerService.open_issue` / `get_issue` | uses | graduation and retirement |
| `worktree_environment.protected_argv`, `native_sandbox_settings` | modifies | one more writable directory; three more hook entries |
| `parrot sdd` CLI `VERBS` | extends | noun `experience` |
| `LLMCodeDispatcher._dispatch_loop` | modifies | interceptor around the tool call |
| `CodexCodeDispatcher`, `GoogleCodingDispatcher`, `GeminiCodeDispatcher` | modifies | collect command outcomes, replay at attempt end |
| `TaskScopedBrief`, `NativePrep`, `DevelopmentOutput` | extends | `experience_briefing`, `lessons` |
| `SddCoderEngine` attempt path | modifies | build the briefing, consume returned lessons |
| `/sdd-start`, `/sdd-done`, `sdd-coder`, `sdd-worker` definitions and their twins | modifies | briefing call, export call, hooks, `lessons[]` contract |
| `.codex/hooks.json`, `.agents/hooks.json`, `sdd/installer.py` | modifies | hook entries for other hosts |

### Data Models

```python
LessonCategory = Literal["pitfall"]
LessonState = Literal["candidate", "confirmed", "quarantined", "retired"]
LessonTier = Literal["repo", "global"]
LessonSource = Literal["paired", "authored", "mined"]
ExperienceEventKind = Literal[
    "lesson.recorded", "failure.observed", "lesson.injected", "lesson.validated",
    "lesson.refuted", "lesson.confirmed", "lesson.quarantined", "lesson.graduated",
    "lesson.retired",
]

class LessonTrigger(BaseModel):
    executable: str                 # leading executable basename, e.g. "gh"
    subcommand: str = ""            # e.g. "pr edit"
    error_signature: str = ""       # normalized error text
    error_excerpt: str = ""         # redacted literal excerpt, <= 400 chars
    command_example: str = ""       # redacted failing command, <= 300 chars

class LessonDraft(BaseModel):
    """What an agent or the pairing logic submits. extra='forbid'."""
    category: LessonCategory = "pitfall"
    trigger: LessonTrigger
    symptom: str = ""               # <= 400 chars
    solution: str                   # <= 600 chars
    fix_example: str = ""           # redacted succeeding command, <= 300 chars
    scope_paths: list[str] = []     # repo-relative paths; empty = tool-level

class Lesson(BaseModel):
    lesson_id: str
    draft: LessonDraft
    tier: LessonTier
    state: LessonState
    hits: int
    validations: int
    refutations: int
    sessions: int
    issue_id: str = ""
    recorded_by: str
    recorded_at: str

class ExperienceEvent(BaseModel):
    schema_version: int = 1
    event_id: str                   # sha1 of kind|lesson_id|session|ts|payload, 12 hex
    kind: ExperienceEventKind
    lesson_id: str = ""
    session: str                    # host session id, attempt uid or PARROT_EXPERIENCE_SESSION
    actor: str                      # authoring_identity()
    seat: str = ""                  # "claude" | "codex" | "agy" | "gemini" | "<backend>:<model>"
    ts: str                         # UTC ISO-8601
    payload: dict[str, Any] = {}

class ExperienceConfig(BaseModel):
    enabled: bool = True
    confirm_sessions: int = 2
    quarantine_refutations: int = 2
    graduate_hits: int = 5
    graduate_sessions: int = 3
    brief_max_entries: int = 5
    brief_token_budget: int = 400
    inject_min_score: float = 0.35
    advice_cooldown_seconds: int = 600
    pairing_excluded_executables: list[str] = [
        "pytest", "ruff", "mypy", "black", "pylint", "vitest", "cargo",
        "grep", "rg", "ls", "cat", "find", "test", "head", "tail", "wc",
    ]
```

### New Public Interfaces

```
parrot sdd experience init                       # create the plane, register the read-only namespace
parrot sdd experience brief --task-file <task.md> [--max N]
parrot sdd experience hook --host claude|codex|agy --event pre|post|post-failure|post-invocation
parrot sdd experience record --executable X --solution "..." [--subcommand ...] [--error ...] [--symptom ...] [--path ...]
parrot sdd experience list [--state S] [--tier T] [--json]
parrot sdd experience show <lesson-id> [--json]
parrot sdd experience retire <lesson-id> --reason "..."
parrot sdd experience sync                       # host only: move global-tagged events to $PARROT_HOME
parrot sdd experience export                     # append definition events to sdd/experience/lessons.jsonl
parrot sdd experience rebuild                    # re-reduce the log into the store and triggers.json
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Models, signature, fast log | yes | models in §2; function signatures below; stdlib-only rule for `fastpath.py` | — |
| M2: Reducer, index, service | yes | state machine in §2; signatures below; store layout fixed | — |
| M3: `parrot sdd experience` CLI | yes | verb table in §2; `main(argv) -> int` per helper; `VERBS` shape | — |
| M4: Hook runtime | no | — | Host payload shapes for failure detection must be confirmed against live CLIs first (§8 Q1–Q3) |
| M5: Sandbox writable directory | yes | mirror `coder_evidence_dirs`; exact edit sites in §6 | — |
| M6: Claude hook wiring | no | — | Depends on Q1 (failure event) and Q4 (`--settings` hooks inside subagents) |
| M7: In-process interception | yes | interceptor signatures; advice attached under one key | — |
| M8: codex / agy adapters and replay | no | — | Q2 and Q3 decide whether hook capture works in dispatcher mode |
| M9: Briefing and `lessons[]` contract | yes | field names and call sites fixed below | — |
| M10: Promotion and graduation | yes | thresholds and events fixed in §2 | — |
| M11: Global sync, shared export, namespace | yes | file names and event kinds fixed | — |
| M12: Docs, asset twins, release smoke | yes | page paths and twin list fixed | — |

### Module 1: Models, signature and fast log
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/experience/{__init__,models,fastpath}.py`
- **Responsibility**: Pydantic models; the stdlib-only signature, redaction and append helpers
  that both the hook fast path and the service use.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/experience/models.py  (new)
  # LessonTrigger, LessonDraft, Lesson, ExperienceEvent and the Literal aliases of §2.
  # LessonDraft and ExperienceEvent set model_config = ConfigDict(extra="forbid").

  # knowledge/wiki/experience/fastpath.py  (new — stdlib imports ONLY at module level)
  EXPERIENCE_DIR = Path(".parrot") / "experience"
  EVENTS_FILE = "events.jsonl"
  TRIGGERS_FILE = "triggers.json"
  SESSIONS_DIR = "sessions"
  MAX_EVENT_BYTES = 4096

  def leading_command(command: str) -> tuple[str, str]:
      """Return (executable basename, subcommand) of the first real command segment.

      Skips env assignments, `cd … &&` prefixes and wrappers (rtk, sudo, timeout, uv run).
      Returns ("", "") when no executable can be determined.
      """

  def normalize_error(text: str) -> str:
      """Return the error text with volatile parts removed and whitespace collapsed (<= 300 chars)."""

  def redact(text: str) -> str:
      """Mask secrets: tokens, bearer headers, URL credentials, long hex/base64 runs, KEY=value pairs."""

  def failure_signature(executable: str, subcommand: str, error: str) -> str:
      """Return 'executable|subcommand|normalize_error(error)'."""

  def lesson_id_for(signature: str) -> str:
      """Return 'pit-' + sha1(signature)[:12]."""

  def resolve_plane_dir(cwd: Path) -> Path | None:
      """Return <shared-root>/.parrot/experience for cwd, or None outside a git checkout.

      Stdlib-only re-statement of find_shared_root (verified: knowledge/wiki/project.py:1563).
      """

  def append_event(plane_dir: Path, record: Mapping[str, Any]) -> bool:
      """Append one JSON line with O_APPEND + fsync; truncate payload to MAX_EVENT_BYTES.

      Never raises; returns False when the write did not happen.
      """

  def load_triggers(plane_dir: Path) -> dict[str, list[dict[str, Any]]]:
      """Return the executable → lesson-stub map from triggers.json, or {} when absent/corrupt."""
  ```

### Module 2: Reducer, index and service
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/experience/{reducer,index,service}.py`;
  `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (config section)
- **Responsibility**: fold events into lesson state; maintain the reduced store and
  `triggers.json`; expose record / search / brief / list / show / retire.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/experience/reducer.py  (new, pure)
  def reduce_events(events: Iterable[ExperienceEvent], config: ExperienceConfig) -> dict[str, Lesson]:
      """Fold events (any order, de-duplicated by event_id) into lessons keyed by lesson_id."""

  # knowledge/wiki/experience/index.py  (new)
  class ExperienceIndex:
      """Reduced store for one tier: wiki.db + triggers.json under plane_dir."""
      def __init__(self, plane_dir: Path, *, read_only: bool = False) -> None: ...
      def is_stale(self, sources: Sequence[Path]) -> bool:
          """True when any source's (size, mtime_ns) differs from the stored marker."""
      async def rebuild(self, lessons: Mapping[str, Lesson]) -> int:
          """Rewrite pages (category='pitfall'), attrs and triggers.json; return page count.

          Uses create_wiki_store (verified: knowledge/wiki/store.py:3288) and
          upsert_pages / upsert_attrs (verified: store.py:2325, :2506).
          """
      async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
          """BM25 over the reduced store via search_fts (verified: store.py:2938)."""

  # knowledge/wiki/experience/service.py  (new)
  class ExperienceService:
      """Facade over both tiers. Every public method is best-effort and never raises to hooks."""
      @classmethod
      def from_root(cls, root: Path | None = None) -> "ExperienceService": ...
      async def refresh(self) -> None:
          """Rebuild stale indexes, then run promote() and graduate()."""
      async def record(self, draft: LessonDraft, *, session: str, source: LessonSource, seat: str = "") -> str:
          """Redact, route the tier, append lesson.recorded; return lesson_id."""
      async def match_failure(self, command: str, error: str, *, session: str) -> Lesson | None:
          """Best lesson for a failure above inject_min_score; confirmed preferred over candidate."""
      async def match_command(self, command: str) -> list[Lesson]:
          """Confirmed lessons whose trigger matches the command about to run."""
      async def brief(self, title: str, files: Sequence[str], *, max_entries: int | None = None) -> str:
          """Markdown bullet block of at most brief_max_entries confirmed lessons; '' when none."""
      async def list_lessons(self, *, state: LessonState | None = None, tier: LessonTier | None = None) -> list[Lesson]: ...
      async def get_lesson(self, lesson_id: str) -> Lesson | None: ...
      async def retire(self, lesson_id: str, *, reason: str) -> bool: ...

  # knowledge/wiki/project.py  (modifies WikiProjectConfig, verified: project.py:589)
  class ExperienceConfig(BaseModel): ...      # fields in §2
  #   WikiProjectConfig.experience: ExperienceConfig = Field(default_factory=ExperienceConfig)
  ```

### Module 3: `parrot sdd experience` CLI
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py`;
  `packages/ai-parrot/src/parrot/sdd/cli.py`
- **Responsibility**: the noun and its verbs, except `hook`.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # sdd/scripts/experience_cli.py  (new)
  def main(argv: Sequence[str] | None = None) -> int:
      """Dispatch argv[0] in {init, brief, record, list, show, retire, sync, export, rebuild}.

      Exit 0 on success and on a missing plane (prints nothing); 2 on usage errors.
      """

  # sdd/cli.py  (modifies VERBS, verified: sdd/cli.py:247)
  #   "experience": {
  #       "init": ("experience_cli", ("init",), "..."), "brief": ("experience_cli", ("brief",), "..."),
  #       "record": …, "list": …, "show": …, "retire": …, "sync": …, "export": …, "rebuild": …,
  #       "hook": ("experience_hook", (), "..."),
  #   },
  ```

### Module 4: Hook runtime
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py`
- **Responsibility**: the per-tool-call entry point for every host. Stdlib-only until a lesson
  actually has to be looked up.
- **Depends on**: M1 (fast path), M2 (lazy import on the slow path).
- **Interface Skeleton**:
  ```python
  # sdd/scripts/experience_hook.py  (new — stdlib imports ONLY at module level)
  def main(argv: Sequence[str] | None = None) -> int:
      """Read the hook payload on stdin, print the host response (or nothing); always return 0."""

  def session_of(payload: Mapping[str, Any], env: Mapping[str, str]) -> str:
      """PARROT_EXPERIENCE_SESSION if set, else the payload's session id, else 'unknown'."""

  def command_of(payload: Mapping[str, Any], host: str) -> str:
      """The shell command of a tool call for claude|codex|agy payloads; '' if not a shell tool."""

  def failure_of(payload: Mapping[str, Any], host: str, event: str) -> str | None:
      """The error text when the payload describes a failed command, else None."""

  def handle_pre(payload: Mapping[str, Any], *, host: str, plane_dir: Path) -> str | None:
      """Advice for a confirmed lesson matching the command, honoring the per-session cooldown."""

  def handle_post(payload: Mapping[str, Any], *, host: str, event: str, plane_dir: Path) -> str | None:
      """Success: close a pending failure (pair or validate). Failure: record it and return advice."""

  def handle_post_invocation(payload: Mapping[str, Any], *, plane_dir: Path) -> str | None:
      """agy only: return advice queued in the session file by handle_post, then clear it."""

  def render(advice: str, *, host: str, event: str) -> dict[str, Any]:
      """Host response envelope carrying advice as advisory context only."""
  ```
  Response envelopes (`render`):
  - claude `pre`: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": advice}, "suppressOutput": true}`
  - claude `post` / `post-failure`: same with `"PostToolUse"` / `"PostToolUseFailure"`
  - codex `pre` / `post`: `{"hookSpecificOutput": {"hookEventName": "PreToolUse" | "PostToolUse", "additionalContext": advice}}`
  - agy `post`: always `{}`; agy `post-invocation`: `{"injectSteps": [{"systemMessage": {"systemMessage": advice}}]}`

  Advice template (fixed; lesson text is data inside it, total <= 700 chars):
  `[experience:<lesson_id> <state>] Known pitfall for \`<executable> <subcommand>\`: <symptom> Fix that worked before: <solution>`

### Module 5: Sandbox writable directory
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`,
  `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`
- **Responsibility**: make `<primary>/.parrot/experience` writable in both backends.
- **Depends on**: nothing (path constant is duplicated on purpose: this file is stdlib-only).
- **Interface Skeleton**:
  ```python
  # sdd/scripts/worktree_environment.py  (modifies)
  EXPERIENCE_PLANE_DIR = Path(".parrot") / "experience"      # next to SHARED_LEDGER_DIR, verified: :142

  def experience_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
      """The primary checkout's experience plane, created when missing.

      Same contract as coder_evidence_dirs (verified: :243): () when root is the primary
      checkout, when git_dir is None, or on OSError.
      """
  ```

### Module 6: Claude hook wiring
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`,
  `packages/ai-parrot/src/parrot/sdd/installer.py`, `.claude/agents/sdd-coder.md`,
  `.claude/agents/sdd-worker.md` (+ packaged twins)
- **Responsibility**: register the three experience hooks for launched workers, for subagents,
  and for interactive sessions.
- **Depends on**: M3, M4.
- **Interface Skeleton**:
  ```python
  # sdd/scripts/native_claude_sandbox.py  (modifies native_sandbox_settings, verified: :410)
  def _experience_hook_entries() -> dict[str, list[dict[str, Any]]]:
      """PreToolUse / PostToolUse / PostToolUseFailure entries, matcher 'Bash', timeout 10.

      Command: 'parrot sdd experience hook --host claude --event <pre|post|post-failure>'.
      No '|| exit 2': an experience hook failure must never block a tool call.
      """

  # sdd/installer.py  (modifies; pattern: _install_dangerous_guard, verified: :399)
  def _install_experience_hooks(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
      """Add the three entries to .claude/settings.json idempotently; return changed paths."""
  ```
  Agent frontmatter adds, under `hooks:`, the same three entries with matcher `Bash`.

### Module 7: In-process interception
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/experience.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py`
- **Responsibility**: before/after interception for seats whose tool loop parrot owns, and the
  replay entry point shared with M8.
- **Depends on**: M2, M4 (reuses `handle_pre` / `handle_post` logic through the service).
- **Interface Skeleton**:
  ```python
  # flows/dev_loop/experience.py  (new)
  class CommandOutcome(BaseModel):
      command: str
      ok: bool
      error: str = ""

  class ExperienceInterceptor:
      """Per-attempt interceptor. No method raises; failures are logged at debug level."""
      def __init__(self, *, session: str, cwd: str, seat: str) -> None: ...
      async def before(self, tool_name: str, tool_args: Mapping[str, Any]) -> list[str]:
          """Advice for a run_command call about to execute; [] for other tools."""
      async def after(self, tool_name: str, tool_args: Mapping[str, Any], tool_result: Mapping[str, Any]) -> list[str]:
          """Record the outcome (pair / validate / refute) and return advice on failure."""
      async def replay(self, outcomes: Sequence[CommandOutcome]) -> int:
          """Run the pairing logic over an ordered outcome list; no-op when the session already
          has hook-recorded events. Return the number of events appended."""

  # flows/dev_loop/dispatchers/llm.py  (modifies _dispatch_loop, verified: :589)
  #   advice = await interceptor.before(...) ; tool_result = await self._run_tool(...)
  #   advice += await interceptor.after(...)
  #   if advice: tool_result = {**tool_result, "experience_advice": advice}
  ```

### Module 8: codex and agy adapters, end-of-attempt replay
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/{codex,google_coding,gemini}.py`,
  `.codex/hooks.json`, `.agents/hooks.json`, `packages/ai-parrot/src/parrot/sdd/installer.py`
- **Responsibility**: native hook entries for codex and agy; export
  `PARROT_EXPERIENCE_SESSION` to the CLI process; collect command outcomes from the event stream
  and replay them when the attempt ends.
- **Depends on**: M4, M7.
- **Interface Skeleton**:
  ```python
  # dispatchers/codex.py  (modifies the command_execution branch, verified: :783)
  #   on item.completed: self._outcomes.append(CommandOutcome(command=…, ok=exit_code == 0, error=…))
  # dispatchers/google_coding.py  (modifies, verified: :564) and dispatchers/gemini.py (verified: :384)
  #   on tool_response: append CommandOutcome(command=<paired tool_call args>, ok=not is_error, error=result_snippet)
  # each dispatcher, after the CLI process exits:
  #   await ExperienceInterceptor(session=…, cwd=…, seat=…).replay(self._outcomes)
  ```
  `.codex/hooks.json`: a second `PreToolUse` hook command and a new `PostToolUse` block, matcher
  `Bash`, command `parrot sdd experience hook --host codex --event pre|post`.
  `.agents/hooks.json`: `PostToolUse` (matcher `run_command`) and `PostInvocation` entries under
  the existing named hook, command `parrot sdd experience hook --host agy --event post|post-invocation`.

### Module 9: Briefing and the `lessons[]` contract
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/{engine,models}.py`,
  `.claude/commands/sdd-start.md`, `.claude/agents/sdd-coder.md`, `.claude/agents/sdd-worker.md`
  (+ twins)
- **Responsibility**: deliver the briefing to every seat and consume returned lessons.
- **Depends on**: M2, M3.
- **Interface Skeleton**:
  ```python
  # flows/dev_loop/models/base.py  (modifies)
  #   TaskScopedBrief.experience_briefing: str = Field("", description="Known pitfalls for this task.")   # verified class: :478
  #   DevelopmentOutput.lessons: List[LessonDraft] = Field(default_factory=list, description="…")       # verified class: :527

  # flows/dev_loop/sdd_coder/models.py  (modifies NativePrep, verified: :456)
  #   experience_briefing: str = ""

  # flows/dev_loop/sdd_coder/engine.py  (modifies)
  async def _experience_briefing_for(self, ctx: _FeatureCtx, task: PlannedTask) -> str:
      """ExperienceService.brief(title, files) for the task; '' on any error or when disabled."""
  async def _record_lessons(self, ctx: _FeatureCtx, task: PlannedTask, output: DevelopmentOutput, *, session: str, seat: str) -> int:
      """Record output.lessons as candidates (source='authored'); return how many were stored."""
  ```
  The briefing is **not** appended to `coder_feedback`: review exposure is measured on that text.

### Module 10: Promotion and graduation
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py` (methods),
  `packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py`
- **Responsibility**: emit `lesson.confirmed` / `lesson.quarantined`; open and track graduation
  issues; retire on close.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/experience/service.py
  async def promote(self) -> list[str]:
      """Append lesson.confirmed / lesson.quarantined for lessons that crossed a threshold
      and have no such event yet; return the affected lesson ids."""
  async def graduate(self) -> list[str]:
      """For confirmed lessons past graduate_hits/graduate_sessions with no issue: open one via
      LedgerService.open_issue(kind='tech_debt', severity='low', actor='agent:experience')
      (verified: knowledge/wiki/ledger/service.py:243) and append lesson.graduated.
      For graduated lessons whose issue status is 'closed' (get_issue, verified: :336):
      append lesson.retired. Return the affected lesson ids."""
  ```

### Module 11: Global sync, shared export and namespace
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`, `.gitattributes`,
  `packages/ai-parrot/src/parrot/sdd/installer.py`, `.claude/commands/sdd-done.md` (+ twins)
- **Responsibility**: host-side move of global-tagged events; redacted export of definition
  events; namespace registration.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/experience/sync.py  (new)
  SHARED_LOG = Path("sdd") / "experience" / "lessons.jsonl"
  DEFINITION_KINDS = frozenset({"lesson.recorded", "lesson.confirmed", "lesson.retired", "lesson.graduated"})

  def global_plane_dir() -> Path:
      """parrot_home() / 'experience' (parrot_home verified: launcher.py:26)."""
  def sync_global(repo_plane: Path) -> int:
      """Copy tier='global' events absent from the global log into it; return the count. Host only."""
  def export_shared(repo_plane: Path, checkout: Path) -> int:
      """Append DEFINITION_KINDS events not yet in checkout/SHARED_LOG, redacted; return the count."""
  def register_namespace(root: Path) -> bool:
      """Add namespaces.experience = {store: '.parrot/experience'} to .parrot/wiki.json if absent."""
  ```
  `feature_launcher._preflight_sandbox` calls `sync_global` best-effort before launch;
  `/sdd-done` runs `parrot sdd experience sync` and `parrot sdd experience export` before its
  final commit and stages `sdd/experience/lessons.jsonl`.

### Module 12: Documentation, asset twins and release smoke
- **Path**: `wiki/sdd-tooling/sdd/experience-memory.md`,
  `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md`, `.claude/rules/worktree-management.md`
  (+ packaged twin), `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py`
- **Responsibility**: document the plane and the sandbox policy change; keep packaged asset
  copies in sync; add smoke scenarios for the two new helpers.
- **Depends on**: M3, M5.
- **Interface Skeleton**:
  ```python
  # tests/sdd/test_wheel_only_foreign_repo.py  (modifies SCENARIOS, verified: :363)
  #   "experience_cli": Scenario(...), "experience_hook": Scenario(...)
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_leading_command_skips_wrappers` | M1 | `cd x && rtk gh pr edit 1` → (`gh`, `pr edit`) |
| `test_normalize_error_strips_volatile` | M1 | paths, hashes, numbers and timestamps removed; stable across runs |
| `test_redact_masks_secrets` | M1 | tokens, bearer headers, URL credentials masked |
| `test_append_event_never_raises` | M1 | unwritable directory returns False |
| `test_fastpath_is_stdlib_only` | M1 | importing `fastpath` does not import `pydantic` |
| `test_reduce_candidate_to_confirmed` | M2/M10 | validations from 2 other sessions confirm; recorder's own session does not count |
| `test_reduce_refutations_quarantine` | M2/M10 | 2 refutations quarantine |
| `test_index_rebuild_and_search` | M2 | lesson found by literal error text via BM25 |
| `test_service_tier_routing` | M2 | no repo path → `global`; scoped path → `repo` |
| `test_brief_max_five_confirmed_only` | M2 | candidates excluded; at most 5 bullets |
| `test_cli_missing_plane_is_silent` | M3 | `brief` on a repo with no plane exits 0 with no output |
| `test_hook_pre_miss_is_noop` | M4 | executable absent from `triggers.json` → no output |
| `test_hook_pre_advises_confirmed_only` | M4 | candidate never surfaces before a command |
| `test_hook_pre_cooldown` | M4 | same lesson not repeated within the cooldown |
| `test_hook_post_failure_injects_candidate_labeled` | M4 | candidate advice carries `candidate` |
| `test_hook_pairing_drafts_lesson` | M4 | fail then success of same family appends `lesson.recorded` |
| `test_hook_validation_and_refutation` | M4 | injected lesson followed by success / failure |
| `test_hook_excluded_executables` | M4 | failing `pytest` never drafts a lesson |
| `test_hook_envelopes_per_host` | M4 | exact JSON for claude, codex, agy |
| `test_hook_never_blocks` | M4 | corrupt payload / corrupt index → exit 0, no output |
| `test_experience_dirs_contract` | M5 | created under primary; `()` for the primary checkout itself |
| `test_protected_argv_binds_experience` | M5 | bind present for a linked worktree |
| `test_native_allow_write_includes_experience` | M5 | path in `allowWrite`; wiki plane still absent |
| `test_native_settings_experience_hooks` | M6 | three entries, matcher `Bash`, no `exit 2` |
| `test_interceptor_attaches_advice` | M7 | failed `run_command` result carries `experience_advice` |
| `test_interceptor_replay_skips_hooked_session` | M7 | replay is a no-op when hook events exist |
| `test_codex_outcomes_collected` | M8 | `command_execution` items become outcomes |
| `test_brief_field_reaches_prompt` | M9 | `experience_briefing` present in the dispatched brief JSON |
| `test_lessons_field_in_codex_schema` | M9 | strict schema includes `lessons` |
| `test_record_lessons_from_output` | M9 | returned lessons stored as candidates |
| `test_graduate_opens_one_issue` | M10 | idempotent per lesson |
| `test_closed_issue_retires_lesson` | M10 | retired lessons are not injected |
| `test_sync_global_moves_once` | M11 | second run copies nothing |
| `test_export_shared_redacted_definitions_only` | M11 | no hit events in the shared log |

### Integration Tests
| Test | Description |
|---|---|
| `test_gh_pr_edit_end_to_end` | session A: `gh pr edit` fails, `gh api -X PATCH` … succeeds → candidate drafted from an authored lesson; sessions B and C fail, receive the candidate, succeed → confirmed; session D receives the advisory before running `gh pr edit` and the bullet in its briefing |
| `test_worktree_uses_primary_plane` | a linked worktree outside `.parrot/worktrees/` reads and writes the primary plane |
| `test_shared_log_feeds_fresh_clone` | a plane with only `sdd/experience/lessons.jsonl` yields the confirmed lesson |

### Validation Contract

tests:
- tests/knowledge/wiki/experience/test_fastpath.py
- tests/knowledge/wiki/experience/test_reducer.py
- tests/knowledge/wiki/experience/test_service.py
- tests/knowledge/wiki/experience/test_sync.py
- tests/knowledge/wiki/experience/test_end_to_end.py
- packages/ai-parrot/tests/sdd/test_experience_cli.py
- packages/ai-parrot/tests/sdd/test_experience_hook.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/sdd/test_installer.py
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
- packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py
- packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py
- packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py
- packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py
- packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py
- packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py
- packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
- tests/sdd_scripts/test_check_asset_sync.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def plane(tmp_path: Path) -> Path:
    """An initialized repo-tier plane under a fake git checkout; PARROT_HOME points at tmp_path."""

@pytest.fixture
def claude_bash_failure_payload() -> dict[str, Any]:
    """PostToolUseFailure payload for `gh pr edit 12 --base dev`, error first line 'Exit code 1'."""
```

---

## 5. Acceptance Criteria

- [ ] All tests in the Validation Contract pass.
- [ ] Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).
- [ ] No breaking change: with no plane present every hook, the briefing and the interceptor are no-ops and exit 0.
- [ ] `parrot sdd experience brief --task-file <task.md>` prints at most 5 bullets, confirmed lessons only, within `brief_token_budget`.
- [ ] A pre-tool hook call for a command whose executable has no lesson imports no third-party module and completes in under 50 ms (median of 20 runs, excluding interpreter start).
- [ ] No experience hook ever emits `updatedInput` or a permission decision; no hook command ends in `|| exit 2`.
- [ ] A candidate lesson is never returned by `brief` or by the pre-tool path.
- [ ] A lesson is confirmed only with validations from `confirm_sessions` distinct sessions other than the recording session.
- [ ] `<primary>/.parrot/experience` is writable and `<primary>/.parrot/wiki` is still not writable in both sandbox backends; no `$HOME` path is writable.
- [ ] A linked worktree located outside `.parrot/worktrees/` resolves the primary checkout's plane.
- [ ] Global-tagged lessons recorded in a sandbox reach `$PARROT_HOME/experience/` only through `sync`, and `sync` is idempotent.
- [ ] `sdd/experience/lessons.jsonl` contains only definition events, redacted, and carries `merge=union`.
- [ ] `wikitoolkit query "<text>" --ns experience` returns lessons after `parrot sdd experience init`; a default query does not open the plane for writing.
- [ ] A confirmed lesson past the graduation thresholds opens exactly one `tech_debt` ledger issue; closing it retires the lesson.
- [ ] `DevelopmentOutput.lessons` is accepted from every MCP seat, including the codex strict schema, and stored as candidates.
- [ ] The briefing reaches MCP seats through `TaskScopedBrief.experience_briefing` and native seats through `NativePrep.experience_briefing`; `coder_feedback` text is unchanged.
- [ ] Seat parity as tabled in §2 holds for Claude, in-process and codex seats; for agy, capture works and advice arrives through `PostInvocation` (or the gap is recorded per §8 Q3).
- [ ] The motivating scenario passes end to end (`test_gh_pr_edit_end_to_end`).
- [ ] `scripts/sdd/check_asset_sync.py --check` passes; release smoke has scenarios for `experience_cli` and `experience_hook`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Paths are relative to `packages/ai-parrot/src/parrot/` unless they start with `.`, `sdd/`,
> `scripts/`, `tests/`, `wiki/` or `packages/`.

### Verified Imports
```python
from parrot.knowledge.wiki.project import find_shared_root, WikiProjectConfig, WikiNamespaceConfig  # project.py:1563, :589, :187
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store          # store.py:1265, :606, :3288
from parrot.knowledge.wiki.ledger.service import LedgerService                                      # ledger/service.py:149
from parrot.knowledge.wiki.identity import authoring_identity                                       # identity.py:7
from parrot.launcher import parrot_home                                                             # launcher.py:26
from parrot.flows.dev_loop.models.base import DevelopmentOutput, TaskScopedBrief                    # models/base.py:527, :478
from parrot.flows.dev_loop.sdd_coder.models import NativePrep                                       # sdd_coder/models.py:456
```

### Existing Class Signatures
```python
# knowledge/wiki/store.py
class WikiPageRecord(BaseModel):                                    # :606
    # concept_id, node_id, title, category, summary, body, source_id, token_count,
    # origin, asserted_by, updated_at, content_hash, attrs: dict[str, str]
class SQLiteWikiStore(BaseWikiStore):                               # :1265
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False,
                 sqlite_policy: SQLitePragmaPolicy | None = None, persistent_writer: bool = False): ...  # :1317
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...                                # :2325
    async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int: ...  # :2506
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # :2869
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...  # :2938
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kw): ...                             # :3288, opens {storage_dir}/wiki.db

# knowledge/wiki/project.py
PARROT_DIR = ".parrot"                                              # :46
class WikiNamespaceConfig(BaseModel): ...                           # :187 — extra="forbid"; exactly one of path/store/database/vault
class WikiProjectConfig(BaseModel):                                 # :589
    namespaces: dict[str, WikiNamespaceConfig] = Field(...)         # :664
    def ledger_path(self, root: Path) -> Path: ...                  # :753
def find_shared_root(start: Path | None = None) -> Path | None: ... # :1563

# knowledge/wiki/ledger/service.py
class LedgerService:                                                # :149
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService": ...   # :167
    async def open_issue(self, title: str, body: str, kind: IssueKind = "bug", severity: str = "minor",
                         discovered_from: str = "", about: list[str] | None = None,
                         actor: str = "agent:sdd") -> str: ...             # :243
    async def get_issue(self, issue_id: str) -> dict[str, Any] | None: ... # :336 — dict has "status"
# knowledge/wiki/ledger/events.py:22-24
IssueKind = Literal["bug", "tech_debt", "feature_gap", "vulnerability"]
IssueSeverity = Literal["critical", "major", "minor", "low"]
IssueStatus = Literal["open", "claimed", "closed", "superseded"]

# knowledge/wiki/ledger/log.py — pattern only (its append takes a LedgerEvent with a closed kind list)
class LedgerLog:                                                    # :10
    def append(self, event: LedgerEvent) -> tuple[str, int]: ...    # :21
    def append_line(self, line: str) -> int: ...                    # :83

# knowledge/wiki/identity.py
def authoring_identity(by: str | None) -> str: ...                  # :7 — by → CLAUDE_AGENT_ID/PARROT_AGENT_ID → human:<user>

# knowledge/wiki/claude_code/hook.py — pattern for the stdlib prefilter and stamp-file cooldown
def run_pre_tool_use_hook(stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> int: ...  # :250
def _throttled(storage: Path, cooldown_seconds: int, now: float) -> bool: ...                            # :120

# sdd/scripts/worktree_environment.py
def shared_ledger_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]: ...    # :214
def coder_evidence_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]: ...   # :243
def protected_argv(cwd: Path, argv: Sequence[str], *, derive_pythonpath: bool = False) -> list[str]: ...  # :299

# sdd/scripts/native_claude_sandbox.py
def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = (),
                            include_sandbox: bool = True) -> dict[str, Any]: ...     # :410
def _prefix_writable_roots(cwd: Path) -> tuple[Path, ...]: ...                       # :922
def launch_worker(argv: Sequence[str], *, cwd: Path | None = None, initial_prompt: str | None = None,
                  base_env: Mapping[str, str] | None = None) -> int: ...             # :1230

# sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {…}                  # :247
def _mount(noun: click.Group, verb: str, module: str, prefix: tuple[str, ...], help_: str) -> None: ...  # :349

# flows/dev_loop/dispatchers/llm.py
async def _run_tool(self, *, tool_name: str, tool_args: Dict[str, Any], cwd: str,
                    profile: LLMCodeDispatchProfile) -> Dict[str, Any]: ...          # :1520
async def _tool_run_command(self, cwd: str, args: Dict[str, Any],
                            profile: LLMCodeDispatchProfile) -> Dict[str, Any]: ...  # :1956
async def _run_argv(self, argv: Sequence[str], *, cwd: str, timeout: int,
                    stdin: Optional[str] = None) -> Dict[str, Any]: ...              # :2199

# flows/dev_loop/dispatchers/codex.py
def _strict_output_schema(schema: Any) -> Any: ...                                   # :81 — derived from model_json_schema(), :883

# flows/dev_loop/models/base.py
class TaskScopedBrief(BaseModel): ...   # :478 — research, task_id, coder_feedback, validation_verdict, task_file
class DevelopmentOutput(BaseModel): ... # :527 — files_changed, commit_shas, summary, incomplete_tasks, worker_summaries, merge_performed

# flows/dev_loop/sdd_coder/engine.py
async def _feedback_for(self, ctx: _FeatureCtx, task: PlannedTask, backend: str, model: str) -> str: ...  # :2743

# sdd/installer.py
def _pre_tool_use(settings: dict[str, Any], path: Path, *, create: bool) -> list[Any] | None: ...          # :381
def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]: ...  # :399
def _install_agy_hook(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> tuple[bool, list[str]]: ...  # :640
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ExperienceIndex` | `create_wiki_store`, `upsert_pages`, `upsert_attrs`, `search_fts` | async calls | `knowledge/wiki/store.py:3288`, `:2325`, `:2506`, `:2938` |
| `fastpath.resolve_plane_dir` | `find_shared_root` semantics | stdlib re-statement | `knowledge/wiki/project.py:1563` |
| `ExperienceService.graduate` | `LedgerService.open_issue` / `get_issue` | async calls | `knowledge/wiki/ledger/service.py:243`, `:336` |
| `experience_dirs` | `protected_argv` bind list, `native_sandbox_settings` `allow_paths` | list extension | `sdd/scripts/worktree_environment.py:360`, `sdd/scripts/native_claude_sandbox.py:426` |
| `_experience_hook_entries` | settings `hooks` dict | dict merge | `sdd/scripts/native_claude_sandbox.py:437` |
| `ExperienceInterceptor` | `_dispatch_loop` tool call | before/after wrapper | `flows/dev_loop/dispatchers/llm.py:589` |
| `CommandOutcome` collection | codex `command_execution`, agy/gemini `tool_response` | stream parsing | `dispatchers/codex.py:783`, `google_coding.py:564`, `gemini.py:384` |
| `experience_briefing` | `TaskScopedBrief(...)`, `NativePrep(...)` construction | keyword argument | `flows/dev_loop/sdd_coder/engine.py:3860`, `:2622` |
| `_record_lessons` | attempt return | call before return | `flows/dev_loop/sdd_coder/engine.py:3975` |
| noun `experience` | `VERBS` | dict entry | `sdd/cli.py:247` |
| `parrot` binary in in-process seats | runner-registry merge | already allowed in engine attempts | `flows/dev_loop/sdd_coder/engine.py:3831` |

Host hook facts (external, verified against the installed CLIs / official docs on 2026-11-13):

- Claude Code 2.1.323: `PostToolUse` fires after a tool call succeeds, `PostToolUseFailure` after
  it fails; both accept `hookSpecificOutput.additionalContext`. Bash `tool_response` has
  `stdout`, `stderr`, `interrupted`; the exit code appears only as an `Exit code N` first line of
  `error`. Matching hooks run in parallel and all `additionalContext` values are delivered.
- codex-cli 0.167.2: `PreToolUse` and `PostToolUse` accept
  `hookSpecificOutput.additionalContext`; `systemMessage` does not reach the model.
- agy 1.5.3: `PostToolUse` receives `toolCall.name`, `toolCall.args`, `error` and must return
  `{}`; `PostInvocation` may return `injectSteps` with a `systemMessage`; `PreToolUse` must
  return a `decision`.

### Does NOT Exist (Anti-Hallucination)
- ~~any `PostToolUse` / `PostToolUseFailure` hook~~ — none registered for any host today
- ~~`parrot sdd experience`, `parrot.knowledge.wiki.experience`, `parrot.flows.dev_loop.experience`~~ — created by this feature
- ~~`parrot sdd task start`~~ — no task-start verb; the `/sdd-start` priming step is prose run by the model
- ~~`DevelopmentOutput.lessons` / notes / findings~~ — only `summary` is free-form; unknown keys are dropped (`extra='ignore'`)
- ~~`TaskScopedBrief.experience_briefing`, `NativePrep.experience_briefing`~~ — added by this feature
- ~~page hit / access counter in the wiki~~ — `usage_operations.py` reports token cost per feature
- ~~`WikiProjectConfig.experience`~~ — added by this feature
- ~~`find_shared_root` in wiki store resolution~~ — the wiki uses `find_project_root`; only the ledger uses the shared root
- ~~writable `<primary>/.parrot/wiki` or any `$HOME` path in the sandbox~~
- ~~`sdd/scripts/feature_launcher.py`~~ — the file is `flows/dev_loop/feature_launcher.py`
- ~~`.codex/hooks.json` written by `sdd/installer.py`~~ — it is hand-maintained; only `.agents/hooks.json` has an installer
- ~~`CLAUDE_SESSION_ID` / `PARROT_RUN_ID` in `identity.py`~~ — read in `knowledge/wiki/cli.py:4564` (`_authoring_run_id`)
- ~~`hooks` field on `ClaudeAgentRunOptions`~~ — the `claude-code` seat gets hooks only through settings JSON
- ~~`aggregated_output` parsing in the codex dispatcher~~ — only `command`, `exit_code`, `status` are read
- ~~exit code in agy / gemini stream events~~ — only `error` / `status == "error"`
- ~~per-field BM25 boosts; embeddings on the `query` path~~
- ~~a Codex twin of `/sdd-start`~~ — `.codex/skills` holds only `parrot-wiki`
- ~~`sdd/experience/`~~ — created by this feature

### Edit Sites (Blueprint Anchors)

Verified against: `433e0e9318`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `knowledge/wiki/experience/__init__.py`, `models.py`, `fastpath.py`, `reducer.py`, `index.py`, `service.py`, `sync.py` | CREATE | — | — | — |
| `sdd/scripts/experience_cli.py`, `sdd/scripts/experience_hook.py` | CREATE | — | — | — |
| `flows/dev_loop/experience.py` | CREATE | — | — | — |
| `sdd/experience/lessons.jsonl` | CREATE | — | — | — |
| `wiki/sdd-tooling/sdd/experience-memory.md` | CREATE | — | — | — |
| `knowledge/wiki/project.py` | MODIFY | `class WikiProjectConfig(BaseModel):` | `project.py:589` | 1 |
| `sdd/cli.py` | MODIFY | `"review": ("review_checkpoint", (), "Review: prepare \| validate \| record."),` | `cli.py:281` | 1 |
| `sdd/scripts/worktree_environment.py` | MODIFY | `CODER_EVIDENCE_DIR = Path("artifacts") / "logs" / "sdd-coder-usage"` | `:151` | 1 |
| `sdd/scripts/worktree_environment.py` | MODIFY | `def coder_evidence_dirs(root: Path, git_dir: Path \| None) -> tuple[Path, ...]:` | `:243` | 1 |
| `sdd/scripts/worktree_environment.py` | MODIFY | `for evidence_dir in coder_evidence_dirs(root, git_dir):` | `:360` | 1 |
| `sdd/scripts/native_claude_sandbox.py` | MODIFY | `allow_paths.extend(_we.coder_evidence_dirs(root, git_dir))` | `:426` | 1 |
| `sdd/scripts/native_claude_sandbox.py` | MODIFY | `"hooks": [{"type": "command", "command": hook_command, "timeout": 10}],` | `:442` | 1 |
| `sdd/scripts/native_claude_sandbox.py` | MODIFY | `_canonical(primary / "artifacts" / "logs" / "sdd-coder-usage"),` | `:930` | 1 |
| `sdd/installer.py` | MODIFY | `def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool \| None) -> list[str]:` | `:399` | 1 |
| `sdd/installer.py` | MODIFY | `AGY_HOOKS_PATH = Path(".agents/hooks.json")` | `:500` | 1 |
| `flows/dev_loop/dispatchers/llm.py` | MODIFY | `tool_result = await self._run_tool(` | `:589` | 1 |
| `flows/dev_loop/dispatchers/llm.py` | MODIFY | `if tool_result.get("ok") is False:` | `:595` | 1 |
| `flows/dev_loop/dispatchers/codex.py` | MODIFY | `if item_type == "command_execution":` | `:783` | 1 |
| `flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `elif step_type == "tool_response":` | `:564` | 1 |
| `flows/dev_loop/dispatchers/gemini.py` | MODIFY | `elif event_type == "tool_response":` | `:384` | 1 |
| `flows/dev_loop/models/base.py` | MODIFY | `validation_verdict: str = Field(` | `:491` | 1 |
| `flows/dev_loop/models/base.py` | MODIFY | `merge_performed: bool = Field(` | `:561` | 1 |
| `flows/dev_loop/sdd_coder/models.py` | MODIFY | `validation_verdict: str = ""` | `:470` | 1 |
| `flows/dev_loop/sdd_coder/engine.py` | MODIFY | `validation_verdict=verdict or "",` | `:3865` | 1 |
| `flows/dev_loop/sdd_coder/engine.py` | MODIFY | `return NativePrep(` | `:2622` | 1 |
| `flows/dev_loop/sdd_coder/engine.py` | MODIFY | `return record, output, error, manager, branch, path` | `:3975` | 1 |
| `flows/dev_loop/feature_launcher.py` | MODIFY | `native_claude_sandbox.plan_native_launch(worktree, allowed_domains=allowed_domains)` | `:98` | 1 |
| `.claude/commands/sdd-start.md` (+ `_assets/claude/commands/`, `.agent/workflows/`, `_assets/agent/workflows/`) | MODIFY | `wikitoolkit ledger context <file-1> <file-2> ... 2>/dev/null \|\| true` | `sdd-start.md:174` | 1 |
| `.agents/skills/sdd-start/SKILL.md` (+ `_assets/agents/skills/sdd-start/`) | MODIFY | ``- `wikitoolkit ledger context <files-from-scope> 2>/dev/null \|\| true` `` | `SKILL.md:85` | 1 |
| `.claude/commands/sdd-done.md` (+ twins) | MODIFY | `wikitoolkit ledger outbox prepare --repo-root "<worktree-path>"` | `sdd-done.md:612` | 2 (also `:887`; the exact step is Q6) |
| `.claude/agents/sdd-coder.md` (+ `_assets/claude/agents/`) | MODIFY | `command: 'parrot sdd worktree guard --hook \|\| exit 2'` | `sdd-coder.md:21` | 1 |
| `.claude/agents/sdd-coder.md` (+ twin) | MODIFY | ``## Output — `DevelopmentOutput` JSON (mandatory)`` | `sdd-coder.md:212` | 1 |
| `.claude/agents/sdd-worker.md` (+ `_assets/claude/agents/`) | MODIFY | `command: 'parrot sdd worktree guard --hook \|\| exit 2'` | `sdd-worker.md:32` | 1 |
| `.claude/agents/sdd-worker.md` (+ twin) | MODIFY | ``<classification>. Previous delivery feedback: <prepared.coder_feedback>")`. When `prepared.effort` is non-null, also`` | `sdd-worker.md:368` | 1 |
| `.agents/agents/sdd-coder/agent.md`, `.agents/agents/sdd-worker/agent.md` (+ `_assets/agents/agents/`) | MODIFY | (unverified — check before use) | — | — |
| `.codex/hooks.json` | MODIFY | `"command": "sh scripts/sdd/codex_hook.sh",` | `hooks.json:9` | 1 |
| `.agents/hooks.json` | MODIFY | `"command": "sh ../scripts/sdd/agy_hook.sh",` | `hooks.json:9` | 1 |
| `.gitattributes` | MODIFY | `sdd/ledger/events.jsonl merge=union` | `.gitattributes:2` | 2 (also `:10`; append after the last one) |
| `.claude/rules/worktree-management.md` (+ `_assets/claude/rules/`) | MODIFY | (line 55, sandbox policy paragraph — unverified anchor, check before use) | `:55` | — |
| `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` | MODIFY | (lines 16–20 — unverified anchor, check before use) | `:16` | — |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | `"migrate_index": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),` | `:461` | 1 |

Tests that pin the sandbox path lists and must be updated with M5:
`packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` (:78, :86–101, :562, :971),
`packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` (:388, :488, :499, :509, :550–621, :739, :1338),
`packages/ai-parrot/tests/sdd/test_sdd_launch.py` (:1878).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Hook fast path**: follow `knowledge/wiki/claude_code/hook.py` — stdlib prefilter first,
  heavy imports deferred to the branch that needs them, every exception swallowed, exit code 0.
- **Advisory only**: emit `additionalContext` (or the host's equivalent). Never `updatedInput`,
  never a permission decision. Another `PreToolUse` hook already rewrites Bash input for the
  sandbox; a second rewriting hook would displace it.
- **Lesson text is data**: render it inside the fixed advice template, truncated; never
  concatenate raw lesson text into a prompt outside that template.
- **Redact before storing**, not before displaying. The shared log is public within the team.
- **Append-only**: no code path edits or deletes a line of `events.jsonl`. State changes are new
  events. `rebuild` must be able to recreate `wiki.db` and `triggers.json` from the logs alone.
- **Session identity**: dispatchers export `PARROT_EXPERIENCE_SESSION=<attempt uid>` to the CLI
  process so hook-recorded and replayed events share one session id.
- **Sandbox directory**: bind the directory, not a file (SQLite sidecar files), and create it
  before binding, as `coder_evidence_dirs` does.
- **Worker hook delivery**: sandboxed workers do not load project `.claude/settings.json`; their
  hooks come from `--settings` (built by `native_sandbox_settings`) and agent frontmatter.
- **Installer portability**: hook commands are written as `parrot sdd experience hook …`, never
  as an absolute interpreter path.
- Async-first, Pydantic v2, `logging.getLogger(__name__)`, Google-style docstrings.

### Known Risks / Gotchas

- **Hooks never fail a tool call.** Any error in lookup, reduction or logging is swallowed.
- **Wrong or malicious lesson**: bounded templated text; cannot alter permissions or commands;
  candidates never shown proactively; refutations quarantine; `retire` removes.
- **Self-reinforcement**: validations from the recording session do not count.
- **Noise**: pairing skips `pairing_excluded_executables`; promotion needs two other sessions.
- **Parallel coders**: writes are appends; `rebuild` takes `index.lock` and is idempotent.
- **Stale `triggers.json`**: the pre-tool path may lag by the events appended since the last
  refresh; acceptable, it refreshes on the next failure, briefing or CLI call.
- **Double capture**: hooks and replay could both see one command; replay is a no-op for a
  session that already has hook events.
- **`PostToolUse` on every successful Bash call**: the success path must exit after one `stat`
  of the session file when no failure is pending.
- **Claude Code failure event** is inferred from documentation, not stated outright (Q1).
- **codex `--ignore-user-config`** may or may not drop project hooks (Q2); review profiles pin it.
- **agy** cannot inject from `PostToolUse` and cannot advise from `PreToolUse` without a decision;
  parity for agy is capture + `PostInvocation` advice + briefing (Q3).
- **Native Claude coder output is never parsed by parrot**: its lessons arrive through
  `parrot sdd experience record`, not through `lessons[]`.
- **Worktree outside `.parrot/worktrees/`**: must resolve through the shared root, unlike the
  wiki store.
- **Dirty tracked file**: `export` writes a tracked file; it is called only from `/sdd-done`
  inside the feature worktree, right before a commit that stages it. Never from a hook.
- **Retired signatures** stay known to the reducer so the same failure is not re-learned while
  its graduation issue is open.
- **Lessons fixed upstream**: once the rule or guard lands and the issue closes, the lesson is
  retired automatically.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| none | — | stdlib `sqlite3`/`json` and existing `pydantic` v2 |

---

## Consequences

<!-- decision-audit: input_digest=sha256:f77ebe534ebbf5e8a1d39aaec6d78a6862840d3d2687a5906289da99d62d2356 evaluation_digest=sha256:db0e36abdd61832f8bca1575bb79853bbc5b6bdb5ae69aaa7821dd55b45043e8 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-experience-memory.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: experience-memory, hooks, pitfalls, sandbox, sdd-tooling, wikitoolkit
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "experience-memory",
      "hooks",
      "pitfalls",
      "sandbox",
      "sdd-tooling",
      "wikitoolkit"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-experience-memory.spec.md"
    }
  ],
  "evaluation_digest": "sha256:db0e36abdd61832f8bca1575bb79853bbc5b6bdb5ae69aaa7821dd55b45043e8",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:f77ebe534ebbf5e8a1d39aaec6d78a6862840d3d2687a5906289da99d62d2356",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

Resolved in brainstorm and in the spec intake round:

- [x] Flow type and base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] What promotes `candidate → confirmed` — *Resolved in brainstorm*: recurrence across independent sessions plus evidence that the fix worked; no human in the path.
- [x] Are candidates visible to agents — *Resolved in brainstorm*: only after a matching failure, labeled unverified.
- [x] Where the plane lives — *Resolved in brainstorm*: two tiers, user-global for tools and per-repo for code.
- [x] How a lesson reaches the global tier — *Resolved in brainstorm*: by scope at write time.
- [x] `PreToolUse` behavior on a match — *Resolved in brainstorm*: advisory only; never blocks or rewrites.
- [x] Graduation — *Resolved in brainstorm*: opens a ledger issue past a hit threshold; closing it retires the lesson.
- [x] Non-Claude seats in v1 — *Resolved in brainstorm*: full parity; native hooks where the CLI has them, briefing plus transcript mining where it does not.
- [x] Dedicated directory versus opening `.parrot/wiki` — *Owner: Jesus Lara*: dedicated `.parrot/experience/`; the code wiki stays read-only.
- [x] Global tier writes from a sandbox — *Owner: Jesus Lara*: repo-side outbox moved by a host `sync`; `$HOME` stays read-only.
- [x] Is the repo tier shared through git — *Owner: Jesus Lara*: yes, definition events only; hit and validation events stay local.
- [x] Register the plane as a wiki namespace — *Owner: Jesus Lara*: yes, read-only.
- [x] Which failures are eligible for pairing — *Owner: spec author*: every executable except a configurable exclusion list of validation runners and read-only utilities.
- [x] Is `parrot` callable from in-process seats — *Owner: spec author*: yes inside engine attempts (runner-registry merge, `engine.py:3831`); `lessons[]` remains the primary path for them.
- [x] Native Claude coder lessons — *Owner: spec author*: recorded with `parrot sdd experience record`; its output JSON is not parsed by parrot.
- [x] Hybrid retrieval for deduplication — *Owner: spec author*: deferred; signature hashing deduplicates in v1.

Still open:

- [ ] Q1. Confirm on a live Claude Code session that a Bash call with a non-zero exit fires `PostToolUseFailure` (and not `PostToolUse`), and capture the real payload. The first M4 task must do this before coding `failure_of`. — *Owner: implementer*
- [ ] Q2. Does `codex exec --ignore-user-config` also disable project `.codex/hooks.json`? If yes, review-profile runs rely on replay only. — *Owner: implementer*
- [ ] Q3. Do agy hooks fire under `--print` with permissions skipped, and does `PostInvocation` `injectSteps` reach the model in that mode? If not, agy keeps capture by replay and advice by briefing only, and the parity criterion is recorded as a known gap. — *Owner: implementer, then Jesus Lara if a gap remains*
- [ ] Q4. Do hooks passed with `--settings` apply inside subagents spawned by that session? If not, agent frontmatter is the only delivery path for native coders. — *Owner: implementer*
- [ ] Q5. Thresholds are shipped as defaults (confirm 2 sessions, quarantine 2 refutations, graduate 5 hits across 3 sessions). Adjust after the first weeks of data. — *Owner: Jesus Lara*
- [ ] Q6. `/sdd-done` runs `sync` and `export`; the exact step and anchor in `sdd-done.md` are unverified. — *Owner: implementer*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Status: skipped (exploration document status is `exploration`, not `accepted`)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/sdd-tooling/sdd/experience-memory.md` — create: the plane, lesson lifecycle, hooks per host, CLI, tiers, sharing, graduation, troubleshooting.
  - `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` — update: the new writable directory and the three hook entries.
- **API modules**:
  - `parrot.knowledge.wiki.experience`

---

## Worktree Strategy

- **Isolation**: one feature worktree; the `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (imports `models`, `fastpath`).
  - M3 → M2 (calls `ExperienceService`).
  - M4 → M1 (fast path), M2 (lazy slow path).
  - M6 → M3, M4 (registers the `hook` verb's command line).
  - M7 → M2, M4 (reuses the pre/post logic).
  - M8 → M4, M7 (`CommandOutcome`, `replay`).
  - M9 → M2, M3 (`brief`, `LessonDraft`).
  - M10 → M2. M11 → M2. M12 → M3, M5.
  - M5 has no dependency. M5, M10 and M11 can run concurrently with M3/M4 once M2 lands.
- **Shared files** (their tasks are serialized):
  - `sdd/scripts/native_claude_sandbox.py` — M5 and M6.
  - `sdd/installer.py` — M6, M8, M11.
  - `knowledge/wiki/experience/service.py` — M2 and M10.
  - `.claude/agents/sdd-coder.md`, `.claude/agents/sdd-worker.md` and twins — M6 and M9.
  - `flows/dev_loop/sdd_coder/engine.py`, `models/base.py` — M9 only.
- **Exclusive resources**: packaged asset twins (`scripts/sdd/check_asset_sync.py` must pass
  after every task that edits a command, agent or rule); `.gitattributes`.
- **Cross-feature dependencies**: none must merge first. The hot files above are shared with any
  in-flight SDD-tooling fix; rebase before `/sdd-done`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-13 | Jesus Lara | Initial draft from `sdd/proposals/sdd-experience-memory.brainstorm.md` |
