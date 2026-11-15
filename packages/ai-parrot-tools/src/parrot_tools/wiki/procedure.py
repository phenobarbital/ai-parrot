"""Procedure plane tool (FEAT-891): the framework wrapper of ``wiki_procedure_next``."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from parrot.knowledge.wiki.procedure.operations import (
    PROCEDURE_NEXT_DESCRIPTION,
    ProcedureNextInput,
    op_procedure_next,
    procedure_plane_available,
)
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.abstract import AbstractTool, ToolResult


class WikiProcedureNextTool(AbstractTool):
    """Deterministic next step in the repository's procedure graph."""

    name = "wiki_procedure_next"
    description = PROCEDURE_NEXT_DESCRIPTION
    args_schema = ProcedureNextInput

    def __init__(self, root: Path) -> None:
        super().__init__(name=self.name, description=self.description)
        self._root = root

    async def _execute(self, feature: Optional[str] = None, task: Optional[str] = None) -> ToolResult:
        """Resolve the next valid step(s) with local probes only."""
        result = await op_procedure_next(None, ProcedureNextInput(feature=feature, task=task), root=self._root)
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.data if result.data is not None else result.text)


def create_procedure_tools(store: BaseWikiStore, root: Optional[Path], config: WikiProjectConfig) -> list[AbstractTool]:
    """[WikiProcedureNextTool] when <shared-root>/.parrot/procedure/procedures.json exists, else []."""
    del store, config
    if root is None or not procedure_plane_available(root):
        return []
    return [WikiProcedureNextTool(root)]
