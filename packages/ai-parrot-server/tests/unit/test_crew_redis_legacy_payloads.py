"""``CrewRedis`` must keep already-stored crews loadable.

The crew definition models became ``extra="forbid"`` so that a *new*
definition cannot silently drop a field it misspelled. That strictness must
not be retroactive: a row written years ago carrying a key the models no
longer declare is history, not a bug to fail on. ``_strip_unknown_keys``
drops those keys — at every level, because the nested models are strict too
and an agent entry is where drift actually accumulates.
"""
from __future__ import annotations

import json

import pytest

from parrot.handlers.crew.redis_persistence import CrewRedis


@pytest.fixture
def store() -> CrewRedis:
    """A store instance. ``Redis.from_url`` does not connect eagerly."""
    return CrewRedis(redis_url="redis://localhost:6379/15")


def _payload(**overrides) -> str:
    document = {
        "name": "legacy-crew",
        "agents": [{"agent_id": "a", "name": "Researcher"}],
    }
    document.update(overrides)
    return json.dumps(document)


def test_unknown_root_key_is_dropped(store):
    crew = store._deserialize_crew(_payload(tasks=[]))
    assert crew.name == "legacy-crew"


def test_unknown_key_inside_an_agent_is_dropped(store):
    """The nested models are strict too — root-only stripping still failed."""
    crew = store._deserialize_crew(
        _payload(agents=[{"agent_id": "a", "name": "Researcher", "role": "lead"}])
    )
    assert [agent.agent_id for agent in crew.agents] == ["a"]
    assert not hasattr(crew.agents[0], "role")


def test_unknown_key_inside_a_tool_node_is_dropped(store):
    crew = store._deserialize_crew(
        _payload(
            tool_nodes=[
                {"node_id": "publish", "tool": "rest_api", "retries": 3}
            ]
        )
    )
    assert [node.node_id for node in crew.tool_nodes] == ["publish"]


def test_unknown_key_inside_a_relation_is_dropped(store):
    crew = store._deserialize_crew(
        _payload(
            agents=[
                {"agent_id": "a", "name": "Researcher"},
                {"agent_id": "b"},
            ],
            tool_nodes=[{"node_id": "publish", "tool": "rest_api"}],
            flow_relations=[
                {"source": "Researcher", "target": "publish", "weight": 1}
            ],
        )
    )
    assert crew.flow_relations[0].source == "Researcher"


def test_a_relation_written_against_an_agent_id_still_loads(store):
    """``crew.agents`` is keyed by ``name or agent_id``, but both spellings
    have been stored; the reference is normalised rather than rejected."""
    crew = store._deserialize_crew(
        _payload(
            agents=[
                {"agent_id": "coordinator", "name": "Research Coordinator"},
                {"agent_id": "b"},
            ],
            flow_relations=[{"source": "coordinator", "target": "b"}],
        )
    )
    assert crew.flow_relations[0].source == "Research Coordinator"


def test_a_genuine_typo_still_fails(store):
    with pytest.raises(ValueError, match="unknown crew members"):
        store._deserialize_crew(
            _payload(flow_relations=[{"source": "ghost", "target": "Researcher"}])
        )


def test_dropped_keys_are_logged_with_their_path(store, caplog):
    """Silently absorbing drift is how a stale field stops being noticed."""
    with caplog.at_level("WARNING"):
        store._deserialize_crew(
            _payload(agents=[{"agent_id": "a", "role": "lead"}], tasks=[])
        )
    logged = " ".join(str(record.args) for record in caplog.records)
    assert "agents[0].role" in logged
    assert "tasks" in logged
