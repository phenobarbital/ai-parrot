"""Consequence evaluation for spec-declared decisions (FEAT-784 Module 6).

This module half (TASK-5004) is pure: report models, finding fingerprints,
spec canonicalization and the two digests. The evaluator lives below the
``# --- evaluator (TASK-5005) ---`` marker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from parrot.knowledge.wiki.decisions.approvals import ApprovalAdapter, ApprovalManifest
from parrot.knowledge.wiki.decisions.codec import spec_decision_id
from parrot.knowledge.wiki.decisions.evidence import verify_freshness
from parrot.knowledge.wiki.decisions.inventory import RULES_VERSION, InventorySnapshot, SnapshotManifest
from parrot.knowledge.wiki.decisions.models import (
    ADR_SOURCE_UNAVAILABLE,
    APPROVAL_MANIFEST_INVALID,
    AUDIT_NOT_CONFIGURED,
    SCOPE_INCOMPLETE,
    SNAPSHOT_UNSTABLE,
    SPEC_BLOCK_MISSING,
    SPEC_INVALID_ID,
    SUPERSESSION_INVALID,
    TARGET_FOREIGN,
    TARGET_UNRESOLVED,
    TAXONOMY_INVALID,
    WAIVER_INVALID,
    DecisionConfig,
    DecisionDiagnostic,
    DecisionError,
    DecisionRecord,
    DecisionRef,
    _Strict,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.scope import ResolvedTarget, TargetResolver
from parrot.knowledge.wiki.decisions.spec_entries import (
    ConflictWaiver,
    SpecDecisionEntry,
    SpecDecisionsBlock,
    canonical_block_bytes,
    parse_spec_decisions,
)
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.service import BlastRadiusOutput, StructuralService

Status = Literal["pass", "skipped", "conflict", "invalid", "incomplete"]
FindingKind = Literal["contradiction", "potential-conflict", "possible-supersession", "blast-radius", "evidence-gap"]

#: Exit matrix (spec G5, AC11). Public contract — never renumber.
EXIT_CODES: dict[str, int] = {"pass": 0, "skipped": 0, "conflict": 1, "invalid": 2, "incomplete": 3}
_PRECEDENCE: tuple[str, ...] = ("invalid", "incomplete", "conflict", "pass")
GENERATED_HEADINGS: tuple[str, ...] = ("## Governing Decisions", "## Consequences")


def _canonical(obj: Any) -> bytes:
    """Return deterministic JSON bytes mirroring ``codec.canonical_json``."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    """Return the prefixed SHA-256 digest for ``data``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


class CoverageSummary(_Strict):
    """What the evaluation could and could not see."""

    subsystems: list[str] = Field(default_factory=list)
    unmapped_tags: list[str] = Field(default_factory=list)
    targets_resolved: int = 0
    targets_total: int = 0
    impact_complete: bool = True
    inventory_complete: bool = True
    omitted_ids: list[str] = Field(default_factory=list)


class Finding(_Strict):
    """One stable, fingerprinted consequence finding."""

    kind: FindingKind
    rule_version: int
    fingerprint: str
    participants: list[DecisionRef] = Field(default_factory=list)
    scope: list[str] = Field(default_factory=list)
    blocking: bool = False
    waived_by: str | None = None
    message: str = ""


class GoverningEntry(_Strict):
    """One eligible decision as shown in ``## Governing Decisions``."""

    decision_id: str
    revision: int
    title: str = ""
    statement: str = ""
    normative: str | None = None
    about: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    rationale: str = ""
    consequences: str = ""
    supersedes: list[DecisionRef] = Field(default_factory=list)
    freshness: Literal["current", "stale", "missing", "unverified"] = "unverified"
    source_path: str | None = None


class GoverningDossier(_Strict):
    """The complete governing set; the token budget applies to rendering only."""

    entries: list[GoverningEntry] = Field(default_factory=list)
    omitted_ids: list[str] = Field(default_factory=list)
    searched_subsystems: list[str] = Field(default_factory=list)
    empty_plane: bool = False
    truncated: bool = False
    snapshot: SnapshotManifest | None = None


class ConsequenceReport(_Strict):
    """Result of evaluating one spec."""

    status: Status
    exit_code: int
    input_digest: str = ""
    evaluation_digest: str = ""
    snapshot: SnapshotManifest | None = None
    findings: list[Finding] = Field(default_factory=list)
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)
    coverage: CoverageSummary = Field(default_factory=CoverageSummary)


def finding_fingerprint(kind: str, rule_version: int, participants: list[DecisionRef], scope: list[str]) -> str:
    """Return the stable fingerprint for one finding's identity fields."""
    payload = {
        "kind": kind,
        "rule_version": rule_version,
        "participants": sorted([participant.decision_id, participant.revision] for participant in participants),
        "scope": sorted(scope),
    }
    return _sha256(_canonical(payload))


def canonicalize_spec(text: str) -> bytes:
    """Strip generated sections and status, normalizing Markdown to UTF-8 bytes."""
    normalized_lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    retained: list[str] = []
    index = 0
    while index < len(normalized_lines):
        line = normalized_lines[index]
        if line in GENERATED_HEADINGS:
            index += 1
            while index < len(normalized_lines) and not normalized_lines[index].startswith("## "):
                index += 1
            continue
        if re.match(r"^\*\*Status\*\*:", line):
            index += 1
            continue
        retained.append(line)
        index += 1

    canonical_lines: list[str] = []
    for line in retained:
        if not line:
            if canonical_lines and canonical_lines[-1]:
                canonical_lines.append("")
            continue
        canonical_lines.append(line)
    if canonical_lines and not canonical_lines[-1]:
        canonical_lines.pop()
    return "\n".join(canonical_lines).encode("utf-8")


def input_digest(
    canonical_spec: bytes,
    block: bytes,
    waivers: bytes,
    config_digest: str,
    manifest: SnapshotManifest | None,
) -> str:
    """Return the digest of every input the evaluation reads."""
    payload = {
        "spec": hashlib.sha256(canonical_spec).hexdigest(),
        "block": hashlib.sha256(block).hexdigest(),
        "waivers": hashlib.sha256(waivers).hexdigest(),
        "config": config_digest,
        "manifest": None if manifest is None else manifest.model_dump(mode="json"),
    }
    return _sha256(_canonical(payload))


def evaluation_digest(input_digest_value: str, findings: list[Finding]) -> str:
    """Return the digest of inputs and canonical findings, independent of input order."""
    canonical_findings = sorted(
        (finding.model_dump(mode="json") for finding in findings),
        key=lambda finding: (finding["kind"], finding["fingerprint"]),
    )
    return _sha256(_canonical({"input": input_digest_value, "findings": canonical_findings}))


def status_precedence(statuses: list[str]) -> str:
    """Return the highest status: invalid, incomplete, conflict, then pass."""
    for status in _PRECEDENCE:
        if status in statuses:
            return status
    return "pass"


# --- evaluator (TASK-5005) ---

_IMPACT_RELATIONS = ["calls", "extends", "implements", "uses"]
_OPPOSED: dict[str, frozenset[str]] = {
    "forbids": frozenset({"requires", "constrains"}),
    "requires": frozenset({"forbids"}),
    "constrains": frozenset({"forbids"}),
}
#: Diagnostics that make a report ``invalid`` (AC7, AC8, AC19, parser faults).
_INVALID_CODES = frozenset(
    {
        AUDIT_NOT_CONFIGURED,
        TARGET_UNRESOLVED,
        TARGET_FOREIGN,
        SUPERSESSION_INVALID,
        TAXONOMY_INVALID,
        APPROVAL_MANIFEST_INVALID,
        ADR_SOURCE_UNAVAILABLE,
    }
)
#: Snapshot diagnostics that only explain why a record is not eligible.
_INFORMATIONAL_SNAPSHOT_PREFIX = "APPROVAL_"
_TARGET_ID = re.compile(r"\b(?:sym|file|dir):[A-Za-z0-9_./#\-]+")


def audit_configured(taxonomy_path: Path, approvals_path: Path) -> bool:
    """Decision audit is configured when the taxonomy OR the approvals manifest exists (spec §2 portability)."""
    return taxonomy_path.is_file() or approvals_path.is_file()


def _frontmatter(text: str) -> tuple[list[str], list[str]]:
    """Return ``(projects, tags)`` from a leading YAML frontmatter block; never raises."""
    if not text.startswith("---"):
        return [], []
    lines = text.splitlines()
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return [], []
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return [], []
    if not isinstance(data, dict):
        return [], []

    def _strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if isinstance(item, (str, int))]
        return []

    return _strings(data.get("projects")), _strings(data.get("tags"))


def _contract_ids(text: str) -> set[str]:
    """Return exact typed target ids cited in the spec's Codebase Contract section."""
    ids: set[str] = set()
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = "Codebase Contract" in line
            continue
        if inside:
            ids.update(match.rstrip(".") for match in _TARGET_ID.findall(line))
    return ids


def _ref_key(refs: list[DecisionRef]) -> list[tuple[str, int]]:
    """Return a canonical, order-independent participant key."""
    return sorted((ref.decision_id, ref.revision) for ref in refs)


def _statuses_for(diagnostics: list[DecisionDiagnostic]) -> list[str]:
    """Map diagnostics to the statuses they force (AC11)."""
    statuses: list[str] = []
    for diagnostic in diagnostics:
        if diagnostic.code in _INVALID_CODES or (
            diagnostic.code.startswith("SPEC_") and diagnostic.code != SPEC_BLOCK_MISSING
        ):
            statuses.append("invalid")
    return statuses


class ConsequenceService:
    """Deterministic spec-decision evaluator. Zero LLM calls (AC1).

    ``structural`` MUST be built with ``read_repair=False`` (spec S6) so an
    evaluation never rescans or mutates the plane. A read-repairing service is
    reported with a ``SNAPSHOT_UNSTABLE`` diagnostic and an ``incomplete``
    status rather than trusted.
    """

    def __init__(
        self,
        store: BaseWikiStore,
        root: Path,
        config: DecisionConfig,
        structural: StructuralService,
        *,
        taxonomy_path: Path,
        approvals_path: Path,
        adapter: ApprovalAdapter,
    ) -> None:
        """Bind the read surfaces one evaluation consults.

        Args:
            store: Wiki plane holding ADR and structural pages.
            root: Repository root (confines targets and evidence).
            config: Decision configuration (its digest enters the manifest).
            structural: Structural service built with ``read_repair=False``.
            taxonomy_path: ``sdd/taxonomy/subsystems.yaml``.
            approvals_path: ``sdd/decisions/approvals.jsonl``.
            adapter: Trust check for approval entries.
        """
        self.store, self.root, self.config, self.structural = store, root, config, structural
        self.taxonomy_path, self.approvals_path, self.adapter = taxonomy_path, approvals_path, adapter
        self.resolver = TargetResolver(store, root, structural)
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------ evaluate

    async def evaluate(self, spec_path: Path, *, mode: Literal["preview", "replay"] = "preview") -> ConsequenceReport:
        """Evaluate one spec into a report.

        Never raises for spec/content faults: status ``invalid``/``incomplete``
        carries diagnostics. Precedence invalid > incomplete > conflict > pass;
        ``skipped`` only when the repo is unconfigured and no block is declared.

        Args:
            spec_path: Spec path, relative to ``root`` (or absolute).
            mode: ``preview`` compares against the live plane; ``replay``
                excludes the spec's own already-approved batch (AC12).

        Returns:
            The fingerprinted, digested report.
        """
        rel = spec_path.as_posix()
        try:
            text = await asyncio.to_thread((self.root / spec_path).read_text, encoding="utf-8")
        except OSError as exc:
            diagnostic = DecisionDiagnostic(code=ADR_SOURCE_UNAVAILABLE, message=f"cannot read spec: {exc}", path=rel)
            return self._finish("invalid", "", None, [], None, [], [diagnostic], CoverageSummary())
        block, waivers, parsed = parse_spec_decisions(text, source_path=rel)
        diagnostics = list(parsed)
        has_block = block is not None or any(d.code != SPEC_BLOCK_MISSING for d in diagnostics)
        if not audit_configured(self.taxonomy_path, self.approvals_path):
            if not has_block:
                return ConsequenceReport(status="skipped", exit_code=EXIT_CODES["skipped"])
            diagnostics.append(
                DecisionDiagnostic(
                    code=AUDIT_NOT_CONFIGURED,
                    message="spec declares decisions but decision audit is not configured",
                    path=rel,
                )
            )
            return self._finish("invalid", text, block, waivers, None, [], diagnostics, CoverageSummary())

        try:
            taxonomy = Taxonomy.load(self.taxonomy_path)
            approvals = ApprovalManifest.load(self.approvals_path)
        except DecisionError as exc:
            diagnostics.append(DecisionDiagnostic(code=exc.code, message=exc.message, path=rel))
            return self._finish(
                status_precedence(_statuses_for(diagnostics)),
                text,
                block,
                waivers,
                None,
                [],
                diagnostics,
                CoverageSummary(),
            )

        coverage = CoverageSummary()
        projects, tags = _frontmatter(text)
        coverage.subsystems = taxonomy.map_projects(projects, tags)
        coverage.unmapped_tags = taxonomy.unmapped(tags)

        resolved: dict[str, ResolvedTarget] = {}
        impacts: dict[str, BlastRadiusOutput] = {}
        if block is not None:
            self._validate_about(block, taxonomy, diagnostics, rel)
            resolved = await self._resolve_targets(block, diagnostics, coverage, rel)
            impacts = await self._impacts(resolved, coverage, diagnostics, rel)
        if getattr(self.structural, "_read_repair", False):
            coverage.impact_complete = False
            diagnostics.append(
                DecisionDiagnostic(
                    code=SNAPSHOT_UNSTABLE,
                    message="structural service has read_repair enabled; the plane may change during evaluation",
                    path=rel,
                )
            )

        try:
            snapshot = await InventorySnapshot.take(
                DecisionRepository(self.store, self.config.max_records),
                taxonomy,
                approvals,
                self.adapter,
                await self._structural_revision(resolved, impacts, diagnostics, coverage, rel),
                store=self.store,
                root=self.root,
                config_digest=self._config_digest(),
            )
        except DecisionError as exc:
            diagnostics.append(DecisionDiagnostic(code=exc.code, message=exc.message, path=rel))
            coverage.inventory_complete = False
            statuses = _statuses_for(diagnostics) + ["incomplete"]
            return self._finish(status_precedence(statuses), text, block, waivers, None, [], diagnostics, coverage)

        for diagnostic in snapshot.diagnostics:
            diagnostics.append(diagnostic)
            if diagnostic.code != SUPERSESSION_INVALID and not diagnostic.code.startswith(
                _INFORMATIONAL_SNAPSHOT_PREFIX
            ):
                # decode / unsupported-schema faults: the inventory is not fully readable (AC11)
                coverage.inventory_complete = False

        findings: list[Finding] = []
        if block is not None:
            comparison = self._baseline(block, snapshot, mode, diagnostics, rel)
            findings = await self._judge(
                block,
                waivers,
                snapshot,
                resolved,
                coverage,
                comparison=comparison,
                impacts=impacts,
                approvals=approvals,
                text=text,
                diagnostics=diagnostics,
                rel=rel,
                taxonomy=taxonomy,
            )

        statuses = _statuses_for(diagnostics)
        statuses.append("conflict" if any(f.blocking and f.waived_by is None for f in findings) else "pass")
        if not (coverage.impact_complete and coverage.inventory_complete):
            statuses.append("incomplete")
        return self._finish(
            status_precedence(statuses), text, block, waivers, snapshot.manifest, findings, diagnostics, coverage
        )

    def _config_digest(self) -> str:
        """Digest of the effective decision configuration."""
        return _sha256(_canonical(self.config.model_dump(mode="json")))

    def _finish(self, status, text, block, waivers, manifest, findings, diagnostics, coverage) -> ConsequenceReport:
        """Compute digests and assemble the report (pure)."""
        block_bytes = canonical_block_bytes(block) if block is not None else b""
        waiver_bytes = json.dumps(
            [w.model_dump(mode="json") for w in waivers], sort_keys=True, separators=(",", ":")
        ).encode()
        idig = input_digest(canonicalize_spec(text), block_bytes, waiver_bytes, self._config_digest(), manifest)
        ordered = sorted(findings, key=lambda f: (f.kind, f.fingerprint))
        return ConsequenceReport(
            status=status,
            exit_code=EXIT_CODES[status],
            input_digest=idig,
            evaluation_digest=evaluation_digest(idig, ordered),
            snapshot=manifest,
            findings=ordered,
            diagnostics=sorted(diagnostics, key=lambda d: (d.code, d.path or "", d.decision_id or "", d.message)),
            coverage=coverage,
        )

    # ------------------------------------------------------------ validation

    @staticmethod
    def _validate_about(
        block: SpecDecisionsBlock, taxonomy: Taxonomy, diagnostics: list[DecisionDiagnostic], rel: str
    ) -> None:
        """Every ``about`` id must be a taxonomy id; suggestions never rewrite it."""
        known = taxonomy.ids()
        for entry in block.entries:
            decision_id = spec_decision_id(block.document_id, entry.id)
            for about in entry.about:
                if about in known:
                    continue
                suggestions = taxonomy.closest(about)
                hint = f"; did you mean: {', '.join(suggestions)}" if suggestions else ""
                diagnostics.append(
                    DecisionDiagnostic(
                        code=SPEC_INVALID_ID,
                        message=f"unknown subsystem {about!r} in about{hint}",
                        path=rel,
                        decision_id=decision_id,
                    )
                )

    async def _resolve_targets(
        self,
        block: SpecDecisionsBlock,
        diagnostics: list[DecisionDiagnostic],
        coverage: CoverageSummary,
        rel: str,
    ) -> dict[str, ResolvedTarget]:
        """Resolve every distinct target exactly (AC7)."""
        owners: dict[str, str] = {}
        for entry in block.entries:
            for target_id in entry.targets:
                owners.setdefault(target_id, spec_decision_id(block.document_id, entry.id))
        resolved: dict[str, ResolvedTarget] = {}
        coverage.targets_total = len(owners)
        for target_id in sorted(owners):
            result, target_diagnostics = await self.resolver.resolve(target_id)
            for diagnostic in target_diagnostics:
                diagnostics.append(diagnostic.model_copy(update={"path": rel, "decision_id": owners[target_id]}))
            if result is None:
                continue
            resolved[target_id] = result
            if result.state in ("resolved", "incomplete"):
                coverage.targets_resolved += 1
            if result.state == "incomplete":
                coverage.impact_complete = False
        return resolved

    async def _impacts(
        self,
        resolved: dict[str, ResolvedTarget],
        coverage: CoverageSummary,
        diagnostics: list[DecisionDiagnostic],
        rel: str,
    ) -> dict[str, BlastRadiusOutput]:
        """Blast radius of every resolved symbol target (S6)."""
        impacts: dict[str, BlastRadiusOutput] = {}
        for target_id in sorted(resolved):
            result = resolved[target_id]
            if result.target.kind != "symbol" or result.state != "resolved":
                continue
            out = await self.structural.blast_radius(
                target_id, relations=list(_IMPACT_RELATIONS), depth=2, include_tests=True
            )
            impacts[target_id] = out
            if out.truncated or out.root is None:
                coverage.impact_complete = False
                reason = "truncated at the node cap" if out.truncated else "root symbol missing from the symbol plane"
                diagnostics.append(
                    DecisionDiagnostic(code=SCOPE_INCOMPLETE, message=f"impact of {target_id} {reason}", path=rel)
                )
        return impacts

    async def _structural_revision(
        self,
        resolved: dict[str, ResolvedTarget],
        impacts: dict[str, BlastRadiusOutput],
        diagnostics: list[DecisionDiagnostic],
        coverage: CoverageSummary,
        rel: str,
    ) -> str:
        """Content hash of the structural plane as consulted (AC10).

        Covers the content hashes of every consulted structural page (targets,
        ancestors, descendants, impacted symbols) plus the traversed impact
        edges, so an edge change alters the revision even when no page hash did.
        """
        page_ids: set[str] = set()
        for target_id, result in resolved.items():
            page_ids.add(target_id)
            page_ids.update(result.ancestors)
            page_ids.update(result.descendants)
        edges: list[list[Any]] = []
        for target_id in sorted(impacts):
            out = impacts[target_id]
            for impacted in out.impacted:
                page_ids.add(impacted.symbol.symbol_id)
                edges.append(
                    [target_id, impacted.symbol.symbol_id, impacted.via, impacted.distance, impacted.provenance]
                )
            edges.append([target_id, "truncated", out.truncated])
        try:
            hashes = await self.store.page_hashes(sorted(page_ids))
        except NotImplementedError:
            coverage.impact_complete = False
            diagnostics.append(
                DecisionDiagnostic(
                    code=SNAPSHOT_UNSTABLE, message="structural plane exposes no enumerable revision", path=rel
                )
            )
            return "unknown"
        pages = sorted([page_id, hashes.get(page_id)] for page_id in page_ids)
        return _sha256(_canonical({"pages": pages, "edges": sorted(edges, key=json.dumps)}))

    @staticmethod
    def _baseline(
        block: SpecDecisionsBlock,
        snapshot: InventorySnapshot,
        mode: str,
        diagnostics: list[DecisionDiagnostic],
        rel: str,
    ) -> list[DecisionRecord]:
        """Select the comparison set (AC3, AC12).

        The spec's own ids never compare against themselves: an already
        published revision or the pinned predecessor is replaced, not judged.
        ``replay`` also drops every record of the spec's document so an
        approved batch never conflicts with itself.
        """
        own = {spec_decision_id(block.document_id, entry.id): entry for entry in block.entries}
        by_id = {record.decision_id: record for record in snapshot.eligible}
        for decision_id, entry in sorted(own.items()):
            current = by_id.get(decision_id)
            if current is None:
                continue
            predecessor = entry.previous_revision if entry.previous_revision is not None else entry.revision - 1
            if current.revision not in (entry.revision, predecessor):
                diagnostics.append(
                    DecisionDiagnostic(
                        code=SUPERSESSION_INVALID,
                        message=(
                            f"{decision_id} revision {entry.revision} does not pin the active head "
                            f"revision {current.revision}"
                        ),
                        path=rel,
                        decision_id=decision_id,
                    )
                )
        prefix = f"adr:spec:{block.document_id}#"
        return [
            record
            for record in snapshot.eligible
            if record.decision_id not in own and not (mode == "replay" and record.decision_id.startswith(prefix))
        ]

    # ------------------------------------------------------------------ judge

    async def _expanded(self, target_id: str, resolved: dict[str, ResolvedTarget]) -> set[str]:
        """The target plus its ancestors and (for dirs) descendants."""
        result = resolved.get(target_id)
        if result is not None:
            return {target_id, *result.ancestors, *result.descendants}
        return {target_id, *await self.resolver.ancestors_of(target_id)}

    async def _overlap(self, left: list[str], right: list[str], resolved: dict[str, ResolvedTarget]) -> list[str]:
        """Target ids of ``right`` whose scope overlaps any target of ``left`` (ancestor-aware)."""
        hits: set[str] = set()
        left_expanded = {target_id: await self._expanded(target_id, resolved) for target_id in left}
        for other in right:
            other_expanded = await self._expanded(other, resolved)
            for target_id, expanded in left_expanded.items():
                if other in expanded or target_id in other_expanded:
                    hits.add(other)
        return sorted(hits)

    @staticmethod
    def _finding(kind: str, participants: list[DecisionRef], scope: list[str], message: str, *, blocking=False):
        """Build one fingerprinted finding."""
        participants = sorted(participants, key=lambda ref: (ref.decision_id, ref.revision))
        return Finding(
            kind=kind,
            rule_version=RULES_VERSION,
            fingerprint=finding_fingerprint(kind, RULES_VERSION, participants, scope),
            participants=participants,
            scope=sorted(scope),
            blocking=blocking,
            message=message,
        )

    async def _judge(
        self,
        block: SpecDecisionsBlock,
        waivers: list[ConflictWaiver],
        snapshot: InventorySnapshot,
        resolved: dict[str, ResolvedTarget],
        coverage: CoverageSummary,
        *,
        comparison: list[DecisionRecord],
        impacts: dict[str, BlastRadiusOutput],
        approvals: ApprovalManifest,
        text: str,
        diagnostics: list[DecisionDiagnostic],
        rel: str,
        taxonomy: Taxonomy,
    ) -> list[Finding]:
        """Produce findings from the full eligible set; never from a budgeted surface (F02)."""
        entries = {spec_decision_id(block.document_id, entry.id): entry for entry in block.entries}
        refs = {
            decision_id: DecisionRef(decision_id=decision_id, revision=e.revision) for decision_id, e in entries.items()
        }
        findings = self._contradictions(entries, refs, comparison, snapshot)
        explicit = {frozenset((p.decision_id for p in f.participants)) for f in findings}
        findings += await self._polarity_and_supersession(entries, refs, comparison, resolved, explicit)
        findings += self._blast_findings(entries, refs, impacts)
        findings += await self._evidence_gaps(block, snapshot, resolved, text, taxonomy)
        return await self._bind_waivers(findings, waivers, approvals, text, diagnostics, rel)

    @staticmethod
    def _contradictions(
        entries: dict[str, SpecDecisionEntry],
        refs: dict[str, DecisionRef],
        comparison: list[DecisionRecord],
        snapshot: InventorySnapshot,
    ) -> list[Finding]:
        """Blocking contradictions from explicit ``contradicts`` refs only (AC4, AC5, AC8)."""
        heads = {record.decision_id: record for record in comparison}
        prospective = {(ref.decision_id, ref.revision) for entry in entries.values() for ref in entry.supersedes}
        pairs: dict[tuple[tuple[str, int], ...], tuple[list[DecisionRef], str]] = {}

        def add(participants: list[DecisionRef], resolved_by: DecisionRef, message: str) -> None:
            if (resolved_by.decision_id, resolved_by.revision) in prospective:
                return
            pairs.setdefault(tuple(_ref_key(participants)), (participants, message))

        for decision_id, entry in entries.items():
            for ref in entry.contradicts:
                if ref.decision_id in entries:
                    other = refs[ref.decision_id]
                    add(
                        [refs[decision_id], other],
                        other,
                        f"{decision_id} contradicts {other.decision_id} in the same spec",
                    )
                    continue
                head = snapshot.effective_head(ref.decision_id)
                if head is None or head.decision_id not in heads:
                    continue
                add(
                    [refs[decision_id], head],
                    head,
                    f"{decision_id} contradicts active decision {head.decision_id}@{head.revision}",
                )
        for record in comparison:
            for ref in record.contradicts:
                if ref.decision_id not in entries:
                    continue
                head = DecisionRef(decision_id=record.decision_id, revision=record.revision)
                add(
                    [head, refs[ref.decision_id]],
                    head,
                    f"active decision {record.decision_id}@{record.revision} contradicts {ref.decision_id}",
                )
        return [
            ConsequenceService._finding("contradiction", participants, [], message, blocking=True)
            for participants, message in (pairs[key] for key in sorted(pairs))
        ]

    async def _polarity_and_supersession(
        self,
        entries: dict[str, SpecDecisionEntry],
        refs: dict[str, DecisionRef],
        comparison: list[DecisionRecord],
        resolved: dict[str, ResolvedTarget],
        explicit: set[frozenset[str]],
    ) -> list[Finding]:
        """Advisory ``potential-conflict`` (AC4) and ``possible-supersession`` findings."""
        others: list[tuple[DecisionRef, str | None, list[str], list[str], set[str]]] = [
            (
                DecisionRef(decision_id=record.decision_id, revision=record.revision),
                record.normative,
                [target.target_id for target in record.targets],
                list(record.about),
                {ref.decision_id for ref in [*record.contradicts, *record.supersedes_refs]},
            )
            for record in comparison
        ]
        ordered = sorted(entries)
        findings: list[Finding] = []
        for index, decision_id in enumerate(ordered):
            entry = entries[decision_id]
            linked = {ref.decision_id for ref in [*entry.contradicts, *entry.supersedes]}
            candidates = others + [
                (
                    refs[other_id],
                    entries[other_id].relation,
                    list(entries[other_id].targets),
                    list(entries[other_id].about),
                    {ref.decision_id for ref in [*entries[other_id].contradicts, *entries[other_id].supersedes]},
                )
                for other_id in ordered[index + 1 :]
            ]
            for other_ref, normative, targets, about, other_links in candidates:
                pair = frozenset((decision_id, other_ref.decision_id))
                if pair in explicit or not targets:
                    continue
                is_linked = other_ref.decision_id in linked or decision_id in other_links
                if normative in _OPPOSED.get(entry.relation, frozenset()):
                    scope = await self._overlap(list(entry.targets), targets, resolved)
                    if scope:
                        findings.append(
                            self._finding(
                                "potential-conflict",
                                [refs[decision_id], other_ref],
                                scope,
                                f"{decision_id} ({entry.relation}) and {other_ref.decision_id} ({normative}) "
                                f"govern overlapping scope",
                            )
                        )
                if (
                    not is_linked
                    and sorted(set(targets)) == sorted(set(entry.targets))
                    and sorted(set(about)) == sorted(set(entry.about))
                ):
                    findings.append(
                        self._finding(
                            "possible-supersession",
                            [refs[decision_id], other_ref],
                            sorted(set(targets)),
                            f"{decision_id} and {other_ref.decision_id} share targets and about without an explicit link",
                        )
                    )
        return findings

    def _blast_findings(
        self, entries: dict[str, SpecDecisionEntry], refs: dict[str, DecisionRef], impacts: dict[str, BlastRadiusOutput]
    ) -> list[Finding]:
        """Impact only — never applicability (AC7); inferred edges listed separately."""
        findings: list[Finding] = []
        for decision_id in sorted(entries):
            for target_id in sorted(set(entries[decision_id].targets)):
                out = impacts.get(target_id)
                if out is None or not out.impacted:
                    continue
                direct = sorted({i.symbol.symbol_id for i in out.impacted if i.provenance != "inferred"})
                inferred = sorted({i.symbol.symbol_id for i in out.impacted if i.provenance == "inferred"})
                message = f"{target_id} impacts {len(direct)} dependent(s): {', '.join(direct) or 'none'}"
                if inferred:
                    message += f"; inferred: {', '.join(inferred)}"
                if out.truncated:
                    message += "; traversal truncated"
                findings.append(self._finding("blast-radius", [refs[decision_id]], [target_id], message))
        return findings

    async def _governing_scope(
        self, block: SpecDecisionsBlock | None, resolved: dict[str, ResolvedTarget], text: str
    ) -> set[str]:
        """Scope ids: resolved targets, their ancestors/descendants, Codebase Contract ids."""
        scope: set[str] = set()
        if block is not None:
            for entry in block.entries:
                for target_id in entry.targets:
                    scope.update(await self._expanded(target_id, resolved))
                scope.update(ref.decision_id for ref in [*entry.contradicts, *entry.supersedes])
        for target_id in _contract_ids(text):
            scope.add(target_id)
            scope.update(await self.resolver.ancestors_of(target_id))
        return scope

    def _governing_about(self, block: SpecDecisionsBlock | None, taxonomy: Taxonomy, text: str) -> set[str]:
        """About ids: frontmatter-mapped subsystems plus the block's about ids."""
        projects, tags = _frontmatter(text)
        about = set(taxonomy.map_projects(projects, tags))
        if block is not None:
            about.update(about_id for entry in block.entries for about_id in entry.about)
        return about

    async def _freshness(self, record: DecisionRecord) -> tuple[str, list[str]]:
        """Aggregate evidence freshness and the paths that are stale or missing."""
        if not record.evidence:
            return "unverified", []
        states: list[str] = []
        gaps: list[str] = []
        for evidence in record.evidence:
            try:
                state, _ = await verify_freshness(self.root, evidence)
            except DecisionError:
                state = "missing"
            states.append(state)
            if state in ("stale", "missing"):
                gaps.append(evidence.rel_path)
        for state in ("missing", "stale", "unverified"):
            if state in states:
                return state, sorted(set(gaps))
        return "current", []

    async def _evidence_gaps(
        self,
        block: SpecDecisionsBlock,
        snapshot: InventorySnapshot,
        resolved: dict[str, ResolvedTarget],
        text: str,
        taxonomy: Taxonomy,
    ) -> list[Finding]:
        """Governing records whose cited evidence is stale or missing."""
        scope = await self._governing_scope(block, resolved, text)
        own = {spec_decision_id(block.document_id, entry.id) for entry in block.entries}
        findings: list[Finding] = []
        for record in snapshot.governing(self._governing_about(block, taxonomy, text), scope):
            if record.decision_id in own:
                continue
            state, gaps = await self._freshness(record)
            if not gaps:
                continue
            findings.append(
                self._finding(
                    "evidence-gap",
                    [DecisionRef(decision_id=record.decision_id, revision=record.revision)],
                    gaps,
                    f"{record.decision_id} evidence is {state}: {', '.join(gaps)}",
                )
            )
        return findings

    async def _bind_waivers(
        self,
        findings: list[Finding],
        waivers: list[ConflictWaiver],
        approvals: ApprovalManifest,
        text: str,
        diagnostics: list[DecisionDiagnostic],
        rel: str,
    ) -> list[Finding]:
        """Apply waivers bound to fingerprint, exact participants and a verified approval (AC9)."""
        by_fingerprint = {finding.fingerprint: index for index, finding in enumerate(findings)}
        approval_entries = {entry.batch_id: entry for entry in approvals.entries if entry.kind == "waiver"}
        for waiver in waivers:
            index = by_fingerprint.get(waiver.finding_fingerprint)
            problem: str | None = None
            if index is None:
                problem = "fingerprint matches no current finding"
            elif _ref_key(waiver.participants) != _ref_key(findings[index].participants):
                problem = "participants differ from the finding"
            else:
                approval = approval_entries.get(waiver.approval_ref)
                if approval is None:
                    problem = f"approval_ref {waiver.approval_ref!r} names no waiver approval"
                elif approval.actor != waiver.actor:
                    problem = f"actor {waiver.actor!r} does not match the approval actor"
                else:
                    verified, _ = await self.adapter.verify(approval, spec_text=text)
                    if not verified:
                        problem = f"approval {waiver.approval_ref!r} is not verified"
            if problem is not None or index is None:
                diagnostics.append(
                    DecisionDiagnostic(
                        code=WAIVER_INVALID,
                        message=f"waiver {waiver.finding_fingerprint}: {problem}",
                        path=rel,
                    )
                )
                continue
            findings[index] = findings[index].model_copy(update={"waived_by": waiver.approval_ref})
        return findings

    # -------------------------------------------------------------- governing

    async def governing(self, spec_path: Path, *, budget_tokens: int = 3000) -> GoverningDossier:
        """Full eligible set collected first; ``budget_tokens`` is consumed by the renderer only (G1, AC14).

        Args:
            spec_path: Spec path, relative to ``root`` (or absolute).
            budget_tokens: Rendering budget; never applied here.

        Returns:
            The complete governing dossier. A snapshot failure is reported as
            ``truncated=True`` with no entries rather than raised.
        """
        del budget_tokens  # rendering-only (AC14)
        rel = spec_path.as_posix()
        try:
            text = await asyncio.to_thread((self.root / spec_path).read_text, encoding="utf-8")
        except OSError:
            text = ""
        if not audit_configured(self.taxonomy_path, self.approvals_path):
            return GoverningDossier(empty_plane=True, searched_subsystems=[])
        block, _, _ = parse_spec_decisions(text, source_path=rel)
        try:
            taxonomy = Taxonomy.load(self.taxonomy_path)
            approvals = ApprovalManifest.load(self.approvals_path)
        except DecisionError as exc:
            self.logger.warning("governing: %s", exc)
            return GoverningDossier(truncated=True)
        about = self._governing_about(block, taxonomy, text)
        resolved: dict[str, ResolvedTarget] = {}
        if block is not None:
            for target_id in sorted({t for entry in block.entries for t in entry.targets}):
                result, _ = await self.resolver.resolve(target_id)
                if result is not None:
                    resolved[target_id] = result
        scope = await self._governing_scope(block, resolved, text)
        diagnostics: list[DecisionDiagnostic] = []
        coverage = CoverageSummary()
        try:
            snapshot = await InventorySnapshot.take(
                DecisionRepository(self.store, self.config.max_records),
                taxonomy,
                approvals,
                self.adapter,
                await self._structural_revision(resolved, {}, diagnostics, coverage, rel),
                store=self.store,
                root=self.root,
                config_digest=self._config_digest(),
            )
        except DecisionError as exc:
            self.logger.warning("governing: %s", exc)
            return GoverningDossier(searched_subsystems=sorted(about), truncated=True)
        entries: list[GoverningEntry] = []
        for record in snapshot.governing(about, scope):
            freshness, _ = await self._freshness(record)
            entries.append(
                GoverningEntry(
                    decision_id=record.decision_id,
                    revision=record.revision,
                    title=record.title,
                    statement=record.decision,
                    normative=record.normative,
                    about=list(record.about),
                    targets=[target.target_id for target in record.targets],
                    rationale=record.rationale,
                    consequences=record.consequences,
                    supersedes=list(record.supersedes_refs),
                    freshness=freshness,
                    source_path=record.source_path,
                )
            )
        return GoverningDossier(
            entries=sorted(entries, key=lambda entry: entry.decision_id),
            searched_subsystems=sorted(about),
            empty_plane=not snapshot.eligible,
            snapshot=snapshot.manifest,
        )
