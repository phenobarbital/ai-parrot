"""``profile_execution.py`` — offline versioned execution profiling (FEAT-584 M7/R7).

Reconstructs *requests* (not raw transcript rows) and *spans* (not naive
next-timestamp pairing) by explicit identity, from explicit ``--events``/
``--transcript`` file paths. Never discovers files on its own -- no scanning
of private home sessions, no execution of local profiling scripts (spec R7:
"no ejecutar ni importar sin revisión los scripts de profiling locales con
rutas personales").

Two independent JSON Lines sources, each line one JSON object:

``--events`` (required)
    One object per line, structurally shaped like
    ``parrot.flows.dev_loop.sdd_coder.optimization_models.WorkflowEvent``
    (this module deliberately does not import that class so it stays
    framework-decoupled). The expected fields are pinned by the
    ``ProfileEventRecord`` TypedDict below; parity with the authoritative
    Pydantic model is machine-verified by
    ``test_event_schema_parity_with_workflow_event`` (FEAT-596).

``--transcript`` (optional)
    One row per line from a host transcript. The expected fields are
    pinned by the ``ProfileTranscriptRow`` TypedDict below.

Historical bug this module structurally cannot reproduce: the previous
profiler summed per-category interval unions and then subtracted an
overlap figure computed separately, double-subtracting shared time between
categories (spec evidence: 36.2% vs the corrected 39.0%). Here the GLOBAL
union is computed once, directly, by merging every resolved span's real
(start, end) pair (see ``_merge_intervals``); per-category buckets are a
SEPARATE, independent union of only that category's spans, and are
expected to overlap the global union and each other -- their sum is not,
and must never be read as, the total (AC14).

Background job spans (and any other ``*.finished``/``*.observed`` kind
lacking an already-settled ``payload`` window) are resolved ONLY from
paired events in ``--events`` (a real ``*.launched``/dispatch event and its
real ``*.finished``/receipt counterpart, joined by explicit identity
fields) -- never from an immediate transcript ``tool_result`` row. A
transcript row is used only to build request/token statistics, never to
close a span. When no real receipt/paired-start event exists, the span is
recorded as unresolved (span real = null) instead of being fabricated from
whichever event happens to come next (spec R3, R7, AC22).
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict


# ---------------------------------------------------------------------------
# Schema contracts: the fields this module reads from each JSON Lines source.
# These TypedDicts pin the duck-typed schema so a parity test can detect drift
# against the authoritative WorkflowEvent Pydantic model (FEAT-596).
# ---------------------------------------------------------------------------


class ProfileEventRecord(TypedDict, total=False):
    """Fields this module reads from ``--events`` JSON Lines records.

    Structurally compatible with ``optimization_models.WorkflowEvent``; the
    parity is machine-verified by ``test_event_schema_parity_with_workflow_event``.
    """

    kind: str
    execution_id: str
    task_id: Optional[str]
    attempt_uid: Optional[str]
    job_id: Optional[str]
    timestamp: str
    source: str
    payload: dict[str, Any]


class ProfileTranscriptRow(TypedDict, total=False):
    """Fields this module reads from ``--transcript`` JSON Lines records.

    Transcript rows are host-specific (not an sdd_coder contract), so there
    is no upstream Pydantic model to validate against. This TypedDict exists
    to document the expected shape and prevent silent field-name typos.
    """

    role: str
    request_id: Optional[str]
    message_id: Optional[str]
    timestamp: str
    tool_name: Optional[str]
    tool_input: Optional[dict[str, Any]]
    usage: Optional[dict[str, Any]]
    process_id: Optional[str]
    is_tool_result: Optional[bool]


# ---------------------------------------------------------------------------
# Pairing rules: end-kind -> (start-kind, identity fields that must all be
# present on BOTH events to join them). Joining is always by explicit
# identity, never by "the next event of the right kind" (spec R7).
# ---------------------------------------------------------------------------
_PAIR_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "attempt.finished": ("attempt.dispatched", ("execution_id", "task_id", "attempt_uid")),
    "review.finished": ("review.started", ("execution_id",)),
    "compaction.finished": ("compaction.requested", ("execution_id",)),
    "background.finished": ("background.launched", ("execution_id", "job_id")),
    "fallback.finished": ("fallback.started", ("execution_id",)),
}

_INSPECTION_COMMANDS = frozenset(
    {"cat", "less", "more", "head", "tail", "grep", "rg", "ls", "find", "wc", "pwd", "sed", "awk"}
)
_INSPECTION_GIT_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "blame"})

_TOKEN_FIELDS = ("input_tokens", "cache_read_tokens", "cache_creation_tokens", "output_tokens")

_LONG_SPAN_THRESHOLD_S = 120.0


# ---------------------------------------------------------------------------
# Small, isolated primitives.
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse one JSON object per line.

    An invalid line is skipped with an explicit warning -- never silently
    dropped, never aborts the whole file (R7: degrade explicitly).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"cannot read {path}: {exc}"]

    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            warnings.append(f"{path}:{lineno}: invalid JSON ({exc.msg}), line skipped")
            continue
        if not isinstance(obj, dict):
            warnings.append(f"{path}:{lineno}: expected a JSON object, line skipped")
            continue
        records.append(obj)
    return records, warnings


def _parse_ts(raw: object) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, requiring an explicit UTC/aware offset.

    A naive timestamp cannot be safely correlated across processes (spec
    R3: "timestamps UTC para correlación entre procesos") so it is rejected
    (returns None) rather than silently assumed to be UTC.
    """
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    return ts.astimezone(timezone.utc)


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Merge overlapping/adjacent (start, end) pairs into a disjoint sorted set.

    This is the ONE place "active" time is ever totalled. Because it merges
    real (start, end) pairs directly instead of summing per-category unions
    and subtracting a separately-computed overlap figure, it structurally
    cannot double-subtract shared time between categories -- the bug this
    module exists to fix (spec R7, AC14).
    """
    cleaned = sorted((s, e) for s, e in intervals if e > s)
    merged: list[tuple[datetime, datetime]] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _union_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    return sum((end - start).total_seconds() for start, end in _merge_intervals(intervals))


def _classify_bash_command(command: object) -> str:
    """Classify a Bash command as 'inspection' (recognized read-only op) or 'unknown'.

    Never falls back to a residual "bash-other" bucket treated as pure
    inspection (spec R7): anything the parser does not positively recognize
    stays 'unknown'.
    """
    if not isinstance(command, str) or not command.strip():
        return "unknown"
    try:
        tokens = shlex.split(command.strip())
    except ValueError:
        return "unknown"
    if not tokens:
        return "unknown"
    head = tokens[0].rsplit("/", 1)[-1]
    if head == "git":
        sub = tokens[1] if len(tokens) > 1 else ""
        return "inspection" if sub in _INSPECTION_GIT_SUBCOMMANDS else "unknown"
    return "inspection" if head in _INSPECTION_COMMANDS else "unknown"


def _identity_key(event: dict[str, Any], fields: tuple[str, ...]) -> Optional[tuple[Any, ...]]:
    values = tuple(event.get(field) for field in fields)
    if any(value is None for value in values):
        return None
    return values


def _identity_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_id": event.get("execution_id"),
        "task_id": event.get("task_id"),
        "attempt_uid": event.get("attempt_uid"),
        "job_id": event.get("job_id"),
    }


def _category_for(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    category = payload.get("category") if isinstance(payload, dict) else None
    if isinstance(category, str) and category:
        return category
    kind = str(event.get("kind", "unknown"))
    return kind.split(".", 1)[0]


def _resolve_payload_window(event: dict[str, Any]) -> Optional[tuple[datetime, datetime]]:
    """An already-settled span the event's own payload carries (most authoritative)."""
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    started_raw = payload.get("started_at")
    ended_raw = payload.get("ended_at")
    if started_raw is None or ended_raw is None:
        return None
    start = _parse_ts(started_raw)
    end = _parse_ts(ended_raw)
    if start is None or end is None:
        return None
    return start, end


def _clock_basis(start_event: dict[str, Any], end_event: dict[str, Any]) -> str:
    """Distinguish a same-process monotonic-precise pairing from a wall-clock proxy.

    Duration between two identity-paired events is always ALSO reported on
    UTC wall-clock terms (needed for the global union), but when both
    boundary events agree on ``process_id`` and both carry a numeric
    ``monotonic_s``, that is the more precise number -- and crucially, it
    must never be computed across two DIFFERENT processes (spec R3:
    "duraciones monotónicas solo dentro del mismo proceso").
    """
    start_payload = start_event.get("payload") or {}
    end_payload = end_event.get("payload") or {}
    if not isinstance(start_payload, dict) or not isinstance(end_payload, dict):
        return "identity_paired"
    same_process = (
        start_payload.get("process_id") is not None
        and start_payload.get("process_id") == end_payload.get("process_id")
        and isinstance(start_payload.get("monotonic_s"), (int, float))
        and isinstance(end_payload.get("monotonic_s"), (int, float))
    )
    return "identity_paired+monotonic_same_process" if same_process else "identity_paired"


def _span_public(span: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": span["kind"],
        "category": span["category"],
        "identity": span["identity"],
        "start": span["start"].isoformat(),
        "end": span["end"].isoformat(),
        "duration_s": span["duration_s"],
        "clock_basis": span["clock_basis"],
    }
    if span.get("duration_precise_s") is not None:
        out["duration_precise_s"] = span["duration_precise_s"]
    return out


# ---------------------------------------------------------------------------
# Span resolution.
# ---------------------------------------------------------------------------


def _resolve_spans(events: list[dict[str, Any]]) -> dict[str, list[Any]]:
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        kind = event.get("kind")
        if isinstance(kind, str):
            by_kind[kind].append(event)

    start_pools: dict[tuple[str, tuple[Any, ...]], list[dict[str, Any]]] = defaultdict(list)
    for start_kind, id_fields in _PAIR_RULES.values():
        for event in by_kind.get(start_kind, []):
            key = _identity_key(event, id_fields)
            if key is not None:
                start_pools[(start_kind, key)].append(event)
    for pool in start_pools.values():
        pool.sort(key=lambda e: e.get("timestamp") or "")

    finished_like = [
        event for kind, group in by_kind.items() if kind.endswith((".finished", ".observed")) for event in group
    ]
    finished_like.sort(key=lambda e: e.get("timestamp") or "")

    active_spans: list[dict[str, Any]] = []
    fallback_spans: list[dict[str, Any]] = []
    excluded_spans: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    warnings: list[str] = []

    for end_event in finished_like:
        kind = str(end_event.get("kind", ""))
        category = _category_for(end_event)

        start: Optional[datetime] = None
        end: Optional[datetime] = None
        clock_basis = "payload_window"
        duration_precise_s: Optional[float] = None

        window = _resolve_payload_window(end_event)
        if window is not None:
            start, end = window
        elif kind in _PAIR_RULES:
            start_kind, id_fields = _PAIR_RULES[kind]
            key = _identity_key(end_event, id_fields)
            end_ts = _parse_ts(end_event.get("timestamp"))
            if key is not None and end_ts is not None:
                candidate: Optional[dict[str, Any]] = None
                for start_event in start_pools.get((start_kind, key), []):
                    if start_event.get("_consumed"):
                        continue
                    start_ts = _parse_ts(start_event.get("timestamp"))
                    if start_ts is None or start_ts > end_ts:
                        continue
                    candidate = start_event  # closest not-yet-consumed preceding start, by identity
                if candidate is not None:
                    candidate["_consumed"] = True
                    start = _parse_ts(candidate.get("timestamp"))
                    end = end_ts
                    clock_basis = _clock_basis(candidate, end_event)
                    if clock_basis == "identity_paired+monotonic_same_process":
                        start_mono = (candidate.get("payload") or {}).get("monotonic_s")
                        end_mono = (end_event.get("payload") or {}).get("monotonic_s")
                        duration_precise_s = float(end_mono) - float(start_mono)

        if start is None or end is None:
            unresolved.append(
                {
                    "kind": kind,
                    "category": category,
                    "identity": _identity_snapshot(end_event),
                    "reason": "no_payload_window_and_no_unconsumed_start_event",
                }
            )
            continue
        if end < start:
            warnings.append(f"reversed window for kind={kind} event_id={end_event.get('event_id')}, span skipped")
            continue

        record: dict[str, Any] = {
            "kind": kind,
            "category": category,
            "identity": _identity_snapshot(end_event),
            "start": start,
            "end": end,
            "duration_s": (end - start).total_seconds(),
            "clock_basis": clock_basis,
            "duration_precise_s": duration_precise_s,
        }

        payload = end_event.get("payload") or {}
        if isinstance(payload, dict) and payload.get("baseline_excluded"):
            excluded_spans.append({**_span_public(record), "defect_id": payload.get("defect_id")})
        elif category in ("fallback", "fallback_self_impl"):
            fallback_spans.append(record)
        else:
            active_spans.append(record)

    return {
        "active_spans": active_spans,
        "fallback_spans": fallback_spans,
        "excluded_spans": excluded_spans,
        "unresolved_spans": unresolved,
        "warnings": warnings,
    }


def _build_attempts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consolidate per-(execution_id, task_id, attempt_uid) identity.

    Every join below is keyed by explicit identity fields carried on each
    event -- never by "whichever event comes next" -- so an unrelated later
    merge for a different attempt_uid can never attach to, shorten or
    misattribute this attempt (spec R7).
    """
    by_identity: dict[tuple[Any, Any, Any], dict[str, Any]] = {}

    def _get(execution_id: Any, task_id: Any, attempt_uid: Any) -> dict[str, Any]:
        key = (execution_id, task_id, attempt_uid)
        if key not in by_identity:
            by_identity[key] = {
                "execution_id": execution_id,
                "task_id": task_id,
                "attempt_uid": attempt_uid,
                "dispatched_at": None,
                "finished_at": None,
                "observed_at": None,
                "merged_at": None,
                "accepted_at": None,
            }
        return by_identity[key]

    _ATTEMPT_FIELD = {
        "attempt.dispatched": "dispatched_at",
        "attempt.finished": "finished_at",
        "delivery.observed": "observed_at",
    }
    for event in events:
        kind = event.get("kind")
        execution_id, task_id, attempt_uid = event.get("execution_id"), event.get("task_id"), event.get("attempt_uid")
        if kind in _ATTEMPT_FIELD and execution_id and task_id and attempt_uid:
            record = _get(execution_id, task_id, attempt_uid)
            record[_ATTEMPT_FIELD[kind]] = event.get("timestamp")

    # merge.finished/task.accepted only require task_id (spec R3 minimal
    # identity table): attach to every attempt sharing that task_id, further
    # narrowed to an EXACT attempt_uid match when the event carries one --
    # never to whichever attempt happened to finish most recently.
    for event in events:
        kind = event.get("kind")
        if kind not in ("merge.finished", "task.accepted"):
            continue
        task_id = event.get("task_id")
        if not task_id:
            continue
        attempt_uid = event.get("attempt_uid")
        field = "merged_at" if kind == "merge.finished" else "accepted_at"
        for key, record in by_identity.items():
            if key[1] != task_id:
                continue
            if attempt_uid is not None and key[2] != attempt_uid:
                continue
            record[field] = event.get("timestamp")

    return [by_identity[key] for key in sorted(by_identity, key=lambda k: tuple(str(part) for part in k))]


# ---------------------------------------------------------------------------
# Requests (transcript-derived), kept explicitly separate from raw rows.
# ---------------------------------------------------------------------------


def _first_category(members: list[dict[str, Any]]) -> str:
    for row in members:
        tool_name = row.get("tool_name")
        if tool_name == "Bash":
            tool_input = row.get("tool_input")
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
            return _classify_bash_command(command)
        if isinstance(tool_name, str) and tool_name:
            return tool_name.lower()
    return "text"


def _combine_usage(members: list[dict[str, Any]]) -> dict[str, Optional[int]]:
    """Resolve one settled usage reading per request from streamed rows.

    Never sums token counts ACROSS the streamed delta rows of the SAME
    request (that would double count): usage is typically reported once,
    already-summed, on the row that settles it. Scans from the last row
    backwards for the first row that reports each field.
    """
    result: dict[str, Optional[int]] = dict.fromkeys(_TOKEN_FIELDS, None)
    for row in reversed(members):
        usage = row.get("usage")
        if not isinstance(usage, dict):
            continue
        for field in _TOKEN_FIELDS:
            if result[field] is None and isinstance(usage.get(field), int):
                result[field] = usage[field]
        if all(result[field] is not None for field in _TOKEN_FIELDS):
            break
    return result


def _build_requests(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct requests (unique identity) from raw transcript rows.

    Streamed partial rows that share one ``request_id`` (falling back to
    ``message_id``) collapse into ONE request -- ``count`` is deliberately
    not the same number as ``assistant_rows_total`` (spec AC14: "separan
    requests de mensajes").
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    assistant_rows_total = 0
    for row in rows:
        if row.get("role") == "assistant":
            assistant_rows_total += 1
        key = row.get("request_id") or row.get("message_id")
        if key is None:
            continue
        groups[str(key)].append(row)

    by_category: Counter[str] = Counter()
    long_requests: list[dict[str, Any]] = []
    cross_process_count = 0
    token_sums: dict[str, int] = dict.fromkeys(_TOKEN_FIELDS, 0)
    token_known_counts: dict[str, int] = dict.fromkeys(_TOKEN_FIELDS, 0)
    context_known = 0
    context_unknown = 0

    for request_id, members in groups.items():
        members_sorted = sorted(members, key=lambda r: r.get("timestamp") or "")
        category = _first_category(members_sorted)
        by_category[category] += 1

        timestamps = [ts for ts in (_parse_ts(row.get("timestamp")) for row in members_sorted) if ts is not None]
        process_ids = {row.get("process_id") for row in members_sorted if row.get("process_id") is not None}
        duration_s: Optional[float] = None
        if len(timestamps) >= 2:
            duration_s = (max(timestamps) - min(timestamps)).total_seconds()
        if len(process_ids) > 1:
            cross_process_count += 1
        if duration_s is not None and duration_s >= _LONG_SPAN_THRESHOLD_S:
            long_requests.append({"request_id": request_id, "category": category, "duration_s": duration_s})

        usage = _combine_usage(members_sorted)
        for field in _TOKEN_FIELDS:
            value = usage[field]
            if value is not None:
                token_sums[field] += value
                token_known_counts[field] += 1
        if all(usage[field] is not None for field in ("input_tokens", "cache_read_tokens", "cache_creation_tokens")):
            context_known += 1
        else:
            context_unknown += 1

    tokens: dict[str, Any] = {
        f"{field}_sum": (token_sums[field] if token_known_counts[field] else None) for field in _TOKEN_FIELDS
    }
    tokens["context_tokens_known_requests"] = context_known
    tokens["context_tokens_unknown_requests"] = context_unknown

    return {
        "count": len(groups),
        "assistant_rows_total": assistant_rows_total,
        "by_category": dict(by_category),
        "long_requests": long_requests,
        "clock_cross_process_count": cross_process_count,
        "tokens": tokens,
    }


def _wall_bounds(
    events: list[dict[str, Any]], transcript_rows: list[dict[str, Any]]
) -> tuple[Optional[datetime], Optional[datetime]]:
    stamps: list[datetime] = []
    for record in (*events, *transcript_rows):
        ts = _parse_ts(record.get("timestamp"))
        if ts is not None:
            stamps.append(ts)
    if not stamps:
        return None, None
    return min(stamps), max(stamps)


# ---------------------------------------------------------------------------
# Report assembly and CLI.
# ---------------------------------------------------------------------------


def build_report(
    events: list[dict[str, Any]],
    transcript_rows: list[dict[str, Any]],
    *,
    events_path: str,
    transcript_path: Optional[str],
) -> dict[str, Any]:
    """Build the versioned aggregate report from already-parsed records."""
    resolved = _resolve_spans(events)
    requests = _build_requests(transcript_rows)
    attempts = _build_attempts(events)
    wall_start, wall_end = _wall_bounds(events, transcript_rows)
    wall_span_s = (wall_end - wall_start).total_seconds() if wall_start and wall_end else None

    active_spans = resolved["active_spans"]
    union_s = _union_seconds([(span["start"], span["end"]) for span in active_spans])

    by_category: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for span in active_spans:
        by_category[span["category"]].append((span["start"], span["end"]))
    category_buckets_s = {category: _union_seconds(intervals) for category, intervals in by_category.items()}

    fallback_spans = resolved["fallback_spans"]
    fallback_union_s = _union_seconds([(span["start"], span["end"]) for span in fallback_spans])

    residual_s = max(0.0, wall_span_s - union_s) if wall_span_s is not None else None

    long_spans = [
        {**_span_public(span), "bucket": "active"}
        for span in active_spans
        if span["duration_s"] >= _LONG_SPAN_THRESHOLD_S
    ]
    long_spans += [
        {**_span_public(span), "bucket": "fallback"}
        for span in fallback_spans
        if span["duration_s"] >= _LONG_SPAN_THRESHOLD_S
    ]

    return {
        "schema_version": 1,
        "sources": {"events_path": events_path, "transcript_path": transcript_path},
        "wall_clock": {
            "start": wall_start.isoformat() if wall_start else None,
            "end": wall_end.isoformat() if wall_end else None,
            "span_s": wall_span_s,
        },
        "active": {
            "union_s": union_s,
            "category_buckets_s": category_buckets_s,
            "residual_s": residual_s,
            "spans": [_span_public(span) for span in active_spans],
            "long_spans": long_spans,
            "unresolved_spans": resolved["unresolved_spans"],
        },
        "fallback_self_impl": {
            "union_s": fallback_union_s,
            "spans": [_span_public(span) for span in fallback_spans],
        },
        "baseline": {"excluded_spans": resolved["excluded_spans"]},
        "attempts": attempts,
        "requests": requests,
        "warnings": resolved["warnings"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconstruct requests/spans by identity from explicit sdd-coder event/transcript files."
    )
    parser.add_argument("--events", required=True, type=Path, help="Explicit path to an events JSONL file.")
    parser.add_argument("--transcript", type=Path, default=None, help="Explicit path to a transcript JSONL file.")
    parser.add_argument("--output", required=True, type=Path, help="Explicit path to write the aggregate JSON report.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the output JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Read explicit event/transcript paths and emit versioned aggregate JSON.

    Returns 0 on success, 2 on a usage error (missing/unparsable arguments
    or an unreadable ``--events`` path).
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit:
        return 2

    if not args.events.exists():
        print(f"profile_execution: --events path does not exist: {args.events}", file=sys.stderr)  # noqa: T201
        return 2

    events, events_warnings = _read_jsonl(args.events)
    transcript_rows: list[dict[str, Any]] = []
    warnings: list[str] = list(events_warnings)
    transcript_path: Optional[str] = None
    if args.transcript is not None:
        transcript_path = str(args.transcript)
        if args.transcript.exists():
            transcript_rows, transcript_warnings = _read_jsonl(args.transcript)
            warnings.extend(transcript_warnings)
        else:
            warnings.append(f"--transcript path does not exist, skipped: {args.transcript}")

    report = build_report(
        events,
        transcript_rows,
        events_path=str(args.events),
        transcript_path=transcript_path,
    )
    report["warnings"] = warnings + report["warnings"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2 if args.pretty else None, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
