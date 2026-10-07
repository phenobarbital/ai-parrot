---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-server, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [jira, i18n, localization, prompt-layers, agents]
---

# Brainstorm: JiraSpecialist Multi-Language Artifact Output

**Date**: 2026-10-07
**Author**: Jesus Lara
**Status**: accepted
**Recommended Option**: Option A

---

## Problem Statement

`JiraSpecialist` mirrors the user's input language when it writes to Jira. A
Spanish-speaking developer asking *"crea un ticket para el bug del login"* gets a
Jira issue whose summary, description and comments are written in Spanish —
even when the team's Jira instance is an English-language artifact store read by
people who do not speak Spanish.

The agent has no way to express the distinction that every multilingual team
actually needs:

> *Talk to me in my language. Write the permanent record in the team's language.*

**Who is affected**

- **Operators deploying `JiraSpecialist` subclasses** — they can only control
  output language by hand-writing a custom prompt layer per deployment, because
  no language directive exists anywhere on the `Agent` branch of the class tree.
- **Mixed-language teams** — the Jira project ends up with a mix of Spanish and
  English tickets depending on who filed them, which breaks search, reporting
  and downstream automation that greps ticket text.
- **Every other agent in the framework** — the same gap exists framework-wide.
  `Chatbot` has a `self.language` attribute (`chatbot.py:244`, `:422`, DB-backed
  via `BotModel.language`), but it is **inert**: it is written to the DB and
  echoed in `get_configuration_summary()` and **never reaches the prompt**.
  `Agent`, and therefore `JiraSpecialist`, does not have it at all.

**Why now**

The current state is not merely "unconfigured", it is *inconsistent*. The
button-driven standup path already hardcodes Spanish directly in Python
f-strings (`jira_specialist.py:935`, `:944`, `:946-948`, `:966`, `:969`,
`:1077-1080`, `:1095-1100`) — `"⚠️ Error transicionando {ticket_key}"`,
`"¡A trabajar! 💪"`, `"⚠️ *Escalación Daily Standup*"`. So one deployment's
language choice is currently baked into framework source code, while the
LLM-authored half of the same flow follows whatever language the user typed.
Any serious multi-tenant deployment has to fix both halves.

---

## Constraints & Requirements

- **Backwards compatible by default.** An agent that does not configure a
  language must behave exactly as it does today (mirror the user's language).
  "Unset" must be distinguishable from "defaulted".
- **One concept, not two.** The framework must not end up with both
  `Chatbot.language` and a second, parallel `default_language`/`output_language`
  attribute meaning almost the same thing.
- **The conversational reply stays in the user's language.** Only the durable
  artifacts and agent-authored operational messages switch.
- **Quoted Jira content is never translated.** When the agent summarizes or
  quotes an existing ticket, the quoted text keeps its original language.
- **Identifiers are never translated.** Issue keys, project keys, status and
  transition names, labels, components, usernames/accountIds, JQL fragments,
  URLs and code blocks must survive verbatim — a translated status name breaks
  the transition tool call outright.
- **The FEAT-138 grounding contract must stay enforceable.** The sentinel
  phrases are currently asserted verbatim in 8 places in
  `test_jira_specialist_grounding.py` (`:200-201`, `:270`, `:277`, `:333`,
  `:340`, `:366`, `:431`) and `docs/jira-specialist-prompt-layers.md` explicitly
  forbids localising them. Whatever we do must leave the anti-hallucination
  guarantee mechanically testable.
- **Resolution is static.** The language is fixed at agent construction
  (CONFIGURE phase) so the layer stays prompt-cacheable (FEAT-181). No
  per-request override in v1.
- **No new runtime dependency** unless it earns its place.

---

## Options Explored

### Option A: Promoted bot-level `language` + composable language layer + phrase table

Promote `language` from `Chatbot` up to `AbstractBot` as **the** single
bot-level language directive, change its default from `"en"` to `None`, and
make it mean something by wiring it into the prompt through a new
`output_language` composable layer installed in every `PromptBuilder` factory.

The layer is CONFIGURE-phase and conditional: when `language` is unset the layer
renders to nothing and the prompt is byte-identical to today's. When set, it
injects a directive block that states (a) artifacts are authored in the target
language, (b) the conversational reply follows the user, (c) the never-translate
list, and (d) the quote-preservation rule.

The hardcoded Spanish literals in the standup path are rewritten to English
defaults and routed through a small per-language phrase table keyed by the same
`language` value, so the Python-authored half of the flow obeys the same
directive as the LLM-authored half. The FEAT-138 sentinels move into that same
table (English + Spanish in v1) and the grounding tests assert against the
table rather than a hardcoded literal.

✅ **Pros:**
- One concept framework-wide. `Chatbot.language` stops being a dead field and
  becomes the attribute that actually drives behavior.
- Every agent — not just Jira — gains the capability for free, which is what
  makes this worth doing as a framework feature rather than a Jira patch.
- CONFIGURE-phase + conditional means zero prompt-cache regression and a
  byte-identical prompt when unset.
- The phrase table is the only mechanism that can reach the hardcoded Telegram
  callback strings; a prompt directive provably cannot.
- Deterministically testable: assert the rendered prompt, assert the table.

❌ **Cons:**
- Changing the `language` default from `"en"` to `None` is a hard cut touching
  `Chatbot.__init__`, `_from_db`, and the `BotModel` field/DDL default.
- Installing the layer in all four builder factories changes the rendered
  system prompt of every agent in the framework the moment anyone sets
  `language` — a wide blast radius to regression-test.
- Localising the sentinels modifies a contract FEAT-138 deliberately froze; the
  docs and 8 test assertions must be updated in lockstep.
- A phrase table is the first step onto the i18n slope without being a real
  i18n system (no pluralization, no translator workflow).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none required | ISO-code → display-name mapping is a ~15-entry dict; no new dep |
| `babel` | optional: ISO-639 → language display name | **already a root dependency** (`pyproject.toml:122`) but currently imported nowhere in `packages/`. Available if we want validated names instead of a hand-rolled dict |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/prompts/layers.py:51` — `PromptLayer`
  dataclass with `condition` and `phase`; exactly the extension point needed.
- `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:789` —
  `_DOMAIN_LAYERS` registry + `get_domain_layer()` at `:805`; the new layer
  registers here.
- `packages/ai-parrot/src/parrot/bots/abstract.py:1384` — `configure_context`
  dict; the single injection point where `language` reaches the builder.
- `packages/ai-parrot/src/parrot/bots/prompts/builder.py:66/86/112/120` — the
  four factory methods that install the layer.
- `packages/ai-parrot/src/parrot/bots/chatbot.py:244`, `:422` — the existing
  `language` attribute being promoted.

---

### Option B: Write-side enforcement in JiraToolkit (translate-before-post gate)

Leave the prompt alone. Intercept the Jira **write** tools in `JiraToolkit`
(`parrot_tools/jiratoolkit.py`) and, before any create/comment/update call hits
the API, run the natural-language fields through a secondary LLM translation
pass into the configured language.

✅ **Pros:**
- The strongest guarantee available: artifacts cannot be posted in the wrong
  language, because the check sits at the boundary rather than relying on model
  compliance with a prompt directive.
- Completely decoupled from the prompt stack — no FEAT-138 contract churn, no
  sentinel renegotiation, no framework-wide prompt blast radius.
- Naturally scoped to exactly the prose fields, because the toolkit knows which
  arguments are prose and which are identifiers.

❌ **Cons:**
- An extra LLM round-trip on **every** write, paid in latency and tokens on the
  agent's hot path.
- Translation is lossy and can silently mangle inline identifiers, code blocks
  and quoted text — the exact never-translate content we must preserve.
- Does nothing for standup/HITL messages or chat replies, which the decided
  scope includes.
- Jira-only. The framework-wide gap stays open and the next agent re-solves it.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | reuses `AbstractClient` | a secondary client call per write; no new dep |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — `JiraToolkit`
  and its `JiraToolEnvelope` write surface.
- `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py` — the
  secondary-client pattern, if the translation pass uses a cheaper model.

---

### Option C: Per-tool `language` argument on the Jira write tools

Add an explicit `language` parameter to the Jira write tools' signatures so it
becomes part of the LLM-facing tool schema. The model passes the language on
each call; the agent's configured default is injected as the parameter default.

✅ **Pros:**
- Smallest diff of the four; no prompt-stack changes at all.
- Self-documenting through the tool schema, which is the LLM's actual contract
  surface — arguably a stronger signal than a prose directive.
- Trivially unit-testable: assert the argument reaching the toolkit.

❌ **Cons:**
- Governs only what the tool call *declares*, not what the model *writes* into
  `summary`/`description` — the model can pass `language="en"` and still author
  Spanish prose. It moves the compliance problem rather than solving it.
- Adds a parameter to every write tool, enlarging the schema the model must
  reason about on every turn.
- No effect on chat replies, standup messages, or the hardcoded strings.
- Jira-only; framework-wide gap stays open.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | signature change only |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — the write tools.
- `packages/ai-parrot/src/parrot/tools/` — `@tool` decorator schema generation.

---

### Option D (unconventional): Full Babel/gettext message catalog

Treat this as real internationalization rather than a prompt directive. Add a
`.po`/`.mo` catalog under the package, wrap every user-facing framework string
in a `_()` call, and resolve at runtime from the bot's locale using `babel` —
which is **already a declared root dependency** (`pyproject.toml:122`) and
currently unused. The LLM-authored text still needs a prompt directive, so this
is a superset of Option A's phrase table, not a replacement for its layer.

✅ **Pros:**
- The industry-standard answer, with a real translator workflow, pluralization,
  regional variants (`es_MX` vs `es_ES`) and tooling (`pybabel extract`).
- Scales to the whole framework's user-facing surface (Telegram, Slack, MS
  Teams integrations all have the same hardcoded-string problem), not just the
  strings this feature happens to touch.
- Activates a dependency the project already pays for.
- Catalog extraction would *inventory* every hardcoded string in the codebase —
  valuable diagnostic output regardless of the outcome.

❌ **Cons:**
- Enormous scope relative to the problem actually being solved. The ask is
  "write tickets in Spanish", not "internationalize AI-Parrot".
- Introduces a build step (`pybabel compile`) and `.mo` artifacts into a project
  that currently has no such pipeline, plus packaging implications for ten
  distributions.
- Still does not govern LLM-authored text, which is the actual problem — the
  prompt layer is needed anyway.
- A catalog whose only consumer is one agent's standup strings will rot.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `babel` | catalog extraction/compilation, locale data | `>=2.16.0`, already in `pyproject.toml:122`, currently imported nowhere |
| `pycountry` | ISO-639 validation | `>=23.0`, currently scoped to `parrot-formdesigner` only (`packages/parrot-formdesigner/pyproject.toml:46`) — would need promoting |

🔗 **Existing Code to Reuse:**
- All the Option A anchors, plus the integration packages' hardcoded strings.

---

## Recommendation

**Option A** is recommended.

Option C is the cheapest but solves the wrong half of the problem: a `language`
argument constrains the tool call's metadata, not the prose the model writes
into `summary` and `description`. It would ship fast and not fix the complaint.

Option B offers the only hard *guarantee*, and that is genuinely attractive —
but it buys that guarantee with an LLM round-trip on every write and a real risk
of a translation pass corrupting the identifiers, code blocks and quoted content
the constraints require us to preserve verbatim. It also cannot reach the
standup and HITL messages that are explicitly in scope. Paying latency on every
write to protect against a failure mode we have not yet observed is the wrong
trade at this stage; if prompt-level compliance proves insufficient in
production, Option B remains available as a strict mode layered on top.

Option D is the correct long-term shape for framework-wide i18n and would be the
right answer if the goal were localizing AI-Parrot. It is not. The feature needs
~10 strings in one agent to follow a directive; a `.po` pipeline across ten
distributions is disproportionate, and it would still need Option A's prompt
layer to govern LLM-authored text. Worth revisiting when a second and third
integration need the same treatment.

Option A is recommended because it is the only option that addresses **both**
halves of the split that makes this feature awkward: the LLM-authored text (via
the composable prompt layer) and the Python-authored text (via the phrase
table). Promoting `language` rather than adding a parallel attribute avoids
permanently encoding the confusion of two nearly-synonymous fields, and the
conditional CONFIGURE-phase layer makes "unset" genuinely free — the rendered
prompt is byte-identical to today's.

**What we are explicitly trading off:**

- **Guarantee for cost.** A prompt directive is advisory; the model can
  disobey. We accept that in exchange for zero added latency, and we accept
  that the chosen verification approach (prompt-render assertions only) proves
  the *directive is present*, never that the *model complied*. That gap should
  be stated plainly in the spec rather than papered over.
- **Blast radius for coherence.** Changing the `language` default to `None` and
  installing the layer in all four builder factories touches far more than
  Jira. We take that on because the alternative — a Jira-local
  `default_language` — leaves `Chatbot.language` dead and guarantees the next
  agent reinvents this.
- **A frozen contract for usability.** Localising the FEAT-138 sentinels
  reopens something that was deliberately nailed down, and costs updates to 8
  test assertions plus the prompt-layers doc. We accept it because an English
  "No results found for NAV-123." in an otherwise-Spanish conversation is
  exactly the inconsistency this feature exists to remove.

---

## Feature Description

### User-Facing Behavior

An operator configures an agent with an ISO 639-1 language code:

- Unset (default) — **today's behavior**, unchanged. The agent mirrors the
  user's language everywhere, and the rendered system prompt is byte-identical
  to the current one.
- Set to `"en"` while a user writes in Spanish — the user asks *"crea un ticket
  para el bug del login"*; the Jira issue is created with an **English** summary
  and description; the agent's chat confirmation comes back in **Spanish**.
- Set to `"es"` — the inverse, and the grounding sentinels are delivered in
  Spanish too (`"No se encontraron resultados para NAV-123."`), as are the
  standup button toasts and manager escalation messages.

When the agent summarizes or quotes an existing ticket, the quoted text keeps
its original language regardless of the setting — a Spanish comment quoted back
to the user is never silently translated into English.

Identifiers always survive verbatim: issue keys, project keys, status and
transition names, labels, components, usernames/accountIds, JQL, URLs and code
blocks.

The setting is visible and editable through AgentStudio, since `BotModel`
already surfaces `language` as a UI-annotated field.

### Internal Behavior

1. **Attribute.** `language: Optional[str]` moves up to `AbstractBot`, defaulting
   to `None`. `Chatbot`'s two assignment sites stop defaulting to `"en"` and the
   `BotModel` field/DDL default changes to NULL. The attribute is resolved once
   at construction — there is no per-request override.
2. **Resolution.** The ISO code is mapped to a human-readable language name for
   the prompt (`"es"` → `"Spanish"`), because models follow a named language far
   more reliably than a two-letter code. An unknown code falls back to passing
   the raw value through with a logged warning rather than failing construction.
3. **Injection.** `AbstractBot._configure_prompt_builder()` adds the resolved
   name to the `configure_context` dict it already builds, alongside `name`,
   `role` and `goal`. Nothing else in the configure path changes.
4. **Layer.** A new `output_language` `PromptLayer` — CONFIGURE phase,
   `LayerPriority.OUTPUT`-adjacent, conditional on the variable being set —
   registers in `_DOMAIN_LAYERS` and is installed by `PromptBuilder.default()`,
   `.agent()`, `.rag()` and `.voice()`. Its body carries the four rules:
   artifact language, conversational-reply exception, never-translate list, and
   quote preservation.
5. **Phrase table.** A small per-language mapping (English + Spanish in v1)
   holds the FEAT-138 sentinels and the standup/callback strings. The hardcoded
   Spanish literals in `jira_specialist.py` are rewritten to English defaults
   and read from this table keyed by the agent's `language`; an unmapped
   language falls back to English.
6. **Grounding layer.** `JIRA_GROUNDING_LAYER` renders its two mandated reply
   strings from the table for the configured language instead of hardcoding
   English, and `test_jira_specialist_grounding.py` asserts against the table.

### Edge Cases & Error Handling

| Case | Behavior |
|---|---|
| `language` unset / `None` | Layer condition fails, layer renders to nothing, prompt byte-identical to today. Phrase table returns English. |
| Unknown/invalid ISO code (`"xx"`, `"klingon"`) | Log a warning; pass the raw value into the directive; phrase table falls back to English. Never raise at construction — a typo must not take an agent down. |
| Regional variant (`"es-MX"`, `"pt-BR"`) | Accepted; the base subtag drives the phrase-table lookup, the full tag reaches the prompt directive so the model can honor the regional register. |
| Language set but a tool returns `not_found` | Sentinel rendered in the configured language from the table; the issue key inside it stays verbatim. |
| Language set, user quotes a ticket written in another language | Quote preserved verbatim; only the agent's own surrounding prose follows the directive. |
| Existing deployment relying on `Chatbot.language == "en"` | Behaviorally unaffected — the field was inert; it never reached a prompt. The change is observable only in `get_configuration_summary()` and the DB default. |
| Layer condition false at configure but variable present at build | **Trap, see Code Context.** `partial_render()` returns the layer *unchanged* when the condition fails, leaving `$placeholders` live. Safe today only because `language` is never added to the request-phase context — the spec must state that as an invariant. |
| Model disobeys the directive | Not detectable by the chosen verification approach. Known, accepted limitation; Option B is the escalation path. |

---

## Capabilities

### New Capabilities
- `bot-output-language`: a bot-level, statically-configured language directive
  that governs agent-authored artifacts while leaving conversational replies in
  the user's language.
- `localized-grounding-sentinels`: the FEAT-138 anti-hallucination sentinel
  phrases rendered per-language from a table, keeping the guarantee testable.

### Modified Capabilities
- `jira_analyst_systemprompt_hardening` (FEAT-138) — the sentinel phrases stop
  being verbatim-English constants and become table-driven per language. The
  anti-hallucination guarantee is unchanged; only its surface wording is
  parameterized. `docs/jira-specialist-prompt-layers.md` must be updated: its
  "Do not localise the sentinel phrases" anti-pattern is directly reversed by
  this feature.
- `composable-prompt-layer` — a new layer joins the standard stack in all four
  builder factories.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/abstract.py` | modifies | `language` attribute promoted here; `configure_context` (`:1384`) gains the resolved language name |
| `parrot/bots/chatbot.py` | modifies | **hard cut**: `:244` and `:422` stop defaulting to `"en"` |
| `parrot/bots/prompts/layers.py` | extends | new `output_language` layer definition (or in `domain_layers.py`) |
| `parrot/bots/prompts/domain_layers.py` | modifies | register layer in `_DOMAIN_LAYERS` (`:789`); `JIRA_GROUNDING_LAYER` (`:223`) sentinels become table-driven |
| `parrot/bots/prompts/builder.py` | modifies | install layer in `default()`, `agent()`, `rag()`, `voice()` — **framework-wide blast radius** |
| `parrot/bots/jira_specialist.py` | modifies | hardcoded Spanish literals (`:935`, `:944`, `:966`, `:1077`, `:1095`) rewritten to English + routed through the phrase table |
| `parrot/handlers/models/bots.py` (ai-parrot-server) | modifies | `language` field default `"en"` → `None` (`:245`) and DDL default (`:89`) |
| `tests/test_jira_specialist_grounding.py` | modifies | 8 sentinel assertions become table-driven |
| `tests/test_jiraspecialist_prompt_builder.py` | extends | new layer must not break existing layer-stack assertions |
| `docs/jira-specialist-prompt-layers.md` | modifies | the "do not localise sentinels" anti-pattern is reversed |
| AgentStudio UI | depends on | `language` is a `ui_help`-annotated field; a NULL default changes how the control renders |
| **Every agent in the framework** | depends on | all four builder factories gain the layer; inert while `language` is unset |

**Breaking changes**: the `language` default change is a hard cut, consistent
with the project's no-deprecation-shims policy for internal APIs. No external
consumers depend on `Chatbot.language` defaulting to `"en"` — it was inert.

**New dependencies**: none required.

---

## Code Context

### User-Provided Code

No code was provided by the user during discovery. The original request:

> "Currently JiraSpecialist agent is not able to work with user's demands in a
> language (for example: spanish) but creating the artifacts (tickets, comments)
> in another language. idea is adding a `default_language` directive on
> JiraSpecialist, then add into the prompt about demanding the artifact creation
> in that language instead user's language."

**Note**: discovery changed the placement from a `JiraSpecialist`-local
`default_language` to a promoted bot-level `language`. The spec should use
`language`, not `default_language`.

### Verified Codebase References

#### Classes & Signatures

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py:152
class JiraSpecialist(Agent):
    model = "gemini-3.5-flash"                                    # :187
    _credentials: Optional[Dict[str, Any]] = None                 # :194

    @staticmethod
    def _build_jira_prompt_builder():                             # :197
        from parrot.bots.prompts import PromptBuilder, get_domain_layer
        builder = PromptBuilder.default()
        builder.add(get_domain_layer("jira_workflow"))
        builder.add(get_domain_layer("jira_grounding"))
        return builder

    def __init__(self, **kwargs):                                 # :211
        ...
    async def clone_for_user(self, user_context: UserContext) -> "JiraSpecialist":  # :468
        ...

# packages/ai-parrot/src/parrot/bots/abstract.py:201
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin,
                  EventEmitterMixin, ToolInterface, VectorInterface, ABC):
    def __init__(                                                 # :274
        self,
        name: str = "Nav",
        system_prompt: str = None,
        llm: Union[str, Type[AbstractClient], AbstractClient, Callable, str] = None,
        instructions: str = None,
        tools: List[Union[str, AbstractTool, ToolDefinition]] = None,
        tool_threshold: float = 0.7,
        use_kb: bool = False,
        local_kb: bool = False,
        debug: bool = False,
        strict_mode: bool = True,
        block_on_threat: bool = False,
        injection_detection: bool = True,
        injection_probability_threshold: float = 0.98,
        output_mode: OutputMode = OutputMode.DEFAULT,
        include_search_tool: bool = False,
        warmup_on_configure: bool = False,
        prompt_builder: PromptBuilder = None,
        prompt_preset: str = None,
        event_bus: Optional[Any] = None,
        guardrails: Optional[List[Union[str, Dict[str, Any], Guardrail]]] = None,
        **kwargs,
    ):
        ...
    async def _configure_prompt_builder(self) -> None:            # :1356
        ...
    async def clone_for_user(self, user_context: "UserContext") -> "AbstractBot":  # :4388
        ...

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:51
@dataclass(frozen=True)
class PromptLayer:
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    cacheable: Optional[bool] = field(default=None)

    def render(self, context: Dict[str, Any]) -> Optional[str]:        # :82
        ...
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer:  # :96
        ...

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:22
class LayerPriority(IntEnum):
    IDENTITY = 10; PRE_INSTRUCTIONS = 15; SECURITY = 20; KNOWLEDGE = 30
    USER_SESSION = 40; TOOLS = 50; OUTPUT = 60; BEHAVIOR = 70; CUSTOM = 80

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:35
class RenderPhase(str, Enum):
    CONFIGURE = "configure"
    REQUEST = "request"

# packages/ai-parrot/src/parrot/bots/prompts/builder.py:34
class PromptBuilder:
    @classmethod
    def default(cls) -> PromptBuilder: ...   # :66  — 8 layers
    @classmethod
    def minimal(cls) -> PromptBuilder: ...   # :80
    @classmethod
    def voice(cls) -> PromptBuilder: ...     # :86
    @classmethod
    def agent(cls) -> PromptBuilder: ...     # :112 — default() + AGENT_BEHAVIOR_LAYER
    @classmethod
    def rag(cls) -> PromptBuilder: ...       # :120 — default() − tools + 2 layers
    def add(self, layer: PromptLayer) -> PromptBuilder: ...   # :165
    def configure(self, context: Dict[str, Any]) -> None: ... # :236
    def build(self, context: Dict[str, Any]) -> str: ...      # :256

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py:22
class BotModel(Model):
    language: str = Field(default="en", required=False,
                          ui_help="The bot's language.")       # :245
    # DDL: language VARCHAR(10) DEFAULT 'en',                  # :89
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot.bots.prompts import PromptBuilder, get_domain_layer      # prompts/__init__.py:28, :44
from parrot.bots.prompts import PromptLayer, LayerPriority, RenderPhase  # prompts/__init__.py:15
from parrot.bots.prompts.domain_layers import (
    JIRA_GROUNDING_LAYER,      # domain_layers.py:223
    JIRA_WORKFLOW_LAYER,       # domain_layers.py:266
    get_domain_layer,          # domain_layers.py:805
)
from parrot.bots.jira_specialist import JiraSpecialist             # jira_specialist.py:152
```

#### Key Attributes & Constants

- `Chatbot.language` → `str`, defaults `"en"` — `chatbot.py:244` (manual config)
  and `chatbot.py:422` (`self._from_db(bot, "language", default="en")`). Echoed
  in `save()` payload (`:546`) and `get_configuration_summary()` (`:594`).
  **Never reaches any prompt.**
- `Chatbot._from_db(self, botobj, key, default: str = None) -> Any` — `chatbot.py:167`
- `AbstractBot._configure_prompt_builder()` builds `configure_context` at
  `abstract.py:1384` and calls `self._prompt_builder.configure(configure_context)`
  at `abstract.py:1417`. Existing keys: `name`, `role`, `goal`, `capabilities`,
  `backstory`, `pre_instructions_content`, `extra_security_rules`, `has_tools`,
  `extra_tool_instructions`, `extra_rag_rules`, `rationale`, plus
  `**dynamic_context`. **This is the single injection point.**
- `_DOMAIN_LAYERS: Dict[str, PromptLayer]` — `domain_layers.py:789`. Exactly 12
  entries: `dataframe_context`, `sql_dialect`, `company_context`,
  `crew_context`, `strict_grounding`, `agent_behavior`, `knowledge_scope`,
  `rag_grounding`, `jira_grounding`, `jira_workflow`, `capabilities`,
  `data_instructions`. **None is language/locale related.**
- `JIRA_GROUNDING_LAYER` — `domain_layers.py:223`,
  `priority=LayerPriority.BEHAVIOR - 5` (= 65), `phase=RenderPhase.CONFIGURE`.
  Mandated English sentinels at `:230-231` and `:242`, `:246`.
- `JIRA_WORKFLOW_LAYER` — `domain_layers.py:266`,
  `priority=LayerPriority.PRE_INSTRUCTIONS + 1` (= 16), `phase=CONFIGURE`.
- Sentinel test constants — `tests/test_jira_specialist_grounding.py:200-201`:
  `SENTINEL_NOT_FOUND = "No results found for"`,
  `SENTINEL_ERROR = "Jira lookup failed"`. Used at `:270`, `:277`, `:333`,
  `:340`, `:366`, `:431` — **8 occurrences total**.
- Hardcoded Spanish strings in `jira_specialist.py` (in scope, English-first
  rewrite): `:935` `"⚠️ Error transicionando {ticket_key}"`; `:944`
  `"✅ {ticket_key} → In Progress"`; `:946-948` `"tu ticket … ha sido marcado
  como In Progress … ¡A trabajar! 💪"`; `:966` `"👍 Entendido"`; `:969`
  `"entendido. Ya tienes tu plan para hoy."`; `:1077-1080` `"aún no has
  seleccionado tu ticket para hoy … ¿Necesitas ayuda con la priorización?"`;
  `:1095-1100` `"⚠️ *Escalación Daily Standup* … Los siguientes devs no han
  seleccionado ticket tras {hours}h"`.
- `babel>=2.16.0` — declared at `pyproject.toml:122`, **imported nowhere** in
  `packages/` (verified: no `import babel` / `from babel` outside `build/`).
- `pycountry>=23.0` — `packages/parrot-formdesigner/pyproject.toml:46` **only**;
  not available to `ai-parrot`.

#### Mechanical trap: conditional CONFIGURE-phase layers

Verified in `layers.py:96-131` and `builder.py:236-254`:

```python
# layers.py:116-117 — partial_render()
if self.condition and not self.condition(context):
    return self          # ← returns the layer UNCHANGED: $placeholders live,
                         #    phase still CONFIGURE, condition still attached
```

`PromptBuilder.configure()` calls `partial_render()` on CONFIGURE-phase layers;
`build()` later calls `render()`, which re-evaluates any still-attached
condition (`layers.py:88-89`) against the **request** context. Consequences for
this feature:

- When `language` is unset, the condition fails at configure, the layer is
  returned unchanged, and at build the condition fails again (the variable is
  absent from the request context too) → the layer is omitted. **"Unset = free"
  works, but only because `language` is never added to the request context.**
- If a future change *also* injected `language` into the build context, a layer
  skipped at configure would then render with unresolved `$placeholders` leaking
  into the system prompt. The spec must record "`language` is CONFIGURE-only"
  as an explicit invariant with a regression test.

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractBot.language`~~ — does not exist. Only `Chatbot` has it
  (`chatbot.py:244`, `:422`). `Agent` and `JiraSpecialist` do **not** inherit it.
- ~~`AbstractBot.default_language`~~ / ~~`Agent.default_language`~~ /
  ~~`JiraSpecialist.default_language`~~ — do not exist anywhere.
- ~~`output_language`~~ — no attribute, layer, or context key by that name
  exists today.
- ~~`get_domain_layer("output_language")`~~ / ~~`("language")`~~ /
  ~~`("locale")`~~ — not registered; `get_domain_layer()` raises `KeyError`
  (`domain_layers.py:805-818`).
- ~~`PromptBuilder.jira()`~~ — no such factory. Use
  `JiraSpecialist._build_jira_prompt_builder()`.
- ~~`JiraSpecialist.system_prompt_template`~~ — removed in FEAT-138; setting it
  has no effect.
- ~~`JIRA_SPECIALIST_PROMPT`~~ — deleted in TASK-947; any import raises `ImportError`.
- ~~`parrot.utils.language`~~ / ~~ISO-639 mapping helper~~ — no language-code →
  name utility exists anywhere in `parrot.*`.
- ~~`import babel`~~ anywhere in `packages/` — the dependency is declared but
  never imported; there is no existing locale-resolution code to extend.
- ~~gettext / `.po` / `.mo` catalogs~~ — no i18n infrastructure of any kind exists.
- ~~A `language` key in `configure_context`~~ — `abstract.py:1384` does not
  currently pass it; it must be added.
- ~~Per-request language override~~ — `ask()`/`ask_stream()` take no `language`
  parameter, and v1 deliberately adds none.
- ~~`Agent.create_speech(language=...)`~~ as a general directive — this exists
  (`agent.py:976`, default `"en-US"`) but is **TTS-only** and unrelated; do not
  conflate it with this feature.

---

## Parallelism Assessment

- **Internal parallelism**: Limited. The work is a short dependency chain —
  attribute promotion → context injection → layer definition → builder
  installation → Jira sentinel/table rewrite → docs. Nearly every step depends
  on the one before it, and three of them touch `prompts/` files that would
  collide across worktrees. The only genuinely independent strand is the
  `jira_specialist.py` hardcoded-string rewrite, which touches a different file
  and could proceed once the phrase table's shape is fixed.
- **Cross-feature independence**: `prompts/domain_layers.py`, `prompts/builder.py`
  and `bots/abstract.py` are high-traffic shared files; any in-flight feature
  touching the prompt stack or `AbstractBot.__init__` will conflict. The
  `BotModel` change lands in `ai-parrot-server` and should be checked against
  in-flight AgentStudio work (FEAT-593, FEAT-634 both touch agent configuration
  surfaces). Verify at spec time with `wikitoolkit ledger context`.
  **FEAT-637 (jiratoolkit-template-support, proposal on `dev` 2026-10-07)**
  has no file overlap — it is confined to
  `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — but it is
  conceptually adjacent: Jinja-templated ticket descriptions and comments
  are authored by a template file, not by the LLM, so that prose bypasses
  this feature's prompt directive entirely. The two features should agree
  on whether templates are per-language or language-agnostic.
- **Recommended isolation**: `per-spec`
- **Rationale**: The chain is sequential, short, and concentrated in three
  shared prompt-stack files. A single feature worktree with sequential tasks
  avoids self-inflicted merge conflicts, and the one parallelizable strand is
  not worth a sub-worktree.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus*: `type: feature`, `base_branch: dev`.
- [x] Does the directive govern artifacts only, or the whole conversation? — *Owner: Jesus*: Artifacts follow the configured language; the chat reply follows the user's language; quoted/summarized existing Jira content keeps its original language verbatim.
- [x] Where does the directive live? — *Owner: Jesus*: Bot-level (`AbstractBot`), with a reusable prompt layer; JiraSpecialist is the first consumer, not the owner.
- [x] Static or per-request override? — *Owner: Jesus*: Config-only, resolved at construction (CONFIGURE phase, prompt-cacheable). No per-request override in v1.
- [x] How to resolve the English-sentinel vs. user-language collision? — *Owner: Jesus*: Localize the sentinels and update the tests/docs accordingly.
- [x] Relationship to the existing `Chatbot.language`? — *Owner: Jesus*: Promote `language` to `AbstractBot` as a hard cut; one concept, no parallel attribute.
- [x] Value format and meaning of "unset"? — *Owner: Jesus*: ISO 639-1 code; unset = today's behavior (mirror the user), fully backwards compatible.
- [x] Reconciling the promoted attribute with Chatbot's `"en"` default? — *Owner: Jesus*: The default becomes `None` everywhere, including `_from_db` and the `BotModel` field/DDL.
- [x] Which Jira content does it apply to? — *Owner: Jesus*: Prose fields (summary, description, comment bodies) plus an explicit never-translate list stated in the layer.
- [x] Which builders install the layer? — *Owner: Jesus*: All of them (`default`, `agent`, `rag`, `voice`) — framework-wide consistency.
- [x] Standup and HITL messages — artifact or chat? — *Owner: Jesus*: Artifact; they follow the configured language.
- [x] Sentinel production mechanism and v1 languages? — *Owner: Jesus*: An explicit phrase table, English + Spanish in v1, unknown language falls back to English.
- [x] Are the hardcoded Spanish Python strings in scope? — *Owner: Jesus*: Yes — rewritten to English defaults and routed through the same phrase table.
- [x] Verification approach? — *Owner: Jesus*: Prompt-render assertions only (deterministic; no live model calls). Accepted limitation: this proves the directive renders, never that the model obeys.
- [x] Should `minimal()` also install the layer? — *Owner: Jesus*: No. `minimal()` stays a deliberate 3-layer stack; agents using it opt in by adding the layer themselves. "All builders" therefore means `default`, `agent`, `rag`, `voice`.
- [x] Does the `BotModel` DDL default change (`:89`) require a migration for existing rows? — *Owner: Jesus*: Yes. Ship a migration setting existing `'en'` values to NULL alongside the DDL default change, so already-deployed agents keep today's mirror-the-user behavior.
- [x] How do this feature and FEAT-637 (jiratoolkit-template-support) interact? — *Owner: Jesus*: This spec declares the per-language convention FEAT-637 should follow (template lookup falls back `<name>.<lang>.j2` → `<name>.j2`) without implementing it. Direction is set here; the work belongs to FEAT-637.
- [ ] Should regional variants (`es-MX`, `pt-BR`) be validated against a known list, or accepted free-form with a warning? Current design says free-form + warning. — *Owner: Jesus*
