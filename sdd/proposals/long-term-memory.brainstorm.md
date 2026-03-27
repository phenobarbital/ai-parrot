# AI-Parrot Long-Term Memory System

## Spec Document: Unified Memory Architecture

**Version**: 1.0.0-draft  
**Author**: Auto-generated  
**Date**: 2026-03-22  
**Status**: PROPOSAL  

---

## 1. Executive Summary

This specification defines a unified long-term memory architecture for AI-Parrot agents, integrating:

1. **EpisodicMemory**: Tracks interactions, failures, and lessons learned (Reflexion pattern)
2. **SkillRegistry**: Git-like versioned knowledge base with agent-authored documentation
3. **Existing ConversationMemory**: Current turn-based conversation history

The goal is to enable agents to **learn from experience** and **improve over time**, while maintaining efficient context window usage.

---

## 2. Problem Statement

### Current State

```
┌─────────────────────────────────────────────────────────────┐
│                    CURRENT ARCHITECTURE                     │
├─────────────────────────────────────────────────────────────┤
│  ConversationMemory (Redis/File/InMemory)                  │
│    └── Stores: user_id, session_id, turns[]                │
│                                                             │
│  LocalKB (FAISS + .md files)                               │
│    └── Stores: vectorized documents per agent              │
│                                                             │
│  KnowledgeBase Stores (PgVector, etc.)                     │
│    └── Stores: facts, documents (user-provided)            │
└─────────────────────────────────────────────────────────────┘

LIMITATIONS:
- No learning from failures (agents repeat mistakes)
- No agent-authored knowledge (only user-provided)
- No versioning of knowledge
- Context injection is static (no relevance-based retrieval)
- Multi-turn errors not tracked or prevented
```

### Desired State

```
┌─────────────────────────────────────────────────────────────┐
│                    PROPOSED ARCHITECTURE                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Episodic   │  │    Skill    │  │   Conversation      │ │
│  │   Memory    │  │  Registry   │  │     Memory          │ │
│  │  (lessons)  │  │ (knowledge) │  │    (turns)          │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                     │            │
│         └────────────────┼─────────────────────┘            │
│                          │                                  │
│                   ┌──────▼──────┐                          │
│                   │  Unified    │                          │
│                   │  Memory     │                          │
│                   │  Manager    │                          │
│                   └──────┬──────┘                          │
│                          │                                  │
│         ┌────────────────┼────────────────┐                │
│         │                │                │                │
│    ┌────▼────┐     ┌─────▼─────┐    ┌─────▼─────┐        │
│    │ Context │     │  Memory   │    │   Auto    │        │
│    │Injection│     │   Tools   │    │ Learning  │        │
│    └─────────┘     └───────────┘    └───────────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Architecture Overview

### 3.1 Memory Types (CoALA Framework)

| Memory Type | Purpose | Implementation | Storage |
|-------------|---------|----------------|---------|
| **Working** | Current task state | Context window | LLM context |
| **Episodic** | Past interactions, failures | `EpisodicMemoryStore` | FAISS + Redis |
| **Semantic** | Learned facts, skills | `SkillRegistry` | FAISS + Files/Redis |
| **Procedural** | How to behave | System prompt + KB | Static files |

### 3.2 Component Overview

```
parrot/
├── memory/
│   ├── __init__.py
│   ├── abstract.py           # Existing ConversationMemory ABC
│   ├── mem.py                # Existing InMemoryConversation
│   ├── redis.py              # Existing RedisConversation
│   ├── file.py               # Existing FileConversationMemory
│   │
│   ├── episodic/             # NEW: Episodic Memory
│   │   ├── __init__.py
│   │   ├── models.py         # EpisodicMemory, MemoryNamespace
│   │   ├── store.py          # EpisodicMemoryStore
│   │   ├── tools.py          # search_episodic_memory, etc.
│   │   └── mixin.py          # EpisodicMemoryMixin
│   │
│   ├── skills/               # NEW: Skill Registry
│   │   ├── __init__.py
│   │   ├── models.py         # Skill, SkillVersion
│   │   ├── store.py          # SkillRegistry
│   │   ├── tools.py          # document_skill, search_skills
│   │   └── mixin.py          # SkillRegistryMixin
│   │
│   └── unified/              # NEW: Unified Manager
│       ├── __init__.py
│       ├── manager.py        # UnifiedMemoryManager
│       ├── mixin.py          # LongTermMemoryMixin
│       └── context.py        # ContextAssembler
```

---

## 4. Detailed Design

### 4.1 MemoryNamespace

Hierarchical namespace for multi-tenant isolation:

```python
@dataclass
class MemoryNamespace:
    org_id: str = "default"      # Organization
    agent_id: str = "default"    # Agent identifier
    user_id: str = "anonymous"   # User interacting
    session_id: Optional[str] = None  # Conversation session
    
    @property
    def redis_prefix(self) -> str:
        """Redis key prefix."""
        return f"memory:{self.org_id}:{self.agent_id}:{self.user_id}"
    
    @property
    def vector_filter(self) -> Dict[str, str]:
        """Filter for vector store queries."""
        return {
            "org_id": self.org_id,
            "agent_id": self.agent_id,
        }
```

### 4.2 EpisodicMemory Integration Points

#### 4.2.1 Post-Tool Recording

```python
# In AbstractBot._handle_tool_call() or similar
async def _execute_tool_with_memory(
    self,
    tool: AbstractTool,
    args: Dict[str, Any],
    user_query: str,
    namespace: MemoryNamespace,
) -> ToolResult:
    """Execute tool and record episode."""
    result = await tool.execute(**args)
    
    # Record episode (async, non-blocking)
    if self._episodic_memory:
        asyncio.create_task(
            self._episodic_memory.record_tool_episode(
                tool_name=tool.name,
                tool_args=args,
                tool_result=result,
                user_query=user_query,
                namespace=namespace,
            )
        )
    
    return result
```

#### 4.2.2 Context Injection

```python
# In BaseBot.create_system_prompt()
async def create_system_prompt(
    self,
    conversation_context: str = "",
    user_context: str = "",
    kb_context: str = "",
    **kwargs
) -> str:
    """Build system prompt with episodic warnings."""
    
    # Get base prompt
    base_prompt = self._build_base_system_prompt(**kwargs)
    
    # NEW: Inject episodic warnings
    episodic_context = ""
    if self._episodic_memory and self.episodic_memory_inject_warnings:
        query = kwargs.get('query', '')
        episodic_context = await self._episodic_memory.get_failure_warnings(
            query=query,
            namespace=self._get_namespace(**kwargs),
            max_warnings=3,
        )
    
    # NEW: Inject relevant skills
    skill_context = ""
    if self._skill_registry and self.skill_registry_inject_context:
        query = kwargs.get('query', '')
        skill_context = await self._skill_registry.get_relevant_skills(
            query=query,
            max_skills=3,
        )
    
    # Assemble final prompt
    return self._assemble_prompt(
        base=base_prompt,
        conversation=conversation_context,
        user=user_context,
        kb=kb_context,
        episodic=episodic_context,
        skills=skill_context,
    )
```

### 4.3 SkillRegistry Integration Points

#### 4.3.1 Auto-Extraction from Successful Interactions

```python
# Post-ask hook for skill extraction
async def _maybe_extract_skill(
    self,
    query: str,
    response: AIMessage,
    tool_calls: List[ToolCall],
):
    """Extract skill from successful complex interaction."""
    if not self._skill_registry:
        return
    
    # Only extract from successful, complex interactions
    if not tool_calls or len(tool_calls) < 2:
        return
    
    all_successful = all(tc.success for tc in tool_calls)
    if not all_successful:
        return
    
    # Build conversation for extraction
    conversation = f"""
User: {query}

Tools used: {[tc.name for tc in tool_calls]}

Result: {response.content[:500]}
"""
    
    # Extract skill (uses lightweight LLM)
    await self._skill_registry.extract_skill_from_conversation(
        conversation=conversation,
        agent_id=self.name,
        context=f"Agent: {self.name}, Role: {self.role}",
    )
```

#### 4.3.2 Skill Tools Registration

```python
# In configure() or _configure_skill_registry()
async def _add_skill_tools(self) -> None:
    """Register skill tools with tool manager."""
    tools = create_skill_tools(
        registry=self._skill_registry,
        agent_id=self.name,
        include_write_tools=True,
    )
    
    for tool in tools:
        await self.tool_manager.register_tool(tool)
```

### 4.4 UnifiedMemoryManager

Central coordinator for all memory systems:

```python
class UnifiedMemoryManager:
    """
    Coordinates episodic memory, skill registry, and conversation memory.
    
    Responsibilities:
    - Lifecycle management (configure, cleanup)
    - Namespace resolution
    - Context assembly with token budgeting
    - Memory persistence and checkpointing
    """
    
    def __init__(
        self,
        namespace: MemoryNamespace,
        conversation_memory: Optional[ConversationMemory] = None,
        episodic_store: Optional[EpisodicMemoryStore] = None,
        skill_registry: Optional[SkillRegistry] = None,
        max_context_tokens: int = 4000,
    ):
        self.namespace = namespace
        self.conversation = conversation_memory
        self.episodic = episodic_store
        self.skills = skill_registry
        self.max_context_tokens = max_context_tokens
        self._context_assembler = ContextAssembler(max_tokens=max_context_tokens)
    
    async def configure(self, **kwargs) -> None:
        """Configure all memory subsystems."""
        if self.episodic:
            await self.episodic.configure(**kwargs)
        if self.skills:
            await self.skills.configure(**kwargs)
    
    async def get_context_for_query(
        self,
        query: str,
        user_id: str,
        session_id: str,
    ) -> MemoryContext:
        """
        Assemble relevant context for a query.
        
        Returns MemoryContext with:
        - episodic_warnings: Past failure lessons
        - relevant_skills: Applicable skills
        - conversation_summary: Recent turns
        - token_budget_remaining: Available tokens
        """
        namespace = self.namespace.with_session(session_id)
        
        # Parallel retrieval
        episodic_task = self.episodic.get_failure_warnings(
            query=query,
            namespace=namespace,
        ) if self.episodic else asyncio.sleep(0)
        
        skills_task = self.skills.get_relevant_skills(
            query=query,
        ) if self.skills else asyncio.sleep(0)
        
        conv_task = self._get_conversation_context(
            user_id=user_id,
            session_id=session_id,
        )
        
        episodic, skills, conv = await asyncio.gather(
            episodic_task, skills_task, conv_task
        )
        
        return self._context_assembler.assemble(
            episodic_warnings=episodic or "",
            relevant_skills=skills or "",
            conversation=conv or "",
        )
    
    async def record_interaction(
        self,
        query: str,
        response: AIMessage,
        tool_calls: List[ToolCall],
        user_id: str,
        session_id: str,
    ) -> None:
        """Record interaction across all memory systems."""
        namespace = self.namespace.with_session(session_id)
        
        # Record tool episodes
        if self.episodic and tool_calls:
            for tc in tool_calls:
                await self.episodic.record_tool_episode(
                    tool_name=tc.name,
                    tool_args=tc.arguments,
                    tool_result=tc.result,
                    user_query=query,
                    namespace=namespace,
                )
        
        # Save conversation turn
        if self.conversation:
            turn = ConversationTurn(
                user_message=query,
                assistant_response=response.content,
                tools_used=[tc.name for tc in tool_calls] if tool_calls else [],
            )
            await self.conversation.add_turn(
                user_id=user_id,
                session_id=session_id,
                turn=turn,
            )
```

### 4.5 LongTermMemoryMixin

Single mixin that combines EpisodicMemory and SkillRegistry:

```python
class LongTermMemoryMixin:
    """
    Unified mixin for long-term memory capabilities.
    
    Combines:
    - EpisodicMemoryMixin
    - SkillRegistryMixin
    - Context assembly
    - Auto-learning hooks
    
    Usage:
        class MyAgent(LongTermMemoryMixin, AbstractBot):
            enable_long_term_memory = True
    """
    
    # Configuration
    enable_long_term_memory: bool = True
    
    # Episodic settings
    episodic_inject_warnings: bool = True
    episodic_auto_record: bool = True
    episodic_max_warnings: int = 3
    
    # Skill settings
    skill_inject_context: bool = True
    skill_auto_extract: bool = False  # Expensive, opt-in
    skill_expose_tools: bool = True
    skill_max_context: int = 3
    
    # Context budgeting
    memory_max_context_tokens: int = 2000
    
    # Runtime
    _memory_manager: Optional[UnifiedMemoryManager] = None
    
    async def _configure_long_term_memory(self) -> None:
        """Configure unified memory during agent configure()."""
        if not self.enable_long_term_memory:
            return
        
        namespace = self._create_namespace()
        
        # Create episodic store
        episodic_store = None
        if self.episodic_inject_warnings or self.episodic_auto_record:
            episodic_store = create_episodic_store(
                agent_id=self.name,
                reflection_llm=self._llm,
            )
        
        # Create skill registry
        skill_registry = None
        if self.skill_inject_context or self.skill_expose_tools:
            skill_registry = create_skill_registry(
                namespace=namespace.agent_scope,
                extraction_llm=self._llm,
            )
        
        # Create unified manager
        self._memory_manager = UnifiedMemoryManager(
            namespace=namespace,
            conversation_memory=self.conversation_memory,
            episodic_store=episodic_store,
            skill_registry=skill_registry,
            max_context_tokens=self.memory_max_context_tokens,
        )
        
        await self._memory_manager.configure()
        
        # Add tools
        if self.skill_expose_tools and skill_registry:
            await self._add_memory_tools()
    
    def _create_namespace(self) -> MemoryNamespace:
        """Create namespace from agent configuration."""
        return MemoryNamespace(
            org_id=getattr(self, 'org_id', 'default'),
            agent_id=getattr(self, 'name', 'agent'),
        )
    
    async def get_memory_context(
        self,
        query: str,
        user_id: str,
        session_id: str,
    ) -> str:
        """Get assembled memory context for system prompt."""
        if not self._memory_manager:
            return ""
        
        context = await self._memory_manager.get_context_for_query(
            query=query,
            user_id=user_id,
            session_id=session_id,
        )
        
        return context.to_prompt_string()
```

---

## 5. Agent Loop Integration

### 5.1 Modified Agent Loop

```
┌────────────────────────────────────────────────────────────────────┐
│                         AGENT LOOP                                 │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  1. RECEIVE QUERY                                                  │
│     └── user_id, session_id, query                                │
│                                                                    │
│  2. RESOLVE CONTEXT                                         [NEW]  │
│     ├── Get namespace (org/agent/user/session)                    │
│     ├── Retrieve episodic warnings (similar past failures)        │
│     ├── Retrieve relevant skills                                  │
│     └── Get recent conversation turns                             │
│                                                                    │
│  3. ASSEMBLE SYSTEM PROMPT                                  [MOD]  │
│     ├── Base prompt (backstory, role, capabilities)               │
│     ├── + Episodic warnings <past_failures_to_avoid>              │
│     ├── + Relevant skills <relevant_skills>                       │
│     ├── + KB context                                              │
│     └── + Conversation context                                    │
│                                                                    │
│  4. EXECUTE LLM                                                    │
│     ├── With memory tools (search_skills, search_memory)          │
│     └── Regular tools                                              │
│                                                                    │
│  5. HANDLE TOOL CALLS                                              │
│     └── For each tool call:                                        │
│         ├── Execute tool                                           │
│         └── Record episode (async)                          [NEW]  │
│                                                                    │
│  6. POST-RESPONSE PROCESSING                                [NEW]  │
│     ├── Save conversation turn                                     │
│     ├── Maybe extract skill (if complex successful interaction)   │
│     └── Checkpoint session state                                   │
│                                                                    │
│  7. RETURN RESPONSE                                                │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 5.2 Implementation in BaseBot.ask()

```python
async def ask(
    self,
    question: str,
    user_id: str = "anonymous",
    session_id: Optional[str] = None,
    **kwargs
) -> AIMessage:
    """Ask with long-term memory integration."""
    
    session_id = session_id or str(uuid.uuid4())
    
    # Step 2: Resolve context (NEW)
    memory_context = ""
    if self._memory_manager:
        ctx = await self._memory_manager.get_context_for_query(
            query=question,
            user_id=user_id,
            session_id=session_id,
        )
        memory_context = ctx.to_prompt_string()
    
    # Step 3: Build system prompt (MODIFIED)
    system_prompt = await self.create_system_prompt(
        query=question,  # Pass query for relevance-based retrieval
        memory_context=memory_context,
        conversation_context=await self._get_conversation_context(user_id, session_id),
        user_id=user_id,
        session_id=session_id,
        **kwargs
    )
    
    # Step 4: Execute LLM
    response = await self._execute_llm(
        prompt=question,
        system_prompt=system_prompt,
        **kwargs
    )
    
    # Step 5 & 6: Post-processing (NEW - async)
    asyncio.create_task(
        self._post_response_processing(
            query=question,
            response=response,
            user_id=user_id,
            session_id=session_id,
        )
    )
    
    return response

async def _post_response_processing(
    self,
    query: str,
    response: AIMessage,
    user_id: str,
    session_id: str,
):
    """Background processing after response."""
    if not self._memory_manager:
        return
    
    await self._memory_manager.record_interaction(
        query=query,
        response=response,
        tool_calls=response.tool_calls or [],
        user_id=user_id,
        session_id=session_id,
    )
    
    # Maybe extract skill
    if self.skill_auto_extract:
        await self._maybe_extract_skill(query, response)
```

---

## 6. Storage Backend Options

### 6.1 Recommended Configuration

| Environment | Episodic | Skills | Conversation |
|-------------|----------|--------|--------------|
| Development | FAISS + Memory | Files + Memory | InMemory |
| Production | FAISS + Redis | Files + Redis | Redis |
| Enterprise | PgVector + Redis | PostgreSQL + Redis | Redis |

### 6.2 Configuration Example

```python
# config.py or agent YAML

MEMORY_CONFIG = {
    "episodic": {
        "backend": "faiss",
        "redis_url": "redis://localhost:6379/1",
        "embedding_model": "sentence-transformers/all-mpnet-base-v2",
        "auto_reflect": True,
        "min_importance": 3,
    },
    "skills": {
        "backend": "file",
        "persistence_path": "/var/lib/parrot/skills",
        "auto_extract": False,
    },
    "context": {
        "max_tokens": 2000,
        "episodic_weight": 0.3,
        "skill_weight": 0.3,
        "conversation_weight": 0.4,
    }
}
```

---

## 7. Token Budget Management

### 7.1 Context Assembly Strategy

```python
class ContextAssembler:
    """Assemble context within token budget."""
    
    def __init__(self, max_tokens: int = 2000):
        self.max_tokens = max_tokens
        self.priorities = {
            "episodic_failures": 1,  # Highest priority
            "relevant_skills": 2,
            "conversation": 3,
            "kb_context": 4,
        }
    
    def assemble(
        self,
        episodic_warnings: str = "",
        relevant_skills: str = "",
        conversation: str = "",
        kb_context: str = "",
    ) -> MemoryContext:
        """Assemble context respecting token budget."""
        
        budget = self.max_tokens
        sections = []
        
        # Priority 1: Episodic failures (critical for avoiding mistakes)
        if episodic_warnings:
            tokens = self._count_tokens(episodic_warnings)
            if tokens <= budget * 0.3:  # Max 30% for episodic
                sections.append(episodic_warnings)
                budget -= tokens
        
        # Priority 2: Relevant skills
        if relevant_skills and budget > 500:
            tokens = self._count_tokens(relevant_skills)
            if tokens <= budget * 0.4:  # Max 40% for skills
                sections.append(relevant_skills)
                budget -= tokens
        
        # Priority 3: Conversation (truncate from old)
        if conversation and budget > 200:
            truncated = self._truncate_conversation(conversation, budget)
            sections.append(truncated)
        
        return MemoryContext(
            sections=sections,
            tokens_used=self.max_tokens - budget,
        )
```

---

## 8. Migration Path

### Phase 1: Add Modules (Non-Breaking)

1. Add `parrot/memory/episodic/` module
2. Add `parrot/memory/skills/` module
3. Add `parrot/memory/unified/` module
4. No changes to existing code

### Phase 2: Add Mixin (Opt-In)

1. Create `LongTermMemoryMixin`
2. Agents can opt-in: `class MyAgent(LongTermMemoryMixin, AbstractBot)`
3. Default: `enable_long_term_memory = False`

### Phase 3: Integration Hooks (Minor Changes)

1. Add `memory_context` parameter to `create_system_prompt()`
2. Add post-response hook point in `ask()`
3. Add tool execution hook in tool handling

### Phase 4: Default Enable (Major Version)

1. Enable by default for new agents
2. Existing agents continue working unchanged
3. Document migration guide

---

## 9. API Reference

### 9.1 EpisodicMemoryStore

```python
class EpisodicMemoryStore:
    async def configure() -> None
    async def record_episode(namespace, situation, action, outcome, ...) -> EpisodicMemory
    async def recall_similar(query, namespace, top_k, ...) -> List[EpisodeSearchResult]
    async def get_failure_warnings(query, namespace, max_warnings) -> str
    async def cleanup() -> None
```

### 9.2 SkillRegistry

```python
class SkillRegistry:
    async def configure() -> None
    async def upload_skill(name, content, agent_id, ...) -> Tuple[Skill, SkillVersion]
    async def read_skill(skill_id, version) -> str
    async def search_skills(query, category, ...) -> List[SkillSearchResult]
    async def get_relevant_skills(query, max_skills) -> str
    async def extract_skill_from_conversation(conversation, agent_id) -> Optional[Skill]
    async def cleanup() -> None
```

### 9.3 UnifiedMemoryManager

```python
class UnifiedMemoryManager:
    async def configure() -> None
    async def get_context_for_query(query, user_id, session_id) -> MemoryContext
    async def record_interaction(query, response, tool_calls, ...) -> None
    async def checkpoint_session(session_id) -> None
    async def cleanup() -> None
```

---

## 10. Open Questions

### 10.1 Design Decisions Needed

1. **Reflection LLM**: Use same LLM as agent or dedicated lightweight model (Haiku/Flash)?
   - Recommendation: Configurable but by default a lightweight gemini-3.1-flash-lite

2. **Skill extraction trigger**: When to auto-extract skills?
   - Option A: After N successful tool calls
   - Option B: On explicit user feedback ("that was helpful")
   - Option C: Opt-in per interaction
   - Recommendation: Opt-in, not automatic

3. **Cross-agent skill sharing**: Should skills be shared across agents in same org?
   - Recommendation: Yes, via namespace (`org_id/shared` namespace)

4. **Memory cleanup policy**: When to prune old memories?
   - Episodic: TTL-based (e.g., 90 days) + importance threshold
   - Skills: Never auto-delete, only deprecate

### 10.2 Future Enhancements

1. **ThoughtChain** (MentisDB-style): Append-only hash-chained memory for auditability
2. **Graph-based memory**: ArangoDB for relationship traversal
3. **Checkpoint/Resume**: Full session state persistence for long-running tasks
4. **Multi-agent SharedBrain**: Shared memory across agent crews

---

## 11. Acceptance Criteria

### 11.1 Functional Requirements

- [ ] Agents can record episodic memories from tool executions
- [ ] Agents can recall similar past situations
- [ ] Failure warnings are injected into system prompt
- [ ] Agents can document skills via tool
- [ ] Skills are versioned with diff storage
- [ ] Relevant skills are injected into context
- [ ] Context assembly respects token budget
- [ ] Multi-tenant isolation via namespace

### 11.2 Non-Functional Requirements

- [ ] Memory retrieval < 100ms (p95)
- [ ] Skill extraction does not block response
- [ ] Storage scales to 100K episodes per agent
- [ ] Backward compatible with existing agents

---

## 12. References

- [MemU Framework](https://github.com/NevaMind-AI/memU)
- [OpenClaw Memory](https://docs.openclaw.ai/concepts/memory)
- [MentisDB](https://github.com/CloudLLM-ai/mentisdb)
- [Reflexion Paper](https://arxiv.org/abs/2303.11366)
- [CoALA Framework](https://arxiv.org/abs/2309.02427)
- [LangMem Conceptual Guide](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)