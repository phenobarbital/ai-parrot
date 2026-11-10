"""Host evaluation for Bookstore agentic retrieval; persist metrics, never source text."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

from parrot.knowledge.bookstore._llm import resolve_adapter
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

logger = logging.getLogger(__name__)

SEED = 858
QUESTIONS_PER_BOOK = 5
MAX_GENERATED = 35
MIN_SEGMENT_TOKENS = 40
MAX_PROBES_PER_BOOK = 60
TOTAL_ROWS = 140
BASELINE_ROWS = 56
HANDWRITTEN_ROWS = 21
MIN_COMPLETED_TOTAL = 112
MIN_COMPLETED_HANDWRITTEN = 17
FAILED_STOPS = frozenset({"timeout", "provider_error"})

# (name, budget_chars, max_reads); tool calls (20) and timeout (120 s) are fixed.
BASELINE = ("baseline", 40000, 12)
SWEEPS: tuple[tuple[str, int, int], ...] = (
    ("c20000_r12", 20000, 12),
    ("c60000_r12", 60000, 12),
    ("c40000_r8", 40000, 8),
    ("c40000_r16", 40000, 16),
)
MAX_TOOL_CALLS = 20
TIMEOUT_S = 120.0


class EvalQuestion(BaseModel):
    """Question provenance and exactly one pinned gold address."""

    question_id: str
    book_id: str
    question: str
    provenance: Literal["handwritten", "generated"]
    doc_id: str
    revision: str
    generation: int
    gold_kind: Literal["seq", "node", "page"]
    gold_seq: Optional[int] = None
    gold_node_id: Optional[str] = None
    gold_page: Optional[int] = None

    @field_validator("question_id", "book_id", "question", "doc_id", "revision")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("identifier and question fields must be nonempty")
        return value

    @model_validator(mode="after")
    def _one_gold(self) -> "EvalQuestion":
        golds = {"seq": self.gold_seq, "node": self.gold_node_id, "page": self.gold_page}
        present = [kind for kind, value in golds.items() if value is not None]
        if present != [self.gold_kind]:
            raise ValueError("exactly one gold address matching gold_kind is required")
        if self.gold_kind == "node" and not self.gold_node_id.strip():  # type: ignore[union-attr]
            raise ValueError("gold_node_id must be nonempty")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        return self


class EvalSettings(BaseModel):
    """Validated corpus paths and experiment settings."""

    library: Path
    questions: Path
    llm: str = "google:gemini-3.5-flash-lite"
    concurrency: int = 1
    out_dir: Path = Path("artifacts/logs/bookstore_agentic_eval")

    @field_validator("concurrency")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("concurrency must be positive")
        return value

    @field_validator("llm")
    @classmethod
    def _llm_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("llm must be nonempty")
        return value


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_bookstore(settings: EvalSettings) -> Bookstore:
    """Build one independent Bookstore (own adapter/client) for a worker."""
    adapter, light, _client = resolve_adapter(settings.llm)
    return Bookstore(
        [LibraryLocation(scope="project", root=settings.library)], adapter=adapter, lightweight_model=light
    )


def error_category(exc: BaseException) -> str:
    """Map an exception to a safe category; the message is never used."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(exc, BookstoreError):
        return "bookstore_error"
    if isinstance(exc, ValueError):
        return "value_error"
    if isinstance(exc, KeyError):
        return "key_error"
    return "provider_error"


def load_questions(path: Path) -> tuple[list[EvalQuestion], str]:
    """Load and validate a fixture; return the questions and the fixture file hash."""
    raw = path.read_bytes()
    data = json.loads(raw)
    items = data["questions"] if isinstance(data, dict) else data
    return [EvalQuestion.model_validate(item) for item in items], _sha256(raw)


def build_plan(questions: list[EvalQuestion]) -> list[dict[str, Any]]:
    """Return the frozen plan: baseline for every question, then four sweeps for handwritten ones."""
    if len(questions) != BASELINE_ROWS:
        raise BookstoreError(f"fixture must hold exactly {BASELINE_ROWS} questions, found {len(questions)}")
    handwritten = [q for q in questions if q.provenance == "handwritten"]
    if len(handwritten) != HANDWRITTEN_ROWS:
        raise BookstoreError(f"fixture must hold exactly {HANDWRITTEN_ROWS} handwritten questions")
    if len({q.question_id for q in questions}) != len(questions):
        raise BookstoreError("question ids must be unique")
    plan: list[dict[str, Any]] = []
    name, chars, reads = BASELINE
    for q in questions:
        plan.append({"question": q, "setting": name, "budget_chars": chars, "max_reads": reads})
    for name, chars, reads in SWEEPS:
        for q in handwritten:
            plan.append({"question": q, "setting": name, "budget_chars": chars, "max_reads": reads})
    if len(plan) != TOTAL_ROWS:  # pragma: no cover - arithmetic invariant
        raise BookstoreError("plan size drifted from the frozen design")
    return plan


def _owned_ranges(node: dict[str, Any]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for owned in node.get("owned") or []:
        if isinstance(owned, list) and len(owned) == 2:
            out.append((int(owned[0]), int(owned[1])))
    return out


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes or []:
        yield node
        yield from _walk(node.get("nodes") or [])


def tree_snapshot(tree: dict[str, Any]) -> dict[str, Any]:
    """Return text-free tree shape metrics, per-node owned ranges and a snapshot hash."""
    nodes = list(_walk(tree.get("structure") or []))
    owned = {n["node_id"]: _owned_ranges(n) for n in nodes if isinstance(n.get("node_id"), str)}
    leaves = [n for n in nodes if not (n.get("nodes") or [])]
    tokens = [n.get("tokens", n.get("token_count")) for n in leaves]
    tokens = [t for t in tokens if isinstance(t, int)]
    skeleton = [{"id": nid, "owned": rng} for nid, rng in sorted(owned.items())]
    return {
        "generation": (tree.get("generation") or {}).get("id"),
        "node_count": len(nodes),
        "owned_node_count": sum(1 for rng in owned.values() if rng),
        "largest_leaf_tokens": max(tokens) if tokens else None,
        "snapshot_sha256": _sha256(json.dumps(skeleton, sort_keys=True).encode()),
        "owned": owned,
    }


async def _book_context(bookstore: Bookstore, book_id: str) -> dict[str, Any]:
    """Resolve the live doc/revision/generation/tree snapshot of one book."""
    card, loc = bookstore.resolve_book(book_id)
    toolkit = bookstore._toolkit(loc.scope)  # noqa: SLF001 - snapshot read, no public equivalent
    documents = await toolkit.list_documents(card.tree_name)
    if not documents:
        raise BookstoreError("book has no segments")
    tree = await toolkit.get_tree(card.tree_name)
    snap = tree_snapshot(tree)
    return {
        "doc_id": documents[0]["doc_id"],
        "revision": documents[0]["revision"],
        "segments": documents[0].get("segments"),
        "scope": loc.scope,
        "tree_name": card.tree_name,
        **snap,
    }


def is_stale(question: EvalQuestion, ctx: dict[str, Any]) -> bool:
    """Whether the pinned address no longer matches the live book."""
    if question.doc_id != ctx["doc_id"] or question.revision != ctx["revision"]:
        return True
    if question.generation != ctx["generation"]:
        return True
    if question.gold_kind == "node" and not ctx["owned"].get(question.gold_node_id):
        return True
    return False


def gold_hit(question: EvalQuestion, citations: list[dict[str, Any]], ctx: dict[str, Any]) -> bool:
    """Apply the spec's gold-hit rule against validated citations."""
    for cit in citations:
        if cit.get("doc_id") != question.doc_id or cit.get("revision") != question.revision:
            continue
        seq = cit.get("seq")
        if question.gold_kind == "seq" and seq == question.gold_seq:
            return True
        if question.gold_kind == "page" and cit.get("page") == question.gold_page:
            return True
        if question.gold_kind == "node" and isinstance(seq, int):
            if any(lo <= seq < hi for lo, hi in ctx["owned"].get(question.gold_node_id, [])):
                return True
    return False


def _row_base(item: dict[str, Any]) -> dict[str, Any]:
    q: EvalQuestion = item["question"]
    return {
        "question_id": q.question_id,
        "book_id": q.book_id,
        "provenance": q.provenance,
        "setting": item["setting"],
        "budget_chars": item["budget_chars"],
        "max_reads": item["max_reads"],
        "max_tool_calls": MAX_TOOL_CALLS,
        "timeout_s": TIMEOUT_S,
        "status": "skipped",
        "error_category": None,
        "stopped": None,
        "grounded": False,
        "gold_hit": False,
        "kept": 0,
        "rejected": 0,
        "chars_read": 0,
        "tool_calls": 0,
        "usage": {},
        "wall_s": 0.0,
    }


async def _run_row(bookstore: Bookstore, item: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    row = _row_base(item)
    q: EvalQuestion = item["question"]
    started = time.monotonic()
    try:
        bundle = await bookstore.agentic_retrieve(
            q.book_id,
            q.question,
            budget_chars=item["budget_chars"],
            max_reads=item["max_reads"],
            timeout_s=TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 - recorded as a safe category only
        row.update(status="error", error_category=error_category(exc))
        row["wall_s"] = round(time.monotonic() - started, 4)
        return row
    row["wall_s"] = round(time.monotonic() - started, 4)
    citations = [c for c in (bundle.get("citations") or []) if isinstance(c, dict)]
    stopped = bundle.get("stopped")
    usage = bundle.get("usage") or {}
    row.update(
        stopped=stopped,
        grounded=bool(bundle.get("grounded")),
        gold_hit=gold_hit(q, citations, ctx),
        kept=len(citations),
        rejected=len(bundle.get("rejected") or []),
        chars_read=int(bundle.get("chars_read") or 0),
        tool_calls=int(bundle.get("tool_calls") or 0),
        usage={k: v for k, v in usage.items() if isinstance(v, (int, float))},
    )
    if stopped in FAILED_STOPS:
        row.update(status="error", error_category=stopped)
    else:
        row["status"] = "completed"
    return row


# ----------------------------------------------------------------------------
# generation
# ----------------------------------------------------------------------------
def _valid_question(text: Any) -> bool:
    return isinstance(text, str) and 10 <= len(text.strip()) <= 300 and "\n" not in text.strip()


async def _ask_question(adapter: Any, segment_text: str, repair: bool) -> Optional[str]:
    prompt = (
        "Write ONE self-contained question, in the language of the passage, that the passage below answers. "
        "Do not quote the passage. Reply with the question only, on a single line."
    )
    if repair:
        prompt += " Your previous reply was not a single-line question; reply with one short question."
    prompt += f"\n\n<passage>\n{segment_text}\n</passage>"
    reply = await adapter.ask(prompt)
    return reply.strip() if isinstance(reply, str) else None


async def generate_questions(settings: EvalSettings) -> list[EvalQuestion]:
    """Generate questions once from known >=40-token segments without saving source text."""
    if settings.questions.exists():
        raise BookstoreError("refusing to overwrite an existing question fixture")
    bookstore = _make_bookstore(settings)
    if not bookstore.has_llm:
        raise BookstoreError("question generation requires an LLM")
    generated: list[EvalQuestion] = []
    for card in sorted(bookstore.list_books(), key=lambda c: c.book_id):
        if len(generated) >= MAX_GENERATED:
            break
        try:
            ctx = await _book_context(bookstore, card.book_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("skipping book for generation: %s", error_category(exc))
            continue
        total = int(ctx.get("segments") or 0)
        rng = random.Random(f"{SEED}:{card.book_id}")
        order = list(range(total))
        rng.shuffle(order)
        made = 0
        for seq in order[:MAX_PROBES_PER_BOOK]:
            if made >= QUESTIONS_PER_BOOK or len(generated) >= MAX_GENERATED:
                break
            try:
                read = await bookstore.read_segments(card.book_id, start=seq, end=seq + 1, max_chars=4000)
                text = read["segments"][0]["text"]
                # word count is the token proxy: per-segment token counts are not in read results
                if len(text.split()) < MIN_SEGMENT_TOKENS:
                    continue
                question = await _ask_question(bookstore.adapter, text, repair=False)
                if not _valid_question(question):
                    question = await _ask_question(bookstore.adapter, text, repair=True)
                if not _valid_question(question):
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("generation probe failed: %s", error_category(exc))
                continue
            made += 1
            generated.append(
                EvalQuestion(
                    question_id=f"{card.book_id}-g{made}",
                    book_id=card.book_id,
                    question=str(question).strip(),
                    provenance="generated",
                    doc_id=ctx["doc_id"],
                    revision=ctx["revision"],
                    generation=int(ctx["generation"] or 0),
                    gold_kind="seq",
                    gold_seq=seq,
                )
            )
    return generated


# ----------------------------------------------------------------------------
# selection and statistics
# ----------------------------------------------------------------------------
def _median(values: list[float]) -> Optional[float]:
    return statistics.median(values) if values else None


def setting_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and medians for a group of rows; missing/error rows count as zero quality."""
    done = [r for r in rows if r["status"] == "completed"]
    return {
        "planned": len(rows),
        "attempted": sum(1 for r in rows if r["status"] in ("completed", "error")),
        "completed": len(done),
        "error": sum(1 for r in rows if r["status"] == "error"),
        "skipped": sum(1 for r in rows if r["status"] == "skipped"),
        "stale": sum(1 for r in rows if r["status"] == "stale"),
        "grounded": sum(1 for r in done if r["grounded"]),
        "gold_hit": sum(1 for r in done if r["gold_hit"]),
        "median_chars_read": _median([r["chars_read"] for r in done]),
        "median_wall_s": _median([r["wall_s"] for r in done]),
    }


def select_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the fixed coverage gate, quality gate and tie-break rule to the 140 rows.

    Returns ``{"status": "insufficient_coverage" | "retain_baseline" | "candidate", "setting": ...}``.
    A candidate whose handwritten coverage is below 17/21 cannot qualify; independently winning
    knobs are never combined because only the five frozen settings are ever considered.
    """
    completed = sum(1 for r in rows if r["status"] == "completed")
    hw = {
        name: [r for r in rows if r["setting"] == name and r["provenance"] == "handwritten"]
        for name, _, _ in (BASELINE, *SWEEPS)
    }
    base = setting_stats(hw[BASELINE[0]])
    if completed < MIN_COMPLETED_TOTAL or base["completed"] < MIN_COMPLETED_HANDWRITTEN:
        return {"status": "insufficient_coverage", "setting": None, "completed_total": completed}
    qualifying: list[tuple[tuple[float, float, int, int], str]] = []
    for name, chars, reads in SWEEPS:
        stats = setting_stats(hw[name])
        if stats["completed"] < MIN_COMPLETED_HANDWRITTEN:
            continue
        if stats["grounded"] < base["grounded"] or stats["gold_hit"] < base["gold_hit"]:
            continue
        # strictly better than baseline on (median chars, median wall); a complete tie retains baseline
        if (stats["median_chars_read"], stats["median_wall_s"]) >= (base["median_chars_read"], base["median_wall_s"]):
            continue
        qualifying.append(((stats["median_chars_read"], stats["median_wall_s"], reads, chars), name))
    if not qualifying:
        return {"status": "retain_baseline", "setting": BASELINE[0], "completed_total": completed}
    best = min(qualifying)[1]
    return {"status": "candidate", "setting": best, "completed_total": completed}


def build_metrics(
    rows: list[dict[str, Any]], books: dict[str, dict[str, Any]], fixture_sha256: str, settings: EvalSettings
) -> dict[str, Any]:
    """Assemble the metric-only report payload (no excerpts, prompts, answers or provider text)."""
    by_book, by_prov, by_setting = {}, {}, {}
    for key in sorted({r["book_id"] for r in rows}):
        by_book[key] = setting_stats([r for r in rows if r["book_id"] == key])
    for key in ("handwritten", "generated"):
        by_prov[key] = setting_stats([r for r in rows if r["provenance"] == key])
    for name, _, _ in (BASELINE, *SWEEPS):
        by_setting[name] = {
            prov: setting_stats([r for r in rows if r["setting"] == name and r["provenance"] == prov])
            for prov in ("handwritten", "generated")
        }
    return {
        "experiment_count": len(rows),
        "llm": settings.llm,
        "seed": SEED,
        "fixture_sha256": fixture_sha256,
        "trees": {
            bid: {
                k: v
                for k, v in ctx.items()
                if k in ("generation", "node_count", "owned_node_count", "largest_leaf_tokens", "snapshot_sha256")
            }
            for bid, ctx in sorted(books.items())
        },
        "by_book": by_book,
        "by_provenance": by_prov,
        "by_setting": by_setting,
        "recommendation": select_recommendation(rows),
        "rows": rows,
    }


def render_report(metrics: dict[str, Any]) -> str:
    """Render a numeric-only markdown report."""
    rec = metrics["recommendation"]
    lines = [
        "# Bookstore agentic retrieval evaluation",
        "",
        f"- experiments: {metrics['experiment_count']}",
        f"- fixture sha256: {metrics['fixture_sha256']}",
        f"- seed: {metrics['seed']}",
        f"- recommendation: {rec['status']} ({rec['setting']})",
        "",
        "## By setting (handwritten)",
    ]
    for name, groups in metrics["by_setting"].items():
        s = groups["handwritten"]
        lines.append(
            f"- {name}: planned={s['planned']} attempted={s['attempted']} completed={s['completed']} "
            f"grounded={s['grounded']} gold_hit={s['gold_hit']} median_chars={s['median_chars_read']} "
            f"median_wall_s={s['median_wall_s']}"
        )
    lines += ["", "## By provenance"]
    for name, s in metrics["by_provenance"].items():
        lines.append(
            f"- {name}: planned={s['planned']} attempted={s['attempted']} completed={s['completed']} gold_hit={s['gold_hit']}"
        )
    lines += ["", "## By book"]
    for name, s in metrics["by_book"].items():
        lines.append(
            f"- {name}: planned={s['planned']} completed={s['completed']} stale={s['stale']} skipped={s['skipped']}"
        )
    lines += ["", "## Trees"]
    for name, t in metrics["trees"].items():
        lines.append(f"- {name}: nodes={t['node_count']} owned={t['owned_node_count']} sha={t['snapshot_sha256']}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# evaluation
# ----------------------------------------------------------------------------
async def evaluate_library(settings: EvalSettings) -> dict[str, Any]:
    """Run the frozen 140-row plan and return numeric report paths and recommendation."""
    questions, fixture_sha = load_questions(settings.questions)
    plan = build_plan(questions)

    preflight = _make_bookstore(settings)
    books: dict[str, dict[str, Any]] = {}
    unavailable: set[str] = set()
    for book_id in sorted({q.book_id for q in questions}):
        try:
            books[book_id] = await _book_context(preflight, book_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("book unavailable for evaluation: %s", error_category(exc))
            unavailable.add(book_id)

    rows: list[Optional[dict[str, Any]]] = [None] * len(plan)
    pending: asyncio.Queue[int] = asyncio.Queue()
    for index, item in enumerate(plan):
        q: EvalQuestion = item["question"]
        if q.book_id in unavailable:
            rows[index] = _row_base(item)  # skipped
        elif is_stale(q, books[q.book_id]):
            rows[index] = {**_row_base(item), "status": "stale"}
        else:
            pending.put_nowait(index)

    invocations = 0

    async def worker() -> None:
        nonlocal invocations
        bookstore = _make_bookstore(settings)
        while True:
            try:
                index = pending.get_nowait()
            except asyncio.QueueEmpty:
                return
            if invocations >= TOTAL_ROWS:  # defensive cap on agentic invocations
                rows[index] = _row_base(plan[index])
                continue
            invocations += 1
            q = plan[index]["question"]
            rows[index] = await _run_row(bookstore, plan[index], books[q.book_id])

    workers = max(1, min(settings.concurrency, pending.qsize() or 1))
    await asyncio.gather(*(worker() for _ in range(workers)))

    final = [r for r in rows if r is not None]
    metrics = build_metrics(final, books, fixture_sha, settings)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = settings.out_dir / stamp
    out.mkdir(parents=True, exist_ok=True)
    metrics_path, report_path = out / "metrics.json", out / "report.md"
    metrics_bytes = json.dumps(metrics, indent=2, sort_keys=True, default=str).encode()
    metrics_path.write_bytes(metrics_bytes)
    report_bytes = render_report(metrics).encode()
    report_path.write_bytes(report_bytes)
    return {
        "report": str(report_path),
        "metrics": str(metrics_path),
        "report_sha256": _sha256(report_bytes),
        "metrics_sha256": _sha256(metrics_bytes),
        "recommendation": metrics["recommendation"],
        "experiment_count": metrics["experiment_count"],
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Run library/questions/llm/concurrency options or explicit generate-questions mode."""
    parser = argparse.ArgumentParser(prog="agentic_eval", description="Bookstore agentic retrieval evaluation")
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--llm", default=EvalSettings.model_fields["llm"].default)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, default=EvalSettings.model_fields["out_dir"].default)
    parser.add_argument("--generate-questions", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = EvalSettings(
            library=args.library,
            questions=args.questions,
            llm=args.llm,
            concurrency=args.concurrency,
            out_dir=args.out_dir,
        )
    except ValueError as exc:
        sys.stderr.write(f"invalid settings: {exc}\n")
        return 2
    try:
        if args.generate_questions:
            generated = asyncio.run(generate_questions(settings))
            payload = {"seed": SEED, "questions": [q.model_dump() for q in generated]}
            with settings.questions.open("x", encoding="utf-8") as handle:  # never overwrite
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            sys.stdout.write(json.dumps({"generated": len(generated), "fixture": str(settings.questions)}) + "\n")
            return 0
        result = asyncio.run(evaluate_library(settings))
    except (BookstoreError, FileExistsError, OSError, ValueError) as exc:
        sys.stderr.write(f"{error_category(exc)}: evaluation did not complete\n")
        return 1
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
