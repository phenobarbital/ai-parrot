"""Consistent decision inventory snapshot and eligibility predicate (FEAT-784 M5)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from parrot.knowledge.wiki.decisions.approvals import ApprovalAdapter, ApprovalManifest
from parrot.knowledge.wiki.decisions.codec import canonical_json
from parrot.knowledge.wiki.decisions.models import (
    APPROVAL_UNVERIFIED,
    SNAPSHOT_UNSTABLE,
    SUPERSESSION_INVALID,
    DecisionDiagnostic,
    DecisionError,
    DecisionRecord,
    DecisionRef,
    _Strict,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy
from parrot.knowledge.wiki.store import BaseWikiStore

RULES_VERSION = 1
BATCH_MARKER_CATEGORY = "adr_batch"

logger = logging.getLogger(__name__)


def batch_marker_id(batch_id: str) -> str:
    """Return the page id for a batch's visibility marker."""
    return f"adr-batch:{batch_id}"


def record_hash(record: DecisionRecord) -> str:
    """Return the codec's content hash for a decision record."""
    return hashlib.sha1(canonical_json(record).encode("utf-8")).hexdigest()  # noqa: S324


class SnapshotManifest(_Strict):
    """Every input on which an inventory evaluation depended."""

    inventory: dict[str, str]
    taxonomy_digest: str
    approvals_digest: str
    structural_revision: str
    rules_version: int
    config_digest: str


def is_eligible(record: DecisionRecord, *, approved_batches: frozenset[str]) -> bool:
    """Return whether a record is an authoritative active decision."""
    if record.origin != "documented" or record.source_status != "accepted":
        return False
    if record.review_status == "rejected" or record.lifecycle != "active":
        return False
    if record.batch_id is None:
        return record.decision_id.startswith("adr:doc:")
    return record.batch_id in approved_batches


class InventorySnapshot:
    """One consistent read of decision inventory, taxonomy, and approvals."""

    def __init__(
        self,
        eligible: list[DecisionRecord],
        manifest: SnapshotManifest,
        diagnostics: list[DecisionDiagnostic],
        heads: dict[str, DecisionRef],
    ) -> None:
        self.eligible = eligible
        self.manifest = manifest
        self.diagnostics = diagnostics
        self._heads = heads

    @classmethod
    async def take(
        cls,
        repo: DecisionRepository,
        taxonomy: Taxonomy,
        approvals: ApprovalManifest,
        adapter: ApprovalAdapter,
        structural_revision: str,
        *,
        store: BaseWikiStore,
        root: Path,
        config_digest: str,
    ) -> "InventorySnapshot":
        """Take a two-phase snapshot, failing when its pages change mid-read."""
        diagnostics: list[DecisionDiagnostic] = []
        approved, marker_states = await cls._approved_batches(approvals, adapter, store, root, diagnostics)
        records = await repo.inventory()
        diagnostics.extend(repo.last_diagnostics)
        hashes = {record.decision_id: record_hash(record) for record in records}
        candidates = [record for record in records if is_eligible(record, approved_batches=approved)]
        eligible, heads = cls._validate_supersession(candidates, records, diagnostics)

        if await store.page_hashes(sorted(hashes)) != hashes:
            raise DecisionError(SNAPSHOT_UNSTABLE, "decision inventory changed while reading")
        if await cls._marker_states(store, marker_states) != marker_states:
            raise DecisionError(SNAPSHOT_UNSTABLE, "batch visibility markers changed while reading")

        manifest = SnapshotManifest(
            inventory=hashes,
            taxonomy_digest=taxonomy.digest(),
            approvals_digest=approvals.digest(),
            structural_revision=structural_revision,
            rules_version=RULES_VERSION,
            config_digest=config_digest,
        )
        return cls(sorted(eligible, key=lambda record: record.decision_id), manifest, diagnostics, heads)

    @staticmethod
    async def _marker_state(store: BaseWikiStore, batch_id: str) -> str:
        """Read one marker state, treating absent or malformed markers as unpublished."""
        page = await store.get_page(batch_marker_id(batch_id), include_body=True)
        if page is None or page.get("category") != BATCH_MARKER_CATEGORY:
            return ""
        try:
            body = json.loads(page.get("body") or "")
        except (TypeError, json.JSONDecodeError):
            return ""
        state = body.get("state") if isinstance(body, dict) else None
        return state if isinstance(state, str) else ""

    @classmethod
    async def _marker_states(cls, store: BaseWikiStore, states: dict[str, str]) -> dict[str, str]:
        """Re-read the marker states used during approval evaluation."""
        return {batch_id: await cls._marker_state(store, batch_id) for batch_id in sorted(states)}

    @classmethod
    async def _approved_batches(
        cls,
        approvals: ApprovalManifest,
        adapter: ApprovalAdapter,
        store: BaseWikiStore,
        root: Path,
        diagnostics: list[DecisionDiagnostic],
    ) -> tuple[frozenset[str], dict[str, str]]:
        """Return verified-and-published batches and their observed marker states."""
        approved: set[str] = set()
        marker_states: dict[str, str] = {}
        for entry in approvals.entries:
            if entry.kind not in {"spec", "seed"}:
                continue
            spec_path = root / entry.spec_path
            if not spec_path.is_file():
                diagnostics.append(
                    DecisionDiagnostic(
                        code=APPROVAL_UNVERIFIED,
                        message=f"approved spec is missing: {entry.spec_path}",
                        path=entry.spec_path,
                    )
                )
                marker_states[entry.batch_id] = await cls._marker_state(store, entry.batch_id)
                continue
            verified, verification_diagnostics = await adapter.verify(
                entry, spec_text=spec_path.read_text(encoding="utf-8")
            )
            diagnostics.extend(verification_diagnostics)
            state = await cls._marker_state(store, entry.batch_id)
            marker_states[entry.batch_id] = state
            if verified and state == "published":
                approved.add(entry.batch_id)
        return frozenset(approved), marker_states

    @staticmethod
    def _validate_supersession(
        candidates: list[DecisionRecord],
        records: list[DecisionRecord],
        diagnostics: list[DecisionDiagnostic],
    ) -> tuple[list[DecisionRecord], dict[str, DecisionRef]]:
        """Validate full-replacement supersession edges without repairing invalid ones."""
        all_records = {record.decision_id: record for record in records}
        eligible_by_id = {record.decision_id: record for record in candidates}
        valid_edges: dict[str, set[str]] = {}
        invalid_successors: set[str] = set()

        def invalid(successor: DecisionRecord, predecessor_id: str, message: str) -> None:
            diagnostics.append(
                DecisionDiagnostic(
                    code=SUPERSESSION_INVALID,
                    message=f"{successor.decision_id} -> {predecessor_id}: {message}",
                    decision_id=successor.decision_id,
                )
            )
            invalid_successors.add(successor.decision_id)

        for successor in candidates:
            for reference in successor.supersedes_refs:
                predecessor = all_records.get(reference.decision_id)
                if predecessor is None:
                    invalid(successor, reference.decision_id, "predecessor does not exist")
                    continue
                if predecessor.revision != reference.revision:
                    invalid(successor, reference.decision_id, "predecessor revision does not match")
                    continue
                if predecessor.decision_id not in eligible_by_id:
                    active = ", ".join(sorted(eligible_by_id)) or "none"
                    invalid(successor, reference.decision_id, f"predecessor is historical; active heads: {active}")
                    continue
                predecessor_targets = sorted(target.target_id for target in predecessor.targets)
                successor_targets = sorted(target.target_id for target in successor.targets)
                if predecessor_targets != successor_targets:
                    invalid(successor, reference.decision_id, "canonical target sets differ")
                    continue
                valid_edges.setdefault(predecessor.decision_id, set()).add(successor.decision_id)

        for predecessor_id, successors in valid_edges.items():
            if len(successors) > 1:
                for successor_id in successors:
                    invalid(eligible_by_id[successor_id], predecessor_id, "multiple eligible successors")

        valid_edges = {
            predecessor_id: {successor_id for successor_id in successors if successor_id not in invalid_successors}
            for predecessor_id, successors in valid_edges.items()
        }
        valid_edges = {predecessor_id: successors for predecessor_id, successors in valid_edges.items() if successors}

        visiting: set[str] = set()
        visited: set[str] = set()
        cycle_nodes: set[str] = set()

        def visit(node_id: str, trail: list[str]) -> None:
            if node_id in visiting:
                cycle_nodes.update(trail[trail.index(node_id) :])
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            for successor_id in valid_edges.get(node_id, set()):
                visit(successor_id, [*trail, successor_id])
            visiting.remove(node_id)
            visited.add(node_id)

        for candidate in candidates:
            visit(candidate.decision_id, [candidate.decision_id])
        if cycle_nodes:
            names = ", ".join(sorted(cycle_nodes))
            for node_id in sorted(cycle_nodes):
                invalid(eligible_by_id[node_id], node_id, f"cycle includes {names}")
            valid_edges = {
                predecessor_id: {successor_id for successor_id in successors if successor_id not in cycle_nodes}
                for predecessor_id, successors in valid_edges.items()
                if predecessor_id not in cycle_nodes
            }

        successor_for = {predecessor_id: next(iter(successors)) for predecessor_id, successors in valid_edges.items()}
        heads: dict[str, DecisionRef] = {}

        def resolve(decision_id: str) -> DecisionRef:
            successor_id = successor_for.get(decision_id)
            if successor_id is None:
                record = eligible_by_id[decision_id]
                return DecisionRef(decision_id=record.decision_id, revision=record.revision)
            return resolve(successor_id)

        for candidate in candidates:
            heads[candidate.decision_id] = resolve(candidate.decision_id)
        superseded = set(successor_for)
        return [candidate for candidate in candidates if candidate.decision_id not in superseded], heads

    def effective_head(self, decision_id: str) -> DecisionRef | None:
        """Return the effective record for a decision, if it participated in the snapshot."""
        return self._heads.get(decision_id)

    def governing(self, about: set[str], scope_ids: set[str]) -> list[DecisionRecord]:
        """Return all eligible decisions applicable by domain, target, or explicit reference."""
        applicable = {
            record.decision_id: record
            for record in self.eligible
            if set(record.about).intersection(about)
            or any(target.target_id in scope_ids for target in record.targets)
            or record.decision_id in scope_ids
        }
        return [applicable[decision_id] for decision_id in sorted(applicable)]
