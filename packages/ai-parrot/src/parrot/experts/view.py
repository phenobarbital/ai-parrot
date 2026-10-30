"""Name-based overlay of expert bundle sets with SkillView semantics (FEAT-778 M2)."""

from __future__ import annotations

import logging
from typing import Sequence

from parrot.experts.models import ExpertBundle

_LOGGER = logging.getLogger(__name__)


class ExpertView:
    """Overlay expert bundles by name while respecting global-only locks."""

    def __init__(
        self,
        base: Sequence[ExpertBundle],
        overlay: Sequence[ExpertBundle],
        *,
        label: str,
        logger: logging.Logger = _LOGGER,
    ) -> None:
        """Compose an expert view.

        Args:
            base: Wider-scope expert bundles.
            overlay: Narrower-scope expert bundles.
            label: Scope label used in diagnostics, such as ``workspace`` or ``tenant:acme``.
            logger: Logger used for global-only conflicts.
        """
        self.label = label
        self.logger = logger
        self._by_name: dict[str, ExpertBundle] = {bundle.manifest.name: bundle for bundle in base}
        self._shadowing: dict[str, str] = {}
        for bundle in overlay:
            name = bundle.manifest.name
            existing = self._by_name.get(name)
            if existing is not None and existing.manifest.global_only:
                self.logger.warning(
                    "%s expert %s (%s) conflicts with global_only expert (%s); dropping overlay bundle",
                    self.label,
                    name,
                    bundle.root,
                    existing.root,
                )
                continue
            if existing is not None:
                self._shadowing[name] = str(bundle.root)
            self._by_name[name] = bundle

    def resolve(self, name: str) -> ExpertBundle | None:
        """Return the effective expert bundle named ``name``, if present."""
        return self._by_name.get(name)

    def bundles(self) -> list[ExpertBundle]:
        """Return effective expert bundles ordered by name."""
        return [self._by_name[name] for name in sorted(self._by_name)]

    @property
    def shadowing(self) -> dict[str, str]:
        """Return a copy of the name-to-overlay-path shadowing report."""
        return dict(self._shadowing)
