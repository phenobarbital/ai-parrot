# TASK-5494: Documentation — agent as a local MCP server

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5489, TASK-5491, TASK-5493
**Assigned-to**: unassigned

---

## Context

The spec's `docs.policy` is `required` (§10): a new page `wiki/mcp/agent-local-mcp.md`, an
"Exposing an agent" section in `wiki/tools/mcp-local-toolkits.md`, and a one-line pointer in
`wiki/mcp/mcp-server-and-client.md`. This task implements spec §3 **Module 7**. It runs last
because it documents shipped behaviour (error messages, CLI output) from TASK-5489, TASK-5491
and TASK-5493. Its runnable check is a pytest content test appended to a test file already in
the spec's Validation Contract (`parrot sdd techwiki check` is not a registered test runner, so
it is an acceptance criterion, not a Validation Command).

---

## Scope

- Create `wiki/mcp/agent-local-mcp.md` from `sdd/templates/techwiki-page.md` (frontmatter
  `title` + `summary`; sections Purpose, Public API, Configuration & Parameters, Usage
  Examples, Gotchas, Related). Cover:
  - declaring: YAML top-level `mcp_local:` (`true` or `{allow: [...]}`) and
    `@register_agent(name=..., mcp_local=...)`;
  - the own-class rule with a worked MRO example (framework classes, mixins, an author's
    intermediate base, an own override of `configure`);
  - `allow`; why `ask`/`ask_stream` are never exposed (FEAT-477 parity);
  - `parrot toolkits list --agents`, `install --agent`, `uninstall|enable|disable agent-<slug>`;
  - lazy instantiate + `configure()` on the first call, `shutdown()`/`cleanup()` on stop, one
    shared instance;
  - `@mcp_tool` interplay (name, description, schema, confirmation);
  - `AGENTS_DIR` comes from the environment the host launches `parrot` with;
  - troubleshooting: each `AgentExposureError` message → its fix.
  - Public API links: `ref:parrot.mcp.agent_toolkit.AgentToolkit`,
    `ref:parrot.mcp.agent_toolkit.resolve_exposable_agent`,
    `ref:parrot.mcp.agent_toolkit.list_exposable_agents`.
- Add a short `## Exposing an agent` section to `wiki/tools/mcp-local-toolkits.md` (before
  `## Exposing your own toolkit`) linking the new page.
- Add a one-line pointer to the new page at the end of the "Expose agents" bullet in
  `wiki/mcp/mcp-server-and-client.md`.
- Append `test_agent_local_mcp_docs_cover_contract` to
  `packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py`.

**NOT in scope**: any code change; documenting FEAT-422 agentd or the FEAT-477 HTTP mount
beyond a "Related" link.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/mcp/agent-local-mcp.md` | CREATE | Feature page |
| `wiki/tools/mcp-local-toolkits.md` | MODIFY | "Exposing an agent" section |
| `wiki/mcp/mcp-server-and-client.md` | MODIFY | One-line pointer in the "Expose agents" bullet |
| `packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py` | MODIFY | Docs content test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
from pathlib import Path   # the docs test reads files relative to the repo root:
# packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py → Path(__file__).resolve().parents[4] is the repo root
```

### Existing Signatures to Use
```text
sdd/templates/techwiki-page.md            — 38 lines: frontmatter (title, summary) + Purpose / Public API /
                                            Configuration & Parameters / Usage Examples / Gotchas / Related
wiki/tools/mcp-local-toolkits.md:163      — `## Exposing your own toolkit` (occurrences: 1); frontmatter `title:` at line 2
wiki/mcp/mcp-server-and-client.md:17-18   — `3. **Expose agents** as MCP servers, either one endpoint per agent
                                            (`AgentMCPMount`) or by marking` / `   individual agent methods with `@mcp_tool`.`
                                            (`**Expose agents**` occurrences: 1)
```
Shipped names to document (from TASK-5485..5493 — verify the final strings in the code before writing):
`MCPLocalExposure` (`parrot.registry.registry`), `AgentToolkit`, `AgentExposureError`,
`resolve_exposable_agent`, `list_exposable_agents` (`parrot.mcp.agent_toolkit`),
`install_agent_toolkits`, `agent_inventory` (`parrot.mcp.toolkit_install`),
`agent_section_name` (`parrot.mcp.toolkit_config`).

### Does NOT Exist
- ~~`parrot mcp-serve` for this feature~~ — that is FEAT-422 agentd; FEAT-877 serves through `parrot mcp-local agent-<slug>`.
- ~~`parrot toolkits uninstall --agent`~~ — uninstall takes the section name.
- ~~a `warm` option~~ — deferred (spec §8 Q1); do not document it as available.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/mcp/agent-local-mcp.md", "action": "CREATE"},
    {"path": "wiki/tools/mcp-local-toolkits.md", "action": "MODIFY"},
    {"path": "wiki/mcp/mcp-server-and-client.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Copy error messages and CLI output from the merged code, not from the spec, so the page
  matches what users see.
- Examples must be copy-pasteable (real YAML keys, real command names).
- Keep the toolkits-page section short (≤ 15 lines); the detail lives on the new page.

---

## Implementation Blueprint

### Steps (in order)
1. Read the shipped code (`agent_toolkit.py`, `toolkit_install.py`, `cli/toolkits.py`) for exact messages — *why*: the troubleshooting table must match reality.
2. Create the page from the template — *why*: `parrot sdd techwiki check` validates the structure.
3. Edit the two existing pages — *why*: spec §10 pages.
4. Append the docs test; run the Validation Commands and `parrot sdd techwiki check --spec sdd/specs/agent-local-mcp.spec.md --root .`.

### `wiki/mcp/agent-local-mcp.md` (CREATE)
```markdown
---
title: "Agent as a Local MCP Server (`parrot toolkits install --agent`)"
summary: Serve a registered agent's own async methods as a local stdio MCP server for Claude Code, Codex and Antigravity.
---

# Agent as a Local MCP Server

> **Feature**: FEAT-877 — Agent as a local stdio MCP server
> **Spec**: [sdd/specs/agent-local-mcp.spec.md](https://github.com/phenobarbital/ai-parrot/blob/main/sdd/specs/agent-local-mcp.spec.md)
> **Package**: `ai-parrot` (core) — `parrot.mcp.agent_toolkit`

## Purpose
<!-- FILL IN: what it does, when to use it vs the FEAT-477 HTTP mount and FEAT-422 agentd -->

## Public API
- [`AgentToolkit`](ref:parrot.mcp.agent_toolkit.AgentToolkit) — serves one agent's own async methods as tools
- [`resolve_exposable_agent`](ref:parrot.mcp.agent_toolkit.resolve_exposable_agent) — resolve and validate an agent by name
- [`list_exposable_agents`](ref:parrot.mcp.agent_toolkit.list_exposable_agents) — every declared, exposable agent

## Configuration & Parameters
<!-- FILL IN: mcp_local YAML section and decorator keyword; allow; the own-class rule with a worked MRO example;
     ask/ask_stream never exposed; the generated .parrot/mcp-toolkits.yaml section -->

## Usage Examples
<!-- FILL IN: YAML + Python declaration; `parrot toolkits list --agents`; `install --agent finance`;
     `disable|enable|uninstall agent-finance`; what Claude Code shows -->

## Gotchas
<!-- FILL IN: first-call configure latency; one shared instance (concurrency-safe methods); AGENTS_DIR from the launch
     environment; discovery imports agent modules; troubleshooting table: each AgentExposureError message → fix -->

## Related
- [Expose Toolkits as Local MCP](../tools/mcp-local-toolkits.md) — the `mcp-local` runner this feature reuses
- [MCP server and client](mcp-server-and-client.md) — remote agent exposure (`AgentMCPMount`, `@mcp_tool`)
```

### `wiki/tools/mcp-local-toolkits.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '## Exposing your own toolkit' wiki/tools/mcp-local-toolkits.md → line 163) -->
<!-- BEFORE — insert above `## Exposing your own toolkit`, followed by `---` and a blank line like the other sections -->
## Exposing an agent

<!-- FILL IN: 5-10 lines — declare `mcp_local:` on the agent, `parrot toolkits install --agent <name>`, the generated
     `agent-<slug>` section served by `parrot mcp-local agent-<slug>`; link [Agent as a Local MCP Server](../mcp/agent-local-mcp.md) -->
```

### `wiki/mcp/mcp-server-and-client.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '\*\*Expose agents\*\*' wiki/mcp/mcp-server-and-client.md → line 17) -->
<!-- REPLACE line 18 `   individual agent methods with `@mcp_tool`.` with: -->
   individual agent methods with `@mcp_tool`. To serve an agent locally over stdio instead, see
   [Agent as a Local MCP Server](agent-local-mcp.md).
```

### `packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py` (MODIFY) — append
```python
# AFTER — append at end of file (created by TASK-5493)
REPO_ROOT = Path(__file__).resolve().parents[4]


def test_agent_local_mcp_docs_cover_contract() -> None:
    page = (REPO_ROOT / "wiki" / "mcp" / "agent-local-mcp.md").read_text(encoding="utf-8")
    assert page.startswith("---\ntitle:")
    for phrase in ("mcp_local", "parrot toolkits install --agent", "parrot toolkits list --agents",
                   "ask_stream", "agent-", "not declared for local MCP exposure", "defines no exposable methods"):
        assert phrase in page, phrase
    # FILL IN: mcp-local-toolkits.md contains "## Exposing an agent" and "agent-local-mcp.md";
    #   mcp-server-and-client.md contains "agent-local-mcp.md"
```

### FILL IN checklist
- [ ] every `<!-- FILL IN -->` section of the new page — spec §3 M7, from the shipped code.
- [ ] the toolkits-page section.
- [ ] the docs test's remaining assertions.

---

## Acceptance Criteria

- [ ] `wiki/mcp/agent-local-mcp.md` exists with the template's sections and documents declaring, the own-class rule, `allow`, the `ask` exclusion, CLI commands, lifecycle, `@mcp_tool` and troubleshooting.
- [ ] `wiki/tools/mcp-local-toolkits.md` has an "Exposing an agent" section linking the new page; `mcp-server-and-client.md` points to it.
- [ ] `parrot sdd techwiki check --spec sdd/specs/agent-local-mcp.spec.md --root .` passes (AC-15).
- [ ] `ruff check packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py -q`

---

## Test Specification

`test_agent_local_mcp_docs_cover_contract` (appended above) checks the page's frontmatter,
the key phrases and the two cross-links.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug agent-local-mcp --feature-id FEAT-877`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/agent-local-mcp.json`
4. **Verify the Codebase Contract** before writing code; if anything changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5494 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
