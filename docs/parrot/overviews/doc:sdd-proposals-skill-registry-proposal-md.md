---
type: Wiki Overview
title: 'FEAT-XXX: Skills Directory Loader + PromptBuilder Integration'
id: doc:sdd-proposals-skill-registry-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The `parrot.memory.skills` module already exposes a mature filesystem-backed
  skill subsystem:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.memory.skills
  rel: mentions
- concept: mod:parrot.memory.skills.parsers
  rel: mentions
- concept: mod:parrot.memory.skills.tools
  rel: mentions
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.skills.loader
  rel: mentions
---

# FEAT-XXX: Skills Directory Loader + PromptBuilder Integration

**Status:** Brainstorm v0.1
**Author:** jesus (assisted by Claude)
**Depends on:** existing `parrot.memory.skills` module
**Related:** FEAT-069 (IntentRouter), EpisodicMemory v2

---

## 1. Motivation

The `parrot.memory.skills` module already exposes a mature filesystem-backed skill subsystem:

- `SkillFileRegistry` — hot-loadable in-memory store of file-based skills
- `parse_skill_file` — YAML frontmatter parser
- `SaveLearnedSkillTool` — agent self-documentation writes `.md` files with frontmatter
- `create_skill_trigger_middleware` — deterministic `/comando` dispatch
- `SearchSkillsTool` / `ReadSkillTool` — embedding-based RAG over the versioned `SkillRegistry` (git-like DB store)

**What's missing** is the Anthropic Claude Code "skills directory" activation pattern: user-authored skills auto-discovered from a configured path (`.agent/skills/`), surfaced to the LLM as a description index in the system prompt (**Tier 1**), and lazy-loaded on demand by an LLM-initiated tool call (**Tier 2**). This complements — does not replace — the three existing activation mechanisms:

| Mechanism                                  | Decider | Latency               | Use case                       |
| ------------------------------------------ | ------- | --------------------- | ------------------------------ |
| `/trigger` middleware                      | User    | 0 LLM calls           | Power-user slash commands      |
| **Description index + `LoadSkillTool`** ⬅ NEW | LLM     | +1 tool call          | Contextual, discovery-time     |
| `SearchSkillsTool` (existing)              | LLM     | +1 search +1 load     | Skills beyond prompt budget    |

The three coexist; the LLM picks the cheapest path naturally if Tier 1 surfaces a hit.

---

## 2. Confirmed design decisions

| #  | Decision                                                                                                                              |
| -- | ------------------------------------------------------------------------------------------------------------------------------------- |
| D1 | Directory layout: `.agent/skills/{SKILL}/SKILL.md` (composite). Loader **also** accepts `.agent/skills/{SKILL}.md` (single-file).      |
| D2 | Injection mechanism: a new layer in `PromptBuilder` (not ad-hoc concatenation inside the mixin).                                       |
| D3 | Tier 2 is a NEW tool — `LoadSkillTool` — distinct from `ReadSkillTool` (which targets the versioned `SkillRegistry`).                  |
| D4 | Both single-file AND directory-based skills are supported in the same loader. Detection by filesystem inspection.                      |

---

## 3. Codebase contract

### ✅ Verified to exist

From inspection of `parrot/memory/skills/__init__.py` and `parrot/memory/skills/tools.py`:

- `parrot.memory.skills.SkillFileRegistry`
  - `.list_skills() -> list[Skill]` (used in `SaveLearnedSkillTool`)
  - `.has_trigger(trigger: str) -> bool`
  - `.add(skill: Skill) -> None` (hot-add)
- `parrot.memory.skills.parse_skill_file(path: Path) -> Skill`
- `parrot.memory.skills.SkillMetadata` — Pydantic model with fields `name`, `description`, `category`, `tags`, `triggers` (confirmed via usage in `SearchSkillsTool._format_summary`)
- `parrot.memory.skills.SkillRegistryMixin` — exported, hooks via `SkillRegistryHooks`
- Existing frontmatter schema:
  ```yaml
  ---
  name: <str>
  description: <str>
  triggers:
    - <str>
  source: learned | authored
  category: <str>
  ---
  ```

### ❎ Needs to be built

- `parrot.skills.loader.SkillsDirectoryLoader`
- `parrot.memory.skills.parsers.parse_skill_directory` (companion to `parse_skill_file`)
- `parrot.memory.skills.tools.LoadSkillTool`
- `parrot.prompt.layers.SkillsPromptLayer`
- `Skill.assets_dir: Path | None` field (composite-skill marker)

### ⚠ Needs verification before `/sdd-spec`

- [ ] `PromptBuilder` API: confirm there's a registerable "layer" / "section" mechanism. If not, this is a bigger architectural change. Expected signature: `prompt_builder.register_layer(layer: AbstractPromptLayer) -> None`.
- [ ] `SkillRegistryMixin.configure()` lifecycle — confirm hook signature and where `self._skill_file_registry` is initialized.
- [ ] Full field list of `Skill` and `SkillMetadata` in `parrot/memory/skills/models.py` — confirm `content` field name (used in `LoadSkillTool` draft below).
- [ ] `SkillFileRegistry.get_by_name(name: str) -> Skill | None` — needed by `LoadSkillTool`. If absent, add it or use `.list_skills()` + filter.
- [ ] `AbstractPromptLayer` base class location (assumed `parrot.prompt.layers.abstract`).
- [ ] How tools are registered on the bot in current Mixin pattern (`self._tools.add(...)`? `self.add_tool(...)`?).

---

## 4. Architecture

### 4.1 Module layout

Pending Open Q1, two viable placements:

**Option A — stay under `parrot.memory.skills`:**

```
parrot/memory/skills/
├── __init__.py            # existing — add new exports
├── models.py              # existing — add Skill.assets_dir
├── parsers.py             # existing — add parse_skill_directory
├── file_registry.py       # existing — maybe add get_by_name
├── store.py               # existing (git-like SkillRegistry, untouched)
├── tools.py               # existing — add LoadSkillTool
├── mixin.py               # existing — wire loader + prompt layer
├── middleware.py          # existing (/trigger, untouched)
└── loader.py              # NEW — SkillsDirectoryLoader
```

**Option B — promote to `parrot.skills`:**

`parrot/skills/` becomes the top-level capability; `parrot.memory.skills` re-exports for backward compatibility, eventually deprecated. Aligns with future `IntentRouter` and routing-related code. See Open Q1.

### 4.2 SkillsDirectoryLoader

```python
# parrot/memory/skills/loader.py  (or parrot/skills/loader.py per Q1)
from pathlib import Path
from logging import Logger

from .parsers import parse_skill_file, parse_skill_directory
from .file_registry import SkillFileRegistry
from .models import Skill


class SkillsDirectoryLoader:
    """
    Discovers skills from one or more filesystem paths.

    Accepts two layouts within the same parent directory:
      - {dir}/{skill_name}.md         → single-file skill
      - {dir}/{skill_name}/SKILL.md   → composite skill (with adjacent assets)

    Collision policy: delegated to SkillFileRegistry. Loader logs warnings
    on parse failure and continues; never crashes boot.
    """

    def __init__(
        self,
        paths: list[Path],
        logger: Logger | None = None,
    ):
        self._paths = [Path(p).expanduser().resolve() for p in paths]
        self._logger = logger

    async def discover(self) -> list[Skill]:
        skills: list[Skill] = []
        for base in self._paths:
            if not base.exists() or not base.is_dir():
                if self._logger:
                    self._logger.debug(f"Skills path not found: {base}")
                continue

            for entry in base.iterdir():
                try:
                    if entry.is_file() and entry.suffix == ".md":
                        skills.append(parse_skill_file(entry))
                    elif entry.is_dir() and (entry / "SKILL.md").exists():
                        skills.append(parse_skill_directory(entry))
                except Exception as e:
                    if self._logger:
                        self._logger.warning(
                            f"Failed to parse skill at {entry}: {e}"
                        )
        return skills

    async def load_into(self, registry: SkillFileRegistry) -> int:
        skills = await self.discover()
        loaded = 0
        for s in skills:
            try:
                registry.add(s)
                loaded += 1
            except Exception as e:
                if self._logger:
                    self._logger.warning(
                        f"Failed to register skill {s.metadata.name}: {e}"
                    )
        return loaded
```

### 4.3 parse_skill_directory

Drop-in companion to `parse_skill_file`. Reuses the same frontmatter parser, then attaches `assets_dir` for downstream tools.

```python
# parrot/memory/skills/parsers.py  (extension)
def parse_skill_directory(skill_dir: Path) -> Skill:
    """
    Parse a composite skill: {dir}/SKILL.md plus arbitrary adjacent files.
    The body of SKILL.md may reference siblings (scripts, examples, templates).
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"Missing SKILL.md in composite skill: {skill_dir}")

    skill = parse_skill_file(skill_md)
    skill.assets_dir = skill_dir  # ← new field on Skill model
    return skill
```

Required model change in `models.py`:
```python
class Skill(BaseModel):
    # ... existing fields ...
    assets_dir: Path | None = Field(
        default=None,
        description="Filesystem dir for composite skills; None for single-file."
    )
```

### 4.4 LoadSkillTool

Tier 2 — returns the full body + a manifest of available assets. Asset *content* is NOT eagerly inlined (would defeat the purpose of lazy load). The LLM can request specific assets via a follow-up `LoadSkillAsset` tool — deferred to v2 per Open Q2.

```python
# parrot/memory/skills/tools.py  (addition)
from typing import Type
from pydantic import BaseModel, Field

from ...tools.abstract import AbstractTool, ToolResult
from .file_registry import SkillFileRegistry


class LoadSkillArgs(BaseModel):
    name: str = Field(
        ...,
        description="Skill name as listed in <available_skills>."
    )


class LoadSkillTool(AbstractTool):
    """
    Load the full content of a skill discovered in the agent's skills directory.

    Use after seeing a relevant skill in the <available_skills> block of the
    system prompt. Returns the skill body and, for composite skills, a
    manifest of adjacent asset filenames.
    """

    name: str = "load_skill"
    description: str = (
        "Load the full content of a skill from the agent's skills directory. "
        "Use after spotting a relevant skill in <available_skills>."
    )
    args_schema: Type[BaseModel] = LoadSkillArgs

    def __init__(self, file_registry: SkillFileRegistry, **kwargs):
        super().__init__(**kwargs)
        self._registry = file_registry

    async def _execute(self, name: str, **kwargs) -> ToolResult:
        # ⚠ Confirm SkillFileRegistry has get_by_name; otherwise filter list_skills()
        skill = self._registry.get_by_name(name)
        if not skill:
            return ToolResult(
                status="error",
                error=f"Skill not found: {name}",
            )

        # Build asset manifest for composite skills
        assets: list[str] = []
        if skill.assets_dir:
            for p in skill.assets_dir.rglob("*"):
                if p.is_file() and p.name != "SKILL.md":
                    assets.append(str(p.relative_to(skill.assets_dir)))

        return ToolResult(
            status="done",
            result=skill.content,  # ⚠ confirm field name
            metadata={
                "skill_name": name,
                "category": skill.metadata.category,
                "assets": assets,
                "is_composite": skill.assets_dir is not None,
            },
        )
```

### 4.5 SkillsPromptLayer

Tier 1 — resolved ONCE at `bot.configure()` via the two-phase prompt rendering pattern (`partial_render`). Zero per-turn cost beyond the persistent tokens in the system prompt.

```python
# parrot/prompt/layers/skills.py
from ..abstract import AbstractPromptLayer  # ⚠ verify location/base class
from ...memory.skills.file_registry import SkillFileRegistry


class SkillsPromptLayer(AbstractPromptLayer):
    """
    Injects an <available_skills> XML block listing every discovered skill's
    name + description. Static layer — rendered once at configure() and frozen
    into the system prompt via partial_render.

    Honors the project principle: XML owns structure, Markdown owns content.
    """

    name = "available_skills"

    def __init__(
        self,
        file_registry: SkillFileRegistry,
        max_skills: int | None = None,
    ):
        self._registry = file_registry
        self._max = max_skills

    def render(self) -> str:
        skills = self._registry.list_skills()
        if not skills:
            return ""

        # If above budget, future hook for IntentRouter (FEAT-069) top-K filtering.
        # For now: truncate (alphabetical or insertion order — TBD).
        if self._max and len(skills) > self._max:
            skills = skills[: self._max]

        lines = ["<available_skills>"]
        for s in skills:
            trigger_hint = ""
            if s.metadata.triggers:
                trigger_hint = (
                    f"\n    Also triggerable via: {', '.join(s.metadata.triggers)}"
                )
            lines.append(f'  <skill name="{s.metadata.name}">')
            lines.append(f"    {s.metadata.description}")
            lines.append(f'    Load with: load_skill(name="{s.metadata.name}"){trigger_hint}')
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)
```

### 4.6 Mixin wiring

```python
# parrot/memory/skills/mixin.py  (extension)
class SkillRegistryMixin:
    # Existing config flags...
    enable_skill_registry: bool = True

    # NEW config flags
    skill_paths: list[Path] = []
    enable_skill_discovery: bool = True
    inject_skills_into_prompt: bool = True
    skill_prompt_max_entries: int | None = None  # None = inject all

    async def configure(self, *args, **kwargs):
        await super().configure(*args, **kwargs)

        if not (self.enable_skill_discovery and self.skill_paths):
            return

        # Discovery + filesystem-registry population
        loader = SkillsDirectoryLoader(self.skill_paths, logger=self.logger)
        loaded = await loader.load_into(self._skill_file_registry)
        self.logger.info(
            f"Loaded {loaded} skills from {[str(p) for p in self.skill_paths]}"
        )

        # Tier 1: prompt injection
        if self.inject_skills_into_prompt:
            layer = SkillsPromptLayer(
                self._skill_file_registry,
                max_skills=self.skill_prompt_max_entries,
            )
            self._prompt_builder.register_layer(layer)  # ⚠ verify API

        # Tier 2: tool registration
        self._tools.add(  # ⚠ verify tool-registration API
            LoadSkillTool(file_registry=self._skill_file_registry)
        )
```

---

## 5. Latency budget

Per the *latency is first-class* principle:

| Phase                          | Cost                                | Frequency             |
| ------------------------------ | ----------------------------------- | --------------------- |
| Directory scan                 | O(n) filesystem I/O                 | Once at boot          |
| Frontmatter parse              | O(n) YAML parse                     | Once at boot          |
| `SkillsPromptLayer.render()`   | O(n) string concat                  | Once at configure()   |
| Description index in context   | ~50–80 tokens/skill (persistent)    | Every LLM turn        |
| `load_skill(...)` invocation   | +1 round-trip                       | Per skill activation  |

**Token red line:** at ~70 tokens/skill, 100 skills ≈ 7,000 tokens persistent in the system prompt. The empirical sweet spot is likely 20–40 skills surfaced. Beyond that, `skill_prompt_max_entries` truncates, and the proper long-term answer is embedding pre-filtering via `IntentRouter` (FEAT-069). The integration point is `SkillsPromptLayer.render()` — swap the truncation block for a router call.

---

## 6. Open questions

### Q1 — Module location: `parrot.memory.skills` vs `parrot.skills`

Skills today live under `parrot.memory.skills`, but they aren't *learned state* in the sense that EpisodicMemory or BrainService are. Authored skills are closer to **prompts/capabilities** than to memory. As routing grows (Tier 1 + IntentRouter + embedding pre-filter), the `memory.` namespace becomes misleading.

**Recommendation:** promote to `parrot.skills` as a top-level capability. Keep `parrot.memory.skills` as a deprecation-warning re-export for one or two minor versions. The `SkillRegistry` (git-like versioned store) stays where it is OR moves alongside — TBD by where its consumers live.

### Q2 — Asset access for composite skills

When `LoadSkillTool` reports `assets: ["scripts/extract.py", "examples/sample.csv"]`, how does the agent retrieve those?

**Recommendation:** v1 ships with the manifest only. The body of `SKILL.md` instructs the agent on how to use named assets — most often, asset references resolve via tools the agent already has (e.g., a Python REPL tool reads `scripts/extract.py` from disk). A dedicated `LoadSkillAssetTool(skill_name, asset_path)` lands in v2 if usage data shows it's needed.

### Q3 — Frontmatter for composites: implicit vs explicit asset declaration

Two options for letting `SKILL.md` describe its sibling files:

```yaml
# Option A — implicit (filesystem inspection)
---
name: extract-pdf-tables
description: ...
---
# Option B — explicit allowlist
---
name: extract-pdf-tables
description: ...
assets:
  - scripts/extract.py: "Camelot-based extractor"
  - examples/sample.pdf: "Reference input"
---
```

**Recommendation:** A is default. Add B as optional in v1.1 once a real use case demands per-asset descriptions.

### Q4 — Interaction with `/trigger` middleware

A discovered skill declaring `triggers: [/resumen]` is activated by the middleware deterministically. Should it ALSO appear in `<available_skills>` for the LLM to pick up contextually?

**Recommendation:** yes. The description includes an *"Also triggerable via /resumen"* hint (already in the layer code above). Lets the agent volunteer the skill when context fits, even if the user didn't type the slash command.

### Q5 — Hot reload

Dev workflow benefits from picking up `.md` edits without restarting the agent.

**Recommendation:** out of scope for v1. Add `SkillRegistryMixin.reload_skills() -> int` as a manual API now; a `watchdog`-based watcher is a clean future addition.

### Q6 — Where do `SaveLearnedSkillTool` outputs go?

Currently writes to a `learned_dir` injected at construction. With directory-discovery, learned skills naturally belong in a `learned/` subdir of one of the configured `skill_paths` (so they're auto-rediscovered on next boot).

**Recommendation:** make the existing `learned_dir` default to `skill_paths[0] / "learned/"` when unset; preserve override for explicit configurations.

---

## 7. Acceptance criteria

- [ ] `SkillsDirectoryLoader` discovers both `*.md` and `*/SKILL.md` from each configured path.
- [ ] Failed parses log warnings; boot continues.
- [ ] `<available_skills>` block appears in the system prompt after `configure()` when `inject_skills_into_prompt=True`.
- [ ] `LoadSkillTool` returns body + asset manifest for composite skills; returns body only for single-file skills.
- [ ] Existing `SaveLearnedSkillTool` outputs land in a discoverable subdir of `skill_paths`.
- [ ] Skills declaring `triggers:` remain functional via `/trigger` middleware AND surface in `<available_skills>` with the trigger hint.
- [ ] Zero measurable latency added to turns that don't invoke `load_skill` (description block is static, resolved once).
- [ ] Backward compatibility: existing usage of `SkillFileRegistry` and the trigger middleware unaffected.

---

## 8. Out of scope (future FEATs)

- Embedding-based top-K filtering of the description index (→ FEAT-069 `IntentRouter`).
- Bidirectional sync between `SkillFileRegistry` (filesystem) and `SkillRegistry` (versioned DB) — automatic promotion of stable/successful skills.
- Skill package distribution / install-from-URL (npm-style).
- `watchdog`-based filesystem hot-reload.
- `LoadSkillAssetTool` for granular asset retrieval.
- Frontmatter schema validation via JSON Schema export (for IDE integration).

---

## 9. Pre-`/sdd-spec` checklist

Before promoting this to a spec, resolve:

1. **Verify `PromptBuilder` exposes a layer/section registration API.** If not, scope expands to include that API itself.
2. **Verify `Skill` model field name** for body content (`content`? `body`? `text`?) and add `assets_dir`.
3. **Verify `SkillFileRegistry.get_by_name`** exists, or add it.
4. **Verify tool-registration API** inside the mixin (`self._tools.add` vs `self.add_tool` vs something else).
5. **Decide Q1** (module location) — affects all import paths in the spec.
6. **Decide on default `skill_paths`** — opinionated default (e.g. `[Path(".agent/skills/")]`) or empty by default and require explicit opt-in?