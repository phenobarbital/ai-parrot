"""Runner registry: built-ins merged with `.parrot/test_runners.toml` (FEAT-709 M1). Stdlib only."""

from __future__ import annotations

import importlib
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..policy import TIERS
from .base import DEFAULT_TIMEOUTS, RunnerAdapter, normalize_launcher_argv

CONFIG_PATH: str = ".parrot/test_runners.toml"
BUILTIN_MODULES: Mapping[str, str] = {
    "pytest": "pytest",
    "vitest": "vitest",
    "cargo": "cargo",
    "parrot-e2e": "parrot_e2e",
}


class RunnerRegistry:
    """Resolve adapters by kind or argv; carries per-kind settings."""

    def __init__(self, adapters: Mapping[str, RunnerAdapter], settings: Mapping[str, Mapping[str, str]]) -> None:
        self._adapters = dict(adapters)
        self._settings = {kind: dict(value) for kind, value in settings.items()}

    def adapter_for_kind(self, kind: str) -> RunnerAdapter:
        """Return the adapter for ``kind`` or raise KeyError listing known kinds."""
        adapter = self._adapters.get(kind)
        if adapter is not None:
            return adapter

        module_name = BUILTIN_MODULES.get(kind)
        if module_name is None:
            known_kinds = ", ".join(sorted({*BUILTIN_MODULES, *self._adapters}))
            raise KeyError(f"Unknown runner {kind!r}; known kinds: {known_kinds}")

        module = importlib.import_module(f"{__package__}.{module_name}")
        adapter = module.ADAPTER
        self._adapters[kind] = adapter
        return adapter

    def adapter_for_argv(self, argv: Sequence[str]) -> RunnerAdapter | None:
        """Normalise the launcher chain, then return its first matching adapter."""
        normalized = normalize_launcher_argv(argv, pnpm_test_is_vitest=self._pnpm_test_is_vitest())
        for kind in (*BUILTIN_MODULES, *(key for key in self._adapters if key not in BUILTIN_MODULES)):
            try:
                adapter = self.adapter_for_kind(kind)
            except ModuleNotFoundError:
                continue
            if adapter.matches(normalized):
                return adapter
        return None

    def settings_for(self, kind: str) -> Mapping[str, str]:
        """Return a copy of the configured settings for ``kind``."""
        return dict(self._settings.get(kind, {}))

    def tiers_for(self, kind: str) -> frozenset[str]:
        """Return configured eligible tiers, rejecting tiers outside adapter support."""
        adapter = self.adapter_for_kind(kind)
        configured = self._settings.get(kind, {}).get("tiers")
        if configured is None or not configured.strip():
            return adapter.default_tiers
        tiers = frozenset(tier.strip() for tier in configured.split(",") if tier.strip())
        invalid = tiers - adapter.default_tiers
        if invalid:
            raise ValueError(f"Runner {kind!r} does not support tiers: {', '.join(sorted(invalid))}")
        return tiers

    def timeout_for(self, kind: str) -> int:
        """Return the configured or built-in timeout in seconds."""
        return int(self._settings.get(kind, {}).get("timeout_s", DEFAULT_TIMEOUTS.get(kind, 60)))

    @property
    def binaries(self) -> tuple[str, ...]:
        """Return sorted executable names for every currently loadable adapter."""
        binaries: set[str] = set()
        for kind in (*BUILTIN_MODULES, *(key for key in self._adapters if key not in BUILTIN_MODULES)):
            try:
                binaries.update(self.adapter_for_kind(kind).binaries)
            except ModuleNotFoundError:
                continue
        return tuple(sorted(binaries))

    def _pnpm_test_is_vitest(self) -> bool:
        return str(self._settings.get("vitest", {}).get("test_script", "true")).lower() != "false"


def _settings_from_toml(raw_settings: Mapping[str, Any]) -> dict[str, str]:
    """Convert a TOML runner table to the string-valued kernel settings contract."""
    settings: dict[str, str] = {}
    for key, value in raw_settings.items():
        if isinstance(value, list):
            if not all(isinstance(item, str) for item in value):
                raise ValueError(f"{CONFIG_PATH}: runners settings lists must contain strings")
            settings[key] = ",".join(value)
        elif isinstance(value, (str, int, float, bool)):
            settings[key] = str(value)
        else:
            raise ValueError(f"{CONFIG_PATH}: runners settings must be scalar values")
    return settings


def _extension_adapter(kind: str, target: object) -> RunnerAdapter:
    """Import, construct, and verify one configured extension adapter."""
    if not isinstance(target, str) or target.count(":") != 1:
        raise ValueError(f"{CONFIG_PATH}: extension {kind!r} must be 'module:Class'")
    module_name, class_name = target.split(":", 1)
    if not module_name or not class_name:
        raise ValueError(f"{CONFIG_PATH}: extension {kind!r} must be 'module:Class'")
    try:
        adapter_class = getattr(importlib.import_module(module_name), class_name)
        adapter = adapter_class()
    except Exception as exc:
        raise ValueError(f"{CONFIG_PATH}: unable to load extension {kind!r}: {exc}") from exc
    if not isinstance(adapter, RunnerAdapter):
        raise ValueError(f"{CONFIG_PATH}: extension {kind!r} does not implement RunnerAdapter")
    return adapter


def load_registry(worktree: Path) -> RunnerRegistry:
    """Load TOML settings and extensions, failing closed for every invalid input."""
    path = Path(worktree) / CONFIG_PATH
    if not path.is_file():
        return RunnerRegistry({}, {})
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"{CONFIG_PATH}: invalid TOML: {exc}") from exc
    if not isinstance(data, dict) or set(data) - {"runners", "extensions"}:
        raise ValueError(f"{CONFIG_PATH}: only [runners] and [extensions] are allowed")

    runners_raw = data.get("runners", {})
    extensions_raw = data.get("extensions", {})
    if not isinstance(runners_raw, dict) or not isinstance(extensions_raw, dict):
        raise ValueError(f"{CONFIG_PATH}: [runners] and [extensions] must be tables")

    adapters: dict[str, RunnerAdapter] = {}
    for kind, target in extensions_raw.items():
        if not isinstance(kind, str):
            raise ValueError(f"{CONFIG_PATH}: extension names must be strings")
        adapters[kind] = _extension_adapter(kind, target)

    settings: dict[str, dict[str, str]] = {}
    for kind, raw_settings in runners_raw.items():
        if not isinstance(kind, str) or kind not in {*BUILTIN_MODULES, *adapters}:
            raise ValueError(f"{CONFIG_PATH}: unknown runner {kind!r}")
        if not isinstance(raw_settings, dict):
            raise ValueError(f"{CONFIG_PATH}: [runners.{kind}] must be a table")
        setting = _settings_from_toml(raw_settings)
        tiers = setting.get("tiers")
        if tiers is not None:
            invalid = {tier.strip() for tier in tiers.split(",") if tier.strip()} - set(TIERS)
            if invalid:
                raise ValueError(f"{CONFIG_PATH}: invalid tiers for {kind!r}: {', '.join(sorted(invalid))}")
        settings[kind] = setting
    return RunnerRegistry(adapters, settings)
