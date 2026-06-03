"""State-based sandbox components for the Generic Agent Evaluation Harness.

FEAT-217 — Module 4 (partial — TASK-1418 contributes StateBackend and
DictStateBackend; TASK-1419 adds ToolkitBinder, InMemoryStateSandbox, and
the DB binder; TASK-1420 adds the Jira binder).

``DictStateBackend`` is the resettable, in-memory world state owned by the
sandbox.  It is keyed as ``{collection: {entity_id: {field: value}}}``
and produces deterministic snapshots (sorted collections and entity keys)
so diffs and baselines are stable.
"""
from __future__ import annotations

import copy
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StateBackend ABC
# ---------------------------------------------------------------------------


class StateBackend(ABC):
    """Abstract resettable world-state store.

    Sandboxes own one ``StateBackend`` and delegate ``reset``/``snapshot``
    to it.  The backend is also the injection point that ``ToolkitBinder``
    implementations wire into toolkit internals.
    """

    @abstractmethod
    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """Reset the store to *seed_state* (or empty if ``None``).

        Args:
            seed_state: Initial state keyed as
                ``{collection: {entity_id: {field: value}}}``.
                A deep copy is taken so the caller's dict is not aliased.
        """
        ...

    @abstractmethod
    async def snapshot(self) -> dict[str, Any]:
        """Return a deterministic deep copy of the current state.

        Collections and entity keys are sorted so that two snapshots taken
        after the same mutations are byte-equal (stable for diffs and
        baselines).

        Returns:
            ``{collection: {entity_id: {field: value}}}`` with all keys
            sorted.
        """
        ...


# ---------------------------------------------------------------------------
# DictStateBackend
# ---------------------------------------------------------------------------


class DictStateBackend(StateBackend):
    """In-memory ``{collection: {entity_id: {field: value}}}`` store.

    Provides CRUD-ish helpers used by fake database / Jira drivers:
    ``create``, ``get``, ``update``, ``delete``, ``list``, ``query``.

    Snapshots are:
    - **deep copies** — callers cannot mutate internal state.
    - **deterministic** — collections and entity keys are sorted.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # StateBackend protocol
    # ------------------------------------------------------------------

    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """Reset the store.

        Args:
            seed_state: New initial state.  Deep-copied so the caller's
                dict is not aliased.  Pass ``None`` to empty the store.
        """
        if seed_state is None:
            self._data = {}
            self.logger.debug("DictStateBackend reset to empty state")
        else:
            self._data = copy.deepcopy(seed_state)
            self.logger.debug(
                "DictStateBackend seeded with %d collection(s)",
                len(self._data),
            )

    async def snapshot(self) -> dict[str, Any]:
        """Return a sorted, deep-copied snapshot of the current state.

        Returns:
            ``{collection: {entity_id: {field: value}}}`` with all
            collection names and entity ids sorted lexicographically.
        """
        return {
            c: {
                eid: copy.deepcopy(self._data[c][eid])
                for eid in sorted(self._data[c])
            }
            for c in sorted(self._data)
        }

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    async def create(
        self, collection: str, entity_id: str, fields: dict[str, Any]
    ) -> None:
        """Insert a new entity.

        Args:
            collection: Collection (table) name.
            entity_id: Unique identifier for the entity.
            fields: Initial field values.

        Raises:
            KeyError: If *entity_id* already exists in *collection*.
        """
        col = self._data.setdefault(collection, {})
        if entity_id in col:
            raise KeyError(
                f"Entity '{entity_id}' already exists in collection "
                f"'{collection}'. Use update() to modify it."
            )
        col[entity_id] = copy.deepcopy(fields)

    async def get(
        self, collection: str, entity_id: str
    ) -> dict[str, Any] | None:
        """Fetch a single entity by id.

        Args:
            collection: Collection name.
            entity_id: Entity identifier.

        Returns:
            A deep copy of the entity's fields, or ``None`` if not found.
        """
        col = self._data.get(collection, {})
        entity = col.get(entity_id)
        return copy.deepcopy(entity) if entity is not None else None

    async def update(
        self, collection: str, entity_id: str, fields: dict[str, Any]
    ) -> None:
        """Merge *fields* into an existing entity (partial update).

        Args:
            collection: Collection name.
            entity_id: Entity identifier.
            fields: Fields to merge (values set to ``None`` are removed).

        Raises:
            KeyError: If *entity_id* does not exist in *collection*.
        """
        col = self._data.get(collection, {})
        if entity_id not in col:
            raise KeyError(
                f"Entity '{entity_id}' not found in collection '{collection}'."
            )
        col[entity_id].update(fields)

    async def delete(self, collection: str, entity_id: str) -> bool:
        """Remove an entity.

        Args:
            collection: Collection name.
            entity_id: Entity identifier.

        Returns:
            ``True`` if the entity was removed; ``False`` if it did not
            exist.
        """
        col = self._data.get(collection, {})
        if entity_id in col:
            del col[entity_id]
            return True
        return False

    async def list(self, collection: str) -> list[dict[str, Any]]:
        """Return all entities in a collection as a list of dicts.

        Each dict contains the entity's fields plus the key ``"_id"``
        carrying the entity identifier.

        Args:
            collection: Collection name.

        Returns:
            List of ``{_id: entity_id, **fields}`` dicts (sorted by id).
        """
        col = self._data.get(collection, {})
        return [
            {"_id": eid, **copy.deepcopy(col[eid])} for eid in sorted(col)
        ]

    async def query(
        self,
        collection: str,
        predicate: Callable[[dict[str, Any]], bool],
    ) -> list[dict[str, Any]]:
        """Return entities in *collection* where *predicate* returns ``True``.

        Args:
            collection: Collection name.
            predicate: A callable that receives a field dict (without the
                ``_id`` key) and returns ``True`` to include the entity.

        Returns:
            Matching entities as ``{_id: entity_id, **fields}`` dicts,
            sorted by entity id.
        """
        col = self._data.get(collection, {})
        result = []
        for eid in sorted(col):
            entity = copy.deepcopy(col[eid])
            if predicate(entity):
                result.append({"_id": eid, **entity})
        return result

    async def upsert(
        self, collection: str, entity_id: str, fields: dict[str, Any]
    ) -> None:
        """Insert or update an entity.

        Args:
            collection: Collection name.
            entity_id: Entity identifier.
            fields: Field values to set (merged with existing on update).
        """
        col = self._data.setdefault(collection, {})
        if entity_id in col:
            col[entity_id].update(copy.deepcopy(fields))
        else:
            col[entity_id] = copy.deepcopy(fields)
