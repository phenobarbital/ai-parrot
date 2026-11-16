"""Accounting model loader (FEAT-713 M4): selectors, resolved natures, validation, hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

import yaml
from pydantic import BaseModel, ValidationError

from .errors import ModelValidationError, Problem
from .models import AccountingModel, AccountingModelSpec, AccountSet, ChartSnapshot, ResolvedSet
from .validation import partition_intervals, validate


def canonical_json(obj: BaseModel) -> str:
    """Sorted keys, no whitespace, Decimals as strings — the hashing representation."""
    return json.dumps(obj.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))


def load_spec(source: Path | dict) -> AccountingModelSpec:
    """Parse a model YAML (or dict) into an ``AccountingModelSpec``.

    Args:
        source: A YAML file path or an already-parsed mapping.

    Returns:
        The validated spec.

    Raises:
        ModelValidationError: On unreadable/non-mapping YAML or any schema error (one problem per error).
    """
    data: object = source
    if isinstance(source, Path):
        try:
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ModelValidationError(
                [Problem(code="dangling_ref", message=f"cannot read model file {source}: {exc}")]
            ) from exc
    if not isinstance(data, dict):
        raise ModelValidationError([Problem(code="dangling_ref", message="model document must be a mapping")])
    try:
        return AccountingModelSpec.model_validate(data)
    except ValidationError as exc:
        problems = [
            Problem(
                code="dangling_ref",
                message=f"schema error at {'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}",
            )
            for err in exc.errors()
        ]
        raise ModelValidationError(problems) from exc


def _select(account_set: AccountSet, snapshot: ChartSnapshot) -> set[str]:
    """Accounts picked by the set's selector (empty when it has none)."""
    selector = account_set.select
    if selector is None:
        return set()
    picked: set[str] = set()
    for account in snapshot.accounts:
        account_id = account.account_id
        if selector.prefix is not None and account_id.startswith(selector.prefix):
            picked.add(account_id)
        if selector.range is not None and selector.range[0] <= account_id <= selector.range[1]:
            picked.add(account_id)
        if selector.tag is not None and selector.tag in account.tags:
            picked.add(account_id)
    return picked


def _resolve_sets(spec: AccountingModelSpec, snapshot: ChartSnapshot) -> dict[str, ResolvedSet]:
    """accounts ∪ select(prefix | range | tag) − except, sorted; valid_from / valid_to kept."""
    resolved: dict[str, ResolvedSet] = {}
    for name, account_set in spec.sets.items():
        members = (set(account_set.accounts) | _select(account_set, snapshot)) - set(account_set.except_)
        resolved[name] = ResolvedSet(
            name=name,
            accounts=tuple(sorted(members)),
            valid_from=account_set.valid_from,
            valid_to=account_set.valid_to,
        )
    return resolved


def _resolve_natures(
    spec: AccountingModelSpec, snapshot: ChartSnapshot, resolved: Mapping[str, ResolvedSet]
) -> tuple[tuple[str, str], ...]:
    """Sorted unique ``(account, nature)`` for every selected account that has a nature."""
    selected = {account for resolved_set in resolved.values() for account in resolved_set.accounts}
    snapshot_natures = {account.account_id: account.nature for account in snapshot.accounts}
    nature = spec.chart_of_accounts.nature
    explicit = nature.accounts if nature is not None and nature.accounts is not None else None
    pairs: list[tuple[str, str]] = []
    for account in sorted(selected):
        value = explicit.get(account) if explicit is not None else None
        if value is None:
            value = snapshot_natures.get(account)
        if value is not None:
            pairs.append((account, value))
    return tuple(pairs)


def load_model(
    source: Path | dict, snapshot: ChartSnapshot, *, columns: Mapping[str, str] | None = None
) -> AccountingModel:
    """Resolve selectors, partition intervals, validate (ALL problems), hash. Raises ModelValidationError."""
    spec = load_spec(source)
    resolved = _resolve_sets(spec, snapshot)
    problems = validate(spec, resolved, snapshot, columns)
    if problems:
        raise ModelValidationError(problems)
    natures = _resolve_natures(spec, snapshot, resolved)
    intervals = partition_intervals(spec.sets)
    draft = AccountingModel(
        spec=spec,
        snapshot_hash=snapshot.snapshot_hash,
        natures=natures,
        intervals=intervals,
        sets=resolved,
        model_hash="",
    )
    payload = canonical_json(draft).encode() + snapshot.snapshot_hash.encode()
    return draft.model_copy(update={"model_hash": hashlib.sha256(payload).hexdigest()})


def detect_drift(model: AccountingModel, fresh: ChartSnapshot) -> tuple[str, ...]:
    """Accounts in *fresh* that no set of *model* covers and no exclusion lists, sorted."""
    known = {account for resolved_set in model.sets.values() for account in resolved_set.accounts}
    known |= {account for exclusion in model.spec.excluded for account in exclusion.accounts}
    return tuple(sorted(account.account_id for account in fresh.accounts if account.account_id not in known))
