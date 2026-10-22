# JiraSpecialist Prompt-Layer Stack

> **Feature**: FEAT-138 — jira_analyst_systemprompt_hardening
> **Since**: ai-parrot next minor
> **Stability**: stable

---

## Why layers?

Before FEAT-138, `JiraSpecialist` used a single 500-line string assigned
to `system_prompt_template`. This caused three persistent failure modes:

1. **Hallucination on empty results** — the LLM invented ticket fields when
   a `jira_get_issue` call returned nothing, because the monolithic prompt
   contained no authoritative instruction for that case.
2. **Cross-ticket bleed** — fields from a prior lookup appeared in the reply
   for a different issue key.
3. **Apology-then-fabricate loop** — after a `not_found` answer, user
   corrections caused a second fabricated reply instead of a tool re-call.

The fix: replace the monolithic string with a
[`PromptBuilder`](../packages/ai-parrot/src/parrot/bots/prompts/layers.py)
composed of two focused layers. Each layer is independently testable,
versionable, and overridable by subclasses.

---

## The layer stack

`JiraSpecialist._build_jira_prompt_builder()` installs layers in this order
(lowest priority number renders first in the system prompt):

| Layer name | Priority | Phase | Purpose |
|---|---|---|---|
| `jira_workflow` | `PRE_INSTRUCTIONS + 1` (16) | `CONFIGURE` | Behavioural rules — posture, standup flow, HITL logic, fresh-turn rule, interaction-type examples |
| `jira_grounding` | `BEHAVIOR - 5` (45) | `CONFIGURE` | Anti-hallucination policy — sentinel phrases, no cross-ticket bleed, no apology-then-fabricate loop |

Both layers use `phase=RenderPhase.CONFIGURE`, meaning they contain no
per-request variables and are rendered once at agent construction time.

### `jira_workflow`

Defines the agent's identity, default posture ("act then report"), and
the operational rules for standup, HITL interactions, and ticket management.
It answers: *"What should the agent do?"*

Source: `parrot/bots/prompts/domain_layers.py::JIRA_WORKFLOW_LAYER`

### `jira_grounding`

Defines hard constraints on how the agent uses Jira tool results. It
answers: *"What must the agent never do?"*

Source: `parrot/bots/prompts/domain_layers.py::JIRA_GROUNDING_LAYER`

---

## Sentinel phrases

`JIRA_GROUNDING_LAYER` mandates two reply prefixes. Since FEAT-638 their wording follows
the bot's `language`: the template carries `$sentinel_not_found` / `$sentinel_error`,
which `AbstractBot._configure_prompt_builder()` fills from `GROUNDING_SENTINELS`
(English when `language` is unset). The anti-hallucination rules are identical in every language.

| Situation | `en` (default) | `es` |
|---|---|---|
| Tool returns `status="not_found"` or `status="empty"` | `No results found for <KEY\|JQL>.` | `No se encontraron resultados para <KEY\|JQL>.` |
| Tool returns `status="error"` or raises | `Jira lookup failed: <message>.` | `La consulta a Jira falló: <message>.` |

The phrases are **assertion targets**: `test_jira_grounding_layer.py` and
`test_jira_specialist_grounding.py` read them from `GROUNDING_SENTINELS`, so change them only
there. To add a language see [`prompts/output-language.md`](prompts/output-language.md).

---

## Extending or overriding

### Adding an extra layer in a subclass

```python
from parrot.bots.jira_specialist import JiraSpecialist
from parrot.bots.prompts import PromptLayer, LayerPriority, RenderPhase, get_domain_layer


MY_EXTRA_LAYER = PromptLayer(
    name="my_extra",
    priority=LayerPriority.BEHAVIOR,
    phase=RenderPhase.CONFIGURE,
    template="<my_rules>Always respond in bullet points.</my_rules>",
)


class MyJira(JiraSpecialist):
    def __init__(self, **kwargs):
        builder = JiraSpecialist._build_jira_prompt_builder()
        builder.add(MY_EXTRA_LAYER)
        kwargs.setdefault("prompt_builder", builder)
        super().__init__(**kwargs)
```

### Replacing a layer entirely

```python
from parrot.bots.jira_specialist import JiraSpecialist
from parrot.bots.prompts import PromptBuilder, PromptLayer, LayerPriority, RenderPhase


CUSTOM_GROUNDING = PromptLayer(
    name="jira_grounding",       # same name — replaces the default
    priority=LayerPriority.BEHAVIOR - 5,
    phase=RenderPhase.CONFIGURE,
    template="<jira_grounding_policy>... custom rules ...</jira_grounding_policy>",
)


class StrictJira(JiraSpecialist):
    def __init__(self, **kwargs):
        builder = JiraSpecialist._build_jira_prompt_builder()
        # Remove the default grounding layer by name, then add the custom one
        builder.remove("jira_grounding")
        builder.add(CUSTOM_GROUNDING)
        kwargs.setdefault("prompt_builder", builder)
        super().__init__(**kwargs)
```

### Supplying a fully custom builder at instantiation

```python
from parrot.bots.jira_specialist import JiraSpecialist
from parrot.bots.prompts import PromptBuilder, get_domain_layer

builder = PromptBuilder.default()
builder.add(get_domain_layer("jira_workflow"))   # keep workflow rules
# omit jira_grounding on purpose (not recommended — will break regression tests)

agent = JiraSpecialist(prompt_builder=builder)
```

---

## Anti-patterns

The following patterns are explicitly **forbidden**:

- **Do not set `system_prompt_template`** — this attribute was removed in
  FEAT-138. Setting it has no effect and masks the layered builder.

- **Do not import `JIRA_SPECIALIST_PROMPT`** — this constant was deleted in
  TASK-947. Any import will raise `ImportError`.

- **Do not hardcode the sentinel phrases** — read them from `GROUNDING_SENTINELS`
  (`parrot/bots/prompts/domain_layers.py`). Localising them is supported since FEAT-638;
  a literal edited in a test or a layer instead of the table will drift out of sync.

- **Do not add anti-hallucination rules outside `JIRA_GROUNDING_LAYER`** —
  grounding rules scattered across layers are hard to audit and override. Add
  them to a custom grounding layer following the "Replacing a layer" pattern
  above.

- **Do not call `PromptBuilder.jira()`** — no such factory exists. Use
  `JiraSpecialist._build_jira_prompt_builder()`.

---

## Cross-references

| Resource | Path |
|---|---|
| FEAT-138 spec | `sdd/specs/jira_analyst_systemprompt_hardening.spec.md` |
| Layer definitions | `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` |
| PromptBuilder source | `packages/ai-parrot/src/parrot/bots/prompts/layers.py` |
| Grounding regression tests | `packages/ai-parrot/tests/test_jira_specialist_grounding.py` |
| Envelope shape (FEAT-138) | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py::JiraToolEnvelope` |
| Composable prompt layer spec | `sdd/specs/composable-prompt-layer.spec.md` |
