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
from parrot.mcp.toolkit_config import (
    AGENT_TOOLKIT_CLASS_PATH,
    agent_section_name,
    is_agent_section,
    load_toolkits_config,
)
from parrot.mcp.toolkit_seed import (
    REPO_ROOT_PLACEHOLDER,
    available_templates,
    load_template,
    preflight_seed,
    remove_section,
    seed_agent_sections,
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
    requires_pip: tuple[str, ...] = ()
    post_install: tuple[str, ...] = ()
    requires_env: tuple[str, ...] = ()
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
                requires_pip=template.requires_pip,
                post_install=template.post_install,
                requires_env=template.requires_env,
                drift=drift,
                hosts=row_hosts,
            )
        )
    return rows


def _reconcile_all(
    root: Path, hosts: Sequence[HostKind], report: ActionReport, *, portable: bool | None = None
) -> None:
    """Collect reconciler results with explicit command form and existing failure isolation."""
    for kind in hosts:
        adapter = get_adapter(kind)
        try:
            actions, warnings = adapter.reconcile(root, portable=portable)
        except (OSError, ValueError) as exc:
            report.failed_hosts[kind] = str(exc)
            continue
        for action in actions:
            is_fallback_note = action.startswith("note: host config baked to absolute paths ")
            if not (is_fallback_note and action in report.actions):
                report.actions.append(action)
        report.warnings.extend(warnings)


def install_toolkits(
    root: Path, names: Sequence[str], hosts: Sequence[HostKind], *, portable: bool | None = None
) -> ActionReport:
    """Seed and register toolkits with the caller's explicit or inferred form.

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
    _reconcile_all(root, resolved_hosts, report, portable=portable)

    if HostKind.CLAUDE in resolved_hosts:
        message = get_adapter(HostKind.CLAUDE).sync_approvals(root)
        if message:
            report.actions.append(message)

    return report


def install_agent_toolkits(
    root: Path, agents: Sequence[str], hosts: Sequence[HostKind], *, portable: bool | None = None
) -> ActionReport:
    """Resolve, seed, reconcile, and approve agent sections atomically before the first write.

    Raises:
        ValueError: An agent cannot be exposed, two agents share a section name, or the config is malformed.
    """
    from parrot.mcp.agent_toolkit import AgentExposureError, _tool_names, resolve_exposable_agent  # noqa: PLC0415

    root = Path(root)
    resolved = []
    errors: list[str] = []
    for name in dict.fromkeys(agents):
        try:
            resolved.append(resolve_exposable_agent(name))
        except AgentExposureError as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError("; ".join(errors))

    sections: dict[str, str] = {}
    for agent in resolved:
        section = agent_section_name(agent.name)
        if section in sections:
            raise ValueError(f"Agents {sections[section]!r} and {agent.name!r} share section {section!r}")
        sections[section] = agent.name

    load_toolkits_config(root)
    report = ActionReport()
    seed_result = seed_agent_sections(root, sections)
    tools = {agent_section_name(agent.name): ", ".join(_tool_names(agent.methods, agent.name)) for agent in resolved}
    report.actions.extend(
        f"{sections[section]} — seeded as {section} (tools: {tools[section]})" for section in seed_result.added
    )
    report.warnings.extend(f"{sections[section]} — already installed as {section}" for section in seed_result.skipped)
    resolved_hosts = list(hosts)
    _reconcile_all(root, resolved_hosts, report, portable=portable)

    if HostKind.CLAUDE in resolved_hosts:
        message = get_adapter(HostKind.CLAUDE).sync_approvals(root)
        if message:
            report.actions.append(message)

    return report


def agent_inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:
    """Return one row per exposable agent and per orphaned installed agent section."""
    from parrot.mcp.agent_toolkit import (
        AgentExposureError,
        list_exposable_agents,
        resolve_exposable_agent,
    )  # noqa: PLC0415

    root = Path(root)
    resolved_hosts = _resolve_hosts(root, hosts)
    declared = load_toolkits_config(root)
    exposable = list_exposable_agents()
    installed = {name: section for name, section in declared.toolkits.items() if is_agent_section(section)}
    names = sorted({agent.section_name for agent in exposable} | set(installed))
    host_states = {kind: get_adapter(kind).inspect(root, names) for kind in resolved_hosts}

    def _state(section_name: str) -> ToolkitState:
        section = declared.toolkits.get(section_name)
        if section is None:
            return ToolkitState.NOT_INSTALLED
        return ToolkitState.ENABLED if section.enabled else ToolkitState.DISABLED

    def _hosts(section_name: str) -> list[HostEntryState]:
        return [host_states[kind][section_name] for kind in resolved_hosts if section_name in host_states[kind]]

    rows = [
        ToolkitRow(
            name=agent.section_name,
            summary=f"agent {agent.name}: {', '.join(agent.tools)}",
            class_path=AGENT_TOOLKIT_CLASS_PATH,
            state=_state(agent.section_name),
            hosts=_hosts(agent.section_name),
        )
        for agent in exposable
    ]
    listed = {agent.section_name for agent in exposable}
    for section_name, section in installed.items():
        if section_name in listed:
            continue
        agent = str(section.kwargs.get("agent", ""))
        try:
            resolve_exposable_agent(agent)
        except AgentExposureError as exc:
            reason = str(exc)
        else:
            reason = f"installed as {section_name}, expected {agent_section_name(agent)}"
        rows.append(
            ToolkitRow(
                name=section_name,
                summary=f"agent {agent}",
                class_path=AGENT_TOOLKIT_CLASS_PATH,
                state=_state(section_name),
                drift=[f"agent not exposable: {reason}"],
                hosts=_hosts(section_name),
            )
        )
    return rows


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


def set_toolkits_enabled(
    root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind], *, portable: bool | None = None
) -> ActionReport:
    """Toggle sections and reconcile while retaining all existing approval semantics."""
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

    _reconcile_all(root, resolved_hosts, report, portable=portable)

    if HostKind.CLAUDE in resolved_hosts:
        if enabled:
            message = get_adapter(HostKind.CLAUDE).sync_approvals(root)
        else:
            message = get_adapter(HostKind.CLAUDE).sync_approvals(root, removed=tuple(sorted(removed_approvals)))
        if message:
            report.actions.append(message)

    return report
