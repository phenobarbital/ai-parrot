---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Portable wikitoolkit config paths (.mcp.json & .claude/settings.json)

**Date**: 2026-09-01
**Author**: Arturo Martinez
**Status**: exploration
**Recommended Option**: B (revised 2026-09-01 after empirical verification — the original Option A recommendation was **disproven**; see "Verification Results")

---

## Problem Statement

Two tracked, committed config files carry a **machine-specific absolute path** to
the `wikitoolkit` executable inside each developer's `.venv`:

- `.mcp.json` → `mcpServers.wikitoolkit.command`
- `.claude/settings.json` → a `PreToolUse` hook command

Because the path is absolute (`/home/<user>/.../ai-parrot/.venv/bin/wikitoolkit`),
every developer whose checkout lives at a different path must hand-edit the file to
point at their own home directory. Arturo and Jesus Lara keep **overwriting each
other's path** on every pull/commit, and the working tree is dirty by default.

This is not a one-off — the git history shows it has been "fixed" and **regressed
three times**:

| Commit | Date | Author | What it did |
|---|---|---|---|
| `e3aea087c` | Aug 6 | Jesus | bare `wikitoolkit` → **hardcoded** `/home/jesuslara/...` (broke everyone else) |
| `ecb2cd05e` | Aug 18 | Javier León | hardcoded → `${CLAUDE_PROJECT_DIR}/.venv/bin/wikitoolkit` (portable attempt, **no default**) |
| `856faec5a` | Aug 28 | Jesus | Found bare `${CLAUDE_PROJECT_DIR}` was **passed to posix_spawn verbatim → ENOENT**; replaced with an `sh -c` spawn-time resolver |
| `cc6695747` | Aug 31 | Jesus | "sdd infra for Codex" — **silently reverted** the `sh -c` fix back to a hardcoded path |

So the churn has **two root causes**, not one:
1. The path is not parametrized in a form that reliably expands.
2. The correct fix keeps getting **clobbered by unrelated commits and by a `dev`
   merge** — the current `settings.json` even contains a **duplicate** wiki hook
   (one portable copy + one hardcoded copy from a merge that kept both sides).

**Who is affected**: every developer on the team (Arturo, Jesus, Javier, and any
new hire) plus every Claude Code / `sdd-worker` session, which fails its wiki
PreToolUse hook and MCP server startup on a foreign checkout.

## Constraints & Requirements

- **Both files must stay committed and shared** (the user's explicit requirement —
  no gitignoring `.mcp.json`).
- The parametrized form must resolve to the repo root **on each machine** with no
  per-developer hand-editing.
- **`.claude/settings.json` hooks** already support `$CLAUDE_PROJECT_DIR` (proven —
  two hooks in the file use it today and Javier's `ecb2cd05e` relied on it). The
  hook side is settled; the only open technical question is `.mcp.json`.
- **`.mcp.json` expansion is version-sensitive.** Empirically (Aug 28, this repo)
  the **bare** `${CLAUDE_PROJECT_DIR}` form did **not** expand and failed with
  ENOENT. Current docs (checked 2026-09-01) say `.mcp.json` expands `${VAR}` and
  `${VAR:-default}`, and that `CLAUDE_PROJECT_DIR` there **requires the default
  form** `${CLAUDE_PROJECT_DIR:-.}`. This must be **empirically verified** on the
  team's current Claude Code (2.1.258) before committing to it.
- The wikitoolkit MCP server must be launched with the **repo root as cwd** — when
  launched from a foreign cwd it writes DEBUG logging to stdout and corrupts the
  JSON-RPC stream (documented in `856faec5a`). Any `.mcp.json` approach must
  preserve this property.
- Scope is deliberately **minimal**: fix the paths + remove the duplicate hook. No
  CI check, no CLAUDE.md guard note (user decision — "just fix the files").

---

## Options Explored

### Option A: Clean `${CLAUDE_PROJECT_DIR:-.}` expansion (verify-first) + remove duplicate hook — ❌ REJECTED after verification

Use Claude Code's own documented variable expansion in both files:

- `.mcp.json` → `"command": "${CLAUDE_PROJECT_DIR:-.}/.venv/bin/wikitoolkit"`,
  `"args": ["mcp"]`, `"type": "stdio"`.
- `.claude/settings.json` → keep the existing `"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit"`
  hook (line 9) and **delete** the duplicate hardcoded copy (lines 24–33).

Because the **bare** `${CLAUDE_PROJECT_DIR}` form provably failed here before, the
recommendation is **verify the `:-.` default form actually starts the server on the
current Claude Code version first**, then commit it. If verification fails, fall
back to Option B.

Note: `${CLAUDE_PROJECT_DIR:-.}` resolves cwd-relatively when the variable is unset
(the `.` default). Verification must confirm the server both **starts** and gets a
usable cwd; if cwd correctness is in doubt, Option B is the safer resolver.

✅ **Pros:**
- Simplest, self-documenting single-line change — no shell wrapper to read.
- Uses the officially documented mechanism; forward-compatible.
- The `:-.` default is exactly what current docs say the bare form was missing —
  plausibly the true fix for the Aug 28 ENOENT.
- Removing the duplicate hook also stops the wiki hook firing **twice** per tool call.

❌ **Cons:**
- Contradicts in-repo empirical evidence unless re-verified — MUST test before trust.
- The `.` fallback does not itself guarantee correct cwd for the stdout-corruption
  issue if `CLAUDE_PROJECT_DIR` is ever unset; needs a verification check.
- Does not handle the worktree-with-no-own-`.venv` case that Option B's resolver does.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Claude Code var expansion | `${CLAUDE_PROJECT_DIR:-.}` in `.mcp.json` | Documented current behavior; verify on v2.1.258 |
| `$CLAUDE_PROJECT_DIR` (hooks) | settings.json hook path | Already proven-working in this file |

🔗 **Existing Code to Reuse:**
- `.claude/settings.json:9` — the already-correct portable hook form to keep.
- `ecb2cd05e` diff — the exact clean form (add the `:-.` default it lacked).

---

### Option B: Restore the proven `sh -c` spawn-time resolver (856faec5a) — ✅ RECOMMENDED (confirmed by verification)

Re-apply Jesus's battle-tested `.mcp.json` wrapper verbatim, and apply the same
duplicate-hook removal to `settings.json`:

```
"command": "sh",
"args": ["-c", "r=\"$CLAUDE_PROJECT_DIR\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(git rev-parse --show-toplevel 2>/dev/null)\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(cd \"$(git rev-parse --git-common-dir 2>/dev/null)/..\" 2>/dev/null && pwd)\"; cd \"$r\" && exec \"$r/.venv/bin/wikitoolkit\" mcp"]
```

✅ **Pros:**
- **Empirically proven in THIS repo** (verified with a real `initialize` handshake
  from repo root, a subdirectory, and `/`).
- **Version-independent** — does not depend on Claude Code expanding any variable.
- Handles the extra cases: worktree with no own `.venv` (falls back to the main
  repo via `git rev-parse --git-common-dir`), and forces correct cwd (`cd "$r"`)
  so DEBUG logging never corrupts the JSON-RPC stream.

❌ **Cons:**
- Verbose, hard-to-read one-liner; the very illegibility that made it easy to
  clobber in `cc6695747`.
- Shell-form command; slightly more moving parts than a plain path.
- "Restores something already reverted" — needs care that a future merge/`sdd`
  commit doesn't clobber it again (but user opted out of a CI guard).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| POSIX `sh`, `git rev-parse` | spawn-time repo-root resolution | Present on every dev machine |

🔗 **Existing Code to Reuse:**
- `856faec5a` — restore its `.mcp.json` diff verbatim.

---

### Option C: Custom exported env var (e.g. `$AI_PARROT_VENV`) + README

Each developer exports one variable in their shell profile
(`export AI_PARROT_VENV="$HOME/.../ai-parrot/.venv"`), and both files reference
`${AI_PARROT_VENV}/bin/wikitoolkit` (settings.json hook) / `${AI_PARROT_VENV:-...}`
(.mcp.json). This is the literal reading of the user's phrase "leave the path in
our envs".

✅ **Pros:**
- Fully explicit; each dev controls their own path once.
- Decouples from any Claude-Code-specific expansion quirk.

❌ **Cons:**
- **Adds an onboarding step** — every dev must export the var or both files silently
  break; new hires hit the same wall.
- Requires a README/doc note to be discoverable — but user chose **minimal scope,
  no docs**, so this option is effectively out of scope.
- Reinvents `$CLAUDE_PROJECT_DIR`, which already exists and needs zero setup.

📊 **Effort:** Medium (env setup + onboarding doc)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| shell profile (`.zshrc`/`.bashrc`) | export `AI_PARROT_VENV` | per-developer, one-time |

🔗 **Existing Code to Reuse:**
- None — new convention.

---

## Recommendation

**Option B** is recommended. (The brainstorm originally recommended Option A,
"verify-then-prefer `${CLAUDE_PROJECT_DIR:-.}`"; the verification below **disproved
it**, so the recommendation is revised.)

Reasoning (grounded in the Verification Results):
- Empirically, on Claude Code 2.1.258, `${CLAUDE_PROJECT_DIR}` is **not expanded**
  in `.mcp.json` and `${CLAUDE_PROJECT_DIR:-.}` collapses to the literal default
  **`.`** — a cwd-relative path. So the "clean" Option A form is really
  `./.venv/bin/wikitoolkit`: it works only when the session is launched from the
  repo root and **breaks from any subdirectory and in worktrees without their own
  `.venv`**. It adds no value over a bare relative path and does not deliver the
  machine-independence the feature requires.
- **Option B** (`sh -c` + `git rev-parse`) is the only approach that resolves the
  **true repo root regardless of launch cwd**, handles **worktrees without a venv**
  (via `git rev-parse --git-common-dir/..`), forces correct cwd (`cd "$r"`) to
  avoid DEBUG-log stdout corruption of the JSON-RPC stream, and is **version-
  independent** (relies on no Claude Code variable expansion). It is already proven
  in this exact repo (commit `856faec5a`) — this feature essentially **restores a
  fix that `cc6695747` reverted**.
- `.claude/settings.json` is unaffected by this reversal: its **hook** commands use
  shell form where `$CLAUDE_PROJECT_DIR` **does** expand to the repo root (proven —
  the wiki hook fires correctly today). So the settings.json fix stays: keep the
  portable hook, delete the duplicate. Only `.mcp.json` needs the Option B resolver.

What we're trading off: Option B is a verbose, hard-to-read one-liner (the very
illegibility that let `cc6695747` clobber it). We accept that for correctness. The
residual risk — a future merge/`sdd` commit reverting it a 4th time — is a
recurrence-guard concern the team deferred out of scope (see Open Questions).

---

## Verification Results (2026-09-01, Claude Code 2.1.258)

The Option-A "verify-then-prefer `${CLAUDE_PROJECT_DIR:-.}`" hypothesis was tested
empirically in isolation (never touching the live `.mcp.json`). Several tests, plus
the production git history, all agree.

**Method**: isolated MCP configs pointing at a probe/introspection command, launched
with real headless sessions (`claude -p … --dangerously-skip-permissions`), both via
`--mcp-config --strict-mcp-config` and via a genuine project-scoped `.mcp.json`
auto-approved with `enableAllProjectMcpServers: true`. The introspection command
logged the *literal expanded value* of each form, plus the server's cwd and injected
`CLAUDE_PROJECT_DIR`.

**Findings** (identical across `--mcp-config` and project-scoped `.mcp.json`, and
from both repo-root and subdirectory launches):

| Form in `.mcp.json` | Expanded to | Result |
|---|---|---|
| `${CLAUDE_PROJECT_DIR}` (bare) | `${CLAUDE_PROJECT_DIR}` **verbatim** | ENOENT — server never spawns. **Reproduces the Aug-28 bug (`856faec5a`) exactly.** |
| `${CLAUDE_PROJECT_DIR:-.}` (default) | `.` (the literal default) | Spawns **only** when cwd is the repo root; a cwd-relative path. |
| `env` value `${CLAUDE_PROJECT_DIR:-.}` | `.` | Same — env fields are not special-cased. |

Additional observed facts:
- The stdio MCP server's **cwd = the directory Claude was launched from**, not the
  git root. From `repo/sub/deeper`, cwd was `repo/sub/deeper`.
- The `CLAUDE_PROJECT_DIR` injected into the server's environment (headless `-p`)
  was likewise the **launch directory**, not the git root. (Hooks differ — see below.)

**Conclusions**:
1. `${CLAUDE_PROJECT_DIR}` is **not expanded** in the `.mcp.json` `command`/`args`/
   `env` fields on this version. Only the literal `:-default` text survives.
2. `${CLAUDE_PROJECT_DIR:-.}/.venv/bin/wikitoolkit` is therefore effectively
   `./.venv/bin/wikitoolkit` — **cwd-relative, not repo-root-anchored**. It breaks
   from subdirectories and in worktrees without their own `.venv`.
3. The current Claude Code docs' claim (relayed via the reviewer) that
   `${CLAUDE_PROJECT_DIR:-.}` yields the project root in `.mcp.json` **did not hold**
   on 2.1.258. Per CLAUDE.md, verified evidence overrides the doc claim → **Option A
   rejected, Option B adopted.**
4. `.claude/settings.json` **hooks** are unaffected: they are shell-form commands
   where `$CLAUDE_PROJECT_DIR` **does** expand to the repo root (independently proven
   — the repo's wiki PreToolUse hook works today). No change needed there beyond
   removing the duplicate.

**Reproducer artifacts** (scratchpad, not committed):
`scratchpad/mcpexp/`, `scratchpad/mcpgit/`, `scratchpad/mcpproj/` — probe server,
introspection script, and the isolated MCP configs.

---

## Feature Description

### User-Facing Behavior
After this change, a developer clones/pulls the repo and Claude Code "just works"
on their machine with **no hand-editing** of `.mcp.json` or `.claude/settings.json`:
- The `wikitoolkit` MCP server starts from whatever path their checkout lives at.
- The wiki PreToolUse hook fires (exactly **once**, not twice) with the correct path.
- `git status` is clean after a pull — no more path collisions between Arturo and
  Jesus, and no more "No existe el fichero o el directorio" on a fresh checkout.

### Internal Behavior
1. `.mcp.json` `mcpServers.wikitoolkit` becomes the **Option B `sh -c` resolver**
   (`command: "sh"`, `args: ["-c", "…git rev-parse… cd \"$r\" && exec …"]`) — it
   locates the true repo root at spawn time regardless of launch cwd, falls back to
   the main repo for a venv-less worktree, and `cd`s there before exec. (Option A's
   `${CLAUDE_PROJECT_DIR:-.}` form was empirically rejected — see Verification
   Results.)
2. `.claude/settings.json` keeps the single portable hook
   (`"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit" claude-hook`) and **deletes** the
   duplicate hardcoded `Grep|Glob|Read|Bash` wiki hook (current lines 24–33),
   ending the double-firing.
3. Both files are committed on `dev` in one focused commit that touches **only**
   these two files.

### Edge Cases & Error Handling
- **`CLAUDE_PROJECT_DIR` unset** (user/global MCP scope): the `:-.` default keeps
  the command syntactically valid; verification must confirm behavior from the repo
  root where sessions actually start.
- **Worktree with no own `.venv`**: Option A resolves to the worktree root, which
  may lack `.venv/bin/wikitoolkit`. This is the one case Option B handles better —
  note it in the spec; if the team runs `sdd-worker` in worktrees without a venv,
  prefer Option B.
- **cwd / stdout corruption**: verification must assert the JSON-RPC `initialize`
  handshake succeeds (no DEBUG-log stream corruption) from at least the repo root.
- **Future merge re-clobbering**: out of scope per the minimal-scope decision, but
  called out as a known residual risk (see Open Questions).

---

## Capabilities

### New Capabilities
- `portable-wikitoolkit-config-paths`: parametrize the wikitoolkit executable path
  in `.mcp.json` and `.claude/settings.json` so both files are committable and
  machine-independent, and remove the duplicate wiki hook.

### Modified Capabilities
- None (no existing spec covers these config files).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `.mcp.json` | modifies | `wikitoolkit` → Option B `sh -c` + `git rev-parse` resolver (restores `856faec5a`) |
| `.claude/settings.json` | modifies | keep portable hook, delete duplicate hardcoded hook (lines 24–33) |
| wikitoolkit MCP server startup | depends on | must still spawn with repo root reachable and correct cwd |
| wiki PreToolUse hook | fixes | stops firing twice per Grep/Glob/Read/Bash call |
| Every dev checkout / `sdd-worker` session | fixes | no hand-editing; clean `git status` after pull |

**No breaking changes** to application code. No new dependencies. Config-only.

---

## Code Context

### User-Provided Code
```text
# Source: user-provided (the two files named in the request)
/home/thephoenixbird/TROC/projects/ai-parrot/.claude/settings.json
/home/thephoenixbird/TROC/projects/ai-parrot/.mcp.json
```

### Verified Codebase References

#### Current `.mcp.json` (HEAD, hardcoded — the thing to fix)
```json
// .mcp.json:1-11  (working tree has /home/thephoenixbird/... ; HEAD has /home/jesuslara/...)
{
  "mcpServers": {
    "wikitoolkit": {
      "command": "/home/jesuslara/proyectos/ai-parrot/.venv/bin/wikitoolkit",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

#### Current `.claude/settings.json` — the portable hook to KEEP
```json
// .claude/settings.json:5-13  (PreToolUse, Grep|Glob|Read|Bash) — ALREADY portable
{
  "matcher": "Grep|Glob|Read|Bash",
  "hooks": [
    { "type": "command",
      "command": "\"$CLAUDE_PROJECT_DIR/.venv/bin/wikitoolkit\" claude-hook",
      "timeout": 10 }
  ]
}
```

#### Current `.claude/settings.json` — the DUPLICATE hook to DELETE
```json
// .claude/settings.json:24-33  (second Grep|Glob|Read|Bash matcher, hardcoded) — REMOVE
{
  "matcher": "Grep|Glob|Read|Bash",
  "hooks": [
    { "type": "command",
      "command": "/home/thephoenixbird/TROC/projects/ai-parrot/.venv/bin/wikitoolkit claude-hook",
      "timeout": 10 }
  ]
}
```

#### Proven fallback: the `sh -c` resolver (from commit 856faec5a)
```text
"command": "sh",
"args": ["-c", "r=\"$CLAUDE_PROJECT_DIR\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(git rev-parse --show-toplevel 2>/dev/null)\"; [ -x \"$r/.venv/bin/wikitoolkit\" ] || r=\"$(cd \"$(git rev-parse --git-common-dir 2>/dev/null)/..\" 2>/dev/null && pwd)\"; cd \"$r\" && exec \"$r/.venv/bin/wikitoolkit\" mcp"]
```

#### Verified facts
- Claude Code version on this machine: **2.1.258** (`claude --version`, 2026-09-01).
- `.venv/bin/wikitoolkit` exists and is executable at the repo root.
- `$CLAUDE_PROJECT_DIR` expansion **works** in `.claude/settings.json` hook commands
  (in active use at `.claude/settings.json:9`).

### Does NOT Exist (Anti-Hallucination)
- ~~Any current CI check or pre-commit hook guarding these paths~~ — none exists;
  out of scope by decision.
- ~~A custom `$AI_PARROT_VENV` (or similar) env var convention~~ — does not exist
  today (Option C only).
- ~~Any expansion of `${CLAUDE_PROJECT_DIR}` in `.mcp.json` `command`/`args`/`env`~~
  — **verified NOT to happen** on 2.1.258 (bare form passed verbatim; `:-.` yields
  literal `.`). Confirmed by `856faec5a` and by the 2026-09-01 Verification Results.
  Do NOT reintroduce a `${CLAUDE_PROJECT_DIR}`-based `.mcp.json` command.

---

## Parallelism Assessment

- **Internal parallelism**: None. Two small edits to two files in one commit; a
  single verification step gates the `.mcp.json` form choice. Sequential.
- **Cross-feature independence**: `.mcp.json` and `.claude/settings.json` are
  repo-wide config touched by many branches/merges (this is *why* the churn
  happens). Any in-flight branch that also edits these files will conflict — land
  this fix quickly and rebase others onto it.
- **Recommended isolation**: `per-spec` (single worktree, one commit). A worktree
  is arguably overkill (single-commit config change per CLAUDE.md's "When NOT to
  Use Worktrees"), but per-spec keeps it consistent with the SDD flow.
- **Rationale**: Trivial surface area, no independent sub-tasks, high merge-conflict
  sensitivity → do it in one focused commit and merge to `dev` fast.

---

## Open Questions
- [x] Does `${CLAUDE_PROJECT_DIR:-.}` expand correctly in `.mcp.json` on Claude Code 2.1.258? — *Owner: Arturo*: **No — verified 2026-09-01.** `${CLAUDE_PROJECT_DIR}` is not expanded (verbatim → ENOENT); `${CLAUDE_PROJECT_DIR:-.}` collapses to `.` (cwd-relative), breaking from subdirs/worktrees. Recommendation flipped to **Option B** (`sh -c` + `git rev-parse`). See Verification Results.
- [x] Custom env var vs. `$CLAUDE_PROJECT_DIR`? — *Owner: Arturo*: Use `$CLAUDE_PROJECT_DIR` (no per-dev setup); custom env var (Option C) rejected as it needs onboarding docs that minimal scope excludes.
- [x] Keep or remove the duplicate settings.json hook? — *Owner: Arturo*: Remove (lines 24–33); it also stops the wiki hook firing twice.
- [ ] Should a recurrence guard (CI check / CLAUDE.md note) be added later to stop merges/`sdd` commits from clobbering the fix a 4th time? — *Owner: Arturo*: Deferred — out of scope now ("just fix the files"), but the history shows the fix was reverted by `cc6695747`, so it may be worth a follow-up.
