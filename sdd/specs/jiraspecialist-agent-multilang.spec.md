---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, docs]
tags: [jira, i18n, localization, prompt-layers, agents]
---

# Feature Specification: Bot-Level Output Language Directive

**Feature ID**: FEAT-638
**Date**: 2026-10-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`JiraSpecialist` mirrors the user's input language when it writes to Jira. A
Spanish-speaking developer asking *"crea un ticket para el bug del login"* gets a
Jira issue whose summary, description and comments are written in Spanish — even
when the team's Jira instance is an English-language artifact store read by
people who do not speak Spanish. The agent cannot express the distinction every
multilingual team needs:

> *Talk to me in my language. Write the permanent record in the team's language.*

The framework has no mechanism for this. `Chatbot` carries a `language`
attribute (`chatbot.py:244`, `:422`), but it is **inert** — persisted to the DB,
echoed in configuration summaries, and never reaching any prompt. `Agent`, and
therefore `JiraSpecialist`, does not have it at all.

The current state is not merely unconfigured, it is *inconsistent*: the
button-driven standup path hardcodes Spanish directly in Python f-strings
(`jira_specialist.py:935`, `:944`, `:946-948`, `:966`, `:969`, `:1077-1080`,
`:1095-1100`), so one deployment's language choice is baked into framework
source, while the LLM-authored half of the same flow follows whatever the user
typed.

### Goals

1. A **bot-level, statically-configured language directive** that governs
   agent-authored artifacts while conversational replies follow the user.
2. **One concept framework-wide** — promote the existing `Chatbot.language` to
   `AbstractBot` rather than introducing a parallel attribute.
3. **Zero behavior change when unset** for LLM-authored text: the rendered
   system prompt must be byte-identical to today's.
4. **Governed Python-authored text**: the hardcoded standup/callback strings
   follow the same directive, via a message catalog a prompt cannot reach.
5. **Preserve the FEAT-138 grounding guarantee** while localizing its surface
   wording.
6. **No raw operator input reaches the system prompt** — the language value is
   bounded and allowlisted.

### Non-Goals (explicitly out of scope)

- Per-request language override. The value resolves once at construction
  (`ask()`/`ask_stream()` gain no `language` parameter).
- Proving model compliance. Verification is prompt-render assertions only; this
  demonstrates the directive is *present*, never that the LLM *obeyed* it.
- Full i18n infrastructure (gettext/Babel `.po` catalogs) — considered and
  rejected in brainstorm Option D as disproportionate.
- Write-side translation enforcement in `JiraToolkit` — rejected in brainstorm
  Option B (an LLM round-trip per write, and a corruption risk for identifiers);
  it remains the escalation path if prompt-level compliance proves insufficient.
- Localizing templated Jira writes. FEAT-637 renders descriptions/comments from
  Jinja templates, which no prompt directive can govern; this spec declares the
  convention (§7) but implements none of it.
- Languages beyond English and Spanish. Adding one is a catalog entry, not a
  code change.
- `PromptBuilder.minimal()` — deliberately excluded (see §3 M3).

---

## 2. Architectural Design

### Overview

Promote `language` from `Chatbot` to `AbstractBot` as the single bot-level
language directive, change its default from `"en"` to `None`, and make it
*mean* something by wiring it into the prompt through a new `output_language`
composable layer installed by the `default()`, `agent()`, `rag()` and `voice()`
builder factories.

The value is normalized through a bounded allowlist (`"es-MX"` → `"es"`) and
mapped to an English display name (`"es"` → `"Spanish"`) before it reaches the
prompt — models follow a named language far more reliably than a two-letter
code, and an allowlist closes the prompt-injection surface that a free-text UI
field (`TabsGeneral.svelte:82-86`) would otherwise open.

When the resolved language is `None`, `AbstractBot._configure_prompt_builder()`
**removes** the layer from the builder outright. It is deliberately *not* a
`condition=` callable: `PromptLayer.partial_render()` returns the layer
unchanged when a condition fails (`layers.py:116-117`), and `_build_prompt()`
spreads arbitrary `**kwargs` into the request context before `build()`
(`abstract.py:1446-1455`), so a request-time `language=` kwarg could reactivate
a layer that was absent at configure time and render it with unresolved
`$placeholders`. Removal is irrevocable and cannot be reactivated.

Python-authored operational text (standup callbacks, nudges, manager
escalations) is governed by a **message catalog of templates with protected
placeholders** rather than whole rendered strings. The Jira status `In Progress`
is embedded in those strings today (`jira_specialist.py:944`, `:947`) and
asserted at `test_jira_callbacks.py:56`; storing whole strings per language
would translate a status name and break the very transition call the never-
translate rule exists to protect.

The FEAT-138 grounding sentinels become template variables resolved at configure
time from the same catalog, so `JIRA_GROUNDING_LAYER` stays a module constant
and a registry entry while its wording follows the configured language.

**Unset semantics.** For LLM-authored text, unset = today's behavior exactly
(the layer is absent, the prompt is byte-identical). For Python-authored text,
unset renders **English** — today's literals are Spanish, so "unset = today" and
"unset = English" cannot both hold for them. The existing Spanish deployment
preserves its behavior by setting `language='es'` explicitly at rollout, and
`test_jira_callbacks.py:84` (which asserts `"Entendido"`) is updated accordingly.

### Component Diagram

```
operator config / BotModel.language / UserBotModel.language
          │
          ▼
AbstractBot.language  (Optional[str], default None)          ── M1
          │
          ▼
normalize_language() → resolve_language_name()               ── M2
   "es-MX" → "es"        "es" → "Spanish"
          │
          ├──────────────────────────────┬───────────────────────────┐
          ▼                              ▼                           ▼
_configure_prompt_builder()        render_message()          GROUNDING_SENTINELS
  injects $output_language          (protected placeholders)   $sentinel_not_found
  injects $sentinel_*                        │                 $sentinel_error
  removes layer when None                    │                        │
          │                                  ▼                        ▼
          ▼                        JiraSpecialist callbacks   JIRA_GROUNDING_LAYER
   OUTPUT_LANGUAGE_LAYER            standup / escalation            ── M5
   installed by default()/          ── M4
   agent()/rag()/voice()  ── M3
```

### Integration Points

| Component | Interaction | Verified At |
|---|---|---|
| `AbstractBot.__init__` | gains `self.language` beside the personality attributes | `abstract.py:431` |
| `AbstractBot._configure_prompt_builder` | injects `output_language` + sentinel vars into `configure_context`; removes the layer when unset | `abstract.py:1384`, `:1417` |
| `Chatbot` | both `"en"` defaults removed (hard cut) | `chatbot.py:244`, `:422` |
| `PromptBuilder.default/agent/rag/voice` | install `OUTPUT_LANGUAGE_LAYER` | `builder.py:66`, `:112`, `:120`, `:86` |
| `PromptBuilder.minimal` | deliberately **not** changed; `presets.py` exposes it as an opt-out | `builder.py:80`, `presets.py:30` |
| `PromptBuilder.remove` | the unset path's removal mechanism | `builder.py:177` |
| `_DOMAIN_LAYERS` | registers `output_language` | `domain_layers.py:789` |
| `JIRA_GROUNDING_LAYER` | sentinels become `$sentinel_not_found` / `$sentinel_error` | `domain_layers.py:223` |
| `JiraSpecialist` callbacks | hardcoded Spanish → catalog templates | `jira_specialist.py:935`, `:944`, `:966`, `:1077`, `:1095` |
| `BotModel.language` | field default `"en"` → `None` | `bots.py:245` |
| `UserBotModel.language` | field default `"en"` → `None` | `users_bots.py:107` |
| `BotManager` | consumes `to_bot_kwargs()`; no change, but carries the new value | `manager.py:1183`, `:1386` |
| `navigator.ai_bots` DDL (docstring) | `DEFAULT 'en'` → no default | `bots.py:89` |
| `navigator.ai_bots` DDL (executed) | `DEFAULT 'en'` → no default | `creation.sql:64` |
| `users_bots` DDL | `DEFAULT 'en'` → no default | `users_bots_creation.sql:66` |
| FEAT-621 AC17 gate | rebaselined (it pins both DDLs to the merge-base) | `test_storage_gates.py:136-137` |
| `docs/jira-specialist-prompt-layers.md` | its "do not localise sentinels" anti-pattern is reversed | `docs/jira-specialist-prompt-layers.md` |
| `docs/prompts/layers-reference.md` | documents `jira_grounding` + gains `output_language` | `layers-reference.md:435`, `:512` |

### Data Models

```python
# packages/ai-parrot/src/parrot/bots/prompts/language.py  (new)
SUPPORTED_LANGUAGES: Final[dict[str, str]] = {"en": "English", "es": "Spanish"}
FALLBACK_LANGUAGE: Final[str] = "en"

# packages/ai-parrot/src/parrot/bots/jira_messages.py  (new)
@dataclass(frozen=True)
class MessageTemplate:
    template: str                      # `string.Template` source
    protected: frozenset[str]          # placeholder names that must survive verbatim
```

### New Public Interfaces

```python
from parrot.bots.prompts.language import (
    SUPPORTED_LANGUAGES, normalize_language, resolve_language_name,
)
from parrot.bots.prompts.domain_layers import OUTPUT_LANGUAGE_LAYER, GROUNDING_SENTINELS
from parrot.bots.jira_messages import MessageTemplate, JIRA_MESSAGES, render_message
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: language attribute promotion | yes | Insertion anchor `abstract.py:431`, idiom `kwargs.get(...) or getattr(...) or None`; both `chatbot.py` defaults → `None` | — |
| M2: language resolution | yes | Signatures fixed below; allowlist `{"en","es"}`; unknown ⇒ `None` + `self.logger.warning` | — |
| M3: output_language layer | yes | Layer name/priority/phase fixed; unset handled by `builder.remove("output_language")`, never `condition=` | — |
| M4: message catalog + Jira rewrite | yes | `MessageTemplate` shape fixed; protected placeholder set fixed per entry | — |
| M5: sentinel localization | yes | Template vars `$sentinel_not_found` / `$sentinel_error`; catalog values fixed | — |
| M6: persistence + DDL + gate | no | Touches another feature's release gate and ships a data migration — the rebaseline is a judgement call, not mechanical | AC17 baseline update must be reviewed by a human |

### Module 1: Language attribute promotion
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`, `packages/ai-parrot/src/parrot/bots/chatbot.py`
- **Responsibility**: Own `language` at the base class; remove Chatbot's inert `"en"` defaults.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies abstract.py:431)
  class AbstractBot(...):
      language: Optional[str]
      """ISO 639-1 code for agent-authored artifacts; None = mirror the user."""
      # inserted immediately after:
      #   self.rationale = kwargs.get("rationale") or ...   # verified: abstract.py:431
      #   self.language = kwargs.get("language") or getattr(self, "language", None) or None

  # packages/ai-parrot/src/parrot/bots/chatbot.py  (modifies chatbot.py:244, :422)
  #   self.language = getattr(self, "language", None)                      # was "en"
  #   self.language = self._from_db(bot, "language", default=None)         # was "en"
  ```

### Module 2: Language resolution
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/language.py` *(new)*
- **Responsibility**: Normalize and validate a raw language value; map it to a display name. Closes the prompt-injection surface.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/prompts/language.py  (new)
  SUPPORTED_LANGUAGES: Final[dict[str, str]] = {"en": "English", "es": "Spanish"}
  FALLBACK_LANGUAGE: Final[str] = "en"

  def normalize_language(raw: Optional[str]) -> Optional[str]:
      """Normalize a raw language value to a supported ISO 639-1 base subtag.

      Strips whitespace, lowercases, and takes the base subtag before any
      ``-``/``_`` separator, so ``"es-MX"`` and ``"ES_mx"`` both yield ``"es"``.

      Returns:
          The supported base subtag, or ``None`` when the input is empty,
          malformed, or not in :data:`SUPPORTED_LANGUAGES`. Never returns
          caller-controlled text — an unsupported value resolves to ``None``
          so nothing unvalidated can reach the system prompt.
      """

  def resolve_language_name(code: Optional[str]) -> Optional[str]:
      """Map a normalized code to its English display name for the prompt.

      Returns:
          e.g. ``"Spanish"`` for ``"es"``; ``None`` when ``code`` is ``None``.
      """
  ```

### Module 3: `output_language` prompt layer
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`, `packages/ai-parrot/src/parrot/bots/prompts/builder.py`, `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: Define, register and install the directive layer; inject the resolved name; remove the layer when unset.
- **Depends on**: M1 (attribute), M2 (resolver)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py  (modifies domain_layers.py:789)
  OUTPUT_LANGUAGE_LAYER = PromptLayer(
      name="output_language",
      priority=LayerPriority.OUTPUT - 1,        # 59 — before OUTPUT (60)
      phase=RenderPhase.CONFIGURE,              # cacheable (FEAT-181)
      template="<output_language_policy> ... $output_language ... </output_language_policy>",
      required_vars=frozenset({"output_language"}),
      # NO condition= — see §7 Known Risks (S4).
  )
  # _DOMAIN_LAYERS gains: "output_language": OUTPUT_LANGUAGE_LAYER   # verified: domain_layers.py:789

  # packages/ai-parrot/src/parrot/bots/prompts/builder.py
  #   default()  adds OUTPUT_LANGUAGE_LAYER        # verified: builder.py:66
  #   agent()    inherits via default()            # verified: builder.py:112
  #   rag()      inherits via default()            # verified: builder.py:120
  #   voice()    adds OUTPUT_LANGUAGE_LAYER        # verified: builder.py:86
  #   minimal()  deliberately UNCHANGED            # verified: builder.py:80

  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies abstract.py:1384, :1417)
  #   configure_context["output_language"] = resolve_language_name(normalize_language(self.language)) or ""
  #   if not normalize_language(self.language):
  #       self._prompt_builder.remove("output_language")   # verified: builder.py:177
  ```
  The layer body states the four rules: artifacts in `$output_language`; the
  conversational reply follows the user; the never-translate list (issue keys,
  project keys, status and transition names, labels, components,
  usernames/accountIds, JQL, URLs, code blocks); and quoted Jira content
  preserved verbatim in its original language.

### Module 4: Operational message catalog + JiraSpecialist rewrite
- **Path**: `packages/ai-parrot/src/parrot/bots/jira_messages.py` *(new)*, `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**: Hold localized operational templates with protected placeholders; replace the hardcoded Spanish literals.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/jira_messages.py  (new)
  @dataclass(frozen=True)
  class MessageTemplate:
      """A localized operational message with placeholders that must not be translated."""
      template: str
      protected: frozenset[str]

  JIRA_MESSAGES: Final[dict[str, dict[str, MessageTemplate]]]
  """{language: {key: MessageTemplate}} for 'en' and 'es'.

  Keys: transition_error, transition_ok, transition_edit, skip_ok, skip_edit,
  nudge, escalation.
  """

  def render_message(key: str, language: Optional[str], **params: Any) -> str:
      """Render an operational message in the configured language.

      Falls back to :data:`FALLBACK_LANGUAGE` when ``language`` is ``None`` or
      has no entry for ``key``.

      Raises:
          KeyError: when ``key`` is unknown in the fallback language.
      """

  # packages/ai-parrot/src/parrot/bots/jira_specialist.py
  #   :935  answer_text=render_message("transition_error", self.language, ticket_key=ticket_key)
  #   :944  answer_text=render_message("transition_ok", self.language, ticket_key=ticket_key, status=...)
  #   :966  answer_text=render_message("skip_ok", self.language)
  #   :1077 text=render_message("nudge", self.language, name=dev.name)
  #   :1095 text=render_message("escalation", self.language, hours=hours, names=names)
  ```
  `protected` names (`ticket_key`, `status`, `name`, `names`) are substituted
  verbatim in every language — the Jira status `In Progress` must survive
  byte-for-byte (`test_jira_callbacks.py:56`).

### Module 5: Grounding sentinel localization
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`, `packages/ai-parrot/tests/test_jira_specialist_grounding.py`, `packages/ai-parrot/tests/bots/prompts/test_jira_grounding_layer.py`, `docs/jira-specialist-prompt-layers.md`, `docs/prompts/layers-reference.md`
- **Responsibility**: Parameterize the FEAT-138 sentinels per language without weakening the anti-hallucination guarantee.
- **Depends on**: M2, M3 (shares the `configure_context` injection)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py  (modifies domain_layers.py:223)
  GROUNDING_SENTINELS: Final[dict[str, dict[str, str]]] = {
      "en": {"not_found": "No results found for", "error": "Jira lookup failed"},
      "es": {"not_found": "No se encontraron resultados para",
             "error": "La consulta a Jira falló"},
  }
  # JIRA_GROUNDING_LAYER.template: the two literals become
  #   $sentinel_not_found   and   $sentinel_error
  # resolved at CONFIGURE time; the layer stays a module constant and a
  # _DOMAIN_LAYERS entry. Rules 1/4/5/6 of the policy are unchanged.
  ```

### Module 6: Persistence, DDL and gate rebaseline
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/models/bots.py`, `.../models/users_bots.py`, `.../handlers/creation.sql`, `.../models/users_bots_creation.sql`, `sdd/migrations/FEAT-638-bot-language-nullable.sql` *(new)*, `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
- **Responsibility**: Align both bot models and both DDLs with the `None` default, migrate existing rows, and rebaseline the FEAT-621 AC17 gate.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/models/bots.py
  #   :245  language: str = Field(default="en", ...)
  #      →  language: Optional[str] = Field(default=None, required=False,
  #                                         ui_help="The bot's language.")
  #   :89   docstring DDL  language VARCHAR(10) DEFAULT 'en',  →  language VARCHAR(10),

  # packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py
  #   :107  language: str = Field(required=False, default="en")
  #      →  language: Optional[str] = Field(required=False, default=None)
  ```
  ```sql
  -- packages/ai-parrot-server/src/parrot/handlers/creation.sql:64
  -- packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql:66
  language VARCHAR(10),                      -- was: DEFAULT 'en'

  -- sdd/migrations/FEAT-638-bot-language-nullable.sql  (new)
  ALTER TABLE navigator.ai_bots    ALTER COLUMN language DROP DEFAULT;
  UPDATE      navigator.ai_bots    SET language = NULL WHERE language = 'en';
  -- same pair for the users_bots table
  ```
  `test_storage_gates.py::test_load_database_bots_untouched` is rebaselined: its
  AC17 assertion that both DDLs are byte-identical to the merge-base is updated
  to accept this feature's change.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_normalize_language_base_subtag` | M2 | `"es-MX"`, `"ES_mx"`, `" es "` → `"es"` |
| `test_normalize_language_unsupported_is_none` | M2 | `"fr"`, `"klingon"`, `"<xml>"`, `"$x"`, `""`, `None` → `None` |
| `test_normalize_language_never_returns_input` | M2 | No caller-controlled string is ever returned (injection guard, S3) |
| `test_resolve_language_name` | M2 | `"es"` → `"Spanish"`; `None` → `None` |
| `test_layer_registered` | M3 | `get_domain_layer("output_language")` resolves |
| `test_layer_in_default_agent_rag_voice` | M3 | `output_language` ∈ `layer_names` for all four factories |
| `test_layer_absent_from_minimal` | M3 | `minimal()` and the `"minimal"` preset omit it (S5) |
| `test_layer_is_configure_and_cacheable` | M3 | `phase is CONFIGURE`, `cacheable is True` (FEAT-181) |
| `test_prompt_byte_identical_when_unset` | M3 | `_build_prompt()` output with `language=None` equals the pre-feature baseline |
| `test_layer_has_no_condition` | M3 | `OUTPUT_LANGUAGE_LAYER.condition is None` (S4 guard) |
| `test_configure_none_then_build_with_language_kwarg` | M3 | configure with `None`, then `_build_prompt(language="es")` → **no** directive and **no** `$placeholder` leak (S4 regression) |
| `test_prompt_contains_directive_when_set` | M3 | `language="es"` → rendered prompt names "Spanish" and the never-translate list |
| `test_render_message_locales` | M4 | Every key renders in `en` and `es` |
| `test_render_message_protects_placeholders` | M4 | `In Progress`, `NAV-123`, dev names survive byte-for-byte in every locale (S7) |
| `test_render_message_falls_back_to_english` | M4 | `None` and an unknown key's language → English |
| `test_callback_transition_localized` | M4 | `on_ticket_*` `answer_text`/`edit_message` follow `self.language` (S8) |
| `test_escalation_localized` | M4 | `escalate_non_responders` nudge + manager text follow `self.language` |
| `test_grounding_sentinels_per_language` | M5 | Rendered layer carries the `en`/`es` sentinel for the configured language |
| `test_grounding_rules_unchanged` | M5 | Policy rules 1/4/5/6 unchanged in every locale |
| `test_bot_model_language_defaults_none` | M6 | `BotModel()` and `UserBotModel()` → `language is None` |

### Integration Tests

| Test | Description |
|---|---|
| `test_jira_specialist_prompt_language_matrix` | Build `JiraSpecialist` with `language` ∈ {unset, `"en"`, `"es"`, `"es-MX"`} and assert the rendered system prompt at the `AbstractBot._build_prompt()` level (S8) |
| `test_chatbot_language_no_longer_defaults_en` | A `Chatbot` built with no language keeps `None` through manual config and `_from_db` |
| `test_storage_gate_rebaselined` | FEAT-621 AC17 passes against the new baseline |

### Test Data / Fixtures

- Reuse `packages/ai-parrot/tests/fixtures/jira_payloads.py`.
- `test_jira_specialist_grounding.py` keeps its module-level sentinel constants
  but sources them from `GROUNDING_SENTINELS` instead of hardcoding (8 call
  sites: `:200-201`, `:270`, `:277`, `:333`, `:340`, `:366`, `:431`).
- `test_jira_callbacks.py:84` (`"Entendido"`) is updated to the English default;
  a new case asserts `"Entendido"` with `language="es"`.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `AbstractBot` exposes `language: Optional[str]`, default `None`; `Agent` and `JiraSpecialist` inherit it.
- [ ] `Chatbot` no longer defaults `language` to `"en"` at either site (`chatbot.py:244`, `:422`).
- [ ] With `language` unset, the rendered system prompt is **byte-identical** to the pre-feature baseline for `default()`, `agent()`, `rag()` and `voice()`.
- [ ] With `language="es"`, the rendered prompt names "Spanish", states the artifact rule, the conversational-reply exception, the never-translate list, and the quote-preservation rule.
- [ ] `OUTPUT_LANGUAGE_LAYER.condition is None`; configuring with `None` and then calling `_build_prompt(language="es")` yields neither the directive nor a `$placeholder` leak.
- [ ] The layer is `RenderPhase.CONFIGURE` and `cacheable is True`.
- [ ] `minimal()` and the `"minimal"` preset do not install the layer, and a test asserts that opt-out contract.
- [ ] `normalize_language()` never returns caller-controlled text; unsupported, malformed, empty and `None` inputs all resolve to `None` and are logged at WARNING.
- [ ] Regional variants (`"es-MX"`, `"pt-BR"`) normalize to their base subtag.
- [ ] Every hardcoded Spanish literal in `jira_specialist.py` is replaced by a `render_message()` call; none remain.
- [ ] Protected placeholders — issue keys, the Jira status `In Progress`, developer names, hours — survive byte-for-byte in every locale.
- [ ] Grounding sentinels render per language; FEAT-138 policy rules 1/4/5/6 are unchanged in every locale.
- [ ] `test_jira_grounding_layer.py` and `test_jira_specialist_grounding.py` both pass against the parameterized sentinels.
- [ ] `BotModel.language` and `UserBotModel.language` default to `None`; both DDLs drop `DEFAULT 'en'`.
- [ ] `sdd/migrations/FEAT-638-bot-language-nullable.sql` drops the defaults and NULLs existing `'en'` rows in both tables.
- [ ] FEAT-621 AC17 (`test_storage_gates.py`) passes against its updated baseline.
- [ ] `docs/jira-specialist-prompt-layers.md` no longer forbids localizing the sentinels; `docs/prompts/layers-reference.md` documents `output_language`.
- [ ] `ruff check` clean on all changed files; no banned imports.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against base commit `1b258f9b6` on 2026-10-07.

### Verified Imports

```python
from parrot.bots.prompts import PromptBuilder, get_domain_layer      # verified: prompts/__init__.py:28, :44
from parrot.bots.prompts import PromptLayer, LayerPriority, RenderPhase  # verified: prompts/__init__.py:15
from parrot.bots.prompts.domain_layers import (
    JIRA_GROUNDING_LAYER,      # verified: domain_layers.py:223
    JIRA_WORKFLOW_LAYER,       # verified: domain_layers.py:266
    get_domain_layer,          # verified: domain_layers.py:805
)
from parrot.bots.jira_specialist import JiraSpecialist              # verified: jira_specialist.py:152
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
@dataclass(frozen=True)
class PromptLayer:                                     # line 51
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    cacheable: Optional[bool] = field(default=None)
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...        # line 82
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer: ...  # line 96

class LayerPriority(IntEnum):                          # line 22
    IDENTITY=10; PRE_INSTRUCTIONS=15; SECURITY=20; KNOWLEDGE=30
    USER_SESSION=40; TOOLS=50; OUTPUT=60; BEHAVIOR=70; CUSTOM=80

class RenderPhase(str, Enum):                          # line 35
    CONFIGURE = "configure"; REQUEST = "request"

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:                                   # line 34
    @classmethod
    def default(cls) -> PromptBuilder: ...             # line 66  (8 layers)
    @classmethod
    def minimal(cls) -> PromptBuilder: ...             # line 80  (3 layers)
    @classmethod
    def voice(cls) -> PromptBuilder: ...               # line 86
    @classmethod
    def agent(cls) -> PromptBuilder: ...               # line 112 (default() + AGENT_BEHAVIOR_LAYER)
    @classmethod
    def rag(cls) -> PromptBuilder: ...                 # line 120 (default() − tools + 2)
    def add(self, layer: PromptLayer) -> PromptBuilder: ...     # line 165
    def remove(self, name: str) -> PromptBuilder: ...           # line 177  (no-op if absent)
    def configure(self, context: Dict[str, Any]) -> None: ...   # line 236
    def build(self, context: Dict[str, Any]) -> str: ...        # line 256

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin,
                  EventEmitterMixin, ToolInterface, VectorInterface, ABC):   # line 201
    def __init__(self, name: str = "Nav", ..., **kwargs): ...               # line 274
    #   self.rationale = kwargs.get("rationale") or getattr(self, "rationale", None) or DEFAULT_RATIONALE  # line 431
    async def _configure_prompt_builder(self) -> None: ...                  # line 1356
    #   configure_context = { ... }                                          # line 1384
    #   self._prompt_builder.configure(configure_context)                     # line 1417
    def _build_prompt(self, user_context: str = "", ..., **kwargs) -> Union[str, List]: ...  # line 1419
    async def clone_for_user(self, user_context: "UserContext") -> "AbstractBot": ...        # line 4388

# packages/ai-parrot/src/parrot/bots/chatbot.py
    def _from_db(self, botobj, key, default: str = None) -> Any: ...   # line 167
    self.language = getattr(self, "language", "en")                    # line 244
    self.language = self._from_db(bot, "language", default="en")       # line 422

# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):                           # line 152
    model = "gemini-3.5-flash"                         # line 187
    @staticmethod
    def _build_jira_prompt_builder(): ...              # line 197
    def __init__(self, **kwargs): ...                  # line 211
    async def clone_for_user(self, user_context: UserContext) -> "JiraSpecialist": ...  # line 468

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py
class BotModel(Model):                                 # line 22  (docstring lines 23–95)
    language: str = Field(default="en", required=False, ui_help="The bot's language.")  # line 245

# packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py
    language: str = Field(required=False, default="en")   # line 107
    def to_bot_kwargs(self) -> dict: ...                  # line 165
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OUTPUT_LANGUAGE_LAYER` | `_DOMAIN_LAYERS` | dict entry | `domain_layers.py:789` |
| `OUTPUT_LANGUAGE_LAYER` | `PromptBuilder.default()` | `builder.add()` | `builder.py:66`, `:165` |
| unset path | `PromptBuilder.remove()` | method call | `builder.py:177` |
| `resolve_language_name()` | `configure_context` | dict key | `abstract.py:1384` |
| `render_message()` | `CallbackResult(answer_text=…)` | call-site replacement | `jira_specialist.py:935`, `:944`, `:966` |
| `render_message()` | `send_interactive_message(text=…)` | call-site replacement | `jira_specialist.py:1077`, `:1095` |
| `GROUNDING_SENTINELS` | `JIRA_GROUNDING_LAYER.template` | `$sentinel_*` vars | `domain_layers.py:223` |
| migration | `navigator.ai_bots` | SQL | `creation.sql:64` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractBot.language`~~ — does not exist today; only `Chatbot` has it (`chatbot.py:244`, `:422`). `Agent`/`JiraSpecialist` do **not** inherit it.
- ~~`AbstractBot.default_language`~~ / ~~`JiraSpecialist.default_language`~~ — the original request's name; **not** the name this feature uses.
- ~~`output_language`~~ — no attribute, layer, context key or registry entry exists yet.
- ~~`get_domain_layer("output_language")`~~ / ~~`("language")`~~ / ~~`("locale")`~~ — not registered; raises `KeyError` (`domain_layers.py:805-818`).
- ~~`parrot.bots.prompts.language`~~ / ~~`parrot.bots.jira_messages`~~ — new in this feature; do not import before M2/M4 land.
- ~~`PromptBuilder.jira()`~~ — no such factory; use `JiraSpecialist._build_jira_prompt_builder()`.
- ~~`JiraSpecialist.system_prompt_template`~~ — removed in FEAT-138; setting it has no effect.
- ~~`JIRA_SPECIALIST_PROMPT`~~ — deleted in TASK-947; importing raises `ImportError`.
- ~~`parrot.utils.language`~~ / any ISO-639 helper — no language-code utility exists anywhere in `parrot.*`.
- ~~`import babel`~~ anywhere in `packages/` — declared at `pyproject.toml:122` but imported nowhere; there is no existing locale code to extend.
- ~~`pycountry` in `ai-parrot`~~ — scoped to `parrot-formdesigner` only (`packages/parrot-formdesigner/pyproject.toml:46`).
- ~~gettext / `.po` / `.mo` catalogs~~ — no i18n infrastructure exists.
- ~~a `language` key in `configure_context`~~ — `abstract.py:1384` does not pass one; it must be added.
- ~~per-request language override~~ — `ask()`/`ask_stream()` take no `language` parameter, and this feature adds none.
- ~~`Agent.create_speech(language=...)`~~ as a general directive — exists (`agent.py:976`, default `"en-US"`) but is **TTS-only**; do not conflate.
- ~~alembic / a migrations framework~~ — migrations are hand-written SQL in `sdd/migrations/` (e.g. `FEAT-593-ai-bots-tooling-columns.sql`); there is no alembic dependency.

### Edit Sites (Blueprint Anchors)

Verified against: `1b258f9b6`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        self.rationale = kwargs.get("rationale") or getattr(self, "rationale", None) or DEFAULT_RATIONALE` (8-space indent is part of the anchor) | `abstract.py:431` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `            "rationale": _resolve(getattr(self, "rationale", "")),` | `abstract.py:1400` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        self._prompt_builder.configure(configure_context)` | `abstract.py:1417` | 1 |
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | `        self.language = getattr(self, "language", "en")` | `chatbot.py:244` | 1 |
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | `        self.language = self._from_db(bot, "language", default="en")` | `chatbot.py:422` | 1 |
| `packages/ai-parrot/src/parrot/bots/prompts/language.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | `_DOMAIN_LAYERS: Dict[str, PromptLayer] = {` | `domain_layers.py:789` | 1 |
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | `JIRA_GROUNDING_LAYER = PromptLayer(` | `domain_layers.py:223` | 1 |
| `packages/ai-parrot/src/parrot/bots/prompts/builder.py` | MODIFY | `    def default(cls) -> PromptBuilder:` | `builder.py:66` | 1 |
| `packages/ai-parrot/src/parrot/bots/prompts/builder.py` | MODIFY | `    def voice(cls) -> PromptBuilder:` | `builder.py:86` | 1 |
| `packages/ai-parrot/src/parrot/bots/jira_messages.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | `                answer_text=f"⚠️ Error transicionando {ticket_key}",` | `jira_specialist.py:935` | 1 |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | `            answer_text=f"✅ {ticket_key} → In Progress",` | `jira_specialist.py:944` | 1 |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | `            answer_text="👍 Entendido",` | `jira_specialist.py:966` | 1 |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | `                        f"👋 *{dev.name}*, aún no has seleccionado tu ticket "` | `jira_specialist.py:1077` | 1 |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | `                        f"⚠️ *Escalación Daily Standup*\n\n"` | `jira_specialist.py:1095` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` | MODIFY | `    language: str = Field(default="en", required=False, ui_help="The bot’s language.")` | `bots.py:245` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` | MODIFY | `        language VARCHAR(10) DEFAULT 'en',` | `bots.py:89` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py` | MODIFY | `    language: str = Field(required=False, default="en")` | `users_bots.py:107` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/creation.sql` | MODIFY | `    language VARCHAR(10) DEFAULT 'en',` | `creation.sql:64` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql` | MODIFY | `    language       VARCHAR(10) DEFAULT 'en',` | `users_bots_creation.sql:66` | 1 |
| `sdd/migrations/FEAT-638-bot-language-nullable.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` | MODIFY | `    assert (REPO / CREATION_SQL).read_text(encoding="utf-8") == old_sql, "handlers/creation.sql changed"` | `test_storage_gates.py:137` | 1 |
| `packages/ai-parrot/tests/test_jira_specialist_grounding.py` | MODIFY | `SENTINEL_NOT_FOUND = "No results found for"` | `test_jira_specialist_grounding.py:200` | 1 |
| `packages/ai-parrot/tests/bots/prompts/test_jira_grounding_layer.py` | MODIFY | `    assert "No results found for" in rendered` | `test_jira_grounding_layer.py:15` | 1 |
| `packages/ai-parrot/tests/test_jira_callbacks.py` | MODIFY | `        self.assertIn("Entendido", result.answer_text)` | `test_jira_callbacks.py:84` | 1 |
| `docs/jira-specialist-prompt-layers.md` | MODIFY | `- **Do not localise the sentinel phrases**` | `docs/jira-specialist-prompt-layers.md` | 1 |
| `docs/prompts/layers-reference.md` | MODIFY | `| `jira_grounding` | `JIRA_GROUNDING_LAYER` | 65 | CONFIGURE | Jira anti-hallucination |` | `layers-reference.md:512` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `language` follows the existing personality-attribute idiom at `abstract.py:427-431`: `kwargs.get(...) or getattr(self, ...) or <default>`.
- The layer is CONFIGURE-phase so it stays prompt-cacheable under FEAT-181; `cacheable` derives from `phase` in `PromptLayer.__post_init__` (`layers.py:76-80`).
- Migrations are hand-written SQL in `sdd/migrations/`, named `FEAT-<NNN>-<slug>.sql` (precedent: `FEAT-593-ai-bots-tooling-columns.sql`). There is no alembic.
- Logging is `self.logger.warning` for an unsupported language — never `print`, and never log the raw rejected value at INFO or above alongside other configuration.

### Known Risks / Gotchas

- **A false `condition=` is reactivatable (S4, verified).** `partial_render()` returns the layer unchanged when the condition fails (`layers.py:116-117`), and `_build_prompt()` spreads `**kwargs` into the request context before `build()` (`abstract.py:1446-1455`). A request-time `language=` kwarg would therefore re-evaluate the condition against a context that now has the variable, rendering a layer that was absent at configure time — with configure-only `$placeholders` unresolved. **Mitigation**: no `condition=` at all; remove the layer in `_configure_prompt_builder()` when unset. Regression test: `test_configure_none_then_build_with_language_kwarg`.
- **Free-text operator input reaches the prompt (S3, verified).** `TabsGeneral.svelte:82-86` is an unvalidated text input and no DB-level validator exists. Passing an unknown value through raw (as the brainstorm originally proposed) would let XML, newlines or `$`-template syntax alter the system prompt. **Mitigation**: `normalize_language()` returns only an allowlisted subtag or `None`; nothing caller-controlled is ever interpolated.
- **A whole-string phrase table translates identifiers (S7, verified).** `In Progress` is embedded at `jira_specialist.py:944`, `:947` and asserted at `test_jira_callbacks.py:56`. **Mitigation**: `MessageTemplate.protected` placeholders, with a per-locale test asserting byte-for-byte survival.
- **Two bot models, two DDLs, one release gate (S2, verified).** `UserBotModel` (`users_bots.py:107`) and `users_bots_creation.sql:66` are a second, independent persistence path, and `creation.sql:64` — not the `bots.py:89` docstring — is the executed DDL. FEAT-621 AC17 (`test_storage_gates.py:136-137`) pins both to the merge-base and will fail until rebaselined. M6 is marked `parallel: false` for this reason.
- **Unset is not "today" for Python-authored text.** Today's literals are Spanish; unset now renders English. The affected deployment must set `language='es'` explicitly as part of rollout. This is a deliberate, operator-visible behavior change and needs a release note.
- **`minimal()` is an opt-out, not an oversight (S5).** It is exposed as a preset (`presets.py:30`) and an explicit `prompt_builder=` can omit any layer (`jira_specialist.py:234`). The contract is tested, not assumed.
- **Localizing the sentinels reverses a FEAT-138 anti-pattern.** `docs/jira-specialist-prompt-layers.md` currently forbids it in as many words; the doc must change in the same commit as the layer, or it becomes actively misleading.
- **Verification bound.** All tests assert the *directive renders*, never that the model obeyed it. If production shows non-compliance, brainstorm Option B (write-side gate in `JiraToolkit`) is the escalation path.
- **FEAT-637 interaction.** Jinja-templated descriptions/comments are authored by a template file, not the LLM, so this directive cannot govern them. This spec declares the convention FEAT-637 should adopt — template lookup falls back `<name>.<lang>.j2` → `<name>.j2` — and implements none of it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | None. The ISO→display-name map is a 2-entry dict; `babel>=2.16.0` (`pyproject.toml:122`) is deliberately **not** adopted, since an allowlist of supported languages is required anyway (S3). |

---

## 8. Open Questions

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Artifacts only, or the whole conversation? — *Resolved in brainstorm*: artifacts follow the configured language; chat replies follow the user; quoted Jira content stays verbatim.
- [x] Where does the directive live? — *Resolved in brainstorm*: bot-level on `AbstractBot`; JiraSpecialist is the first consumer, not the owner.
- [x] Static or per-request? — *Resolved in brainstorm*: config-only, CONFIGURE phase, prompt-cacheable. No per-request override in v1.
- [x] English-sentinel vs. user-language collision? — *Resolved in brainstorm*: localize the sentinels and update tests/docs.
- [x] Relationship to `Chatbot.language`? — *Resolved in brainstorm*: promote it to `AbstractBot` as a hard cut; one concept, no parallel attribute.
- [x] Value format and meaning of unset? — *Resolved in brainstorm*: ISO 639-1; unset = today's behavior for LLM-authored text.
- [x] Reconciling the promoted attribute with Chatbot's `"en"` default? — *Resolved in brainstorm*: the default becomes `None` everywhere, including `_from_db` and the model field/DDL.
- [x] Which Jira content does it apply to? — *Resolved in brainstorm*: prose fields plus an explicit never-translate list stated in the layer.
- [x] Which builders install the layer? — *Resolved in brainstorm*: `default`, `agent`, `rag`, `voice`.
- [x] Standup/HITL — artifact or chat? — *Resolved in brainstorm*: artifact; they follow the configured language.
- [x] Sentinel mechanism and v1 languages? — *Resolved in brainstorm*: an explicit table, English + Spanish, unknown falls back to English.
- [x] Are the hardcoded Spanish strings in scope? — *Resolved in brainstorm*: yes, rewritten to English defaults routed through the catalog.
- [x] Verification approach? — *Resolved in brainstorm*: prompt-render assertions only; this proves presence, not compliance.
- [x] Should `minimal()` install the layer? — *Resolved in brainstorm*: no; it stays a 3-layer stack and the opt-out is tested.
- [x] Does the DDL change need a row migration? — *Resolved in brainstorm*: yes, existing `'en'` rows are NULLed.
- [x] FEAT-637 interaction? — *Resolved in brainstorm*: this spec declares the `<name>.<lang>.j2` → `<name>.j2` convention; FEAT-637 implements it.
- [x] Unset semantics for Python-authored strings, given today's literals are Spanish? — *Resolved during spec design research (S1)*: unset renders English; the affected deployment sets `language='es'` explicitly at rollout; `test_jira_callbacks.py:84` is updated.
- [x] FEAT-621 AC17 pins the `ai_bots` DDL — how do we proceed? — *Resolved during spec design research (S2)*: update the DDL in `bots.py`, `creation.sql` and `users_bots_creation.sql`, and rebaseline the gate as part of this feature.
- [x] Regional variants — validated or free-form? — *Resolved during spec design research (S3)*: bounded. Normalized to the base subtag and checked against an allowlist; unsupported values resolve to `None` with a warning, never raw passthrough.
- [x] Should a future language (e.g. `pt`) be addable purely as a catalog entry, or does it need a contribution guide section? The design makes it a 2-dict edit; whether that is documented is open. — *Owner: Jesus*: need a contribution guide section

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted brainstorm**
> (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.160.0, reasoning_effort=high)
> · Status: completed · Transcript: `sdd/state/FEAT-638/design_research/`
> All 21 `affected_paths` passed repository containment and `test -e`; every substantive
> claim was independently re-verified in source before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define unset-language behavior for Python-authored messages (risk) | CONFIRM | Real contradiction — today's literals are Spanish (`jira_specialist.py:966`), so "unset = today" and "unset → English" cannot both hold. User resolved: unset → English, Spanish deployment sets `language='es'` at rollout. | §2 Overview, §5, §7 |
| S2 | Cover all persistence paths and existing-row migration semantics (architecture) | CONFIRM | Verified: `UserBotModel.language` (`users_bots.py:107`), `users_bots_creation.sql:66`, the executed DDL at `creation.sql:64` and `to_bot_kwargs()` (`manager.py:1183`) were all missing from the brainstorm; FEAT-621 AC17 pins both DDLs. | §2 Integration Points, §3 M6, §6 |
| S3 | Do not inject raw language input into the system prompt (risk) | CONFIRM | Verified: `TabsGeneral.svelte:82-86` is free text with no validator; raw passthrough is a prompt-injection surface. Replaced by a bounded allowlist; also resolves the last open question. | §2 Overview, §3 M2, §5, §7 |
| S4 | Freeze or remove a false CONFIGURE-phase layer (architecture) | CONFIRM | Verified reachable: `partial_render()` returns the layer unchanged on a false condition (`layers.py:116-117`) and `_build_prompt()` spreads `**kwargs` into the request context (`abstract.py:1446-1455`). | §3 M3, §5, §7 |
| S5 | Specify built-in factory coverage and custom-builder opt-out (architecture) | CONFIRM | Verified: `minimal` is a preset (`presets.py:30`) and `JiraSpecialist` accepts arbitrary builders (`jira_specialist.py:234`); the exclusion is now a tested contract. | §3 M3, §4 |
| S6 | Update the omitted grounding tests and documentation (testing) | CONFIRM | Verified: `test_jira_grounding_layer.py:15-16` asserts the English sentinels directly and `docs/prompts/layers-reference.md:435,512` documents the layer — both absent from the brainstorm's impact table. | §2, §4, §6 |
| S7 | Represent localized operational text as protected templates (api) | CONFIRM | Verified: the status `In Progress` is embedded at `jira_specialist.py:944`, `:947` and asserted at `test_jira_callbacks.py:56`; whole-string entries would translate it. | §3 M4, §5 |
| S8 | Test the rendered prompt and callbacks rather than only constants or fakes (testing) | CONFIRM | Verified: grounding tests stub `agent.ask` with hand-written replies and the layer test inspects a constant only; a locale matrix at builder and `_build_prompt()` level is what actually exercises the directive. | §4, §5 |
| S9 | Consider keeping FEAT-138 sentinel tokens invariant (alternative) | REJECT | This exact alternative was put to the user in brainstorm Round 2 ("Sentinels stay English") and deliberately rejected in favour of localizing them. Re-opening it would be the reviewer overriding a decision the user already took. | — |

Summary: **8** confirmed · **1** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree per spec — `.claude/worktrees/feat-FEAT-638-jiraspecialist-agent-multilang`. The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M1 (reads `self.language` set at `abstract.py:431`) and → M2 (calls `normalize_language`/`resolve_language_name`)
  - M4 → M2 (`render_message` falls back via `FALLBACK_LANGUAGE`)
  - M5 → M2 (sentinel lookup keyed by normalized code) and → M3 (shares the `configure_context` injection at `abstract.py:1384`)
  - M6 → M1 (model default must match the attribute default)
  - M1 and M2 have no edge between them and are expected to run concurrently.
- **Shared files** (their tasks serialize):
  - `abstract.py` — M1 (attribute, `:431`) and M3/M5 (`configure_context`, `:1384`/`:1417`)
  - `domain_layers.py` — M3 (registry, `:789`) and M5 (grounding layer, `:223`)
  - `prompts/language.py` — M2 creates it; M5 reads `SUPPORTED_LANGUAGES` from it
- **Exclusive resources**: **M6** is `parallel: false`. It mutates two DDL files and rebaselines another feature's release gate (FEAT-621 AC17), which is shared state outside its own module.
- **Cross-feature dependencies**: none blocking. FEAT-637 (`jiratoolkit-template-support`) is conceptually adjacent but touches only `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — no file overlap. FEAT-621's gate test is modified here, not depended upon.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-07 | Jesus Lara | Initial draft from accepted brainstorm + codex design research (8 confirmed / 1 rejected) |
