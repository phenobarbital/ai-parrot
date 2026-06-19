# PromptBuilder — User-Modifiable Variables

How agent authors customize the system prompt **without touching layer
templates**. Every layer is a `string.Template`; the variables below are the
`$placeholders` the runtime fills in. This document covers *who sets what*,
*where*, and *the resolution order*.

---

## 1. The two variable classes

| Class | Resolved | Who provides the value |
|-------|----------|------------------------|
| **CONFIGURE** (static) | Once, at `bot.configure()` | The agent author (DB row, YAML, subclass, or kwargs) |
| **REQUEST** (dynamic) | Every `ask()` / `ask_stream()` | The runtime, per turn (RAG results, history, output mode) |

Only the **CONFIGURE** variables are "user-modifiable" in the sense of agent
configuration. REQUEST variables are listed in §5 for completeness, but they
are filled by the framework — you don't set them per agent.

---

## 2. CONFIGURE variables (the ones you set)

These are the personality / policy knobs. Defaults come from the `DEFAULT_*`
constants in `parrot/bots/prompts/__init__.py`.

| Variable | Rendered by (layer) | Default constant | Notes |
|----------|--------------------|------------------|-------|
| `name` | `identity` | — (required) | Agent name. |
| `role` | `identity` | `DEFAULT_ROLE` = "helpful and informative AI assistant" | "You are `$role`." |
| `goal` | `identity` | `DEFAULT_GOAL` | One-line mission statement. |
| `backstory` | `identity` | `DEFAULT_BACKHISTORY` | Persona / identity prose. **Not** for grounding rules. |
| `rationale` | `behavior` | `DEFAULT_RATIONALE` = "Match the level of formality and detail to the user's question." | Conversational style only (register, length). Grounding policy belongs in a domain layer. |
| `capabilities` | `knowledge_scope` (domain) | `DEFAULT_CAPABILITIES` | **Not** in `identity`. Declares the authoritative KB scope. Only rendered when `knowledge_scope` is in the stack (RAG agents) **and** `capabilities` is non-empty. |
| `pre_instructions` | `pre_instructions` | `[]` | A `list[str]`; joined into a bulleted block. Empty list ⇒ layer skipped by its condition. |
| `extra_security_rules` | `security` | `""` | Appended after the baseline security policy. |
| `extra_tool_instructions` | `tools` | `""` | Appended to the tool policy. Layer only renders when `has_tools` is true. |
| `extra_rag_rules` | `rag_grounding` (domain) | `""` | Appended to the RAG policy (RAG agents only). |

### Important nuances

- **`capabilities` ≠ `identity`.** It was deliberately moved out of the
  identity block to avoid projecting the same list twice. It now feeds
  `KNOWLEDGE_SCOPE_LAYER`, which is *only* present on RAG-style stacks
  (`PromptBuilder.rag()`). On a `default()` stack, setting `capabilities`
  has no visible effect unless you add that layer.
- **`rationale` is style, not policy.** It renders inside `<response_style>`.
  Keep grounding/anti-hallucination rules in `strict_grounding`,
  `agent_behavior`, or `rag_grounding` — not here.
- **Empty string collapses to the default.** `AbstractBot.__init__` uses
  `kwargs.get('x') or getattr(...) or DEFAULT_X`, so a `NULL`/`""` coming
  from the DB row becomes the package default instead of leaking a blank
  section into the prompt.

---

## 3. Resolution order (precedence)

For `role`, `goal`, `capabilities`, `backstory`, `rationale`, the value is
resolved in `AbstractBot.__init__` as:

```
kwargs[x]  or  getattr(self, x)  or  DEFAULT_X
```

1. **`kwargs[x]`** — highest precedence. Comes from the instantiation call,
   which the manager populates from the `navigator.ai_bots` DB row, or from
   the YAML registry config, or passed directly in code.
2. **`getattr(self, x)`** — a class-level attribute on a subclass
   (e.g. `class FinanceBot(AbstractBot): role = "financial analyst"`).
3. **`DEFAULT_X`** — the package constant, used when nothing else is set.

### Where each source lives

| Source | Mechanism | Fields it carries |
|--------|-----------|-------------------|
| **DB row** (`navigator.ai_bots`) | `manager.py` passes them as kwargs | `role`, `goal`, `backstory`, `rationale`, `capabilities`, `pre_instructions`, `system_prompt`, `model_config`, `prompt_config` |
| **YAML registry** | `registry.py` factory | same personality fields; `prompt:` block or `system_prompt:` |
| **Subclass** | class attributes | any of the personality fields as defaults |
| **kwargs** | direct instantiation | any field, wins over the above |

---

## 4. `dynamic_values` — computed tokens you can embed

`dynamic_values` is a registry of named callables (e.g. `$current_date`,
`$local_time`). They are resolved **once** during `_configure_prompt_builder()`
(the expensive calls happen here, not per turn) and then **pre-substituted**
into the identity text fields.

Why pre-substitution matters: `Template.safe_substitute` is **not recursive**.
A `$current_date` written inside `$backstory` would otherwise survive as
literal text. The configure step resolves these tokens against the identity
fields first, so you *can* safely embed them:

```yaml
backstory: "You are the assistant on duty as of $current_date."
```

---

## 5. REQUEST variables (runtime-filled, for reference)

You don't set these per agent — the framework injects them every turn from
`_build_prompt()`. Listed so you know what the dynamic layers consume.

| Variable | Layer | Source |
|----------|-------|--------|
| `knowledge_content` | `knowledge` | Vector store / KB facts / PageIndex context |
| `user_context` | `user_session` | Per-request user context |
| `chat_history` | `user_session` | Conversation memory |
| `output_instructions` | `output` | Active output mode (structured, infographic, …) |
| `dataframe_schemas` | `dataframe_context` (domain) | PandasAgent dataframe inventory |
| `crew_context` | `crew_context` (domain) | Prior agents' results in a crew |

---

## 6. Domain-layer variables

Set when you install the corresponding domain layer (via a preset or
`builder.add(get_domain_layer(...))`).

| Variable | Layer | Phase | Set where |
|----------|-------|-------|-----------|
| `company_information` | `company_context` | CONFIGURE | Agent config (company bots) |
| `dialect` | `sql_dialect` | CONFIGURE | SQL agent config |
| `top_k` | `sql_dialect` | CONFIGURE | SQL agent config |
| `extra_rag_rules` | `rag_grounding` | CONFIGURE | RAG agent config |

---

## 7. How to customize the stack (not just the values)

Beyond filling variables, you can reshape which layers exist:

```python
from parrot.bots.prompts import PromptBuilder, get_domain_layer

# Start from the default 8-layer stack and mutate it
builder = (
    PromptBuilder.default()
    .remove("tools")                          # drop a base layer
    .add(get_domain_layer("company_context")) # add a domain layer
)

# Or start from a preset
builder = PromptBuilder.rag()      # removes tools, adds knowledge_scope + rag_grounding
builder = PromptBuilder.agent()    # default + agent_behavior
builder = PromptBuilder.voice()    # voice-optimized behavior layer
builder = PromptBuilder.minimal()  # identity + security + user_session only

# YAML/DB agents whose system_prompt already declares identity:
builder = PromptBuilder.from_system_prompt(my_prompt)  # replaces only `identity`
```

### Declarative customization (DB / YAML)

The `prompt_config` JSONB column (and the YAML equivalent) drives the same
mutations without code:

```json
{
  "preset": "default",
  "remove": ["tools"],
  "add": ["company_context"],
  "customize": { "...": "..." }
}
```

When a `system_prompt` is present but **no** `prompt:` block is declared, the
registry routes it through `PromptBuilder.from_system_prompt()` so the agent
still gets the security / knowledge / tools / output / behavior layers without
colliding with `IDENTITY_LAYER`.

---

## Quick mental model

- **Values** (`backstory`, `rationale`, …) → set via DB row / YAML / subclass /
  kwargs; resolved once at configure with `kwargs or attr or DEFAULT`.
- **Tokens** (`$current_date`) → from `dynamic_values`, pre-substituted into
  identity fields so they work even when nested.
- **Structure** (which layers) → `default()`/presets + `add`/`remove`/`replace`,
  or the declarative `prompt_config`.
- **Style vs policy** → `rationale` is style; grounding lives in domain layers.
- **Scope** → `capabilities` only shows up via `knowledge_scope` (RAG stacks).
