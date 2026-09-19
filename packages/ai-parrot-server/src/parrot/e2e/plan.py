"""Load and validate an E2E plan from its Markdown frontmatter (FEAT-581, M2).

``load_plan()`` is the single entry point every caller (CLI, runner, dev-loop
E2E stage) uses to turn one ``e2e-plan.md`` file into a fully validated
:class:`parrot.e2e.models.E2EPlan`. Per spec §2 "Data Models":

    ``e2e-plan.md`` has YAML frontmatter containing the complete ``E2EPlan``;
    its body is human-readable rationale. The spec remains authoritative for
    policy and scenario IDs. Plan/spec disagreements are configuration
    errors. Required policy demands at least one required codified scenario.
    A node ID belongs to one scenario only; parameterized nodes must be
    enumerated, not selected by wildcard or directory.

Every failure mode below raises :class:`parrot.e2e.errors.E2EConfigError`
(exit code 2) *before* any subprocess, target adapter or client is
constructed — this module has no target/provider imports and no process
side effects of its own, only filesystem reads relative to ``worktree``.

Scope boundaries (see ``TASK-3521``): duplicate/undeclared node IDs,
wildcard/bare-directory pytest selection, unsafe/escaping paths, and
missing/malformed/mismatched policy are this module's responsibility.
Per-adapter option-key allow-listing (``TargetConfig.options``) is
explicitly deferred to the M4 target adapters (see
``parrot.e2e.models.TargetConfig`` docstring); this module only rejects
target references that are not declared in the plan's own ``targets`` map
(surfaced from :class:`parrot.e2e.models.E2EPlan`'s own validators).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import E2EPlan

__all__ = ["load_plan"]

_FRONTMATTER_DELIMITER = "---"


def load_plan(path: Path, *, worktree: Path) -> E2EPlan:
    """Validate frontmatter, contained paths and spec/plan policy consistency.

    Args:
        path: Path to the ``e2e-plan.md`` document (absolute or relative to
            the current working directory); its resolved location must lie
            inside ``worktree``.
        worktree: Canonical worktree root every plan/spec path must resolve
            inside of.

    Returns:
        The fully validated :class:`E2EPlan`.

    Raises:
        E2EConfigError: If the plan file is missing/unreadable, its
            frontmatter is absent/malformed, the resolved plan or referenced
            spec path escapes ``worktree``, the referenced spec is missing,
            the parsed content fails :class:`E2EPlan` validation (duplicate
            or undeclared node/target/prerequisite IDs, wildcard or
            bare-directory node selection, an invalid/malformed policy
            value, ...), or the plan's ``policy``/scenario IDs disagree with
            the ones declared by the authoritative spec's own frontmatter.
    """
    resolved_worktree = _resolve_root(worktree)
    resolved_plan_path = _resolve_within(resolved_worktree, path, root_label="worktree", path_label="plan path")
    raw = _read_frontmatter(resolved_plan_path, label="plan")

    # spec §2: "A missing policy defaults to optional for compatibility ...
    # Malformed policy values fail metadata validation instead of silently
    # defaulting." Only an *absent* key is defaulted; a present-but-invalid
    # value is passed through unchanged so E2EPlan's own Literal validation
    # rejects it (never coerced).
    if "policy" not in raw or raw.get("policy") is None:
        raw = {**raw, "policy": "optional"}

    plan = _build_plan(raw, source=resolved_plan_path)

    resolved_spec_path = _resolve_within(
        resolved_worktree, resolved_worktree / plan.spec_path, root_label="worktree", path_label="spec_path"
    )
    if not resolved_spec_path.is_file():
        raise E2EConfigError(
            f"E2E plan {resolved_plan_path} references a missing spec file: {plan.spec_path!r}",
            reason_code="spec_path_missing",
        )

    _check_spec_consistency(plan, spec_path=resolved_spec_path)
    return plan


def _resolve_root(worktree: Path) -> Path:
    """Resolve the worktree root, requiring it to already exist.

    Args:
        worktree: Candidate worktree root.

    Returns:
        The canonical (symlink-resolved, absolute) worktree path.

    Raises:
        E2EConfigError: If ``worktree`` cannot be resolved or does not exist.
    """
    try:
        resolved = worktree.resolve(strict=True)
    except OSError as exc:
        raise E2EConfigError(
            f"worktree root does not exist or is unreadable: {worktree}: {exc}", reason_code="worktree_missing"
        ) from exc
    if not resolved.is_dir():
        raise E2EConfigError(f"worktree root is not a directory: {worktree}", reason_code="worktree_not_directory")
    return resolved


def _resolve_within(root: Path, candidate: Path, *, root_label: str, path_label: str) -> Path:
    """Resolve ``candidate`` and reject it if it escapes ``root``.

    Resolution follows symlinks (``Path.resolve``), so a symlink whose
    target lies outside ``root`` is rejected the same way a literal ``..``
    traversal would be — spec §2's "reject traversal and escaping symlinks".

    Args:
        root: Canonical root the resolved candidate must be contained in.
        candidate: Path to resolve; used as-is if absolute, else joined
            against ``root`` first.
        root_label: Human-readable name for ``root`` in error messages.
        path_label: Human-readable name for ``candidate`` in error messages.

    Returns:
        The resolved, contained path.

    Raises:
        E2EConfigError: If the candidate cannot be resolved, or resolves
            outside ``root``.
    """
    absolute_candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved_candidate = absolute_candidate.resolve(strict=False)
    except OSError as exc:
        raise E2EConfigError(
            f"{path_label} could not be resolved: {candidate}: {exc}", reason_code="path_unresolvable"
        ) from exc

    if resolved_candidate != root and root not in resolved_candidate.parents:
        raise E2EConfigError(
            f"{path_label} escapes {root_label} (traversal or symlink escape): {candidate} resolves to "
            f"{resolved_candidate}, outside {root}",
            reason_code="path_escape",
        )
    return resolved_candidate


def _read_frontmatter(path: Path, *, label: str) -> dict[str, Any]:
    """Read one Markdown file and parse its YAML frontmatter block.

    Args:
        path: Resolved path to the Markdown document.
        label: Human-readable document name for error messages (``"plan"``
            or ``"spec"``).

    Returns:
        The parsed frontmatter mapping (empty if the block itself is empty).

    Raises:
        E2EConfigError: If the file is missing/unreadable, is not a file,
            has no closed ``---`` frontmatter block, the block is not valid
            YAML, or the parsed YAML is not a mapping.
    """
    if not path.is_file():
        raise E2EConfigError(f"E2E {label} file not found: {path}", reason_code=f"{label}_missing")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise E2EConfigError(
            f"E2E {label} file could not be read: {path}: {exc}", reason_code=f"{label}_unreadable"
        ) from exc

    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        raise E2EConfigError(
            f"E2E {label} file must start with a YAML frontmatter block delimited by '---': {path}",
            reason_code=f"{label}_no_frontmatter",
        )

    closing_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_DELIMITER:
            closing_index = index
            break
    if closing_index is None:
        raise E2EConfigError(
            f"E2E {label} file frontmatter block is not closed with a second '---': {path}",
            reason_code=f"{label}_no_frontmatter",
        )

    frontmatter_text = "\n".join(lines[1:closing_index])
    try:
        raw = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise E2EConfigError(
            f"E2E {label} frontmatter is not valid YAML: {path}: {exc}", reason_code=f"{label}_invalid_yaml"
        ) from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise E2EConfigError(
            f"E2E {label} frontmatter must be a YAML mapping: {path}", reason_code=f"{label}_invalid_yaml"
        )
    return raw


def _build_plan(raw: dict[str, Any], *, source: Path) -> E2EPlan:
    """Construct and validate an :class:`E2EPlan` from a raw frontmatter mapping.

    Args:
        raw: Parsed frontmatter mapping.
        source: The plan file the mapping was read from, for error context.

    Returns:
        The validated :class:`E2EPlan`.

    Raises:
        E2EConfigError: Wrapping any :class:`pydantic.ValidationError` raised
            while constructing the model — duplicate/undeclared node IDs,
            wildcard/bare-directory node selection, unknown target/tier/
            outcome literals, malformed policy, missing required-policy
            coverage, unsafe ``spec_path`` content, etc.
    """
    try:
        return E2EPlan.model_validate(raw)
    except ValidationError as exc:
        raise E2EConfigError(f"E2E plan {source} failed schema validation: {exc}", reason_code="plan_invalid") from exc


def _check_spec_consistency(plan: E2EPlan, *, spec_path: Path) -> None:
    """Cross-validate the plan's policy/scenario IDs against the authoritative spec.

    The referenced spec file's own frontmatter may declare an ``e2e``
    mapping (``policy`` and/or ``scenario_ids``) once a feature spec adopts
    that metadata (spec §2: "Feature policy metadata ... introduced by this
    feature are prospective"). When present, any disagreement with the plan
    is a configuration error (spec §2: "Plan/spec disagreements are
    configuration errors."). When the spec declares no ``e2e`` metadata at
    all — the case for every spec in this repository today — no cross-check
    is performed; this keeps ``load_plan`` forward-compatible without
    inventing a schema no other module writes yet.

    Args:
        plan: The already-validated plan.
        spec_path: Resolved path to the authoritative spec file.

    Raises:
        E2EConfigError: If the spec declares an ``e2e.policy`` or
            ``e2e.scenario_ids`` that disagrees with ``plan``.
    """
    spec_frontmatter = _read_frontmatter(spec_path, label="spec")
    declared = spec_frontmatter.get("e2e")
    if not isinstance(declared, dict):
        return

    declared_policy = declared.get("policy")
    if declared_policy is not None and declared_policy != plan.policy:
        raise E2EConfigError(
            f"E2E plan policy {plan.policy!r} disagrees with spec {spec_path}'s declared e2e.policy "
            f"{declared_policy!r}",
            reason_code="spec_plan_policy_mismatch",
        )

    declared_scenario_ids = declared.get("scenario_ids")
    if declared_scenario_ids is not None:
        plan_scenario_ids = {scenario.id for scenario in plan.scenarios}
        if set(declared_scenario_ids) != plan_scenario_ids:
            raise E2EConfigError(
                f"E2E plan scenario IDs {sorted(plan_scenario_ids)} disagree with spec {spec_path}'s declared "
                f"e2e.scenario_ids {sorted(declared_scenario_ids)}",
                reason_code="spec_plan_scenario_mismatch",
            )
