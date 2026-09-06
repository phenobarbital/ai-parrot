"""Tests for the bounded Roblox mapping reader and require resolver
(FEAT-532 TASK-2898).

Exercises ``roblox/project.py`` directly: no scanner exists yet (that is
TASK-2899's scope), so these tests build a discovered-path set and a
``scan_root`` directory the way ``scan_repository()`` would, and call
``build_instance_index``/``resolve_roblox_require`` the way the future
scanner will.
"""

from __future__ import annotations

import json

import pytest
from parrot.knowledge.wiki.roblox import project as roblox_project
from parrot.knowledge.wiki.roblox.project import build_instance_index, resolve_roblox_require


def _write(tmp_path, rel_path: str, content: str = "-- stub\n") -> None:
    full = tmp_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# test_resolution_cascade
# ---------------------------------------------------------------------------


def test_resolution_cascade_sourcemap_wins(tmp_path):
    discovered = ["src/Main.server.luau", "src/Shared/Utils.luau"]
    for rel in discovered:
        _write(tmp_path, rel)

    sourcemap = {
        "name": "test-place",
        "className": "DataModel",
        "filePaths": [],
        "children": [
            {
                "name": "ServerScriptService",
                "className": "ServerScriptService",
                "filePaths": [],
                "children": [
                    {
                        "name": "Main",
                        "className": "Script",
                        "filePaths": ["src/Main.server.luau"],
                        "children": [],
                    }
                ],
            },
            {
                "name": "ReplicatedStorage",
                "className": "ReplicatedStorage",
                "filePaths": [],
                "children": [
                    {
                        "name": "Utils",
                        "className": "ModuleScript",
                        "filePaths": ["src/Shared/Utils.luau"],
                        "children": [],
                    }
                ],
            },
        ],
    }
    (tmp_path / "sourcemap.json").write_text(json.dumps(sourcemap), encoding="utf-8")
    # A default.project.json is ALSO present, to prove the sourcemap wins
    # and the project-file fallback is not blended in.
    (tmp_path / "default.project.json").write_text(json.dumps({"tree": {"$className": "DataModel"}}), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "sourcemap"
    assert index.class_names["game.ServerScriptService.Main"] == "Script"

    resolved = resolve_roblox_require("game.ReplicatedStorage.Utils", "src/Main.server.luau", index, discovered)
    assert resolved == "src/Shared/Utils.luau"


def test_resolution_cascade_falls_back_to_project_file(tmp_path):
    discovered = ["src/server/Main.server.luau"]
    for rel in discovered:
        _write(tmp_path, rel)

    project = {
        "tree": {
            "$className": "DataModel",
            "ServerScriptService": {"$path": "src/server"},
        }
    }
    (tmp_path / "default.project.json").write_text(json.dumps(project), encoding="utf-8")
    # No sourcemap.json present at all.

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "project-file"
    resolved = resolve_roblox_require("game.ServerScriptService.Main", "irrelevant.luau", index, discovered)
    assert resolved == "src/server/Main.server.luau"


def test_resolution_cascade_invalid_sourcemap_falls_back(tmp_path):
    discovered = ["src/server/Main.server.luau"]
    for rel in discovered:
        _write(tmp_path, rel)

    (tmp_path / "sourcemap.json").write_text("{not valid json", encoding="utf-8")
    project = {
        "tree": {
            "$className": "DataModel",
            "ServerScriptService": {"$path": "src/server"},
        }
    }
    (tmp_path / "default.project.json").write_text(json.dumps(project), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "project-file"
    assert any("sourcemap" in d.lower() for d in index.diagnostics)


def test_resolution_cascade_relative_strings_work_without_any_mapping(tmp_path):
    discovered = ["src/Main.luau", "src/Helper.luau"]
    for rel in discovered:
        _write(tmp_path, rel)

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "none"

    resolved = resolve_roblox_require('"./Helper"', "src/Main.luau", index, discovered)
    assert resolved == "src/Helper.luau"


# ---------------------------------------------------------------------------
# test_unique_existing_target_only
# ---------------------------------------------------------------------------


def test_unique_existing_target_only_rejects_stale_entry(tmp_path):
    discovered = ["src/Main.server.luau"]  # note: "src/Gone.luau" was removed
    _write(tmp_path, "src/Main.server.luau")

    sourcemap = {
        "className": "DataModel",
        "filePaths": [],
        "children": [
            {
                "name": "ServerScriptService",
                "className": "ServerScriptService",
                "filePaths": [],
                "children": [
                    {
                        "name": "Main",
                        "className": "Script",
                        "filePaths": ["src/Main.server.luau"],
                        "children": [],
                    },
                    {
                        "name": "Gone",
                        "className": "ModuleScript",
                        "filePaths": ["src/Gone.luau"],
                        "children": [],
                    },
                ],
            }
        ],
    }
    (tmp_path / "sourcemap.json").write_text(json.dumps(sourcemap), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert "game.ServerScriptService.Gone" not in index.instance_to_files
    resolved = resolve_roblox_require("game.ServerScriptService.Gone", "src/Main.server.luau", index, discovered)
    assert resolved is None


def test_unique_existing_target_only_rejects_ambiguous_instance(tmp_path):
    discovered = ["src/A/Foo.luau", "src/B/Foo.luau"]
    for rel in discovered:
        _write(tmp_path, rel)

    sourcemap = {
        "className": "DataModel",
        "filePaths": [],
        "children": [
            {
                "name": "ServerScriptService",
                "className": "ServerScriptService",
                "filePaths": [],
                "children": [
                    {
                        "name": "Foo",
                        "className": "ModuleScript",
                        "filePaths": ["src/A/Foo.luau", "src/B/Foo.luau"],
                        "children": [],
                    }
                ],
            }
        ],
    }
    (tmp_path / "sourcemap.json").write_text(json.dumps(sourcemap), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    # Both files retained under the one instance path — not collapsed.
    assert index.instance_to_files["game.ServerScriptService.Foo"] == [
        "src/A/Foo.luau",
        "src/B/Foo.luau",
    ]
    # But resolution refuses to guess between them.
    resolved = resolve_roblox_require("game.ServerScriptService.Foo", "irrelevant.luau", index, discovered)
    assert resolved is None


def test_unique_existing_target_only_rejects_escaping_relative_path(tmp_path):
    discovered = ["src/Main.luau"]
    _write(tmp_path, "src/Main.luau")
    index = build_instance_index(tmp_path, discovered)

    resolved = resolve_roblox_require('"../../../../etc/passwd"', "src/Main.luau", index, discovered)
    assert resolved is None


def test_unique_existing_target_only_rejects_numeric_and_computed(tmp_path):
    discovered = ["src/Main.luau"]
    _write(tmp_path, "src/Main.luau")
    index = build_instance_index(tmp_path, discovered)

    assert resolve_roblox_require("123456", "src/Main.luau", index, discovered) is None
    assert resolve_roblox_require("game[computedKey]", "src/Main.luau", index, discovered) is None
    assert resolve_roblox_require('game:FindService("Foo")', "src/Main.luau", index, discovered) is None


# ---------------------------------------------------------------------------
# test_project_init_and_script_classes
# ---------------------------------------------------------------------------


def test_project_init_and_script_classes(tmp_path):
    discovered = [
        "src/server/init.server.luau",
        "src/server/Helper.luau",
        "src/client/init.client.lua",
        "src/shared/init.luau",
    ]
    for rel in discovered:
        _write(tmp_path, rel)

    project = {
        "tree": {
            "$className": "DataModel",
            "ServerScriptService": {"$path": "src/server"},
            "StarterPlayerScripts": {"$path": "src/client"},
            "ReplicatedStorage": {"$path": "src/shared"},
        }
    }
    (tmp_path / "default.project.json").write_text(json.dumps(project), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "project-file"

    # init.server.luau maps the *folder* ("server") to a Script instance.
    assert index.class_names["game.ServerScriptService.server"] == "Script"
    assert index.instance_to_files["game.ServerScriptService.server"] == ["src/server/init.server.luau"]
    # A sibling plain module keeps its own stem-based instance.
    assert index.class_names["game.ServerScriptService.Helper"] == "ModuleScript"

    # init.client.lua -> LocalScript, folder-named.
    assert index.class_names["game.StarterPlayerScripts.client"] == "LocalScript"

    # init.luau -> ModuleScript, folder-named.
    assert index.class_names["game.ReplicatedStorage.shared"] == "ModuleScript"


def test_project_file_duplicated_instance_names_not_collapsed(tmp_path):
    discovered = ["src/server/Foo.lua", "src/server/Foo.luau"]
    for rel in discovered:
        _write(tmp_path, rel)

    project = {
        "tree": {
            "$className": "DataModel",
            "ServerScriptService": {"$path": "src/server"},
        }
    }
    (tmp_path / "default.project.json").write_text(json.dumps(project), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert index.instance_to_files["game.ServerScriptService.Foo"] == [
        "src/server/Foo.lua",
        "src/server/Foo.luau",
    ]


def test_project_file_unsupported_directive_is_diagnostic_only(tmp_path):
    discovered = ["src/server/Main.server.luau"]
    _write(tmp_path, "src/server/Main.server.luau")

    project = {
        "tree": {
            "$className": "DataModel",
            "ServerScriptService": {
                "$path": "src/server",
                "$ignoreUnknownInstances": True,
                "$attributes": {"nope": True},
            },
        }
    }
    (tmp_path / "default.project.json").write_text(json.dumps(project), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert any("$attributes" in d for d in index.diagnostics)
    assert index.source_kind == "project-file"


# ---------------------------------------------------------------------------
# test_mapping_resource_limits
# ---------------------------------------------------------------------------


def test_mapping_resource_limits_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(roblox_project, "MAPPING_JSON_BYTE_LIMIT", 64)
    discovered = ["src/Main.luau"]
    _write(tmp_path, "src/Main.luau")

    big_sourcemap = {"className": "DataModel", "filePaths": [], "children": [{"pad": "x" * 200}]}
    (tmp_path / "sourcemap.json").write_text(json.dumps(big_sourcemap), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "none"
    assert any("byte limit" in d for d in index.diagnostics)


def test_mapping_resource_limits_over_depth(tmp_path, monkeypatch):
    monkeypatch.setattr(roblox_project, "MAPPING_JSON_DEPTH_LIMIT", 5)
    discovered = ["src/Main.luau"]
    _write(tmp_path, "src/Main.luau")

    nested: dict = {"leaf": True}
    for _ in range(10):
        nested = {"children": [nested]}
    (tmp_path / "sourcemap.json").write_text(json.dumps(nested), encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "none"
    assert any("depth limit" in d for d in index.diagnostics)


def test_mapping_resource_limits_malformed_json_is_diagnostic_not_crash(tmp_path):
    discovered = ["src/Main.luau"]
    _write(tmp_path, "src/Main.luau")
    (tmp_path / "sourcemap.json").write_text("{ this is not json", encoding="utf-8")
    (tmp_path / "default.project.json").write_text("{ also not json", encoding="utf-8")

    index = build_instance_index(tmp_path, discovered)
    assert index.source_kind == "none"
    assert index.diagnostics  # degrades predictably, never raises
