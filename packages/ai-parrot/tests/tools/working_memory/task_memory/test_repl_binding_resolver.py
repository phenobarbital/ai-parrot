"""Generation-bound REPL evidence materialization (FEAT-538 / TASK-2993).

Three required cases from the task's Test Specification:

- ``test_generation`` — a restarted or replaced worker invalidates only
  its live binding; the resolver returns a new generation-bound binding.
- ``test_scope_size_hash`` — a foreign scope, an oversized load or a hash
  mismatch is rejected **before** injection.
- ``test_explicit_only`` — recall and descriptor reads never invoke the
  resolver or load data.

Two things this module is careful about:

*Refusals are asserted to happen before injection*, not merely to happen.
A resolver that loaded and injected and *then* returned a refusal would
pass a naive "it raised" assertion while having already done the damage,
so the worker doubles here count their calls and the tests assert zero.

*A stale binding and lost bytes are asserted separately.* Both halves of
"``binding_invalid`` but still locatable" are checked, because collapsing
them in either direction is a real failure: reporting lost evidence as a
stale binding hides data loss, and reporting a stale binding as lost
evidence would make a routine worker restart look like corruption.
"""

from __future__ import annotations

import ast
import asyncio
import concurrent.futures
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest
from parrot.tools.repl_worker.protocol import TransportEnvelope
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import ArtifactKind, EvidenceRef, TaskScope
from parrot.tools.working_memory.task_memory.repl import BindingStatus, ReplBindingResolver, ReplLoadRefusal, WorkerLike

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_USER = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")
OTHER_BOT = TaskScope(chatbot_id="bot-b", user_id="user-1", session_id="sess-1")
OTHER_SESSION = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-2")


def _referenced_names(tree: ast.AST) -> set:
    """Return every identifier a module's CODE references.

    Docstrings and comments are excluded by construction, because this
    walks the parsed tree rather than the source text. That distinction
    matters: a module may legitimately *document* that it never calls
    something, and a substring search over the source would flag its own
    explanation as a violation.

    Args:
        tree: A parsed module.

    Returns:
        The set of ``Name`` ids and ``Attribute`` attribute names used.
    """
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def frame(rows: int = 3) -> pd.DataFrame:
    """Return a small Arrow-representable frame.

    Args:
        rows: Row count.

    Returns:
        A numeric/string DataFrame.
    """
    return pd.DataFrame({"n": range(rows), "s": [f"r{i}" for i in range(rows)]})


class CountingWorker:
    """A worker double that records every injection it is asked to do.

    Counting rather than merely recording is deliberate: several tests
    assert a refusal happened **before** injection, and that claim is only
    checkable if the double can report that it was never called.
    """

    def __init__(self, generation: str = "gen-1") -> None:
        """Initialize the double.

        Args:
            generation: The generation identity to report.
        """
        self._generation = generation
        self.namespace: Dict[str, Any] = {}
        self.injections: List[str] = []
        self.envelopes: List[Optional[TransportEnvelope]] = []
        self.strict_flags: List[bool] = []

    @property
    def generation(self) -> str:
        """Stable identity of this worker generation."""
        return self._generation

    def restart(self, generation: str) -> None:
        """Simulate a worker restart: new generation, empty namespace.

        Args:
            generation: The new generation identity.
        """
        self._generation = generation
        self.namespace.clear()

    async def inject_dataframe(
        self,
        name: str,
        df: Any,
        *,
        strict: bool = False,
        envelope: Any = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        """Record and perform a DataFrame injection."""
        self.injections.append(name)
        self.envelopes.append(envelope)
        self.strict_flags.append(strict)
        self.namespace[name] = df

    async def set_var(self, name: str, value: Any) -> None:
        """Record and perform a variable assignment."""
        self.injections.append(name)
        self.namespace[name] = value

    @property
    def call_count(self) -> int:
        """How many injections this worker was asked to perform."""
        return len(self.injections)


@pytest.fixture()
async def store():
    """Yield a fresh in-memory artifact store."""
    backend = InMemoryArtifactStore()
    try:
        yield backend
    finally:
        await backend.close()


@pytest.fixture()
def resolver(store: InMemoryArtifactStore) -> ReplBindingResolver:
    """Yield a resolver over the store."""
    return ReplBindingResolver(store)


def make_inprocess_handle():
    """Build a real :class:`InProcessHandle` over a minimal fake tool.

    A real ``PythonREPLTool`` pulls in the whole REPL stack; the handle
    only needs ``locals``/``globals`` for the namespace API under test.

    Returns:
        A ``(handle, tool)`` pair.
    """
    from parrot.tools.repl_worker.inprocess import InProcessHandle

    class _FakeTool:
        def __init__(self) -> None:
            self.locals: dict = {}
            self.globals: dict = {}

        def reset_environment(self) -> None:
            self.locals.clear()
            self.globals.clear()

    tool = _FakeTool()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    return InProcessHandle(tool, executor, deadline_ms=5_000), tool  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────
# test_generation
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generation_stale_binding_does_not_lose_the_artifact(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """A gone generation yields binding_invalid — and the artifact stays locatable.

    BOTH halves are asserted. Collapsing them in either direction is a
    real failure: reporting lost evidence as a stale binding hides data
    loss, and reporting a stale binding as lost evidence makes a routine
    worker restart look like corruption.
    """
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")
    worker = CountingWorker("gen-CURRENT")

    result = await resolver.load(
        SCOPE,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        "gen-GONE",
        worker=worker,
        task_id="t-1",
    )

    assert result.status is BindingStatus.BINDING_INVALID
    assert result.artifact_locatable is True, "a stale binding is not lost bytes"
    assert result.binding is None
    assert worker.call_count == 0, "a stale generation must not inject anything"

    # And the artifact really is still resolvable.
    assert await store.get_version(SCOPE, descriptor.ref, task_id="t-1") is not None


@pytest.mark.asyncio
async def test_generation_rebinding_after_restart_returns_a_new_binding(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """After a restart the resolver rebinds against the NEW generation."""
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")
    worker = CountingWorker("gen-1")

    first = await resolver.load(
        SCOPE,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        "gen-1",
        worker=worker,
        task_id="t-1",
    )
    assert first.ok
    assert first.binding is not None
    assert first.binding.worker_session_id == "gen-1"
    assert "sales" in worker.namespace

    # The worker restarts: new generation, namespace gone.
    worker.restart("gen-2")
    assert "sales" not in worker.namespace

    stale = await resolver.load(
        SCOPE,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        "gen-1",
        worker=worker,
        task_id="t-1",
    )
    assert stale.status is BindingStatus.BINDING_INVALID

    rebound = await resolver.load(
        SCOPE,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        "gen-2",
        worker=worker,
        task_id="t-1",
    )
    assert rebound.ok
    assert rebound.binding is not None
    assert rebound.binding.worker_session_id == "gen-2", "the new binding is bound to the NEW generation"
    assert rebound.binding.ref == descriptor.ref, "the same exact version, rebound"
    assert "sales" in worker.namespace


@pytest.mark.asyncio
async def test_generation_binding_carries_the_envelope(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """The injection carries a bounded envelope naming the live generation."""
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")
    worker = CountingWorker("gen-7")

    result = await resolver.load(
        SCOPE,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        worker=worker,
        task_id="t-1",
        fencing_token=42,
    )
    assert result.ok

    envelope = worker.envelopes[0]
    assert isinstance(envelope, TransportEnvelope)
    assert envelope.worker_generation == "gen-7"
    assert envelope.artifact_id == descriptor.ref.artifact_id
    assert envelope.version == descriptor.ref.version
    assert envelope.task_id == "t-1"
    assert envelope.fencing_token == 42
    assert envelope.scope_key == SCOPE.cache_key()
    assert worker.strict_flags == [True], "task evidence must always use the strict path"


@pytest.mark.asyncio
async def test_generation_none_binds_to_whatever_worker_is_live(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """Omitting the expected generation binds to the current worker."""
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")
    worker = CountingWorker("gen-whatever")

    result = await resolver.load(
        SCOPE, descriptor.ref.artifact_id, descriptor.ref.version, worker=worker, task_id="t-1"
    )
    assert result.ok
    assert result.binding is not None and result.binding.worker_session_id == "gen-whatever"


@pytest.mark.asyncio
async def test_generation() -> None:
    """Required aggregate case: restarts invalidate only the binding."""
    for case in (
        test_generation_stale_binding_does_not_lose_the_artifact,
        test_generation_rebinding_after_restart_returns_a_new_binding,
        test_generation_binding_carries_the_envelope,
        test_generation_none_binds_to_whatever_worker_is_live,
    ):
        backend = InMemoryArtifactStore()
        try:
            await case(backend, ReplBindingResolver(backend))
        finally:
            await backend.close()


# ─────────────────────────────────────────────────────────────
# test_scope_size_hash
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_size_hash_foreign_scope_rejects_before_injection(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """A version from another scope never resolves, and nothing is injected.

    Each scope component is varied independently, and absence is
    indistinguishable from foreign on purpose — telling them apart would
    make this an existence oracle for another scope's artifact ids.
    """
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")

    for foreign in (OTHER_USER, OTHER_BOT, OTHER_SESSION):
        worker = CountingWorker()
        result = await resolver.load(
            foreign,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
            worker=worker,
            task_id="t-1",
        )
        assert result.status is BindingStatus.REFUSED
        assert result.refusal == ReplLoadRefusal.UNKNOWN_VERSION
        assert result.artifact_locatable is False
        assert worker.call_count == 0, "a foreign scope must not inject anything"

    # A genuinely nonexistent version fails identically.
    worker = CountingWorker()
    absent = await resolver.load(SCOPE, "no-such-artifact", 1, worker=worker, task_id="t-1")
    assert absent.refusal == ReplLoadRefusal.UNKNOWN_VERSION
    assert worker.call_count == 0


@pytest.mark.asyncio
async def test_scope_size_hash_oversized_rejects_before_injection(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """An over-ceiling payload is refused, carrying no payload and injecting nothing."""
    descriptor = await store.put(SCOPE, "big", frame(500), task_id="t-1")
    worker = CountingWorker()

    result = await resolver.load(
        SCOPE,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        worker=worker,
        task_id="t-1",
        max_bytes=16,
    )
    assert result.status is BindingStatus.REFUSED
    assert result.refusal == ReplLoadRefusal.TOO_LARGE
    assert result.artifact_locatable is True, "too big to load is not gone"
    assert worker.call_count == 0, "the ceiling must be enforced BEFORE injection"
    assert result.guidance


@pytest.mark.asyncio
async def test_scope_size_hash_ceiling_is_a_hard_configured_maximum(
    store: InMemoryArtifactStore,
) -> None:
    """A caller may lower the byte ceiling but never raise it."""
    tight = ReplBindingResolver(store, TaskMemoryConfig(max_rehydrate_bytes=32))
    descriptor = await store.put(SCOPE, "sales", frame(200), task_id="t-1")
    worker = CountingWorker()

    # Asking for far more than the configured hard ceiling does not lift it.
    result = await tight.load(
        SCOPE,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        worker=worker,
        task_id="t-1",
        max_bytes=10_000_000,
    )
    assert result.refusal == ReplLoadRefusal.TOO_LARGE
    assert worker.call_count == 0

    # And 0 means never rehydrate, whatever the caller asks for.
    never = ReplBindingResolver(store, TaskMemoryConfig(max_rehydrate_bytes=0))
    small = await store.put(SCOPE, "tiny", {"a": 1}, task_id="t-1")
    worker2 = CountingWorker()
    disabled = await never.load(
        SCOPE,
        small.ref.artifact_id,
        small.ref.version,
        worker=worker2,
        task_id="t-1",
        max_bytes=10_000,
    )
    assert disabled.refusal == ReplLoadRefusal.TOO_LARGE
    assert worker2.call_count == 0


@pytest.mark.asyncio
async def test_scope_size_hash_fingerprint_mismatch_rejects_before_injection(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """Content that no longer matches its recorded fingerprint is never bound.

    This is the evidence chain's last line of defence: binding content
    that differs from what was fingerprinted would let a completed step
    cite a variable that is not what was verified.
    """
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")
    worker = CountingWorker()

    # Return a DIFFERENT frame than the one that was fingerprinted.
    original = store.load_payload

    async def _tampered(scope, ref, *, max_bytes, offset=None, limit=None):
        result = await original(scope, ref, max_bytes=max_bytes, offset=offset, limit=limit)
        return result.model_copy(update={"payload": frame(99)})

    store.load_payload = _tampered  # type: ignore[assignment]
    try:
        result = await resolver.load(
            SCOPE,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
            worker=worker,
            task_id="t-1",
        )
    finally:
        store.load_payload = original  # type: ignore[assignment]

    assert result.status is BindingStatus.REFUSED
    assert result.refusal == ReplLoadRefusal.FINGERPRINT_MISMATCH
    assert result.artifact_locatable is True
    assert worker.call_count == 0, "the fingerprint must be verified BEFORE injection"


@pytest.mark.asyncio
async def test_scope_size_hash_unverifiable_and_unsupported_are_refused(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """Unverifiable and unsupported evidence cannot be bound at all."""
    # A nested-object frame is UNVERIFIABLE: pandas repr-hashes it, so a
    # computable fingerprint would not prove content integrity.
    nested = pd.DataFrame({"v": [1.0], "obj": pd.Series([{"a": 1}], dtype="object")})
    descriptor = await store.put(SCOPE, "nested", nested, task_id="t-1")
    assert descriptor.evidence_verifiable is False

    worker = CountingWorker()
    result = await resolver.load(
        SCOPE, descriptor.ref.artifact_id, descriptor.ref.version, worker=worker, task_id="t-1"
    )
    assert result.status is BindingStatus.REFUSED
    assert result.refusal in (ReplLoadRefusal.UNVERIFIABLE, ReplLoadRefusal.UNSUPPORTED)
    assert result.artifact_locatable is True
    assert worker.call_count == 0


@pytest.mark.asyncio
async def test_scope_size_hash_invalidated_evidence_is_refused(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """An invalidated version is refused, but is still locatable."""
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")
    await store.invalidate(SCOPE, descriptor.ref, reason="source mutated")

    worker = CountingWorker()
    result = await resolver.load(
        SCOPE, descriptor.ref.artifact_id, descriptor.ref.version, worker=worker, task_id="t-1"
    )
    assert result.status is BindingStatus.REFUSED
    assert result.refusal == ReplLoadRefusal.INVALIDATED
    assert result.artifact_locatable is True
    assert worker.call_count == 0


@pytest.mark.asyncio
async def test_scope_size_hash() -> None:
    """Required aggregate case: scope, size and hash all reject before injection."""
    for case in (
        test_scope_size_hash_foreign_scope_rejects_before_injection,
        test_scope_size_hash_oversized_rejects_before_injection,
        test_scope_size_hash_fingerprint_mismatch_rejects_before_injection,
        test_scope_size_hash_unverifiable_and_unsupported_are_refused,
        test_scope_size_hash_invalidated_evidence_is_refused,
    ):
        backend = InMemoryArtifactStore()
        try:
            await case(backend, ReplBindingResolver(backend))
        finally:
            await backend.close()

    backend = InMemoryArtifactStore()
    try:
        await test_scope_size_hash_ceiling_is_a_hard_configured_maximum(backend)
    finally:
        await backend.close()


# ─────────────────────────────────────────────────────────────
# test_explicit_only
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_only_describe_never_materializes(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """``describe`` reports on a binding without loading or injecting."""
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")

    loads = {"n": 0}
    original = store.load_payload

    async def _counting(scope, ref, *, max_bytes, offset=None, limit=None):
        loads["n"] += 1
        return await original(scope, ref, max_bytes=max_bytes, offset=offset, limit=limit)

    store.load_payload = _counting  # type: ignore[assignment]
    try:
        described = await resolver.describe(
            SCOPE, descriptor.ref.artifact_id, descriptor.ref.version, "gen-1", task_id="t-1"
        )
    finally:
        store.load_payload = original  # type: ignore[assignment]

    assert loads["n"] == 0, "describe() must never load a payload"
    assert described.binding is None or described.binding.ref == descriptor.ref


@pytest.mark.asyncio
async def test_explicit_only_describe_reports_stale_without_touching_anything(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """A stale generation is diagnosable without any materialization."""
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")

    described = await resolver.describe(
        SCOPE, descriptor.ref.artifact_id, descriptor.ref.version, "gen-GONE", task_id="t-1"
    )
    assert described.status is BindingStatus.BINDING_INVALID
    assert described.artifact_locatable is True


@pytest.mark.asyncio
async def test_explicit_only_recall_does_not_import_the_resolver() -> None:
    """The recall path cannot invoke the resolver — it does not import it.

    Checked structurally. A runtime assertion would only prove the
    resolver was not reached on the paths a test happened to exercise;
    the absence of the import proves it cannot be reached at all.
    """
    from parrot.tools.working_memory.task_memory import recall as recall_module

    tree = ast.parse(Path(recall_module.__file__).read_text(encoding="utf-8"))

    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)

    assert not any("repl" in name for name in imported), f"recall imports a REPL module: {imported}"
    assert "ReplBindingResolver" not in _referenced_names(tree)
    # Nor does it load payloads. Checked over the AST rather than the raw
    # text: recall's own docstring legitimately says it never calls
    # `load_payload`, and a substring search would flag that prose.
    assert "load_payload" not in _referenced_names(tree), "recall must never load an artifact payload"


@pytest.mark.asyncio
async def test_explicit_only_no_pickle_path_for_task_evidence() -> None:
    """The resolver has no pickle path at all.

    Asserted structurally as well as behaviourally: a runtime test only
    proves pickle was not reached on the paths exercised, whereas the
    absence of any reference proves it cannot be reached.
    """
    from parrot.tools.working_memory.task_memory import repl as repl_module

    tree = ast.parse(Path(repl_module.__file__).read_text(encoding="utf-8"))

    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "pickle" not in imported
    # Over the AST, not the raw text: the module docstring explains that
    # there is no pickle fallback, and a substring search would flag that
    # sentence. What matters is that no *code* references pickle.
    assert not {n for n in _referenced_names(tree) if "pickle" in n.lower()}

    # And every injection it performs is strict.
    load_src = inspect.getsource(ReplBindingResolver.load)
    assert "strict=True" in load_src


@pytest.mark.asyncio
async def test_explicit_only_binding_published_only_after_acknowledgement(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """A failed injection yields no binding.

    The binding is the claim "this value is live in that worker". If the
    injection never completed, publishing one would be a lie.
    """
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")

    class _FailingWorker(CountingWorker):
        async def inject_dataframe(self, name, df, *, strict=False, envelope=None, max_bytes=None):
            self.injections.append(name)
            raise RuntimeError("worker died mid-injection")

    worker = _FailingWorker("gen-1")
    with pytest.raises(RuntimeError, match="worker died"):
        await resolver.load(
            SCOPE,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
            worker=worker,
            task_id="t-1",
        )
    assert worker.namespace == {}, "nothing was bound"


@pytest.mark.asyncio
async def test_explicit_only_never_restores_a_namespace(
    store: InMemoryArtifactStore, resolver: ReplBindingResolver
) -> None:
    """One explicit request binds exactly one variable, never a namespace."""
    a = await store.put(SCOPE, "alpha", frame(), task_id="t-1")
    await store.put(SCOPE, "beta", frame(), task_id="t-1")
    await store.put(SCOPE, "gamma", {"x": 1}, task_id="t-1")

    worker = CountingWorker()
    result = await resolver.load(SCOPE, a.ref.artifact_id, a.ref.version, worker=worker, task_id="t-1")
    assert result.ok
    assert list(worker.namespace) == ["alpha"], "only the requested variable is bound"
    assert worker.call_count == 1

    # There is no bulk entry point to restore the rest.
    public = {n for n, m in vars(ReplBindingResolver).items() if not n.startswith("_") and callable(m)}
    assert public == {"describe", "load"}, f"unexpected public surface: {public}"


@pytest.mark.asyncio
async def test_explicit_only() -> None:
    """Required aggregate case: reads never materialize; loads are explicit."""
    await test_explicit_only_recall_does_not_import_the_resolver()
    await test_explicit_only_no_pickle_path_for_task_evidence()
    for case in (
        test_explicit_only_describe_never_materializes,
        test_explicit_only_describe_reports_stale_without_touching_anything,
        test_explicit_only_binding_published_only_after_acknowledgement,
        test_explicit_only_never_restores_a_namespace,
    ):
        backend = InMemoryArtifactStore()
        try:
            await case(backend, ReplBindingResolver(backend))
        finally:
            await backend.close()


# ─────────────────────────────────────────────────────────────
# Real handles: in-process and a real subprocess
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_inprocess_handle_round_trip(store: InMemoryArtifactStore) -> None:
    """A real ``InProcessHandle`` receives the frame and satisfies the protocol."""
    resolver = ReplBindingResolver(store)
    descriptor = await store.put(SCOPE, "sales", frame(), task_id="t-1")

    handle, tool = make_inprocess_handle()
    try:
        assert isinstance(handle, WorkerLike), "InProcessHandle must satisfy the worker protocol"

        result = await resolver.load(
            SCOPE,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
            handle.generation,
            worker=handle,
            task_id="t-1",
        )
        assert result.ok
        assert result.binding is not None
        assert result.binding.worker_session_id == handle.generation
        pd.testing.assert_frame_equal(tool.locals["sales"], frame())

        # JSON evidence travels as a safe value, not a pickle.
        cfg = await store.put(SCOPE, "cfg", {"a": 1, "b": [1, 2]}, task_id="t-1")
        json_result = await resolver.load(SCOPE, cfg.ref.artifact_id, cfg.ref.version, worker=handle, task_id="t-1")
        assert json_result.ok
        assert tool.locals["cfg"] == {"a": 1, "b": [1, 2]}
    finally:
        await handle.kill()


@pytest.mark.asyncio
async def test_real_subprocess_worker_round_trip(store: InMemoryArtifactStore) -> None:
    """A REAL worker subprocess receives strictly-transported evidence.

    This is the only case that crosses an actual process boundary. It
    skips **explicitly** — reported as an environmental skip, never as a
    pass — when a worker cannot be spawned here.
    """
    from parrot.tools.repl_worker.handle import WorkerHandle

    resolver = ReplBindingResolver(store)
    descriptor = await store.put(SCOPE, "sales", frame(20), task_id="t-1")

    handle = WorkerHandle()
    try:
        try:
            await asyncio.wait_for(handle.start(), timeout=60)
            await asyncio.wait_for(handle.wait_ready(), timeout=60)
        except Exception as exc:  # noqa: BLE001 — environmental, reported as a skip
            pytest.skip(
                "ENVIRONMENTAL SKIP, not a pass: a REPL worker subprocess could not be "
                f"started here, so no cross-process behaviour was exercised ({exc!r})"
            )

        assert isinstance(handle, WorkerLike)
        assert isinstance(handle.generation, str) and len(handle.generation) == 32

        result = await resolver.load(
            SCOPE,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
            handle.generation,
            worker=handle,
            task_id="t-1",
        )
        assert result.ok, f"load refused: {result.refusal} {result.guidance}"
        assert result.binding is not None
        assert result.binding.worker_session_id == handle.generation
        assert result.binding.variable_name == "sales"

        # The frame really crossed the boundary intact.
        got = await handle.get_var("sales")
        pd.testing.assert_frame_equal(got, frame(20))

        # A stale generation refuses without touching the live worker.
        stale = await resolver.load(
            SCOPE,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
            "gen-GONE",
            worker=handle,
            task_id="t-1",
        )
        assert stale.status is BindingStatus.BINDING_INVALID
        assert stale.artifact_locatable is True
    finally:
        await handle.kill()
