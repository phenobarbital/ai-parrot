<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
FEAT-485 built the generic local-MCP machinery (`parrot mcp-local <name>`,
`.parrot/mcp-toolkits.yaml`, managed `.mcp.json` / `.codex/config.toml` /
`mcp_config.json` reconciliation) and FEAT-556 added packaged **templates**
so a section can be seeded without hand-editing YAML. Three templates ship
today: `bounded-source`, `targeted-writer`, `sdd-coder`.

Two problems remain.

**1. The two database toolkits are invisible.** `QuerysourceToolkit`
(FEAT-558, `parrot_tools.querysource.toolkit`) and `DatabaseQueryToolkit`
(FEAT-105/136, `parrot.tools.databasequery.toolkit`) are exactly the kind of
tool a coding or analysis session wants as a first-class MCP tool — schema
discovery, validated read-only query execution, tenant-scoped query slugs and
MultiQuery pipelines. Neither ships a template, so exposing them means
hand-writing a YAML section from the class signature.

**2. Toolkit selection is a flag buried inside the wrong command.** Today the
only way to choose toolkits is `parrot claude install --toolkits=a,b` or
`--all-toolkits` — a flag on the *wiki* installer. The operator must already
know the template names; `--help` only lists them in a fallback hint after a
no-op run. There is no way to **list** what is available with descriptions,
no way to **disable** one without hand-editing YAML and re-running the host
installer, and no way to **uninstall** one at all.

Compounding this: `scraping`, `browsing` and `memory` are hardcoded as
`BUILTIN_TOOLKITS` (`toolkit_config.py:89`) and resolve implicitly whether or
not the operator wants them. A repo that never asked for browser automation
still has `browsing` resolvable, and `parrot claude install` will happily
write a `parrot-browsing` entry. The owner's decision is that **nothing
except wikitoolkit should be implicit** — every local MCP server becomes
opt-in and individually toggleable.

**Who is affected**: every operator wiring an ai-parrot repo into Claude
Code, Codex, or Google Antigravity — plus the ai-parrot repo itself, whose
`.mcp.json` currently carries `parrot-browsing`, `parrot-memory` and
`parrot-scraping` entries that resolve through the builtins.

### Constraints and goals
- **Full replacement.** `parrot toolkits` becomes the *only* toolkit
  selection surface. `--toolkits=` / `--all-toolkits` are removed from
  `parrot claude|codex|google install` (hard cut — no external consumers, per
  project policy).
- **All three hosts.** Claude Code (`.mcp.json`), Codex
  (`.codex/config.toml`), Google Antigravity (`mcp_config.json`) must all be
  installable/uninstallable targets.
- **No secrets on disk.** The installer must never prompt for, capture, or
  write a DSN or credential. `ToolkitSection.env` values are copied
  **verbatim** into the host entry (`google/assets.py:99`), and `.mcp.json`
  is git-tracked in this repo — so a baked secret would be committed.
- **`BUILTIN_TOOLKITS` is deleted.** `scraping`, `browsing` and `memory`
  become packaged templates like any other; `load_toolkits_config` returns
  only sections actually declared in the file.
- **Hard cut on migration.** No auto-migration of existing installs. Repos
  re-run `parrot toolkits install` and pick what they want.
- **wikitoolkit stays invisible** to this command — it remains owned by
  `parrot claude install` and its siblings.
- Every subcommand needs a non-interactive form (`--yes`, explicit names,
  `--host`) so CI and scripts never block on a picker.
- Lean startup preserved: listing templates must not import any toolkit
  class (the existing `--list` contract, `local_cli.py:35`).

---

### Recommended option / probable scope
**Option A** is recommended.

The honest framing of this feature is that **~85% of it already exists**.
FEAT-485 built the runner and the three host reconcilers; FEAT-556 built
packaged templates, seeding, and drift reporting. What is missing is a
front door (a picker and a `list`), two templates, and the removal of an
implicit-defaults mechanism that predates the template system and now
contradicts it. Option A is the option scoped to exactly that.

The tradeoff against **Option C** is deliberate: C's plan/apply model is
genuinely better *if* toolkit management grows per-host targeting, staged
rollouts, or team-shared profiles. None of that is asked for, and buying it
now costs a second config file whose overlap with `mcp-toolkits.yaml`'s
existing `enabled:` flag would be a standing source of confusion. If the
need appears, A's subcommands are the natural sugar to put on top of C
later — A does not preclude C.

The tradeoff against **Option D** is about sequencing, not merit. D is the
right long-run answer to "who owns a template", and core bundling a template
whose `class:` points into `parrot_tools` is a real wart that D would fix.
But D is a packaging change across four distributions that delivers none of
the `list`/`enable`/`disable` capability the owner actually asked for. A
ships the capability; D remains open as a follow-up that can change the
template *source* without changing the command surface A establishes.

**Option B** is rejected outright: it distributes host-agnostic logic across
three host-specific commands and has no home for `enable`/`disable`/
`uninstall`.

What Option A trades away: it accepts a wide (if shallow) diff across the
three host installers to remove `--toolkits=`, and it accepts breaking
existing installs. Both are owner decisions, and the hard cut is consistent
with this project's no-deprecation-shims policy.

---

--- Recommended option body ---

### Option A: `parrot toolkits` group over the existing seed + reconcile machinery

A new top-level lazy Click group `toolkits` with five subcommands
(`list`, `install`, `uninstall`, `enable`, `disable`) that orchestrates
machinery which **already exists and is already tested**:

- selection → `toolkit_seed.available_templates()` / `load_template()` for
  names and `# parrot:summary:` descriptions;
- seeding → `toolkit_seed.seed_toolkit_sections()`;
- host wiring → the three hosts' existing `_install_mcp*` reconcilers, which
  already derive their entry set from `load_toolkits_config(root)` filtered
  on `section.enabled`.

The decisive insight: **enable/disable already works end-to-end today.** All
three host installers compute desired entries from enabled sections and
remove entries for sections that are disabled or deleted
(`claude_code/installer.py:528-532`, `google/installer.py:187-191`,
`codex/installer.py:134`). `parrot toolkits disable X` is therefore a YAML
flag flip plus a re-run of the host reconciler — no new reconciliation logic.

Five new templates ship: `querysource`, `database-query`, plus `scraping`,
`browsing`, `memory` migrated out of `BUILTIN_TOOLKITS`. `BUILTIN_TOOLKITS`
is deleted, which also removes the awkward workaround block in
`toolkit_seed.py:193-205` that exists solely to filter builtins back out of
`load_toolkits_config`'s result.

Interactive picker uses `questionary.checkbox` — already a **core**
dependency (`pyproject.toml:165`), already used this way in
`knowledge/wiki/cli.py:4591-4606`.

✅ **Pros:**
- Smallest new surface for the largest capability gain — most of the work is
  wiring and five YAML templates, not new subsystems.
- Reuses three independently-tested reconcilers; foreign-entry protection,
  marker blocks and managed-shape detection all come for free.
- Deleting `BUILTIN_TOOLKITS` *simplifies* two modules rather than
  complicating them.
- `list` gives the operator something they have never had: available
  toolkits with descriptions and per-host installed state.
- Non-interactive forms fall out naturally (names as arguments, `--yes`).

❌ **Cons:**
- Touches all three host installers to remove the `toolkits` parameter
  (hard cut) — a wide, if shallow, diff.
- Breaks existing installs in this repo and any other that relies on the
  builtins; deliberate, but it is real churn.
- A fourth host added later means touching `parrot toolkits` too, not just
  that host's installer.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `questionary>=2.1.1` | Interactive checkbox/select picker | Already a **core** dependency (`pyproject.toml:165`); precedent at `wiki/cli.py:4602`. Blocking — must never be called from async code. |
| `click>=8.1.7` | CLI group, options, `--yes` confirmation | Core dep; `LazyGroup` pattern already in `parrot/cli/__init__.py`. |
| `rich>=13.0` | Tabular `list` output | Core dep (`pyproject.toml:131`). |
| `PyYAML` | Read/write `enabled:` in the config | Already used by `toolkit_config.py` / `toolkit_seed.py`. |

🔗 **Existing Code to Reuse:**
- `parrot/mcp/toolkit_seed.py` — `available_templates()`, `load_template()`,
  `seed_toolkit_sections()`, `template_drift()`, `SeedResult`.
- `parrot/mcp/toolkit_config.py` — `ToolkitSection`, `load_toolkits_config()`.
- `parrot/knowledge/wiki/claude_code/installer.py:462` `_install_mcp_json`,
  `:340` `_install_mcp_approval`, `:420` `_is_managed_toolkit_entry`.
- `parrot/knowledge/wiki/codex/installer.py:110` `_install_mcp`.
- `parrot/knowledge/wiki/google/installer.py:139` `_install_mcp`.
- `parrot/cli/__init__.py` — `LazyGroup` + `_lazy_commands` registration.
- `parrot/mcp/_toolkit_templates/bounded-source.yaml` — template format with
  `# parrot:summary:` / `# parrot:requires_llm:` headers.

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py
packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
packages/ai-parrot/src/parrot/mcp/toolkit_config.py
packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
