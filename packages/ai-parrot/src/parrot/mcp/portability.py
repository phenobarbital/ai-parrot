"""Shared command-form decision for installer emitters."""

from __future__ import annotations

import dataclasses
import sys
from typing import Literal

from parrot.launcher import managed_launcher_on_path

PortableReason = Literal["explicit", "sticky", "launcher", "baked-fallback"]


@dataclasses.dataclass(frozen=True)
class PortableDecision:
    """Chosen form, provenance and optional fallback explanation."""

    portable: bool
    reason: PortableReason
    note: str | None


BAKED_NOTE_TEMPLATE: str = (
    "note: host config baked to absolute paths ({prefix}); install the global launcher "
    "(install-parrot.sh --global) and re-run with --portable to commit a machine-independent config"
)


def resolve_portable_mode(explicit: bool | None, *, current: bool | None) -> PortableDecision:
    """Resolve explicit, sticky, launcher and baked-fallback choices in that order."""
    if explicit is not None:
        return PortableDecision(explicit, "explicit", None)
    if current is not None:
        return PortableDecision(current, "sticky", None)
    if managed_launcher_on_path():
        return PortableDecision(True, "launcher", None)
    return PortableDecision(False, "baked-fallback", BAKED_NOTE_TEMPLATE.format(prefix=sys.prefix))
