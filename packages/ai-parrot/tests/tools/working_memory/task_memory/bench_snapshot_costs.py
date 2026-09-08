#!/usr/bin/env python
"""Phase 0 investigation benchmark for FEAT-538 (TASK-2970).

Runnable deliverable for the specification's Phase 0 gate. It does two
independent things and asserts on both:

1. ``test_contract_inventory`` — statically inventories the concrete
   integration points the feature must hook (direct catalog writes/reads,
   the two ``ToolManager.execute_tool`` dispatch branches plus its
   full-result mode, the plan node's post-dispatch receipt boundary, the
   compression tee, the ordinary/streaming bot render + turn-construction
   call sites, and the REPL worker transport's pickle fallback). The
   inventory is derived by reading the pinned source files, never by
   assuming a universal hook exists.

2. ``test_snapshot_measurements`` — measures independent snapshot (copy)
   and fingerprint (BLAKE2b-8 over canonical content) cost for
   numeric/string DataFrames, nested-object DataFrames and canonical
   JSON/text at 8/64/256 MiB, recording environment, reproducible input
   sizes and the verification limitations of each measurement.

This module is an investigation artifact: it imports nothing from the
(not yet existing) ``parrot.tools.working_memory.task_memory`` package and
implements no production behaviour. Run it directly::

    uv run python packages/ai-parrot/tests/tools/working_memory/task_memory/bench_snapshot_costs.py

Set ``TM_BENCH_MAX_MIB`` to cap the largest measured size on a small host
(default 256). Sizes above the cap are reported as ``skipped``, never as
measured — an environmental skip is not a passed acceptance case.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import platform
import re
import resource
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

MIB: int = 1024 * 1024

#: Sizes the spec's Phase 0 gate requires (§3 Phase 0, AC16).
TARGET_MIB: Tuple[int, ...] = (8, 64, 256)

#: Repository root: …/packages/ai-parrot/tests/tools/working_memory/task_memory/ -> 6 levels up.
REPO_ROOT: Path = Path(__file__).resolve().parents[6]
CORE_SRC: Path = REPO_ROOT / "packages" / "ai-parrot" / "src" / "parrot"


# ─────────────────────────────────────────────────────────────
# 1. Contract inventory
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CallSite:
    """One inventoried integration point.

    Attributes:
        category: Coarse group used by the acceptance assertions.
        path: Repository-relative path of the file containing the site.
        pattern: Regular expression identifying the site in that file.
        note: Why this site matters to the feature.
    """

    category: str
    path: str
    pattern: str
    note: str


#: Every integration point Phase 0 must pin. Each entry is verified to
#: exist by :func:`test_contract_inventory`; a stale entry fails loudly
#: rather than silently shrinking the inventory.
INVENTORY: Tuple[CallSite, ...] = (
    # ── direct catalog writes/reads (no universal hook exists) ──
    CallSite(
        "catalog_write",
        "packages/ai-parrot/src/parrot/tools/working_memory/tool.py",
        r"self\._catalog\.put\(",
        "DataFrame registrations: store/import/operate/compute paths write synchronously.",
    ),
    CallSite(
        "catalog_write",
        "packages/ai-parrot/src/parrot/tools/working_memory/tool.py",
        r"self\._catalog\.put_generic\(",
        "Generic registrations: store_result and the tee land here.",
    ),
    CallSite(
        "catalog_read",
        "packages/ai-parrot/src/parrot/bots/flows/plan/node.py",
        r"catalog\.get\(key\)",
        "PlanToolNode._read_key reads the catalog synchronously, bypassing the toolkit.",
    ),
    CallSite(
        "catalog_read",
        "packages/ai-parrot/src/parrot/bots/flows/plan/node.py",
        r'getattr\(self\.working_memory, "_catalog", None\)',
        "Plan node reaches into the private catalog attribute directly.",
    ),
    # ── manager dispatch branches ──
    CallSite(
        "dispatch_branch",
        "packages/ai-parrot/src/parrot/tools/manager.py",
        r"if isinstance\(tool, ToolDefinition\):",
        "ToolDefinition branch of execute_tool.",
    ),
    CallSite(
        "dispatch_branch",
        "packages/ai-parrot/src/parrot/tools/manager.py",
        r"elif isinstance\(tool, AbstractTool\):",
        "AbstractTool branch of execute_tool.",
    ),
    CallSite(
        "dispatch_branch",
        "packages/ai-parrot/src/parrot/tools/manager.py",
        r"if return_tool_result:",
        "FEAT-536 full-result mode must keep its envelope untouched.",
    ),
    CallSite(
        "dispatch_early_return",
        "packages/ai-parrot/src/parrot/tools/manager.py",
        r'status="not_found"',
        "Unknown tool returns before any execution: executed=False, never a tool body.",
    ),
    CallSite(
        "dispatch_early_return",
        "packages/ai-parrot/src/parrot/tools/manager.py",
        r'status="forbidden"',
        "Guardrail/grant/resolver denials: unsuccessful dispatch, not a failed tool.",
    ),
    CallSite(
        "dispatch_early_return",
        "packages/ai-parrot/src/parrot/tools/manager.py",
        r'status="authorization_required"',
        "AuthorizationRequired is caught and converted, not raised.",
    ),
    # ── plan receipts ──
    CallSite(
        "plan_receipt",
        "packages/ai-parrot/src/parrot/bots/flows/plan/node.py",
        r"await self\.working_memory\.store_result\(",
        "PlanToolNode._store runs AFTER dispatch returned; the call receipt must outlive it.",
    ),
    CallSite(
        "plan_receipt",
        "packages/ai-parrot/src/parrot/bots/flows/plan/node.py",
        r"coro = self\.tool_manager\.execute_tool\(",
        "_call_with_retry is the physical attempt boundary; the parent aggregate is not one.",
    ),
    # ── compression tee ──
    CallSite(
        "tee",
        "packages/ai-parrot/src/parrot/tools/compression/tee.py",
        r"await self\._wm\.store_result\(",
        "Tee write; failure returns None and must surface as tracking_degraded, not evidence.",
    ),
    CallSite(
        "tee",
        "packages/ai-parrot/src/parrot/tools/compression/tee.py",
        r"await self\._wm\.drop_stored\(",
        "Tee retention drops the live alias only; pinned snapshots must survive it.",
    ),
    # ── bot turn lifetime: ordinary and streaming ──
    CallSite(
        "bot_render",
        "packages/ai-parrot/src/parrot/bots/base.py",
        r"await self\.render_context_history\(",
        "Stage 2 injection point; several entry points call it, so the hook cannot be single-site.",
    ),
    CallSite(
        "bot_turn",
        "packages/ai-parrot/src/parrot/bots/base.py",
        r"ConversationTurn\.from_ai_message\(",
        "Turn construction converts AIMessage.tool_calls; enabled turns must replace, not duplicate.",
    ),
    CallSite(
        "bot_render",
        "packages/ai-parrot/src/parrot/bots/data.py",
        r"await self\.render_context_history\(",
        "DataBot render path.",
    ),
    CallSite(
        "bot_render",
        "packages/ai-parrot/src/parrot/bots/voice.py",
        r"await self\.render_context_history\(",
        "Voice/streaming render path.",
    ),
    CallSite(
        "turn_invocations",
        "packages/ai-parrot/src/parrot/memory/abstract.py",
        r"tool_invocations = \[",
        "The legacy list comprehension is the fallback for unobserved turns.",
    ),
    # ── worker transport ──
    CallSite(
        "worker_transport",
        "packages/ai-parrot/src/parrot/tools/repl_worker/transport.py",
        r"pickle\.dumps\(df\)",
        "Arrow failure silently falls back to pickle; strict evidence mode must prevent this branch.",
    ),
    # ── redis association ──
    CallSite(
        "redis_metadata",
        "packages/ai-parrot/src/parrot/memory/redis.py",
        r'meta\["compaction"\] = compaction_state',
        "Non-atomic read-modify-write of the metadata blob; association needs compare-and-merge.",
    ),
    # ── blob I/O ──
    CallSite(
        "file_manager",
        "packages/ai-parrot/src/parrot/interfaces/file/__init__.py",
        r"FileManagerInterface",
        "Compatibility shim re-exporting navigator's file managers; no versioned Parquet store here.",
    ),
)


#: File-manager operations pinned by actually importing the installed
#: interface (never invented). Filled in by :func:`probe_file_manager`.
REQUIRED_FILE_MANAGER_OPS: Tuple[str, ...] = (
    "create_from_bytes",
    "download_file",
    "get_file_metadata",
    "exists",
    "delete_file",
)


def _read(path: str) -> str:
    """Return the text of a repository-relative file.

    Args:
        path: Repository-relative path.

    Returns:
        The file's UTF-8 text.

    Raises:
        FileNotFoundError: If the pinned path no longer exists.
    """
    full = REPO_ROOT / path
    if not full.is_file():
        raise FileNotFoundError(f"pinned path disappeared: {path}")
    return full.read_text(encoding="utf-8")


def probe_file_manager() -> Dict[str, Any]:
    """Introspect the installed navigator file manager without inventing APIs.

    Returns:
        A dict with the resolved interface module, the signatures of the
        byte-stream/stat operations the blob adapter may use, and the set
        of declared abstract methods. On ImportError the dict carries
        ``{"available": False, "error": ...}`` so a missing optional
        dependency is reported as a skip, never as a pass.
    """
    try:
        import inspect

        from parrot.interfaces.file import FileManagerInterface, FileMetadata
    except Exception as exc:  # noqa: BLE001 — environmental, reported honestly
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    signatures: Dict[str, str] = {}
    for name in REQUIRED_FILE_MANAGER_OPS:
        member = getattr(FileManagerInterface, name, None)
        signatures[name] = str(inspect.signature(member)) if member is not None else "MISSING"

    metadata_fields: List[str] = []
    try:
        import dataclasses

        metadata_fields = [f.name for f in dataclasses.fields(FileMetadata)]
    except Exception:  # noqa: BLE001 — shape probe only
        metadata_fields = sorted(getattr(FileMetadata, "model_fields", {}) or {})

    return {
        "available": True,
        "module": FileManagerInterface.__module__,
        "signatures": signatures,
        "metadata_fields": metadata_fields,
        "abstract_methods": sorted(getattr(FileManagerInterface, "__abstractmethods__", ())),
    }


def test_contract_inventory() -> Dict[str, Any]:
    """Verify every pinned integration point still exists in the source.

    Returns:
        A report dict with per-category hit counts and the file-manager
        probe result.

    Raises:
        AssertionError: If any pinned site is missing, or a required
            category ends up empty (which would mean the inventory
            silently assumed a universal hook).
    """
    hits: Dict[str, List[Dict[str, Any]]] = {}
    missing: List[str] = []
    for site in INVENTORY:
        text = _read(site.path)
        found = len(re.findall(site.pattern, text))
        if found == 0:
            missing.append(f"{site.path}::{site.pattern}")
        hits.setdefault(site.category, []).append(
            {"path": site.path, "pattern": site.pattern, "occurrences": found, "note": site.note}
        )

    assert not missing, f"pinned integration points no longer present: {missing}"

    required_categories = {
        "catalog_write",
        "catalog_read",
        "dispatch_branch",
        "dispatch_early_return",
        "plan_receipt",
        "tee",
        "bot_render",
        "bot_turn",
        "turn_invocations",
        "worker_transport",
        "redis_metadata",
        "file_manager",
    }
    assert required_categories <= set(hits), f"inventory missing categories: {required_categories - set(hits)}"

    # There is deliberately NO universal hook: catalog writes are spread
    # across many call sites and the bot render path is called from more
    # than one entry point. Assert that plurality so a future refactor
    # that centralises them forces this map to be revisited.
    catalog_writes = sum(h["occurrences"] for h in hits["catalog_write"])
    assert catalog_writes >= 5, f"expected several direct catalog writes, found {catalog_writes}"
    render_sites = sum(h["occurrences"] for h in hits["bot_render"])
    assert render_sites >= 3, f"expected several render_context_history call sites, found {render_sites}"

    fm = probe_file_manager()
    if fm.get("available"):
        assert "MISSING" not in fm["signatures"].values(), f"file-manager op vanished: {fm['signatures']}"
        assert "size" in fm["metadata_fields"], "FileMetadata must expose a size for bounded reads"

    return {"hits": hits, "file_manager": fm}


# ─────────────────────────────────────────────────────────────
# 2. Snapshot / fingerprint measurements
# ─────────────────────────────────────────────────────────────


def _canonical_json_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes (sorted keys, compact separators).

    Args:
        value: Any JSON-serializable value.

    Returns:
        The encoding used for JSON/text fingerprints in this benchmark's
        stdlib arm.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _canonical_json_bytes_orjson(value: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes using ``orjson`` with sorted keys.

    ``orjson`` is already a core dependency (spec §7). It emits compact
    separators unconditionally and ``OPT_SORT_KEYS`` gives the same
    canonical key order as the stdlib arm, so the two produce identical
    bytes for the JSON subset used here.

    Args:
        value: Any JSON-serializable value.

    Returns:
        The canonical encoding.
    """
    import orjson

    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def fingerprint_dataframe(df: pd.DataFrame) -> str:
    """Fingerprint a DataFrame's canonical content.

    Canonical content is shape, ordered column names, dtype metadata,
    index metadata and stable per-row/index hashes — never the object
    repr and never the Parquet bytes.

    Args:
        df: The DataFrame to fingerprint.

    Returns:
        ``"fp_"`` plus a 16-hex-character BLAKE2b-8 digest.

    Raises:
        TypeError: If pandas cannot hash a column's values (unsupported
            evidence: the caller must mark it unverifiable instead).
    """
    h = hashlib.blake2b(digest_size=8)
    header = {
        "shape": list(df.shape),
        "columns": [str(c) for c in df.columns],
        "dtypes": [str(dt) for dt in df.dtypes],
        "index_name": [str(n) for n in df.index.names],
        "index_dtype": str(df.index.dtype),
    }
    h.update(_canonical_json_bytes(header))
    row_hashes = pd.util.hash_pandas_object(df, index=True, categorize=False)
    h.update(np.ascontiguousarray(row_hashes.to_numpy(dtype="uint64")).tobytes())
    return f"fp_{h.hexdigest()}"


def fingerprint_bytes(payload: bytes) -> str:
    """Fingerprint canonical bytes (JSON/text evidence).

    Args:
        payload: Canonical UTF-8 bytes.

    Returns:
        ``"fp_"`` plus a 16-hex-character BLAKE2b-8 digest.
    """
    return f"fp_{hashlib.blake2b(payload, digest_size=8).hexdigest()}"


def _calibrate(build: Callable[[int], pd.DataFrame], target_bytes: int) -> pd.DataFrame:
    """Build a frame of approximately ``target_bytes`` by measuring, not guessing.

    A small probe frame is built first and its actual deep-accounted
    bytes-per-row measured; the row count is then scaled to the target.
    Hard-coded per-row estimates drift with pandas versions and are exactly
    the kind of unverified assumption this Phase 0 task must avoid.

    Args:
        build: Callable turning a row count into a DataFrame.
        target_bytes: Desired deep memory footprint.

    Returns:
        The calibrated DataFrame.
    """
    probe_rows = 10_000
    probe = build(probe_rows)
    per_row = max(1.0, _deep_bytes(probe) / probe_rows)
    del probe
    gc.collect()
    return build(max(1, int(target_bytes / per_row)))


def _numeric_string_frame(target_bytes: int, seed: int = 1338) -> pd.DataFrame:
    """Build a deterministic numeric/string DataFrame of ~``target_bytes``.

    Args:
        target_bytes: Desired deep memory footprint.
        seed: RNG seed for reproducibility.

    Returns:
        A DataFrame with four float columns, one int column and one short
        string column.
    """

    def build(rows: int) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        return pd.DataFrame(
            {
                "a": rng.random(rows),
                "b": rng.random(rows),
                "c": rng.random(rows),
                "d": rng.random(rows),
                "i": rng.integers(0, 1_000_000, rows),
                "s": pd.Series([f"k{n % 9973:05d}" for n in range(rows)], dtype="object"),
            }
        )

    return _calibrate(build, target_bytes)


def _nested_object_frame(target_bytes: int, seed: int = 4711) -> pd.DataFrame:
    """Build a deterministic DataFrame whose cells are nested mutable dicts.

    Args:
        target_bytes: Desired deep memory footprint.
        seed: RNG seed for reproducibility.

    Returns:
        A DataFrame with one numeric column and one object column holding
        ``dict`` values. A pandas deep copy does NOT detach these dicts —
        that is exactly the false-verification hazard D4 warns about.
    """

    def build(rows: int) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        values = rng.integers(0, 1000, rows)
        payloads = [{"n": int(v), "tags": ["x", "y"], "meta": {"k": f"v{v % 97}"}} for v in values]
        return pd.DataFrame({"v": rng.random(rows), "obj": pd.Series(payloads, dtype="object")})

    return _calibrate(build, target_bytes)


def _deep_bytes(df: pd.DataFrame) -> int:
    """Return the DataFrame's deep memory estimate in bytes.

    Args:
        df: The DataFrame to measure.

    Returns:
        ``df.memory_usage(deep=True).sum()``. This is an *estimate*: it
        does not account for shared string interning or for objects
        referenced by, but not owned by, the frame.
    """
    return int(df.memory_usage(deep=True).sum())


@dataclass
class Measurement:
    """One (kind, size) measurement row.

    Attributes:
        kind: Payload family measured.
        target_mib: Requested size.
        status: ``measured`` or ``skipped``.
        input_bytes: Actual deep-accounted input size, when measured.
        snapshot_seconds: Wall time of the independent snapshot copy.
        snapshot_peak_bytes: ``tracemalloc`` peak attributable to the copy.
        fingerprint_seconds: Wall time of the canonical fingerprint.
        fingerprint: The resulting fingerprint, when computable.
        mutation_detected: Whether mutating the source changed the
            fingerprint while the snapshot's stayed stable.
        detached: Whether the snapshot is genuinely independent of the
            source (False for nested mutable object cells).
        limitations: Free-text verification caveats.
        error: Populated when the payload cannot be fingerprinted at all.
    """

    kind: str
    target_mib: int
    status: str
    input_bytes: Optional[int] = None
    snapshot_seconds: Optional[float] = None
    snapshot_peak_bytes: Optional[int] = None
    fingerprint_seconds: Optional[float] = None
    fingerprint: Optional[str] = None
    mutation_detected: Optional[bool] = None
    detached: Optional[bool] = None
    limitations: List[str] = field(default_factory=list)
    error: Optional[str] = None


def _time_peak(fn: Callable[[], Any]) -> Tuple[Any, float, int]:
    """Run ``fn`` measuring wall time and peak tracemalloc allocation.

    Args:
        fn: Zero-argument callable to measure.

    Returns:
        ``(result, seconds, peak_bytes)``.
    """
    gc.collect()
    tracemalloc.start()
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, peak


def measure_dataframe(kind: str, df: pd.DataFrame, target_mib: int, *, verify: bool = True) -> Measurement:
    """Measure snapshot and fingerprint cost for one DataFrame.

    Args:
        kind: Label for the payload family.
        df: The frame to measure.
        target_mib: The requested size, for reporting.
        verify: When ``True``, additionally run the semantic checks
            (mutation detection, snapshot detachment). These cost three
            further fingerprint passes, so the caller runs them at the
            smallest size only and measures pure cost at the larger ones.

    Returns:
        A populated :class:`Measurement`.
    """
    m = Measurement(kind=kind, target_mib=target_mib, status="measured", input_bytes=_deep_bytes(df))
    snapshot, m.snapshot_seconds, m.snapshot_peak_bytes = _time_peak(lambda: df.copy(deep=True))

    try:
        fp, m.fingerprint_seconds, _ = _time_peak(lambda: fingerprint_dataframe(df))
        m.fingerprint = fp
    except Exception as exc:  # noqa: BLE001 — unsupported evidence is a result, not a crash
        m.error = f"{type(exc).__name__}: {exc}"
        m.limitations.append("unhashable content: evidence must be marked evidence_verifiable=False")
        return m

    obj_cols = [c for c, dt in zip(df.columns, df.dtypes) if str(dt) == "object"]
    nested_col = next((c for c in obj_cols if isinstance(df[c].iloc[0], (dict, list, set))), None)

    if verify:
        # Mutation detection on the SOURCE must not move the SNAPSHOT's
        # fingerprint — that is what makes the snapshot usable as evidence.
        snap_fp = fingerprint_dataframe(snapshot)
        # Column 0 is a float64 column in both fixtures — mutate the SOURCE
        # in place and confirm the fingerprint moves.
        df.iat[0, 0] = float(df.iat[0, 0]) + 1.0
        m.mutation_detected = fingerprint_dataframe(df) != fp
        m.detached = fingerprint_dataframe(snapshot) == snap_fp
    else:
        m.limitations.append("cost-only measurement: semantic verification runs at the smallest size")

    if nested_col is not None:
        # Prove, rather than assume, that deep=True did NOT detach the
        # nested value: both frames still reference the same dict.
        shared = df[nested_col].iloc[0] is snapshot[nested_col].iloc[0]
        m.detached = not shared
        m.limitations.append(
            "pandas deep=True does not detach nested mutable cells "
            f"(shared identity={shared}); requires a safe snapshot adapter or evidence_verifiable=False"
        )
        m.limitations.append(
            "pandas hashes unhashable object cells via their string repr instead of raising, "
            "so a fingerprint over nested-object cells is NOT proof of content integrity"
        )
    m.limitations.append(
        "input_bytes is pandas' deep estimate, not a proof of retained bytes; "
        "tracemalloc peak covers Python allocations only"
    )
    return m


def measure_json_text(target_mib: int, *, serializer: str = "stdlib") -> Measurement:
    """Measure canonical JSON/text snapshot and fingerprint cost.

    Args:
        target_mib: Requested payload size.
        serializer: ``"stdlib"`` (``json.dumps``) or ``"orjson"``. Both
            produce the same canonical bytes for this payload; the arm
            exists to price the choice the implementation must make.

    Returns:
        A populated :class:`Measurement`.
    """
    encode = _canonical_json_bytes if serializer == "stdlib" else _canonical_json_bytes_orjson
    target = target_mib * MIB
    unit = {"id": 0, "name": "row", "tags": ["alpha", "beta"], "note": "ünïcode ✓"}
    unit_bytes = len(encode(unit))
    rows = max(1, target // unit_bytes)
    payload = [{**unit, "id": n} for n in range(rows)]

    m = Measurement(kind=f"json_text_{serializer}", target_mib=target_mib, status="measured")
    encoded, m.snapshot_seconds, m.snapshot_peak_bytes = _time_peak(lambda: encode(payload))
    m.input_bytes = len(encoded)
    fp, m.fingerprint_seconds, _ = _time_peak(lambda: fingerprint_bytes(encoded))
    m.fingerprint = fp
    payload[0]["id"] = -1
    m.mutation_detected = fingerprint_bytes(encode(payload)) != fp
    m.detached = True  # canonical bytes are an immutable snapshot by construction
    m.limitations.append("canonical bytes double memory during encoding: live value + encoded snapshot")
    return m


def environment() -> Dict[str, Any]:
    """Return the environment record accompanying every measurement.

    Returns:
        Interpreter, platform, library versions and the process RSS limit
        observed at import time.
    """
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "max_rss_kb_at_start": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "tm_bench_max_mib": int(os.environ.get("TM_BENCH_MAX_MIB", "256")),
    }


def test_snapshot_measurements() -> Dict[str, Any]:
    """Measure snapshot/fingerprint cost at 8/64/256 MiB and assert invariants.

    Returns:
        A report dict with the environment record and every measurement.

    Raises:
        AssertionError: If a measured size drifts more than 40% from its
            target, if fingerprints are not reproducible, or if a nested
            object frame is reported as safely detached.
    """
    cap = int(os.environ.get("TM_BENCH_MAX_MIB", "256"))
    env = environment()
    results: List[Measurement] = []

    for mib in TARGET_MIB:
        if mib > cap:
            for kind in ("numeric_string_df", "nested_object_df", "json_text_stdlib", "json_text_orjson"):
                results.append(
                    Measurement(
                        kind=kind,
                        target_mib=mib,
                        status="skipped",
                        limitations=[f"skipped: above TM_BENCH_MAX_MIB={cap} (environmental skip, not a pass)"],
                    )
                )
            continue

        # Semantic verification costs three extra fingerprint passes; run it
        # at the smallest size and measure pure cost at the larger ones.
        verify = mib == min(TARGET_MIB)

        num_df = _numeric_string_frame(mib * MIB)
        results.append(measure_dataframe("numeric_string_df", num_df, mib, verify=verify))
        del num_df
        gc.collect()

        obj_df = _nested_object_frame(mib * MIB)
        results.append(measure_dataframe("nested_object_df", obj_df, mib, verify=verify))
        del obj_df
        gc.collect()

        results.append(measure_json_text(mib, serializer="stdlib"))
        gc.collect()

        results.append(measure_json_text(mib, serializer="orjson"))
        gc.collect()

    measured = [m for m in results if m.status == "measured"]
    assert measured, "no measurement ran; every size was skipped"

    for m in measured:
        assert m.input_bytes is not None
        ratio = m.input_bytes / (m.target_mib * MIB)
        assert 0.6 <= ratio <= 1.6, f"{m.kind}@{m.target_mib}MiB drifted from target: ratio={ratio:.2f}"
        assert m.fingerprint or m.error, f"{m.kind}@{m.target_mib}MiB produced neither fingerprint nor error"
        if m.fingerprint and m.mutation_detected is not None:
            assert m.mutation_detected is True, f"{m.kind}@{m.target_mib}MiB: mutation went undetected"

    # Reproducibility: the same deterministic input yields the same
    # fingerprint in a fresh object.
    a = _numeric_string_frame(1 * MIB)
    b = _numeric_string_frame(1 * MIB)
    assert fingerprint_dataframe(a) == fingerprint_dataframe(b), "fingerprint is not reproducible"

    # Nested mutable cells are never reported as safely detached.
    for m in measured:
        if m.kind == "nested_object_df":
            assert m.detached is False, "nested object frame must not claim a detached snapshot"

    return {"environment": env, "measurements": [asdict(m) for m in results]}


def main() -> int:
    """Run both Phase 0 checks and print a JSON report.

    Returns:
        Process exit code: 0 on success, 1 on any assertion failure.
    """
    report: Dict[str, Any] = {"feature": "FEAT-538", "task": "TASK-2970"}
    try:
        report["contract_inventory"] = test_contract_inventory()
        report["snapshot_measurements"] = test_snapshot_measurements()
    except AssertionError as exc:
        report["failure"] = str(exc)
        print(json.dumps(report, indent=2, default=str))
        return 1
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
