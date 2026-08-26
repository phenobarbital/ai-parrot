"""
Composer — deterministic expansion of catalogued actions into a flat,
executable sequence.

Handles:

- **Prerequisites** (``SiteAction.requires``): injected before the action
  the first time they are needed; a prerequisite already satisfied earlier
  in the sequence (e.g. ``login``) is never re-run.
- **Composite actions** (``kind="composite"``): expanded depth-first in
  declared order, binding child parameters from the parent's parameters.
- **Safety**: cycle detection and a hard recursion depth cap, so a broken
  catalog can never produce an unbounded plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from .catalog import ActionCatalog
from .models import SiteAction, slugify
from .templating import render_value, resolve_params

#: Hard cap on composite nesting (a composite referencing a composite ...).
MAX_COMPOSE_DEPTH = 5


@dataclass
class ResolvedAction:
    """One executable entry of an expanded sequence.

    Attributes:
        action: The catalogued action (non-composite by construction).
        params: Fully-resolved parameter values for this execution.
        injected: True when the entry was injected as a prerequisite
            rather than requested explicitly.
    """

    action: SiteAction
    params: Dict[str, Any]
    injected: bool = False


@dataclass
class _ExpandState:
    """Mutable bookkeeping shared across one expansion run."""

    satisfied: Set[str] = field(default_factory=set)
    stack: Tuple[str, ...] = ()


async def expand_action(
    catalog: ActionCatalog,
    site: str,
    action_name: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    include_requires: bool = True,
    _state: Optional[_ExpandState] = None,
    _depth: int = 0,
    _injected: bool = False,
) -> List[ResolvedAction]:
    """Expand one action into a flat list of executable entries.

    Args:
        catalog: Source catalog.
        site: Site reference (slug/alias/domain).
        action_name: Action to expand.
        params: Caller-provided parameter values.
        include_requires: Inject ``requires`` prerequisites (deduplicated
            across the whole expansion).

    Returns:
        Ordered, flat list of :class:`ResolvedAction` (composites fully
        expanded away).

    Raises:
        ValueError: On composition cycles, excessive nesting depth, or
            missing required parameters.
        KeyError: When the action (or a referenced action) is missing.
    """
    state = _state or _ExpandState()
    name = slugify(action_name)

    if name in state.stack:
        chain = " -> ".join((*state.stack, name))
        raise ValueError(f"Action composition cycle detected: {chain}")
    if _depth > MAX_COMPOSE_DEPTH:
        raise ValueError(
            f"Action composition exceeds the maximum nesting depth of "
            f"{MAX_COMPOSE_DEPTH} (at {name!r})"
        )

    action = await catalog.get_action(site, name)
    try:
        resolved_params = resolve_params(action.params, params)
    except ValueError as exc:
        raise ValueError(f"action {name!r}: {exc}") from exc
    sequence: List[ResolvedAction] = []

    inner_state = _ExpandState(
        satisfied=state.satisfied, stack=(*state.stack, name)
    )

    # Prerequisites first — only once per expansion run.
    if include_requires:
        for req in action.requires:
            if req in state.satisfied:
                continue
            sequence.extend(
                await expand_action(
                    catalog,
                    site,
                    req,
                    # Prerequisites see the caller's params so a composite
                    # can forward e.g. credentials profile selection.
                    dict(resolved_params),
                    include_requires=include_requires,
                    _state=inner_state,
                    _depth=_depth + 1,
                    _injected=True,
                )
            )

    if action.kind == "composite":
        for ref in action.compose:
            child_params = {
                key: render_value(value, resolved_params)
                for key, value in ref.params.items()
            }
            # Unbound parent params flow through so children can pick up
            # shared values (e.g. customer name) without explicit binding.
            merged = {**resolved_params, **child_params}
            sequence.extend(
                await expand_action(
                    catalog,
                    site,
                    ref.action,
                    merged,
                    include_requires=include_requires,
                    _state=inner_state,
                    _depth=_depth + 1,
                    _injected=_injected,
                )
            )
    else:
        sequence.append(
            ResolvedAction(
                action=action, params=resolved_params, injected=_injected
            )
        )

    state.satisfied.add(name)
    return sequence


async def expand_sequence(
    catalog: ActionCatalog,
    site: str,
    plan: Sequence[Union[str, Dict[str, Any]]],
    shared_params: Optional[Dict[str, Any]] = None,
    *,
    include_requires: bool = True,
) -> List[ResolvedAction]:
    """Expand an ordered plan of actions into one flat sequence.

    Prerequisites are deduplicated across the WHOLE plan: if the first
    entry already performed ``login``, later entries requiring it will
    not re-run it.

    Args:
        catalog: Source catalog.
        site: Site reference (slug/alias/domain).
        plan: Ordered entries — either an action name or a dict of the
            form ``{"action": name, "params": {...}}``.
        shared_params: Parameter values applied to every entry (entry
            params take precedence).
        include_requires: Inject ``requires`` prerequisites.

    Returns:
        Ordered, flat list of :class:`ResolvedAction`.

    Raises:
        ValueError: On malformed plan entries or expansion errors.
    """
    state = _ExpandState()
    sequence: List[ResolvedAction] = []
    for idx, entry in enumerate(plan):
        if isinstance(entry, str):
            name, entry_params = entry, {}
        elif isinstance(entry, dict) and "action" in entry:
            name = str(entry["action"])
            entry_params = dict(entry.get("params") or {})
        else:
            raise ValueError(
                f"plan[{idx}]: expected an action name or "
                f"{{'action': ..., 'params': {{...}}}}, got {entry!r}"
            )
        merged = {**(shared_params or {}), **entry_params}
        sequence.extend(
            await expand_action(
                catalog,
                site,
                name,
                merged,
                include_requires=include_requires,
                _state=state,
            )
        )
    return sequence
