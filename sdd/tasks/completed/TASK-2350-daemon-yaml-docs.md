# TASK-2350: Document `default_filters` in `fireflies_daemon.yaml`

**Feature**: FEAT-441 — Fireflies MCP Meeting Filters & Native Summary Retrieval
**Spec**: `sdd/specs/fireflies-mcp-improvements.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2347
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `default_filters` (TASK-2347) is only useful for the
scheduled-daemon use case (spec Problem Statement) if an operator can
actually discover and set it via `fireflies_daemon.yaml` — this task is
documentation-only, adding a commented example so the option is visible.

---

## Scope

- Add a commented, illustrative `default_filters:` example under
  `agent.kwargs` in `examples/agents/fireflies_daemon.yaml`, following the
  file's existing commenting style (e.g. the already-commented
  `# fireflies_token: FIREFLIES_API_KEY` line).
- Update the file's top-of-file comment block if needed to mention the new
  option exists (optional, only if it improves discoverability without
  disrupting the existing structure).

**NOT in scope**:
- Enabling `default_filters` by default (must stay commented-out/opt-in,
  consistent with the rest of the file's style).
- Any change to `exposed_methods:`, `scheduler:`, or other existing YAML
  sections.
- Documenting `include_summary` (TASK-2349's capability) — the spec's
  Module 5 scope is `default_filters` only; do not expand beyond it.
- Any code change — this task touches only the YAML file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/fireflies_daemon.yaml` | MODIFY | Add commented `default_filters` example under `agent.kwargs`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
N/A — this task modifies only a YAML file, no Python code.

### Existing Signatures to Use
```yaml
# examples/agents/fireflies_daemon.yaml (CURRENT, verified 2026-08-21 on dev)
name: fireflies-sync

agent:
  target: "parrot.agents.obsidian:FirefliesObsidianAgent"
  kwargs:
    name: "FirefliesObsidianSync"
    vault_path: "${OBSIDIAN_VAULT_PATH:-~/vaults/notes}"   # env var with fallback
    meetings_folder: "meetings"
    # fireflies_token: FIREFLIES_API_KEY  # bare-name shorthand also works

exposed_methods:
  - sync_fireflies_transcripts
  - summarize_transcript

scheduler:
  enabled: true

log_level: INFO
```

### Does NOT Exist
- ~~A `default_filters:` key anywhere in `fireflies_daemon.yaml` today~~ — does not exist; this task adds it (commented, as an example).
- ~~`summarize_pending_transcripts` in `exposed_methods:`~~ — not present today either; out of scope to add it (unrelated to this feature).

---

## Implementation Notes

### Pattern to Follow
```yaml
agent:
  target: "parrot.agents.obsidian:FirefliesObsidianAgent"
  kwargs:
    name: "FirefliesObsidianSync"
    vault_path: "${OBSIDIAN_VAULT_PATH:-~/vaults/notes}"
    meetings_folder: "meetings"
    # fireflies_token: FIREFLIES_API_KEY  # bare-name shorthand also works
    # default_filters:                    # FEAT-441: standing scope applied to every scheduled sync
    #   mine: true                        # e.g. only sync meetings you organized/attended
    #   # channel_id: "<fireflies-channel-id>"
```

### Key Constraints
- Keep the addition commented-out by default, matching the existing
  `# fireflies_token: ...` line's style — this is a documentation example,
  not a default-on behavior change.
- Do not reformat or reorder unrelated existing YAML content.

### References in Codebase
- `sdd/specs/fireflies-mcp-improvements.spec.md` §3 Module 5.
- `examples/agents/fireflies_daemon.yaml` — file to edit in place.

---

## Acceptance Criteria

- [ ] `examples/agents/fireflies_daemon.yaml` contains a commented `default_filters:` example under `agent.kwargs`.
- [ ] The YAML file still parses as valid YAML after the change (`python -c "import yaml; yaml.safe_load(open('examples/agents/fireflies_daemon.yaml'))"`).
- [ ] No other section of the file was modified.

---

## Test Specification

```python
# No pytest suite for this task — validate with a YAML parse check:
import yaml

def test_daemon_yaml_still_valid():
    with open("examples/agents/fireflies_daemon.yaml") as f:
        doc = yaml.safe_load(f)
    assert doc["agent"]["target"] == "parrot.agents.obsidian:FirefliesObsidianAgent"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fireflies-mcp-improvements.spec.md` for full context.
2. **Check dependencies** — verify TASK-2347 is in `sdd/tasks/completed/`
   (so the `default_filters` kwarg being documented actually exists).
3. **Verify the Codebase Contract** — re-read the current
   `fireflies_daemon.yaml` to confirm it matches the excerpt above before
   editing.
4. **Update status** in the per-spec index → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2350-daemon-yaml-docs.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: claude-sonnet-5 (sdd-start session)
**Date**: 2026-08-22
**Notes**: Added a commented `default_filters:` example (with `mine: true`
and a commented `channel_id` line) under `agent.kwargs` in
`examples/agents/fireflies_daemon.yaml`, matching the existing
`# fireflies_token: ...` commenting style. Verified the file still parses
as valid YAML and that `default_filters` does not appear in the parsed
`agent.kwargs` dict (stays opt-in/commented). No other section touched —
`git diff` confirms a 3-line, single-hunk addition.

**Deviations from spec**: none.
