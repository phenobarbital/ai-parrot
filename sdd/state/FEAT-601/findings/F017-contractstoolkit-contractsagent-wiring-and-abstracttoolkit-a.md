---
id: F017
query_id: Q017
type: read
intent: ContractsToolkit attrs + tool signatures; ContractsAgent build; AbstractToolkit attr anchors
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F017 — ContractsToolkit / ContractsAgent wiring and AbstractToolkit attributes

## Summary
`ContractsToolkit(AbstractToolkit)` sets `name="contracts"`, `tool_prefix="contracts"`, `confirming_tools={"verify_card","retire_answer"}` and `exclude_tools=("get_tools","get_tools_sync")`. Its constructor takes keyword-only `service`, a trusted `request_context`, `library` and `relations`, and every tool calls `_gate()`, which runs `retrieval.authorize`. `ContractsAgent(Agent)` creates the toolkit before `super().__init__` because `Agent.__init__` calls `agent_tools()`. It defaults `system_prompt` to `CONTRACTS_SYSTEM_PROMPT` and sends every answer through `service.answer(..., producer=ContractsAgentProducer)`. The ReAct draft is a private `super().ask(use_conversation_history=False)`, and the public `ask`, `ask_stream` and `invoke` all refuse. In AbstractToolkit, `tool_prefix` defaults to None and is idempotent (it won't double-prefix), and `confirming_tools` sets `routing_meta["requires_confirmation"]`.

## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py`
  lines: 39-72
  symbol: `ContractsToolkit`, `ContractsToolkit.__init__`
  excerpt: |
    class ContractsToolkit(AbstractToolkit):
        name: str = "contracts"
        tool_prefix: str = "contracts"
        confirming_tools: frozenset = frozenset({"verify_card", "retire_answer"})
        exclude_tools: tuple[str, ...] = ("get_tools", "get_tools_sync")
        def __init__(self, *, service: ContractsAnswerService, request_context: RequestContext,
                     library: Any = None, relations: Any = None, **kwargs: Any) -> None:
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py`
  lines: 84-107
  symbol: `ContractsToolkit._gate`, `ContractsToolkit.catalog_search`
  excerpt: |
    def _gate(self, *, owner_only: bool = False) -> None:
        self.retrieval.authorize(self.request_context, owner_only=owner_only)
    async def catalog_search(self, query: str, top_k: int = 8) -> dict[str, Any]:
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py`
  lines: 109-301
  symbol: `get_card`, `get_toc`, `read_section`, `obligations`, `expiring`, `verification_queue`, `related_contracts`
  excerpt: |
    109: async def get_card(self, contract_id: str) -> dict[str, Any]:
    134: async def get_toc(self, contract_id: str) -> dict[str, Any]:
    150: async def read_section(self, contract_id: str, node_id: str) -> dict[str, Any]:
    196: async def obligations(
    233: async def expiring(self, days: int = 90, by_notice: bool = True) -> dict[str, Any]:
    257: async def verification_queue(self, limit: int = 20) -> dict[str, Any]:
    282: async def related_contracts(self, contract_id: str) -> dict[str, Any]:
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py`
  lines: 305-376
  symbol: `ContractsToolkit.verify_card`, `ContractsToolkit.retire_answer`
  excerpt: |
    async def verify_card(self, contract_id: str, fields: Optional[dict[str, Any]] = None,
        merge_party_id: Optional[str] = None, keep_party_id: Optional[str] = None,
        owner_employee_id: Optional[str] = None, expected_revision: Optional[int] = None) -> dict[str, Any]:
    async def retire_answer(self, answer_id: str, reason: str) -> dict[str, Any]:
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py`
  lines: 29-37
  symbol: `imports`
  excerpt: |
    from parrot.bots import Agent
    from parrot.knowledge.contracts.models import ContractAnswer, ContractCard
    from .flow import ContractsDraftProducer
    from .service import AnswerOutcome, ContractsAnswerService
    from .toolkit import ContractsToolkit
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py`
  lines: 232-268
  symbol: `ContractsAgent`, `ContractsAgent.__init__`, `ContractsAgent.agent_tools`
  excerpt: |
    class ContractsAgent(Agent):
        agent_id: str = "contracts_agent"
        temperature: float = 0.1
        ...
            kwargs.setdefault("system_prompt", CONTRACTS_SYSTEM_PROMPT)
            self.toolkit = ContractsToolkit(service=service, request_context=request_context, library=library)
            # Agent.__init__ calls agent_tools, so initialize the toolkit first.
            super().__init__(*args, **kwargs)
            self.producer = ContractsAgentProducer(self)
        def agent_tools(self) -> list[Any]: return self.toolkit.get_tools()
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py`
  lines: 270-326
  symbol: `ContractsAgent.answer_question`, `ContractsAgent._draft_reply`
  excerpt: |
    return await self.service.answer(question, request_context=context, producer=self.producer)
    ...
    return await super().ask(prompt, user_id=self._request_context.get().user_id,
        session_id=f"contracts-draft-{uuid.uuid4().hex}", use_conversation_history=False)
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py`
  lines: 338-353
  symbol: `ContractsAgent.ask`, `ask_stream`, `invoke`, `released_answer`
  excerpt: |
    def ask(...): Refuse: use :meth:`answer_question`, which passes the gate.
    def released_answer(outcome: AnswerOutcome | Clarification) -> Optional[ContractAnswer]:
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 231-272
  symbol: `AbstractToolkit.return_direct`, `exclude_tools`, `tool_prefix`, `prefix_separator`, `confirming_tools`
  excerpt: |
    input_class: type[BaseModel] | None = None
    return_direct: bool = False  # Whether tools return results directly
    exclude_tools: tuple[str, ...] = ()
    tool_prefix: str | None = None
    prefix_separator: str = "_"
    confirming_tools: frozenset = frozenset()
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 694-699
  symbol: `AbstractToolkit._create_tool_from_method`
  excerpt: |
    # confirming_tools set stays stable regardless of tool_prefix.
    if method_name in self.confirming_tools:
        tool.routing_meta["requires_confirmation"] = True

## Notes
- WRONG in the brainstorm: there is no `structured_output=ContractAnswer`. `ContractAnswer` is built and released by `ContractsAnswerService` after `CitationVerifier` runs (service.py L145-212, verifier.py L114-206). For ProcedureAnswer, the proposal has to pick one of two routes: copy this producer→verifier→service gate, or actually use `structured_output`.
- Tools are generated from public async methods (toolkit.py L547-590). Names come out as `contracts_<method>`.

