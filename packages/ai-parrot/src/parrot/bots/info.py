"""InfoAgent — infographic-capable agent with sandboxed Python execution.

A general-purpose agent pre-composed with :class:`NarrativeMixin` and
:class:`InfographicAuthoringMixin` on top of :class:`Agent`, plus a
sandboxed :class:`PythonREPLTool` for data manipulation.

Unlike :class:`PandasAgent`, ``InfoAgent`` does **not** bundle a
``DatasetManager`` or DataFrame-centric tooling — data access is the
consumer's concern (MCP servers, REST tools, database toolkits, etc.).
This makes it the right base for any agent that needs to *produce*
infographics or narrative reports without being tied to the pandas
data-analysis workflow.

Usage::

    from parrot.bots import InfoAgent

    class MyReporter(InfoAgent):
        llm = "anthropic:claude-sonnet-4-20250514"
        narrative_skill = "my-narrative-skill"

        def agent_tools(self):
            # Add domain-specific tools alongside the REPL
            return [*super().agent_tools(), MyCustomTool()]
"""
from __future__ import annotations

from typing import Any, List, Optional

from ..tools.abstract import AbstractTool
from ..tools.pythonrepl import PythonREPLTool
from .agent import Agent
from .mixins.infographic_authoring import InfographicAuthoringMixin
from .mixins.narrative import NarrativeMixin


class InfoAgent(NarrativeMixin, InfographicAuthoringMixin, Agent):
    """Agent with built-in infographic authoring, narrative, and Python REPL.

    Composes:

    - **NarrativeMixin** — figure-guarded prose generation via skills.
    - **InfographicAuthoringMixin** — tier-1/tier-2 infographic authoring
      (``generate_infographic``, ``publish_recipe``).
    - **Agent** — tool-using ReAct reasoning loop.
    - **PythonREPLTool** — sandboxed Python execution for data transformation
      and analysis (wired via :meth:`agent_tools`).

    Data sources are NOT baked in — attach them via constructor ``tools``,
    MCP servers, or any other mechanism. The REPL is available for the LLM
    to transform/aggregate whatever data the tools provide.

    Args:
        name: Agent display name.
        enable_repl: When ``True`` (default), a :class:`PythonREPLTool` is
            included in the agent's tool set.  Set to ``False`` if the
            subclass provides its own REPL variant (e.g. ``PythonPandasTool``).
        repl_config: Optional kwargs forwarded to the :class:`PythonREPLTool`
            constructor (``setup_code``, ``policy``, ``worker_config``, etc.).
        **kwargs: Forwarded to :class:`Agent`.
    """

    def __init__(
        self,
        *args: Any,
        enable_repl: bool = True,
        repl_config: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._enable_repl = enable_repl
        self._repl_config = repl_config or {}
        super().__init__(*args, **kwargs)

    def agent_tools(self) -> List[AbstractTool]:
        """Return the agent-specific tools including the sandboxed Python REPL.

        Subclasses that override this should call ``super().agent_tools()``
        to preserve the REPL (unless they set ``enable_repl=False`` and
        provide their own variant).
        """
        tools = super().agent_tools()
        if self._enable_repl:
            tools.append(PythonREPLTool(**self._repl_config))
        return tools
