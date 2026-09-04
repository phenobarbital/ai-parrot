"""§27 ingest orchestrator (FEAT-481, spec Module 6).

Wires every node from Modules 2-14 into the contract's ordered ingest
workflow: read context (§12) → fetch-gate (§14, dedup) → chronological
sort (G5) → per meeting: raw bundle (§13/§14) → classify (§15) →
contradiction detection (§9/§22, run against the summary BEFORE the
meeting page renders or the project updates — this task's own Scope
ordering) → meeting page (§17) → project reconcile/new-project (§16/§19)
→ entities/concepts (§20/§21) → daily synthesis (§23) → indexes/overview
(§18/§24) → registry mirror (§25) → §34 validation gate → log (§33) →
archive (§31, Module 14 — lazily picked up once implemented) → derived
GraphIndex rebuild (Module 13).

**§34 gate.** A meeting whose post-op validation fails has its
Claude-created *compiled* changes rolled back (never raw — raw bytes are
immutable regardless of outcome), a review item queued, and NO
registry/log success entry written — exactly the §34 failure protocol.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import conf
from .naming import meeting_source_filename, now_iso, title_case_name
from .nodes import classify as classify_node
from .nodes import contradictions as contradictions_node
from .nodes import daily as daily_node
from .nodes import entity_concept_batch as entity_concept_batch_node
from .nodes import fetch_gate as fetch_gate_node
from .nodes import indexes as indexes_node
from .nodes import log as log_node
from .nodes import meeting_page as meeting_page_node
from .nodes import project_reconcile as project_reconcile_node
from .nodes import quarantine as quarantine_node
from .nodes import raw_bundle as raw_bundle_node
from .nodes import review_queue as review_queue_node
from .render.project import parse_project_page
from .validation import ValidationContext, validate

logger = logging.getLogger(__name__)


class IngestProfile(BaseModel):
    """Cost/fidelity profile for one ingest run.

    The ``full`` profile runs the whole contract pipeline at full fidelity
    (steady-state). The ``backfill`` profile trades fidelity for LLM cost on a
    one-time historical import, toggling off the most expensive strong-tier
    work while still producing the core pages. Entity/concept resolution stays
    ON in both — it is cheap (batched, cheap tier) after the FEAT-481 cost pass.

    Attributes:
        name: Profile name (``"full"`` / ``"backfill"``).
        reconcile_additional_projects: Reconcile every additional related
            project, not just the primary (the FEAT-481 #6 behavior).
        detect_contradictions: Run §22 contradiction detection (strong tier).
        classify_transcript_fallback: Allow the §15.4 full-transcript
            classification fallback (strong tier, long input).
        resolve_entities_concepts: Resolve §20/§21 entities + concepts.
        update_overview: Update ``Wiki/overview.md`` per run (§24.2).
    """

    name: str = "full"
    reconcile_additional_projects: bool = True
    detect_contradictions: bool = True
    classify_transcript_fallback: bool = True
    resolve_entities_concepts: bool = True
    update_overview: bool = True


_PROFILES: dict[str, IngestProfile] = {
    "full": IngestProfile(name="full"),
    "backfill": IngestProfile(
        name="backfill",
        reconcile_additional_projects=False,
        detect_contradictions=False,
        classify_transcript_fallback=False,
        resolve_entities_concepts=True,
        update_overview=False,
    ),
}


def resolve_profile(name: str | None) -> IngestProfile:
    """Resolve an ingest profile by name (falls back to conf, then ``full``).

    Args:
        name: Requested profile name, or ``None`` to use
            :data:`conf.WIKI_KB_INGEST_PROFILE`.

    Returns:
        The matching :class:`IngestProfile` (``full`` for an unknown name).
    """
    key = (name or conf.WIKI_KB_INGEST_PROFILE or "full").lower()
    return _PROFILES.get(key, _PROFILES["full"])


class WikiIngestContext(BaseModel):
    """Parameters for one :func:`run_ingest` invocation.

    Attributes:
        limit: Per-run cap on the total listing examined (steady-state
            throughput bound — spec Module 6). ``None`` means no cap.
        max_new: Per-run cap on NEW meetings fetched+compiled (the backfill
            chunk size). Distinct from ``limit`` — the fetch-gate pages past
            already-known meetings to find this many new ones, so a chunked
            backfill progresses instead of stalling on the newest page. Also
            bounds per-run Fireflies calls and LLM cost. ``None`` falls back
            to :data:`conf.WIKI_KB_MAX_NEW_PER_RUN`.
        force_refetch: Bypass the fetch-gate cheap-skip path and always
            fetch + fingerprint already-known meeting ids.
        since: ISO date lower bound for a manual wide-window ingest.
        lookback_days: Alternative to ``since`` — how many days back to
            widen the fetch window (bounded by
            :data:`~parrot.flows.wiki_ingest.conf.WIKI_KB_MAX_CATCHUP_DAYS`).
        profile: Cost/fidelity profile name (``"full"`` / ``"backfill"``);
            ``None`` uses :data:`conf.WIKI_KB_INGEST_PROFILE`. See
            :class:`IngestProfile`.
        agent: The :class:`~parrot.flows.wiki_ingest.agent.FirefliesWikiKBAgent`
            instance — supplies ``strong_client``/``cheap_client`` (built
            in ``configure()``) and the MCP tool surface the fetch-gate
            needs. Typed ``Any`` here to avoid a circular import with
            ``agent.py`` (which imports this module for
            :class:`IngestReport`).
    """

    model_config = {"arbitrary_types_allowed": True}

    limit: int | None = None
    max_new: int | None = None
    force_refetch: bool = False
    since: str | None = None
    lookback_days: int | None = None
    profile: str | None = None
    agent: Any = None


class IngestReport(BaseModel):
    """Result of one :func:`run_ingest` run (spec §35 change summary).

    Attributes:
        processed: Number of meetings compiled into the vault.
        skipped: Number of meetings skipped by the fetch gate (already
            processed / duplicate-skip).
        failed: Number of meetings whose §34 validation failed and were
            rolled back.
        created: Vault paths created across the whole run.
        updated: Vault paths updated across the whole run.
        contradictions: Contradiction page paths created/updated.
        review_items: Review Queue entries added.
        errors: Human-readable error messages collected during the run.
    """

    processed: int = 0
    skipped: int = 0
    failed: int = 0
    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class _PageWrite(BaseModel):
    """One page write recorded this meeting, for §34-failure rollback.

    Attributes:
        path: Vault-relative path.
        previous_content: The page's content before this write, or
            ``None`` when this write created the page (so rollback
            deletes rather than restores it).
    """

    path: str
    previous_content: str | None = None


class _MeetingOutcome(BaseModel):
    """One meeting's compiled result, prior to the §34 gate."""

    model_config = {"arbitrary_types_allowed": True}

    validation_passed: bool
    validation_failures: list[str] = Field(default_factory=list)
    writes: list[_PageWrite] = Field(default_factory=list)
    review_items: list[classify_node.ReviewItemDraft] = Field(default_factory=list)
    meeting_source_link: str = ""
    processing_mode: str = ""
    projects: list[str] = Field(default_factory=list)
    contradiction_links: list[str] = Field(default_factory=list)


async def _write_note(toolkit: Any, path: str, content: str, writes: list[_PageWrite]) -> None:
    """Create or update a page, recording a rollback snapshot first."""
    previous_content = None
    try:
        existing = await toolkit.read_note(path, include_content=True)
        previous_content = existing["content"]
        await toolkit.update_note(path, content, preserve_frontmatter=False)
    except FileNotFoundError:
        await toolkit.create_note(path, content)
    writes.append(_PageWrite(path=path, previous_content=previous_content))


async def _write_enrichment_page(
    toolkit: Any,
    vault_path: str,
    content: str,
    *,
    writes: list[_PageWrite],
    validation_ctx: ValidationContext,
    touched_paths: list[str],
) -> None:
    """Write one resolved entity/concept page and record §34 evidence.

    Shared by the batched entity + concept write loops so both record the
    same rollback journal entry, wikilink/queued-page evidence, and
    written-filename check.
    """
    await _write_note(toolkit, vault_path, content, writes)
    touched_paths.append(vault_path)
    validation_ctx.new_wikilinks.append(vault_path.removesuffix(".md"))
    validation_ctx.existing_or_queued_pages.append(vault_path.removesuffix(".md"))
    validation_ctx.written_filenames.append(Path(vault_path).name)


async def _rollback(toolkit: Any, writes: list[_PageWrite]) -> None:
    """§34 failure protocol — undo every compiled write, in reverse order.

    Never touches ``Raw/`` (raw bytes are immutable regardless of
    outcome) — only the pages recorded via :func:`_write_note`.
    """
    for write in reversed(writes):
        try:
            if write.previous_content is None:
                await toolkit.delete_note(write.path)
            else:
                await toolkit.update_note(write.path, write.previous_content, preserve_frontmatter=False)
        except Exception:
            logger.warning("Rollback failed for %s", write.path, exc_info=True)


async def _maybe_run_archive(toolkit: Any, registry: Any) -> None:
    """§27 step 22 — archive (Module 14, TASK-2673), picked up lazily.

    This orchestrator does not depend on Module 14 — a missing
    ``nodes/archive.py`` (not yet implemented) is a silent no-op, never
    a failure, so this function needs no change once that module lands.
    """
    try:
        from .nodes.archive import run_archive
    except ImportError:
        return
    try:
        await run_archive(toolkit, registry)
    except Exception:
        logger.warning("Archive step failed; continuing", exc_info=True)


def _project_vault_path(project_name: str) -> str:
    name = title_case_name(project_name)
    return f"Projects/{name}/{name}.md"


def _is_canonical_project_note(path: str) -> bool:
    """True for a ``Projects/<Name>/<Name>.md`` canonical project page."""
    note_path = Path(path)
    try:
        rel = note_path.relative_to("Projects")
    except ValueError:
        return False
    return len(rel.parts) == 2 and note_path.stem == note_path.parent.name


async def _build_existing_context(toolkit: Any) -> classify_node.ExistingContext:
    """§12/§15.1 — read the vault's existing-knowledge candidates once.

    The classifier's contract is match-before-create (rule #6): without
    these candidate lists it receives empty context and can return a
    spelling/alias variant of an existing project, which the subsequent
    exact-path lookup then treats as new — creating a duplicate canonical
    page. Building this once per run (the §12 startup-context model) keeps
    it cheap (vault listings, no LLM).

    Args:
        toolkit: This subsystem's own vault toolkit.

    Returns:
        The populated :class:`~.nodes.classify.ExistingContext`.
    """

    async def _stems(folder: str) -> list[str]:
        try:
            listing = await toolkit.list_notes(folder=folder, recursive=True)
        except FileNotFoundError:
            return []
        return sorted(
            {Path(n["path"]).stem for n in listing.get("notes", []) if Path(n["path"]).stem.lower() != "index"}
        )

    async def _project_names() -> list[str]:
        try:
            listing = await toolkit.list_notes(folder="Projects", recursive=True)
        except FileNotFoundError:
            return []
        return sorted({Path(n["path"]).stem for n in listing.get("notes", []) if _is_canonical_project_note(n["path"])})

    async def _excerpt(path: str, limit: int = 1500) -> str:
        try:
            note = await toolkit.read_note(path)
        except FileNotFoundError:
            return ""
        return str(note.get("content", ""))[:limit]

    return classify_node.ExistingContext(
        index_summary=await _excerpt("Wiki/index.md"),
        overview_summary=await _excerpt("Wiki/overview.md"),
        candidate_projects=await _project_names(),
        candidate_clients=await _stems("Wiki/Entities/Companies"),
        candidate_people=await _stems("Wiki/Entities/People"),
        candidate_products=await _stems("Wiki/Entities/Products"),
        candidate_concepts=await _stems("Wiki/Concepts"),
    )


async def _upsert_project_meeting_index(
    toolkit: Any,
    project_name: str,
    *,
    meeting: fetch_gate_node.GatedMeeting,
    meeting_source_link: str,
    significance: str,
    writes: list[_PageWrite],
) -> None:
    """§18 — keep a project's active ``Meeting Summaries/index.md`` current.

    A newly-created project would otherwise never get this required
    structure: the §31 archive workflow only re-splits an index that
    already exists, so without seeding it here the project's meetings are
    absent from project navigation and archival processing. Idempotent —
    an entry for ``meeting_source_link`` is de-duplicated on reprocess.
    The write is recorded in ``writes`` so a §34 failure rolls it back.

    Args:
        toolkit: This subsystem's own vault toolkit.
        project_name: The project's name (Title-Cased internally).
        meeting: The meeting being added to the index.
        meeting_source_link: Wikilink target of the meeting source page.
        significance: One-line significance for the index entry.
        writes: The meeting's rollback journal.
    """
    from .nodes.archive import _parse_meeting_index
    from .nodes.indexes import render_project_meeting_index_active

    name = title_case_name(project_name)
    index_path = f"Projects/{name}/Meeting Summaries/index.md"
    try:
        note = await toolkit.read_note(index_path)
        entries = _parse_meeting_index(note["content"])
    except FileNotFoundError:
        entries = []
    entries = [e for e in entries if e[1] != meeting_source_link]
    entries.append((meeting.meeting_date, meeting_source_link, significance))
    entries.sort(key=lambda e: e[0], reverse=True)
    await _write_note(toolkit, index_path, render_project_meeting_index_active(name, entries), writes)


async def _reconcile_project(
    agent: Any,
    toolkit: Any,
    project_name: str,
    *,
    meeting: fetch_gate_node.GatedMeeting,
    meeting_extraction: Any,
    meeting_source_link: str,
    classification: Any,
    contradiction_titles: list[str],
    writes: list[_PageWrite],
    validation_ctx: ValidationContext,
    review_items: list[Any],
    touched_paths: list[str],
) -> str | None:
    """§16/§19 — reconcile (or create) ONE project page for this meeting.

    Applied to the primary project AND every additional related project: a
    project the classifier declared relevant must receive this meeting's
    source link and current-state update, not merely a wikilink from the
    meeting page. Only the primary project carries this meeting's
    contradiction links (they were detected against the primary project's
    claims); additional projects get an empty ``contradiction_titles``.

    Args:
        agent: The agent (for ``strong_client``).
        toolkit: This subsystem's vault toolkit.
        project_name: The project to reconcile.
        meeting: The meeting driving the reconcile.
        meeting_extraction: The Module 8 extraction.
        meeting_source_link: Wikilink target of the meeting source page.
        classification: The Module 7 classification.
        contradiction_titles: Bare contradiction-page titles to link.
        writes: The meeting's rollback journal.
        validation_ctx: The §34 evidence context (updated in place).
        review_items: The meeting's collected review-item drafts.
        touched_paths: The meeting's touched-path list (for §2 rule 1).

    Returns:
        The project name if a page was written (created/updated/
        chronological), else ``None``.
    """
    from .models import ProjectFrontmatter

    project_path = _project_vault_path(project_name)
    touched_paths.append(project_path)
    existing_content = None
    existing_frontmatter = None
    locked = False
    try:
        note = await toolkit.read_note(project_path)
        existing_content = note["content"]
        locked = bool(note["frontmatter"].get("locked", False))
        existing_frontmatter = ProjectFrontmatter(**{k: v for k, v in note["frontmatter"].items() if k != "locked"})
    except FileNotFoundError:
        pass

    reconcile_result = await project_reconcile_node.run_project_reconcile(
        agent.strong_client,
        existing_content=existing_content,
        existing_frontmatter=existing_frontmatter,
        locked=locked,
        project_name=project_name,
        meeting=meeting,
        meeting_extraction=meeting_extraction,
        meeting_source_link=meeting_source_link,
        classification=classification,
        contradiction_titles=contradiction_titles,
    )
    validation_ctx.diff_guard_violations.extend(reconcile_result.diff_guard_violations)
    if reconcile_result.review_item:
        review_items.append(reconcile_result.review_item)
    if reconcile_result.content and reconcile_result.vault_path:
        await _write_note(toolkit, reconcile_result.vault_path, reconcile_result.content, writes)
        validation_ctx.new_wikilinks.append(reconcile_result.vault_path.removesuffix(".md"))
        validation_ctx.existing_or_queued_pages.append(reconcile_result.vault_path.removesuffix(".md"))
        # §18 — seed/maintain the project's active meeting index so a
        # newly-created project gets the required structure (archive only
        # re-splits an index that already exists).
        await _upsert_project_meeting_index(
            toolkit,
            project_name,
            meeting=meeting,
            meeting_source_link=meeting_source_link,
            significance=meeting.title,
            writes=writes,
        )
        return project_name
    return None


async def _queue_review_item(
    toolkit: Any,
    report: IngestReport,
    *,
    review_type: str,
    title: str,
    source_id: str,
    issue: str,
    evidence: str,
    recommended_action: str,
) -> None:
    """Append one ``Wiki/Review Queue.md`` entry and record it on the report.

    Single source of truth for the read-append-write pattern, shared by
    every review-queue write site in this module — a validation failure
    always gets exactly one such entry, independent of any other
    pre-existing review items (fixes the prior duplicate-or-missing bug).
    """
    try:
        queue_note = await toolkit.read_note("Wiki/Review Queue.md")
        queue_content = queue_note["content"]
    except FileNotFoundError:
        queue_content = "# Review Queue\n\n"
    entry = review_queue_node.render_review_item(
        review_type=review_type,
        timestamp=now_iso(),
        title=title[:80],
        source_id=source_id,
        related_pages=[],
        issue=issue,
        evidence=evidence,
        recommended_action=recommended_action,
    )
    queue_content = review_queue_node.append_review_item(queue_content, entry)
    await toolkit.update_note("Wiki/Review Queue.md", queue_content, preserve_frontmatter=False)
    report.review_items.append(issue)


async def _handle_meeting_failure(
    toolkit: Any,
    report: IngestReport,
    vault_path: str,
    meeting: fetch_gate_node.GatedMeeting,
    *,
    error: str,
    prior_attempts: int,
    cap: int,
) -> None:
    """Module 17 — quarantine a failed meeting and surface it in the Review Queue.

    The caller has already rolled back this meeting's compiled writes. This moves the
    raw bundle to ``Raw/Failed/`` (the id is never marked processed, so it stays
    reprocessable) and queues a ``failed-processing`` item — or ``reprocess-exhausted``
    once ``attempts`` reaches ``cap``.

    Args:
        toolkit: The vault toolkit.
        report: The run's :class:`IngestReport` (``failed``/``errors`` updated).
        vault_path: Obsidian vault root.
        meeting: The gated meeting whose compile failed.
        error: The failure message.
        prior_attempts: Attempts before this failure (0 first time; the quarantine's
            recorded count on a retry).
        cap: :data:`conf.WIKI_KB_MAX_REPROCESS_ATTEMPTS`.
    """
    report.failed += 1
    report.errors.append(f"{meeting.source_id}: {error}")
    models = {"strong": conf.WIKI_KB_LLM_STRONG, "cheap": conf.WIKI_KB_LLM_CHEAP}
    try:
        attempts = await asyncio.to_thread(
            quarantine_node.quarantine,
            vault_path,
            meeting,
            error=error,
            models=models,
            prior_attempts=prior_attempts,
        )
    except Exception:  # noqa: BLE001 — quarantine must never crash the batch
        logger.exception("Quarantine failed for %s", meeting.source_id)
        attempts = prior_attempts + 1
    if attempts >= cap:
        review_type = "reprocess-exhausted"
        action = (
            f"Auto-retry exhausted after {attempts} attempt(s). Inspect "
            f"Raw/Failed/{meeting.fireflies_id}/ and reprocess manually."
        )
    else:
        review_type = "failed-processing"
        action = f"Quarantined to Raw/Failed/{meeting.fireflies_id}/; will auto-retry (attempt {attempts}/{cap})."
    await _queue_review_item(
        toolkit,
        report,
        review_type=review_type,
        title=f"LLM could not process {meeting.title}",
        source_id=meeting.source_id,
        issue="Meeting compilation failed (LLM could not produce valid structured output)",
        evidence=error[:300],
        recommended_action=action,
    )


async def _resolve_quarantine_items(toolkit: Any, source_id: str) -> None:
    """Mark a source's Module 17 quarantine review items ``Resolved`` after a good retry.

    Args:
        toolkit: The vault toolkit.
        source_id: The reprocessed meeting's source id.
    """
    try:
        queue_note = await toolkit.read_note("Wiki/Review Queue.md")
    except FileNotFoundError:
        return
    updated = review_queue_node.resolve_items_for_source(
        queue_note["content"],
        source_id,
        resolution="Reprocessed successfully (Module 17 auto-retry).",
        resolved_at=now_iso(),
        only_types=frozenset({"failed-processing", "reprocess-exhausted"}),
    )
    if updated != queue_note["content"]:
        await toolkit.update_note("Wiki/Review Queue.md", updated, preserve_frontmatter=False)


async def _process_one_meeting(
    agent: Any,
    toolkit: Any,
    registry: Any,
    vault_path: str,
    meeting: fetch_gate_node.GatedMeeting,
    *,
    existing_context: classify_node.ExistingContext | None = None,
    profile: IngestProfile | None = None,
) -> _MeetingOutcome:
    """Run the §27 per-meeting pipeline (steps 3-21) for one gated meeting."""
    profile = profile or _PROFILES["full"]
    writes: list[_PageWrite] = []
    review_items: list[Any] = []
    validation_ctx = ValidationContext()
    validation_ctx.source_ids = [meeting.source_id]
    # §34 source integrity "no-double-process" check (spec §2 rule 4) —
    # populated from the actual registry so it is a live assertion, not
    # structurally dead.
    validation_ctx.existing_source_ids = [r.fireflies_id for r in await registry.all_records()]
    # §2 rule 1 / §34 — every vault-relative path this function itself
    # reads or writes, so `private_accessed` is derived from actual
    # evidence (never a hardcoded constant). Entity/concept resolution
    # (Modules 10) additionally scope their own reads/writes strictly to
    # `Wiki/Entities/`/`Wiki/Concepts/` by construction (see those
    # modules' own folder constants) and are not duplicated here.
    touched_paths: list[str] = []

    # --- §13/§14 raw bundle -------------------------------------------------
    # raw_bundle.py is synchronous file I/O (hashing, shutil.move) — never
    # call it unawaited inline; dispatch to a thread so it cannot stall
    # the event loop during a batch ingest.
    await asyncio.to_thread(raw_bundle_node.write_bundle_to_incoming, vault_path, meeting)
    incoming_dir = Path(vault_path) / conf.WIKI_KB_RAW_ROOT / "Incoming"
    paired, unpaired = await asyncio.to_thread(raw_bundle_node.pair_incoming_bundles, incoming_dir)
    for group in unpaired:
        review_items.append(
            classify_node.ReviewItemDraft(
                review_type="source-pairing",
                source_id=meeting.source_id,
                issue=f"Incomplete/ambiguous bundle: {group.reason}",
                evidence=", ".join(group.paths),
            )
        )
    bundle = next((b for b in paired if b.source_id == meeting.fireflies_id), None)
    if bundle is None:
        validation_ctx.raw_files_modified = []
        return _MeetingOutcome(
            validation_passed=False,
            validation_failures=[f"raw bundle for {meeting.fireflies_id} failed to pair"],
            review_items=review_items,
        )

    hashes = await asyncio.to_thread(raw_bundle_node.hash_bundle, incoming_dir, bundle)
    pre_hash = hashes.transcript_sha256
    processed = await asyncio.to_thread(
        raw_bundle_node.move_to_processed, vault_path, incoming_dir, bundle, hashes, meeting_date=meeting.meeting_date
    )
    validation_ctx.pre_move_hashes[processed.transcript_path] = pre_hash
    validation_ctx.post_move_hashes[processed.transcript_path] = processed.hashes.transcript_sha256
    validation_ctx.raw_links = [processed.transcript_path]
    if processed.summary_path:
        validation_ctx.raw_links.append(processed.summary_path)
    validation_ctx.existing_raw_files = [p for p in (processed.transcript_path, processed.summary_path) if p]

    # --- §15 classify -----------------------------------------------------
    # Pass the vault's existing-knowledge context so the classifier can
    # match-before-create (rule #6) — without it, a variant project name
    # would create a duplicate canonical page.
    classification_result = await classify_node.run_classify(
        agent.strong_client,
        meeting,
        context=existing_context,
        allow_transcript_fallback=profile.classify_transcript_fallback,
    )
    classification = classification_result.classification
    if classification_result.review_item:
        review_items.append(classification_result.review_item)

    # §27 step 10 — once classification confidently resolves the primary
    # client/project, relocate the raw bundle out of Uncategorized/ into
    # its classified <Client>/<Project>/YYYY/MM/<source-id>/ home. Every
    # file move re-verifies its hash (raw_bundle.reclassify_move), so
    # this never risks raw immutability.
    if classification.primary_client and classification.primary_project:
        processed = await asyncio.to_thread(
            raw_bundle_node.reclassify_move,
            vault_path,
            processed,
            meeting_date=meeting.meeting_date,
            client=title_case_name(classification.primary_client),
            project=title_case_name(classification.primary_project),
        )
        validation_ctx.pre_move_hashes[processed.transcript_path] = pre_hash
        validation_ctx.post_move_hashes[processed.transcript_path] = processed.hashes.transcript_sha256
        validation_ctx.raw_links = [processed.transcript_path]
        if processed.summary_path:
            validation_ctx.raw_links.append(processed.summary_path)
        validation_ctx.existing_raw_files = [p for p in (processed.transcript_path, processed.summary_path) if p]

    meeting_date_local = (meeting.meeting_date_iso or meeting.meeting_date)[:10]
    filename = meeting_source_filename(
        meeting_date_local=date.fromisoformat(meeting_date_local), title=meeting.title, source_id=meeting.source_id
    )
    meeting_source_link = f"Wiki/Sources/Meetings/{filename[:-3]}"

    # §34 gate — everything from here on writes compiled pages that
    # must be atomically rolled back (never Raw/, which is immutable
    # regardless of outcome) if ANY step raises. Without this, a raw
    # bundle already moved to Raw/Processed/ combined with a mid-
    # pipeline exception would leave partial compiled writes in place
    # with no registry/log entry, and the fetch-gate's raw-id scan
    # would then permanently skip the source on every future run —
    # an unrecoverable, silent partial ingest.
    try:
        # --- §9/§22 contradiction detection (before destination/meeting page) -
        contradiction_links: list[str] = []
        if profile.detect_contradictions and classification.primary_project:
            project_path = _project_vault_path(classification.primary_project)
            touched_paths.append(project_path)
            try:
                existing_note = await toolkit.read_note(project_path)
                existing_state = parse_project_page(existing_note["content"])
                existing_claims = [
                    contradictions_node.ExistingClaimRef(
                        text=c.text, source=c.source, date=existing_note["frontmatter"].get("last_meeting", "")
                    )
                    for c in (*existing_state.current_decisions, *existing_state.current_requirements)
                ]
                new_claims = [meeting.summary_text] if meeting.summary_text else []
                pages = await contradictions_node.run_contradiction_detection(
                    agent.strong_client,
                    existing_claims,
                    new_claims,
                    new_claim_source=meeting_source_link,
                    new_claim_date=meeting.meeting_date,
                    affected_pages=[project_path],
                )
                for page in pages:
                    await _write_note(toolkit, page.vault_path, page.content, writes)
                    contradiction_links.append(page.vault_path)
                    validation_ctx.new_wikilinks.append(page.vault_path.removesuffix(".md"))
                    validation_ctx.existing_or_queued_pages.append(page.vault_path.removesuffix(".md"))
                    if page.review_item:
                        review_items.append(page.review_item)
            except FileNotFoundError:
                pass

        # §22 rule 6 — bare contradiction-page titles, for linking this
        # meeting's own source page and the affected project back to them.
        contradiction_titles = [Path(p).stem for p in contradiction_links]

        # --- §17 meeting page ---------------------------------------------------
        meeting_result = await meeting_page_node.run_meeting_page(
            agent.cheap_client,
            meeting,
            classification_result,
            raw_summary_path=processed.summary_path or "",
            raw_transcript_path=processed.transcript_path,
            summary_sha256=hashes.summary_sha256 or "",
            transcript_sha256=hashes.transcript_sha256,
            meeting_date_local=meeting_date_local,
            contradictions=contradiction_titles,
        )
        await _write_note(toolkit, meeting_result.vault_path, meeting_result.content, writes)
        touched_paths.append(meeting_result.vault_path)
        validation_ctx.new_wikilinks.append(meeting_result.vault_path.removesuffix(".md"))
        validation_ctx.existing_or_queued_pages.append(meeting_result.vault_path.removesuffix(".md"))
        validation_ctx.written_filenames.append(Path(meeting_result.vault_path).name)
        meeting_extraction = _extraction_from_meeting(meeting_result)

        # --- §16/§19 project reconcile / new project -----------------------------
        # Reconcile the primary project AND every additional related project.
        # A project the classifier declared relevant must receive this
        # meeting's source link + current-state update, not merely a wikilink
        # from the meeting page (which would otherwise dangle / silently drop
        # the meeting from the project's history). Only the primary project
        # carries this meeting's contradiction links (detected against ITS
        # claims); additional projects get none.
        projects_touched: list[str] = []
        reconcile_targets: list[tuple[str, list[str]]] = []
        if classification.primary_project:
            reconcile_targets.append((classification.primary_project, contradiction_titles))
        # The backfill profile reconciles the primary project only — skipping
        # the per-additional-project strong-tier reconcile call is the single
        # biggest per-meeting saving on a bulk historical import.
        if profile.reconcile_additional_projects:
            for additional_project in classification.additional_projects:
                reconcile_targets.append((additional_project, []))

        seen_projects: set[str] = set()
        for target_name, target_contradictions in reconcile_targets:
            dedup_key = title_case_name(target_name)
            if dedup_key in seen_projects:
                continue
            seen_projects.add(dedup_key)
            touched_project = await _reconcile_project(
                agent,
                toolkit,
                target_name,
                meeting=meeting,
                meeting_extraction=meeting_extraction,
                meeting_source_link=meeting_source_link,
                classification=classification,
                contradiction_titles=target_contradictions,
                writes=writes,
                validation_ctx=validation_ctx,
                review_items=review_items,
                touched_paths=touched_paths,
            )
            if touched_project:
                projects_touched.append(touched_project)

        # --- §20/§21 entities + concepts -----------------------------------------
        # Resolved in ONE cheap-tier batch call (was one strong-tier call per
        # candidate — the dominant per-meeting LLM cost). The match-before-create
        # lookup stays deterministic; only the extraction is batched. Same pages.
        if profile.resolve_entities_concepts:
            entity_candidates: list[tuple[str, str]] = [(p, "person") for p in classification.people]
            entity_candidates += [(p, "product") for p in classification.products]
            if classification.primary_client:
                entity_candidates.append((classification.primary_client, "company"))

            try:
                entity_results, concept_results = await entity_concept_batch_node.run_entities_and_concepts(
                    agent.cheap_client,
                    toolkit,
                    entity_candidates=entity_candidates,
                    concept_candidates=list(classification.concepts),
                    project_name=classification.primary_project,
                    meeting_source_link=meeting_source_link,
                    meeting_summary=meeting.summary_text or "",
                )
            except Exception as exc:
                # Best-effort enrichment: the meeting itself compiled and its
                # pages link the entities/concepts — a future meeting will create
                # the pages. Surface the failure to the Review Queue instead of
                # failing the whole meeting for a flaky enrichment call.
                logger.warning("Entity/concept batch resolve failed for %s", meeting.source_id, exc_info=True)
                entity_results, concept_results = [], []
                review_items.append(
                    classify_node.ReviewItemDraft(
                        review_type="entity-resolution-failed",
                        source_id=meeting.source_id,
                        issue="Entity/concept batch resolution failed; pages not created this run",
                        evidence=str(exc)[:300],
                    )
                )

            for entity_result in entity_results:
                if entity_result.content and entity_result.vault_path:
                    await _write_enrichment_page(
                        toolkit,
                        entity_result.vault_path,
                        entity_result.content,
                        writes=writes,
                        validation_ctx=validation_ctx,
                        touched_paths=touched_paths,
                    )
            for concept_result in concept_results:
                if concept_result.content and concept_result.vault_path:
                    await _write_enrichment_page(
                        toolkit,
                        concept_result.vault_path,
                        concept_result.content,
                        writes=writes,
                        validation_ctx=validation_ctx,
                        touched_paths=touched_paths,
                    )

        # --- §23 daily synthesis --------------------------------------------------
        daily_path = f"Diary/Daily Notes/{meeting.meeting_date}.md"
        touched_paths.append(daily_path)
        existing_daily = None
        try:
            note = await toolkit.read_note(daily_path)
            existing_daily = note["content"]
        except FileNotFoundError:
            pass
        action_item_lines = [
            f"{a.action} - {a.owner} - {a.due_date} - {classification.primary_project or 'Unknown'}"
            for a in meeting_extraction.action_items
        ]
        daily_result = await daily_node.run_daily_synthesis(
            agent.cheap_client,
            existing_content=existing_daily,
            day=meeting.meeting_date,
            meeting_source_link=meeting_source_link,
            project_name=classification.primary_project,
            new_project_updates=meeting_extraction.decisions + meeting_extraction.requirements,
            new_decisions=meeting_extraction.decisions,
            new_action_items=action_item_lines,
            new_risks=meeting_extraction.risks,
            new_contradictions_and_review=contradiction_links,
        )
        await _write_note(toolkit, daily_result.vault_path, daily_result.content, writes)
        touched_paths.append(daily_result.vault_path)

        validation_ctx.private_accessed = any(p.startswith("Private/") or p == "Private" for p in touched_paths)
        validation_ctx.obsidian_dir_modified = any(
            p.startswith(".obsidian/") or p == ".obsidian" for p in touched_paths
        )

        validation_result = validate(validation_ctx)
        return _MeetingOutcome(
            validation_passed=validation_result.passed,
            validation_failures=validation_result.failures,
            writes=writes,
            review_items=review_items,
            meeting_source_link=meeting_source_link,
            processing_mode=classification_result.processing_mode,
            projects=projects_touched,
            contradiction_links=contradiction_links,
        )
    except Exception as exc:
        logger.exception("Unhandled error compiling meeting %s; rolling back partial writes", meeting.source_id)
        await _rollback(toolkit, writes)
        return _MeetingOutcome(
            validation_passed=False,
            validation_failures=[f"Unhandled exception while compiling meeting: {exc}"],
            writes=[],
            review_items=review_items,
        )


def _extraction_from_meeting(meeting_result: Any) -> Any:
    """Recover the ``MeetingExtraction`` fields from the rendered meeting
    page's frontmatter-adjacent data — see the module note below.

    ``run_meeting_page`` does not currently return the raw
    ``MeetingExtraction`` alongside its result (spec Module 8's own
    return type is ``MeetingPageResult`` — frontmatter/filename/content
    only). Re-parsing the rendered page's Decisions/Requirements/Risks/
    Open-Questions sections back into a fresh
    :class:`~.models.MeetingExtraction` keeps this orchestrator decoupled
    from Module 8's internals (this task's own "NOT in scope: the node
    internals" boundary) at the cost of a light re-parse.
    """
    from .models import ActionItem, MeetingExtraction
    from .render.project import _parse_section

    body = meeting_result.content.split("---", 2)[-1]

    def _bullets(heading: str) -> list[str]:
        text = _parse_section(body, heading)
        return [
            line[2:].strip()
            for line in text.splitlines()
            if line.startswith("- ") and line[2:].strip().lower() not in {"none identified", "not established"}
        ]

    def _action_items(heading: str) -> list[ActionItem]:
        # ``render_action_items_table`` renders a Markdown table, not
        # bullets — parse its rows back, skipping the header, the
        # ``| --- | ... |`` separator, and the "None identified" placeholder.
        text = _parse_section(body, heading)
        items: list[ActionItem] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("|") and stripped.endswith("|")):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) != 5:
                continue
            action, owner, due_date, status, confidence = cells
            if action.lower() == "action" or action.strip("-: ") == "" or action.lower() == "none identified":
                continue
            valid_confidence: Literal["High", "Medium", "Low"] = (
                confidence if confidence in ("High", "Medium", "Low") else "Medium"  # type: ignore[assignment]
            )
            items.append(
                ActionItem(
                    action=action,
                    owner=owner or "Unknown",
                    due_date=due_date or "Unknown",
                    status=status or "Open",
                    source_confidence=valid_confidence,
                )
            )
        return items

    return MeetingExtraction(
        decisions=_bullets("Decisions"),
        requirements=_bullets("Requirements"),
        action_items=_action_items("Action Items"),
        risks=_bullets("Risks and Blockers"),
        open_questions=_bullets("Open Questions"),
    )


async def run_ingest(ctx: WikiIngestContext) -> IngestReport:
    """Run the §27 ordered ingest pipeline.

    Args:
        ctx: The run's :class:`WikiIngestContext` (``ctx.agent`` supplies
            the tiered LLM clients and MCP tool surface).

    Returns:
        The resulting :class:`IngestReport`.

    Raises:
        ValueError: If ``ctx.agent`` is not set.
    """
    if ctx.agent is None:
        raise ValueError("run_ingest: ctx.agent is required")

    from . import vault
    from .graph import build_wiki_kb_graph_toolkit, rebuild_graph_index

    agent = ctx.agent
    vault_path = conf.WIKI_KB_VAULT_PATH
    toolkit = vault.build_vault_toolkit(vault_path)
    registry = vault.build_meeting_registry(vault_path)

    # §12 startup context / §11 idempotent init.
    await vault.initialize_vault(toolkit)

    # §12/§15.1 — read existing-knowledge candidates once, so every meeting's
    # classification can match-before-create (rule #6) instead of duplicating
    # a project/entity that only differs by spelling.
    existing_context = await _build_existing_context(toolkit)

    profile = resolve_profile(ctx.profile)
    logger.info("Ingest profile: %s", profile.name)

    raw_processed_root = Path(vault_path) / conf.WIKI_KB_RAW_ROOT / "Processed"
    raw_failed_root = Path(vault_path) / conf.WIKI_KB_RAW_ROOT / "Failed"

    # Module 17 — build the retry batch (quarantined bundles with attempts < cap)
    # BEFORE the fetch, from local bytes (no Fireflies re-download). The fetch-gate
    # is told about Raw/Failed/ so those ids are treated as known and not re-fetched.
    reprocess_cap = conf.WIKI_KB_MAX_REPROCESS_ATTEMPTS
    retry_batch = await asyncio.to_thread(quarantine_node.build_retry_batch, vault_path, cap=reprocess_cap)
    retry_prior: dict[str, int] = {m.fireflies_id: prior for m, prior in retry_batch}

    # `max_new` (per-call or conf default) is the backfill chunk knob: it caps
    # NEW meetings fetched while the gate pages past already-known ones. When it
    # governs, it (not `limit`) bounds the run.
    max_new = ctx.max_new if ctx.max_new is not None else conf.WIKI_KB_MAX_NEW_PER_RUN

    gated = await fetch_gate_node.run_fetch_gate(
        agent,
        registry=registry,
        raw_processed_root=raw_processed_root,
        raw_failed_root=raw_failed_root,
        limit=ctx.limit if ctx.limit is not None else conf.WIKI_KB_INGEST_LIMIT,
        max_new=max_new,
        force_refetch=ctx.force_refetch,
        since=ctx.since,
        lookback_days=ctx.lookback_days,
    )

    # G5 — sort the WHOLE batch (freshly-fetched + Module 17 retries) oldest → newest.
    fetched = [m for m in gated if m.outcome == "fetch"]
    to_process = sorted(fetched + [m for m, _ in retry_batch], key=lambda m: m.meeting_date)
    # Bounded chunk (spec Module 6): the per-run limit applies to the COMBINED
    # fresh + retry batch, not just fresh meetings — otherwise a large retry
    # backlog would blow the cap. Oldest-first ordering means retries (older)
    # get priority; anything over the cap stays quarantined and retries next run.
    # When `max_new` governs (backfill), the fetch-gate already bounded the new
    # meetings this run, so don't also truncate here (that would drop retries).
    if max_new is None:
        effective_limit = ctx.limit if ctx.limit is not None else conf.WIKI_KB_INGEST_LIMIT
        if effective_limit is not None:
            to_process = to_process[:effective_limit]
    skipped = len([m for m in gated if m.outcome != "fetch"])

    report = IngestReport(skipped=skipped)
    all_projects_touched: set[str] = set()

    # §33 — a "duplicate-skip" (R3 permanent skip: content changed on an
    # already-known id) is an interesting event and gets its own log op,
    # distinct from the silent "skip" (already-synced, no change) case.
    for duplicate in (m for m in gated if m.outcome == "duplicate-skip"):
        entry = log_node.render_log_entry(
            op="duplicate-skip",
            timestamp=now_iso(),
            title=duplicate.title,
            fields={
                "Source ID": f"`{duplicate.source_id}`",
                "Reason": "Content changed on an already-known id (R3 — no revision workflow).",
            },
        )
        try:
            log_note = await toolkit.read_note("Wiki/log.md")
            log_content = log_note["content"]
        except FileNotFoundError:
            log_content = "# Operation Log\n\n"
        log_content = log_node.append_log_entry(log_content, entry)
        await toolkit.update_note("Wiki/log.md", log_content, preserve_frontmatter=False)

    for meeting in to_process:
        is_retry = meeting.fireflies_id in retry_prior
        prior_attempts = retry_prior.get(meeting.fireflies_id, 0)
        if is_retry:
            # _process_one_meeting re-materialises the bundle into Raw/Incoming from
            # the in-memory meeting; drop the stale quarantine dir first (the fetch-gate
            # already scanned Raw/Failed/ so this id is not re-downloaded).
            await asyncio.to_thread(quarantine_node.discard_failed_dir, vault_path, meeting.fireflies_id)

        try:
            outcome = await _process_one_meeting(
                agent, toolkit, registry, vault_path, meeting, existing_context=existing_context, profile=profile
            )
        except Exception as exc:
            logger.exception("Ingest failed for %s", meeting.source_id)
            # Module 17 — _process_one_meeting already rolled back its compiled writes;
            # quarantine the raw bundle (never mark it processed) + surface it.
            await _handle_meeting_failure(
                toolkit,
                report,
                vault_path,
                meeting,
                error=str(exc),
                prior_attempts=prior_attempts,
                cap=reprocess_cap,
            )
            continue

        if not outcome.validation_passed:
            await _rollback(toolkit, outcome.writes)
            # Module 17 — §34 failure OR compile failure: rollback (above) + quarantine
            # to Raw/Failed/ (id stays reprocessable) + queue review + no success log.
            await _handle_meeting_failure(
                toolkit,
                report,
                vault_path,
                meeting,
                error="; ".join(outcome.validation_failures) or "§34 post-operation validation failed",
                prior_attempts=prior_attempts,
                cap=reprocess_cap,
            )
            # Preserve any other review items this meeting collected before failing.
            for item in outcome.review_items:
                await _queue_review_item(
                    toolkit,
                    report,
                    review_type=item.review_type,
                    title=item.issue,
                    source_id=item.source_id,
                    issue=item.issue,
                    evidence=item.evidence,
                    recommended_action="See issue/evidence above.",
                )
            continue

        # §34 passed — post-validation bookkeeping (review items + registry +
        # log). The compiled pages are already written and the raw bundle is
        # already in Raw/Processed/, so a failure here must NOT abort the whole
        # batch (subsequent meetings would silently never process) — it is
        # caught, surfaced as an error, and the loop continues. The pages
        # remain in the vault; the raw-id gate correctly skips the meeting on
        # the next run.
        try:
            # If this was a Module 17 retry, clear its quarantine review items.
            if is_retry:
                await _resolve_quarantine_items(toolkit, meeting.source_id)

            for item in outcome.review_items:
                await _queue_review_item(
                    toolkit,
                    report,
                    review_type=item.review_type,
                    title=item.issue,
                    source_id=item.source_id,
                    issue=item.issue,
                    evidence=item.evidence,
                    recommended_action="See issue/evidence above.",
                )

            await registry.record_synced(
                fireflies_id=meeting.fireflies_id,
                note_path=Path(vault_path) / f"{outcome.meeting_source_link}.md",
                title=meeting.title,
                meeting_date=meeting.meeting_date,
                participants=meeting.participants,
                duration_minutes=meeting.duration_minutes,
                fingerprint=meeting.fingerprint or "",
                summary_fingerprint=meeting.summary_fingerprint,
                reset_analysis=False,
            )

            log_entry = log_node.render_ingest_log_entry(
                timestamp=now_iso(),
                meeting_title=meeting.title,
                source_id=meeting.source_id,
                source_page=outcome.meeting_source_link,
                projects=[_project_vault_path(p).removesuffix(".md") for p in outcome.projects],
                processing_mode=outcome.processing_mode,
                created=[w.path for w in outcome.writes if w.previous_content is None],
                updated=[w.path for w in outcome.writes if w.previous_content is not None],
                contradictions=outcome.contradiction_links,
                validation="Passed",
            )
            try:
                log_note = await toolkit.read_note("Wiki/log.md")
                log_content = log_note["content"]
            except FileNotFoundError:
                log_content = "# Operation Log\n\n"
            log_content = log_node.append_log_entry(log_content, log_entry)
            await toolkit.update_note("Wiki/log.md", log_content, preserve_frontmatter=False)
        except Exception:
            logger.exception(
                "Post-validation bookkeeping failed for %s; pages are written but "
                "registry/log may be incomplete (continuing with the batch)",
                meeting.source_id,
            )
            report.errors.append(f"{meeting.source_id}: post-validation bookkeeping failed")
            continue

        report.processed += 1
        report.created.extend(w.path for w in outcome.writes if w.previous_content is None)
        report.updated.extend(w.path for w in outcome.writes if w.previous_content is not None)
        report.contradictions.extend(outcome.contradiction_links)
        all_projects_touched.update(outcome.projects)

    # §24.1 Wiki index — rebuilt after every write operation.
    try:
        await _rebuild_wiki_index(toolkit, report)
    except Exception:
        logger.warning("Wiki index rebuild failed", exc_info=True)

    # §24.2 overview — updated only on a material change (skipped entirely by
    # the backfill profile; a single overview rebuild after the import is
    # cheaper than one strong-tier materiality check per run).
    if profile.update_overview and (report.created or report.updated):
        try:
            await _maybe_update_overview(agent.strong_client, toolkit, report)
        except Exception:
            logger.warning("Overview update check failed", exc_info=True)

    # §25 registry mirror — regenerated every ingest, regardless of per-meeting outcomes.
    try:
        await vault.regenerate_registry_mirror(toolkit, registry)
    except Exception:
        logger.warning("Registry mirror regeneration failed", exc_info=True)

    # §27 step 22 — archive (Module 14, lazily picked up once implemented).
    await _maybe_run_archive(toolkit, registry)

    # §35 change summary.
    _print_change_summary(report)

    # Derived GraphIndex/PageIndex rebuild (Module 13, D3) — never blocks.
    try:
        wiki_toolkit = await build_wiki_kb_graph_toolkit(vault_path)
        await rebuild_graph_index(wiki_toolkit, vault_path=vault_path)
    except Exception:
        logger.warning("GraphIndex rebuild failed", exc_info=True)

    return report


async def _rebuild_wiki_index(toolkit: Any, report: IngestReport) -> None:
    """§24.1 — rebuild ``Wiki/index.md`` after this run's write operations."""
    try:
        # Canonical project pages live one level nested — Projects/<Name>/
        # <Name>.md (see _project_vault_path) — so a non-recursive listing
        # of Projects/ always returns an empty set. List recursively and
        # keep only paths matching that exact canonical shape.
        listing = await toolkit.list_notes(folder="Projects", recursive=True)
    except FileNotFoundError:
        listing = {"notes": []}

    projects: list[tuple[str, str]] = []
    for note in listing.get("notes", []):
        note_path = Path(note["path"])
        if len(note_path.relative_to("Projects").parts) != 2 or note_path.stem != note_path.parent.name:
            continue
        name = note_path.stem
        try:
            project_note = await toolkit.read_note(_project_vault_path(name))
            status = project_note["frontmatter"].get("status", "unknown")
        except FileNotFoundError:
            status = "unknown"
        projects.append((name, status))

    today = now_iso()[:10]
    recently_updated = [(today, p.removesuffix(".md"), "ingested") for p in (*report.created, *report.updated)]

    index_content = indexes_node.render_wiki_index(projects, recently_updated)
    await _write_note(toolkit, "Wiki/index.md", index_content, [])


async def _maybe_update_overview(strong_client: Any, toolkit: Any, report: IngestReport) -> None:
    """§24.2 — update ``Wiki/overview.md`` only on a material change."""
    try:
        existing_note = await toolkit.read_note("Wiki/overview.md")
        existing_overview = existing_note["content"]
    except FileNotFoundError:
        existing_overview = ""

    developments = [f"Updated {p}" for p in report.created] + [f"Revised {p}" for p in report.updated]
    assessment = await indexes_node.overview_materially_changed(strong_client, existing_overview, developments)
    if assessment.materially_changed:
        updated_overview = indexes_node.render_overview(existing_overview, assessment.reason)
        await _write_note(toolkit, "Wiki/overview.md", updated_overview, [])


def _section(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- None"]


def _print_change_summary(report: IngestReport) -> None:
    """§35 — print the required final change summary."""
    status = "Completed" if report.failed == 0 else "Completed with warnings"
    lines = [
        "Operation: ingest",
        f"Status: {status}",
        "",
        "Created:",
        *_section(report.created),
        "",
        "Updated:",
        *_section(report.updated),
        "",
        "Skipped:",
        f"- {report.skipped} meeting(s)" if report.skipped else "- None",
        "",
        "Contradictions:",
        *_section(report.contradictions),
        "",
        "Review required:",
        *_section(report.review_items),
        "",
        f"Validation: {'Passed' if report.failed == 0 else f'{report.failed} failure(s)'}",
    ]
    logger.info("\n".join(lines))
