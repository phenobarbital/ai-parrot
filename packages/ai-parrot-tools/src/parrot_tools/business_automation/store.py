"""PlanDirectoryStore — loads BusinessOperation/TemplatePlan/ScrapingFlow
definitions from an external, private plans directory.

FEAT-453, Module 6 (Goal G4). Per the spec's public/private seam, this
engine is public; the plans it drives (credentials, selectors, real business
identifiers) are not — they live in a directory outside this repository,
configured at runtime. This store is deliberately distinct from
:class:`~parrot_tools.scraping.registry.PlanRegistry`, which is
fingerprint-keyed and reads *inside* the repo tree for scraped/cached plans;
this store is operation-keyed and reads an *external* directory of
hand-authored definitions.

File naming convention within the plans directory:
    - ``*.operation.json`` — a :class:`BusinessOperation`
    - ``*.template.json``  — a :class:`~parrot_tools.scraping.TemplatePlan`
    - ``*.flow.json``       — a :class:`~parrot_tools.scraping.ScrapingFlow`

Directory contents are untrusted input (authored outside the repo, driving a
browser against a financial system): any malformed file, or any
``.template.json`` carrying a literal ``authenticate`` password (TASK-2389's
lint), rejects the **whole directory** — never silently skips one file.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Union

from pydantic import ValidationError

from parrot_tools.scraping import ScrapingFlow, TemplatePlan
from parrot_tools.scraping.models import lint_literal_credentials

from .models import BusinessOperation

logger = logging.getLogger(__name__)


class PlanDirectoryStore:
    """Loads and hot-reloads business-operation definitions from a directory.

    Args:
        plans_dir: External, private directory containing
            ``*.operation.json`` / ``*.template.json`` / ``*.flow.json``
            files.

    Attributes:
        operations: Loaded :class:`BusinessOperation`\\ s, keyed by name.
        templates: Loaded ``TemplatePlan``\\ s, keyed by name.
        flows: Loaded ``ScrapingFlow``\\ s, keyed by name.
    """

    def __init__(self, plans_dir: Union[str, Path]) -> None:
        self.plans_dir = Path(plans_dir)
        self.operations: Dict[str, BusinessOperation] = {}
        self.templates: Dict[str, TemplatePlan] = {}
        self.flows: Dict[str, ScrapingFlow] = {}
        self._mtimes: Dict[Path, float] = {}

    def load(self) -> None:
        """(Re)load every definition file in ``plans_dir``.

        The directory is scanned and parsed into local (not-yet-committed)
        registries first; only once every file has been validated
        successfully are ``self.operations``/``self.templates``/``self.flows``
        replaced atomically. A failed load therefore leaves any previously
        loaded (good) state untouched.

        Raises:
            ValueError: On the first malformed file or credential-lint
                violation, naming the offending filename and reason. Never
                silently skips a bad file — the whole directory is rejected.
        """
        if not self.plans_dir.is_dir():
            raise ValueError(f"Plans directory does not exist: {self.plans_dir}")

        operations: Dict[str, BusinessOperation] = {}
        templates: Dict[str, TemplatePlan] = {}
        flows: Dict[str, ScrapingFlow] = {}
        mtimes: Dict[Path, float] = {}

        for path in sorted(self.plans_dir.glob("*.json")):
            mtimes[path] = path.stat().st_mtime

            try:
                raw: Dict[str, Any] = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}: invalid JSON — {exc}") from exc

            if path.name.endswith(".operation.json"):
                try:
                    op = BusinessOperation(**raw)
                except ValidationError as exc:
                    raise ValueError(
                        f"{path.name}: BusinessOperation schema validation failed — {exc}"
                    ) from exc
                operations[op.name] = op

            elif path.name.endswith(".template.json"):
                lint_warnings = lint_literal_credentials(raw.get("steps_template", []))
                if lint_warnings:
                    raise ValueError(
                        f"{path.name}: rejected — literal credential(s) in "
                        f"steps_template: {'; '.join(lint_warnings)}"
                    )
                try:
                    template = TemplatePlan(**raw)
                except ValidationError as exc:
                    raise ValueError(
                        f"{path.name}: TemplatePlan schema validation failed — {exc}"
                    ) from exc
                templates[template.name] = template

            elif path.name.endswith(".flow.json"):
                try:
                    flow = ScrapingFlow(**raw)
                except ValidationError as exc:
                    raise ValueError(
                        f"{path.name}: ScrapingFlow schema validation failed — {exc}"
                    ) from exc
                flows[flow.name] = flow

            else:
                logger.debug("Skipping unrecognized plans-dir file: %s", path.name)
                continue

        self.operations = operations
        self.templates = templates
        self.flows = flows
        self._mtimes = mtimes

        logger.info(
            "PlanDirectoryStore loaded %d operation(s), %d template(s), %d flow(s) from %s",
            len(operations), len(templates), len(flows), self.plans_dir,
        )

    def reload_if_changed(self) -> bool:
        """Hot-reload: re-scan and reload if any ``.json`` file's mtime
        changed, or a file was added/removed, since the last load.

        Returns:
            ``True`` if a reload happened, ``False`` if nothing changed.

        Raises:
            ValueError: Propagated from :meth:`load` if the changed
                directory is now malformed — the previously loaded (good)
                state is left untouched (see :meth:`load`).
        """
        if not self.plans_dir.is_dir():
            return False

        current = {p: p.stat().st_mtime for p in self.plans_dir.glob("*.json")}
        if current != self._mtimes:
            self.load()
            return True
        return False
