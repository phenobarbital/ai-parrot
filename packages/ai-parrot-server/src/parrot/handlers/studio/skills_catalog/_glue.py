"""Request-less glue over the legacy catalogue persistence helpers, for non-HTTP callers (the meta-agent tool)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from ._catalog_legacy import _StudioSkillsCatalogLegacyMixin
from ._mixin import _StudioSkillsMixin


class SkillsCatalogGlue(_StudioSkillsCatalogLegacyMixin, _StudioSkillsMixin):
    """The SAME ``_insert_entry`` / ``_dual_write_to_registry`` / ``_flag_stale`` the HTTP handler uses, minus a request.

    The helpers only need ``self.request.app`` and ``self.logger``; both are plain attributes here (the HTTP views
    expose ``request`` as a read-only property, so a handler instance cannot be built without a real request).
    """

    def __init__(self, app: Any) -> None:
        self.request = SimpleNamespace(app=app)
        self.logger = logging.getLogger("Parrot.AgentStudio.PublishSkill")
