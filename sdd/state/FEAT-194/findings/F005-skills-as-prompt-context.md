---
id: F005
queries: [Q013, Q014, Q015, Q016, Q021, Q026]
confidence: high
---

# Skills are prompt-level instructions (FEAT-188 shipped), not OutputModes or tools

A `SkillDefinition` (skills/models.py:53-84) is a parsed markdown file
with YAML frontmatter. Fields:

```
name, description, triggers (List[str]),
source (authored | learned), priority (default 90),
version, category, template_body, token_count, file_path,
assets_dir (Optional[Path] for composite skills with non-md assets)
```

Hard token limit: `MAX_TOKENS = 1000` (line 74) enforced by validator.
Skills are NOT tools; they are NOT OutputModes; they are
**prompt-injected behavioural instructions** scoped to specific triggers.

## How a Skill activates (FEAT-188 design)

`SkillRegistryMixin` (skills/mixin.py) ships **three** complementary
activation channels:

| Channel                                  | Decider | Latency      | Use case                  |
|------------------------------------------|---------|--------------|---------------------------|
| `/trigger` middleware                    | User    | 0 LLM calls  | Power-user slash commands |
| Tier 1: `<available_skills>` prompt layer| LLM     | 0 extra calls| Static index in sys prompt|
| Tier 2: `LoadSkillTool`                  | LLM     | +1 tool call | On-demand body retrieval  |
| `SearchSkillsTool` (DB-backed)           | LLM     | +1 search +1 | Skills beyond prompt budget|

At `configure()` time:
- Skills are discovered from `skill_paths: List[Path]` (default empty —
  opt-in; recommended `.agent/skills/`) via `SkillsDirectoryLoader`.
- An `<available_skills>` XML block is rendered (`render_skills_prompt_layer`)
  and inserted into the system prompt via `_prompt_builder.add(layer)` —
  zero per-turn cost.
- `LoadSkillTool` is registered on the `ToolManager` so the LLM can pull
  full skill bodies on demand.
- For user-triggered patterns, `SkillTriggerMiddleware` is added to the
  prompt pipeline (`_prompt_pipeline`) and short-circuits with the skill
  body when a trigger matches.

## Implications for FEAT-194

- A "finance-infographic" Skill is **just a `.md` file** with frontmatter:
  `triggers: ["/finance-dashboard"]`, `category`, and a `template_body`
  ≤ 1000 tokens describing (a) which data the LLM should fetch via tools
  and (b) which infographic template name to use (e.g. `"dashboard"` or
  a custom registered one).
- Skills cannot themselves render HTML — that remains the renderer's job.
- Skills cannot themselves expose datasets back to the caller — that is
  separate from skill activation.

Recent git log on the namespace:
- `87c49a69 feat(skill-registry): TASK-1294 — Mixin Wiring`
- `6010c29c TASK-1293 — LoadSkillTool — Tier 2 On-Demand Retrieval`
- `1393f9d8 TASK-1292 — Skills Prompt Layer Factory`
- `99433eac TASK-1291 — SkillsDirectoryLoader`
- `ed6c6f02 TASK-1287 — Namespace Promotion (parrot.memory.skills →
  parrot.skills)`

## Citations
- packages/ai-parrot/src/parrot/skills/models.py:53-84 — SkillDefinition
- packages/ai-parrot/src/parrot/skills/mixin.py:139-249 —
  `_configure_skill_file_registry()` (FEAT-188 extensions)
- packages/ai-parrot/src/parrot/skills/mixin.py:216-232 — prompt layer
  injection at configure() time
- packages/ai-parrot/src/parrot/skills/mixin.py:234-248 — LoadSkillTool
  registration
- sdd/specs/skill-registry.spec.md:1-78 — FEAT-188 spec overview (status:
  approved, base_branch: dev)
