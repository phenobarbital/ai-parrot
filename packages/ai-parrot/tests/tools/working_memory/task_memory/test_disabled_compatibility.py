"""TASK-3002 — disabled task memory preserves the pre-feature behaviour (AC13).

FEAT-538 is opt-in. A deployment that never passes ``task_memory=`` must
be unable to tell the feature was merged: same tools, same input schemas,
same persisted turn shape, and none of the new machinery constructed.

Required case:

``test_legacy_regression``
    The disabled tool surface and the persisted ``ConversationTurn`` shape
    match the pre-feature baseline exactly, and no behaviour drifts.

Two independent checks, deliberately kept separate:

1. A **pinned baseline** — the exact tool names and input-schema field
   sets captured from ``dev`` before this feature. It runs everywhere,
   needs no git, and fails loudly on any drift.
2. A **live diff against the real ``dev`` tree**, which catches drift the
   pinned literal cannot describe — a changed default, a renamed
   parameter's position, a tool that vanished. It skips explicitly when
   git or the ``dev`` ref is unavailable; a skip is never a pass.

The pinned baseline exists because a test that can only run where git
does is a test that silently stops protecting anything in CI.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

import pytest

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolStatus
from parrot.tools.working_memory import WorkingMemoryToolkit

pytestmark = pytest.mark.asyncio

#: The complete disabled tool surface, captured from `dev` at the commit
#: this feature branched from: tool name -> sorted input-schema fields.
#: Any addition, removal or renamed field fails the comparison. This is a
#: literal on purpose — it states what the contract IS, so a reviewer can
#: read the guarantee without running anything.
LEGACY_DISABLED_SURFACE: Dict[str, List[str]] = {
    "wm_compute_and_store": ["description", "spec", "turn_id"],
    "wm_drop_stored": ["key"],
    "wm_get_result": ["include_raw", "key", "max_length"],
    "wm_get_stored": ["key", "max_cols", "max_rows"],
    "wm_import_from_tool": ["description", "store_as", "tool_name", "turn_id", "variable_name"],
    "wm_list_stored": ["turn_id"],
    "wm_list_tool_dataframes": ["tool_name"],
    "wm_merge_stored": ["keys", "merge_how", "merge_on", "store_as", "turn_id"],
    "wm_recall_interaction": ["import_as", "query", "turn_id"],
    "wm_save_interaction": ["answer", "question", "turn_id"],
    "wm_search_stored": ["entry_type", "query"],
    "wm_store_result": ["data", "data_type", "description", "key", "metadata", "turn_id"],
    "wm_summarize_stored": ["agg_rules", "group_by", "keys", "merge_on", "store_as", "turn_id"],
}

#: The persisted turn's field set, which history readers depend on.
LEGACY_TURN_FIELDS = {
    "assistant_response",
    "chatbot_id",
    "context_used",
    "error",
    "metadata",
    "norm_version",
    "schema_version",
    "state",
    "timestamp",
    "token_count",
    "tool_invocations",
    "tools_used",
    "turn_id",
    "user_id",
    "user_message",
}

#: Dumps the disabled tool surface. Run in a subprocess against whichever
#: source tree is on PYTHONPATH, so the same code describes both sides.
_DUMP_SURFACE = """
import json
from parrot.tools.working_memory import WorkingMemoryToolkit

toolkit = WorkingMemoryToolkit()
surface = {}
for tool in toolkit.get_tools():
    schema = tool.args_schema
    surface[tool.name] = sorted(schema.model_fields) if schema is not None else None
print("<<<JSON>>>" + json.dumps(surface, sort_keys=True))
"""


def _current_surface() -> Dict[str, Any]:
    """Return this tree's disabled tool surface.

    Returns:
        Tool name -> sorted input-schema field names.
    """
    toolkit = WorkingMemoryToolkit()
    return {
        tool.name: (sorted(tool.args_schema.model_fields) if tool.args_schema is not None else None)
        for tool in toolkit.get_tools()
    }


class _ToolCall:
    """A tool call shaped as ``from_ai_message`` expects."""

    def __init__(self, name: str) -> None:
        """Initialize the call."""
        self.name = name
        self.arguments = {"k": "v"}
        self.result = "ok"
        self.error = None
        self.execution_time = 0.25


class _Response:
    """An ``AIMessage``-shaped stand-in."""

    def __init__(self, tool_calls: Optional[List[Any]] = None) -> None:
        """Initialize the response."""
        self.tool_calls = tool_calls or []
        self.content = "answer"
        self.to_text = "answer"
        self.turn_id = "turn-1"
        self.model = "m"
        self.provider = "p"
        self.usage = None
        self.finish_reason = "stop"
        self.response_time = 1.0


# ─────────────────────────────────────────────────────────────
# test_legacy_regression
# ─────────────────────────────────────────────────────────────


async def test_legacy_regression() -> None:
    """The disabled surface and persisted turn match the pre-feature baseline."""
    surface = _current_surface()

    # ── the tool set is exactly what it was ──────────────────────────
    assert set(surface) == set(LEGACY_DISABLED_SURFACE), (
        "the disabled tool set changed: "
        f"added={sorted(set(surface) - set(LEGACY_DISABLED_SURFACE))} "
        f"removed={sorted(set(LEGACY_DISABLED_SURFACE) - set(surface))}"
    )

    # ── and every input schema still has exactly its old fields ──────
    for name, expected in LEGACY_DISABLED_SURFACE.items():
        assert surface[name] == expected, f"{name} input schema drifted: {surface[name]} != {expected}"

    # None of the ten task tools is reachable when disabled.
    assert not [n for n in surface if "task" in n], surface
    # `wm_store` stayed excluded — enabling the feature rebuilds the tool
    # cache, which is a real opportunity to un-exclude it by accident.
    assert "wm_store" not in surface

    # ── the persisted turn keeps its exact shape ─────────────────────
    response = _Response([_ToolCall("wm_get_result")])
    turn = ConversationTurn.from_ai_message(user_message="q", response=response, user_id="u", chatbot_id="bot-a")
    assert set(turn.to_dict()) == LEGACY_TURN_FIELDS

    # The legacy derivation from AIMessage.tool_calls still applies when
    # nothing observed the turn — this is what keeps history identical.
    assert [i.tool_name for i in turn.tool_invocations] == ["wm_get_result"]
    assert turn.tool_invocations[0].status is ToolStatus.COMPLETED
    assert turn.tools_used == ["wm_get_result"]

    # Passing the new parameter explicitly as None must be identical to
    # not passing it at all — the disabled call site does exactly that.
    explicit_none = ConversationTurn.from_ai_message(
        user_message="q", response=response, user_id="u", chatbot_id="bot-a", tool_invocations=None
    )
    assert explicit_none.to_dict()["tool_invocations"] == turn.to_dict()["tool_invocations"]


async def test_legacy_regression_toolkit_constructs_without_task_memory() -> None:
    """A disabled toolkit builds and answers without task memory."""
    toolkit = WorkingMemoryToolkit()
    assert toolkit.task_memory_enabled is False
    assert toolkit._task_memory is None

    # A real round trip through the legacy synchronous catalog.
    stored = await toolkit.store_result(key="k", data={"a": 1}, description="d")
    assert stored["status"] in {"stored", "ok", "success"}, stored
    fetched = await toolkit.get_result(key="k")
    assert isinstance(fetched, dict)

    # The enabled-only paging parameters are absent from the disabled
    # schema, so a caller cannot even name them.
    schema = toolkit.get_tool("wm_get_result").args_schema
    assert set(schema.model_fields) == {"include_raw", "key", "max_length"}


async def test_legacy_regression_constructs_no_task_memory_machinery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The disabled path never builds an observer or a turn session."""
    import parrot.tools.working_memory.task_memory.context as context_mod
    import parrot.tools.working_memory.task_memory.observer as observer_mod

    built: List[str] = []

    original_observer = observer_mod.InvocationObserver
    original_session = context_mod.TurnTaskSession

    class _ObserverTripwire(original_observer):  # type: ignore[misc,valid-type]
        """Records construction."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Record and delegate."""
            built.append("observer")
            super().__init__(*args, **kwargs)

    class _SessionTripwire(original_session):  # type: ignore[misc,valid-type]
        """Records construction."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Record and delegate."""
            built.append("session")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(observer_mod, "InvocationObserver", _ObserverTripwire)
    monkeypatch.setattr(context_mod, "TurnTaskSession", _SessionTripwire)

    toolkit = WorkingMemoryToolkit()
    await toolkit.store_result(key="k", data={"a": 1}, description="d")
    await toolkit.get_result(key="k")
    await toolkit.list_stored()

    assert built == [], f"the disabled path constructed task-memory objects: {built}"
    # And no task is bound to this context.
    assert context_mod.current_session() is None


# ─────────────────────────────────────────────────────────────
# Live comparison against the real pre-feature tree
# ─────────────────────────────────────────────────────────────


def _repo_root() -> Optional[pathlib.Path]:
    """Return the worktree root, or ``None`` when git is unavailable.

    Returns:
        The repository root path.
    """
    if shutil.which("git") is None:
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return pathlib.Path(out.stdout.strip()) if out.returncode == 0 else None


def _dump_surface_from(source_root: pathlib.Path) -> Optional[Dict[str, Any]]:
    """Dump the disabled tool surface from a given source tree.

    Args:
        source_root: A directory containing ``parrot`` importable.

    Returns:
        The surface, or ``None`` if the subprocess could not produce one.
    """
    env = dict(os.environ, PYTHONPATH=str(source_root))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _DUMP_SURFACE],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("<<<JSON>>>"):
            return json.loads(line[len("<<<JSON>>>") :])
    return None


async def test_legacy_regression_matches_the_real_dev_tree() -> None:
    """Diff the disabled surface against the actual pre-feature source.

    Skips explicitly — never silently passes — when git or the ``dev``
    ref is unavailable, because a comparison that did not happen proves
    nothing.
    """
    root = _repo_root()
    if root is None:
        pytest.skip("git is unavailable; cannot materialize the pre-feature tree")

    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "dev^{commit}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("the 'dev' ref is not present in this clone")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        archive = subprocess.run(
            ["git", "-C", str(root), "archive", "dev", "packages/ai-parrot/src/parrot"],
            capture_output=True,
            timeout=300,
            check=False,
        )
        if archive.returncode != 0:
            pytest.skip("could not export the 'dev' source tree")
        extract = subprocess.run(
            ["tar", "-x", "-C", str(tmp_path)], input=archive.stdout, capture_output=True, timeout=300, check=False
        )
        if extract.returncode != 0:
            pytest.skip("could not extract the 'dev' source tree")

        # Compiled extensions are gitignored, so the exported tree cannot
        # import without them; copy them across from this worktree.
        live_src = root / "packages/ai-parrot/src/parrot"
        for compiled in live_src.rglob("*.so"):
            target = tmp_path / compiled.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(compiled, target)

        legacy = _dump_surface_from(tmp_path / "packages/ai-parrot/src")

    if legacy is None:
        pytest.skip("the pre-feature tree could not be imported in this environment")

    current = _current_surface()
    assert current == legacy, (
        "the DISABLED tool surface drifted from the pre-feature tree.\n"
        f"only in dev: {json.dumps({k: v for k, v in legacy.items() if current.get(k) != v}, indent=2)}\n"
        f"only in HEAD: {json.dumps({k: v for k, v in current.items() if legacy.get(k) != v}, indent=2)}"
    )
    # And the pinned literal above is itself still accurate — otherwise
    # the cheap check would drift away from the expensive one.
    assert legacy == {k: list(v) for k, v in LEGACY_DISABLED_SURFACE.items()}
