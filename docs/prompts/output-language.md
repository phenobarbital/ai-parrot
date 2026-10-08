# Output Language (FEAT-638)

Every bot has a `language` attribute (ISO 639-1). It controls the language of the
**artifacts the agent writes** — tickets, issue descriptions, comments, reports,
standup and escalation messages — while the agent keeps **replying to the user in
the language the user wrote in**.

```python
agent = JiraSpecialist(language="en")        # Spanish chat, English Jira tickets
```

It can also be a class attribute (`language = "es"`) or the `language` column of a
DB-backed bot (`navigator.ai_bots` / `navigator.users_bots`).

## Behavior

| `language` | Prompt | Python-authored messages | Grounding sentinels |
|---|---|---|---|
| unset (`None`) | unchanged — the directive layer is removed | English | English |
| `"en"` / `"es"` | `OUTPUT_LANGUAGE_LAYER` directive | that language | that language |
| `"es-MX"` | treated as `"es"` (base subtag) | Spanish | Spanish |
| unsupported (`"fr"`, garbage) | treated as unset, logged at WARNING | English | English |

The directive always keeps identifiers verbatim (issue keys, project keys, status and
transition names, labels, components, usernames, JQL, URLs, code blocks) and keeps
quoted existing content in its original language.

Supported today: `en` (English), `es` (Spanish).

**Builders**: `default()`, `agent()`, `rag()`, `voice()` and the `identity` preset
install the layer; `minimal()` deliberately does not — add it yourself with
`builder.add(get_domain_layer("output_language"))`.

**Verification bound**: the tests prove the directive is present in the rendered
prompt. They do not prove the model obeys it.

## Adding a language

A language is three catalog entries — no other code changes. Example for Portuguese (`pt`):

1. `parrot/bots/prompts/language.py` — add `"pt": "Portuguese"` to `SUPPORTED_LANGUAGES`.
2. `parrot/bots/prompts/domain_layers.py` — add a `"pt"` row to `GROUNDING_SENTINELS`
   with both `not_found` and `error`. These are assertion targets; keep them short and literal.
3. `parrot/bots/jira_messages.py` — add a `"pt"` block to `JIRA_MESSAGES` defining
   **every** key the other languages define, with the **same `protected` set** per key.
   Never translate a protected placeholder (`${ticket_key}`, `${status}`, `${name}`,
   `${names}`, `${hours}`): their values are identifiers or data, substituted verbatim.
4. Run the catalog tests — they fail until all three catalogs agree:
   `test_language.py`, `test_output_language_layer.py`, `test_jira_grounding_layer.py`,
   `test_jira_messages.py`, `test_output_language_docs.py`.
5. Add the language to the "Supported today" line above.

**Templated Jira writes (FEAT-637)**: Jinja templates are authored by files, not the
LLM, so this directive cannot reach them. Localize them by convention — template lookup
falls back from `<name>.<lang>.j2` to `<name>.j2`.
