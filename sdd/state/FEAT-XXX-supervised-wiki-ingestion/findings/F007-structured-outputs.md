# F007 — Structured-output infrastructure exists at two levels

- `packages/ai-parrot/src/parrot/models/outputs.py:67` —
  `class StructuredOutputConfig`.
- `packages/ai-parrot/src/parrot/clients/base.py:1476-1640` — AbstractClient
  accepts `structured_output: Union[type, StructuredOutputConfig, None]` on
  ask/completion paths.
- `packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py:93-101` —
  `adapter.ask_structured(prompt, output_type=IngestedMarkdown, ...)` shows
  the adapter-level pattern in this exact subsystem.
- Implication: `TriageOutput` (see `references/schemas.py`) plugs in with no
  new infrastructure.

Method: grep + targeted reads.
