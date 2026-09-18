"""S4 spike harness: brain page-state designs, version identity, lineage and report writer."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import aiosqlite

from parrot.knowledge.wiki import create_wiki_store, pack_results  # __init__.py re-export (brain.py:17)
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens  # store.py:409, :318
from parrot.memory.episodic.models import EpisodeOutcome, EpisodicMemory  # episodic/models.py:20,55

logger = logging.getLogger(__name__)
SPIKE_DIR = Path(__file__).resolve().parent  # coder-owned spike package dir — sdd-coder fidelity gate forbids commits under sdd/
MAX_LINEAGE_DEPTH = 32  # report parameter — the amendment freezes the production bound
_IMPORTANCE_THRESHOLD = 5  # mirrors DreamConfig.importance_threshold default (models.py:78)

_STATE_BLOCK_RE = re.compile(r"<!--\s*s4-state\n(?P<json>.*?)\n-->\n\n", re.DOTALL)


@dataclass(frozen=True)
class PageState:
    """Mutable dynamics state a page version carries (subset of spec §2 MemoryState + priors)."""

    stability: float
    difficulty: float
    review_count: int
    prior_stability: float | None
    prior_difficulty: float | None
    parameter_version: str


def content_version(body_without_state: str, source_episode_ids: list[str]) -> str:
    """Deterministic version id: same prose + same sources ⇒ same version; new evidence ⇒ new version."""
    digest = hashlib.sha1()
    digest.update(body_without_state.encode("utf-8"))
    digest.update(b"|")
    digest.update(",".join(sorted(source_episode_ids)).encode("utf-8"))
    return digest.hexdigest()


class Design(Protocol):
    """One page-state storage design; all three run identical scenarios."""

    name: str

    async def write(self, store: Any, record: WikiPageRecord, state: PageState, version: str) -> None: ...
    async def read_state(self, store: Any, concept_id: str, version: str) -> PageState | None: ...
    def searchable_body(self, body: str) -> str: ...


class FrontmatterDesign:
    """(A) A JSON-ish fenced state block prepended to `body`; stripped before FTS/search."""

    name = "A-frontmatter"

    def _render(self, state: PageState, version: str) -> str:
        payload = {"version": version, **dataclasses.asdict(state)}
        return "<!-- s4-state\n" + json.dumps(payload, sort_keys=True) + "\n-->\n\n"

    async def write(self, store: Any, record: WikiPageRecord, state: PageState, version: str) -> None:
        body_with_state = self._render(state, version) + record.body
        merged = record.model_copy(update={"body": body_with_state})
        await store.upsert_pages([merged])

    async def read_state(self, store: Any, concept_id: str, version: str) -> PageState | None:
        page = await store.get_page(concept_id, include_body=True)
        if page is None:
            return None
        match = _STATE_BLOCK_RE.match(page.get("body") or "")
        if not match:
            return None
        try:
            payload = json.loads(match.group("json"))
        except json.JSONDecodeError:
            return None
        if payload.get("version") != version:
            return None
        payload.pop("version", None)
        return PageState(**payload)

    def searchable_body(self, body: str) -> str:
        return _STATE_BLOCK_RE.sub("", body, count=1)


class SidecarDesign:
    """(B) State lives in a companion `WikiPageRecord` (`concept_id + ':state:' + version`); body untouched."""

    name = "B-sidecar"

    @staticmethod
    def _sidecar_id(concept_id: str, version: str) -> str:
        return f"{concept_id}:state:{version}"

    async def write(self, store: Any, record: WikiPageRecord, state: PageState, version: str) -> None:
        await store.upsert_pages([record])
        sidecar_id = self._sidecar_id(record.concept_id, version)
        payload = {"version": version, **dataclasses.asdict(state)}
        sidecar = WikiPageRecord(
            concept_id=sidecar_id,
            node_id=sidecar_id,
            title=f"state:{record.concept_id}",
            # "archive" is EXISTING production plumbing (store.py:1963-1965) that already excludes a
            # category from the default search_fts() result set — reused here, no schema change needed.
            category="archive",
            summary="",
            body=json.dumps(payload),
            token_count=0,
            origin="memory",
            asserted_by=record.asserted_by,
        )
        await store.upsert_pages([sidecar])

    async def read_state(self, store: Any, concept_id: str, version: str) -> PageState | None:
        page = await store.get_page(self._sidecar_id(concept_id, version), include_body=True)
        if page is None:
            return None
        try:
            payload = json.loads(page.get("body") or "{}")
        except json.JSONDecodeError:
            return None
        if payload.get("version") != version:
            return None
        payload.pop("version", None)
        return PageState(**payload)

    def searchable_body(self, body: str) -> str:
        return body


class SimulatedMetadataColumnDesign:
    """(C) State kept in a prototype-owned SQLite table beside the wiki DB — NOT a `WikiPageRecord` change."""

    name = "C-metadata-column(simulated)"

    def _companion_path(self, store: Any) -> Path:
        db_path = getattr(store, "db_path", None)  # SQLiteWikiStore.db_path property (store.py:921-923)
        if db_path is None:
            raise RuntimeError("SimulatedMetadataColumnDesign requires a SQLiteWikiStore (needs `db_path`)")
        return db_path.with_name(db_path.name + ".s4_state.sqlite")

    async def _connect(self, store: Any) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._companion_path(store))
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS page_state ("
            "concept_id TEXT NOT NULL, version TEXT NOT NULL, state_json TEXT NOT NULL,"
            " PRIMARY KEY (concept_id, version))"
        )
        await conn.commit()
        return conn

    async def write(self, store: Any, record: WikiPageRecord, state: PageState, version: str) -> None:
        await store.upsert_pages([record])  # production WikiPageRecord unchanged — body/summary untouched
        conn = await self._connect(store)
        try:
            await conn.execute(
                "INSERT OR REPLACE INTO page_state (concept_id, version, state_json) VALUES (?, ?, ?)",
                (record.concept_id, version, json.dumps(dataclasses.asdict(state))),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def read_state(self, store: Any, concept_id: str, version: str) -> PageState | None:
        conn = await self._connect(store)
        try:
            cursor = await conn.execute(
                "SELECT state_json FROM page_state WHERE concept_id = ? AND version = ?",
                (concept_id, version),
            )
            row = await cursor.fetchone()
        finally:
            await conn.close()
        if row is None:
            return None
        return PageState(**json.loads(row[0]))

    def searchable_body(self, body: str) -> str:
        return body


class LineageCycle(Exception):
    """Raised when a `supersedes` traversal revisits a version or exceeds `MAX_LINEAGE_DEPTH` (spec §7 `lineage_cycle`)."""


@dataclass
class Lineage:
    """episode → version edges and version --supersedes--> version edges, depth-bounded and cycle-checked."""

    episode_to_version: dict[str, str] = field(default_factory=dict)
    supersedes: dict[str, str] = field(default_factory=dict)  # new_version -> old_version

    def canonical(self, version: str) -> str:
        """Follow `supersedes` forward (old → newest) up to `MAX_LINEAGE_DEPTH`; raise `LineageCycle` on revisit."""
        reverse = {old: new for new, old in self.supersedes.items()}  # old_version -> new_version
        seen = {version}
        current = version
        depth = 0
        while current in reverse:
            depth += 1
            if depth > MAX_LINEAGE_DEPTH:
                raise LineageCycle(f"lineage traversal exceeded MAX_LINEAGE_DEPTH={MAX_LINEAGE_DEPTH} from {version!r}")
            current = reverse[current]
            if current in seen:
                raise LineageCycle(f"lineage cycle detected at {current!r} starting from {version!r}")
            seen.add(current)
        return current

    def credit_targets(self, cited_ids: list[str]) -> set[str]:
        """Map episode ids/version ids to canonical versions; return the deduped set (one credit per version)."""
        targets: set[str] = set()
        for cid in cited_ids:
            version = self.episode_to_version.get(cid, cid)
            targets.add(self.canonical(version))
        return targets


async def make_store(tmp_dir: Path) -> Any:
    """Mirror `BrainStore.__init__` (brain.py:31-52): `create_wiki_store(tmp_dir, wiki_name=..., backend='sqlite')`."""
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return create_wiki_store(tmp_dir, wiki_name="s4-brain-state-spike", backend="sqlite")


async def scenario_redistill_5x(design: Design, store: Any) -> dict[str, Any]:
    """Same title/category, 5 successive bodies/evidence: distinct versions? old excluded from search? state kept?"""
    family_id = "mem-" + hashlib.sha1(f"{design.name}-same-title::same-category".encode()).hexdigest()[:12]
    versions: list[str] = []
    concept_ids: list[str] = []
    prev_concept_id: str | None = None

    for i in range(5):
        body_i = f"Distilled lesson body revision {i}: evidence accrues with each re-distillation."
        episode_ids = [f"ep-{design.name}-{i}-a", f"ep-{design.name}-{i}-b"]
        version = content_version(body_i, episode_ids)
        concept_id = f"{family_id}-{version[:10]}"
        versions.append(version)
        concept_ids.append(concept_id)

        state = PageState(
            stability=1.0 + i,
            difficulty=5.0,
            review_count=0,
            prior_stability=None if i == 0 else 1.0 + (i - 1),
            prior_difficulty=None if i == 0 else 5.0,
            parameter_version="v1",
        )
        record = WikiPageRecord(
            concept_id=concept_id,
            node_id=concept_id,
            title="Same Title",
            category="lesson",
            summary=body_i[:120],
            body=body_i,
            token_count=estimate_tokens(body_i),
            origin="memory",
            asserted_by="agent:s4-spike",
        )
        await design.write(store, record, state, version)

        if prev_concept_id is not None:
            # A re-distillation supersedes the previous version — archive its page row so the
            # EXISTING default search_fts() category filter (store.py:1963-1965) excludes it from
            # ordinary search without any new admission mechanism.
            prev_page = await store.get_page(prev_concept_id, include_body=True)
            if prev_page is not None:
                await store.upsert_pages(
                    [
                        WikiPageRecord(
                            concept_id=prev_page["concept_id"],
                            node_id=prev_page.get("node_id") or prev_page["concept_id"],
                            title=prev_page.get("title") or "",
                            category="archive",
                            summary=prev_page.get("summary") or "",
                            body=prev_page.get("body") or "",
                            token_count=prev_page.get("token_count") or 0,
                            origin=prev_page.get("origin") or "memory",
                            asserted_by=prev_page.get("asserted_by"),
                        )
                    ]
                )
        prev_concept_id = concept_id

    distinct_versions = len(set(versions)) == len(versions)

    search_results = await store.search_fts("distilled lesson body revision", limit=10)
    found_ids = {r["concept_id"] for r in search_results}
    old_versions_excluded_from_search = concept_ids[-1] in found_ids and not any(
        cid in found_ids for cid in concept_ids[:-1]
    )

    state_preserved_per_version = True
    for concept_id, version in zip(concept_ids, versions, strict=True):
        if await design.read_state(store, concept_id, version) is None:
            state_preserved_per_version = False
            break

    return {
        "design": design.name,
        "family_id": family_id,
        "concept_ids": concept_ids,
        "versions": versions,
        "distinct_versions": distinct_versions,
        "old_versions_excluded_from_search": old_versions_excluded_from_search,
        "state_preserved_per_version": state_preserved_per_version,
    }


async def scenario_copy_and_edit(design: Design, store: Any) -> dict[str, Any]:
    """remember-style re-write + copy to a second store — does state survive (mirrors brain.py:97, :176)?"""
    dest_dir = Path(tempfile.mkdtemp(prefix="s4-dest-"))
    dest_store = await make_store(dest_dir)

    page_id = "mem-" + hashlib.sha1(f"{design.name}-copy-edit-title::note".encode()).hexdigest()[:12]
    episode_ids = ["ep-copy-1"]

    body_v1 = "Original distilled body for the copy/edit scenario."
    version_v1 = content_version(body_v1, episode_ids)
    state_v1 = PageState(
        stability=2.0, difficulty=4.0, review_count=1, prior_stability=None, prior_difficulty=None,
        parameter_version="v1",
    )
    record_v1 = WikiPageRecord(
        concept_id=page_id,
        node_id=page_id,
        title="Copy Edit Title",
        category="note",
        summary=body_v1[:120],
        body=body_v1,
        token_count=estimate_tokens(body_v1),
        origin="memory",
        asserted_by="agent:s4-spike",
    )
    await design.write(store, record_v1, state_v1, version_v1)

    # remember()-style re-write: same page_id, updated body/evidence (brain.py:80-97 upserts in place).
    body_v2 = body_v1 + " Updated with new evidence."
    version_v2 = content_version(body_v2, episode_ids)
    state_v2 = PageState(
        stability=2.5, difficulty=4.0, review_count=2, prior_stability=2.0, prior_difficulty=4.0,
        parameter_version="v1",
    )
    record_v2 = WikiPageRecord(
        concept_id=page_id,
        node_id=page_id,
        title="Copy Edit Title",
        category="note",
        summary=body_v2[:120],
        body=body_v2,
        token_count=estimate_tokens(body_v2),
        origin="memory",
        asserted_by="agent:s4-spike",
    )
    await design.write(store, record_v2, state_v2, version_v2)
    survives_remember_rewrite = (await design.read_state(store, page_id, version_v2)) is not None

    # copy_page_to()-style copy: get_page + upsert into `other` (brain.py:158-177) — touches ONLY the
    # WikiPageRecord fields; it never invokes a design's write() on the destination store.
    page = await store.get_page(page_id, include_body=True)
    copied_record = WikiPageRecord(
        concept_id=page["concept_id"],
        node_id=page.get("node_id") or page["concept_id"],
        title=page.get("title") or "",
        category=page.get("category") or "note",
        summary=page.get("summary") or "",
        body=page.get("body") or "",
        token_count=page.get("token_count") or 0,
        origin="memory",
        asserted_by=page.get("asserted_by"),
    )
    await dest_store.upsert_pages([copied_record])
    survives_copy_page_to = (await design.read_state(dest_store, page_id, version_v2)) is not None

    return {
        "design": design.name,
        "survives_remember_rewrite": survives_remember_rewrite,
        "survives_copy_page_to": survives_copy_page_to,
    }


async def scenario_search_drift(design: Design, store: Any) -> dict[str, Any]:
    """FTS hit set/rank + pack_results token cost: same prose WITH design-embedded state vs a plain control page."""
    body = "The deploy pipeline requires a valid kubeconfig secret before rollout."
    episode_ids = ["ep-drift-1"]
    version = content_version(body, episode_ids)
    state = PageState(
        stability=3.3333, difficulty=6.6666, review_count=4, prior_stability=None, prior_difficulty=None,
        parameter_version="v1",
    )
    with_state_id = "mem-" + hashlib.sha1(f"{design.name}-drift-with-state::lesson".encode()).hexdigest()[:12]
    without_state_id = "mem-" + hashlib.sha1(f"{design.name}-drift-without-state::lesson".encode()).hexdigest()[:12]

    record_with = WikiPageRecord(
        concept_id=with_state_id,
        node_id=with_state_id,
        title="Deploy Kubeconfig Lesson (state)",
        category="lesson",
        summary=body[:120],
        body=body,
        token_count=estimate_tokens(body),
        origin="memory",
        asserted_by="agent:s4-spike",
    )
    await design.write(store, record_with, state, version)

    record_without = WikiPageRecord(
        concept_id=without_state_id,
        node_id=without_state_id,
        title="Deploy Kubeconfig Lesson (control)",
        category="lesson",
        summary=body[:120],
        body=body,
        token_count=estimate_tokens(body),
        origin="memory",
        asserted_by="agent:s4-spike",
    )
    await store.upsert_pages([record_without])

    results = await store.search_fts("kubeconfig deploy pipeline", limit=10)
    hit_ids = [r["concept_id"] for r in results]
    scores = {r["concept_id"]: r["score"] for r in results}
    with_state_results = [r for r in results if r["concept_id"] == with_state_id]
    without_state_results = [r for r in results if r["concept_id"] == without_state_id]
    packed_with = pack_results(with_state_results, budget_tokens=600) if with_state_results else None
    packed_without = pack_results(without_state_results, budget_tokens=600) if without_state_results else None

    return {
        "design": design.name,
        "hits": hit_ids,
        "with_state_hit": with_state_id in hit_ids,
        "without_state_hit": without_state_id in hit_ids,
        "score_with_state": scores.get(with_state_id),
        "score_without_state": scores.get(without_state_id),
        "packed_token_cost_with_state": packed_with.tokens_used if packed_with else None,
        "packed_token_cost_without_state": packed_without.tokens_used if packed_without else None,
    }


def _fake_episode(
    tag: str,
    *,
    created_at: datetime,
    importance: int = 5,
    lesson_learned: str = "some lesson",
    metadata: dict[str, Any] | None = None,
) -> EpisodicMemory:
    return EpisodicMemory(
        episode_id=tag,
        agent_id="s4-agent",
        situation=f"S4 watermark scenario situation {tag}",
        action_taken=f"S4 action {tag}",
        outcome=EpisodeOutcome.SUCCESS,
        created_at=created_at,
        importance=importance,
        lesson_learned=lesson_learned,
        metadata=metadata or {},
    )


def scenario_watermark_recovery() -> dict[str, Any]:
    """Episodes older than `DreamState.last_run` without `consolidated_into` — recovery path (runner.py:235-267)."""
    now = datetime.now(UTC)
    last_run = now - timedelta(hours=1)

    old_unconsolidated = _fake_episode("old-unconsolidated", created_at=now - timedelta(hours=5), importance=8)
    old_consolidated = _fake_episode(
        "old-consolidated",
        created_at=now - timedelta(hours=5),
        importance=8,
        metadata={"consolidated_into": "mem-x"},
    )
    new_eligible = _fake_episode("new-eligible", created_at=now - timedelta(minutes=10), importance=8)
    below_threshold_no_lesson = _fake_episode(
        "below-threshold", created_at=now - timedelta(hours=6), importance=1, lesson_learned=""
    )
    all_episodes = [old_unconsolidated, old_consolidated, new_eligible, below_threshold_no_lesson]

    # `_collect` filters by `since=state.last_run` on `get_recent` BEFORE the eligibility predicate
    # (runner.py:253-256); the watermark is exclusive, so an episode older than `last_run` is
    # invisible to the NEXT ordinary cycle regardless of its own consolidation status.
    since_filtered = [ep for ep in all_episodes if ep.created_at > last_run]
    eligible = [
        ep
        for ep in since_filtered
        if (ep.importance >= _IMPORTANCE_THRESHOLD or bool(ep.lesson_learned)) and "consolidated_into" not in ep.metadata
    ]
    excluded_by_watermark = [ep.episode_id for ep in all_episodes if ep.created_at <= last_run]

    return {
        "last_run": last_run.isoformat(),
        "eligible_ids": [ep.episode_id for ep in eligible],
        "excluded_by_watermark_ids": excluded_by_watermark,
        "recovery_path": (
            "Episodes with created_at <= state.last_run are invisible to the ordinary next cycle "
            "(runner.py:253-256 — `since` is a lower bound on get_recent). Recovering them requires an "
            "explicit backfill query that bypasses `since` (e.g. a one-off get_recent(since=None) scoped "
            "by episode_id, or a dedicated scan for metadata['consolidated_into'] absent), never a "
            "`last_run` rewind — rewinding `last_run` would re-collect already-consolidated episodes too, "
            "since DreamState carries a single scalar cursor, not a per-episode watermark."
        ),
    }


def _fmt(value: Any) -> str:
    return "PASS" if value else "FAIL"


def write_report(results: dict[str, Any], *, commands: list[str]) -> Path:
    """Persist `metrics.json` + `REPORT.md` under `SPIKE_DIR`."""
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    (SPIKE_DIR / "metrics.json").write_text(json.dumps(results, indent=2, sort_keys=True, default=str) + "\n")

    designs: dict[str, Any] = results.get("designs", {})
    watermark: dict[str, Any] = results.get("watermark_recovery", {})
    lineage: dict[str, Any] = results.get("lineage", {})

    lines: list[str] = []
    lines.append("# S4 (TASK-3385) — Brain Page State Storage, Version Identity and Lineage — Gate Report")
    lines.append("")
    lines.append(
        "Gate: G4/S4 (spec §3 row G4; brainstorm S4). This report is the reproducible artifact reviewed "
        "by the owner; it is not itself the gate pass — see `amendment.md`."
    )
    lines.append("")
    lines.append("## Commands")
    lines.append("")
    for c in commands:
        lines.append(f"```\n{c}\n```")
    lines.append("")
    lines.append("## Versions")
    lines.append("")
    lines.append(f"- `MAX_LINEAGE_DEPTH` (traversal bound used by this report): {MAX_LINEAGE_DEPTH}")
    lines.append("- `WikiPageRecord` has no `metadata` field (spec C6) — verified against store.py:409-453")
    lines.append("")
    lines.append("## Per-Design Comparison")
    lines.append("")
    lines.append(
        "| Design | 5x redistill: distinct versions | old excluded from search | state per version preserved "
        "| survives remember-rewrite | survives copy_page_to | FTS hit w/ state | FTS hit w/o state "
        "| packed tokens (state) | packed tokens (control) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, r in designs.items():
        redist = r["redistill_5x"]
        copy_edit = r["copy_and_edit"]
        drift = r["search_drift"]
        lines.append(
            f"| {name} | {redist['distinct_versions']} | {redist['old_versions_excluded_from_search']} | "
            f"{redist['state_preserved_per_version']} | {copy_edit['survives_remember_rewrite']} | "
            f"{copy_edit['survives_copy_page_to']} | {drift['with_state_hit']} | {drift['without_state_hit']} | "
            f"{drift['packed_token_cost_with_state']} | {drift['packed_token_cost_without_state']} |"
        )
    lines.append("")
    lines.append("## Lineage — Bound and Cycle Results")
    lines.append("")
    lines.append(
        f"- Traversal bound: `MAX_LINEAGE_DEPTH` = {MAX_LINEAGE_DEPTH} (report parameter; the amendment "
        "freezes the production bound)"
    )
    lines.append("- Cycle detection event category: `lineage_cycle` (spec §7)")
    for name, lin in lineage.items():
        lines.append(
            f"- {name}: canonical(oldest) resolves to newest = {lin['canonical_of_oldest_is_newest']}; "
            f"duplicate forwarding → one credit = {lin['duplicate_forwarding_one_credit']}"
        )
    lines.append("")
    lines.append("## Watermark Recovery")
    lines.append("")
    lines.append(f"- `last_run` watermark: {watermark.get('last_run')}")
    lines.append(f"- Eligible episode ids for the next ordinary cycle: {watermark.get('eligible_ids')}")
    lines.append(f"- Excluded by the watermark: {watermark.get('excluded_by_watermark_ids')}")
    lines.append(f"- Recovery path: {watermark.get('recovery_path')}")
    lines.append("")
    lines.append("## Legacy Promotion Evidence Inventory")
    lines.append("")
    lines.append(
        "- `DreamCycleRunner.run_cycle` (runner.py:182-186) increments `state.reinforcement_counts[page_id]` "
        "once per DISTINCT CYCLE that reinforces a page — not per verified review of that page's content."
    )
    lines.append(
        "- Promotion to the org wiki (runner.py:196-201) fires when `reinforcement_counts[page_id] >= "
        "DreamConfig.org_promotion_cycles` (default 3, models.py:81) — a cycle-count threshold, not "
        "evidence of a verified successful outcome that actually used the promoted content."
    )
    lines.append(
        "- `DreamCycleReport` (models.py:103-129) has no `pages_redistilled` / `memories_forgotten` fields "
        "(spec C7) — this report proposes their count semantics only in `amendment.md`."
    )
    lines.append("")
    lines.append("## G2 Coordination Points")
    lines.append("")
    lines.append(
        "- State-write ordering: whichever design is frozen must write its page-state update either in the "
        "SAME unit of work as G2's atomic review-apply transaction, or immediately after under a documented "
        "at-least-once/idempotent replay contract — this spike used a single, non-transactional "
        "`upsert_pages`/companion-write call per design and never modeled the atomic review transaction "
        "itself (that protocol is G2's; NOT in scope here)."
    )
    lines.append(
        "- Version admission: a G2 review command should target a `content_version`, not a bare `page_id`, "
        "so a review that lands after a re-distillation can never silently apply to content the reviewer "
        "did not actually see (spec §2 'A review of old content must not automatically count as verified "
        "success of newly synthesized content')."
    )
    lines.append("")
    lines.append("## Pass/Fail")
    lines.append("")
    for name, r in designs.items():
        redist = r["redistill_5x"]
        passed = (
            redist["distinct_versions"]
            and redist["old_versions_excluded_from_search"]
            and redist["state_preserved_per_version"]
        )
        lines.append(f"- {name} — 5× re-distill (distinct versions, old excluded, state preserved): {_fmt(passed)}")
    for name, r in designs.items():
        copy_edit = r["copy_and_edit"]
        lines.append(
            f"- {name} — state survives remember()/copy_page_to(): "
            f"{_fmt(copy_edit['survives_remember_rewrite'])}/{_fmt(copy_edit['survives_copy_page_to'])}"
        )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- Environment: this attempt worktree is missing the compiled `parrot/utils/types.*.so` / "
        "`parrot/utils/parsers/toml.*.so` build artifacts; `packages/ai-parrot/tests/conftest.py`'s "
        "repo-wide autouse fixture transitively imports them, making a bare "
        "`pytest packages/ai-parrot/tests/...` uncollectable in this worktree — a pre-existing, "
        "worktree-wide gap unrelated to this task (see S1's REPORT.md for the same finding). Verified "
        "instead with `pytest -c /dev/null <path>`, which bypasses only the broken root conftest chain, "
        "never any logic under this spike."
    )
    lines.append(
        "- The atomic review protocol itself belongs to G2; this report only records the coordination "
        "points above, it does not design a second protocol."
    )
    lines.append(
        "- `SimulatedMetadataColumnDesign`'s companion table lives beside the wiki db file via the "
        "SQLite-specific `db_path` property; the real migration (if design C is chosen) is a genuine "
        "`WikiPageRecord.metadata` column across all four wiki backends (see `amendment.md`)."
    )
    lines.append(
        "- `scenario_search_drift` uses query terms that never overlap the JSON state-block vocabulary, so "
        "it isolates document-length/BM25 normalisation drift rather than lexical noise; a state payload "
        "containing terms that accidentally match future queries is not modeled here."
    )
    lines.append("")
    lines.append("See `amendment.md` in this directory for the proposed spec freeze.")
    (SPIKE_DIR / "REPORT.md").write_text("\n".join(lines) + "\n")
    return SPIKE_DIR / "REPORT.md"
