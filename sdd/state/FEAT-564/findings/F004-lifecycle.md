---
id: F004
query_id: Q004
type: read
intent: Client and job ownership
executed_at: 2026-09-17T01:24:16Z
parent_id: null
depth: 0
---

# F004 — Client and job ownership

## Summary

get_client creates fresh SDK clients; direct generation calls are not cache-owned. Context exit closes the optional aiohttp session only. Job execution has no enforced deadline. Fix generation-scoped ownership and handler deadlines without a broad base-client refactor.

## Citations

- packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630-700 — GoogleGenAIClient.get_client, close.
- packages/ai-parrot/src/parrot/clients/base.py:1158-1171,1282-1300 — AbstractClient.__aenter__, __aexit__, close_all.
- packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:209-277 — JobManager.execute_job, _run_job.
