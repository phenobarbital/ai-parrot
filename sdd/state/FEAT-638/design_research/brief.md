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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/bots/abstract.py
packages/ai-parrot/src/parrot/bots/chatbot.py
packages/ai-parrot/src/parrot/bots/jira_specialist.py
packages/ai-parrot/src/parrot/bots/prompts/layers.py
packages/ai-parrot/src/parrot/bots/prompts/builder.py
packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
packages/ai-parrot/src/parrot/bots/prompts/__init__.py
packages/ai-parrot/tests/test_jira_specialist_grounding.py
packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py
packages/ai-parrot-server/src/parrot/handlers/models/bots.py
docs/jira-specialist-prompt-layers.md

### Questions still open in the exploration document
- [ ] Should regional variants (`es-MX`, `pt-BR`) be validated against a known list, or accepted free-form with a warning? Current design says free-form + warning. — *Owner: Jesus*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
