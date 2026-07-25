import json

import pytest

from navrules.storages import FileStorage, MemoryStorage, StorageError

DEFS = [
    {
        "rule_type": "ConditionRule",
        "name": "ot_weekend",
        "priority": 100,
        "conditions": {"env.is_weekend": True},
        "result": {"payrate": 33.75},
    }
]


class TestMemoryStorage:
    async def test_load(self):
        async with MemoryStorage(DEFS) as storage:
            assert await storage.load() == DEFS

    async def test_returns_copy(self):
        storage = MemoryStorage(DEFS)
        loaded = await storage.load()
        loaded.append({"x": 1})
        assert len(await storage.load()) == 1


class TestFileStorage:
    async def test_load(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(DEFS))
        async with FileStorage(path) as storage:
            assert (await storage.load())[0]["name"] == "ot_weekend"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(StorageError, match="does not exist"):
            FileStorage(tmp_path / "nope.json")

    async def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(StorageError, match="Invalid JSON"):
            await FileStorage(path).load()

    async def test_non_list_raises(self, tmp_path):
        path = tmp_path / "obj.json"
        path.write_text('{"a": 1}')
        with pytest.raises(StorageError, match="JSON list"):
            await FileStorage(path).load()


class TestEndToEnd:
    async def test_storage_to_ruleset(self):
        from navrules import Policy, RuleSet

        rs = RuleSet(policy=Policy.FIRST_MATCH, default={"payrate": 25.0})
        async with MemoryStorage(DEFS) as storage:
            for spec in await storage.load():
                rs.add_rule(spec)
        rs.compile()
        assert len(rs) == 1
        assert rs.rules[0].name == "ot_weekend"
