# TASK-3730: End-to-end + live Arango/Postgres + channel matrix tests

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3703, TASK-3713, TASK-3718, TASK-3719, TASK-3717, TASK-3725
**Assigned-to**: unassigned

---

## Context

Spec §4 **Integration Tests** and AC8/AC19. Unit tests prove each module in isolation; this task proves the seams: a synthetic manual goes through `ManualLibrary.add_manual` → `ManualGraphLoader.publish_all` → `ProceduresAnswerService.answer` and comes back as an ordered, cited `procedure` answer with primary figures; a revision re-ingest re-links technician tips exactly as spike 4 expects; the live Arango and Postgres backends behave like the fakes; and one presigned figure is delivered through Teams, Slack, Telegram and WhatsApp.

Test names from spec §4: `test_ingest_publish_answer_roundtrip`, `test_tip_survives_revision`, `test_live_arango_publish`, `test_live_postgres_catalog`, `test_channel_delivery_matrix`.

**Exclusive (`parallel: false`)**: the live suites share the explicitly configured Postgres (`GRAPHINDEX_PG_DSN`) and ArangoDB (`CONTRACTS_ARANGO_URL`) services; running them alongside any other task's live tests would contend for the same schemas/databases.

---

## Scope

- `packages/ai-parrot-tools/tests/procedures/test_end_to_end.py` — in-process round trip and tip survival on fakes (no network, no LLM): scripted structured adapter, fake indexer, fake file manager, and a **projecting** in-memory graph store that answers the `procedure_steps` / `tips_for_procedure` patterns from the documents the loader wrote.
- `packages/ai-parrot/tests/knowledge/manuals/test_integration_live.py` — `test_live_arango_publish`, `test_live_postgres_catalog`; skip cleanly (reported as skipped, never as passed) without credentials.
- `packages/ai-parrot-integrations/tests/test_channel_delivery_matrix.py` — one `AIMessage(image_urls=[…])` from a stub `ProceduresAgent` delivered through each channel's sender with mocked transports.

**NOT in scope**: fixing defects found in modules owned by other tasks (file a ledger issue / report in the Completion Note instead); the M0 spike reports (TASK-3726); any production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/procedures/test_end_to_end.py` | CREATE | Ingest → publish → answer round trip; tip survival |
| `packages/ai-parrot/tests/knowledge/manuals/test_integration_live.py` | CREATE | Live ArangoDB + Postgres suites (env-gated) |
| `packages/ai-parrot-integrations/tests/test_channel_delivery_matrix.py` | CREATE | Teams/Slack/Telegram/WhatsApp URL-media delivery |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import os, uuid
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock
import pytest
# channel wrappers (verified class names)
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper      # msteams/wrapper.py:93
from parrot.integrations.slack.wrapper import SlackAgentWrapper          # slack/wrapper.py:75
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper    # telegram/wrapper.py:69
from parrot.integrations.whatsapp.wrapper import WhatsAppAgentWrapper    # whatsapp/wrapper.py:37
from parrot.integrations.parser import parse_response                    # integrations/parser.py:519
from parrot.models.responses import AIMessage                            # models/responses.py:75
from parrot.models.basic import CompletionUsage                          # models/basic.py:48
# created by earlier FEAT-601 tasks
from parrot.knowledge.manuals.library import ManualLibrary               # TASK-3713
from parrot.knowledge.manuals.graph_loader import ManualGraphLoader      # TASK-3712
from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog   # TASK-3703
from parrot.knowledge.manuals.tips import add_tip                        # TASK-3710
from parrot_tools.procedures.retrieval import ProcedureRetrieval         # TASK-3720
from parrot_tools.procedures.verifier import ProcedureVerifier           # TASK-3722
from parrot_tools.procedures.service import ProceduresAnswerService      # TASK-3723
from parrot_tools.procedures.agent import ProceduresAgent                # TASK-3725
```

### Existing Signatures to Use
```python
# Env-gating pattern — packages/ai-parrot/tests/knowledge/contracts/conftest.py (COPY into the live module; that conftest
# is not visible from tests/knowledge/manuals/)
PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN")                                     # line 30
ARANGO_URL = os.environ.get("CONTRACTS_ARANGO_URL")                              # line 31
ARANGO_USER = os.environ.get("CONTRACTS_ARANGO_USER", "root")                    # line 32
ARANGO_PASSWORD = os.environ.get("CONTRACTS_ARANGO_PASSWORD", "")                # line 33
requires_pg = pytest.mark.skipif(not PG_DSN, reason="live Postgres suites require an explicit GRAPHINDEX_PG_DSN")  # line 35
requires_arango = pytest.mark.skipif(not ARANGO_URL, reason="…CONTRACTS_ARANGO_URL")                               # line 36-39
async def pg_pool(): asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=6)    # line 229-240
async def temp_schema(pg_pool): schema f"contracts_it_{uuid4().hex[:8]}" dropped CASCADE afterwards   # line 243-251
def arango_params() -> {"host","port","username","password","database": "_system"}                    # line 254-270
# Use a "manuals_it_<hex>" schema / tenant prefix so runs never collide with contracts suites.

# Wrapper senders (verified)
MSTeamsAgentWrapper._parsed_to_card_spec(self, parsed) -> CardSpec                 # msteams/wrapper.py:1167 (image_entries at :1259)
SlackAgentWrapper._build_blocks(parsed) -> List[Dict[str, Any]]  (staticmethod)    # slack/wrapper.py:567
TelegramAgentWrapper._send_attachments(self, chat_id: int, parsed) -> None         # telegram/wrapper.py:2960
WhatsAppAgentWrapper._send_parsed_response(self, to: str, parsed, client) -> None  # whatsapp/wrapper.py:246
# Construction precedent without I/O: `TelegramAgentWrapper.__new__(TelegramAgentWrapper)` + MagicMock logger
#   (packages/ai-parrot-integrations/tests/integrations/test_telegram_wrapper_send.py:14-17)

# created by TASK-3716 — ParsedResponse.image_urls / media_urls; parrot.integrations.media_download.download_to_temp
# created by TASK-3717/3718/3719 — URL rendering/sending in the four wrappers (read their tests for the mock seams)
# created by TASK-3698 — packages/ai-parrot/tests/knowledge/manuals/conftest.py fixtures: manual_pdf, manual_pdf_rev_b,
#   fake_graph_store, fake_adapter, fake_file_manager (usable ONLY from tests/knowledge/manuals/)
```

### Does NOT Exist
- ~~Importing `tests.knowledge._support` or `tests.knowledge.manuals.conftest` from `packages/ai-parrot-tools/tests/`~~ — separate `tests` packages collide; the tools-side e2e defines its own fakes (reuse `tests/procedures/_doubles.py` read-only for contexts/catalog shapes).
- ~~A `default_dsn` fallback for live tests~~ — explicit env vars only; missing ⇒ skip.
- ~~Real AQL evaluation in the fake graph store~~ — the projecting fake builds rows for the two patterns from stored documents; live AQL is covered only by `test_live_arango_publish`.
- ~~Network calls in the channel matrix~~ — `download_to_temp` and every transport client are mocked.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/tests/procedures/test_end_to_end.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_integration_live.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/test_channel_delivery_matrix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._parsed_to_card_spec",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._build_blocks",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._send_attachments",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py#WhatsAppAgentWrapper._send_parsed_response",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#parse_response"
  ]
}
```

---

## Implementation Notes

- **Round trip expectations** (spec §4): answer_kind `procedure`, 5 steps in order, one citation per step whose quote is verbatim in the archived section, primary figures `Fig. 1`/`Fig. 2` presigned to `https://fake/…` in `AnswerOutcome.image_urls`, hazard inlined.
- **Tip survival** (spike 4 in-process): rev A + 3 tips on steps 3, 4, 5; rev B renumbers step 3 (same `source_identity` ⇒ relinked by identity), keeps step 4's text but moves it (exact `content_hash` ⇒ relinked by hash) and removes step 5 (tip ⇒ `orphaned=True`); the next answer excludes the orphan. If the fixture's "reworded step 4" cannot keep an identical hash, make step 4 the *hash* case by keeping its text and changing only order, and assert the reworded case becomes a curator **candidate**, not a relink (R1).
- **Live Arango**: `initialize_tenant` for a unique tenant, `publish_all`, then run each declared traversal pattern and assert it returns rows with the projected keys; tear down the tenant database/collections.
- **Live Postgres**: `PostgresManualCatalog(pool=pg_pool, tenant_id=..., schema=temp_schema)` → `setup` → `upsert` → `search` → `verification_queue`.
- **Channel matrix**: one released `AIMessage` with `image_urls=["https://files.example/fig1.png?sig=x"]` → `parse_response` → Teams card has an `ImageSection`, Slack blocks contain an `image` block with that URL, Telegram `send_photo` called after a mocked `download_to_temp` (host allowlisted via `PARROT_MEDIA_URL_HOSTS`), WhatsApp `client.send_image(image=url)`.
- Every async test uses `pytest-asyncio` (check the package's `asyncio_mode`; add `@pytest.mark.asyncio` where it is not `auto`).

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.
- Live suites: `GRAPHINDEX_PG_DSN=... CONTRACTS_ARANGO_URL=... pytest <file> -q`; without them the suite must report **skipped** (spec §4: a missing service does not count as acceptance).

### References in Codebase
- `packages/ai-parrot-tools/tests/contracts/test_end_to_end.py` — contracts e2e structure
- `packages/ai-parrot/tests/knowledge/contracts/conftest.py:30-270` — live gating + fixtures
- `packages/ai-parrot-integrations/tests/integrations/test_telegram_photo_attachments.py` — Telegram mock seams

---

## Implementation Blueprint

### Steps (in order)
1. Write the live module first (block 2) — *because* it is self-contained and its skips must be verified locally without credentials.
2. Write the channel matrix (block 3) — *because* it only depends on M12 + the agent and is quick to stabilise.
3. Write the tools-side e2e (block 1) with a projecting graph store — *because* it exercises the most modules and needs the others settled.
4. Run all three Validation Commands; record skipped counts in the Completion Note.

### `packages/ai-parrot-tools/tests/procedures/test_end_to_end.py` (CREATE)
```python
"""In-process FEAT-601 round trip: ingest → publish → answer, and tip survival across revisions."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.knowledge.manuals.graph_loader import ManualGraphLoader
from parrot.knowledge.manuals.library import ManualLibrary
from parrot.knowledge.manuals.tips import add_tip
from parrot_tools.procedures.retrieval import ProcedureRetrieval
from parrot_tools.procedures.service import ProceduresAnswerService
from parrot_tools.procedures.verifier import ProcedureVerifier

from ._doubles import FakeOntology, FakePattern, make_context


class ProjectingGraphStore:
    """In-memory graph store: stores what the loader writes, projects rows for two traversal patterns."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges: dict[str, list[dict[str, Any]]] = {}

    # FILL IN: upsert_nodes / create_edges (UPSERT on (_from,_to), UPDATE {} — never updates, graph_store.py:411) /
    #          soft_delete_nodes / query_documents / edges_incident / remove_edge_by_triple / get_all_edges with the
    #          signatures ManualGraphLoader (TASK-3712) and relink_tips (TASK-3710) call — copy the promoted
    #          FakeGraphStore shape from packages/ai-parrot/tests/knowledge/_support/graph.py (TASK-3698), do not import it

    async def execute_traversal(self, ctx: Any, aql: str, bind_vars: Optional[dict[str, Any]] = None,
                                collection_binds: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
        # FILL IN: aql == "procedure_steps" ⇒ has_step edges of bind_vars["procedure_id"] joined to step/media/hazard
        #          docs (active only); "tips_for_procedure" ⇒ tech_tip docs via tech_tip_on — bounded by the RETURN
        #          shapes of procedures.ontology.yaml (TASK-3701); the FakeOntology maps pattern name → name as AQL
        raise NotImplementedError


def _pdf(tmp_path: Path, *, rev: str) -> Path:
    # FILL IN: 6-page synthetic manual (cover, parts table, 5 numbered steps, Fig. 1/Fig. 2 captions, hazard box)
    #          via pymupdf (pytest.importorskip("pymupdf")); rev "B": step 3 renumbered, step 4 moved, step 5 removed
    raise NotImplementedError


async def test_ingest_publish_answer_roundtrip(tmp_path):
    """corpus PDF → add_manual → publish_all → answer("how do I assemble X") ⇒ ordered steps, primary figures, citations."""
    # FILL IN: scripted structured adapter (header + procedure drafts with verbatim quotes), fake indexer, fake file
    #          manager returning https://fake/…; library.add_manual → loader.publish_all → service.answer(ctx)
    ...


async def test_tip_survives_revision(tmp_path):
    """rev A + 3 tips → rev B ⇒ 1 relinked by identity, 1 by hash, 1 orphaned; answer excludes the orphan."""
    ...
```

### `packages/ai-parrot/tests/knowledge/manuals/test_integration_live.py` (CREATE)
```python
"""Live FEAT-601 suites — explicit credentials only; a missing service SKIPS (never counts as acceptance)."""
from __future__ import annotations

import os
import uuid
from typing import Any, AsyncIterator

import pytest

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN")
ARANGO_URL = os.environ.get("CONTRACTS_ARANGO_URL")
ARANGO_USER = os.environ.get("CONTRACTS_ARANGO_USER", "root")
ARANGO_PASSWORD = os.environ.get("CONTRACTS_ARANGO_PASSWORD", "")
requires_pg = pytest.mark.skipif(not PG_DSN, reason="live Postgres suites require an explicit GRAPHINDEX_PG_DSN")
requires_arango = pytest.mark.skipif(not ARANGO_URL, reason="live ArangoDB suites require an explicit CONTRACTS_ARANGO_URL")


@pytest.fixture()
async def pg_pool() -> AsyncIterator[Any]:
    if not PG_DSN:  # pragma: no cover - skipped by the marker
        pytest.skip("no GRAPHINDEX_PG_DSN")
    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture()
async def temp_schema(pg_pool) -> AsyncIterator[str]:
    schema = f"manuals_it_{uuid.uuid4().hex[:8]}"
    try:
        yield schema
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture()
def arango_params() -> dict[str, Any]:
    if not ARANGO_URL:  # pragma: no cover - skipped by the marker
        pytest.skip("no CONTRACTS_ARANGO_URL")
    from urllib.parse import urlparse

    parsed = urlparse(ARANGO_URL)
    return {"host": parsed.hostname or "127.0.0.1", "port": parsed.port or 8529, "username": ARANGO_USER,
            "password": ARANGO_PASSWORD, "database": "_system"}


@requires_arango
async def test_live_arango_publish(arango_params):
    """Real initialize_tenant + publish + traversal patterns return rows."""
    # FILL IN: OntologyGraphStore over arango_params (import from parrot.knowledge.ontology.graph_store — submodule
    #          only, AC17); unique tenant; ManualGraphLoader(...).publish_all(); run each pattern's query_template;
    #          teardown the tenant — bounded by AC5/AC10/AC17
    ...


@requires_pg
async def test_live_postgres_catalog(pg_pool, temp_schema):
    """upsert/search/queue against Postgres."""
    # FILL IN: PostgresManualCatalog(pool=pg_pool, tenant_id=f"t-{uuid4().hex[:6]}", schema=temp_schema) → setup →
    #          upsert(card) → search("assembly") hit → verification_queue ordering — bounded by TASK-3703
    ...
```

### `packages/ai-parrot-integrations/tests/test_channel_delivery_matrix.py` (CREATE)
```python
"""One presigned figure delivered per channel contract (FEAT-601 M12 end to end, AC8/AC14)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.parser import parse_response
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

URL = "https://files.example/fig1.png?sig=x"


def _released() -> AIMessage:
    """What ProceduresAgent.ask() returns for a released procedure (TASK-3725)."""
    return AIMessage(input="how do I assemble X", output="1. Fit the base plate.", model="procedures-service",
                     provider="parrot", usage=CompletionUsage(), image_urls=[URL])


def test_channel_delivery_matrix_teams():
    # FILL IN: MSTeamsAgentWrapper.__new__ + logger; spec = wrapper._parsed_to_card_spec(parse_response(_released()));
    #          assert one image entry with URL
    ...


def test_channel_delivery_matrix_slack():
    from parrot.integrations.slack.wrapper import SlackAgentWrapper

    blocks = SlackAgentWrapper._build_blocks(parse_response(_released()))
    assert any(b.get("type") == "image" and b.get("image_url") == URL for b in blocks)


async def test_channel_delivery_matrix_telegram(monkeypatch, tmp_path):
    # FILL IN: TelegramAgentWrapper.__new__; wrapper.bot = MagicMock(send_photo=AsyncMock()); monkeypatch the
    #          download helper TASK-3718 uses to return a tmp png; await wrapper._send_attachments(1, parsed);
    #          assert send_photo awaited once — bounded by TASK-3718's seam
    ...


async def test_channel_delivery_matrix_whatsapp():
    # FILL IN: WhatsAppAgentWrapper.__new__; client = MagicMock(send_image=MagicMock()); await
    #          wrapper._send_parsed_response("+100", parsed, client); assert send_image called with image=URL
    ...
```
**Why**: the matrix exercises exactly the path a channel takes (`agent.ask` result → `parse_response` → sender) with transports mocked, which is what AC8 requires beyond the per-wrapper unit tests of TASK-3717/3718/3719.

### FILL IN checklist
- [ ] `ProjectingGraphStore` write methods + two-pattern projection
- [ ] `_pdf` synthetic manual (rev A/B)
- [ ] round-trip and tip-survival bodies (spec §4 expectations)
- [ ] live Arango publish + traversal; live Postgres catalog
- [ ] Teams / Telegram / WhatsApp matrix bodies against the TASK-3717/3718/3719 seams

---

## Acceptance Criteria

- [ ] `test_ingest_publish_answer_roundtrip` passes on fakes: `procedure` answer, 5 ordered steps, citations verbatim, primary figures presigned.
- [ ] `test_tip_survives_revision` passes: identity relink, hash relink, orphan excluded from the next answer (AC6).
- [ ] Without `GRAPHINDEX_PG_DSN` / `CONTRACTS_ARANGO_URL` both live tests are reported **skipped**; with them they pass.
- [ ] The channel matrix delivers the URL on Teams, Slack, Telegram and WhatsApp (AC8, AC14).
- [ ] No production file is modified by this task.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_end_to_end.py -q`
- `pytest packages/ai-parrot/tests/knowledge/manuals/test_integration_live.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_channel_delivery_matrix.py -q`

---

## Test Specification

The three blueprint blocks above are the test scaffolds (they ARE the deliverable). Names required by spec §4:
`test_ingest_publish_answer_roundtrip`, `test_tip_survives_revision`, `test_live_arango_publish`,
`test_live_postgres_catalog`, and `test_channel_delivery_matrix_*` (one per channel; together they are the spec's
`test_channel_delivery_matrix`).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3730
- Feature: training-agent
- Implementation SHA: 5ddea85fe8e883df6c66f05b6d8022541b4ce69a
- Closed at (UTC): 2026-09-25T19:12:06+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra - Backend: codex - Model: gpt-5.6-terra - Attempts: 1 - Duration: ~295s - Tokens: n/a |
