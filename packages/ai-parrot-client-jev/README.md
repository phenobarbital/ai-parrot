# ai-parrot-client-jev

TypeSafe AI **System One** client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot), targeting the
**Jev** model.

Jev is not a text generator: you send it *state* (a string or JSON document)
plus typed *questions* and it returns structured answers with calibrated
probabilities — a `choice` from a fixed set, a `score` on an ordered rubric,
or a `noul` (yes/no) probability. `parrot.clients.jev.JevClient` maps that
contract onto the `AbstractClient` interface:

- `ask(prompt, questions=...)` — the prompt (plus optional system prompt and
  conversation history) becomes the state; the answers come back as an
  `AIMessage` whose `output` / `structured_output` is a `SystemOneResponse`.
- `invoke(prompt, output_type=MyModel)` — a Pydantic model is translated into
  questions (`bool` → noul, `Literal`/`Enum` → choice, `int`/`float` with
  `criteria` levels → score) and the answers are validated back into it.
- `system_one(state, questions)` — the raw, typed API call.

```bash
uv pip install ai-parrot-client-jev
export TYPESAFE_API_KEY=...
```

```python
from parrot.clients.jev import JevClient, Choice, Noul, Score

client = JevClient()  # reads TYPESAFE_API_KEY; calls jev-latest by default
ticket = (
    "Hi, I've been trying to connect my Stripe account for 3 days and it keeps "
    "failing. I'm losing sales. Please help ASAP."
)
response = await client.system_one(
    state=ticket,
    questions={
        "department": Choice(
            instructions="Which team should handle this",
            criteria={
                "billing": "Payment or subscription issues",
                "technical": "Bugs or integration problems",
                "sales": "Pricing or account questions",
            },
        ),
        "frustration": Score(
            instructions="How frustrated the customer appears",
            criteria=["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
        ),
        "is_urgent": Noul(instructions="The message conveys urgency or time-sensitivity"),
    },
)
response.answers["department"].choice   # "billing"
response.answers["frustration"].score   # 1.035
response.answers["is_urgent"].noul      # 0.999
```

Models (`JevModel`): `jev-latest` (default alias, stable), `jev-preview`
(alias, newest build), `jev-1.13.0` (versioned). Text input only; 64k tokens
per request. Output tokens are free.

Registers itself with `LLMFactory` under the `jev` and `typesafe` provider
keys via the `parrot.clients` entry-point group.
