# TASK-5154: Sweep docs/, examples/ and plugins/ off gemini-2.5-{pro,flash}

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5150
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (docs/examples) and U3: every surface follows the code. 77 mentions sit in 13 docs,
25 example files and one plugin agent. After 2026-12-01 Google auto-routes any missed pin to a different
model and bill, so examples that users copy must not keep teaching a retired id. A guard test keeps these
trees clean (spec AC-10). This task depends on TASK-5150: the guard scans `docs/`, including
`docs/config.md` and `docs/configuration/llm-defaults.md`, which TASK-5150 rewrites.

## Scope

Apply the spec §2 replacement table to the files below (whole ids only):
- `gemini-2.5-pro` → `gemini-4-argon`
- `gemini-2.5-flash` → `gemini-3.8-flash`
- `gemini-2.5-flash-native-audio-preview-*` → `gemini-3.8-live`
- `gemini-2.5-flash-preview-tts` / `-pro-preview-tts` → `gemini-3.8-flash-tts`

Leave `gemini-2.5-flash-lite` and `gemini-2.5-flash-image` untouched. Create the docs guard test.

**Worktree note (orchestrator, 2026-11-04)**: 5 listed files (`examples/decision_simple_working.py`, `examples/orchestration/messaging.py`, `examples/orchestration/sample_autonomous_agent.py`, `examples/voice/bot.py`, `plugins/agents/epson.py`) are untracked/gitignored and exist only in the main checkout; removed from the contract. Operator must swap their gemini-2.5 ids by hand.

**NOT in scope**: `docs/config.md`, `docs/configuration/llm-defaults.md`, `docs/migration/gemini-2-5-retirement.md`
(TASK-5150; the migration guide names the retired ids on purpose); `sdd/` (historical records); any `src/` file.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent_factory_handler.md` | MODIFY | id swap |
| `docs/architecture/04-interaction-surface.md` | MODIFY | id swap (native-audio at :152) |
| `docs/architecture/07-agentcrew.md` | MODIFY | id swap |
| `docs/audio-form-voice-modes.md` | MODIFY | id swap |
| `docs/experts/domain-experts.md` | MODIFY | id swap |
| `docs/frontend/voicebot-realtime-frontend-guide.md` | MODIFY | id swap (:312 `"gemini-2.5-..."` → `"gemini-3.8-live"`) |
| `docs/migration/video-reel-omni-veo-reliability.md` | MODIFY | id swap |
| `docs/testing/agentic-e2e.md` | MODIFY | id swap |
| `docs/toolkits/execution_plan_toolkit.md` | MODIFY | id swap |
| `docs/voice_chat.md` | MODIFY | id swap |
| `docs/web-agent.md` | MODIFY | id swap |
| `docs/web-navigator-agent.md` | MODIFY | id swap |
| `docs/whatif_scenarios.md` | MODIFY | id swap |
| `examples/advisors/rag.py` | MODIFY | id swap |
| `examples/agents/a2ui/linked_e2e/README.md` | MODIFY | id swap |
| `examples/agents/a2ui/linked_e2e/server.py` | MODIFY | id swap |
| `examples/agents/webbrowser/README.md` | MODIFY | id swap |
| `examples/crew/market_researcher.py` | MODIFY | id swap |
| `examples/crew/product_research_crew.json` | MODIFY | id swap (8 hits) |
| `examples/crew/reproduce_orchestrator.py` | MODIFY | id swap |
| `examples/crew/simple_a2a_agent.py` | MODIFY | id swap |
| `examples/data/scenario_test.py` | MODIFY | id swap |
| `examples/data/whatif_scenario_e2e.py` | MODIFY | id swap |
| `examples/db_tool_usage.py` | MODIFY | id swap |
| `examples/flow/consensus_synthesis_flow.py` | MODIFY | id swap |
| `examples/genmedia_example.py` | MODIFY | id swap |
| `examples/google/structured_with_tools.py` | MODIFY | id swap |
| `examples/knowledge_wiki/obsidian_wiki_agent.py` | MODIFY | id swap |
| `examples/matrix_swarm/agents.yaml` | MODIFY | id swap |
| `examples/matrix_swarm/.env.example` | MODIFY | id swap |
| `examples/matrix_swarm/README.md` | MODIFY | id swap |
| `examples/navigator_agent.py` | MODIFY | id swap |
| `examples/passkey/server.py` | MODIFY | id swap |
| `examples/tool/o365.py` | MODIFY | id swap |
| `packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py` | CREATE | guard over docs/examples/plugins |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — the guard uses only stdlib (re, pathlib, pytest)
```

### Existing Signatures to Use
```text
File list = `grep -rl 'gemini-2\.5' docs examples plugins` at 63e72545ce, minus docs/config.md and
docs/configuration/llm-defaults.md (TASK-5150). Total 77 mentions (proposal F008).
Some hits are gemini-2.5-flash-lite or -image: keep those.
```

### Does NOT Exist
- ~~a 4.x flash id~~ — flash-class mentions become `gemini-3.8-flash`, never `gemini-4-flash`.
- ~~`examples/matrix_swarm/.env`~~ — only `.env.example` is tracked.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/agent_factory_handler.md", "action": "MODIFY"},
    {"path": "docs/architecture/04-interaction-surface.md", "action": "MODIFY"},
    {"path": "docs/architecture/07-agentcrew.md", "action": "MODIFY"},
    {"path": "docs/audio-form-voice-modes.md", "action": "MODIFY"},
    {"path": "docs/experts/domain-experts.md", "action": "MODIFY"},
    {"path": "docs/frontend/voicebot-realtime-frontend-guide.md", "action": "MODIFY"},
    {"path": "docs/migration/video-reel-omni-veo-reliability.md", "action": "MODIFY"},
    {"path": "docs/testing/agentic-e2e.md", "action": "MODIFY"},
    {"path": "docs/toolkits/execution_plan_toolkit.md", "action": "MODIFY"},
    {"path": "docs/voice_chat.md", "action": "MODIFY"},
    {"path": "docs/web-agent.md", "action": "MODIFY"},
    {"path": "docs/web-navigator-agent.md", "action": "MODIFY"},
    {"path": "docs/whatif_scenarios.md", "action": "MODIFY"},
    {"path": "examples/advisors/rag.py", "action": "MODIFY"},
    {"path": "examples/agents/a2ui/linked_e2e/README.md", "action": "MODIFY"},
    {"path": "examples/agents/a2ui/linked_e2e/server.py", "action": "MODIFY"},
    {"path": "examples/agents/webbrowser/README.md", "action": "MODIFY"},
    {"path": "examples/crew/market_researcher.py", "action": "MODIFY"},
    {"path": "examples/crew/product_research_crew.json", "action": "MODIFY"},
    {"path": "examples/crew/reproduce_orchestrator.py", "action": "MODIFY"},
    {"path": "examples/crew/simple_a2a_agent.py", "action": "MODIFY"},
    {"path": "examples/data/scenario_test.py", "action": "MODIFY"},
    {"path": "examples/data/whatif_scenario_e2e.py", "action": "MODIFY"},
    {"path": "examples/db_tool_usage.py", "action": "MODIFY"},
    {"path": "examples/flow/consensus_synthesis_flow.py", "action": "MODIFY"},
    {"path": "examples/genmedia_example.py", "action": "MODIFY"},
    {"path": "examples/google/structured_with_tools.py", "action": "MODIFY"},
    {"path": "examples/knowledge_wiki/obsidian_wiki_agent.py", "action": "MODIFY"},
    {"path": "examples/matrix_swarm/agents.yaml", "action": "MODIFY"},
    {"path": "examples/matrix_swarm/.env.example", "action": "MODIFY"},
    {"path": "examples/matrix_swarm/README.md", "action": "MODIFY"},
    {"path": "examples/navigator_agent.py", "action": "MODIFY"},
    {"path": "examples/passkey/server.py", "action": "MODIFY"},
    {"path": "examples/tool/o365.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Run the four whole-id substitutions on every MODIFY file — *why*: the spec §2 table is the single mapping.
   Order matters: replace the native-audio and preview-tts ids **before** the plain `gemini-2.5-flash` rule.
2. Hand-check every `docs/` diff — *why*: prose such as "2.5 Pro works well with…" may need rewording, not a swap.
3. Create the guard test and run it.

### Substitution rules (apply per file, in this order)
```python
import re
RULES = (
    (r"gemini-2\.5-flash-native-audio-preview-\d\d-\d{4}", "gemini-3.8-live"),
    (r"gemini-2\.5-flash-native-audio-preview(?![-\w])", "gemini-3.8-live"),
    (r"gemini-2\.5-(?:flash|pro)-preview-tts", "gemini-3.8-flash-tts"),
    (r"gemini-2\.5-pro(?![-\w])", "gemini-4-argon"),
    (r"gemini-2\.5-flash(?![-\w])", "gemini-3.8-flash"),
)
# FILL IN: docs/frontend/voicebot-realtime-frontend-guide.md:312 has the truncated `"gemini-2.5-..."` → write "gemini-3.8-live"
# FILL IN: labels like "Gemini 2.5 Flash" / "Gemini 2.5 Pro" in prose → "Gemini 3.8 Flash" / "Gemini 4 Argon"
```

### `packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py` (CREATE)
```python
"""FEAT-798 (spec AC-10): docs/, examples/ and plugins/ do not present retired gemini-2.5 ids."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED = ("docs", "examples", "plugins")
SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".example", ".toml"}
# The migration guide names the retired ids on purpose.
EXCLUDED = {"docs/migration/gemini-2-5-retirement.md"}
RETIRED = re.compile(r"gemini-2\.5-(?:pro|flash)(?![-\w])|gemini-2\.5-flash-native-audio|gemini-2\.5-(?:flash|pro)-preview-tts")


def test_no_retired_gemini_id_in_docs_examples_plugins() -> None:
    hits: list[str] = []
    for top in SCANNED:
        for path in (REPO_ROOT / top).rglob("*"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if not path.is_file() or rel in EXCLUDED or "node_modules" in path.parts:
                continue
            if path.suffix not in SUFFIXES and not path.name.endswith(".env.example"):
                continue
            # FILL IN: read text (utf-8, errors="ignore"), append f"{rel}:{lineno}" for each RETIRED match
    assert not hits, "retired gemini-2.5 ids found:\n" + "\n".join(hits)
```
**Why**: `parents[3]` resolves `packages/ai-parrot/tests/<file>` to the repo root. FILL IN: verify the depth.
The pattern lets `gemini-2.5-flash-lite` and `-image` through (`(?![-\w])`).

### FILL IN checklist
- [ ] Truncated id in the voicebot frontend guide.
- [ ] Prose labels rewritten.
- [ ] Guard loop body; `REPO_ROOT` depth verified.

---

## Acceptance Criteria

- [ ] `grep -rlE 'gemini-2\.5-(pro|flash)\b' docs examples plugins` lists only `docs/migration/gemini-2-5-retirement.md` (flash-lite/flash-image may remain anywhere) (spec AC-10).
- [ ] `ruff check` clean on the touched `.py` example files (syntax unchanged).

## Validation Commands
- `pytest packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py -q`

## Test Specification
See the CREATE block.

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug google-migration --feature-id FEAT-798 --spec sdd/specs/google-migration.spec.md --index sdd/tasks/index/google-migration.json`
2. Read the spec (§2 table, §3 M7).
3. Check dependencies: TASK-5150 must be `done`.
4. Re-run `grep -rl 'gemini-2\.5' docs examples plugins` and compare it with the file table. Report any new file in the Completion Note and include it.
5. Mark the task `in-progress` in the index and commit only that file.
6. Implement from the blueprint.
7. Run the Validation Commands.
8. Commit only the files listed above.
9. Close with `parrot sdd task close TASK-5154 google-migration verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator); coder gpt-5.6-terra
**Date**: 2026-11-04
**Verification**: verified
**Notes**: Contract trimmed by orchestrator: 5 untracked/gitignored files (decision_simple_working.py, orchestration/messaging.py, orchestration/sample_autonomous_agent.py, voice/bot.py, plugins/agents/epson.py) exist only in the main checkout and still need their gemini-2.5 ids swapped by the operator. Merge-tier validation (chunk 3) completed green.

**Deviations from spec**: none
