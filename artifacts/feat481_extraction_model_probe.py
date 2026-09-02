#!/usr/bin/env python
"""FEAT-481 — cross-model probe for the MeetingPageExtraction structured call.

Runs the *real* meeting-page extraction (same schema, system prompt, and prompt
builder the agent uses) against a list of LLMs and prints a pass/fail table, so we
can see which models can actually satisfy `MeetingPageExtraction` and which
degenerate into repetition/truncation (see FEAT-481-cheap-tier-extraction-bug.md).

It does NOT touch Fireflies or the vault — you feed it a meeting (a raw Fireflies
bundle dir, or the built-in synthetic sample), and it calls
`client.invoke(prompt, output_type=MeetingPageExtraction)` per model.

Usage
-----
    source .venv/bin/activate
    python artifacts/feat481_extraction_model_probe.py \
        --models google:gemini-2.5-flash,google:gemini-2.5-flash-lite,google:gemini-2.5-pro,anthropic:claude-sonnet-4-5,openai:gpt-4.1-mini \
        [--meeting-dir /path/to/Raw/Processed/.../<fireflies_id>] \
        [--transcript] [--max-tokens 4096]

`--meeting-dir` expects a folder with `summary.md` (required) and optionally
`transcript.md` / `metadata.json`. With no `--meeting-dir`, a built-in synthetic
meeting is used (good for a quick relative comparison; for a *faithful* repro of
the truncation, point it at the real bundle that triggered it).

Each provider must have its credentials configured (e.g. GOOGLE_API_KEY,
ANTHROPIC_API_KEY, OPENAI_API_KEY) or that row reports an auth ERROR.

Verdicts
--------
    OK           result.output is a MeetingPageExtraction (model satisfied the schema)
    STR-LEAK     result.output came back a raw str (unparsed; provider has no recovery)
    INVOKE-ERROR invoke() raised (e.g. Google's guard after reformat recovery also failed)
    ERROR        other failure (often missing credentials / unknown model)
"""
from __future__ import annotations

import uvloop

uvloop.install()

import argparse
import asyncio
import json
from pathlib import Path

_SYNTHETIC_SUMMARY = (
    "The team met to review FieldSync development ahead of the launch. Topics: "
    "field testing status, form builder access issues, phased UX improvements, "
    "training material coordination, and integration testing with the HR system. "
    "Decisions were taken on prioritising fixes; several action items and open "
    "questions were raised about ownership and support readiness."
)


def _load_meeting(meeting_dir: str | None) -> dict:
    if not meeting_dir:
        return {
            "fireflies_id": "synthetic-0001",
            "title": "FieldSync Weekly Sync (synthetic)",
            "meeting_date": "2026-09-01",
            "summary_text": _SYNTHETIC_SUMMARY,
            "transcript_text": None,
        }
    d = Path(meeting_dir)
    summary = (d / "summary.md")
    transcript = (d / "transcript.md")
    meta = (d / "metadata.json")
    md = json.loads(meta.read_text()) if meta.exists() else {}
    return {
        "fireflies_id": md.get("fireflies_id") or md.get("id") or d.name,
        "title": md.get("title") or d.name,
        "meeting_date": str(md.get("meeting_date") or md.get("date") or "1970-01-01"),
        "summary_text": summary.read_text(encoding="utf-8") if summary.exists() else "",
        "transcript_text": transcript.read_text(encoding="utf-8") if transcript.exists() else None,
    }


def _out_tokens(usage) -> str:
    for attr in ("completion_tokens", "candidates_token_count", "output_tokens", "total_tokens"):
        v = getattr(usage, attr, None)
        if v:
            return f"{attr}={v}"
    return "n/a"


async def _probe_one(model: str, prompt: str, system_prompt: str, max_tokens: int | None) -> dict:
    from parrot.clients.factory import LLMFactory
    from parrot.exceptions import InvokeError
    from parrot.flows.wiki_ingest.nodes.meeting_page import MeetingPageExtraction

    row = {"model": model, "verdict": "", "detail": ""}
    try:
        client = LLMFactory.create(model)
    except Exception as exc:  # unknown model / provider
        row["verdict"] = "ERROR"
        row["detail"] = f"create: {type(exc).__name__}: {exc}"
        return row
    try:
        async with client:
            result = await client.invoke(
                prompt,
                output_type=MeetingPageExtraction,
                system_prompt=system_prompt,
                temperature=0.0,
                # None => let the client resolve its own budget
                # (_resolve_invoke_max_tokens), which is what production does.
                max_tokens=max_tokens,
            )
        out = result.output
        if isinstance(out, MeetingPageExtraction):
            row["verdict"] = "OK"
            row["detail"] = _out_tokens(getattr(result, "usage", None))
        elif isinstance(out, str):
            row["verdict"] = "STR-LEAK"
            row["detail"] = f"raw_str chars={len(out)}"
        else:
            row["verdict"] = "OTHER"
            row["detail"] = f"output_type={type(out).__name__}"
    except InvokeError as exc:
        row["verdict"] = "INVOKE-ERROR"
        row["detail"] = str(exc)[:200]
    except Exception as exc:
        row["verdict"] = "ERROR"
        row["detail"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return row


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="comma-separated provider:model list")
    ap.add_argument("--meeting-dir", default=None)
    ap.add_argument("--transcript", action="store_true", help="include transcript in the prompt")
    ap.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="max_output_tokens override; omit to use each client's own "
             "_invoke_max_tokens default (8192, Google 16384, Groq 4096)",
    )
    args = ap.parse_args()

    from parrot.flows.wiki_ingest.nodes.fetch_gate import GatedMeeting
    from parrot.flows.wiki_ingest.nodes.meeting_page import _SYSTEM_PROMPT, _build_prompt

    m = _load_meeting(args.meeting_dir)
    meeting = GatedMeeting(
        fireflies_id=m["fireflies_id"],
        source_id=f"fireflies:{m['fireflies_id']}",
        title=m["title"],
        meeting_date=m["meeting_date"],
        outcome="fetch",
        summary_text=m["summary_text"],
        transcript_text=m["transcript_text"],
    )
    prompt = _build_prompt(meeting, transcript_read=args.transcript and bool(m["transcript_text"]))
    print(f"meeting='{meeting.title}' summary_chars={len(m['summary_text'] or '')} "
          f"transcript={'yes' if args.transcript and m['transcript_text'] else 'no'} "
          f"max_tokens={args.max_tokens if args.max_tokens else 'client default'}\n")

    models = [s.strip() for s in args.models.split(",") if s.strip()]
    rows = []
    for model in models:
        row = await _probe_one(model, prompt, _SYSTEM_PROMPT, args.max_tokens)
        rows.append(row)
        print(f"  {row['verdict']:<12} {model:<34} {row['detail']}")

    print("\n==== SUMMARY ====")
    width = max((len(r["model"]) for r in rows), default=10)
    for r in rows:
        print(f"  {r['model']:<{width}}  {r['verdict']:<12}  {r['detail']}")
    print("\nJSON:", json.dumps(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
