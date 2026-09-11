---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: sdd-coder Shared Conventions & Turn Budget

**Feature ID**: FEAT-553
**Date**: 2026-09-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor after FEAT-549 (`parrot/version.py`)
**Enhances**: FEAT-549 — `sdd/specs/sdd-worker-subagents.spec.md`

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

FEAT-549 turned `sdd-worker` into an orchestrator that dispatches one
`sdd-coder` per task across heterogeneous seats: a native Claude Code
sub-agent (`haiku`) plus MCP seats driven by external coding agents
(`nova`, `google-compat`, `codex`, `google_coding`). Those seats do **not**
receive the same directives as the native seat:

| Seat | Backend | What it receives from the repository today |
|---|---|---|
| `haiku` | native `Agent` | `CLAUDE.md`, `.agent/CONTEXT.md`, every `.claude/rules/*.md` — injected by Claude Code itself |
| `codex-spark` | `codex` CLI | `AGENTS.md` only (the dispatcher keeps `ignore_rules=False`, `models/codex.py:30`) |
| `gemini` | `google-compat` (in-process `LLMCodeDispatcher` loop) | **nothing** |
| `qwen` / `minimax` | `nova` (in-process `LLMCodeDispatcher` loop) | **nothing** |
| — | `google_coding` (`agy` CLI) | `GEMINI.md` only |

Every MCP seat gets exactly one repo-derived input: the body of
`_subagent_data/sdd-coder.md`, whose only convention line is
*"asyncio-first, Pydantic v2, Google-style docstrings, `self.logger`"*
(`_subagent_data/sdd-coder.md:108`). Nothing tells an external coder that
the HTTP stack is aiohttp + navigator-api behind gunicorn, that `requests`
/ `httpx` / `starlette` / `uvicorn` / `fastapi` / LangChain are forbidden,
that the repo is a uv workspace with no root `parrot/` directory, or that
the lint gate is ruff. The result is convention drift: an external seat
reaches for starlette or uvicorn in an aiohttp repo, and the drift is only
caught (if at all) at code review.

The two files external CLIs do read are stale: `AGENTS.md` is a generic
persona (Svelte/Capacitor front-end and `prettier`, an `isort` step no
tooling runs, an unresolved `@RTK.md` include, and a pointer *"Rules:
are specific rules for python development, use it"* with no path), and
`GEMINI.md` contains only the LLM-wiki nudge block.

Separately, the in-process loop's library default turn budget
(`LLMCodeDispatchProfile.max_turns = 24`, `models/llm.py:23`) is too small
for a real SDD task: an operator-measured run needed 35 turns and died
against the budget. The MCP roster path already overrides that default to
60 via `build_dispatcher` (`agent_builder.py:134`), so the library default
is the number that bites whenever a profile is constructed directly.

### Goals

- **G1 — One source of truth for coding conventions**, tool-neutral, under
  `.agent/rules/`: the three existing coding rule files plus a new
  `codebase-conventions.md` (stack, forbidden libraries with their
  substitutes, workspace layout, tooling, code standards).
- **G2 — Every MCP seat receives the conventions inline** in its system
  prompt / prompt preamble, next to the `sdd-coder` body — never as a
  "go read this file" instruction that costs turns and may be skipped.
- **G3 — The native seat keeps reading the same text** through
  `.claude/rules/`, guarded by a byte-parity test (the FEAT-377 pattern).
- **G4 — `AGENTS.md` and `GEMINI.md` carry a managed conventions block**
  regenerated from the same source by the existing `parrot wiki codex
  install` / `parrot wiki google install` installers, so a hand-launched
  codex / agy session sees the same rules.
- **G5 — A deterministic backstop that does not depend on any model
  reading anything**: ruff `flake8-tidy-imports` banned-api (TID251) for
  the forbidden modules, wired into `ruff.toml`, and enforced per attempt
  by the FEAT-549 engine before a branch is eligible for merge.
- **G6 — Library default `max_turns` raised from 24 to 40** on
  `LLMCodeDispatchProfile` and on the one subclass that redeclares it
  (`GrokCodeDispatchProfile`), without touching the 60-turn wiring default.

### Non-Goals (explicitly out of scope)

- Turning the conventions into a **skill**. External seats have no
  on-demand skill loader (the in-process loop has no `load_skill` tool),
  and a skill is by definition something the agent decides to invoke. An
  always-injected rule is the right shape.
- Language-aware injection (only shipping the Cython/Rust rules when the
  task touches `.pyx`/`.rs`). The full coder rule set is ~10 KB (~2.5 K
  tokens); trimming it is a later optimisation, see §8.
- Rewriting `AGENTS.md`'s **safety / git protocol** sections. Only the
  stale tech-stack and formatting prose is pruned (§3 M3, §8 Q1 resolved).
- Changing `DEFAULT_LLM_MAX_TURNS = 60` or the `DEV_LOOP_LLM_MAX_TURNS`
  env override in `agent_builder.py`.
- Bringing the whole repository to zero TID251 findings. Existing
  `requests`/`httpx`/`starlette`/`uvicorn` usages are grandfathered by
  file (§7) so the rule bites only new code.

---

## 2. Architectural Design

### Overview

One directory, `.agent/rules/`, becomes the canonical home of the coder
rule set — the four files named in `CODER_RULE_NAMES`. Three consumers read
it, each through the mechanism it already has:

1. **Claude Code (native seat)** keeps auto-loading `.claude/rules/*.md`.
   The four files exist there as byte-identical twins; a parity test
   fails when they drift (the same discipline `test_subagent_parity.py`
   applies to `_subagent_data/*.md` vs `.claude/agents/*.md`).
2. **The three dispatch prompt builders** call a new helper,
   `load_project_conventions(cwd)`, and append its output to the prompt
   right after the `sdd-coder` body. The helper prefers the worktree copy
   (`<cwd>/.agent/rules/<name>.md`, so a feature branch that edits a rule
   dispatches its own version) and falls back to a package-shipped copy
   under `parrot/flows/_rules_data/` — the same dual-sourcing
   `load_subagent_definition` already uses, so dispatch keeps working when
   `ai-parrot` runs from a wheel outside the repo. The helper lives in a
   **stdlib-only leaf module, `parrot/flows/conventions.py`** (importing
   `parrot.flows` costs ~8 ms; importing anything under
   `parrot.flows.dev_loop` costs ~2.2 s because that package's `__init__`
   eagerly imports every dispatcher), and `_subagent_defs` re-exports it.
3. **`AGENTS.md` / `GEMINI.md`** get a `<!-- parrot:conventions:… -->`
   marker block rendered from the same helper, upserted by **both**
   installer paths: the codex/google wiki installers
   (`knowledge/wiki/codex|google/installer.py`) and the stdlib-only
   `coding_agents.install()` (`parrot wiki <agent> install`). `AGENTS.md`'s
   stale prose outside the markers (front-end stack, `isort`/`prettier`,
   the unresolved `@RTK.md` include) is pruned in the same module. `black`
   stays: it IS the repo's formatter (`Makefile:399/404`, `pyproject.toml:237`).

Prompts are advisory, so the guarantee is deterministic: `ruff.toml` bans
the forbidden modules (TID251) with a per-file grandfather list, and the
FEAT-549 engine runs `ruff check --select TID251` over the attempt's
changed files right after the dispatch returns. A violation is recorded
as an **attempt error**, which feeds the existing retry ladder (attempt 2
on a different seat, then `failed`) instead of the non-retried
`fidelity_violation` outcome — a banned import is a code-quality failure a
different seat can fix, not a scope breach.

Finally, `max_turns` defaults move from 24 to 40 in
`LLMCodeDispatchProfile` and `GrokCodeDispatchProfile`; the "Your budget is
N turns" sentence in `_initial_messages` reads the profile, so it follows
automatically.

### Component Diagram

```
.agent/rules/{codebase-conventions,python-development,
              cython-development,rust-development}.md      ← single source
        │
        ├─ byte-parity test ──→ .claude/rules/<same>.md    ← native haiku seat (Claude Code auto-load)
        │
        ├─ byte-parity test ──→ parrot/flows/_rules_data/<same>.md   ← wheel fallback
        │
        └─ parrot/flows/conventions.py : load_project_conventions(cwd)   (stdlib-only leaf)
                 │
                 ├─→ _subagent_defs (re-export) ─→ LLMCodeDispatcher._initial_messages()      (nova, google-compat, grok, zai, moonshot)
                 │                              ├→ CodexCodeDispatcher._build_codex_prompt()  (codex)
                 │                              └→ GoogleCodingDispatcher._build_agy_prompt() (agy)
                 ├─→ knowledge/wiki/codex|google installers ──→ AGENTS.md / GEMINI.md marker block
                 └─→ knowledge/wiki/coding_agents.install()   ──→ AGENTS.md / GEMINI.md marker block (claude: unchanged)

ruff.toml [lint.flake8-tidy-imports.banned-api] ──→ sdd-coder step e) `ruff check`
                                                 └─→ SddCoderEngine._run_attempt() → check_banned_imports() → attempt error
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/flows/conventions.py` (new) | creates | stdlib-only `CODER_RULE_NAMES`, `load_project_conventions()`, `CONVENTIONS_PREAMBLE` |
| `parrot.flows.dev_loop._subagent_defs` | extends | re-exports the three names above |
| `knowledge/wiki/coding_agents.py` `install()` (`:89`) | extends | second marker block for conventions, all three agents |
| `AGENTS.md` | modifies | stale prose pruned outside the managed blocks |
| `LLMCodeDispatcher._initial_messages` (`llm.py:891`) | modifies | appends conventions to the system message |
| `CodexCodeDispatcher._build_codex_prompt` (`codex.py:345`) | modifies | gains `cwd`, appends conventions after the body |
| `GoogleCodingDispatcher._build_agy_prompt` (`google_coding.py:317`) | modifies | gains `cwd`, appends conventions after the body |
| `SddCoderEngine._run_attempt` (`engine.py:520`) | modifies | runs `check_banned_imports` after a successful dispatch |
| `sdd_coder/fidelity.py` | extends | adds `check_banned_imports()` |
| `knowledge/wiki/codex/installer.py` `_install_agents` (`:77`) | extends | second marker block for conventions |
| `knowledge/wiki/google/installer.py` `_install_gemini_md` (`:81`) | extends | second marker block for conventions |
| `ruff.toml` | modifies | `TID251` in `select`, `banned-api` table, grandfather `per-file-ignores` |
| `models/llm.py:23`, `models/grok.py:22` | modifies | `max_turns` default 24 → 40 |
| `packages/ai-parrot/pyproject.toml:894-909` | modifies | new package-data entry `"parrot.flows" = ["_rules_data/*.md"]` |
| `tests/flows/dev_loop/test_subagent_parity.py` | reference | pattern reused by the new `test_rules_parity.py` |

### Data Models

No new Pydantic models. `AttemptRecord.error` (`sdd_coder/models.py:126`)
carries the banned-import failure text; `DispatchEvent` payloads are
unchanged.

### New Public Interfaces

```python
# parrot/flows/conventions.py  (new, stdlib-only — re-exported by parrot/flows/dev_loop/_subagent_defs.py)
CODER_RULE_NAMES: tuple[str, ...]
RULES_DIRNAME: str  # ".agent/rules"
CONVENTIONS_PREAMBLE: str

def load_project_conventions(cwd: str | os.PathLike[str] | None = None, *, names: Sequence[str] = CODER_RULE_NAMES) -> str: ...

# parrot/flows/dev_loop/sdd_coder/fidelity.py
async def check_banned_imports(cwd: str, changed: List[str]) -> List[str]: ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Conventions source of truth + `parrot/flows/conventions.py` | **no** (content) / yes (module, twins, parity test) | File names, twin locations, loader signature and lookup order, parity test shape fixed | The prose of `codebase-conventions.md` encodes architectural decisions; a thinking model writes it, the module/twins/tests are mechanical |
| M2: prompt injection + `_subagent_defs` re-export | yes | Insertion point per builder, `cwd` kwarg, preamble constant all fixed below; consumes the M1 module | — |
| M3: AGENTS.md / GEMINI.md conventions block + AGENTS.md prune | yes | Marker strings, upsert helpers, installer hook points, and the exact list of AGENTS.md sections to delete are fixed | — |
| M4: ruff banned-api + engine backstop | yes | Rule list, grandfather list, `check_banned_imports` contract, attempt-error wiring fixed | — |
| M5: `max_turns` 24 → 40 | yes | Two field defaults + one comment + one test | — |

### Module 1: Conventions source of truth
- **Path**: `.agent/rules/codebase-conventions.md` (new),
  `.claude/rules/codebase-conventions.md` (new twin),
  `.agent/rules/python-development.md` + `.claude/rules/python-development.md` (modifies CRITICAL RULE 2 — see below),
  `packages/ai-parrot/src/parrot/flows/conventions.py` (new, stdlib-only: `CODER_RULE_NAMES`, `RULES_DIRNAME`, `CONVENTIONS_PREAMBLE`, `_strip_frontmatter`, `load_project_conventions` — contract in §3 M2's skeleton; M1 owns the file so M1's tests collect on their own),
  `packages/ai-parrot/src/parrot/flows/_rules_data/{codebase-conventions,python-development,cython-development,rust-development}.md` (new, byte-identical to `.agent/rules/`),
  `packages/ai-parrot/pyproject.toml` (`[tool.setuptools.package-data]`, add `"parrot.flows" = ["_rules_data/*.md"]` next to the `parrot.flows.dev_loop` entry at `:906`),
  `packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py` (new)
- **Responsibility**: the canonical coder rule set and the guards that keep
  its three copies identical. `.agent/rules/python-development.md`,
  `cython-development.md`, `rust-development.md` already exist and are
  byte-identical to their `.claude/rules/` twins today (verified
  2026-09-12). `cython-development.md` and `rust-development.md` are
  adopted as-is. `python-development.md` CRITICAL RULE 2 ("NEVER run
  `uv`, `python`, or `pip` commands without activating first") gains one
  sentence: *"A tool-driven coder with no shell (the dev-loop in-process
  seats) cannot `source`; it runs the allowlisted `pytest`/`ruff`/
  `python`/`uv` binaries directly and never provisions a `.venv` in its
  worktree."* All three copies (`.agent/`, `.claude/`, `_rules_data/`)
  change together.
- **Depends on**: nothing.
- **Content contract for `codebase-conventions.md`** (section outline —
  the body is written in the task, but every bullet below is a §5
  acceptance criterion):
  1. `## Stack` — aiohttp + navigator-api, served by gunicorn; async-first;
     `AbstractClient` for every LLM call; Pydantic v2 for data; `self.logger`.
  2. `## Forbidden — and what to use instead` — a table:
     `requests`/`httpx` → `aiohttp`; `starlette`/`fastapi`/`uvicorn` → the
     aiohttp handlers under `parrot/handlers/` + gunicorn; `langchain*` →
     framework primitives (removed, never subclass); `print` → `self.logger`;
     `pip`/`poetry` → `uv`; `isort`/`prettier` → nothing (no import-sorting
     step exists; `black` formats, `ruff` lints).
  3. `## Repository layout` — uv workspace, `packages/*`, no root `parrot/`;
     core source root `packages/ai-parrot/src/parrot/`; PEP 420 satellites;
     concrete tools live in `parrot_tools`.
  4. `## Tooling` — two explicit modes, because the in-process seats have
     no shell (`llm.py:922`, `_tool_run_command` `:1713`, `_run_argv`
     `:1944` exec a bare argv against an allowlist) and a task worktree is
     a bare `git worktree` with no `.venv` (`worktree_manager.py:146`):
     - *Interactive shell (humans, Claude Code, codex, agy)*: `source
       .venv/bin/activate` first; then `uv add` / `uv pip`, `pytest`,
       `ruff check`, `black`.
     - *Tool-driven coder without a shell*: never try `source`; call the
       allowlisted binaries directly (`pytest`, `ruff`, `python`, `uv`) —
       the host resolves them on its `PATH` (the main checkout's `.venv`);
       do not create or look for a `.venv` inside the worktree.
     - Common: `black` (line-length 120) formats, `ruff check` is the lint
       gate, `pytest` + `pytest-asyncio`, tests live under
       `packages/<dist>/tests/`.
  5. `## Code standards` — Google-style docstrings, strict type hints,
     snake_case / PascalCase, 120-column lines, no blocking I/O in async
     code, secrets via environment only.
  6. Size cap: the four coder rule files together ≤ 12 000 bytes
     (they are injected into a 40-turn prompt).
- **Interface Skeleton** *(test module only — rule files are Markdown)*:
  ```python
  # packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py  (new; mirrors test_subagent_parity.py:38-64)
  from parrot.flows.conventions import CODER_RULE_NAMES  # created by THIS module (M1)

  @pytest.mark.parametrize("name", CODER_RULE_NAMES)
  def test_claude_rules_twin_is_identical(name: str) -> None:
      """`.claude/rules/<name>.md` == `.agent/rules/<name>.md` byte-for-byte; skipped when the repo dir is absent (wheel install)."""

  @pytest.mark.parametrize("name", CODER_RULE_NAMES)
  def test_package_rules_copy_is_identical(name: str) -> None:
      """`parrot/flows/_rules_data/<name>.md` == `.agent/rules/<name>.md` byte-for-byte; skipped when the repo dir is absent."""

  def test_coder_rules_fit_the_prompt_budget() -> None:
      """sum(len(bytes)) over CODER_RULE_NAMES in `parrot/flows/_rules_data/` ≤ 12_000."""
  ```

### Module 2: prompt injection + `_subagent_defs` re-export
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` (modifies: re-export only),
  `dispatchers/llm.py` (modifies `_initial_messages`, `:891`),
  `dispatchers/codex.py` (modifies `_build_codex_prompt` `:345` and its call site `:118`),
  `dispatchers/google_coding.py` (modifies `_build_agy_prompt` `:317` and its call site `:171`),
  `tests/flows/dev_loop/test_subagent_defs_conventions.py` (new — re-export identity only; loader tests live in M1's `tests/flows/test_conventions.py`),
  `tests/flows/dev_loop/test_llm_code_dispatcher.py` (extends, next to `test_system_prompt_names_the_working_directory` `:711`)
- **Responsibility**: read the rule set once per dispatch and put it in the
  prompt, inline, for every backend that builds its own prompt.
- **Depends on**: Module 1 (owns `parrot/flows/conventions.py` and the package copy).
- **Interface Skeleton**:
  ```python
  # parrot/flows/conventions.py  (CREATED IN M1 — contract restated here because M2 consumes it; imports ONLY os, pathlib, importlib.resources, typing — never parrot.flows.dev_loop)
  CODER_RULE_NAMES: tuple[str, ...] = (
      "codebase-conventions", "python-development", "cython-development", "rust-development",
  )
  RULES_DIRNAME: str = ".agent/rules"
  CONVENTIONS_PREAMBLE: str = (
      "Project conventions — binding for every file you touch; a banned import fails "
      "this attempt at the merge gate:"
  )

  def _strip_frontmatter(text: str) -> str:
      """Same contract as `_subagent_defs._strip_frontmatter` (:64); duplicated here (8 lines) so this module stays a leaf.
      `_subagent_defs` switches to importing THIS one to keep a single implementation."""

  def load_project_conventions(
      cwd: str | os.PathLike[str] | None = None,
      *,
      names: Sequence[str] = CODER_RULE_NAMES,
  ) -> str:
      """Return the coder rule set as ONE Markdown block for prompt injection.

      Lookup order per name: `<cwd>/.agent/rules/<name>.md` when `cwd` is given and the
      file exists (the worktree copy wins, so a branch that edits a rule dispatches its own
      text), else the package copy `files("parrot.flows") / "_rules_data" / f"{name}.md"`.
      Each file has its YAML frontmatter stripped with `_strip_frontmatter` and is wrapped as
      `## Project rule: <name>\n\n<body>`; blocks are joined with `\n\n---\n\n`.
      Never raises for a missing worktree file. Raises FileNotFoundError only when a
      package copy is missing (packaging error), ValueError when a name is not in
      CODER_RULE_NAMES.
      """

  # parrot/flows/dev_loop/_subagent_defs.py  (modifies :117 — re-export, no logic)
  from parrot.flows.conventions import CODER_RULE_NAMES, CONVENTIONS_PREAMBLE, load_project_conventions, _strip_frontmatter
  __all__ = ["load_subagent_definition", "load_project_conventions", "CODER_RULE_NAMES", "CONVENTIONS_PREAMBLE"]

  # parrot/flows/dev_loop/dispatchers/llm.py  (modifies _initial_messages, :891-951)
  def _initial_messages(self, profile, brief, output_model, *, cwd: str = "") -> List[Dict[str, Any]]:
      """Unchanged signature. The system content gains, immediately after
      `f"Subagent instructions:\n{body}"`:
          "\n\n" + CONVENTIONS_PREAMBLE + "\n" + load_project_conventions(cwd or None)
      """

  # parrot/flows/dev_loop/dispatchers/codex.py  (modifies :345; call site :118 passes cwd=cwd)
  def _build_codex_prompt(self, profile, brief, output_model, *, cwd: str = "") -> str:
      """Same text as today plus the conventions paragraph between the body and the output prompt."""

  # parrot/flows/dev_loop/dispatchers/google_coding.py  (modifies :317; call site :171 passes cwd=cwd)
  def _build_agy_prompt(self, profile, brief, output_model, *, cwd: str = "") -> str:
      """Same text as today plus the conventions paragraph between the body and the output prompt."""
  ```
- **Notes**: the three builders use the `CONVENTIONS_PREAMBLE` constant, never
  a re-typed literal. `NovaCodeDispatcher`
  and `GoogleCompatCodeDispatcher` inherit `_initial_messages`, so they
  need no change (`nova.py:66`, `google_compat.py:19`).

### Module 3: AGENTS.md / GEMINI.md conventions block + AGENTS.md prune
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (modifies),
  `knowledge/wiki/codex/installer.py` (modifies `_install_agents` `:77`, `uninstall_codex_integration` `:235`),
  `knowledge/wiki/google/assets.py` (modifies),
  `knowledge/wiki/google/installer.py` (modifies `_install_gemini_md` `:81`, `uninstall_google_integration` `:247`),
  `knowledge/wiki/coding_agents.py` (modifies `install()` `:89`; adds `_conventions_markers`, `_conventions_block`),
  `AGENTS.md` (pruned + regenerated block), `GEMINI.md` (regenerated block),
  `packages/ai-parrot/tests/test_coding_agents.py` (extends),
  `packages/ai-parrot/tests/knowledge/wiki/test_codex_installer_conventions.py` (new),
  `packages/ai-parrot/tests/knowledge/wiki/test_google_installer_conventions.py` (new)
- **Responsibility**: a second managed block —
  `<!-- parrot:conventions:codex:begin/end -->` in `AGENTS.md`,
  `<!-- parrot:conventions:google:begin/end -->` in `GEMINI.md` — and
  **no block in `CLAUDE.md`**: the Claude native seat already reads
  `.claude/rules/`, a generated 10 KB block there would duplicate context
  in every Claude Code session, and `coding_agents` has no uninstaller to
  remove it (review R5). `coding_agents.install("claude")` is unchanged.
  The block body is
  `load_project_conventions(root)` under a `## Project conventions`
  heading. **Both installer paths** write it (§8 Q3 resolved: yes):
  the `knowledge/wiki/codex|google` installers via their own
  `_upsert_marker_block` (`codex/installer.py:17`, `google/installer.py:18`)
  and the stdlib-only `coding_agents.install()` via its `_upsert` (`:66`).
  Uninstall (only the `knowledge/wiki/codex|google` installers have one;
  `coding_agents.py` exposes `install` and `hook` only, `:89`/`:125`) removes
  it with `_remove_marker_block` (`:31` / `:32`).
  **Marker canonicalisation (review R4):** `coding_agents._AGENTS` maps both
  `gemini` and `google` to `GEMINI.md` (`:43-55`), so the conventions
  marker is keyed by the *canonical* name, not the raw alias:
  `codex → codex`, `gemini → google`, `google → google`. The strings are
  therefore byte-identical across both installer paths, and either
  installer updates or removes the block the other wrote.
- **AGENTS.md prune** (§8 Q1 resolved: yes). Delete, outside the managed
  blocks: the whole `### Frontend / Mobile (If React/Web detected)`
  section; in `## CODING STANDARDS` the `prettier` and `isort` lines
  and the two JavaScript camelCase/PascalCase lines (the `black` line
  stays — black is the active formatter, review R3); the sentence
  `- **Rules:** are specific rules for python development, use it.`; the
  trailing `@RTK.md` line (a Claude-Code import codex cannot resolve).
  Replace the `### Python / Backend` and `### Rust Development` bodies
  with one line each pointing at the conventions block ("see *Project
  conventions* below"). Keep untouched: role/planning/operating
  style/tone, MUST-READ FILES, SAFETY & GIT PROTOCOLS, ARCHITECTURE &
  PATTERN, the Completeness / No Hallucinations / Dependency Hygiene /
  Change Discipline / Correctness First paragraphs, and the wiki block.
- **Depends on**: Module 2.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/codex/assets.py  (modifies; next to AGENTS_BEGIN :13)
  CONVENTIONS_BEGIN = "<!-- parrot:conventions:codex:begin -->"
  CONVENTIONS_END = "<!-- parrot:conventions:codex:end -->"
  def conventions_section(root: Path) -> str:
      """`{CONVENTIONS_BEGIN}\n## Project conventions\n\n{load_project_conventions(root)}\n\n{CONVENTIONS_END}\n`."""

  # knowledge/wiki/codex/installer.py  (modifies _install_agents :77)
  def _install_agents(root: Path) -> str:
      """Upserts the wiki block (unchanged) THEN the conventions block; return string names both."""

  # knowledge/wiki/google/assets.py / installer.py — same pair with the `google` marker and GEMINI_PATH (:17 / :81)

  # knowledge/wiki/coding_agents.py  (modifies; stdlib-only contract kept — imports parrot.flows.conventions ONLY)
  _CONVENTIONS_AGENT: dict[str, str] = {"codex": "codex", "gemini": "google", "google": "google"}   # no "claude" entry — install("claude") writes no conventions block
  def _conventions_markers(agent: str) -> tuple[str, str]:
      """`<!-- parrot:conventions:{_CONVENTIONS_AGENT[agent]}:begin -->` / `…:end -->` — byte-identical to the codex/google assets constants. KeyError-free: returns None for "claude" and install() skips the block."""
  def _conventions_block(agent: str, root: Path) -> str:
      """`{begin}\n## Project conventions\n\n{load_project_conventions(root)}\n\n{end}\n`."""
  def install(agent: str, root: Path = Path.cwd()) -> list[str]:
      """Unchanged signature. After the wiki `_upsert` (:97-100), for agents in _CONVENTIONS_AGENT runs a second
      `_upsert` with the conventions block on the same instruction file; `changes` still lists the file once."""
  ```
- **Notes**: blocks are regenerated, never hand-edited. Order in a fresh
  file: wiki block, then conventions block; re-running must not reorder.

### Module 4: ruff banned-api + engine backstop
- **Path**: `ruff.toml` (modifies `[lint] select` and adds two tables),
  `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` (extends),
  `sdd_coder/engine.py` (modifies `_run_attempt` `:520-590` AND `_consolidate` `:337-405`),
  `.claude/agents/sdd-worker.md:242` + `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (byte-parity twin — one bullet: `fidelity_violation` now also covers banned imports),
  `docs/dev_loop/sdd-coder-orchestrator.md:125` (outcome table row),
  `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/` (extends the fidelity + engine tests)
- **Responsibility**: make a banned import a lint error everywhere
  (`ruff check` is already step e) of `sdd-coder.md`), and make the engine
  refuse to consolidate an attempt that introduced one.
- **Depends on**: nothing (independent of M1–M3).
- **Decided configuration** (`ruff.toml`, ruff 0.16.3):
  ```toml
  [lint]
  select = ["E4", "E7", "E9", "F", "TID251"]

  [lint.flake8-tidy-imports.banned-api]
  "requests".msg  = "Use aiohttp (parrot.interfaces.http / parrot.tools) — requests is synchronous and banned."
  "httpx".msg     = "Use aiohttp — httpx is banned in this repository."
  "starlette".msg = "The HTTP stack is aiohttp + navigator-api behind gunicorn — starlette is banned."
  "fastapi".msg   = "The HTTP stack is aiohttp + navigator-api behind gunicorn — fastapi is banned."
  "uvicorn".msg   = "Serve with gunicorn (aiohttp worker) — uvicorn is banned."
  "langchain".msg           = "LangChain was removed; use parrot primitives (AbstractClient, AbstractTool, …)."
  "langchain_core".msg      = "LangChain was removed; use parrot primitives."
  "langchain_community".msg = "LangChain was removed; use parrot primitives."
  "langgraph".msg           = "LangGraph is banned; use AgentsFlow / AgentCrew (parrot.bots.flows)."
  "langsmith".msg           = "LangSmith is banned; use parrot observability."

  [lint.per-file-ignores]   # grandfathered, existing usages only — never add a new file here
  "packages/ai-parrot/src/parrot/flows/dev_loop/replication.py" = ["TID251"]
  "packages/ai-parrot/src/parrot/interfaces/http.py" = ["TID251"]
  "packages/ai-parrot/src/parrot/interfaces/jira/client.py" = ["TID251"]
  "packages/ai-parrot/src/parrot/interfaces/onedrive.py" = ["TID251"]
  "packages/ai-parrot/src/parrot/interfaces/sharepoint.py" = ["TID251"]
  "packages/ai-parrot/src/parrot/interfaces/soap.py" = ["TID251"]
  "packages/ai-parrot/src/parrot/tools/openapitoolkit.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/bingsearch.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/massive/client.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/o365/delta.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/powerbi.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/research/academic.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/research/open_data.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/serpapi.py" = ["TID251"]
  "packages/ai-parrot-tools/src/parrot_tools/zipcode.py" = ["TID251"]
  "packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_tool_bridge.py" = ["TID251"]
  ```
  (17 files, measured 2026-09-12: 7 import `requests`, 10 `httpx`,
  `codex_tool_bridge.py` imports `starlette` + `uvicorn`; `fastapi`,
  `langchain`, `langchain_core`, `langchain_community`, `langgraph` and
  `langsmith` have zero usages.) `banned-api` matches a module and its
  submodules (`langchain.chains`), but NOT sibling top-level names, hence
  the explicit `langchain_*`/`langgraph`/`langsmith` rows (§8 Q4 resolved:
  nothing `langchain*` in the repo). A new `langchain_<provider>` package
  seen in a diff is added to this table on sight.
- **Interface Skeleton**:
  ```python
  # parrot/flows/dev_loop/sdd_coder/fidelity.py  (extends; after check_fidelity)
  async def check_banned_imports(cwd: str, changed: List[str]) -> List[str]:
      """Run `ruff check --select TID251 --output-format json --no-fix <changed .py files>` in `cwd`
      (asyncio.create_subprocess_exec, same shape as engine._git :69-80) and return one
      `"<path>:<row>: <message>"` line per finding. Empty list ⇔ clean. Non-.py paths are
      skipped; an empty `changed` returns [] without spawning ruff. A ruff that is missing or
      exits ≥ 2 is reported as a single `"ruff: <stderr>"` line — never raises, the caller
      decides.
      """

  # parrot/flows/dev_loop/sdd_coder/engine.py  (modifies _run_attempt, :520-590)
  #   after `output = await dispatcher.dispatch(...)` succeeds and BEFORE returning:
  #     changed = <git diff --name-only <feature_branch>...HEAD in `path`>  (reuse the diff shape of :374)
  #     violations = await check_banned_imports(path, changed)
  #     if violations: error = "BannedImport: " + "; ".join(violations); collector.error = error; output = None
  #   → the existing ladder in _run_task (:596-616) retries on a different seat, then `failed`.

  # parrot/flows/dev_loop/sdd_coder/engine.py  (modifies _consolidate, :337-405 — the SHARED merge boundary, review R1)
  #   `merge()` (:407) calls _consolidate directly (:428) for native tasks and for re-merges after a
  #   manual conflict fix, bypassing _run_attempt. So the same check runs here, right after the
  #   fidelity report at :374 and BEFORE the merge:
  #     violations = await check_banned_imports(path, changed)      # `changed` is the diff list already computed for check_fidelity
  #     if violations: return TaskResult(task_id=..., outcome="fidelity_violation", branch=branch, worktree_path=path,
  #                                      diagnostics="BannedImport: " + "; ".join(violations))
  #   Native attempt with a banned import → `fidelity_violation` (sdd-worker fixes it itself, as for any
  #   fidelity_violation); MCP attempt → caught earlier in _run_attempt (retry ladder), and _consolidate
  #   is the backstop for a branch amended after that check.
  ```

### Module 5: `max_turns` library default 24 → 40
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py:23`,
  `models/grok.py:22`, `agent_builder.py:129` (comment: "library default of 24" → 40),
  `tests/flows/dev_loop/test_llm_code_dispatcher.py` (one assertion),
  `docs/dev_loop/sdd-coder-orchestrator.md` (one sentence in Troubleshooting)
- **Responsibility**: the operator's measured need (35 turns) fits the
  library default with headroom. The `le=100` bound and the wiring default
  of 60 are untouched.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # models/llm.py:23   (modifies)
  max_turns: int = Field(default=40, ge=1, le=100)
  # models/grok.py:22  (modifies — the only subclass that redeclares the field; nova/google_compat/zai/moonshot inherit)
  max_turns: int = Field(default=40, ge=1, le=100)
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_claude_rules_twin_is_identical[name]` | M1 | `.claude/rules/<name>.md` == `.agent/rules/<name>.md` for the 4 coder rules |
| `test_package_rules_copy_is_identical[name]` | M1 | `parrot/flows/_rules_data/<name>.md` == `.agent/rules/<name>.md` |
| `test_coder_rules_fit_the_prompt_budget` | M1 | total bytes ≤ 12 000 |
| `test_conventions_prefer_worktree_copy` | M1 | with a tmp `cwd/.agent/rules/codebase-conventions.md`, its text wins over the package copy |
| `test_conventions_fall_back_to_package_copy` | M1 | `cwd=None` and a `cwd` without `.agent/rules/` both return the package text |
| `test_conventions_strip_frontmatter_and_join` | M1 | headings `## Project rule: <name>` and the `---` separator are present, no `---\nname:` frontmatter survives |
| `test_conventions_reject_unknown_name` | M1 | `ValueError` for a name outside `CODER_RULE_NAMES` |
| `test_system_prompt_carries_the_conventions` | M2 | `LLMCodeDispatcher._initial_messages(..., cwd=tmp)` system content contains `## Project rule: codebase-conventions` AFTER `Subagent instructions:` |
| `test_codex_prompt_carries_the_conventions` | M2 | `_build_codex_prompt(..., cwd=tmp)` contains the block between the body and `TASK BRIEF`/output prompt |
| `test_agy_prompt_carries_the_conventions` | M2 | same for `_build_agy_prompt` |
| `test_install_agents_upserts_conventions_block` | M3 | `_install_agents(tmp)` writes both markers; re-run is idempotent (`already current`) |
| `test_uninstall_removes_conventions_block` | M3 | uninstall leaves prose outside the markers untouched |
| `test_install_gemini_md_upserts_conventions_block` | M3 | same for GEMINI.md |
| `test_coding_agents_install_writes_conventions_block[agent]` | M3 | `coding_agents.install(agent, tmp)` for codex/gemini/google writes both marker blocks, idempotent on re-run; `install("claude", tmp)` writes NO conventions block (extends `tests/test_coding_agents.py:9`) |
| `test_gemini_and_google_share_one_conventions_block` | M3 | `coding_agents.install("gemini")` then `install_google_integration()` (and the reverse order) leave exactly ONE `parrot:conventions:google` block in `GEMINI.md`; `uninstall_google_integration()` removes it |
| `test_agents_md_has_no_stale_prose` | M3 | the text of repo `AGENTS.md` **outside** the `parrot:wiki:codex` and `parrot:conventions:codex` marker pairs contains none of `Svelte`, `Capacitor`, `isort`, `prettier`, `camelCase`, `@RTK.md`, `are specific rules for python development`; both marker pairs are present; `black` is allowed anywhere |
| `test_conventions_module_is_import_light` | M1 | `python -c "import parrot.flows.conventions, sys; assert 'parrot.flows.dev_loop' not in sys.modules"` in a subprocess exits 0 |
| `test_check_banned_imports_flags_requests` | M4 | a tmp file with `import requests` → one finding line |
| `test_check_banned_imports_clean_and_empty` | M4 | clean file → `[]`; empty `changed` → `[]` without spawning |
| `test_check_banned_imports_skips_non_python` | M4 | `.md`/`.toml` paths are ignored |
| `test_run_attempt_turns_banned_import_into_attempt_error` | M4 | engine test with a fake dispatcher that writes `import httpx`: `AttemptRecord.error` starts with `BannedImport:` and attempt 2 runs on a different seat |
| `test_consolidate_rejects_banned_import` | M4 | a branch whose committed diff adds `import requests` → `_consolidate` returns `outcome="fidelity_violation"`, `diagnostics` starts with `BannedImport:`, nothing merged |
| `test_merge_entry_point_runs_banned_import_gate` | M4 | `SddCoderEngine.merge()` (native-task path, `:407`) hits the same gate — verified through the public entry point, not only `_consolidate` |
| `test_profile_default_max_turns_is_40` | M5 | `LLMCodeDispatchProfile().max_turns == 40` and `GrokCodeDispatchProfile().max_turns == 40` |
| `test_budget_nudge_states_the_count_and_the_turn_economics` | M5 | existing test (`test_llm_code_dispatcher.py:577`) keeps passing — the sentence reads the profile |

### Integration Tests
| Test | Description |
|---|---|
| `test_ruff_tid251_is_clean_on_the_tree` | `ruff check --select TID251 packages/ scripts/` exits 0 with the grandfather list in place (the backlog rule from `ruff.toml`: the rule must not add findings on `dev`) |
| `test_agent_builder_wiring_default_unchanged` | existing `test_agent_builder.py:123` still asserts `DEFAULT_LLM_MAX_TURNS == 60` |

### Test Data / Fixtures
```python
@pytest.fixture
def rules_worktree(tmp_path: Path) -> Path:
    """A fake worktree with `.agent/rules/codebase-conventions.md` whose body is a sentinel string."""
    d = tmp_path / ".agent" / "rules"
    d.mkdir(parents=True)
    (d / "codebase-conventions.md").write_text("---\nname: x\n---\nSENTINEL-WORKTREE-RULE\n")
    return tmp_path
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1 `.agent/rules/codebase-conventions.md` exists with the five sections of §3 M1 and names every forbidden module with its substitute (`requests`, `httpx`, `starlette`, `fastapi`, `uvicorn`, `langchain`, `print`, `pip`, `isort`); it names `black` as the formatter and `ruff` as the linter, never bans `black`.
- [ ] AC-1b The `## Tooling` section carries both modes (interactive shell vs tool-driven coder) and `.agent/rules/python-development.md` + twins no longer state that `source .venv/bin/activate` is mandatory for a coder without a shell.
- [ ] AC-2 `.claude/rules/<name>.md` and `parrot/flows/_rules_data/<name>.md` are byte-identical to `.agent/rules/<name>.md` for the four `CODER_RULE_NAMES`, enforced by `test_rules_parity.py`.
- [ ] AC-3 The four coder rule files total ≤ 12 000 bytes.
- [ ] AC-4 `load_project_conventions(cwd)` prefers `<cwd>/.agent/rules/`, falls back to the package copy, strips frontmatter, never raises for a missing worktree file.
- [ ] AC-5 The system prompt built by `LLMCodeDispatcher._initial_messages` and the prompts built by `CodexCodeDispatcher._build_codex_prompt` and `GoogleCodingDispatcher._build_agy_prompt` contain the conventions block after the `sdd-coder` body; the `nova` and `google-compat` dispatchers inherit it without changes.
- [ ] AC-6 `parrot wiki codex install`, `parrot wiki google install` AND `coding_agents.install(codex|gemini|google)` upsert an idempotent `parrot:conventions:<canonical>:*` block in `AGENTS.md` / `GEMINI.md` (`gemini` canonicalises to `google`; `claude` writes none); the regenerated blocks are committed; `uninstall_codex_integration` / `uninstall_google_integration` remove them and nothing else (`coding_agents` has no uninstall, pre-existing).
- [ ] AC-6b Outside its managed blocks, `AGENTS.md` no longer contains the Frontend/Mobile section, the `isort`/`prettier`/camelCase lines, the "Rules: are specific rules…" pointer or the `@RTK.md` line; the `black` line and the safety/git sections are byte-unchanged.
- [ ] AC-7 `ruff.toml` selects `TID251` with the §3 M4 banned-api table (incl. `langchain_core`, `langchain_community`, `langgraph`, `langsmith`) and grandfather list; `ruff check --select TID251 packages/ scripts/` exits 0 on `dev` after the change.
- [ ] AC-14 `parrot/flows/conventions.py` imports nothing from `parrot.flows.dev_loop`; importing it in a fresh interpreter leaves `parrot.flows.dev_loop` out of `sys.modules`.
- [ ] AC-8 `check_banned_imports()` returns one line per finding and `[]` when clean; the engine records a `BannedImport:` attempt error and the retry ladder runs attempt 2 on a different seat.
- [ ] AC-8b `_consolidate` — reached by `merge()` for native tasks and re-merges — returns `fidelity_violation` with `BannedImport:` diagnostics for a branch that adds a banned import; nothing is merged. `sdd-worker.md` (both copies) and the orchestrator doc describe the new cause.
- [ ] AC-9 `LLMCodeDispatchProfile().max_turns == 40` and `GrokCodeDispatchProfile().max_turns == 40`; `DEFAULT_LLM_MAX_TURNS` stays 60; `le=100` unchanged.
- [ ] AC-10 `pyproject.toml` package-data ships `parrot/flows/_rules_data/*.md` (verified by `importlib.resources` in the parity test).
- [ ] AC-11 `docs/dev_loop/sdd-coder-orchestrator.md` gains a short "Conventions & lint backstop" section and the 40-turn note.
- [ ] AC-12 All tests pass: `pytest packages/ai-parrot/tests/flows/ packages/ai-parrot/tests/knowledge/wiki/ packages/ai-parrot/tests/test_coding_agents.py -v`.
- [ ] AC-13 No breaking change to public APIs: every modified builder keeps its positional signature; the new `cwd` keyword defaults to `""`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

All paths below are relative to `packages/ai-parrot/src/parrot/flows/dev_loop/`
unless they start with `packages/`, `knowledge/`, `.agent/`, `.claude/` or are repo-root files.

### Verified Imports
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition   # verified: _subagent_defs.py:89, __all__ :117
from parrot.flows.dev_loop.agent_builder import build_dispatcher, DEFAULT_LLM_MAX_TURNS, ENV_LLM_MAX_TURNS  # verified: agent_builder.py:137, :134, :133
from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files   # verified: fidelity.py:49, :25; imported at engine.py:40
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, RosterSeat, TaskResult  # verified: sdd_coder/models.py:115, :23, :129
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile          # verified: models/llm.py:10
from parrot.flows.dev_loop.models.grok import GrokCodeDispatchProfile        # verified: models/grok.py (max_turns at :22)
from parrot.flows.dev_loop.models.codex import CodexCodeDispatchProfile      # verified: models/codex.py:10
from parrot.flows.dev_loop.models.google_coding import GoogleCodingDispatchProfile  # verified: models/google_coding.py:15
from parrot.flows.dev_loop.models.base import TaskScopedBrief                # verified: models/base.py:458
from parrot.knowledge.wiki.codex import assets                               # verified: knowledge/wiki/codex/assets.py (AGENTS_BEGIN :13)
from parrot.knowledge.wiki.google import assets                              # verified: knowledge/wiki/google/assets.py (AGENTS_BEGIN :15, GEMINI_PATH :17)
from importlib.resources import files                                        # verified: used at _subagent_defs.py:48/111
from parrot.knowledge.wiki import coding_agents                              # verified: knowledge/wiki/coding_agents.py; install() :89, _upsert :66, _markers :57, _AGENTS :43
# import cost, measured 2026-09-12 (python -X importtime): parrot 8.4 ms · parrot.flows 8.5 ms (docstring-only __init__) ·
# parrot.knowledge.wiki.coding_agents 10.8 ms · parrot.flows.dev_loop._subagent_defs 2 248 ms (eager dev_loop/__init__.py:11-25 imports every dispatcher)
```

### Existing Class Signatures
```python
# _subagent_defs.py
_VALID_NAMES: frozenset[str]                                   # line 50
def _strip_frontmatter(text: str) -> str                       # line 64 — reuse for rule files
def load_subagent_definition(name: str) -> str                 # line 89 — reads files("parrot.flows.dev_loop") / "_subagent_data" / f"{name}.md" (:111-113)
__all__ = ["load_subagent_definition"]                         # line 117

# dispatchers/llm.py
class LLMCodeDispatcher:                                       # line 51
    def _initial_messages(self, profile: LLMCodeDispatchProfile, brief: BaseModel, output_model: Type[BaseModel], *, cwd: str = "") -> List[Dict[str, Any]]  # line 891
        # body = load_subagent_definition(profile.subagent) at :899; system content ends with f"Subagent instructions:\n{body}" at :940
        # "Your budget is {profile.max_turns} turns" at :914 — reads the profile, no literal 24
    # call site: messages = self._initial_messages(profile, brief, output_model, cwd=cwd)   # line 275
    def _build_prompt(self, brief: BaseModel, output_model: Type[BaseModel]) -> str    # line 2362
    # dispatch.completed payload carries "max_turns": profile.max_turns                # line 840

# dispatchers/nova.py / google_compat.py — subclasses that INHERIT _initial_messages
class NovaCodeDispatcher(LLMCodeDispatcher)                    # nova.py:66
class GoogleCompatCodeDispatcher(LLMCodeDispatcher)            # google_compat.py:19

# dispatchers/codex.py
class CodexCodeDispatcher:                                     # line 43
    prompt = self._build_codex_prompt(profile, brief, output_model)                   # call site line 118 (inside dispatch, cwd in scope)
    def _build_command(self, *, profile, cwd, schema_path, output_path, prompt) -> List[str]  # line 240 — passes --cd cwd (:261-262), --ignore-rules only when profile.ignore_rules (:277)
    def _build_codex_prompt(self, profile: CodexCodeDispatchProfile, brief: BaseModel, output_model: Type[BaseModel]) -> str  # line 345
        # returns f"You are the `{profile.subagent}` dev-loop subagent.\n\nSubagent instructions:\n{body}\n\n{output_prompt}"  (:351-357)
    def _build_prompt(self, brief, output_model) -> str        # line 557

# dispatchers/google_coding.py
class GoogleCodingDispatcher:                                  # line 48
    prompt = self._build_agy_prompt(profile, brief, output_model)                     # call site line 171
    def _build_agy_prompt(self, profile: GoogleCodingDispatchProfile, brief: BaseModel, output_model: Type[BaseModel]) -> str  # line 317 (same shape as codex :323-329)
    def _build_prompt(self, brief, output_model) -> str        # line 331

# models/llm.py
class LLMCodeDispatchProfile(BaseModel):                       # line 10
    subagent: Literal["sdd-worker", "sdd-coder"] = "sdd-worker"    # line 18
    max_turns: int = Field(default=24, ge=1, le=100)           # line 23  ← M5 target
    allowed_commands: List[str]                                # line 53 — already contains "ruff" and "mypy"
# models/grok.py
class GrokCodeDispatchProfile(LLMCodeDispatchProfile):
    max_turns: int = Field(default=24, ge=1, le=100)           # line 22  ← M5 target
# models/codex.py
class CodexCodeDispatchProfile(BaseModel):                     # line 10
    ignore_user_config: bool = Field(default=True)             # line 23
    ignore_rules: bool = Field(default=False)                  # line 30 — AGENTS.md stays in effect for codex dispatches

# agent_builder.py
ENV_LLM_MAX_TURNS: str = "DEV_LOOP_LLM_MAX_TURNS"              # line 133
DEFAULT_LLM_MAX_TURNS: int = 60                                # line 134 — comment at :129 says "library default of 24" (update wording only)
def build_dispatcher(spec: DevAgentSpec, *, redis_url: str, max_concurrent: int, stream_ttl_seconds: int, config_getter=...) -> Tuple[DevLoopCodeDispatcher, BaseModel]  # line 137
    # nova (:257-263) and google-compat (:265-273) branches pass max_turns=llm_max_turns

# sdd_coder/engine.py
async def _git(*args: str, cwd: str) -> Tuple[int, str, str]  # line 69 — asyncio.create_subprocess_exec wrapper to mirror for ruff
class SddCoderEngine:
    __init__(..., dispatcher_builder: Callable[..., Any] = build_dispatcher, ...)   # line 156
    async def _consolidate(self, ctx, manager, task, *, branch, path) -> TaskResult  # line 337 — fidelity at :374 via check_fidelity(parse_task_files(task_md), diff lines)
    async def _run_attempt(self, ctx, task, seat, *, attempt, job_id) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]  # line 520
        # dispatcher, profile = self._dispatcher_builder(DevAgentSpec(agent=seat.backend, model=seat.model), ...)  :546
        # profile = profile.model_copy(update={"subagent": "sdd-coder"})  :552
        # output = await dispatcher.dispatch(brief=TaskScopedBrief(...), profile=profile, ..., cwd=path, session_host=collector, labels=...)  :553-578
        # except Exception → error = f"{type(exc).__name__}: {exc}"; collector.error = error  :579-586
        # return collector.record(), output, error, manager, branch, path  :587
    async def _run_task(self, ctx, task, seat, *, job_id) -> TaskResult   # line 588 — retry ladder: if err → self._assigner.retry_seat(seat.label, {seat.label}) → attempt 2

# sdd_coder/fidelity.py
class FidelityReport(BaseModel)                                # line 15
def parse_task_files(task_md: str) -> List[str]                # line 25
def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport   # line 49

# sdd_coder/models.py
class RosterSeat(BaseModel): label, kind, backend, model, fallback_model   # line 23-34 (no max_turns field)
class AttemptRecord(BaseModel): attempt, seat_label, backend, model, started_at, ended_at, duration_s, usage: Dict, error: str   # line 115-126

# knowledge/wiki/codex/assets.py
AGENTS_BEGIN = "<!-- parrot:wiki:codex:begin -->"; AGENTS_END   # lines 13-14
AGENTS_SECTION: str                                            # line 23
# knowledge/wiki/codex/installer.py
def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str   # line 17
def _remove_marker_block(text: str, begin: str, end: str) -> str               # line 31
def _install_agents(root: Path) -> str                         # line 77 — upserts AGENTS_SECTION into root / "AGENTS.md"
def install_codex_integration(...)                             # line 204
def uninstall_codex_integration(root: Path) -> list[str]       # line 235 — removes the wiki block at :243-249
# knowledge/wiki/google/assets.py
AGENTS_BEGIN = "<!-- parrot:wiki:google:begin -->"; AGENTS_END  # lines 15-16
GEMINI_PATH = Path("GEMINI.md")                                # line 17
GEMINI_SECTION: str                                            # line 31
# knowledge/wiki/google/installer.py
def _upsert_marker_block(...)  # line 18 ; def _remove_marker_block(...)  # line 32
def _install_gemini_md(root: Path) -> str                      # line 81
def install_google_integration(...)                            # line 214
def uninstall_google_integration(root, mcp_config_path=None) -> list[str]   # line 247 — GEMINI.md block removal at :258-268
# knowledge/wiki/coding_agents.py — a SEPARATE stdlib-only installer (`parrot wiki <agent> install`, cli.py:4643-4656)
_AGENTS = {"codex": ("AGENTS.md", ".codex/hooks.json", ...), "claude": ("CLAUDE.md", ...), "gemini": ("GEMINI.md", ...), "google": ("GEMINI.md", ...)}  # line 43
def _markers(agent: str) -> tuple[str, str]                    # line 57 — wiki markers; add _conventions_markers next to it
def _block(agent: str) -> str                                  # line 61
def _upsert(text: str, block: str, begin: str, end: str) -> str   # line 66 — idempotent marker upsert, reuse for the conventions block
def install(agent: str, root: Path = Path.cwd()) -> list[str]  # line 89 — instruction-file upsert at :97-100, skill at :101-104, hooks at :105-120
# tests/test_coding_agents.py — test_install_is_idempotent_and_preserves_settings (:9), test_codex_and_claude_emit_advisory_hook_responses (:27)
# tests/knowledge/wiki/ — NO existing test exercises _install_agents / _install_gemini_md / install_codex_integration / install_google_integration (grep 2026-09-12): M3 adds them
# parrot/flows/__init__.py — docstring only, no imports (verified) → safe home for a stdlib-only leaf module

# tests/flows/dev_loop/test_subagent_parity.py
_REPO_ROOT = Path(__file__).resolve().parents[5]               # line 20
def _repo_agents_dir() -> Path | None                          # line 29 — walk-up pattern to reuse for `.agent/rules`
def _package_prompts() -> list[str]                            # line 38
def test_prompt_parity(name)                                   # line 44

# tests/flows/dev_loop/test_llm_code_dispatcher.py
def test_budget_nudge_states_the_count_and_the_turn_economics()   # line 577
def test_system_prompt_names_the_working_directory(monkeypatch, brief, tmp_path)   # line 711 — calls dispatcher._initial_messages(..., cwd=...) at :714
# tests/flows/dev_loop/test_agent_builder.py
assert profile.max_turns == DEFAULT_LLM_MAX_TURNS == 60        # line 123 — must keep passing

# Repo-root files
# ruff.toml — [lint] select = ["E4", "E7", "E9", "F"] ; [lint.per-file-ignores] exists ; extend-exclude has ".claude/worktrees"
# packages/ai-parrot/pyproject.toml:906 — "parrot.flows.dev_loop" = ["_subagent_data/*.md"]   (glob does NOT cover a rules/ subdirectory)
# .agent/rules/ — python-development.md, cython-development.md, rust-development.md (byte-identical to .claude/rules/ twins, verified 2026-09-12) + 5 Antigravity persona files NOT in CODER_RULE_NAMES
# .claude/rules/ — the three coding rules + 4 worktree rules; Claude Code auto-loads every *.md here
# .claude/agents/sdd-coder.md:108 == _subagent_data/sdd-coder.md:108 — the single "Follow project conventions" line
# AGENTS.md — has the `parrot:wiki:codex` block; GEMINI.md — has only the `parrot:wiki:google` block
# .parrot/mcp-toolkits.yaml (git-ignored) — roster seats carry no max_turns; env/.env does NOT set DEV_LOOP_LLM_MAX_TURNS (checked 2026-09-12)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `load_project_conventions()` | `_strip_frontmatter()` | function call | `_subagent_defs.py:64` |
| `load_project_conventions()` | `files("parrot.flows.dev_loop") / "_subagent_data"` | importlib.resources | `_subagent_defs.py:111` |
| `_initial_messages()` | `load_project_conventions(cwd or None)` | string concat after `Subagent instructions:` | `llm.py:940` |
| `_build_codex_prompt(cwd=)` | call site in `dispatch()` | new kwarg | `codex.py:118` |
| `_build_agy_prompt(cwd=)` | call site in `dispatch()` | new kwarg | `google_coding.py:171` |
| `check_banned_imports()` | `SddCoderEngine._run_attempt()` | awaited after `dispatcher.dispatch()` returns | `engine.py:553-578` |
| `BannedImport:` attempt error | `_run_task()` retry ladder | non-empty `err` | `engine.py:588-616` |
| conventions marker block | `_install_agents()` / `_install_gemini_md()` | `_upsert_marker_block` | `codex/installer.py:77`, `google/installer.py:81` |
| `TID251` | `sdd-coder.md` step e) `ruff check` | existing behaviour | `_subagent_data/sdd-coder.md` "### e) Validate" |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/flows/conventions.py`~~, ~~`parrot.flows.conventions.load_project_conventions`~~ — created by M2; `_subagent_defs` only re-exports it.
- ~~`parrot/flows/_rules_data/`~~ — created by M1; no package-data entry for `parrot.flows` exists until M1 adds `"parrot.flows" = ["_rules_data/*.md"]`.
- ~~`coding_agents._conventions_markers` / `_conventions_block` / `_CONVENTIONS_AGENT`~~ — created by M3.
- ~~`coding_agents.uninstall()`~~ — does not exist (`coding_agents.py` has `install` :89 and `hook` :125 only); do not promise removal through it.
- ~~a `parrot:conventions:claude` block in `CLAUDE.md`~~ — deliberately NOT created (review R5).
- ~~a `parrot:conventions:gemini` marker~~ — never emitted; `gemini` canonicalises to `google` (review R4).
- ~~`tests/knowledge/wiki/test_codex_installer_conventions.py`~~, ~~`test_google_installer_conventions.py`~~ — created by M3.
- ~~`.agent/rules/codebase-conventions.md`~~, ~~`.claude/rules/codebase-conventions.md`~~ — created by M1.
- ~~`RosterSeat.max_turns`~~ — no per-seat turn budget exists (`sdd_coder/models.py:23-34`); do not add one.
- ~~`LLMCodeDispatchProfile.rules` / `.conventions` / `.extra_instructions`~~ — no profile field carries extra prompt text; injection happens in the builders.
- ~~`TaskScopedBrief.rules`~~ — the brief is `{research, task_id, task_file}` only (`models/base.py:458-478`).
- ~~`[tool.ruff]` in any `pyproject.toml`~~ — ruff config lives ONLY in the repo-root `ruff.toml`.
- ~~`fidelity.check_banned_imports`~~ — created by M4; `check_fidelity` is synchronous and pure, the new function is async because it spawns ruff.
- ~~`_subagent_defs.load_rules` / `load_rule`~~ — the helper is named `load_project_conventions`; do not invent aliases.
- ~~`CodexCodeDispatcher` reading `.codex/agents/sdd-worker.toml`~~ — the dispatcher embeds the prompt body itself; that toml is for interactive `codex` only.
- ~~`coding_agents.py` importing `parrot.flows.dev_loop.*`~~ — forbidden: it would add ~2.2 s to `parrot wiki <agent> install` and break the module's stdlib-only contract. Import `parrot.flows.conventions` only.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Dual-sourcing with byte parity** (`test_subagent_parity.py`): repo copy is the human-edited one, package copy is what dispatch reads from a wheel. Same for the rules.
- **Worktree copy wins**: `load_project_conventions(cwd)` reads the worktree's `.agent/rules/` first so a branch that changes a rule dispatches the changed text. `cwd` is always a full checkout (`engine.py:576` passes the sub-worktree path).
- **Inline, never "go read"**: for the in-process loop every file read is a turn; the conventions are pasted into the system message once.
- **Two gates, one check**: in `_run_attempt` a banned import is an attempt error so the retry ladder (`_run_task`) gives a different seat a shot; in `_consolidate` — the shared merge boundary that `merge()` also reaches for native tasks and re-merges — it is a `fidelity_violation`, so nothing with a banned import can merge no matter which entry point produced the branch (review R1).
- **Marker blocks are regenerated**: never hand-edit inside `parrot:conventions:*` markers; run the installer.
- Google-style docstrings, strict type hints, `self.logger`, async subprocess via `asyncio.create_subprocess_exec` (mirror `engine._git`).

### Known Risks / Gotchas
- **The 24 vs 60 discrepancy.** The MCP roster path builds profiles through `build_dispatcher`, which sets `max_turns=60` unless `DEV_LOOP_LLM_MAX_TURNS` overrides it; `env/.env` does not set it. A run that died at 35 turns against a 24 budget therefore came from a profile constructed directly (or from an env override in that session). M5 raises the library default as asked; §8 Q2 asks the operator to confirm which path the failing run used, because if it was the roster path the budget was 60 and the failure has another cause (`dispatch.completed` payload at `llm.py:840` records the effective `max_turns` — check the run bundle).
- **TID251 backlog.** 17 files import a banned module today; the grandfather list keeps `ruff check` at zero new findings, but any coder that touches one of those files will see zero TID251 findings there (whole-file ignore). Acceptable: the goal is new code. Never extend the list.
- **`banned-api` semantics.** Ruff's banned-api matches a module and its submodules; `langchain` does NOT cover the sibling top-level names `langchain_core`, `langchain_community`, `langgraph`. They must be listed explicitly (§8 Q4, default yes).
- **Prompt size.** ~2.5 K tokens more per dispatch for every in-process seat; the 12 000-byte cap in AC-3 is the guard. `max_tokens` (`models/llm.py:24`) is the output budget and is unaffected.
- **Codex reads `AGENTS.md` AND gets the inline block** — duplicated text is harmless and intentional (covers hand-launched sessions).
- **No shell in the in-process seats** (review R2): rule text that says `source …` is unexecutable there; the Tooling section's two-mode wording is the fix, and `python-development.md` is edited in step with it.
- **Pre-existing marker duplication in the wiki blocks**: `coding_agents._markers("gemini")` emits `parrot:wiki:gemini` while `google/assets.py` emits `parrot:wiki:google` in the same `GEMINI.md`. Out of scope here (the conventions markers avoid it by canonicalising), worth its own fix.
- **Import cost trap.** `parrot.flows.dev_loop` is an eager package (2.2 s); anything that must stay cheap (`coding_agents.py`, the parity tests, the `parrot wiki … install` CLI) imports `parrot.flows.conventions`, never `_subagent_defs`.
- **AGENTS.md prune is a hand edit inside a managed file**: the installers only touch text between their markers, so the prune is done once in M3 and guarded by `test_agents_md_has_no_stale_prose`.
- **Parity tests need the repo**: skip (not fail) when `.agent/rules/` is not found by the walk-up, exactly like `test_subagent_parity.py:48-52`.
- **`_upsert_marker_block` ordering**: upsert the conventions block after the wiki block so a fresh `AGENTS.md` reads wiki → conventions; re-running must not reorder.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ruff` | `0.16.3` (already in the venv) | `TID251` / `flake8-tidy-imports.banned-api` |

No new runtime dependency.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Q1 Prune the stale persona prose in `AGENTS.md` (Svelte/Capacitor, `isort`/`prettier`, the `@RTK.md` include)? — *Resolved by Jesus Lara, 2026-09-12*: **yes, prune it** — folded into §3 M3 and AC-6b. Narrowed by adversarial review R3: the `black` line is NOT stale (black is the active formatter) and is kept.
- [ ] Q2 Which path produced the 35-turn failure — a directly constructed profile (24) or the roster/`build_dispatcher` path (60)? Check `max_turns` in that run's `dispatch.completed` payload. If it was 60, M5 is still wanted but the failure needs its own ticket. — *Owner: Jesus Lara*
- [x] Q3 Should the stdlib-only `coding_agents.install()` path (`parrot wiki <agent> install`, `coding_agents.py:89`) also write the conventions block? — *Resolved by Jesus Lara, 2026-09-12*: **yes** — folded into §3 M3 (helper moved to the stdlib-only `parrot/flows/conventions.py` so the installer keeps its import contract) and AC-6/AC-14.
- [x] Q4 Ban `langchain_core` / `langchain_community` / `langgraph` explicitly in addition to `langchain`? — *Resolved by Jesus Lara, 2026-09-12*: **yes, nothing `langchain*` in the repo** — folded into §3 M4 (`langchain_core`, `langchain_community`, `langgraph`, `langsmith`) and AC-7.
- [ ] Q5 Language-aware trimming (skip `cython-development` / `rust-development` unless the task's file list has `.pyx`/`.pxd`/`.rs`) — deferred; revisit if AC-3 becomes hard to hold. — *Owner: implementation*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: **skipped (no accepted exploration document — this spec was written directly from the FEAT-549 enhancement discussion; no `.brainstorm.md` / `.proposal.md` exists for `sdd-coder-shared-conventions`)**
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Adversarial Review Cross-Check

> Independent adversarial review of spec v0.2 (2026-09-12, external reviewer; transcript
> `sdd/state/FEAT-553/adversarial_review_v0.2.md`). Every finding was re-verified against the
> tree before triage. Reviewer's own checks: the proposed TID251 configuration produced zero
> findings on `packages/` + `scripts/`; rule twins byte-identical (6 490 bytes, leaving 5 510
> for `codebase-conventions.md` under AC-3); both `max_turns` fields and the 60-turn wiring
> correctly identified.

| # | Finding | Disposition | Reason | Landed in |
|---|---|---|---|---|
| R1 | P1 — gate only in `_run_attempt`; `merge()` (`engine.py:407`) calls `_consolidate` (`:428`) directly for native tasks and re-merges | **CONFIRM** | verified: `_consolidate` has two call sites (`:428`, `:611`) | §3 M4 skeleton, AC-8b, §7 |
| R2 | P1 — mandatory `source .venv/bin/activate` is unexecutable for shell-free seats; worktrees have no `.venv` | **CONFIRM** | verified: `_tool_run_command` `llm.py:1713`, `_run_argv` `:1944`, `worktree_manager.py:146`; no `.claude/worktrees/*/.venv` on disk | §3 M1 Tooling (two modes) + `python-development.md` edit, AC-1b |
| R3 | P2 — spec bans `black` but `make format`/`make lint` run it | **CONFIRM → spec corrected (ban REJECTED)** | verified: `Makefile:399/404`, `pyproject.toml:67/237`, 17 "apply black" commits in the last 200. black is the formatter; only `isort`/`prettier` are stale | §1, §3 M1 item 2, M3 prune list, AC-1, AC-6b, Q1 |
| R4 | P2 — `gemini` vs `google` markers duplicate the block in `GEMINI.md` | **CONFIRM** | verified: `coding_agents._AGENTS` `:46-54` maps both to `GEMINI.md` | §3 M3 `_CONVENTIONS_AGENT`, new cross-installer test, AC-6 |
| R5 | P2 — Claude conventions block has no uninstall path | **CONFIRM → block dropped** | verified: `coding_agents.py` has only `install`/`hook`; `claude_code/installer.py:643` uninstaller exists but the block itself is unnecessary (Claude reads `.claude/rules/`) and would duplicate 10 KB per session | §3 M3, AC-6, §6 Does NOT Exist |
| R6 | P2 — M1 tests import the module M2 creates (cycle) | **CONFIRM** | `parrot/flows/conventions.py` moves to M1; M2 is injection + re-export | §3 delegation table, M1/M2 paths, §4 |
| R7 | P2 — stale-prose test forbids `black`/`isort` that the generated table contains | **CONFIRM** | test now inspects only text outside the marker pairs; `black` allowed | §4 row, AC-6b |

Summary: **7** confirmed (one of them, R3, by reversing the spec's own black ban) · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Default isolation unit**: per-spec — one worktree `feat-FEAT-553-sdd-coder-shared-conventions` from `origin/dev`.
- **Parallelism**: M1, M4 and M5 touch disjoint files and can run in parallel seats under the FEAT-549 orchestrator. M2 depends on M1 (package copy). M3 depends on M2 (helper). Suggested waves: {M1, M4, M5} → {M2} → {M3}.
- **Cross-feature dependencies**: FEAT-549 is merged on `dev` (PR #1368 lineage). None pending.
- **Dogfooding note**: the feature's own MCP seats will run WITHOUT the conventions until M2 merges; the task index should place M1 and M2 first so later tasks (M3) already benefit.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-12 | Jesus Lara | Initial draft — enhancement of FEAT-549 |
| 0.2 | 2026-09-12 | Jesus Lara | Q1/Q3/Q4 resolved: AGENTS.md prune, `coding_agents.install()` writes the block, full `langchain*` ban; helper moved to stdlib-only `parrot/flows/conventions.py` |
| 0.3 | 2026-09-12 | Jesus Lara | Adversarial review R1–R7 folded in (§10): gate at `_consolidate` too, two-mode Tooling rule, black ban reversed, gemini→google marker canonicalisation, no CLAUDE.md block, `conventions.py` owned by M1, stale-prose test scoped to unmanaged text |
