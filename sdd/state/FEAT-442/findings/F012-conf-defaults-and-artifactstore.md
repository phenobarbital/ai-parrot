# F012 — Config defaults + ArtifactStore keying (evidence for open questions)
**Query**: R007, R008 · **Confidence**: high

- `conf.py:309` `CREW_RESULT_STORAGE` default **documentdb**; :310 PG DSN separate (`CREW_RESULT_STORAGE_PG_DSN`); :103 `PARROT_SCHEMA` static fallback 'navigator'. Open question U-crew-storage stands: shared deployment must pin `CREW_RESULT_STORAGE=postgres` or tenant data lands in one shared DocumentDB collection.
- `storage/artifacts.py:27` ArtifactStore keyed `(user_id, agent_id, session_id)` throughout (:48-60, :79-85, :120-134) — no tenant dimension. Claim holds.
