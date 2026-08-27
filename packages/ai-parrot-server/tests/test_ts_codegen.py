"""Unit tests for the Pydantic -> JSON Schema TS codegen pipeline
(FEAT-468, TASK-2526).

Covers ``scripts/generate_ts_types.py``: deterministic output, drift
detection against the committed ``ui/schemas/`` snapshot, and that the
``/api/v1/bots`` descriptor model (:class:`BotsListResponse`) stays
permissive enough to describe both the database- and registry-backed
agent item shapes emitted by ``parrot.handlers.bots``.

Follows the same "worktree root on sys.path via conftest.py" pattern as
the rest of the suite (see ``test_admin_status.py``) — ``scripts`` is a
namespace package rooted at the worktree/repo root, importable without an
``__init__.py``.
"""
from __future__ import annotations

import json

from parrot.server.ui.models import BotAgentItem, BotsListResponse

from scripts.generate_ts_types import SCHEMAS_DIR, export_schemas


def test_schema_export_deterministic(tmp_path):
    """Two consecutive exports to different directories are byte-identical."""
    out_a = export_schemas(tmp_path / "run_a")
    out_b = export_schemas(tmp_path / "run_b")

    assert out_a.keys() == out_b.keys()
    for name in out_a:
        assert out_a[name].read_text() == out_b[name].read_text()


def test_schemas_in_sync_with_committed(tmp_path):
    """Regenerating schemas produces no diff against the committed snapshot.

    Fails when a UI-consumed response model changed without re-running
    ``python scripts/generate_ts_types.py`` — the drift-detection gate the
    task requires.
    """
    fresh = export_schemas(tmp_path / "fresh")

    committed_files = {p.name for p in SCHEMAS_DIR.glob("*.json")}
    fresh_files = {f"{name}.json" for name in fresh}
    assert committed_files == fresh_files, (
        "committed ui/schemas/ is out of sync with the current models "
        "(model added/removed without regenerating) — run "
        "`python scripts/generate_ts_types.py`"
    )

    for name, fresh_path in fresh.items():
        committed_path = SCHEMAS_DIR / f"{name}.json"
        committed = json.loads(committed_path.read_text())
        regenerated = json.loads(fresh_path.read_text())
        assert committed == regenerated, (
            f"{name}.json is out of sync with the current model — run "
            "`python scripts/generate_ts_types.py` and commit the diff"
        )


def test_bots_list_schema_allows_registry_shape():
    """BotsListResponse/BotAgentItem tolerate both emitted agent-item shapes.

    Mirrors ``parrot.handlers.bots.ChatbotHandler._bot_model_to_dict``
    (database source) and ``._registry_agent_to_dict`` (registry source,
    ``bot_config is None`` fallback) — neither payload should be rejected
    just because it carries extra fields beyond ``name``/``source``.
    """
    db_item = {
        "chatbot_id": "11111111-1111-1111-1111-111111111111",
        "name": "sales-bot",
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-01 00:00:00",
        "source": "database",
    }
    registry_item = {
        "name": "billing-bot",
        "module_path": "parrot.bots.billing",
        "file_path": "/app/parrot/bots/billing.py",
        "singleton": True,
        "at_startup": False,
        "priority": 10,
        "tags": ["finance"],
        "source": "registry",
    }

    for raw in (db_item, registry_item):
        item = BotAgentItem.model_validate(raw)
        assert item.name == raw["name"]
        assert item.source == raw["source"]

    response = BotsListResponse.model_validate(
        {"agents": [db_item, registry_item], "total": 2}
    )
    assert response.total == 2
    assert [a.source for a in response.agents] == ["database", "registry"]

    # extra="allow" — the schema's additionalProperties: true must round-trip
    # every field a real handler payload carries, not just name/source.
    dumped = response.agents[1].model_dump()
    for key, value in registry_item.items():
        assert dumped[key] == value
