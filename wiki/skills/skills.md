---
title: "Skills system: discovery, toolkits and mixin"
summary: "How AI Parrot discovers file based skills (single file and composite SKILL.md), exposes them through two toolkits, and wires them into a bot with SkillRegistryMixin."
---

# Skills system: discovery, toolkits and mixin

## Purpose

Skills are lightweight, on-demand behavioral instructions an agent can load at
runtime. The system is two-tier: a static `<available_skills>` index is injected
into the system prompt, and the full skill body (plus any bundled assets) is
retrieved only when the model asks for it, or when the user types a
deterministic `/trigger` command.

There are two independent skill stores:

- **File based skills** — Markdown files with YAML frontmatter, held in a
  `SkillFileRegistry`. This is what `/trigger` commands, `load_skill` and
  `read_skill_asset` operate on.
- **DB backed skill registry** — a versioned, searchable `SkillRegistry`
  (namespace `{org_id}/{agent_id}`) that agents can write to with
  `document_skill` / `update_skill`.

`SkillRegistryMixin` ties both into an `AbstractBot`. Tenant specific skill
trees are an opt in layer on top of the file registry; they are documented in
[Per tenant skills](per-tenant-skills.md) and only summarized here.

Source root: `packages/ai-parrot/src/parrot/skills/`.

## Public API

Everything below is re-exported from [`parrot.skills`](ref:parrot.skills).

- [`parrot.skills.parsers`](ref:parrot.skills.parsers) — `parse_skill_file(file_path)` parses one `.md`
  file; `parse_skill_directory(skill_dir)` parses a composite skill and sets
  `assets_dir`; `discover_skills_in_dir(directory, logger, exclude_names)`
  scans one directory (non recursive) and is the shared discovery routine.
- [`parrot.skills.loader`](ref:parrot.skills.loader) — `SkillsDirectoryLoader(paths, logger=None)` with
  `await discover()` and `await load_into(registry) -> int`.
- [`parrot.skills.file_registry`](ref:parrot.skills.file_registry) — `SkillFileRegistry(skills_dir, learned_dir=None)`
  with `await load()`, `get(trigger)`, `get_by_name(name)`, `add(skill)`,
  `list_skills()` and `has_trigger(trigger)`.
- [`parrot.skills.tools`](ref:parrot.skills.tools) — `SkillFileToolkit`, `SkillRegistryToolkit` and the
  `create_skill_tools(...)` factory.
- [`parrot.skills.mixin`](ref:parrot.skills.mixin) — `SkillRegistryMixin` and `SkillRegistryHooks`.
- `parrot.skills.middleware` exposes `create_skill_trigger_middleware`, and
  `parrot.skills.prompt` exposes `render_skills_prompt_layer`; both are
  re-exported from [`parrot.skills`](ref:parrot.skills), along with the per tenant helpers
  (`SkillView`, `validate_tenant_id`, `current_skill_tenant`, ...).

### Skill layouts

`discover_skills_in_dir` recognises two layouts per directory:

| Layout | Path | Parsed by |
|---|---|---|
| Single file | `{dir}/{name}.md` | `parse_skill_file` |
| Composite | `{dir}/{name}/SKILL.md` plus adjacent files | `parse_skill_directory` |

A composite skill's `SkillDefinition.assets_dir` is the skill directory;
single file skills have `assets_dir = None`. Entries that are neither a `.md`
file nor a directory containing `SKILL.md` are silently skipped, and a
malformed skill is logged as a warning and skipped, so one bad file never
aborts discovery.

Frontmatter read by `parse_skill_file`: `name` and `description` are required
and `triggers` must be present (it may be an empty list, or a single string).
Optional keys: `source`, `version`, `category`, `priority` (default 90),
`global_only`, `suggestions`. The body must fit `SkillDefinition.MAX_TOKENS`
(1000 tokens), otherwise Pydantic validation fails.

### The two toolkits

`SkillFileToolkit(file_registry, learned_dir=None, max_asset_bytes=64 * 1024, *, view_provider=None)`
exposes, with tool names equal to method names:

- `list_skill_commands` — live listing of skills with descriptions and triggers.
- `load_skill(name)` — returns the skill body; metadata carries `assets` and
  `is_composite`.
- `read_skill_asset(skill_name, asset)` — sandboxed reader for a bundled
  asset; path traversal is rejected, `SKILL.md` is reserved for `load_skill`,
  and output is truncated at `max_asset_bytes`.
- `save_learned_skill(name, description, content, triggers, category)` —
  writes `{learned_dir}/{safe_name}.md` and hot adds it. Hidden when
  `learned_dir` is `None`.

`SkillRegistryToolkit(registry, agent_id, include_write_tools=True, *, registry_provider=None)`
exposes `search_skills`, `read_skill`, `list_skills` and, only when
`include_write_tools` is true, `document_skill` and `update_skill`.

### Factory

```python
def create_skill_tools(
    registry: SkillRegistry,
    agent_id: str,
    include_write_tools: bool = True,
    file_registry: Optional["SkillFileRegistry"] = None,
    learned_dir: Optional[Path] = None,
    *,
    view_provider: Optional[Callable[[], Any]] = None,
    registry_provider: Optional[Callable[[], Optional[SkillRegistry]]] = None,
) -> List[AbstractTool]
```

It always includes the `SkillRegistryToolkit` tools, and adds the
`SkillFileToolkit` tools only when `file_registry` is given.

## Configuration & Parameters

### Where the registry looks

`SkillFileRegistry` is eager: `load()` scans `skills_dir` (excluding the
`learned` subdirectory) and `learned_dir` (default `skills_dir / "learned"`).
It indexes skills by name and by trigger. Collisions are resolved by dropping:

- a name present in both authored and learned trees: both are skipped and an
  error is logged;
- a duplicate name: the later one is skipped;
- a trigger already registered: that trigger is skipped for the later skill.

### `SkillRegistryMixin` attributes

| Attribute | Default | Meaning |
|---|---|---|
| `enable_skill_registry` | `True` | Master switch for `_configure_skill_registry()`. |
| `skill_registry_expose_tools` | `True` | Register the DB registry tools via `create_skill_tools`. |
| `skill_registry_inject_context` | `True` | Inject relevant skills into context. |
| `skill_registry_auto_extract` | `False` | Auto extract skills from conversations (expensive). |
| `skill_registry_max_context_skills` | `3` | Context injection limit. |
| `skill_registry_max_context_tokens` | `1500` | Context injection token budget. |
| `skill_paths` | `[]` | Extra directories scanned by `SkillsDirectoryLoader`. |
| `inject_skills_into_prompt` | `True` | Install the `<available_skills>` prompt layer. |
| `skill_prompt_max_entries` | `None` | Cap on layer entries; `None` means all. |
| `tenant_based` | `False` | Opt in to per tenant skill trees. |
| `tenant_id` | `None` | Instance level default tenant (lowest precedence). |

`tenant_based` and `tenant_id` can also be passed as constructor keyword
arguments. The agents directory comes from `self._agents_dir` if set, else
`parrot.conf.AGENTS_DIR`.

### What `configure()` wires up

1. `_configure_skill_registry()` builds a DB `SkillRegistry` through
   `create_skill_registry` (namespace `{org_id}/{agent_id}`, persistence under
   `AGENTS_DIR/{agent_id}/skills`) and registers its tools.
2. `_configure_skill_file_registry()` creates
   `AGENTS_DIR/{agent_id}/skills/` and `skills/learned/` if missing, loads a
   `SkillFileRegistry`, and appends the `/trigger` middleware to
   `_prompt_pipeline` when one exists.
3. If `skill_paths` is non empty, a `SkillsDirectoryLoader` hot adds those
   skills into the same registry (a temporary directory backs the registry when
   no agents directory resolves).
4. The `<available_skills>` layer is installed into `_prompt_builder`.
5. A `SkillFileToolkit` is registered whenever a file registry exists, even an
   empty one, because `save_learned_skill` can add skills mid session.

### Per tenant skills

With `tenant_based = True`, each `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`
tree gets its own `SkillFileRegistry` and a `SkillView` that shadows the global
tree by name and trigger. The mixin passes `current_skill_view` as
`view_provider` (and `_current_store_registry` as `registry_provider`) so the
toolkits resolve the tenant per request. Tenant resolution order in
`_resolve_tenant` is: explicit argument, `RequestContext.kwargs["tenant"]`, the
bound ContextVar, then the instance `tenant_id`. Full behavior, layout and
reload semantics are in [Per tenant skills](per-tenant-skills.md).

## Usage Examples

A bot with an agents directory skill tree:

```python
from pathlib import Path

from parrot.bots.agent import Agent
from parrot.skills import SkillRegistryMixin


class SupportAgent(SkillRegistryMixin, Agent):
    enable_skill_registry = True
    skill_paths = [Path(".agent/skills/")]
    inject_skills_into_prompt = True
```

A composite skill on disk (`triggers` may be empty; the model then reaches it
through `load_skill`):

```text
skills/
├── resumen.md                 # single file skill
└── report_builder/            # composite skill
    ├── SKILL.md
    └── template.md            # read via read_skill_asset
```

```markdown
---
name: report_builder
description: Build a weekly report from a bundled template.
triggers:
  - /report
category: workflow
---

Load the bundled template with read_skill_asset, then fill it in.
```

Using the discovery pieces directly, without a bot:

```python
import asyncio
from pathlib import Path

from parrot.skills import SkillFileRegistry, SkillsDirectoryLoader, SkillFileToolkit


async def main() -> None:
    registry = SkillFileRegistry(skills_dir=Path("skills"))
    await registry.load()

    loader = SkillsDirectoryLoader(paths=[Path(".agent/skills/")])
    count = await loader.load_into(registry)
    print(f"hot added {count} skills")

    toolkit = SkillFileToolkit(
        file_registry=registry,
        learned_dir=registry.learned_dir,
    )
    for tool in toolkit.get_tools():
        print(tool.name)


asyncio.run(main())
```

Building the full tool list with the factory:

```python
from pathlib import Path

from parrot.skills import SkillFileRegistry, create_skill_registry, create_skill_tools

registry = create_skill_registry(namespace="my_org/my_agent")
# await registry.configure() before use
file_registry = SkillFileRegistry(skills_dir=Path("skills"))

tools = create_skill_tools(
    registry=registry,
    agent_id="my_agent",
    include_write_tools=False,
    file_registry=file_registry,
    learned_dir=None,  # hides save_learned_skill
)
```

## Gotchas

- **`triggers` must exist.** A skill whose frontmatter lacks the `triggers` key
  fails to parse and is skipped with a warning; use `triggers: []` for a skill
  reachable only through `load_skill`.
- **Name collisions drop both skills.** If an authored and a learned skill
  share a name, `SkillFileRegistry.load()` logs an error and registers neither.
- **`SkillFileToolkit.save_learned_skill` rejects collisions** on name or
  trigger instead of overwriting.
- **The `learned` directory is reserved.** It is excluded from authored
  discovery so it is not parsed as a composite skill. In tenant trees it is
  ignored with a warning, since learned skills are global.
- **Discovery is non recursive.** Only direct children of each directory are
  considered; nested folders without `SKILL.md` are ignored.
- **`read_skill_asset` only works on composite skills,** and never returns
  `SKILL.md`; large assets are truncated at 64 KiB by default.
- **Tenant arguments are ignored when `tenant_based` is `False`.** The mixin
  logs once at debug level and uses the global view.
- **Unknown tenants fall back to the global view** with a single warning per
  tenant.
- The tool names (`load_skill`, `read_skill_asset`, ...) are referenced by the
  `<available_skills>` prompt layer; no `tool_prefix` is applied, so do not
  rename the methods in subclasses.

## Related

- [Per tenant skills](per-tenant-skills.md) — tenant trees, shadowing rules, reloads and request scoping.
- [`parrot.skills`](ref:parrot.skills) — generated API reference for the package.
