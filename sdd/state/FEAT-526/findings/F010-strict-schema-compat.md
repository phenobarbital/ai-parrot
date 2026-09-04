# F010 — `strict: true` is accepted by Meta, and parrot's normalizer conforms

**External** (`docs/structured-output.md` § Strict mode; `docs/tool-calling.md` § Strict):
- `strict` defaults to **`false`** on all four surfaces.
- `strict: true` requires the strict subset: root a plain object;
  `additionalProperties: false` on every object; `required` lists every
  property; **no `allOf`/`oneOf` anywhere**; `anyOf` only below the root.
- Violating the subset → HTTP 400 **only when `strict: true`**.
- Independently: recursive/`$ref`-cycle schemas → HTTP 400 on every surface.
- Structured output is schema-constrained regardless of `strict`.

**Codebase check**:
- `base.py:1399` — for `ToolFormat.OPENAI`, tools go through
  `_make_openai_strict_tool()`.
- `base.py:1269-1293` — that helper forces `type: object`, runs
  `_oai_normalize_schema()` recursively, then sets `fn["strict"] = True`.

**Conclusion**: parrot always sends `strict: true` on the OPENAI tool format,
and its normalizer targets exactly OpenAI's strict subset — which Meta
explicitly says its own subset is *"modeled on"*. So `ToolFormat.OPENAI` can be
inherited unchanged (unlike Groq, which needed `ToolFormat.GROQ` because it
*rejects* `strict`).
**Residual risk (medium)**: any tool whose schema carries `allOf`/`oneOf` or a
`$ref` cycle will 400 under `strict: true` where omitting `strict` would pass.
Needs a real-schema test, not just an assumption.
