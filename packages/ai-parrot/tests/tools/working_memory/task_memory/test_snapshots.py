"""Unit tests for bounded snapshots and fingerprints (FEAT-538 / TASK-2975).

Three required cases from the task's Test Specification:

- ``test_independence`` — mutating the live input never mutates a
  captured snapshot, and nested object cells are handled explicitly
  rather than optimistically.
- ``test_fingerprint`` — reload-equivalent content hashes identically,
  while column/dtype/index/value changes all move the fingerprint.
- ``test_size_limit`` — the cap boundary and unsupported types report
  true memory and verification status, never ``sys.getsizeof``-style
  false confidence.

Each is implemented as a group of focused functions plus an aggregate
function carrying the required name, so a failure names the specific
invariant that broke rather than just the group.

Fixtures are local: the shared-fixture task is not complete, and these
tests deliberately depend on nothing beyond the committed domain models.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import orjson
import pandas as pd
import pytest
from parrot.tools.working_memory.task_memory.config import MIB, TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    ArtifactDescriptor,
    ArtifactKind,
    EvidenceRef,
    Limits,
    TaskScope,
)
from parrot.tools.working_memory.task_memory.snapshots import (
    CHECKSUM_ALGORITHM,
    CHECKSUM_PREFIX,
    FINGERPRINT_ALGORITHM,
    FINGERPRINT_PREFIX,
    MAX_SUMMARY_COLUMNS,
    ByteAccount,
    ContentSnapshot,
    SizeMethod,
    SnapshotOutcome,
    UnsupportedEvidence,
    blob_checksum,
    canonical_json_bytes,
    capture_snapshot,
    capture_snapshot_async,
    dataframe_schema_summary,
    detect_kind,
    fingerprint_bytes,
    fingerprint_dataframe,
    unsafe_object_columns,
)

CAP: int = 64 * MIB


# ─────────────────────────────────────────────────────────────
# Local fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture()
def scope() -> TaskScope:
    """Return a deterministic trusted scope."""
    return TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


@pytest.fixture()
def simple_df() -> pd.DataFrame:
    """Return a small numeric/string frame — supported evidence."""
    return pd.DataFrame(
        {
            "a": np.array([1, 2, 3], dtype="int64"),
            "b": ["x", "y", "z"],
            "c": np.array([1.5, 2.5, 3.5], dtype="float64"),
        }
    )


@pytest.fixture()
def nested_df() -> pd.DataFrame:
    """Return a frame whose object column holds nested mutable dicts."""
    return pd.DataFrame({"v": [1.0, 2.0], "obj": [{"a": 1}, {"b": 2}]})


# ─────────────────────────────────────────────────────────────
# Independence
# ─────────────────────────────────────────────────────────────


def test_independence_dataframe_snapshot_is_detached(simple_df: pd.DataFrame) -> None:
    """Mutating the live frame leaves the captured snapshot untouched."""
    snapshot = capture_snapshot(simple_df, max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.CAPTURED
    assert snapshot.evidence_verifiable is True

    captured = snapshot.payload
    before = fingerprint_dataframe(captured)

    simple_df.iloc[0, 0] = 999
    simple_df.loc[0, "b"] = "MUTATED"

    assert captured.iloc[0, 0] == 1, "snapshot must not follow the live frame"
    assert captured.loc[0, "b"] == "x"
    assert fingerprint_dataframe(captured) == before
    assert fingerprint_dataframe(simple_df) != before, "the live frame's fingerprint must move"


def test_independence_snapshot_survives_column_addition(simple_df: pd.DataFrame) -> None:
    """Structural mutation of the live frame does not reach the snapshot."""
    snapshot = capture_snapshot(simple_df, max_bytes=CAP)
    simple_df["d"] = [7, 8, 9]

    assert list(snapshot.payload.columns) == ["a", "b", "c"]
    assert snapshot.shape == (3, 3)


def test_independence_nested_object_cells_are_refused(nested_df: pd.DataFrame) -> None:
    """A frame with nested mutable cells is explicitly unverifiable.

    This is the central honesty rule: ``copy(deep=True)`` does not detach
    such cells, and pandas hashes them by ``repr``, so a fingerprint over
    them would be a false integrity claim.
    """
    snapshot = capture_snapshot(nested_df, max_bytes=CAP)

    assert snapshot.outcome is SnapshotOutcome.UNVERIFIABLE
    assert snapshot.evidence_verifiable is False
    assert snapshot.payload is None, "a refusal must retain no bytes"
    assert "obj" in snapshot.reason
    # Structure is still described — the refusal is informative.
    assert snapshot.shape == (2, 2)
    assert snapshot.schema_summary is not None


def test_independence_proves_deep_copy_does_not_detach(nested_df: pd.DataFrame) -> None:
    """Demonstrate the pandas behaviour the refusal above is protecting against.

    If this ever stops being true, the conservative refusal can be
    revisited — until then it is load-bearing.
    """
    copied = nested_df.copy(deep=True)
    assert copied["obj"].iloc[0] is nested_df["obj"].iloc[0], "deep=True still aliases nested cells"

    nested_df["obj"].iloc[0]["a"] = 99
    assert copied["obj"].iloc[0]["a"] == 99, "the 'copy' followed the mutation"


def test_independence_pandas_repr_hashes_unhashable_cells(nested_df: pd.DataFrame) -> None:
    """Demonstrate that a computable digest is not an integrity proof.

    pandas does not raise on dict cells; it hashes their ``repr``. Two
    semantically equal dicts with different key order therefore hash
    differently, which is why such a digest cannot back a completion.
    """
    hashed = pd.util.hash_pandas_object(nested_df, index=True, categorize=False)
    assert len(hashed) == 2, "pandas produced a digest rather than raising"

    left = pd.DataFrame({"o": [{"a": 1, "b": 2}]})
    right = pd.DataFrame({"o": [{"b": 2, "a": 1}]})
    left_hash = list(pd.util.hash_pandas_object(left, categorize=False))
    right_hash = list(pd.util.hash_pandas_object(right, categorize=False))
    assert left_hash != right_hash, "equal content, different digest — a repr artefact"

    # And so both are refused rather than trusted.
    assert capture_snapshot(left, max_bytes=CAP).evidence_verifiable is False
    assert capture_snapshot(right, max_bytes=CAP).evidence_verifiable is False


def test_independence_list_cells_raise_and_are_refused() -> None:
    """A column of list cells makes pandas raise; the refusal is still graceful."""
    frame = pd.DataFrame({"l": [[1, 2], [3]]})
    with pytest.raises(UnsupportedEvidence):
        fingerprint_dataframe(frame)

    snapshot = capture_snapshot(frame, max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.UNVERIFIABLE
    assert snapshot.payload is None


def test_independence_immutable_object_columns_are_allowed() -> None:
    """Object columns holding only immutable scalars remain verifiable."""
    frame = pd.DataFrame(
        {
            "s": ["a", "b"],
            "mixed": [None, "text"],
            "num": [Decimal("1.5"), Decimal("2.5")],
            "when": [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)],
        }
    )
    assert unsafe_object_columns(frame) == ()

    snapshot = capture_snapshot(frame, max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.CAPTURED
    assert snapshot.evidence_verifiable is True


def test_independence_tuple_and_frozenset_cells_are_conservatively_refused() -> None:
    """Immutable containers are still refused: they can hide mutables or reorder."""
    assert unsafe_object_columns(pd.DataFrame({"t": [(1, 2), (3, 4)]})) == ("t",)
    assert unsafe_object_columns(pd.DataFrame({"f": [frozenset({1}), frozenset({2})]})) == ("f",)


def test_independence_json_snapshot_is_detached() -> None:
    """A JSON snapshot round-trips through canonical bytes, so it is detached."""
    live = {"outer": {"inner": [1, 2, 3]}, "n": 1}
    snapshot = capture_snapshot(live, max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.CAPTURED

    live["outer"]["inner"].append(4)
    live["n"] = 99

    assert snapshot.payload["outer"]["inner"] == [1, 2, 3]
    assert snapshot.payload["n"] == 1
    assert snapshot.payload["outer"] is not live["outer"]


def test_independence_text_snapshot_is_the_value() -> None:
    """``str`` is immutable, so it is its own snapshot."""
    snapshot = capture_snapshot("hello world", max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.CAPTURED
    assert snapshot.payload == "hello world"


@pytest.mark.asyncio
async def test_independence_async_matches_sync(simple_df: pd.DataFrame) -> None:
    """The threaded path produces the same result and mutates no shared state."""
    sync = capture_snapshot(simple_df, max_bytes=CAP)
    first, second = await asyncio.gather(
        capture_snapshot_async(simple_df, max_bytes=CAP),
        capture_snapshot_async(simple_df, max_bytes=CAP),
    )
    assert first.fingerprint == second.fingerprint == sync.fingerprint
    assert first.outcome is second.outcome is sync.outcome
    # The source frame is untouched by having been snapshotted.
    assert list(simple_df.columns) == ["a", "b", "c"]


def test_independence() -> None:
    """Required aggregate case: snapshots are independent of their live input."""

    def df() -> pd.DataFrame:
        """Rebuild the ``simple_df`` fixture's frame (each case mutates its input)."""
        return pd.DataFrame(
            {
                "a": np.array([1, 2, 3], dtype="int64"),
                "b": ["x", "y", "z"],
                "c": np.array([1.5, 2.5, 3.5], dtype="float64"),
            }
        )

    nested = pd.DataFrame({"v": [1.0, 2.0], "obj": [{"a": 1}, {"b": 2}]})

    test_independence_dataframe_snapshot_is_detached(df())
    test_independence_snapshot_survives_column_addition(df())
    test_independence_nested_object_cells_are_refused(nested.copy())
    test_independence_proves_deep_copy_does_not_detach(nested.copy())
    test_independence_pandas_repr_hashes_unhashable_cells(nested.copy())
    test_independence_list_cells_raise_and_are_refused()
    test_independence_immutable_object_columns_are_allowed()
    test_independence_json_snapshot_is_detached()
    test_independence_text_snapshot_is_the_value()


# ─────────────────────────────────────────────────────────────
# Fingerprints
# ─────────────────────────────────────────────────────────────


def test_fingerprint_is_reproducible(simple_df: pd.DataFrame) -> None:
    """The same content fingerprints identically across independent objects."""
    twin = pd.DataFrame(
        {
            "a": np.array([1, 2, 3], dtype="int64"),
            "b": ["x", "y", "z"],
            "c": np.array([1.5, 2.5, 3.5], dtype="float64"),
        }
    )
    assert fingerprint_dataframe(simple_df) == fingerprint_dataframe(twin)
    assert fingerprint_dataframe(simple_df).startswith(FINGERPRINT_PREFIX)
    assert len(fingerprint_dataframe(simple_df)) == len(FINGERPRINT_PREFIX) + 16


def test_fingerprint_survives_a_parquet_reload(simple_df: pd.DataFrame) -> None:
    """Reload-equivalent content hashes identically.

    A Parquet round trip is the realistic "reload" path for spilled
    evidence, so the serializer must reproduce the same *content*
    fingerprint even though the stored bytes differ.
    """
    buffer = io.BytesIO()
    simple_df.to_parquet(buffer, index=True)
    buffer.seek(0)
    reloaded = pd.read_parquet(buffer)

    assert reloaded is not simple_df
    assert fingerprint_dataframe(reloaded) == fingerprint_dataframe(simple_df)


def test_fingerprint_detects_value_change(simple_df: pd.DataFrame) -> None:
    """Changing one cell changes the fingerprint."""
    before = fingerprint_dataframe(simple_df)
    changed = simple_df.copy()
    changed.iloc[0, 0] = 99
    assert fingerprint_dataframe(changed) != before


def test_fingerprint_detects_column_rename(simple_df: pd.DataFrame) -> None:
    """Renaming a column changes the fingerprint.

    Load-bearing: ``hash_pandas_object`` alone does **not** notice a
    rename, so this proves the ordered column names really are folded
    into the header.
    """
    before = fingerprint_dataframe(simple_df)
    renamed = simple_df.rename(columns={"a": "A"})

    row_hashes_unchanged = list(pd.util.hash_pandas_object(renamed, index=True, categorize=False)) == list(
        pd.util.hash_pandas_object(simple_df, index=True, categorize=False)
    )
    assert row_hashes_unchanged, "premise: row hashes are blind to column names"
    assert fingerprint_dataframe(renamed) != before, "the header must catch what row hashes miss"


def test_fingerprint_detects_column_reorder(simple_df: pd.DataFrame) -> None:
    """Reordering columns changes the fingerprint."""
    before = fingerprint_dataframe(simple_df)
    assert fingerprint_dataframe(simple_df[["c", "b", "a"]]) != before


def test_fingerprint_detects_dtype_change(simple_df: pd.DataFrame) -> None:
    """Changing a dtype changes the fingerprint even with equal values."""
    before = fingerprint_dataframe(simple_df)
    retyped = simple_df.astype({"a": "float64"})
    assert (retyped["a"] == simple_df["a"]).all(), "premise: the values compare equal"
    assert fingerprint_dataframe(retyped) != before


def test_fingerprint_detects_index_change(simple_df: pd.DataFrame) -> None:
    """Changing the index changes the fingerprint."""
    before = fingerprint_dataframe(simple_df)
    reindexed = simple_df.set_index(pd.Index([10, 11, 12], name="rid"))
    assert fingerprint_dataframe(reindexed) != before


def test_fingerprint_detects_row_order_change(simple_df: pd.DataFrame) -> None:
    """Reordering rows changes the fingerprint."""
    before = fingerprint_dataframe(simple_df)
    assert fingerprint_dataframe(simple_df.iloc[::-1]) != before


def test_fingerprint_json_is_key_order_independent() -> None:
    """Canonical JSON sorts keys, so key order is not content."""
    left = capture_snapshot({"b": 1, "a": 2}, max_bytes=CAP)
    right = capture_snapshot({"a": 2, "b": 1}, max_bytes=CAP)
    assert left.fingerprint == right.fingerprint

    different = capture_snapshot({"a": 2, "b": 99}, max_bytes=CAP)
    assert different.fingerprint != left.fingerprint


def test_fingerprint_json_rejects_non_string_keys() -> None:
    """Non-string keys are refused rather than stringified into a collision.

    With ``OPT_NON_STR_KEYS`` orjson would encode ``{1: "a"}`` and
    ``{"1": "a"}`` identically, handing two different values the same
    fingerprint. Strict encoding refuses instead.
    """
    with pytest.raises(UnsupportedEvidence):
        canonical_json_bytes({1: "a"})

    snapshot = capture_snapshot({1: "a"}, max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.UNVERIFIABLE
    assert snapshot.evidence_verifiable is False


def test_fingerprint_json_rejects_arbitrary_objects() -> None:
    """A non-serializable value gets no digest at all, rather than a repr digest."""
    with pytest.raises(UnsupportedEvidence):
        canonical_json_bytes({"o": object()})

    snapshot = capture_snapshot({"o": object()}, max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.UNVERIFIABLE
    assert snapshot.fingerprint is None


def test_fingerprint_text_is_utf8_canonical() -> None:
    """Text fingerprints are over canonical UTF-8 bytes."""
    snapshot = capture_snapshot("ünïcode ✓", max_bytes=CAP)
    assert snapshot.fingerprint == fingerprint_bytes("ünïcode ✓".encode("utf-8"))
    assert capture_snapshot("ünïcode ✗", max_bytes=CAP).fingerprint != snapshot.fingerprint


def test_fingerprint_algorithm_version_is_recorded(simple_df: pd.DataFrame) -> None:
    """Every fingerprint travels with the algorithm identity that produced it."""
    snapshot = capture_snapshot(simple_df, max_bytes=CAP)
    assert snapshot.fingerprint_algorithm == FINGERPRINT_ALGORITHM == "blake2b-8/v1"

    # And the version is inside the hashed header, so a rules change
    # cannot silently produce a colliding digest.
    assert FINGERPRINT_ALGORITHM.encode() in canonical_json_bytes(
        {
            "algorithm": FINGERPRINT_ALGORITHM,
            "shape": [3, 3],
            "columns": ["a", "b", "c"],
            "dtypes": ["int64", "object", "float64"],
            "index_names": ["None"],
            "index_dtype": "int64",
        }
    )


def test_fingerprint_blob_checksum_is_distinct_from_content(simple_df: pd.DataFrame) -> None:
    """A blob checksum and a content fingerprint are not interchangeable."""
    buffer = io.BytesIO()
    simple_df.to_parquet(buffer, index=True)
    parquet_bytes = buffer.getvalue()

    checksum = blob_checksum(parquet_bytes)
    content = fingerprint_dataframe(simple_df)

    assert checksum.startswith(CHECKSUM_PREFIX)
    assert content.startswith(FINGERPRINT_PREFIX)
    assert CHECKSUM_PREFIX != FINGERPRINT_PREFIX
    assert checksum != content
    assert CHECKSUM_ALGORITHM != FINGERPRINT_ALGORITHM

    # The prefixes are what stop the two ever being compared by accident.
    assert not checksum.startswith(FINGERPRINT_PREFIX)


def test_fingerprint_descriptor_accepts_a_verified_snapshot(scope: TaskScope, simple_df: pd.DataFrame) -> None:
    """A captured snapshot's fields satisfy ArtifactDescriptor's verifiability rule."""
    snapshot = capture_snapshot(simple_df, max_bytes=CAP)
    descriptor = ArtifactDescriptor(
        ref=EvidenceRef(artifact_id="art-1", version=1),
        scope=scope,
        kind=snapshot.kind,
        fingerprint=snapshot.fingerprint,
        fingerprint_algorithm=snapshot.fingerprint_algorithm,
        evidence_verifiable=snapshot.evidence_verifiable,
        byte_size=snapshot.account.snapshot_bytes,
        shape=snapshot.shape,
        schema_summary=snapshot.schema_summary,
    )
    assert descriptor.evidence_verifiable is True
    assert descriptor.fingerprint_algorithm == FINGERPRINT_ALGORITHM


def test_fingerprint_descriptor_rejects_a_laundered_claim(scope: TaskScope, nested_df: pd.DataFrame) -> None:
    """An unverifiable snapshot cannot be upgraded into a verified descriptor."""
    snapshot = capture_snapshot(nested_df, max_bytes=CAP)
    assert snapshot.evidence_verifiable is False
    assert snapshot.fingerprint is None

    with pytest.raises(ValueError, match="requires a fingerprint"):
        ArtifactDescriptor(
            ref=EvidenceRef(artifact_id="art-1", version=1),
            scope=scope,
            kind=snapshot.kind,
            fingerprint=snapshot.fingerprint,
            evidence_verifiable=True,
        )


def test_fingerprint_empty_frame_is_still_verifiable() -> None:
    """An empty frame is legitimate, verifiable evidence."""
    empty = pd.DataFrame({"a": pd.Series(dtype="int64")})
    snapshot = capture_snapshot(empty, max_bytes=CAP)
    assert snapshot.outcome is SnapshotOutcome.CAPTURED
    assert snapshot.shape == (0, 1)
    # Distinguishable from a differently-shaped empty frame.
    other = pd.DataFrame({"b": pd.Series(dtype="int64")})
    assert capture_snapshot(other, max_bytes=CAP).fingerprint != snapshot.fingerprint


def test_fingerprint() -> None:
    """Required aggregate case: fingerprints are reproducible and sensitive."""
    df = pd.DataFrame(
        {
            "a": np.array([1, 2, 3], dtype="int64"),
            "b": ["x", "y", "z"],
            "c": np.array([1.5, 2.5, 3.5], dtype="float64"),
        }
    )
    test_fingerprint_is_reproducible(df)
    test_fingerprint_survives_a_parquet_reload(df)
    test_fingerprint_detects_value_change(df)
    test_fingerprint_detects_column_rename(df)
    test_fingerprint_detects_column_reorder(df)
    test_fingerprint_detects_dtype_change(df)
    test_fingerprint_detects_index_change(df)
    test_fingerprint_detects_row_order_change(df)
    test_fingerprint_json_is_key_order_independent()
    test_fingerprint_json_rejects_non_string_keys()
    test_fingerprint_text_is_utf8_canonical()
    test_fingerprint_blob_checksum_is_distinct_from_content(df)
    test_fingerprint_empty_frame_is_still_verifiable()


# ─────────────────────────────────────────────────────────────
# Size limits
# ─────────────────────────────────────────────────────────────


def test_size_limit_cap_boundary_for_text() -> None:
    """Text at exactly the cap is captured; one byte over spills."""
    at_cap = "a" * 1_000
    exactly = capture_snapshot(at_cap, max_bytes=1_000)
    assert exactly.outcome is SnapshotOutcome.CAPTURED
    assert exactly.account.snapshot_bytes == 1_000

    over = capture_snapshot("a" * 1_001, max_bytes=1_000)
    assert over.outcome is SnapshotOutcome.SPILL_REQUIRED
    assert over.payload is None, "an over-cap value must not be retained"
    assert over.evidence_verifiable is False


def test_size_limit_multibyte_text_is_measured_in_bytes() -> None:
    """The cap is a byte cap: multibyte text is measured after encoding."""
    text = "✓" * 400  # 400 characters, 1200 UTF-8 bytes
    assert len(text) == 400
    assert len(text.encode("utf-8")) == 1_200

    # Under the character count but over the byte count.
    over = capture_snapshot(text, max_bytes=1_000)
    assert over.outcome is SnapshotOutcome.SPILL_REQUIRED
    assert over.account.live_bytes == 1_200

    under = capture_snapshot(text, max_bytes=2_000)
    assert under.outcome is SnapshotOutcome.CAPTURED
    assert under.account.snapshot_bytes == 1_200


def test_size_limit_huge_text_is_rejected_before_encoding() -> None:
    """A string longer than the cap is refused without being encoded."""
    huge = "x" * 100_000
    result = capture_snapshot(huge, max_bytes=1_000)
    assert result.outcome is SnapshotOutcome.SPILL_REQUIRED
    # live_bytes is None precisely because encoding was skipped — an
    # honest "not measured" rather than a fabricated number.
    assert result.account.live_bytes is None
    assert result.shape == (100_000,)


def test_size_limit_zero_cap_never_retains(simple_df: pd.DataFrame) -> None:
    """``max_bytes=0`` means never keep a RAM snapshot."""
    for value in (simple_df, "text", {"a": 1}):
        result = capture_snapshot(value, max_bytes=0)
        assert result.outcome is SnapshotOutcome.SPILL_REQUIRED
        assert result.payload is None


def test_size_limit_negative_cap_is_a_caller_bug(simple_df: pd.DataFrame) -> None:
    """A negative cap raises rather than being clamped."""
    with pytest.raises(ValueError, match="max_bytes must be >= 0"):
        capture_snapshot(simple_df, max_bytes=-1)


def test_size_limit_dataframe_over_cap_is_not_copied() -> None:
    """An over-cap frame is refused on the estimate, before any copy is made."""
    frame = pd.DataFrame({"a": np.arange(50_000, dtype="int64")})
    estimate = int(frame.memory_usage(deep=True).sum())
    assert estimate > 1_000

    result = capture_snapshot(frame, max_bytes=1_000)
    assert result.outcome is SnapshotOutcome.SPILL_REQUIRED
    assert result.payload is None
    assert result.account.snapshot_bytes == 0
    assert result.account.live_bytes == estimate
    assert "durable tier" in result.reason


def test_size_limit_reports_estimates_as_estimates(simple_df: pd.DataFrame) -> None:
    """DataFrame accounting is labelled an estimate; byte accounting is not."""
    frame = capture_snapshot(simple_df, max_bytes=CAP)
    assert frame.account.method is SizeMethod.PANDAS_DEEP_ESTIMATE
    assert frame.account.exact is False, "pandas deep memory is an estimate and must say so"

    text = capture_snapshot("hello", max_bytes=CAP)
    assert text.account.method is SizeMethod.CANONICAL_UTF8
    assert text.account.exact is True

    payload = capture_snapshot({"a": 1}, max_bytes=CAP)
    assert payload.account.exact is True


def test_size_limit_accounts_live_and_snapshot_separately(simple_df: pd.DataFrame) -> None:
    """Both copies are counted, because both are resident at once."""
    result = capture_snapshot(simple_df, max_bytes=CAP)
    assert result.account.live_bytes is not None
    assert result.account.snapshot_bytes > 0
    assert result.account.total_retained == result.account.live_bytes + result.account.snapshot_bytes


def test_size_limit_unsupported_object_reports_unknown_size() -> None:
    """An arbitrary object's footprint is reported unknown, never guessed.

    ``sys.getsizeof`` would return the shallow container size — a number
    that looks like an answer while proving nothing about what the object
    references.
    """

    class Custom:
        def __init__(self) -> None:
            self.payload = list(range(10_000))

    result = capture_snapshot(Custom(), max_bytes=CAP)
    assert result.outcome is SnapshotOutcome.UNVERIFIABLE
    assert result.kind is ArtifactKind.OBJECT
    assert result.account.method is SizeMethod.UNKNOWN
    assert result.account.live_bytes is None, "an unknown size must be None, not a getsizeof guess"
    assert result.account.exact is False
    assert result.fingerprint is None
    assert result.payload is None


def test_size_limit_binary_is_measured_but_unverifiable() -> None:
    """Bytes get an exact size and a checksum, but never a verifiability claim."""
    result = capture_snapshot(b"\x00\x01\x02", max_bytes=CAP)
    assert result.kind is ArtifactKind.BINARY
    assert result.outcome is SnapshotOutcome.UNVERIFIABLE
    assert result.evidence_verifiable is False
    assert result.account.live_bytes == 3
    assert result.account.exact is True
    assert result.schema_summary["checksum"].startswith(CHECKSUM_PREFIX)


def test_size_limit_json_over_cap_retains_nothing() -> None:
    """An over-cap JSON value releases its encode buffer and retains no snapshot."""
    payload = {"rows": [{"i": n, "pad": "x" * 50} for n in range(500)]}
    encoded = len(canonical_json_bytes(payload))
    assert encoded > 1_000

    result = capture_snapshot(payload, max_bytes=1_000)
    assert result.outcome is SnapshotOutcome.SPILL_REQUIRED
    assert result.payload is None
    assert result.account.live_bytes == encoded
    assert result.account.snapshot_bytes == 0


def test_size_limit_schema_summary_stays_within_bound() -> None:
    """A wide frame's schema summary is truncated, not oversized or dropped."""
    wide = pd.DataFrame({f"column_name_number_{i:04d}": [1.0] for i in range(2_000)})
    summary = dataframe_schema_summary(wide)

    assert len(canonical_json_bytes(summary)) <= Limits.MAX_SCHEMA_SUMMARY_BYTES
    assert summary["column_count"] == 2_000
    assert summary["columns_truncated"] is True
    assert len(summary["columns"]) <= MAX_SUMMARY_COLUMNS

    # And the resulting descriptor is constructible — the bound is real.
    snapshot = capture_snapshot(wide, max_bytes=CAP)
    ArtifactDescriptor(
        ref=EvidenceRef(artifact_id="a", version=1),
        scope=TaskScope(chatbot_id="b", user_id="u", session_id="s"),
        kind=snapshot.kind,
        fingerprint=snapshot.fingerprint,
        fingerprint_algorithm=snapshot.fingerprint_algorithm,
        evidence_verifiable=snapshot.evidence_verifiable,
        schema_summary=snapshot.schema_summary,
    )


def test_size_limit_declared_kind_mismatch_is_refused(simple_df: pd.DataFrame) -> None:
    """A forced kind that contradicts the value is not trusted."""
    result = capture_snapshot(simple_df, kind=ArtifactKind.JSON, max_bytes=CAP)
    assert result.outcome is SnapshotOutcome.UNVERIFIABLE
    assert "does not match" in result.reason


def test_size_limit_uses_configured_default() -> None:
    """The configured 64 MiB default is the cap callers get by default."""
    config = TaskMemoryConfig()
    assert config.snapshot_max_bytes == 64 * MIB

    result = capture_snapshot(pd.DataFrame({"a": [1]}), max_bytes=config.snapshot_max_bytes)
    assert result.outcome is SnapshotOutcome.CAPTURED


def test_size_limit() -> None:
    """Required aggregate case: caps and unsupported types report true status."""
    df = pd.DataFrame(
        {
            "a": np.array([1, 2, 3], dtype="int64"),
            "b": ["x", "y", "z"],
            "c": np.array([1.5, 2.5, 3.5], dtype="float64"),
        }
    )
    test_size_limit_cap_boundary_for_text()
    test_size_limit_multibyte_text_is_measured_in_bytes()
    test_size_limit_huge_text_is_rejected_before_encoding()
    test_size_limit_zero_cap_never_retains(df)
    test_size_limit_negative_cap_is_a_caller_bug(df)
    test_size_limit_dataframe_over_cap_is_not_copied()
    test_size_limit_reports_estimates_as_estimates(df)
    test_size_limit_accounts_live_and_snapshot_separately(df)
    test_size_limit_unsupported_object_reports_unknown_size()
    test_size_limit_binary_is_measured_but_unverifiable()
    test_size_limit_json_over_cap_retains_nothing()
    test_size_limit_schema_summary_stays_within_bound()
    test_size_limit_declared_kind_mismatch_is_refused(df)


# ─────────────────────────────────────────────────────────────
# Kind detection
# ─────────────────────────────────────────────────────────────


def test_detect_kind_covers_every_supported_type() -> None:
    """Detection maps each value to its evidence type."""
    assert detect_kind(pd.DataFrame()) is ArtifactKind.DATAFRAME
    assert detect_kind("text") is ArtifactKind.TEXT
    assert detect_kind(b"bytes") is ArtifactKind.BINARY
    assert detect_kind(bytearray(b"x")) is ArtifactKind.BINARY
    assert detect_kind({"a": 1}) is ArtifactKind.JSON
    assert detect_kind([1, 2]) is ArtifactKind.JSON
    assert detect_kind(object()) is ArtifactKind.OBJECT
    assert detect_kind(None) is ArtifactKind.OBJECT

    assert ArtifactKind.DATAFRAME.is_supported_evidence
    assert ArtifactKind.JSON.is_supported_evidence
    assert ArtifactKind.TEXT.is_supported_evidence
    assert not ArtifactKind.BINARY.is_supported_evidence
    assert not ArtifactKind.OBJECT.is_supported_evidence


def test_snapshot_dataclasses_are_frozen(simple_df: pd.DataFrame) -> None:
    """Outcomes are immutable records, not mutable scratch space."""
    result = capture_snapshot(simple_df, max_bytes=CAP)
    assert isinstance(result, ContentSnapshot)
    assert isinstance(result.account, ByteAccount)
    with pytest.raises(Exception):
        result.evidence_verifiable = True  # type: ignore[misc]
    with pytest.raises(Exception):
        result.account.snapshot_bytes = 0  # type: ignore[misc]


def test_captured_property_matches_outcome(simple_df: pd.DataFrame) -> None:
    """``captured`` is a convenience view of ``outcome``, never a second truth."""
    assert capture_snapshot(simple_df, max_bytes=CAP).captured is True
    assert capture_snapshot(simple_df, max_bytes=0).captured is False
    assert capture_snapshot(object(), max_bytes=CAP).captured is False


def test_fingerprint_bytes_matches_orjson_canonical_form() -> None:
    """JSON fingerprints are over the exact canonical encoding."""
    value = {"b": [1, 2], "a": "x"}
    encoded = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    assert canonical_json_bytes(value) == encoded
    assert capture_snapshot(value, max_bytes=CAP).fingerprint == fingerprint_bytes(encoded)
