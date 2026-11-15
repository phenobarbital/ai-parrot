---
title: SDD experience memory
summary: Scoped, replayable operational lessons for SDD agents.
---

# SDD experience memory

## Purpose

The SDD experience memory subsystem captures, indexes, and replays operational lessons learned during SDD agent sessions. It provides a scoped, reviewed-log trust boundary that enables agents to learn from past mistakes and successes without exposing sensitive data or violating the sandbox's read-only guarantees.

Key characteristics:
- **Scoped to a session**: Each feature or brief worktree maintains its own experience store under `.parrot/experience/`.
- **Reviewed-log trust model**: Lessons are recorded as structured events and reviewed before graduation to shared tiers.
- **Replayable**: Lessons can be queried and replayed to inform future decisions within the same trust scope.
- **Bounded I/O**: All operations respect the sandbox's filesystem and network isolation policies.

## Public API

- [`ExperienceService`](ref:parrot.knowledge.wiki.experience.service.ExperienceService) — Core service for recording, querying, and managing experience events.
- [`ExperienceIndex`](ref:parrot.knowledge.wiki.experience.index.ExperienceIndex) — Index and search interface over recorded lessons.

## Configuration & Parameters

### Environment Variables

- `PARROT_HOME`: Root directory for Parrot artifacts (defaults to `~/.parrot`). The experience store lives under `${PARROT_HOME}/experience` for shared tiers and `.parrot/experience/` in the primary checkout for session-scoped data.
- `PARROT_EXPERIENCE_SESSION`: Optional session identifier; when unset, the current worktree name is used.

### ExperienceConfig (defaults)

```python
ExperienceConfig(
    store_path=Path(".parrot/experience/"),
    max_lessons_per_namespace=1000,
    max_payload_bytes=1024 * 1024,  # 1 MiB
    quarantine_threshold=0.3,  # 30% of max_lessons triggers quarantine review
    revision_ttl_days=30,
)
```

## Usage Examples

### Initialize and record a lesson

```python
from parrot.knowledge.wiki.experience import ExperienceService, LessonDraft

svc = ExperienceService.from_worktree(cwd=Path.cwd())

# Record a pitfall lesson
draft = LessonDraft(
    category="pitfall",
    trigger={
        "executable": "gh",
        "subcommand": "pr edit",
        "error_signature": "Projects classic is no longer supported",
    },
    symptom="The pull-request edit command fails before applying the change.",
    solution="Use the REST pull-request endpoint for the same update.",
    fix_example="gh api -X PATCH repos/acme/widgets/pulls/42",
    scope_paths=["src/widgets"],
)

await svc.record_lesson(draft)
```

### Query lessons by namespace

```python
# Query all lessons in the current namespace
lessons = await svc.query_lessons(namespace="experience")
for lesson in lessons:
    print(f"{lesson.category}: {lesson.symptom}")
```

### Sync and export

```python
# Export lessons to a shared tier (requires review)
await svc.export_lessons(target_tier="shared", namespace="experience")

# Sync with a remote store (e.g., for backup)
await svc.sync_remote(remote_name="origin", push=True)
```

### Retire stale lessons

```python
# Retire lessons older than the TTL
retired = await svc.retire_stale(revision_ttl_days=30)
```

### Deterministic A/B/C/D integration scenario

The end-to-end test (`test_end_to_end.py`) demonstrates a full cycle:

1. **A (Record)**: Agent encounters a pitfall and records a lesson.
2. **B (Query)**: Same agent queries lessons before attempting a similar operation.
3. **C (Replay)**: Lesson is replayed to avoid the pitfall.
4. **D (Graduate)**: After review, the lesson is promoted to the `shared` tier.

Run it with:

```bash
pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py -q
```

## Gotchas

### Candidate advice
- Lessons are **advisory only**: Agents must never treat them as absolute truth. Always validate advice against the current context.
- **Quarantine**: When the store approaches capacity (`quarantine_threshold`), new lessons are held for review before indexing.

### Revisions and locales
- Lessons are **immutable** after recording. To update, record a new revision with an incremented `revision` field.
- Locale-specific lessons use the `locale` field (e.g., `en-US`). Unset means "any locale."

### Stale generations and unknown outcomes
- Lessons older than `revision_ttl_days` are retired automatically. Stale lessons may reference outdated APIs or behaviors.
- If a replayed lesson leads to an unknown outcome, record a new lesson with the `unknown_outcome` flag set.

### Bounded I/O and replay identity
- Payloads are limited to `max_payload_bytes`. Large payloads are truncated or rejected.
- Replay identity is scoped to the namespace. A lesson recorded in namespace `A` is not replayed in namespace `B` unless explicitly shared.

### Hook timing and host differences
- **Hook timing**: Experience hooks run **after** the tool call (PostToolUse) and **after** tool failure (PostToolUseFailure). There is no PreToolUse hook to avoid interfering with the sandbox's test-scope guard.
- **Host differences**: On macOS, the Seatbelt sandbox may behave differently. Lessons recorded on macOS should note the platform in their `scope_paths` or `trigger` metadata.

### Troubleshooting

- **"Experience store not writable"**: Ensure `.parrot/experience/` exists and is writable. The sandbox mounts it read-write, but the primary checkout's permissions must allow it.
- **"Namespace not found"**: Verify the namespace with `parrot sdd experience list --ns <namespace>`.
- **"Lesson rejected (quarantine)"**: The store is full. Retire stale lessons or increase `max_lessons_per_namespace`.

## Related

- [Native sandbox](../dev_loop/claude-native-sandbox.md) — Filesystem and network isolation policies that experience hooks respect.
