# F015 — ⚠️ Muse Spark spends most of its output budget on reasoning

Live `usage` for a prompt whose entire answer was the word `pong`:

**Chat Completions**
```json
{"completion_tokens": 210, "prompt_tokens": 12, "total_tokens": 222,
 "completion_tokens_details": {"reasoning_tokens": 199},
 "prompt_tokens_details": {"cached_tokens": 0}}
```
**Responses**
```json
{"input_tokens": 12, "output_tokens": 153,
 "output_tokens_details": {"reasoning_tokens": 142}, "total_tokens": 165}
```

**199 of 210** and **142 of 153** output tokens were reasoning — for a
four-character answer. Docs corroborate: *"`max_tokens` ... cap reasoning
tokens plus visible output tokens combined. If the model spends most of the
budget on reasoning, the visible response may be truncated."*

**Implication (high impact, easy to get wrong)**: a conventional
`max_tokens=256` default will frequently return **empty or truncated visible
text** on Muse Spark. `MetaClient` needs a generously high default output
budget, and its docs must say why. This is the single most likely source of
confusing "the model returned nothing" bug reports.

Reasoning tokens bill at the same rate as visible output tokens.
