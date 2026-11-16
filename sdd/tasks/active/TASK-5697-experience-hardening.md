# TASK-5697: Experience memory hardening — dispatcher fail-open, index caps, redaction gaps, CLI edges

**Feature**: FEAT-887 — SDD Experience Memory (`experience.pitfall`)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5696, TASK-5588, TASK-5589, TASK-5590, TASK-5592, TASK-5598, TASK-5599, TASK-5604
**Assigned-to**: unassigned
**Discovered-from**: `issue:46d135cd1101`

---

## Context

Deferred review findings on FEAT-887 (read-only review, unexecuted):

1. `gemini.py` dispatch: `try: replay finally: reset` has no `except`, and the
   `ExperienceInterceptor(...)` construction is unwrapped — unlike codex/google_coding, an
   experience failure can mask the dispatch result or abort the dispatch.
2. `index.py`/`sync.py` ignore sources over 8 MiB: a rebuild then publishes an empty store and an
   empty trigger map `{}`; nothing rotates the logs; `generations/generation-<uuid>/` are never pruned.
3. `fastpath.redact` misses `--password X`, `-pSECRET`, `Authorization: Basic …`, quoted values with
   spaces, JSON `"api_key": "…"` and AWS `AKIA…` keys.
4. `experience_cli`: mutating verbs exit 0 silently when the plane is missing; `export` writes under
   `Path.cwd()` instead of the checkout root; `brief` exits 1 (not the usage-error 2) on a missing
   task file.
5. Codex replay vs hook observation hash may differ for quoted commands (hit inflation, unconfirmed).
6. The in-process briefing lacks a fixed "unverified data" header (delivered by TASK-5696).
7. Hook caps hard-coded instead of read from the published config (delivered by TASK-5696).
Also: several `models.py` classes carry one-line placeholder docstrings.

---

## Scope

- (1) Wrap interceptor construction and replay in `gemini.py` exactly like the codex dispatcher:
  experience errors are logged and never mask or abort the dispatch.
- (2) Rebuild fails closed (returns `-1`, keeps the published generation) when a source exceeds the
  read cap instead of publishing an empty store; prune superseded generations (keep the current and
  the previous one); `export` rotates an over-cap repo log into a sealed segment that stays a source.
- (3) Extend `redact` for the listed shapes, with tests.
- (4) Missing plane: keep the spec's exit code 0 and empty stdout (Module 3), but log a one-line
  stderr warning for the mutating verbs; `export` writes under the checkout root; a missing
  `brief` task file is a usage error (exit 2).
- (5) Verify whether codex replay and hook observation identities diverge for quoted commands; fix
  if they do, otherwise record the evidence in the Completion Note.
- (6)/(7): confirm delivered by TASK-5696.
- Replace the placeholder model docstrings.

**NOT in scope**: anything already delivered by TASK-5693..TASK-5696.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py` | MODIFY | fail-open interceptor |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py` | MODIFY | fail closed on oversize; prune generations |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py` | MODIFY | fail closed on oversize; rotate on export |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` | MODIFY | redaction patterns |
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` | MODIFY | CLI edge cases |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | MODIFY | docstrings |
| `packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py` | MODIFY | fail-open tests |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py` | MODIFY | oversize + prune tests |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py` | MODIFY | rotation test |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` | MODIFY | redaction tests |
| `packages/ai-parrot/tests/sdd/test_experience_cli.py` | MODIFY | CLI edge tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# flows/dev_loop/dispatchers/gemini.py:128 (construction) and :275-280 (replay in finally)
# flows/dev_loop/dispatchers/codex.py:335, 488-492 — the fail-open pattern to mirror
# knowledge/wiki/experience/index.py:34 _MAX_SOURCE_BYTES; :94 rebuild(); :307 _read_events()
# knowledge/wiki/experience/sync.py:26 _MAX_SOURCE_BYTES; :211 _read_bounded()
# knowledge/wiki/experience/fastpath.py:210
def redact(text: str) -> str
# sdd/scripts/experience_cli.py:134 _dispatch(); :189 export_shared(service.plane_dir, Path.cwd())
```

### Does NOT Exist
- No log-rotation helper exists today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_experience_cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py#redact",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py#ExperienceIndex.rebuild"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `fastpath.py` is a protected control file — implemented from the host.
- Redaction must stay idempotent (`redact(redact(x)) == redact(x)`).

---

## Implementation Blueprint

### Steps (in order)
1. gemini fail-open; 2. index/sync caps, prune, rotation; 3. redaction; 4. CLI; 5. codex identity check; 6. docstrings.

---

## Acceptance Criteria

- [ ] An interceptor that raises on construction or replay never changes a gemini dispatch result.
- [ ] An over-cap source never publishes an empty index; old generations are pruned.
- [ ] Every listed secret shape is redacted.
- [ ] CLI edge cases behave as scoped.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_experience_cli.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py -q`

---

## Test Specification

```python
async def test_gemini_dispatch_survives_interceptor_failures(): ...
async def test_rebuild_fails_closed_on_oversize_source(tmp_path): ...
async def test_rebuild_prunes_superseded_generations(tmp_path): ...
def test_redact_covers_password_flags_basic_auth_json_and_aws_keys(): ...
def test_cli_mutating_verb_warns_when_plane_missing(): ...
def test_cli_export_writes_under_checkout_root(): ...
def test_cli_brief_missing_task_file_is_usage_error(): ...
```

---

## Agent Instructions

Follow `docs/sdd/WORKFLOW.md` § "Implementing a task by hand" inside
`.parrot/worktrees/feat-FEAT-887-sdd-experience-memory`.

---

## Completion Note

*(Agent fills this in when done)*
