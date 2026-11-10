# TASK-5383: Documentation — abstract-client, pageindex-agentic-retrieval

**Feature**: FEAT-848 — Client tool-loop capability flag
**Spec**: `sdd/specs/client-tool-loop-capability.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5379, TASK-5380, TASK-5381
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and §10 (G5, AC-6; docs policy `required`). The FEAT-843 wiki page lists six providers as
"no tool execution in `ask()`" that actually inherit `OpenAIBaseClient.ask()`'s loop (meta, local, vllm,
moonshot, nvidia, plus "OpenRouter is not verified"). This task replaces that table, documents
`supports_tool_loop` on the `AbstractClient` page (scope, the three `False` classes, the bridge prerequisite,
the bot warning, no streaming flag), and closes FEAT-843's open item with a pointer. Following this repo's
documentation-task convention, a small pytest file checks the page content so the task has a runnable
validation command.

---

## Scope

- `wiki/clients/abstract-client.md`: add a `### Tool-loop capability (supports_tool_loop)` subsection at the end of `## Public API`; add two Gotchas bullets.
- `wiki/knowledge/pageindex-agentic-retrieval.md`: rewrite the `### Provider support` subsection (`:167-178`).
- `sdd/specs/pageindex-agentic-retrieval.spec.md:939`: append `— Resolved by FEAT-848 (client-tool-loop-capability)`; leave the checkbox as it is.
- Create `packages/ai-parrot/tests/clients/test_tool_loop_docs.py` asserting AC-6.

**NOT in scope**:
- Rewriting FEAT-843's spec §6 (historical) or any other page.
- Code changes of any kind.
- Documenting streaming tool loops beyond "no flag; Groq/Grok/Meta gaps are tracked defects".

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/clients/abstract-client.md` | MODIFY | `supports_tool_loop` subsection + two Gotchas |
| `wiki/knowledge/pageindex-agentic-retrieval.md` | MODIFY | corrected provider table, fail-fast and `no_tool_calls` semantics |
| `sdd/specs/pageindex-agentic-retrieval.spec.md` | MODIFY | one-line resolution pointer on the open item |
| `packages/ai-parrot/tests/clients/test_tool_loop_docs.py` | CREATE | content checks for both pages (AC-6) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev @ d8832d3fc8` (2026-11-09). Names below are created by TASK-5379/5380/5381 — confirm
> them in the worktree before writing (they are the strings the pages must quote).

### Verified Imports
```python
from pathlib import Path   # stdlib — the docs test reads the pages from the repo root: Path(__file__).resolve().parents[4]
```

### Existing Signatures to Use
```python
# Symbols the pages document (exact spelling):
#   AbstractClient.supports_tool_loop: bool = True                         (TASK-5379, base.py)
#   TransformersClient / JevClient / GeminiLiveClient: supports_tool_loop = False   (TASK-5379)
#   provider keys: hf, transformers (TransformersClient); jev, typesafe (JevClient); gemini-live (GeminiLiveClient)
#   parrot.knowledge.pageindex.agentic.require_tool_loop(client) -> None   (TASK-5380)
#   error: "agentic retrieval requires a client that executes tool calls inside ask(); <Class> (<client_type>) declares supports_tool_loop=False"
#   AbstractBot._warn_if_client_lacks_tool_loop() — one warning per real configure() run, never raises   (TASK-5381)
#   OpenAICodexClient / ClaudeAgentClient: True through CodexToolBridge / ClaudeAgentToolBridge; inline ask(tools=...) ignored,
#     only tools registered in client.tool_manager are exposed
#   ask_stream(): no capability flag; ledger issues 3e76568cae48 (Groq), 2d16e4d75557 (Grok), 3a0ea22ce45a (Meta Responses)

# wiki/clients/abstract-client.md (257 lines)
## Public API                                     # :58  (subsections: The abstract surface :69, Concrete helpers :115, History handling :124)
## Configuration & Parameters                     # :132 (1 occurrence) — insert the new subsection right above it
## Gotchas                                        # :231
- **Never modify `parrot/clients/base.py` casually.** It is the foundation of every provider.   # :250 (1 occurrence) — last bullet
## Related                                        # :252

# wiki/knowledge/pageindex-agentic-retrieval.md (248 lines)
### Provider support                              # :167 (1 occurrence) — subsection body :168-178
| anthropic, google, openai (via ... | hf, meta, local, vllm, moonshot, nvidia, jev |   # :173 (the wrong row)
OpenRouter is not in the verified table, ...      # :175
### Ledger versus cursors                         # :180 (1 occurrence) — next subsection, keep it

# sdd/specs/pageindex-agentic-retrieval.spec.md
- [ ] Should `AbstractClient` gain a capability flag (e.g. `supports_tool_loop`) so callers can fail fast on ... out of this slice.   # :939 (1 occurrence)
```

### Does NOT Exist
- ~~meta / local / vllm / moonshot / nvidia / openrouter without a tool loop~~ — all inherit `OpenAIBaseClient.ask()` (`openai_base.py:995`); never repeat FEAT-843 §6's list.
- ~~a streaming capability flag~~ (`supports_stream_tool_loop`) — not added; do not document one.
- ~~`StopReason` `"unsupported_client"`~~ — the fail-fast path raises `ValueError`.
- ~~`wiki/bots/...` page changes~~ — spec §10 lists exactly two pages.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/clients/abstract-client.md", "action": "MODIFY"},
    {"path": "wiki/knowledge/pageindex-agentic-retrieval.md", "action": "MODIFY"},
    {"path": "sdd/specs/pageindex-agentic-retrieval.spec.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/clients/test_tool_loop_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Keep each page's frontmatter and section order; edit only the anchored regions.
- State the scope plainly: the flag covers text `ask()` only — no streaming guarantee, no inline `tools=` guarantee.
- `no_tool_calls` stays meaningful: it is now reserved for a capable client whose model made no call.
- Run `parrot sdd techwiki check --spec sdd/specs/client-tool-loop-capability.spec.md --root .` (never blocking; it must report the two pages ok).

---

## Implementation Blueprint

### Steps (in order)
1. Confirm in the worktree the names and error text listed above — *why*: the pages quote them verbatim.
2. Rewrite `### Provider support` in the agentic-retrieval page — *why*: AC-6, it is the only user-facing place with the wrong list.
3. Add the subsection and Gotchas to `abstract-client.md` — *why*: G5, spec M4 content contract.
4. Append the pointer to FEAT-843's open item — *why*: closes the escalated question without rewriting a historical spec.
5. Create the docs test and run it plus `techwiki check` — *why*: AC-6 needs a runnable check.

### `wiki/knowledge/pageindex-agentic-retrieval.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '### Provider support' wiki/knowledge/pageindex-agentic-retrieval.md) -->
<!-- REPLACE the body between `### Provider support` (:167) and `### Ledger versus cursors` (:180) with: -->
### Provider support

The loop needs a client whose text `ask()` executes tool calls. Clients declare it with the class attribute
`AbstractClient.supports_tool_loop` (text `ask()` only — it makes no claim about `ask_stream()` or about inline
`ask(tools=...)` registration).

| Text `ask()` runs the tool loop | Declares `supports_tool_loop = False` |
|---|---|
| every installed provider, except the three on the right; `OpenAICodexClient` and `ClaudeAgentClient` run it through their agent bridges, using tools registered in `client.tool_manager` | `hf` / `transformers` (`TransformersClient`), `jev` / `typesafe` (`JevClient`), `gemini-live` (`GeminiLiveClient`) |

<!-- FILL IN: one paragraph — agentic_retrieve raises ValueError (quote the message shape) before candidate search
     on a False client; stopped="no_tool_calls" now only means a capable client whose model made no call. -->
```
**Why**: the table and its scope sentence are fixed by spec §3 M4; the remove-OpenRouter rule is satisfied by
replacing the whole body.

### `wiki/clients/abstract-client.md` (MODIFY — 2 edits)
```markdown
<!-- Edit 1 — occurrences: 1 (verified: grep -cF '## Configuration & Parameters' wiki/clients/abstract-client.md) -->
<!-- BEFORE — insert above `## Configuration & Parameters` (:132), as the last subsection of `## Public API`: -->
### Tool-loop capability (`supports_tool_loop`)

<!-- FILL IN: what True promises (text ask() executes enabled, registered tools and feeds results back before
     returning, in-process or through an agent bridge, within existing loop limits); declarative — ask() never
     reads it; the three False classes; Codex/Claude bridges expose only tools registered in client.tool_manager
     (inline tools= ignored); readers: PageIndex agentic retrieval fails fast, AbstractBot.configure() warns. -->

<!-- Edit 2 — occurrences: 1 (verified: grep -cF '- **Never modify `parrot/clients/base.py` casually.**' wiki/clients/abstract-client.md) -->
<!-- AFTER — insert below that bullet (:250), before `## Related`: -->
- **A `supports_tool_loop = False` client ignores offered tools.** <!-- FILL IN: TransformersClient logs nothing when
  tools arrive through tool_manager; check the flag first; an agent-mode AbstractBot logs one warning at configure()
  and never refuses the client. -->
- **There is no streaming capability flag.** <!-- FILL IN: ask_stream() may skip the tool loop ask() runs — Groq,
  Grok and Meta's Responses path today, tracked as ledger issues 3e76568cae48, 2d16e4d75557, 3a0ea22ce45a. -->
```
**Why**: spec §3 M4 content contract; keep bullets in the page's existing bold-lead style.

### `sdd/specs/pageindex-agentic-retrieval.spec.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '- [ ] Should `AbstractClient` gain a capability flag' sdd/specs/pageindex-agentic-retrieval.spec.md) -->
<!-- APPEND to the end of line :939 (keep "- [ ]" unchanged — historical document): -->
 — Resolved by FEAT-848 (client-tool-loop-capability)
```

### `packages/ai-parrot/tests/clients/test_tool_loop_docs.py` (CREATE)
```python
"""FEAT-848 AC-6 — the tool-loop documentation says the right thing."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AGENTIC = ROOT / "wiki" / "knowledge" / "pageindex-agentic-retrieval.md"
CLIENT = ROOT / "wiki" / "clients" / "abstract-client.md"


def _section(text: str, heading: str) -> str:
    """Body of a markdown section, up to the next heading of the same or higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(heading) + len(heading)
    ends = [i for i in (text.find("\n" + "#" * n + " ", start) for n in range(1, len(level) + 1)) if i != -1]
    return text[start : min(ends)] if ends else text[start:]


def test_agentic_provider_table_is_corrected() -> None:
    """No inherited-loop provider is listed as unsupported; the three False classes are."""
    body = _section(AGENTIC.read_text(encoding="utf-8"), "### Provider support")
    # FILL IN: assert "supports_tool_loop" in body; "OpenRouter is not in the verified table" not in body;
    #   for name in ("TransformersClient", "JevClient", "GeminiLiveClient"): assert name in body;
    #   assert "hf, meta, local, vllm, moonshot, nvidia, jev" not in body; "ValueError" and "no_tool_calls" in body — bounded by AC-6


def test_abstract_client_documents_the_flag() -> None:
    """The client page documents scope, bridges, the bot warning and the absence of a streaming flag."""
    text = CLIENT.read_text(encoding="utf-8")
    # FILL IN: assert "### Tool-loop capability" in text; "supports_tool_loop" in _section(text, "## Gotchas");
    #   "tool_manager" and "configure()" and "ask_stream" appear in the new subsection or Gotchas — bounded by AC-6
```
**Why**: `parents[4]` is the repo root (`clients` → `tests` → `ai-parrot` → `packages` → root). Assert on stable
phrases the blueprint fixes, not on whole paragraphs.

### FILL IN checklist
- [ ] agentic page: fail-fast + `no_tool_calls` paragraph — bounded by spec §3 M4
- [ ] abstract-client subsection + two Gotchas bodies — bounded by spec §3 M4 / AC-6
- [ ] two docs tests — bounded by AC-6

---

## Acceptance Criteria

- [ ] `wiki/knowledge/pageindex-agentic-retrieval.md` no longer lists meta, local, vllm, moonshot, nvidia or openrouter as unsupported; both pages document the ask-only scope and both bridges' manager-registration prerequisite (spec AC-6).
- [ ] `abstract-client.md` documents the attribute, the bot warning and that no streaming flag exists.
- [ ] `parrot sdd techwiki check --spec sdd/specs/client-tool-loop-capability.spec.md --root .` reports both pages ok (spec AC-6).
- [ ] FEAT-843's open item carries the FEAT-848 pointer; its checkbox is unchanged.
- [ ] The Validation Command passes.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/clients/test_tool_loop_docs.py -q`

---

## Test Specification

See the CREATE block above: two content tests over the two wiki pages.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug client-tool-loop-capability --feature-id FEAT-848`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/client-tool-loop-capability.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/client-tool-loop-capability.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5383 client-tool-loop-capability verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Seat: minimax (nova). documentation: wiki pages, spec note, test_tool_loop_docs.py. Merge-tier validation green.

**Completed by**: sdd-worker
**Date**: 2026-11-09
**Notes**: documentation: wiki pages, spec note, test_tool_loop_docs.py

**Deviations from spec**: none
