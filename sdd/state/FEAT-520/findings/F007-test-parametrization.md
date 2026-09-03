# F007 — Store test parametrization (OQ4): YES for wiki plane
**Query**: Q009 | **Confidence**: high

- `tests/knowledge/wiki/test_store.py:1-32` — "run against EVERY backend"; fixture `@pytest.fixture(params=["sqlite", "memory"])` → `create_wiki_store(tmp_path, backend=request.param)`. Arango excluded from default matrix (live DB; separate `test_factory_arango.py`).
- GraphIndex: `tests/knowledge/graphindex/test_persist.py` + `test_persist_commit_protocol.py` (behavioral tests for the Arango commit protocol) — per-backend tests, no unified param fixture found.
⇒ OQ4: wiki suite parametrization exists (add "postgres" param, gated on a live DB like Arango). GraphIndex commit-protocol behavioral suite is the parity bar for a persist_postgres backend.
