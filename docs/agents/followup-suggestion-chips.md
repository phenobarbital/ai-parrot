# Follow-up Suggestion Chips (FEAT-752)

Agents can attach a short row of follow-up "chips" to every answer: ready-made next questions, "View as table / chart /
KPI" re-presentations and an "Explain this" action. Chips are **opt-in per agent**, cost nothing unless enabled, and
travel as one additive `suggestions` key that every client can ignore.

This page is for agent authors, operators and frontend developers. It documents what shipped; the design record is
`sdd/specs/followup-suggestion-chips.spec.md`.

## 1. What you get

Each chip is a small object. A chip's `prompt` is sent through the normal chat path when it is clicked; the other
fields tell the client how to present it and what to send.

```json
{
  "input": "...", "output": "...",
  "metadata": {"turn_id": "...", "suggestions": {"count": 3, "...": "..."}},
  "suggestions": [
    {"label": "vs last month", "prompt": "Compare the same figures against the previous month",
     "output_mode": null, "kind": "followup", "source": "skill", "action": null},
    {"label": "View as table", "prompt": "Show the previous answer as a table",
     "output_mode": "structured_table", "kind": "presentation", "source": "provider", "action": null},
    {"label": "Explain this", "prompt": "Explain this answer", "output_mode": null,
     "kind": "action", "source": "provider", "action": "explain"}
  ]
}
```

| Field | Meaning |
|---|---|
| `label` | Chip text, at most 40 characters. |
| `prompt` | Text sent as a new chat turn on click, at most 500 characters. |
| `output_mode` | Optional explicit output mode for the click turn (`structured_table`, `structured_chart`, `card`, ...). |
| `kind` | `followup`, `presentation` or `action`. |
| `source` | Who produced it: `llm`, `skill` or `provider`. |
| `action` | `"explain"` when `kind == "action"`, otherwise `null`. Only `explain` is allowed. |

`Suggestion` rejects unknown keys (`extra="forbid"`), blank text, and an `action` that does not match its `kind`.

## 2. Opt-in per agent

Nothing changes for an agent that does not opt in: `AIMessage.suggestions` stays `[]` and the response bodies are
unchanged.

| Kwarg | Default | Effect |
|---|---|---|
| `enable_suggestions` | `False` | Turns on the **deterministic** lane: presentation chips and the explain chip. No LLM call. |
| `suggest_followups` | `False` | Also turns on the **LLM** lane (one extra call per answer). Implies `enable_suggestions`. |
| `suggestion_timeout_s` | `4.0` | Timeout for each provider, in seconds. |
| `max_suggestions` | `6` | Upper bound on chips per answer. |
| `suggestion_model` | `None` | Model for the chip call. `None` uses the client's lightweight model (see section 7). |
| `presentation_modes` | all of table, chart, KPI | Restricts which "View as ..." chips are offered. Set only when passed, so a class attribute of the same name still wins. |

Python:

```python
agent = BasicAgent(
    name="sales",
    enable_suggestions=True,
    suggest_followups=True,
    suggestion_model="gemini-flash",          # optional: cheap model for the chip call
    max_suggestions=4,
    presentation_modes=["structured_table", "structured_chart"],
)
```

YAML agent definition (`agents/agents.yaml`). Keys under `config:` are passed to the agent's constructor verbatim, so
no whitelist needs updating:

```yaml
agents:
  - name: "SalesAgent"
    class_name: "BasicAgent"
    module: "parrot.bots.agent"
    enabled: true
    config:
      enable_suggestions: true
      suggest_followups: true
      suggestion_timeout_s: 3
      max_suggestions: 4
```

## 3. Skill-declared chips

A skill can declare its own chips in its frontmatter. They are emitted, with `source: "skill"`, only when that skill is
the skill the `/trigger` activated **for the current turn**. The skill lane is always on and costs nothing when no
skill declares chips.

```yaml
---
name: sales-analyst
description: Monthly sales analysis helpers
triggers: [/sales]
suggestions:
  - label: "vs last month"
    prompt: "Compare the same figures against the previous month"
  - label: "As KPI"
    prompt: "Show the headline number as a KPI card"
    output_mode: card
---
```

- A chip with an `output_mode` becomes `kind: "presentation"`; without one it is `kind: "followup"`.
- A chip whose `output_mode` is not a known mode is dropped with a warning; its siblings are kept.
- The turn skill is a request-local value (`parrot.skills.tenancy.current_turn_skill()`). It survives the system-prompt
  build, which clears the active skill, and is restored when `ask()` / `ask_stream()` finish, so it never leaks into
  the next request.
- Per-tenant skill shadowing and `global_only` behave exactly as before; chips follow whichever skill won.

## 4. Writing a provider

A provider is any object with a `name`, a `lane` and an async `suggest()`. The protocol is `runtime_checkable`.

```python
from parrot.bots.suggestions import SuggestionContext, SuggestionProvider
from parrot.models import Suggestion


class VsLastMonthProvider:
    """lane="deterministic": offer a comparison chip when the answer is a time series."""

    name = "vs_last_month"
    lane = "deterministic"

    async def suggest(self, ctx: SuggestionContext) -> list[Suggestion]:
        if not ctx.response.data:
            return []
        return [
            Suggestion(
                label="vs last month",
                prompt="Compare the same figures against the previous month",
                source="provider",
            )
        ]


assert isinstance(VsLastMonthProvider(), SuggestionProvider)
agent.register_suggestion_provider(VsLastMonthProvider())               # appended within its lane
agent.register_suggestion_provider(VsLastMonthProvider(), prepend=True)  # or run first within its lane
```

`SuggestionContext` carries `question`, `response` (the `AIMessage`), `output_mode`, `bot`, `user_id`, `session_id`
and `tenant`.

| Lane | Runs when | Built-in providers |
|---|---|---|
| `skill` | always | `SkillSuggestionProvider` |
| `deterministic` | `enable_suggestions` | `PresentationSuggestionProvider`, `ExplainSuggestionProvider` |
| `llm` | `suggest_followups` | `LLMSuggestionProvider` |

Lane order is fixed (`skill`, `deterministic`, `llm`); registration order is kept within a lane. Registering a provider
with an existing `name` replaces it. The engine guards every provider: an exception or a timeout yields no chips for
that provider and never breaks the answer.

After collection the engine post-processes in this order: drop chips whose `output_mode` has no registered renderer,
de-duplicate by label (case-insensitive, first wins), cap LLM-source chips at 4, then cap the total at
`max_suggestions`.

The built-in rules:

- **Presentation** chips need tabular data (a non-empty list of dicts, or a non-empty DataFrame-like object). The mode
  the answer is already in is skipped, and so is any mode without a renderer. Order: table, chart, KPI.
- **Explain** is offered only for tabular data **and** a bot that has a callable `followup` (today `BasicAgent`).
- **LLM** chips are always rebuilt as `source: "llm"`, `kind: "followup"`, with no `output_mode` and no `action`,
  whatever the model returned.

## 5. Wire contract and click contract

The `suggestions` key appears in the JSON body, the A2UI JSON body, the infographic JSON body and the final stream
envelope. It is **omitted when the list is empty**, so a response from an agent that does not opt in is byte-for-byte
what it was before.

How a client should handle a click:

- `kind != "action"`: send `prompt` as a new chat turn, with `output_mode` when it is present.
- `action == "explain"`: send the existing explain request (`query`, `turn_id`, `data`) for the message the chip is
  under. The agent routes it to `bot.followup()`.
- Any other action: ignore the chip. Never send an unknown action as a chat turn.
- A client that cannot run explain should hide `kind == "action"` chips.

Chips are a property of the **live turn**. They are not stored with the conversation, so reloading a conversation shows
no chips.

## 6. Channel behaviour

| Channel | Behaviour |
|---|---|
| Admin UI (`AgentChat`) | Renders chips under finished assistant answers (never under user messages or while streaming) and routes clicks as described above. |
| Telegram | Renders **non-action** chips as inline buttons when `suggestion_buttons: true`. See below. |
| Teams, A2A | Not implemented. They ignore the field. |

Telegram is opt-in per bot and works in **private chats** only:

```yaml
agents:
  MyAgent:
    chatbot_id: my_bot_id
    suggestion_buttons: true           # default false
    suggestion_button_ttl_s: 86400     # default 24 hours
```

- After the reply, the bot sends a "💡 Follow-ups:" message with at most 6 buttons, two per row, labels cut at 40
  characters. `explain` chips are skipped because Telegram has no explain path.
- Telegram limits `callback_data` to 64 bytes, so a button carries only `sg:<token>`. The chip lives in a TTL store
  keyed by that token.
- A press replays the stored prompt as a new turn for the **same user in the same chat**. A press by anyone else, in a
  different chat, from an unauthorised chat, or after the TTL expires is refused with a short message and nothing is
  sent to the agent.
- Pressing a button again replays the prompt again; tokens are not consumed.

## 7. Cost, latency and metadata

- The LLM lane is **one** `AbstractClient.invoke()` call per answer, through `bot.get_client()`, asking for a
  structured `SuggestionBatch`: `max_tokens=256`, `temperature=0.3`, the answer truncated to 2000 characters. It never
  calls `ask()`. Without `suggestion_model` the client's lightweight model is used.
- A failed, malformed or timed-out call yields no LLM chips; the answer is unaffected.
- On a normal (non-trailer) stream, chips are attached **before** the final envelope, so the stream ends up to
  `suggestion_timeout_s` later than it otherwise would. The text is already on screen by then. Use the stream trailer
  (section 8) to remove that delay.
- When the engine runs, the response metadata gets a `suggestions` entry. It is plain JSON:

```json
{
  "enabled_lanes": ["skill", "deterministic", "llm"],
  "count": 4,
  "providers": {
    "skill": {"status": "ok", "count": 1, "elapsed_ms": 0.1},
    "presentation": {"status": "ok", "count": 2, "elapsed_ms": 0.2},
    "explain": {"status": "skipped", "count": 0, "elapsed_ms": 0.0},
    "llm": {"status": "ok", "count": 1, "elapsed_ms": 812.4}
  },
  "llm": {"model": "gemini-flash", "usage": {"prompt_tokens": 310, "completion_tokens": 42}, "elapsed_ms": 812.4}
}
```

`status` is `ok`, `timeout`, `error` or `skipped` (lane not enabled). `llm` is `null` unless the LLM provider ran
successfully.

The built-in LLM provider reports its cost through the per-turn context (`ctx.scratch["llm_cost"]`), so simultaneous
turns on the same agent keep their own `metadata["suggestions"]["llm"]` record. A custom provider that instead exposes a
`last_cost` attribute is read from instance state shared by every request, and two simultaneous turns can swap those
records; set `per_call_cost = True` on the provider and write the record to `ctx.scratch["llm_cost"]` to avoid that.

## 8. Stream trailer

By default chips ride in the final stream envelope. A client that sends `suggestions_trailer: true` in the stream
request gets the answer finished first and the chips afterwards:

```
<text chunks>\n\x00{envelope}\n\x00{"suggestions": [...], "turn_id": "..."}
```

- The response header becomes `X-Parrot-Stream: chunked-aimessage+suggestions`.
- The envelope carries **no** `suggestions` on this path; they are only in the trailer frame.
- The trailer is written only when the list is non-empty. If the chip task fails or does not finish within
  `suggestion_timeout_s + 1` seconds, no trailer is written and the stream still closes normally.
- If the client disconnects, or the stream fails, the running chip task is cancelled so no LLM call is left running.
- Without the flag the wire is unchanged: one NUL, one envelope, and `suggestions` inside the envelope.

To enable this the handler passes `defer_suggestions=True` to `ask_stream()`, which schedules the chip work as a task
and parks it on the final `AIMessage` instead of awaiting it. Nothing extra is yielded by `ask_stream()`, so other
consumers of that generator are unaffected.

**Parsing frames.** Every NUL starts a new JSON frame; frame 1 is the envelope and later frames are trailers. The admin
UI's `src/lib/api/stream.ts` is the reference implementation: `consumeStream` yields `done` as soon as the second NUL
proves the envelope complete (or at the end of the stream when there is only one frame), then yields
`{type: "suggestions", suggestions, turn_id}` for a trailer that carries a `suggestions` array. Any other trailing
frame, such as a late `{"error": ...}`, is ignored. JSON text never contains a raw NUL, so splitting on it is safe.

`AgentChat` sets the flag only on the agent stream, never on bot chat. It finishes the bubble on `done` and patches the
chips onto that bubble when the trailer arrives.

## 9. Agent Studio settings

The agent form's **Capabilities** tab has a **Follow-up suggestions** group with the five settings: suggestion chips,
LLM follow-up suggestions, timeout, maximum chips and suggestion model. `presentation_modes` is not exposed in Studio;
set it in code or YAML.

Agents defined in the database read these settings from new columns on `navigator.ai_bots`, and `BotModel` /
`to_bot_config()` and the database bot builder carry them to the agent. Defaults match the constructor defaults
(`FALSE`, `FALSE`, `4.0`, `6`, `NULL`).

**Operator step: apply the migration before deploying the code.** `BotModel` selects these columns, so reading a bot
fails if one is missing.

```bash
psql "$DATABASE_URL" -f sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql
```

The script is idempotent (`ADD COLUMN IF NOT EXISTS`) and runs in one transaction, so it is safe to re-run on any
environment. It ends with a commented rollback block that drops the five columns.
