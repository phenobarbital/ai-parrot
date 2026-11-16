"""FEAT-886 M18 — the durable-memory pages exist, name what they document, and what they name still exists."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "wiki").is_dir())
WIKI = ROOT / "wiki"
MAIN = WIKI / "memory" / "durable-conversation-memory.md"
PAGES = [
    MAIN,
    WIKI / "memory" / "conversation-history-ownership.md",
    WIKI / "memory" / "per-turn-conversation-compaction.md",
    WIKI / "stores" / "storage-backends.md",
]

SYMBOLS = {
    "parrot.memory.persistence": [
        "TurnPresentation",
        "TurnPublisher",
        "BusTurnPublisher",
        "TURN_COMPLETED_TOPIC",
        "CONVERSATION_DELETED_TOPIC",
    ],
    "parrot.memory.hydration": [
        "HydrationSource",
        "SequenceAllocator",
        "LocalSequenceAllocator",
        "RedisSequenceAllocator",
        "HydrationError",
        "HydrationUnavailableError",
        "HydrationNotReadyError",
        "SessionDeletedError",
    ],
    "parrot.memory.parts": ["MessagePart", "render_parts_text"],
    "parrot.storage.errors": [
        "StorageError",
        "StorageUnavailableError",
        "StorageWriteError",
        "ConversationDeletedError",
        "IndexNotReadyError",
        "InvalidTurnPayloadError",
    ],
    "parrot.storage.models": ["ChatStorageTurn"],
    "parrot.storage.turn_bus": [
        "TurnPersistence",
        "setup_turn_persistence",
        "shutdown_turn_persistence",
        "replay_dead_letters",
    ],
    "parrot.storage.hydration": ["ChatStorageHydrationSource"],
    "parrot.storage.backfill": ["run_backfill", "BackfillReport"],
    "parrot.core.events.lifecycle.events.memory": ["TurnCompletedEvent"],
}
SETTINGS = [
    "REDIS_HISTORY_EXPLICIT",
    "REDIS_HISTORY_URL",
    "CHAT_HOT_TTL_HOURS",
    "PARROT_TURN_BUS_REDIS_URL",
    "PARROT_TURN_BUS_OUTBOX_DIR",
    "PARROT_TURN_BUS_CHANNEL_PREFIX",
    "PARROT_TURN_BUS_DLQ_DSN",
]
METHODS = {
    "parrot.storage.backends.base.ConversationBackend": [
        "query_turn_window",
        "max_sequence",
        "put_tombstone",
        "is_deleted",
        "get_index_state",
        "backfill_batch",
        "deleted_turn_ids",
        "deleted_session_ids",
    ],
    "parrot.storage.chat.ChatStorage": [
        "store_turn",
        "handle_turn_completed",
        "handle_conversation_deleted",
        "register_memory_cleaner",
    ],
    "parrot.memory.abstract.ConversationMemory": ["install_history"],
    "parrot.memory.redis.RedisConversation": ["upsert_turn"],
    "parrot.bots.abstract.AbstractBot": ["_load_or_hydrate_history"],
}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_page_exists_and_is_clean(page):
    text = page.read_text(encoding="utf-8")
    assert text.strip()
    assert "TODO" not in text and "TASK-" not in text and "worktree" not in text.lower()


def test_main_page_has_every_mandatory_heading():
    text = MAIN.read_text(encoding="utf-8")
    for heading in (
        "Two stores, one bridge",
        "Event flow",
        "Ordering fields",
        "Identity: agent name vs chatbot id",
        "Hydration",
        "Deletion protocol",
        "What a stored turn contains",
        "Structured history parts",
        "Operator settings",
        "Backfill runbook (legacy rows)",
        "Migration notes",
    ):
        assert f"## {heading}" in text, heading
    assert text.startswith('---\ntitle: "Durable Conversation Memory"\n---')


def test_documented_symbols_exist_and_are_named_in_the_main_page():
    text = MAIN.read_text(encoding="utf-8")
    for module, names in SYMBOLS.items():
        mod = importlib.import_module(module)
        for name in names:
            assert hasattr(mod, name), f"{module}.{name} does not exist"
            if name.isupper():
                continue  # topic constants are documented by value
            assert name in text, f"{name} is not documented"
    assert "conversation.turn.completed" in text and "conversation.deleted" in text


def test_documented_methods_and_settings_exist():
    text = "\n".join(p.read_text(encoding="utf-8") for p in PAGES)
    conf = importlib.import_module("parrot.conf")
    for setting in SETTINGS:
        assert hasattr(conf, setting), setting
        assert setting in text, setting
    for dotted, methods in METHODS.items():
        module, cls = dotted.rsplit(".", 1)
        klass = getattr(importlib.import_module(module), cls)
        for method in methods:
            assert hasattr(klass, method), f"{dotted}.{method}"
            assert method in text or method.lstrip("_") in text, method


def test_removed_api_is_not_documented_as_available():
    text = MAIN.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "save_turn" in line:
            assert "gone" in line or "removed" in line or "hard cut" in line, line


def test_pages_use_no_stale_version_claims():
    assert not re.search(r"shipped in \*\*\d", MAIN.read_text(encoding="utf-8"))


def _section(text: str, heading: str) -> str:
    start = text.index(f"## {heading}")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_turn_save_order_is_documented():
    """FEAT-895: the outbox append precedes the working-memory write, and its failure fails the round."""
    flow = _section(MAIN.read_text(encoding="utf-8"), "Event flow")
    flat = " ".join(flow.split())
    ownership = " ".join((WIKI / "memory" / "conversation-history-ownership.md").read_text(encoding="utf-8").split())
    # the diagram draws the outbox append above the working-memory write
    assert flow.index("TurnPublisher.publish") < flow.index("ConversationMemory.add_turn")
    assert "before the working-memory write" in flat
    assert "rejected append fails the round" in flat and "never fails the round" not in flat
    assert "hydration_source" in flat  # the invalidation is limited to bots that can rehydrate
    assert "one save at a time per session" in flat
    assert "chat:" in flat  # ChatStorage's hot tier is its own store, not the bot's working memory
    assert "publishes the raw turn after `add_turn`" not in ownership
    assert "to the outbox before `add_turn`" in ownership
