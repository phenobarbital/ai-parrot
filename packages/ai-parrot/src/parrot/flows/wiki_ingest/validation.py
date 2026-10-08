"""§34 Post-Operation Validation — the executable QA oracle (FEAT-481,
spec Module 5).

:func:`validate` covers the four integrity groups the contract's §34
defines (source / knowledge / Obsidian / operational) plus the extra
assertions spec Module 5 calls out explicitly: the §19 diff-guard (Q2),
``Private/``-never-accessed, new-wikilinks-resolve (§8.1),
Obsidian-safe-filenames (§8.2), and no-fabricated-looking-values
(rule #12).

Pipeline nodes populate a :class:`ValidationContext` with the evidence
they gathered during one operation; every field defaults to a
"nothing to check" value, so a partial context (a single node's unit
test, or an operation that only touched a subset of the vault) still
validates cleanly.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from .models import ALLOWED_PLACEHOLDER_VALUES, UNSAFE_FILENAME_CHARS, ValidationResult


class ValidationContext(BaseModel):
    """Evidence collected during one ingest/operation for §34 validation.

    Attributes:
        source_ids: Source ids (``"fireflies:<id>"``) processed this
            operation.
        existing_source_ids: Source ids already on record (registry)
            before this operation — used to catch a double-process.
        pre_move_hashes: ``{path: sha256}`` recorded before a `Raw/`
            immutable move.
        post_move_hashes: ``{path: sha256}`` recorded after the move —
            must match ``pre_move_hashes`` for the same path.
        raw_files_modified: Any raw path edited/overwritten/deleted this
            operation (must stay empty — §2 rule 2).
        raw_links: Plain-path raw provenance links referenced by pages
            written this operation.
        existing_raw_files: Raw paths that actually exist on disk —
            every entry in ``raw_links`` must resolve against this set.
        project_pages_stale: Project pages that do NOT yet reflect the
            newest supported current state (must stay empty).
        duplicate_pages: Any duplicate project/entity/concept/source page
            created this operation (must stay empty).
        unsourced_claims: Material claims lacking a source link (must
            stay empty).
        human_notes_removed: Pages whose ``## Human Notes`` section was
            altered this operation (must stay empty — §2 rule 13).
        locked_pages_modified: ``locked: true`` pages modified without an
            explicit user request this operation (must stay empty).
        new_wikilinks: Wikilink targets (page ids/paths) emitted this
            operation.
        existing_or_queued_pages: Pages that exist OR are queued for
            creation in the same operation — every ``new_wikilinks``
            entry must resolve against this set (§8.1).
        written_filenames: Filenames (basenames, no directories) written
            this operation — checked for §8.2 Obsidian-unsafe punctuation.
        unreachable_new_pages: New pages not reachable from
            ``Wiki/index.md`` (must stay empty).
        moved_files: ``{old_path: new_path}`` for renames/moves this
            operation.
        files_with_stale_inbound_links: Moved/renamed files whose inbound
            links were NOT updated by link-fixup (must stay empty —
            §8.1, ``move_note`` does not rewrite backlinks on its own).
        diff_guard_violations: Claims the reconciler's own Q2 safety net
            (``project_reconcile._apply_diff_guard``) had to reinsert
            because the LLM's draft proposal dropped them — informational
            (a warning): the reinsertion already guarantees the claim is
            present in the final rendered page.
        insufficient_evidence_fields: ``{field label: rendered value}``
            for every field the compiler flagged as insufficient-evidence
            — the rendered value must be one of
            :data:`~.models.ALLOWED_PLACEHOLDER_VALUES` (rule #12).
        registry_entries_without_success: Registry entries written for an
            operation that did NOT successfully complete (must stay
            empty).
        daily_notes_missing_for: Meeting dates lacking a daily-note update
            (must stay empty).
        review_required_items: Items flagged ``review_required`` this
            operation.
        review_queue_entries: Items actually queued to the Review Queue
            this operation — every ``review_required_items`` entry must
            appear here.
        private_accessed: ``True`` if ``Private/`` was read, listed,
            searched, indexed, moved, or traversed this operation (§2
            rule 1 — must stay ``False``).
        obsidian_dir_modified: ``True`` if ``.obsidian/`` was modified.
        obsidian_change_explicitly_requested: ``True`` when the user
            explicitly requested the ``.obsidian/`` change above.
    """

    source_ids: list[str] = Field(default_factory=list)
    existing_source_ids: list[str] = Field(default_factory=list)
    pre_move_hashes: dict[str, str] = Field(default_factory=dict)
    post_move_hashes: dict[str, str] = Field(default_factory=dict)
    raw_files_modified: list[str] = Field(default_factory=list)
    raw_links: list[str] = Field(default_factory=list)
    existing_raw_files: list[str] = Field(default_factory=list)

    project_pages_stale: list[str] = Field(default_factory=list)
    duplicate_pages: list[str] = Field(default_factory=list)
    unsourced_claims: list[str] = Field(default_factory=list)
    human_notes_removed: list[str] = Field(default_factory=list)
    locked_pages_modified: list[str] = Field(default_factory=list)

    new_wikilinks: list[str] = Field(default_factory=list)
    existing_or_queued_pages: list[str] = Field(default_factory=list)
    written_filenames: list[str] = Field(default_factory=list)
    unreachable_new_pages: list[str] = Field(default_factory=list)
    moved_files: dict[str, str] = Field(default_factory=dict)
    files_with_stale_inbound_links: list[str] = Field(default_factory=list)

    diff_guard_violations: list[str] = Field(default_factory=list)
    insufficient_evidence_fields: dict[str, str] = Field(default_factory=dict)

    registry_entries_without_success: list[str] = Field(default_factory=list)
    daily_notes_missing_for: list[str] = Field(default_factory=list)
    review_required_items: list[str] = Field(default_factory=list)
    review_queue_entries: list[str] = Field(default_factory=list)

    private_accessed: bool = False
    obsidian_dir_modified: bool = False
    obsidian_change_explicitly_requested: bool = False


def _source_integrity(ctx: ValidationContext, failures: list[str]) -> None:
    """§34 "Source integrity" group."""
    duplicate_ids = [sid for sid, count in Counter(ctx.source_ids).items() if count > 1]
    for sid in duplicate_ids:
        failures.append(f"source integrity: source_id {sid!r} is not unique within this operation")
    for sid in ctx.source_ids:
        if sid in ctx.existing_source_ids:
            failures.append(f"source integrity: source_id {sid!r} was already processed (no-double-process, §2 r4)")

    for path, pre_hash in ctx.pre_move_hashes.items():
        post_hash = ctx.post_move_hashes.get(path)
        if post_hash != pre_hash:
            failures.append(
                f"source integrity: pre/post-move hash mismatch for {path!r} " f"(pre={pre_hash!r} post={post_hash!r})"
            )

    for path in ctx.raw_files_modified:
        failures.append(f"source integrity: raw file {path!r} was edited/overwritten/deleted (§2 r2)")

    for link in ctx.raw_links:
        if link not in ctx.existing_raw_files:
            failures.append(f"source integrity: raw link {link!r} does not point to an existing file")


def _knowledge_integrity(ctx: ValidationContext, failures: list[str], warnings: list[str]) -> None:
    """§34 "Knowledge integrity" group (+ Q2 diff-guard).

    ``diff_guard_violations`` is a **warning**, not a failure: by the
    time this context is built, ``project_reconcile.py``'s
    ``_apply_diff_guard`` has already reinserted any claim the LLM's
    draft proposal dropped — the Q2 invariant ("no claim dropped while a
    live source still supports it") holds in the *final* rendered page
    by construction. The list exists so an operator can see the LLM
    needed correcting, not to block/roll back an otherwise-successful
    reconcile that self-healed exactly as designed.
    """
    for path in ctx.project_pages_stale:
        failures.append(f"knowledge integrity: project page {path!r} does not reflect the newest current state")
    for path in ctx.duplicate_pages:
        failures.append(f"knowledge integrity: duplicate page created at {path!r}")
    for claim in ctx.unsourced_claims:
        failures.append(f"knowledge integrity: material claim lacks a source link: {claim!r}")
    for path in ctx.human_notes_removed:
        failures.append(f"knowledge integrity: ## Human Notes altered on {path!r} (§2 r13)")
    for path in ctx.locked_pages_modified:
        failures.append(f"knowledge integrity: locked page {path!r} modified without explicit request (§2 r13)")
    for claim in ctx.diff_guard_violations:
        warnings.append(
            f"knowledge integrity: project reconcile diff-guard (Q2) reinserted a claim "
            f"the draft proposal dropped: {claim!r}"
        )


def _obsidian_integrity(ctx: ValidationContext, failures: list[str]) -> None:
    """§34 "Obsidian integrity" group (+ §8.1/§8.2 assertions)."""
    for link in ctx.new_wikilinks:
        if link not in ctx.existing_or_queued_pages:
            failures.append(
                f"obsidian integrity: dangling wikilink [[{link}]] does not resolve "
                f"and is not queued for creation in the same operation (§8.1)"
            )
    for filename in ctx.written_filenames:
        bad_chars = sorted(UNSAFE_FILENAME_CHARS.intersection(filename))
        if bad_chars:
            failures.append(
                f"obsidian integrity: filename {filename!r} contains Obsidian-unsafe "
                f"characters {bad_chars!r} (§8.2)"
            )
    for path in ctx.unreachable_new_pages:
        failures.append(f"obsidian integrity: new page {path!r} is not reachable from Wiki/index.md")
    for old_path in ctx.moved_files:
        if old_path in ctx.files_with_stale_inbound_links:
            failures.append(
                f"obsidian integrity: moved file {old_path!r} has inbound links that "
                f"were not updated (§8.1 link-fixup)"
            )


def _operational_integrity(ctx: ValidationContext, failures: list[str]) -> None:
    """§34 "Operational integrity" group (+ Private/ boundary, rule #12)."""
    for entry in ctx.registry_entries_without_success:
        failures.append(f"operational integrity: registry entry {entry!r} written for a non-successful operation")
    for date in ctx.daily_notes_missing_for:
        failures.append(f"operational integrity: daily note not updated for meeting date {date!r}")
    for item in ctx.review_required_items:
        if item not in ctx.review_queue_entries:
            failures.append(f"operational integrity: review-required item {item!r} was not queued (§26)")
    if ctx.private_accessed:
        failures.append("operational integrity: Private/ was accessed (§2 rule 1)")
    if ctx.obsidian_dir_modified and not ctx.obsidian_change_explicitly_requested:
        failures.append("operational integrity: .obsidian/ was modified without an explicit request (§2 rule 14)")

    for label, value in ctx.insufficient_evidence_fields.items():
        if value not in ALLOWED_PLACEHOLDER_VALUES:
            failures.append(
                f"operational integrity: {label!r} lacks evidence but rendered "
                f"{value!r} instead of Unknown/Not established/Requires review (rule #12)"
            )


def validate(ctx: ValidationContext) -> ValidationResult:
    """Run the full §34 Post-Operation Validation checklist.

    Args:
        ctx: The :class:`ValidationContext` evidence gathered during one
            ingest/initialization/archive/lint/query/graph operation.

    Returns:
        A :class:`~.models.ValidationResult`. ``passed`` is ``True`` only
        when every check in every group passes — per §34, a failing
        operation must roll back its compiled changes (never raw), queue
        a review item, and write no success registry/log entry.
    """
    failures: list[str] = []
    warnings: list[str] = []
    _source_integrity(ctx, failures)
    _knowledge_integrity(ctx, failures, warnings)
    _obsidian_integrity(ctx, failures)
    _operational_integrity(ctx, failures)
    return ValidationResult(passed=not failures, failures=failures, warnings=warnings)
