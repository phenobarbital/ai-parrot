"""Tests for the deterministic Roblox API class/enum renderer (FEAT-532 TASK-2901)."""

from __future__ import annotations

import copy

import pytest
from parrot.knowledge.wiki import store as wiki_store
from parrot.knowledge.wiki.roblox.render import build_normalized_dump, render_generation

_DUMP = {
    "Classes": [
        {
            "Name": "Instance",
            "Superclass": "<<<ROOT>>>",
            "Tags": [],
            "Members": [
                {
                    "MemberType": "Property",
                    "Name": "Name",
                    "ValueType": {"Category": "Primitive", "Name": "string"},
                    "Security": {"Read": "None", "Write": "None"},
                    "ThreadSafety": "Safe",
                    "Tags": [],
                },
            ],
        },
        {
            "Name": "Players",
            "Superclass": "Instance",
            "Tags": [],
            "Members": [
                {
                    "MemberType": "Function",
                    "Name": "GetPlayers",
                    "Parameters": [],
                    "ReturnType": {"Category": "DataType", "Name": "Array"},
                    "Security": "None",
                    "ThreadSafety": "Safe",
                    "Tags": [],
                },
                {
                    "MemberType": "Event",
                    "Name": "PlayerAdded",
                    "Parameters": [{"Name": "player", "Type": {"Category": "Class", "Name": "Instance"}}],
                    "Security": "None",
                    "ThreadSafety": "Safe",
                    "Tags": [],
                },
                {
                    "MemberType": "Property",
                    "Name": "CharacterAppearance",
                    "ValueType": {"Category": "Enum", "Name": "Material"},
                    "Security": {"Read": "None", "Write": "None"},
                    "ThreadSafety": "Safe",
                    "Tags": [],
                },
            ],
        },
        {
            "Name": "Workspace",
            # Unknown superclass in this generation — must not be rendered as extends.
            "Superclass": "SomethingNotInThisDump",
            "Tags": ["NotBrowsable"],
            "Members": [],
        },
    ],
    "Enums": [
        {
            "Name": "Material",
            "Items": [
                {"Name": "Wood", "Value": 512},
                {"Name": "Plastic", "Value": 256},
            ],
        }
    ],
}

_CLASS_DOCS = {
    "Players": {"description": "A service to interact with the players in a game."},
    # "Instance" and "Workspace" deliberately have no docs -> structural-only.
}


def test_class_and_enum_fidelity():
    """Known signatures/security/thread-safety/superclass/enum values are preserved."""
    dump = build_normalized_dump(_DUMP, _CLASS_DOCS)
    players = next(c for c in dump.classes if c.name == "Players")

    assert players.superclass == "Instance"
    get_players = next(m for m in players.members if m.name == "GetPlayers")
    assert get_players.return_type == "Array"
    assert get_players.security == "None"
    assert get_players.thread_safety == "Safe"

    player_added = next(m for m in players.members if m.name == "PlayerAdded")
    assert player_added.parameters == [type(player_added.parameters[0])(name="player", type="Instance")]

    material = next(e for e in dump.enums if e.name == "Material")
    assert {i.name: i.value for i in material.items} == {"Wood": 512, "Plastic": 256}

    instance = next(c for c in dump.classes if c.name == "Instance")
    name_prop = next(m for m in instance.members if m.name == "Name")
    assert name_prop.value_type == "string"
    assert name_prop.security == "Read=None, Write=None"


def test_missing_docs_still_has_page():
    """Every valid dump entity appears once even without prose."""
    dump = build_normalized_dump(_DUMP, _CLASS_DOCS)
    rendered = render_generation(dump, generation_id="gen-1", schema_version=1)

    page_ids = {p.concept_id for p in rendered.pages}
    assert page_ids == {"class/Instance", "class/Players", "class/Workspace", "enum/Material"}
    assert rendered.class_count == 3
    assert rendered.enum_count == 1
    assert rendered.structural_only_count == 2  # Instance, Workspace
    assert rendered.missing_doc_classes == ["Instance", "Workspace"]

    instance_page = next(p for p in rendered.pages if p.concept_id == "class/Instance")
    assert "no creator-docs description" in instance_page.body

    players_page = next(p for p in rendered.pages if p.concept_id == "class/Players")
    assert "A service to interact with the players in a game." in players_page.body


def test_edges_have_existing_targets():
    """References/inheritance exclude unknown entities."""
    dump = build_normalized_dump(_DUMP, _CLASS_DOCS)
    rendered = render_generation(dump, generation_id="gen-1", schema_version=1)

    # Edge tuples are (src, dst, rel) — the store's actual convention.
    extends_edges = [e for e in rendered.edges if e[2] == "extends"]
    assert ("class/Players", "class/Instance", "extends") in extends_edges
    # Workspace's superclass is not in this generation -> no extends edge at all.
    assert not any(e[0] == "class/Workspace" for e in extends_edges)

    references_edges = [e for e in rendered.edges if e[2] == "references"]
    # Players references Instance (PlayerAdded param) and Material (enum property).
    assert ("class/Players", "class/Instance", "references") in references_edges
    assert ("class/Players", "enum/Material", "references") in references_edges
    # Never a reference to something absent from this generation.
    assert all(
        target in {"class/Instance", "class/Players", "class/Workspace", "enum/Material"}
        for _src, target, _rel in rendered.edges
    )


def test_replay_is_stable():
    """Reordered input yields identical page bodies/catalog and edge order."""
    reordered_dump = copy.deepcopy(_DUMP)
    reordered_dump["Classes"] = list(reversed(reordered_dump["Classes"]))
    reordered_dump["Enums"] = list(reversed(reordered_dump["Enums"]))
    for cls in reordered_dump["Classes"]:
        cls["Members"] = list(reversed(cls.get("Members", [])))

    first = render_generation(build_normalized_dump(_DUMP, _CLASS_DOCS), generation_id="gen-1", schema_version=1)
    second = render_generation(
        build_normalized_dump(reordered_dump, _CLASS_DOCS), generation_id="gen-1", schema_version=1
    )

    assert [p.concept_id for p in first.pages] == [p.concept_id for p in second.pages]
    assert [p.body for p in first.pages] == [p.body for p in second.pages]
    assert [p.content_hash for p in first.pages] == [p.content_hash for p in second.pages]
    assert first.edges == second.edges
    assert first.catalog == second.catalog


def test_render_is_offline(monkeypatch):
    """No HTTP, LLM or tokenizer download on cold-cache rendering."""
    # Simulate a cold tokenizer cache and assert render never resolves it.
    monkeypatch.setattr(wiki_store, "_TOKEN_ENCODER", None)

    def _boom(*_args, **_kwargs):
        raise AssertionError("tiktoken.get_encoding must never be called during rendering")

    monkeypatch.setattr("tiktoken.get_encoding", _boom, raising=False)

    dump = build_normalized_dump(_DUMP, _CLASS_DOCS)
    rendered = render_generation(dump, generation_id="gen-1", schema_version=1)

    assert rendered.pages  # rendering still succeeded
    assert all(p.token_count > 0 for p in rendered.pages)
    # Confirms the encoder cache was never mutated by rendering (never
    # probed, so no fallback-to-False write either).
    assert wiki_store._TOKEN_ENCODER is None


def test_render_is_offline_uses_resolved_encoder_when_already_cached(monkeypatch):
    """When the encoder is already resolved (any prior caller), rendering
    is allowed to use it — this is the "not cold" branch."""
    monkeypatch.setattr(wiki_store, "_TOKEN_ENCODER", False)  # previously resolved: unavailable

    dump = build_normalized_dump(_DUMP, _CLASS_DOCS)
    rendered = render_generation(dump, generation_id="gen-1", schema_version=1)
    assert all(p.token_count > 0 for p in rendered.pages)


def test_unknown_class_and_malformed_entries_are_skipped_not_fatal():
    dump_with_junk = copy.deepcopy(_DUMP)
    dump_with_junk["Classes"].append({"NoNameField": True})
    dump_with_junk["Classes"].append({"Name": "", "Members": []})
    dump_with_junk["Enums"].append({"NoNameField": True})

    dump = build_normalized_dump(dump_with_junk, _CLASS_DOCS)
    # Malformed entries produce no class/enum entity, never raise.
    assert {c.name for c in dump.classes} == {"Instance", "Players", "Workspace"}
    assert {e.name for e in dump.enums} == {"Material"}
