---
id: F005
query_id: Q005
type: read
intent: Brain retrieval and consolidation need structured provenance
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F005 — Brain retrieval and consolidation need structured provenance

## Summary

BrainStore.search returns packed text from FTS, not a typed list of injected memory IDs. remember derives page identity from title/category, while WikiPageRecord has no metadata field. DreamCycleRunner collects by importance or lesson text, skips consolidated episodes and advances a created-at watermark. Promotion counts distinct cycles, not verified outcomes. A state sidecar must survive rewriting/copying; re-distillation needs versioned identity and recovery of old episodes below the watermark.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/dream/brain.py`
  lines: 50-149
  symbol: `BrainStore.remember / search`
  excerpt: |
                self.storage_dir, wiki_name=wiki_name, backend="sqlite"
            )

        async def remember(

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 409-455
  symbol: `WikiPageRecord`
  excerpt: |
    class WikiPageRecord(BaseModel):
        """A single wiki page row in the retrieval plane.

        Attributes:

- path: `packages/ai-parrot/src/parrot/memory/dream/runner.py`
  lines: 180-225
  symbol: `DreamCycleRunner.run_cycle`
  excerpt: |
                    report.pages_written.append(page_id)

                    if page_id not in reinforced_this_cycle:
                        state.reinforcement_counts[page_id] = (

- path: `packages/ai-parrot/src/parrot/memory/dream/runner.py`
  lines: 237-269
  symbol: `DreamCycleRunner._collect`
  excerpt: |

            Sorted ascending by ``created_at`` so that group-cap deferral and
            the watermark-advance rule interact correctly: episodes deferred
            past the cap are always newer than the advanced watermark, so

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
