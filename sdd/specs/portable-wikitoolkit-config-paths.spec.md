---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Portable wikitoolkit config paths

**Feature ID**: FEAT-495
**Date**: 2026-09-01
**Author**: Arturo Martinez
**Status**: approved
**Target version**: n/a (config / developer-tooling change)

> Input: `sdd/proposals/portable-wikitoolkit-config-paths.brainstorm.md`.
> **The brainstorm was grounded in `feat-481` and is partially superseded**:
> on `dev`, `.mcp.json` was already made local-only (untracked + gitignored) by
> commit `145db5786` on 2026-09-01. This spec therefore accepts local-only
> `.mcp.json` and does NOT commit a portable `.mcp.json` (brainstorm Option B for a
> *tracked* `.mcp.json` → Non-Goal). The verified expansion facts from the
> brainstorm still hold and drive the `.mcp.json.example` template.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Two Claude Code config files carried machine-specific absolute paths to each
developer's `.venv/bin/wikitoolkit`, so Arturo and Jesus kept overwriting each
other's paths on every pull/commit (dirty working tree by default; broken wiki
hook / MCP server on a fresh checkout). The history shows the fix regressed
multiple times (`e3aea087c` → `ecb2cd05e` → `856faec5a` → `cc6695747`).

Since the brainstorm, the two halves have diverged in state:

- **`.mcp.json`** — **already resolved on `dev`.** Commit `145db5786`
  ("stop tracking .mcp.json — local-only MCP config", 2026-09-01) untracked the
  file; `.gitignore:389` (`.mcp.json`) keeps it local-only per developer. The
  collision is gone. What is missing is a **committable, path-independent starting
  point** so a new checkout can obtain a working `.mcp.json` without hand-editing a
  home path.
- **`.claude/settings.json`** — **still broken on `dev`.** It is tracked and
  contains the lone remaining hardcoded path at line 35
  (`/home/jesuslara/.../wikitoolkit claude-hook`) inside a **duplicate**
  `Grep|Glob|Read|Bash` wiki hook (lines 30–39). The portable copy already exists
  at line 15 (`"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit" claude-hook`), so the
  wiki hook currently fires **twice** per matching tool call and reintroduces a
  machine-specific path on every merge.

### Goals
- Remove the machine-specific path from `.claude/settings.json` and the duplicate
  wiki hook, leaving exactly one portable `$CLAUDE_PROJECT_DIR`-based wiki hook.
- Provide a tracked, path-independent `.mcp.json.example` a developer can copy to
  their local (gitignored) `.mcp.json` and have wikitoolkit work with no editing,
  regardless of where their checkout lives or which subdirectory the session starts
  in.
- Keep `.mcp.json` itself local-only (honor `145db5786`).

### Non-Goals (explicitly out of scope)
- **Re-tracking a committed `.mcp.json`.** Rejected — it would reverse Jesus's
  same-day `145db5786` decision. (Brainstorm Option B targeted a *tracked*
  `.mcp.json`; superseded — see `proposals/portable-wikitoolkit-config-paths.brainstorm.md`.)
- **A `${CLAUDE_PROJECT_DIR}`-based `.mcp.json` command.** Rejected — empirically
  verified NOT to expand on Claude Code 2.1.258 (see §6 / brainstorm Verification
  Results). The `.example` uses the `sh -c` + `git rev-parse` resolver instead.
- **A recurrence guard (CI check / CLAUDE.md note).** Deferred (see §8); the team
  chose "just fix the files".
- **Changing the existing portable hook mechanism** in `settings.json` (line 15) —
  it already works; only the duplicate is removed.

---

## 2. Architectural Design

### Overview

Two independent, config-only changes on `dev`:

1. **`.claude/settings.json` dedup** — delete the duplicate hardcoded
   `Grep|Glob|Read|Bash` wiki-hook object (lines 30–39), keeping the portable one
   at line 15. Net effect: the wiki `claude-hook` fires once, via
   `$CLAUDE_PROJECT_DIR` (which Claude Code *does* expand in shell-form hook
   commands — proven by the working hook today), and no `/home/...` path remains in
   any tracked file.

2. **`.mcp.json.example` (new, tracked)** — a valid-JSON template whose
   `wikitoolkit` server uses the verified `sh -c` spawn-time resolver (brainstorm
   Option B, commit `856faec5a`). A developer runs `cp .mcp.json.example .mcp.json`
   once; the real `.mcp.json` stays gitignored. The resolver locates the true repo
   root via `$CLAUDE_PROJECT_DIR` → `git rev-parse --show-toplevel` →
   `git rev-parse --git-common-dir/..`, `cd`s there (avoiding the DEBUG-log stdout
   corruption of the JSON-RPC stream), then execs `.venv/bin/wikitoolkit mcp`. This
   is cwd-independent and worktree-safe — the two properties the plain
   `${CLAUDE_PROJECT_DIR:-.}` form provably lacks.

### Component Diagram
```
.claude/settings.json (tracked)
  PreToolUse Grep|Glob|Read|Bash
    hook#1  "$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit" claude-hook   ← KEEP
    hook#2  /home/jesuslara/.../wikitoolkit claude-hook               ← DELETE (dup)

.mcp.json.example (tracked, NEW) ──cp──▶ .mcp.json (gitignored, local per dev)
    wikitoolkit → sh -c 'resolve repo root; cd; exec .venv/bin/wikitoolkit mcp'
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/settings.json` PreToolUse hooks | modifies | remove duplicate hook object; keep the `$CLAUDE_PROJECT_DIR` one |
| wikitoolkit PreToolUse hook | fixes | fires once instead of twice per Grep/Glob/Read/Bash |
| `.gitignore:389` (`.mcp.json`) | depends on | unchanged — keeps real `.mcp.json` local; `.mcp.json.example` is a different, tracked path |
| wikitoolkit MCP server (`.venv/bin/wikitoolkit mcp`) | invokes | spawned by the copied `.mcp.json`; resolver guarantees correct binary + cwd |

### Data Models
Not applicable — no code, no Pydantic models. The artifacts are JSON config files.

### New Public Interfaces
Not applicable — no Python API. The one new user-facing artifact is the file
`.mcp.json.example` and the documented one-time step `cp .mcp.json.example .mcp.json`.

---

## 3. Module Breakdown

> Config-only. Two independent changes; either could be its own task.

### Module 1: Deduplicate `.claude/settings.json`
- **Path**: `.claude/settings.json`
- **Responsibility**: Remove the duplicate hardcoded `Grep|Glob|Read|Bash` wiki
  hook object (lines 30–39 on `dev`), leaving exactly one wiki `claude-hook` (the
  `$CLAUDE_PROJECT_DIR` form at line 15). Preserve all other hooks and the
  `permissions` block. Result must remain valid JSON.
- **Depends on**: nothing.

### Module 2: Add tracked `.mcp.json.example`
- **Path**: `.mcp.json.example` (repo root, NEW)
- **Responsibility**: Provide a valid-JSON template with the `sh -c` resolver so a
  developer can `cp .mcp.json.example .mcp.json`. Must NOT contain any `/home/...`
  path. Must be tracked (it is a `.example`, not matched by the `.mcp.json`
  gitignore rule — verify with `git check-ignore`).
- **Depends on**: nothing (independent of Module 1).

---

## 4. Test Specification

> No unit-test framework applies to static JSON config. "Tests" are deterministic
> shell assertions an implementer / reviewer runs.

### Unit Tests (assertions)
| Check | Target | Description |
|---|---|---|
| valid-json-settings | Module 1 | `python -m json.tool .claude/settings.json` exits 0 |
| single-wiki-hook | Module 1 | exactly one `wikitoolkit ... claude-hook` command remains |
| no-home-path | Module 1 | `grep -R "/home/" .claude/settings.json` finds nothing |
| valid-json-example | Module 2 | `python -m json.tool .mcp.json.example` exits 0 |
| example-tracked | Module 2 | `git check-ignore .mcp.json.example` finds nothing (not ignored) |
| example-no-home | Module 2 | `.mcp.json.example` contains no `/home/` path |

### Integration Tests
| Test | Description |
|---|---|
| copy-and-connect (root) | `cp .mcp.json.example .mcp.json`; a Claude Code session started at the repo root connects to `wikitoolkit` (`claude mcp list` / handshake shows Connected) |
| copy-and-connect (subdir) | Same, but session started from a subdirectory — still connects (the property the `${CLAUDE_PROJECT_DIR:-.}` form fails; verified in the brainstorm) |

### Test Data / Fixtures
Not applicable.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `.claude/settings.json` contains **no** `/home/` (or any absolute home) path.
- [ ] `.claude/settings.json` has **exactly one** `Grep|Glob|Read|Bash` wiki
      `claude-hook` (the duplicate object is gone); all other hooks and the
      `permissions` block are unchanged.
- [ ] `.claude/settings.json` is valid JSON (`python -m json.tool` exits 0).
- [ ] `.mcp.json.example` exists at the repo root, is **tracked**
      (`git check-ignore .mcp.json.example` prints nothing), and is valid JSON.
- [ ] `.mcp.json.example` contains **no** `/home/` path and uses the `sh -c`
      `git rev-parse` resolver (not a bare `${CLAUDE_PROJECT_DIR}` command).
- [ ] `.mcp.json` remains **untracked/gitignored** (this change does not re-track
      it; `.gitignore:389` is unchanged).
- [ ] After `cp .mcp.json.example .mcp.json`, the `wikitoolkit` MCP server connects
      when a session is launched **from the repo root** AND **from a subdirectory**.
- [ ] No unrelated files are modified by the implementing commit(s).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All line numbers are on `dev` at
> `ae2c059b3`/`6df450b9b` (verified 2026-09-01 in a `dev` worktree).

### Verified Imports
Not applicable — no Python.

### Existing file signatures (verified on `dev`)

`.claude/settings.json` (tracked) — relevant structure:
```jsonc
// line 2-7:  "permissions": { "allow": ["Bash(ruff:*)", "Bash(touch:*)"] }   ← preserve
// line 11-19: PreToolUse matcher "Grep|Glob|Read|Bash":
//   line 15: "command": "\"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit\" claude-hook"  ← KEEP (portable)
// line 20-28: PreToolUse matcher "Bash|Edit|Write|MultiEdit" → dangerous-actions-blocker.sh  ← preserve
// line 30-39: PreToolUse matcher "Grep|Glob|Read|Bash" (DUPLICATE):
//   line 35: "command": "/home/jesuslara/proyectos/ai-parrot/.venv/bin/wikitoolkit claude-hook"  ← DELETE whole object
// line 41-52: SubagentStop sdd-worker → sdd-worker-format.sh   ← preserve
// line 53-62: Stop → sdd-worker-format.sh                      ← preserve
```

`.gitignore` (verified):
```
# line 388: #MCP Custom Local configs
# line 389: .mcp.json
```

Verified `sh -c` resolver to place in `.mcp.json.example` (from commit `856faec5a`,
retrieved 2026-09-01 via `git show 856faec5a:.mcp.json`):
```json
{
  "mcpServers": {
    "wikitoolkit": {
      "type": "stdio",
      "command": "sh",
      "args": [
        "-c",
        "r=\"$CLAUDE_PROJECT_DIR\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(git rev-parse --show-toplevel 2>/dev/null)\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(cd \"$(git rev-parse --git-common-dir 2>/dev/null)/..\" 2>/dev/null && pwd)\"; cd \"$r\" && exec \"$r/.venv/bin/wikitoolkit\" mcp"
      ],
      "env": {}
    }
  }
}
```

### Integration Points
| New/changed artifact | Connects To | Via | Verified At |
|---|---|---|---|
| deduped `settings.json` hook | wikitoolkit CLI | `"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit" claude-hook` (shell-form hook; `$CLAUDE_PROJECT_DIR` expands) | `.claude/settings.json:15` |
| `.mcp.json.example` → copied `.mcp.json` | `.venv/bin/wikitoolkit mcp` | `sh -c` resolver | `856faec5a:.mcp.json` |

### Does NOT Exist (Anti-Hallucination)
- ~~A tracked `.mcp.json` on `dev`~~ — untracked since `145db5786`; gitignored at
  `.gitignore:389`. Do NOT `git add` `.mcp.json`.
- ~~`.mcp.json.example`~~ — does not exist yet; this feature creates it.
- ~~Expansion of `${CLAUDE_PROJECT_DIR}` (bare or `:-.`) to the repo root in the
  `.mcp.json` `command`/`args`/`env` fields~~ — verified NOT to happen on 2.1.258
  (bare → verbatim ENOENT; `:-.` → literal `.`, cwd-relative). Do NOT use it.
- ~~A CI check / pre-commit hook guarding these paths~~ — none exists (out of scope).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Edit JSON precisely; keep 2-space indentation and existing key order. Re-validate
  with `python -m json.tool` after each edit.
- Touch ONLY `.claude/settings.json` and the new `.mcp.json.example`. Do not stage
  or modify the local `.mcp.json`, `.gitignore`, or anything else.
- The `.mcp.json.example` must be copy-paste-runnable as strict JSON (no JSON
  comments) so `cp .mcp.json.example .mcp.json` yields a file Claude Code parses.

### Known Risks / Gotchas
- **Merge re-introduction.** History shows the portable fix was reverted before
  (`cc6695747`) and a merge left the duplicate hook. Without a guard (deferred, §8),
  a future merge could re-add a hardcoded hook. Mitigation for now: land quickly;
  reviewers watch for `/home/` in `settings.json`.
- **`.mcp.json.example` illegibility.** The `sh -c` one-liner is hard to read — the
  same trait that made `856faec5a` easy to clobber. Keep it verbatim from the
  verified source; do not "tidy" it.
- **`.example` not auto-applied.** New devs must run `cp .mcp.json.example .mcp.json`
  once; until they do, wikitoolkit MCP is absent (the hook still works via
  `$CLAUDE_PROJECT_DIR`). Acceptable — matches the local-only decision.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none) | — | POSIX `sh` + `git` (already required by the repo) are the only runtime needs of the resolver |

---

## 8. Open Questions

- [x] Does `${CLAUDE_PROJECT_DIR:-.}` expand to the repo root in `.mcp.json`? —
      *Resolved in brainstorm (verified 2026-09-01)*: No. Bare form passed verbatim
      (ENOENT); `:-.` collapses to literal `.` (cwd-relative). Use the `sh -c`
      resolver.
- [x] Custom env var vs `$CLAUDE_PROJECT_DIR`? — *Resolved in brainstorm*: Use
      `$CLAUDE_PROJECT_DIR` (settings.json hooks); no per-dev env var.
- [x] Keep or remove the duplicate `settings.json` hook? — *Resolved in brainstorm*:
      Remove it (also stops double-firing).
- [x] Commit `.mcp.json`, or keep it local? — *Resolved this session (dev state +
      user)*: Keep local-only (per `145db5786`); ship a tracked `.mcp.json.example`
      instead.
- [ ] Should a recurrence guard (CI check for `/home/` paths / duplicate hooks, or a
      CLAUDE.md note) be added to stop a future merge re-breaking this? —
      *Owner: Arturo* — deferred, out of scope for FEAT-495.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- Both modules are config-only, independent, and total one or two small commits.
  Per CLAUDE.md "When NOT to Use Worktrees", a worktree is optional here; if used,
  all tasks run sequentially in one worktree.
- **Cross-feature dependencies**: none. High merge-conflict sensitivity on
  `.claude/settings.json` (many branches touch it) → land promptly and have other
  in-flight branches rebase onto it.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | Arturo Martinez | Initial draft. Rescoped from brainstorm after discovering `.mcp.json` is already local-only on `dev` (`145db5786`): accept local-only + add `.mcp.json.example`; sole tracked fix is the `settings.json` duplicate hook. |
