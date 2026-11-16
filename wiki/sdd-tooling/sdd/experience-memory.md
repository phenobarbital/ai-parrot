---
title: SDD experience memory
summary: Replayable operational pitfalls (command, error, workaround) captured from SDD agent sessions, briefed at task start and shared through a reviewed log.
---

# SDD experience memory

## Purpose

Experience memory remembers **pitfalls**: a command that failed with a recognisable error, and the workaround that
worked. The motivating case is `gh pr edit` failing with `Projects classic is no longer supported`, whose fix is
`gh api -X PATCH`. Once recorded and confirmed, the workaround is shown to later agents before they repeat the mistake
(a task-start briefing) and when the same failure recurs (advice injected after the failing tool call).

The only lesson category today is `pitfall`. Everything is **advisory**: lesson text is quoted, unverified data and
never an instruction that overrides the task, the spec or repository conventions.

How it works:

1. **Capture.** Post-tool hooks and the in-process interceptor watch command outcomes. A failure followed by a
   successful, related command is paired into a candidate lesson (`source: paired`). Coders can also author a lesson
   (`source: authored`) through `DevelopmentOutput.lessons` or `parrot sdd experience record`.
2. **Append-only log.** Everything is an event in `.parrot/experience/events.jsonl` of the **primary checkout**. The
   index and the lesson states are *reduced* from the log; they are never a source of truth.
3. **Lifecycle.** A candidate becomes `confirmed` after it helps in enough distinct sessions, goes `quarantined` when
   refuted, and ends `retired`. Confirmed lessons that keep recurring *graduate* into a ledger issue.
4. **Sharing.** Definitions are exported to `sdd/experience/lessons/` and committed with the feature, so a fresh
   clone starts with the team's lessons. This reviewed shared log is the trust boundary.

## Public API

- [`ExperienceService`](ref:parrot.knowledge.wiki.experience.service.ExperienceService) — facade over the plane:
  `from_root`, `record`, `match_failure`, `brief`, `list_lessons`, `get_lesson`, `retire`. A missing or disabled plane
  yields a service that no-ops instead of raising.
- [`ExperienceIndex`](ref:parrot.knowledge.wiki.experience.index.ExperienceIndex) — generation-based index rebuilt from
  the event log.
- [`LessonDraft`](ref:parrot.knowledge.wiki.experience.models.LessonDraft),
  [`LessonTrigger`](ref:parrot.knowledge.wiki.experience.models.LessonTrigger),
  [`Lesson`](ref:parrot.knowledge.wiki.experience.models.Lesson) — the submitted draft and the reduced view.
- [`ExperienceConfig`](ref:parrot.knowledge.wiki.experience.models.ExperienceConfig) — tunables (below).
- [`ExperienceInterceptor`](ref:parrot.flows.dev_loop.experience.ExperienceInterceptor) — feeds command outcomes of
  in-process dev-loop seats into the plane.
- `parrot.knowledge.wiki.experience.sync` — `sync_global`, `export_shared`, `register_namespace`, `global_plane_dir`.
- `parrot.knowledge.wiki.experience.graduation.graduate` — opens/retires the recurring-pitfall ledger issue.

## Configuration & Parameters

### Lesson vocabulary

| Field | Values |
|---|---|
| `state` | `candidate`, `confirmed`, `quarantined`, `retired` |
| `tier` | `repo`, `global` |
| `source` | `paired`, `authored`, `mined` |

**Tiers and namespace.** A lesson is `repo` tier when it has `scope_paths`, or its executable is a relative path
(`./`, `../`) or an absolute path inside the checkout. Otherwise it is `global`: a tool-level pitfall such as `gh`.
`repo` lessons stay in the checkout's `.parrot/experience/`. `global` lessons are also copied by `sync_global` into
the user-global plane, `${PARROT_HOME}/experience` (`parrot_home()` default is the user's Parrot home), so they help in
every repository registered with `register_namespace`.

### ExperienceConfig defaults

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch; `false` makes every operation a no-op |
| `confirm_sessions` | `2` | Distinct sessions needed to confirm a candidate |
| `quarantine_refutations` | `2` | Refutations that quarantine a lesson |
| `graduate_hits` / `graduate_sessions` | `5` / `3` | Recurrence needed to graduate into a ledger issue |
| `brief_max_entries` | `5` | Entries in a task-start briefing (hard-capped) |
| `brief_token_budget` | `400` | Approximate briefing budget |
| `inject_min_score` | `0.35` | Minimum match score to inject advice |
| `advice_cooldown_seconds` | `600` | Do not repeat advice for the same lesson inside this window |
| `max_session_pending` | `32` | Unpaired failures tracked per session |

The service reads the project's wiki config (`WikiProjectConfig.experience`); defaults apply when none is set. Pairing
ignores noisy executables such as `pytest`, `ruff`, `mypy`, `black`, `grep`, `ls`, `cat`.

### Environment

- `PARROT_HOME` — user-global root; the global plane is `${PARROT_HOME}/experience`.
- `PARROT_EXPERIENCE_SESSION` — optional session key read by the hook adapter to group events by session.

### CLI

`parrot sdd experience <verb>`:

| Verb | Purpose |
|---|---|
| `init` | Initialise the plane in this checkout |
| `brief --task-file <file> [--max N]` | Print the bounded *Known pitfalls* block for a task |
| `record --executable X --solution S [--subcommand] [--error] [--symptom] [--path P]...` | Record an authored candidate |
| `list [--state S] [--tier T] [--json]` / `show <id> [--json]` | Inspect lessons |
| `retire <id> --reason R` | Retire a lesson |
| `sync` | Copy global-tier events into `${PARROT_HOME}/experience` (best-effort) |
| `export` | Write new shared definitions under `sdd/experience/lessons/` and print the new path |
| `rebuild` | Rebuild indexes from the log |

### Where it plugs into the SDD flow

- **Task start** (`/sdd-start`): `parrot sdd experience brief --task-file <task>` — fails open (`|| true`).
- **Coders**: MCP/in-process seats return `lessons: []` in `DevelopmentOutput`; native Claude output is not parsed, so
  a native session uses `parrot sdd experience record`. The worker forwards `prepared.experience_briefing` as a
  separate *Known pitfalls* field, leaving `prepared.coder_feedback` untouched.
- **Host launch**: the sandbox preflight runs `sync_global`, and the installer calls `register_namespace`; neither can
  block a launch.
- **Closeout** (`/sdd-done` Step 7): inside the feature worktree run `sync` then `export`, and stage only the newly
  returned `sdd/experience/lessons/<digest>.jsonl` path with the index and completed task files.

## Usage Examples

The runnable example is the deterministic integration scenario `test_gh_pr_edit_end_to_end` in
`packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py`: it records the authored `gh api -X PATCH`
workaround, drives the production interceptor through a failing and a recovering command, then retires the lesson.
Run it with `PARROT_HOME` pointing at a temporary directory:

```bash
PYTHONPATH=packages/ai-parrot/src pytest \
  packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py -q
```

Authoring and recording a lesson from Python:

```python
from pathlib import Path

from parrot.knowledge.wiki.experience.models import LessonDraft, LessonTrigger
from parrot.knowledge.wiki.experience.service import ExperienceService

service = ExperienceService.from_root(Path.cwd())  # no-ops when no plane/checkout is found
draft = LessonDraft(
    trigger=LessonTrigger(
        executable="gh",
        subcommand="pr edit",
        error_signature="Projects classic is no longer supported",
        error_excerpt="Projects classic is no longer supported",
        command_example="gh pr edit 12 --base dev",
    ),
    symptom="The pull-request edit command rejects project fields.",
    solution="Use gh api -X PATCH for the same pull-request update.",
    fix_example="gh api -X PATCH repos/acme/widgets/pulls/12",
)
lesson_id = await service.record(draft, session="demo", source="authored")  # "" when the plane is unavailable
print(await service.brief("Fix PR edit", ["scripts/release.py"]))
```

The same lesson as `DevelopmentOutput.lessons[]` uses the `LessonDraft` shape (`category`, `trigger`, `symptom`,
`solution`, `fix_example`, `scope_paths`).

## Gotchas

- **Candidate advice.** A `candidate` is unconfirmed. It is only injected when its score reaches `inject_min_score`,
  and it is always quoted data, never an instruction.
- **Secrets are redacted** before anything is stored (bearer tokens, URL credentials, long hex/base64 strings,
  secret assignments), and event size is bounded (`MAX_EVENT_BYTES = 4096`). Do not rely on redaction: never put
  secrets in a lesson.
- **Revisions.** A solution change creates a new `solution_rev` of the same lesson; earlier revisions are kept in
  `Lesson.revisions`. Evidence for an old revision does not confirm the new one.
- **Stale generations.** Reads use a published index generation. After a write the index is stale until the next
  `refresh()`/`rebuild`, which runs off the hook path. If advice looks missing, run `parrot sdd experience rebuild`.
- **Unknown outcomes.** A command whose success cannot be determined (`ok` is `None`) is neither a failure nor a
  recovery, so it never pairs or confirms anything.
- **Bounded I/O.** Event, shared-log and config reads are size-capped; an oversized or unreadable log makes `sync`
  return `0` instead of copying a partial view. Replay identity is the event id, so syncing is idempotent.
- **Hook timing.** Claude hooks are `PostToolUse` and `PostToolUseFailure` only. There is no pre-tool experience hook,
  so the sandbox's test-scope guard is not involved. Antigravity (`agy`) uses `PostToolUse` plus `PostInvocation`;
  Codex, Gemini and in-process seats are wired through their dispatchers. Hosts differ in what a hook payload
  carries, so the adapter normalises exit codes and transcripts and ignores what it cannot read.
- **Host differences.** Only Linux and WSL2 are qualified for the native sandbox; see the sandbox page.

### Troubleshooting

- **Nothing is ever recorded.** Check the plane exists (`.parrot/experience/` in the primary checkout, created by
  `parrot sdd experience init`) and that `ExperienceConfig.enabled` is true. In a worktree the plane is the *primary
  checkout's*; the native sandbox keeps it writable while the rest of the primary checkout is read-only.
- **Hook integrity.** The isolated hook files `experience_hook.py`, `fastpath.py` and `launcher.py` are OS-denied
  control files for workers, and the hook runs under the absolute shared-venv Python with `-I -m`. A worker cannot
  edit them; if hooks stop firing, reinstall with `parrot sdd install`, not by editing the copies.
- **`record` exits 2.** `--executable` and `--solution` are required.
- **Global lessons do not reach another repository.** Run `parrot sdd experience sync` in the source repository, and
  make sure the target repository was registered by the installer.
- **Closeout staged too much.** Only the path printed by `export` belongs in the closeout commit — never the whole
  `sdd/experience/lessons/` directory.

## Related

- [Claude native sandbox](../dev_loop/claude-native-sandbox.md) — writable `.parrot/experience/` and the isolated
  hook control-file policy that this subsystem relies on.
- [Worktree management rule](../../../.claude/rules/worktree-management.md) — the same writable-directory rule for
  worktree agents.
