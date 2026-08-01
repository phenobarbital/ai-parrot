# F004 — The LLM ingest plane: WikiIngestOrchestrator → TwoStepIngester

- `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:69-127` —
  `WikiIngestOrchestrator.ingest(source_path, wiki_config)`: registry check →
  load → `PageIndexToolkit.insert_content()` (TwoStepIngester inside) →
  WikiStore upsert (`replace_source_slice`) → optional GraphIndex mirror →
  manifest update → bookkeeper log. All async, DI-friendly (mockable).
- `packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py:43-108` —
  `TwoStepIngester`: Step 1 CoT analysis on a **lightweight adapter**, Step 2
  `ask_structured(output_type=IngestedMarkdown)` on the heavy adapter.
  `ingest(content, hint=None)` **already accepts a `hint`** — a triage
  briefing can be forwarded here so triage work is not wasted.
- Natural insertion point for supervised ingestion: a "Step 0" gate before
  `insert_content`, or a pre-pipeline router that decides whether
  `WikiIngestOrchestrator.ingest` is called at all.

Method: direct read of both files.
