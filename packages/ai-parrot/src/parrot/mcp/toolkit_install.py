"""Host-agnostic orchestration for `parrot toolkits` (FEAT-570, spec §3 M6).

Joins packaged templates x declared config x per-host entry state, and performs
the four mutations. wikitoolkit is never included — it belongs to
`parrot claude install`.
"""

from __future__ import annotations

import importlib.util
from enum import Enum
from pathlib import Path
from typing import Sequence

import yaml
from pydantic import BaseModel, Field

from parrot.mcp.hosts import HostEntryState, HostKind, detect_hosts, get_adapter
from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import (
    REPO_ROOT_PLACEHOLDER,
    available_templates,
    load_template,
    preflight_seed,
    remove_section,
    seed_toolkit_sections,
    set_section_enabled,
    template_drift,
)


class ToolkitState(str, Enum):
    NOT_INSTALLED = "not_installed"
    ENABLED = "enabled"
    DISABLED = "disabled"


class ToolkitRow(BaseModel):
    """One packaged template joined with its declared and per-host state."""

    name: str
    summary: str
    class_path: str
    state: ToolkitState
    requires_llm: bool = False
    requires_dist: tuple[str, ...] = ()
    dist_available: bool = True
    drift: list[str] = Field(default_factory=list)
    hosts: list[HostEntryState] = Field(default_factory=list)


class ActionReport(BaseModel):
    """What one mutation did, including per-host failures (never raised)."""

    actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failed_hosts: dict[HostKind, str] = Field(default_factory=dict)


def dist_available(requires_dist: Sequence[str]) -> bool:
    """True when every named distribution is importable, WITHOUT importing it.

    Uses `importlib.util.find_spec`, never `import_module`: `inventory()` backs
    `parrot toolkits list`, which must import no toolkit class (AC1). An empty
    `requires_dist` means core-only and is always True.
    """
    for dist in requires_dist:
        try:
            if importlib.util.find_spec(dist) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def _resolve_hosts(root: Path, hosts: Sequence[HostKind] | None) -> list[HostKind]:
    """Explicit hosts, else every detected host (spec §8 Q1 interim default (a))."""
    return list(hosts) if hosts else detect_hosts(root)


def _class_path_for_template(root: Path, name: str) -> str:
    """Read the `class:` value straight from the packaged template body.

    Parses the rendered YAML section WITHOUT importing anything (AC1) — the class
    is read as plain text/YAML, never resolved to a Python object.
    """
    template = load_template(name)
    rendered = template.body.replace(REPO_ROOT_PLACEHOLDER, str(root))
    parsed = yaml.safe_load(f"toolkits:\n{rendered}") or {}
    section_body = (parsed.get("toolkits") or {}).get(name) or {}
    return section_body.get("class", "") if isinstance(section_body, dict) else ""


def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:
    """One row per packaged template: state, drift, dependency and per-host status.

    wikitoolkit is never a row. Imports no toolkit class.
    """
    root = Path(root)
    resolved_hosts = _resolve_hosts(root, hosts)
    declared = load_toolkits_config(root)
    names = available_templates()

    host_states: dict[HostKind, dict[str, HostEntryState]] = {
        kind: get_adapter(kind).inspect(root, names) for kind in resolved_hosts
    }

    rows: list[ToolkitRow] = []
    for name in names:
        template = load_template(name)
        class_path = _class_path_for_template(root, name)

        section = declared.toolkits.get(name)
        if section is None:
            state = ToolkitState.NOT_INSTALLED
            drift: list[str] = []
        else:
            state = ToolkitState.ENABLED if section.enabled else ToolkitState.DISABLED
            drift = template_drift(root, name)

        row_hosts = [host_states[kind][name] for kind in resolved_hosts if name in host_states[kind]]

        rows.append(
            ToolkitRow(
                name=name,
                summary=template.summary,
                class_path=class_path,
                state=state,
                requires_llm=template.requires_llm,
                requires_dist=template.requires_dist,
                dist_available=dist_available(template.requires_dist),
                drift=drift,
                hosts=row_hosts,
            )
        )
    return rows


def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport) -> None:
    """Reconcile every host, collecting per-host failures instead of raising."""
    for kind in hosts:
        adapter = get_adapter(kind)
        try:
            actions, warnings = adapter.reconcile(root)
        except (OSError, ValueError) as exc:
            report.failed_hosts[kind] = str(exc)
            continue
        report.actions.extend(actions)
        report.warnings.extend(warnings)


def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:
    """Seed `names` and register them with each host.

    Order: preflight -> seed -> reconcile -> approvals. Preflight raises BEFORE any
    write, so an unknown name leaves the config byte-identical (AC8).

    Raises:
        ValueError: any name is unknown, or the existing config is malformed.
    """
    root = Path(root)
    preflight_seed(root, names)

    report = ActionReport()
    seed_result = seed_toolkit_sections(root, names)
    report.actions.extend(f"{name} — seeded" for name in seed_result.added)
    report.warnings.extend(f"{name} — already installed" for name in seed_result.skipped)
    report.warnings.extend(f"{name} — template drift: {', '.join(keys)}" for name, keys in seed_result.drift.items())

    resolved_hosts = list(hosts)
    _reconcile_all(root, resolved_hosts, report)

    if HostKind.CLAUDE in resolved_hosts:
        message = get_adapter(HostKind.CLAUDE).sync_approvals(root)
        if message:
            report.actions.append(message)

    return report


def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:
    """Remove `names`' sections and their host entries. Removes CONFIG ONLY.

    Per spec §8 Q2 this NEVER deletes a toolkit's on-disk artifacts (scraping
    plans, db results) — operator data is not ours to delete.
    """
    root = Path(root)
    report = ActionReport()
    resolved_hosts = list(hosts)

    # Snapshot managed host entry names BEFORE mutating (design research S3):
    # the "parrot-<name>" keys confirmed ours by each adapter's `inspect()`.
    removed_approvals: set[str] = set()
    for kind in resolved_hosts:
        adapter = get_adapter(kind)
        for name, state in adapter.inspect(root, names).items():
            if state.managed:
                removed_approvals.add(f"parrot-{name}")

    for name in names:
        if remove_section(root, name):
            report.actions.append(f"{name} — removed")
        else:
            report.warnings.append(f"{name} — not installed")

    _reconcile_all(root, resolved_hosts, report)

    if HostKind.CLAUDE in resolved_hosts:
        message = get_adapter(HostKind.CLAUDE).sync_approvals(root, removed=tuple(sorted(removed_approvals)))
        if message:
            report.actions.append(message)

    return report


def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind]) -> ActionReport:
    """Flip `enabled:` for `names` and reconcile; the section and its kwargs survive."""
    root = Path(root)
    report = ActionReport()
    resolved_hosts = list(hosts)

    removed_approvals: set[str] = set()
    if not enabled:
        # Snapshot managed host entry names BEFORE disabling — same S3 rationale
        # as uninstall: reconcile will delete the disabled entries from each host.
        for kind in resolved_hosts:
            adapter = get_adapter(kind)
            for name, state in adapter.inspect(root, names).items():
                if state.managed:
                    removed_approvals.add(f"parrot-{name}")

    for name in names:
        if set_section_enabled(root, name, enabled):
            report.actions.append(f"{name} — {'enabled' if enabled else 'disabled'}")
        else:
            report.warnings.append(f"{name} — not installed")

    _reconcile_all(root, resolved_hosts, report)

    if HostKind.CLAUDE in resolved_hosts:
        if enabled:
            message = get_adapter(HostKind.CLAUDE).sync_approvals(root)
        else:
            message = get_adapter(HostKind.CLAUDE).sync_approvals(root, removed=tuple(sorted(removed_approvals)))
        if message:
            report.actions.append(message)

    return report
