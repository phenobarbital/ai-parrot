#!/usr/bin/env python3
"""Attribute Claude Code token spend to SDD features, from the local transcripts.

Claude Code writes one JSONL transcript per session under
``~/.claude/projects/<slugified-cwd>/`` (subagent transcripts live in
``<session-id>/subagents/``). Every assistant record carries a ``usage`` block,
and each session carries a ``cost-state`` record with Claude Code's own cost
accounting plus ``pr-link`` records. This script rolls those up per SDD feature.

Two facts make or break the numbers:

1. **One API response is written as several transcript lines** (one per content
   block), each repeating the *same* ``usage`` object. Counting lines instead of
   ``message.id`` inflates every total ~5x.
2. **Cache reads dominate.** ~99% of tokens and ~70% of cost are
   ``cache_read_input_tokens`` — i.e. the context re-read on every turn. Raw
   "tokens per feature" is therefore a context-size metric, not an effort one;
   compare ``$/turn`` and ``ctx/turn``, not token totals.

Feature attribution uses work signals, strongest wins, most recent stays in force:

    tier 3  worktree dir / branch ``feat-FEAT-<n>``  — the agent is working there
    tier 2  ``TASK-<n>`` resolved via ``sdd/tasks/index/*.json``
    tier 1  ``FEAT-<n>`` typed by the human (prompt or slash-command args)
    tier 0  ``FEAT-<n>`` anywhere (tool output, file contents) — fallback only

Tiers 3+2 cover ~99.8% of tokens, which is why a plain "last FEAT-id mentioned"
heuristic is not used: a session that reads the ``sdd/`` tree mentions 30-70 ids.

Not covered: tokens burned by the external sdd-coder seats (nova / codex /
google). Those live on other providers and are recorded, when the durable usage
sink is enabled, in ``artifacts/logs/sdd-coder-usage/<FEAT-ID>.jsonl`` — see
``scripts/analyze_sdd_coder_usage.py``.

Usage:
    python scripts/sdd/token_audit.py scan            # build the row cache
    python scripts/sdd/token_audit.py features        # spend per feature
    python scripts/sdd/token_audit.py trend           # per-turn economics by week
    python scripts/sdd/token_audit.py feature FEAT-584
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Iterator

PROJECTS = Path.home() / ".claude" / "projects"
REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "artifacts" / "logs" / "token-audit"

#: $/MTok: (fresh input, output, cache write 5m, cache write 1h, cache read).
#: Verified against the ``cost-state`` records Claude Code writes itself.
PRICES: dict[str, tuple[float, float, float, float, float]] = {
    "claude-opus-5": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 4.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 6.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 2.00, 0.10),
    "claude-fable-5-1": (10.00, 50.00, 12.50, 20.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 12.50, 20.00, 1.00),
}

WORKTREE_RE = re.compile(r"(?:feat-|feat/)FEAT-(\d{2,4})")
FEAT_RE = re.compile(r"\bFEAT-(\d{2,4})\b")
TASK_RE = re.compile(r"\bTASK-(\d{2,5})\b")
COMMAND_RE = re.compile(r"<command-name>/([a-z0-9\-]+)</command-name>")
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def price(model: str, row: dict[str, int]) -> float:
    """Return the USD cost of one response, or 0.0 for an unpriced model."""
    for prefix, (inp, out, write5m, write1h, read) in PRICES.items():
        if model.startswith(prefix):
            return (
                row["input"] * inp
                + row["output"] * out
                + row["cw5"] * write5m
                + row["cw1"] * write1h
                + row["cr"] * read
            ) / 1e6
    return 0.0


def task_to_feature() -> dict[str, str]:
    """Map every ``TASK-<n>`` to its feature id via the per-spec task indexes."""
    mapping: dict[str, str] = {}
    for path in (REPO / "sdd" / "tasks" / "index").glob("*.json"):
        try:
            index = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        feature_id = index.get("feature_id")
        for task in index.get("tasks") or []:
            task_id = task.get("id")
            if task_id:
                mapping[task_id] = task.get("feature_id") or feature_id
    return mapping


def feature_index() -> dict[str, dict[str, Any]]:
    """Return per-feature metadata (slug, spec, task count) from the indexes."""
    meta: dict[str, dict[str, Any]] = {}
    for path in (REPO / "sdd" / "tasks" / "index").glob("*.json"):
        try:
            index = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        feature_id = index.get("feature_id")
        if feature_id:
            meta[feature_id] = {
                "feature": index.get("feature"),
                "spec": index.get("spec"),
                "type": index.get("type"),
                "ntasks": len(index.get("tasks") or []),
            }
    return meta


def _human_text(record: dict[str, Any]) -> str:
    """Return the text the human actually typed, or '' for anything else."""
    if record.get("type") != "user":
        return ""
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def parse_transcript(
    path: Path,
    session_id: str,
    tasks: dict[str, str],
    agent_file: str | None = None,
    inherit: dict[int, str | None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[int, str | None]]:
    """Parse one transcript into per-response rows plus session metadata."""
    current: dict[int, str | None] = {3: None, 2: None, 1: None, 0: None}
    if inherit:
        current.update({tier: feat for tier, feat in inherit.items() if feat})
    command: str | None = None
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "cost_state": None,
        "prs": set(),
        "commands": [],
        "agent": None,
        "tasks": set(),
        "start": None,
        "end": None,
        "branches": set(),
        "coder_chunks": 0,
        "coder_calls": 0,
    }

    with path.open(errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            kind = record.get("type")
            if kind == "cost-state":
                meta["cost_state"] = record
                continue
            if kind == "pr-link":
                meta["prs"].add(record.get("prNumber"))
                continue
            if kind == "agent-setting":
                meta["agent"] = record.get("agentSetting")
                continue

            raw = json.dumps(record, ensure_ascii=False)
            timestamp = record.get("timestamp")
            if timestamp:
                if meta["start"] is None or timestamp < meta["start"]:
                    meta["start"] = timestamp
                if meta["end"] is None or timestamp > meta["end"]:
                    meta["end"] = timestamp
            if record.get("gitBranch"):
                meta["branches"].add(record["gitBranch"])

            commands = COMMAND_RE.findall(raw)
            meta["commands"].extend(commands)
            if commands:
                command = commands[-1]
            if '"mcp__parrot-sdd-coder__coder_run_chunk"' in raw:
                meta["coder_chunks"] += 1
            if '"mcp__parrot-sdd-coder__' in raw:
                meta["coder_calls"] += 1

            worktrees = WORKTREE_RE.findall(raw)
            if worktrees:
                current[3] = "FEAT-" + worktrees[-1]
            task_ids = [f"TASK-{n}" for n in TASK_RE.findall(raw)]
            meta["tasks"].update(task_ids)
            mapped = [tasks[t] for t in task_ids if t in tasks]
            if mapped:
                current[2] = mapped[-1]
            typed = FEAT_RE.findall(_human_text(record) + " ".join(COMMAND_ARGS_RE.findall(raw)))
            if typed:
                current[1] = "FEAT-" + typed[-1]
            anywhere = FEAT_RE.findall(raw)
            if anywhere:
                current[0] = "FEAT-" + anywhere[-1]

            if kind != "assistant":
                continue
            message = record.get("message") or {}
            usage = message.get("usage") or {}
            if not usage:
                continue
            # One response spans several lines, each repeating this usage block.
            message_id = message.get("id") or record.get("requestId") or record.get("uuid")
            if message_id in seen:
                continue
            seen.add(message_id)

            creation = usage.get("cache_creation") or {}
            row = {
                "ts": timestamp,
                "session": session_id,
                "agent_file": agent_file,
                "model": message.get("model") or "unknown",
                "sidechain": bool(record.get("isSidechain")),
                "cmd": command,
                "feat": current[3] or current[2] or current[1] or current[0],
                "tier": next((t for t in (3, 2, 1, 0) if current[t]), -1),
                "input": usage.get("input_tokens", 0) or 0,
                "output": usage.get("output_tokens", 0) or 0,
                "thinking": (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0) or 0,
                "cw5": creation.get("ephemeral_5m_input_tokens", 0) or 0,
                "cw1": creation.get("ephemeral_1h_input_tokens", 0) or 0,
                "cr": usage.get("cache_read_input_tokens", 0) or 0,
            }
            if not (row["cw5"] or row["cw1"]):
                row["cw5"] = usage.get("cache_creation_input_tokens", 0) or 0
            row["cost"] = price(row["model"], row)
            rows.append(row)

    return rows, meta, current


def project_dirs(match: str) -> list[Path]:
    """Return the Claude Code project directories belonging to this repo."""
    return [d for d in PROJECTS.iterdir() if d.is_dir() and match in d.name]


def scan(match: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse every transcript for the repo, including subagent transcripts."""
    tasks = task_to_feature()
    rows: list[dict[str, Any]] = []
    sessions: dict[str, Any] = {}
    for directory in project_dirs(match):
        for transcript in sorted(directory.glob("*.jsonl")):
            session_id = transcript.stem
            session_rows, meta, current = parse_transcript(transcript, session_id, tasks)
            rows.extend(session_rows)
            subagents = directory / session_id / "subagents"
            meta["n_subagents"] = 0
            if subagents.is_dir():
                for sub in sorted(subagents.glob("*.jsonl")):
                    sub_rows, sub_meta, _ = parse_transcript(
                        sub, session_id, tasks, agent_file=sub.name, inherit=current
                    )
                    rows.extend(sub_rows)
                    meta["n_subagents"] += 1
                    meta["coder_chunks"] += sub_meta["coder_chunks"]
                    meta["coder_calls"] += sub_meta["coder_calls"]
                    meta["tasks"] |= sub_meta["tasks"]
            meta["file"] = str(transcript)
            sessions[session_id] = meta
    return rows, sessions


def save(rows: list[dict[str, Any]], sessions: dict[str, Any]) -> None:
    """Write the row cache so the report commands do not re-parse every run."""
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "rows.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    serializable = {
        sid: {
            **meta,
            "prs": sorted(p for p in meta["prs"] if p),
            "tasks": sorted(meta["tasks"]),
            "branches": sorted(meta["branches"]),
        }
        for sid, meta in sessions.items()
    }
    (CACHE / "sessions.json").write_text(json.dumps(serializable, indent=1))


def load() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the cached rows, or exit telling the caller to scan first."""
    rows_path = CACHE / "rows.jsonl"
    if not rows_path.exists():
        sys.exit("no cache yet - run: python scripts/sdd/token_audit.py scan")
    rows = [json.loads(line) for line in rows_path.open()]
    sessions = json.loads((CACHE / "sessions.json").read_text())
    return rows, sessions


def context_tokens(row: dict[str, Any]) -> int:
    """Return the context carried into one response (everything but output)."""
    return row["cr"] + row["cw5"] + row["cw1"] + row["input"]


def week_of(timestamp: str) -> str:
    """Return the ISO date of the Monday of that timestamp's week."""
    day = dt.date.fromisoformat(timestamp[:10])
    return (day - dt.timedelta(days=day.weekday())).isoformat()


def by_feature(rows: list[dict[str, Any]]) -> dict[str, collections.Counter]:
    """Roll responses up per feature."""
    per: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for row in rows:
        if not row["feat"]:
            continue
        counter = per[row["feat"]]
        counter["turns"] += 1
        counter["ctx"] += context_tokens(row)
        counter["out"] += row["output"]
        counter["cr"] += row["cr"]
        counter["usd_micro"] += round(row["cost"] * 1e6)
    return per


def cmd_features(rows: list[dict[str, Any]], sessions: dict[str, Any], args: argparse.Namespace) -> None:
    per = by_feature(rows)
    meta = feature_index()
    first: dict[str, str] = {}
    for row in rows:
        if row["feat"] and row["ts"]:
            first[row["feat"]] = min(first.get(row["feat"], row["ts"]), row["ts"])
    ranked = sorted(per.items(), key=lambda kv: -kv[1]["usd_micro"])[: args.limit]
    print(f"{'feature':<10}{'start':<12}{'turns':>7}{'ctx/turn':>10}{'$/turn':>8}{'total $':>9}{'tasks':>6}  name")
    for feature, counter in ranked:
        turns = counter["turns"]
        usd = counter["usd_micro"] / 1e6
        info = meta.get(feature, {})
        print(
            f"{feature:<10}{(first.get(feature) or '')[:10]:<12}{turns:>7,}"
            f"{counter['ctx'] // turns:>10,}{usd / turns:>8,.3f}{usd:>9,.2f}"
            f"{str(info.get('ntasks') or '-'):>6}  {info.get('feature') or ''}"
        )


def cmd_trend(rows: list[dict[str, Any]], sessions: dict[str, Any], args: argparse.Namespace) -> None:
    weeks: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for row in rows:
        if not row["ts"]:
            continue
        counter = weeks[week_of(row["ts"])]
        counter["turns"] += 1
        counter["ctx"] += context_tokens(row)
        counter["out"] += row["output"]
        counter["usd_micro"] += round(row["cost"] * 1e6)
    print(f"{'week':<12}{'turns':>9}{'ctx/turn':>11}{'out/turn':>10}{'$/turn':>9}{'week $':>10}")
    for week in sorted(weeks):
        counter = weeks[week]
        turns = max(counter["turns"], 1)
        usd = counter["usd_micro"] / 1e6
        print(
            f"{week:<12}{counter['turns']:>9,}{counter['ctx'] // turns:>11,}"
            f"{counter['out'] // turns:>10,}{usd / turns:>9,.3f}{usd:>10,.0f}"
        )


def cmd_feature(rows: list[dict[str, Any]], sessions: dict[str, Any], args: argparse.Namespace) -> None:
    feature = args.feature.upper()
    selected = [r for r in rows if r["feat"] == feature]
    if not selected:
        sys.exit(f"no responses attributed to {feature}")
    turns = len(selected)
    usd = sum(r["cost"] for r in selected)
    ctx = sum(context_tokens(r) for r in selected)
    out = sum(r["output"] for r in selected)
    session_ids = {r["session"] for r in selected}
    print(f"{feature}  {turns:,} responses across {len(session_ids)} sessions")
    print(f"  context read   {ctx:,} tok  ({ctx // turns:,}/turn)")
    print(f"  output         {out:,} tok  ({out // turns:,}/turn)")
    print(f"  modelled cost  ${usd:,.2f}  (${usd / turns:.3f}/turn)")
    models: dict[str, float] = collections.defaultdict(float)
    for row in selected:
        models[row["model"]] += row["cost"]
    for model, cost in sorted(models.items(), key=lambda kv: -kv[1]):
        print(f"    {model:<28} ${cost:>8,.2f}")
    chunks = sum(sessions.get(s, {}).get("coder_chunks", 0) for s in session_ids)
    prs = sorted({p for s in session_ids for p in sessions.get(s, {}).get("prs", [])})
    print(f"  external coder chunks dispatched: {chunks}   PRs touched: {prs}")
    reported = sum(
        (sessions.get(s, {}).get("cost_state") or {}).get("totalCostUSD", 0.0) for s in session_ids
    )
    print(f"  Claude Code cost-state for those whole sessions: ${reported:,.2f}")


def cmd_scan(rows: list[dict[str, Any]], sessions: dict[str, Any], args: argparse.Namespace) -> None:
    raise NotImplementedError  # handled in main()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--match", default="ai-parrot", help="substring of the Claude Code project dir names")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="parse every transcript and cache the rows")
    features = sub.add_parser("features", help="spend per feature")
    features.add_argument("--limit", type=int, default=30)
    sub.add_parser("trend", help="per-turn economics by week")
    one = sub.add_parser("feature", help="detail for one feature")
    one.add_argument("feature")
    args = parser.parse_args()

    if args.command == "scan":
        rows, sessions = scan(args.match)
        save(rows, sessions)
        print(f"{len(rows):,} responses from {len(sessions)} sessions -> {CACHE}")
        return

    rows, sessions = load()
    {"features": cmd_features, "trend": cmd_trend, "feature": cmd_feature}[args.command](rows, sessions, args)


if __name__ == "__main__":
    main()
