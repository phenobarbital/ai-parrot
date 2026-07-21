# Identity Capability User Guide

The **identity capability** (FEAT-321) lets an agent author its five
composable identity fields — `role`, `goal`, `capabilities`, `backstory`,
`rationale` — as separate, human-editable Markdown files instead of one giant
inline Python string. It also fixes a long-standing gap in the composable
prompt path: `capabilities` used to be silently dropped for non-RAG agents.

Two independent adoption paths ship together:

- **`IdentityMixin`** — file loading, field injection, and hot reload.
- **The `"identity"` preset** — just the `capabilities` rendering, for
  builder-savvy agents that don't want file loading.

See also: [PromptBuilder User Guide](promptbuilder.md) and the
[Layers Reference](layers-reference.md).

---

## The `identity/` directory convention

Create an `identity/` directory next to your agent's module with any subset
of the five files:

```
agents/my_agent/
├── my_agent.py
└── identity/
    ├── role.md
    ├── goal.md
    ├── capabilities.md
    ├── backstory.md
    └── rationale.md
```

Each file is plain Markdown, read verbatim (UTF-8, stripped of leading/
trailing whitespace). A missing file, an empty file, or a whitespace-only
file all resolve that field to `None` **silently** — no error, no warning
(only a debug log entry) — exactly like the existing
`load_agent_context()` whole-blob convention. You only need to author the
files that matter for your agent; the rest fall through to the class
attribute or package default.

---

## Adopting `IdentityMixin`

```python
from parrot.bots.mixins import IdentityMixin

class MyAgent(IdentityMixin, SomeAgentBase):
    enable_identity: bool = True
    # identity_dir defaults to <dir of this module file>/identity;
    # set it explicitly when your agent module and its identity/ directory
    # are not siblings (see the Porygon example below).

    async def configure(self, app=None):
        await super().configure(app)
        await self._configure_identity()
```

Two things to get right:

1. **`IdentityMixin` must be the first base class** — its `__init__` and
   `_build_prompt` override need to run before the agent base class's, and
   delegate to it via `super()`.
2. **Call `await self._configure_identity()` explicitly** in your agent's own
   `configure()`, after `await super().configure(...)` — mirroring the
   existing `SkillRegistryMixin` / `EpisodicMemoryMixin` pattern. The mixin
   does **not** override `configure()`.

### `identity_dir` resolution

By default, `identity_dir` resolves to
`Path(inspect.getfile(type(self))).parent / "identity"` — i.e. an `identity/`
directory living **next to your agent's module file**. When your agent is a
top-level module file with a separate assets directory (rather than a
package directory), set `identity_dir` explicitly. Porygon
(`agents/porygon.py`) is the reference example: its assets live in
`agents/porygon/`, so the default (`agents/identity`) would be wrong:

```python
class Porygon(IdentityMixin, SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent):
    enable_identity: bool = True
    identity_dir = Path(__file__).parent / "porygon" / "identity"
```

---

## The `"identity"` preset (no mixin required)

If you only need `capabilities` rendering — without file loading or hot
reload — adopt the preset directly via the existing `prompt_preset` kwarg:

```python
agent = MyAgent(prompt_preset="identity", capabilities="- Can search\n- Can summarize")
```

`get_preset("identity")` returns the `default()` stack plus
`CAPABILITIES_LAYER` — a fresh `PromptBuilder` instance per call, just like
every other preset. It does not touch `IDENTITY_LAYER` or
`PromptBuilder.default()`; non-adopters are unaffected.

---

## Resolution precedence

Both paths honor the same precedence chain used everywhere else in
`AbstractBot`:

```
explicit kwarg  >  file value  >  class attribute  >  package default
```

`IdentityMixin` injects non-empty file values as instance attributes
**before** `super().__init__()` runs, so `AbstractBot`'s existing
`kwargs.get(f) or getattr(self, f, None) or DEFAULT` resolution
(`abstract.py:432-452`) picks up the file value whenever no explicit kwarg
was passed, while a kwarg still wins and a file value still beats a class
attribute default.

> **`PandasAgent` note**: `PandasAgent.__init__` declares its own
> `capabilities` parameter and stores it as `self._capabilities` instead of
> `self.capabilities` (`data.py:550,586`), which would otherwise bypass the
> usual kwarg resolution for that one field on `PandasAgent`-derived agents.
> `IdentityMixin` captures the caller's original `capabilities=` kwarg
> *before* `super().__init__()` runs (i.e. before `PandasAgent`'s signature
> can swallow it) and re-applies that exact value to `self.capabilities`
> afterwards — so an explicit kwarg still wins over a file value on
> `PandasAgent` subclasses too, restoring the same precedence as every other
> field.

---

## Hot reload

Editing any `identity/*.md` file takes effect on the **next system-prompt
build** — no agent restart required. The mixin re-checks file mtimes
(near-free, backed by the same mtime-keyed LRU cache used by
`load_agent_context`) on every call and only rebuilds the prompt builder when
something actually changed.

- A hot reload re-clones a pristine (never-configured) builder snapshot and
  re-applies your current field values, so `IDENTITY_LAYER`,
  `CAPABILITIES_LAYER`, and `BEHAVIOR_LAYER` all reflect the new content.
- Any transient layer added just before the current turn (e.g. the
  `skill_active` layer `create_system_prompt()` injects when a skill was
  triggered via `/trigger`) is carried over to the freshly-configured
  builder, so an in-flight turn never loses it.
- The swap is atomic: the new builder is fully built before
  `self._prompt_builder` is reassigned, so concurrent requests always see a
  consistent snapshot.

---

## `$`-placeholder semantics

Identity file content is injected **verbatim — no `$`-escaping by default**.
This matters because `AbstractBot` pre-resolves dynamic variables
(`$current_date`, `$local_time`, etc.) *inside* identity text before handing
it to the prompt builder, and that pre-resolution is intentional — it's how
inline `backstory=" ... $current_date ..."` strings have always worked. If
`load_identity()` escaped every `$` by default, dynamic variables embedded in
your Markdown files would stop resolving.

```markdown
<!-- identity/backstory.md -->
Today is $current_date at $local_time.
...
```

renders with `$current_date` / `$local_time` substituted, exactly like an
inline `backstory` string would.

If you need a locked-down persona where `$` must never be treated as a
template placeholder (e.g. a file that legitimately contains a literal
`$` amount), pass `escape_placeholders=True` to `load_identity()` — it
doubles every `$` to `$$` so `string.Template.safe_substitute` treats it as
literal text. `IdentityMixin` does not currently expose this flag itself;
call `load_identity()` directly if you need it outside the mixin.

---

## Non-adopters are unaffected

Agents that don't set `enable_identity = True` (the default) are
byte-for-byte unchanged: no file reads, no `CAPABILITIES_LAYER`, no
`_build_prompt` override effects. The mixin's `__init__` and `_build_prompt`
both short-circuit to a plain `super()` passthrough when the flag is `False`.

---

## Reference implementation: Porygon

`agents/porygon.py` is the reference migration. Its previous ~122-line
inline `BACKSTORY` constant is split by concern into
`agents/porygon/identity/{role,goal,capabilities,backstory,rationale}.md`:

- `role.md` — the one-line persona statement.
- `goal.md` — what the agent is here to do.
- `capabilities.md` — the KPI/tool catalog (Fill Rate, Burn Rate, LRW, KMR,
  Merchandiser Workload, Growth Feasibility, Burn Rate Forecast).
- `rationale.md` — response-style / analysis guidelines (when to
  contextualize, how to handle abandoned kiosks, tool-vs-Pandas decisions).
- `backstory.md` — the remaining domain prose (business context,
  organizational hierarchy, replenishment cycle) plus the
  `$current_date` / `$local_time` dynamic-variable line.

`agents/` is gitignored in this repository (see `.gitignore`), so
`agents/porygon.py` and its `identity/` directory are **local-only** —
present in a working checkout but never committed. Treat the migration
pattern above as the template to replicate for any other gitignored agent.
