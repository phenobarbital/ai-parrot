---
id: F002
intent: Locate the analogous two-phase flow in GoogleGenAIClient.ask_stream()
query_ids: [Q002]
---

# F002 — Two-phase gate in `ask_stream()`

`ask_stream()` mirrors the `ask()` strategy with a slightly different shape.

## Citations

- `packages/ai-parrot/src/parrot/clients/google/client.py:2846-2854` — initial
  config: schema is applied ONLY when no tools are in play:

  ```python
  schema_config = None
  if structured_output and not _use_tools:
      schema_config = (
          structured_output
          if isinstance(structured_output, StructuredOutputConfig)
          else self._get_structured_config(structured_output)
      )
      if schema_config:
          self._apply_structured_output_schema(generation_config_args, schema_config)
  ```

- `packages/ai-parrot/src/parrot/clients/google/client.py:3020-3084` — the
  post-stream reformat: after the streaming loop finishes, if
  `structured_output and final_text` and tools were used, a SECOND
  `generate_content` call is made against `self._reformat_model`:

  ```python
  if structured_output and final_text:
      if _use_tools:
          try:
              # fast-path JSON detect
              ...
              if final_output is None:
                  struct_cfg = {"response_mime_type": "application/json"}
                  ...
                  structured_response = await self.client.aio.models.generate_content(
                      model=reformat_model,
                      contents=[{"role": "user", "parts": [{"text": format_prompt}]}],
                      config=GenerateContentConfig(**struct_cfg)
                  )
                  ...
          except Exception as e:
              self.logger.error(f"Streaming structured output reformat failed: {e}")
      else:
          try:
              final_output = await self._parse_structured_output(final_text, structured_output)
          except Exception:
              pass
  ```

## Notes

- Same shape as `ask()` but for streaming. The same gate decision applies.
- Note line 2843: `if gemini_tools: generation_config_args["tools"] = gemini_tools`
  — tools always go into the config when present. To enable combined mode,
  the schema simply needs to also go in when `_use_tools and structured_output`.
- The post-loop reformat block at 3020-3084 should be **skipped** in combined
  mode (the streamed text already contains the schema-compliant JSON).
