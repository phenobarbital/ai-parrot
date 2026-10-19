"""Per-tenant skill primitives (FEAT-707).

Tenant-id validation, secure tenant paths, per-task ContextVars and the
read-only :class:`SkillView` overlay of a tenant registry over the global one.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Final, List, Optional

from parrot.utils.paths import secure_path, validate_path_segment

from .file_registry import SkillFileRegistry
from .models import SkillDefinition

_LOGGER = logging.getLogger(__name__)

RESERVED_TENANT_NAMES: frozenset[str] = frozenset(
    {"skills", "learned", "tenants", "prompts", "queries", "kb", "documents", "flows", "_drafts", "_shared"}
)
TENANTS_DIRNAME: Final[str] = "tenants"
SKILLS_DIRNAME: Final[str] = "skills"


def validate_tenant_id(value: str) -> str:
    """Return ``value`` when it is a safe, non-reserved tenant id.

    Raises:
        ValueError: If ``value`` is not a safe single path segment or is reserved.
    """
    validate_path_segment(value, name="tenant id")
    if value.lower() in RESERVED_TENANT_NAMES:
        raise ValueError(f"Reserved tenant id: {value!r}")
    return value


def tenant_skills_dir(agent_root: Path, tenant: str) -> Path:
    """Return the contained ``agent_root/tenants/{tenant}/skills`` path.

    Raises:
        ValueError: If the tenant is invalid or the resolved path escapes ``agent_root``.
    """
    return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), SKILLS_DIRNAME, name="tenant id")


def discover_tenant_dirs(agent_root: Path, logger: Optional[logging.Logger] = None) -> Dict[str, Path]:
    """Return valid tenant skill directories, ordered by tenant name.

    Invalid names, escaping symlinks, and entries without a ``skills`` directory
    are skipped with a warning. A missing tenant root returns an empty mapping.
    """
    log = logger or _LOGGER
    tenants_root = agent_root / TENANTS_DIRNAME
    if not tenants_root.is_dir():
        return {}

    found: Dict[str, Path] = {}
    for entry in sorted(tenants_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            skills_dir = tenant_skills_dir(agent_root, entry.name)
        except ValueError as exc:
            log.warning("Skipping tenant dir %s: %s", entry, exc)
            continue
        if not skills_dir.is_dir():
            log.warning("Skipping tenant dir %s: missing skills directory", entry)
            continue
        found[entry.name] = skills_dir
    return found


_skill_tenant: ContextVar[Optional[str]] = ContextVar("parrot_skill_tenant", default=None)
_active_skill: ContextVar[Optional[SkillDefinition]] = ContextVar("parrot_active_skill", default=None)


def current_skill_tenant() -> Optional[str]:
    """Return the tenant bound to the current asyncio task, if any."""
    return _skill_tenant.get()


def bind_skill_tenant(tenant: Optional[str]) -> Token:
    """Bind ``tenant`` for the current task and return its reset token."""
    return _skill_tenant.set(tenant)


def reset_skill_tenant(token: Token) -> None:
    """Undo a prior :func:`bind_skill_tenant` call."""
    _skill_tenant.reset(token)


def current_active_skill() -> Optional[SkillDefinition]:
    """Return the request-local trigger-activated skill, if any."""
    return _active_skill.get()


def set_active_skill(skill: Optional[SkillDefinition]) -> None:
    """Replace the request-local active skill."""
    _active_skill.set(skill)


def enter_active_skill_scope() -> Token:
    """Snapshot the active skill so :func:`exit_active_skill_scope` can restore it.

    ``ask()``/``ask_stream()`` open this scope so a skill a ``/trigger`` set
    during a call never outlives that call, even when the call fails before
    the system prompt consumes it.
    """
    return _active_skill.set(_active_skill.get())


def exit_active_skill_scope(token: Token) -> None:
    """Restore the active skill captured by :func:`enter_active_skill_scope`."""
    _active_skill.reset(token)


@dataclass(frozen=True)
class TenantTreeReport:
    """Configure-time audit of one tenant tree."""

    tenant: str
    skills_dir: Path
    loaded: int
    shadowing: tuple[str, ...] = ()
    shadowed_triggers: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()


class SkillView:
    """Read-only overlay of a tenant registry over the global registry."""

    def __init__(
        self,
        global_registry: SkillFileRegistry,
        tenant_registry: Optional[SkillFileRegistry] = None,
        *,
        tenant: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._global = global_registry
        self._tenant_registry = tenant_registry
        self.tenant = tenant
        self.logger = logger or _LOGGER
        self.report: Optional[TenantTreeReport] = None
        self._by_name: Dict[str, SkillDefinition] = {}
        self._by_trigger: Dict[str, SkillDefinition] = {}
        self._ordered: List[SkillDefinition] = []
        self.compose()

    @property
    def learned_dir(self) -> Path:
        """Return the global learned directory; learned skills are global."""
        return self._global.learned_dir

    def compose(self) -> "SkillView":
        """Recompute the effective indexes for collision cases C1 through C8."""
        globals_ = self._global.list_skills()
        global_by_name = {skill.name: skill for skill in globals_}
        global_by_trigger: Dict[str, SkillDefinition] = {}
        for skill in globals_:
            for trigger in skill.triggers:
                global_by_trigger.setdefault(trigger, skill)

        if self._tenant_registry is None:
            self._by_name = global_by_name
            self._by_trigger = global_by_trigger
            self._ordered = list(globals_)
            self.report = None
            return self

        locked_names = {skill.name: skill for skill in globals_ if skill.global_only}
        locked_triggers: Dict[str, SkillDefinition] = {}
        for skill in locked_names.values():
            for trigger in skill.triggers:
                locked_triggers.setdefault(trigger, skill)

        kept: List[SkillDefinition] = []
        shadowing: List[str] = []
        shadowed_triggers: List[str] = []
        dropped: List[str] = []
        for tenant_skill in self._tenant_registry.list_skills():
            locked_name = locked_names.get(tenant_skill.name)
            if locked_name is not None:
                self.logger.error(
                    "Tenant skill %s (%s) conflicts with global_only skill (%s); dropping tenant skill",
                    tenant_skill.name,
                    tenant_skill.file_path,
                    locked_name.file_path,
                )
                dropped.append(tenant_skill.name)
                continue

            blocked = [trigger for trigger in tenant_skill.triggers if trigger in locked_triggers]
            effective = tenant_skill
            if blocked:
                for trigger in blocked:
                    self.logger.error(
                        "Tenant skill %s (%s) trigger %s conflicts with global_only skill (%s); dropping trigger",
                        tenant_skill.name,
                        tenant_skill.file_path,
                        trigger,
                        locked_triggers[trigger].file_path,
                    )
                effective = tenant_skill.model_copy(
                    update={
                        "triggers": [trigger for trigger in tenant_skill.triggers if trigger not in locked_triggers]
                    }
                )

            global_name = global_by_name.get(tenant_skill.name)
            if global_name is not None:
                self.logger.info("Tenant skill %s shadows global skill %s", tenant_skill.name, global_name.name)
                shadowing.append(tenant_skill.name)

            for trigger in effective.triggers:
                if trigger in global_by_trigger:
                    self.logger.info(
                        "Tenant trigger %s shadowed global skill %s", trigger, global_by_trigger[trigger].name
                    )
                    shadowed_triggers.append(trigger)
            kept.append(effective)

        tenant_names = {skill.name for skill in kept}
        self._ordered = kept + [skill for skill in globals_ if skill.name not in tenant_names]
        self._by_name = dict(global_by_name)
        self._by_name.update({skill.name: skill for skill in kept})
        self._by_trigger = dict(global_by_trigger)
        for skill in kept:
            for trigger in skill.triggers:
                self._by_trigger[trigger] = skill
        self.report = TenantTreeReport(
            tenant=self.tenant,
            skills_dir=self._tenant_registry.skills_dir,
            loaded=len(kept),
            shadowing=tuple(shadowing),
            shadowed_triggers=tuple(shadowed_triggers),
            dropped=tuple(dropped),
        )
        return self

    def get(self, trigger: str) -> Optional[SkillDefinition]:
        """Return the skill matching ``trigger`` in this view."""
        return self._by_trigger.get(trigger)

    def get_by_name(self, name: str) -> Optional[SkillDefinition]:
        """Return the skill named ``name`` in this view."""
        return self._by_name.get(name)

    def list_skills(self) -> List[SkillDefinition]:
        """Return effective skills: tenant first, then unshadowed globals."""
        return list(self._ordered)

    def has_trigger(self, trigger: str) -> bool:
        """Return whether ``trigger`` resolves in this view."""
        return trigger in self._by_trigger
