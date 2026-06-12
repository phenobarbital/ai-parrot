"""Shared dependency-graph infrastructure for FEAT-301/FEAT-300.

``LogicGraph`` builds the combined field-dependency graph for a form:
- Edges from field A → field B when a ``DependencyRule`` on field B references
  field A via ``FieldRefCondition``.
- Extensible to formula inputs (FEAT-300 ``ExpressionEvaluator`` follow-up).

Provides:
- Topological ordering (so chained show/hide resolves deterministically).
- Cycle detection (reports/raises ``CyclicDependencyError`` but
  ``evaluate_form`` degrades gracefully — logs warning, never hangs).
"""

from __future__ import annotations

from collections import deque

import logging
from typing import TYPE_CHECKING

from ..core.constraints import FieldRefCondition

if TYPE_CHECKING:
    from ..core.schema import FormSchema

logger = logging.getLogger(__name__)


class CyclicDependencyError(ValueError):
    """Raised when a circular dependency is detected in the logic graph.

    Attributes:
        cycle: The list of field IDs that form the cycle.
    """

    def __init__(self, cycle: list[str]) -> None:
        """Initialize with the cycle path.

        Args:
            cycle: Ordered list of field IDs forming the cycle.
        """
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")


class LogicGraph:
    """Dependency graph for form fields and their condition references.

    The graph is directed: an edge (A → B) means "field B's rule references
    field A's answer", so A must be evaluated before B.

    Extensible: future formula inputs (FEAT-300) can add edges to the same
    graph so that the combined topological order is correct for an
    orchestrator that runs both ``RuleEvaluator`` and ``ExpressionEvaluator``.

    Args:
        nodes: Set of all field IDs in the graph.
        edges: Adjacency list: field_id → set of field_ids that depend on it
               (i.e. "dependents of X", not "dependencies of X").
    """

    def __init__(
        self,
        nodes: set[str],
        edges: dict[str, set[str]],
    ) -> None:
        """Initialize the graph.

        Args:
            nodes: All field IDs in the form.
            edges: For each field, the set of fields whose rules reference it
                   (X → {fields that depend on X}).
        """
        self._nodes = nodes
        # _deps[B] = set of fields that B depends on (reverse of edges above)
        # For topological sort, we need the "A must come before B" direction.
        self._deps: dict[str, set[str]] = {n: set() for n in nodes}
        for src, dependents in edges.items():
            for dep in dependents:
                self._deps.setdefault(dep, set()).add(src)

    @classmethod
    def build(cls, form: "FormSchema") -> "LogicGraph":
        """Build a LogicGraph from a FormSchema.

        Only ``FieldRefCondition`` variants create intra-form edges.
        ``LocationVarCondition`` and ``VisitContextCondition`` reference
        external keys, not form fields.

        Args:
            form: The form schema to analyze.

        Returns:
            A ``LogicGraph`` for the form's fields.
        """
        all_fields = list(form.iter_all_fields())
        nodes = {f.field_id for f in all_fields}

        # edges[X] = set of fields whose rules reference X (X is a dependency of those fields)
        edges: dict[str, set[str]] = {n: set() for n in nodes}

        for field in all_fields:
            if field.depends_on is None:
                continue
            for condition in field.depends_on.conditions:
                if isinstance(condition, FieldRefCondition):
                    ref_id = condition.field_id
                    if ref_id in nodes:
                        edges.setdefault(ref_id, set()).add(field.field_id)

        return cls(nodes, edges)

    def topological_order(self) -> list[str]:
        """Return field IDs in topological evaluation order.

        Fields with no dependencies come first; dependents come after.
        Nodes not connected to the dependency graph appear at the front
        in their original insertion order (deterministic across Python 3.7+).

        Returns:
            Ordered list of all field IDs.

        Raises:
            CyclicDependencyError: If a cycle is detected.
        """
        # Kahn's algorithm (BFS-based topological sort)
        in_degree: dict[str, int] = {n: 0 for n in self._nodes}
        for n, deps in self._deps.items():
            in_degree[n] = len(deps)

        # Start with nodes that have no dependencies
        queue: deque[str] = deque(sorted(n for n, d in in_degree.items() if d == 0))
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            # For each node that depends on `node`, reduce its in-degree
            for dependent in sorted(self._get_dependents(node)):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self._nodes):
            # Cycle detected — find one cycle for the error message
            visited_in_result = set(result)
            cycle = self._find_cycle(visited_in_result)
            raise CyclicDependencyError(cycle)

        return result

    def detect_cycles(self) -> list[list[str]]:
        """Detect all cycles in the graph.

        Returns:
            List of cycles, each cycle is a list of field IDs. Empty if no cycles.
        """
        # Iterative DFS (explicit stack) — avoids RecursionError on deep
        # dependency chains (Python's default recursion limit is ~1000).
        UNVISITED, VISITING, VISITED = 0, 1, 2
        state: dict[str, int] = {n: UNVISITED for n in self._nodes}
        cycles: list[list[str]] = []

        for root in sorted(self._nodes):
            if state[root] != UNVISITED:
                continue
            path: list[str] = [root]
            stack = [(root, iter(sorted(self._deps.get(root, set()))))]
            state[root] = VISITING
            while stack:
                node, it = stack[-1]
                advanced = False
                for dep in it:
                    if state.get(dep) == VISITING:
                        cycle_start = path.index(dep)
                        cycles.append(path[cycle_start:] + [dep])
                    elif state.get(dep) == UNVISITED:
                        state[dep] = VISITING
                        path.append(dep)
                        stack.append(
                            (dep, iter(sorted(self._deps.get(dep, set()))))
                        )
                        advanced = True
                        break
                if not advanced:
                    stack.pop()
                    path.pop()
                    state[node] = VISITED

        return cycles

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_dependents(self, field_id: str) -> set[str]:
        """Return the set of fields that directly depend on ``field_id``.

        Args:
            field_id: The field ID to look up.

        Returns:
            Set of field IDs that have ``field_id`` as a dependency.
        """
        dependents: set[str] = set()
        for n, deps in self._deps.items():
            if field_id in deps:
                dependents.add(n)
        return dependents

    def _find_cycle(self, visited: set[str]) -> list[str]:
        """Find one cycle among the unvisited nodes (after Kahn failed).

        Args:
            visited: Set of field IDs that were successfully ordered.

        Returns:
            A list of field IDs forming one cycle.
        """
        remaining = self._nodes - visited
        if not remaining:
            return []

        # Iterative DFS (explicit stack) restricted to the remaining nodes —
        # avoids RecursionError on deep chains (review M-4).
        UNVISITED, VISITING, VISITED = 0, 1, 2
        state: dict[str, int] = {n: UNVISITED for n in remaining}

        def _deps_in_remaining(node: str):
            return iter(
                d for d in sorted(self._deps.get(node, set())) if d in remaining
            )

        for root in sorted(remaining):
            if state.get(root) != UNVISITED:
                continue
            path: list[str] = [root]
            stack = [(root, _deps_in_remaining(root))]
            state[root] = VISITING
            while stack:
                node, it = stack[-1]
                advanced = False
                for dep in it:
                    if state.get(dep) == VISITING:
                        cycle_start = path.index(dep)
                        return path[cycle_start:] + [dep]
                    if state.get(dep) == UNVISITED:
                        state[dep] = VISITING
                        path.append(dep)
                        stack.append((dep, _deps_in_remaining(dep)))
                        advanced = True
                        break
                if not advanced:
                    stack.pop()
                    path.pop()
                    state[node] = VISITED

        return list(remaining)[:2] + [list(remaining)[0]]  # fallback
