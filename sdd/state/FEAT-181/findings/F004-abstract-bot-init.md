---
id: F004
query_id: Q009
type: read
intent: AbstractBot/Agent init signature where prompt_caching flag would land.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — AbstractBot already accepts `prompt_builder` kwarg; legacy `system_prompt_template` is fallback

## Summary

`AbstractBot` at `parrot/bots/abstract.py:155` already accepts both a
`system_prompt: str = None` kwarg (line 250) and a `prompt_builder:
PromptBuilder = None` kwarg (line 265). The builder, when set, takes
precedence over the legacy `system_prompt_template`. Subclasses include
`Chatbot` (`bots/chatbot.py:28`), `Agent` (`bots/agent.py:1256`), and
indirectly `GitHubReviewer` and `JiraSpecialist`. The legacy path keeps
`system_prompt_template` populated from `system_prompt` arg (line 305-309)
and is rendered via `Template(self.system_prompt_template)` at line 1042
+ `create_system_prompt` (line 2543) → `_build_prompt` (line 1118).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 155-186
  symbol: `class AbstractBot(...)`
  excerpt: |
    class AbstractBot(
        ...
    ):
        system_prompt_template = BASIC_SYSTEM_PROMPT
        # Composable prompt builder (None = use legacy system_prompt_template)
        _prompt_builder: Optional[PromptBuilder] = None

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 247-309
  symbol: `AbstractBot.__init__`
  excerpt: |
    def __init__(
        self,
        name: str = 'Nav',
        system_prompt: str = None,
        llm: Union[str, Type[AbstractClient], AbstractClient, Callable, str] = None,
        instructions: str = None,
        tools: ...,
        ...
        prompt_builder: PromptBuilder = None,
        prompt_preset: str = None,
        event_bus: Optional[Any] = None,
        **kwargs
    ):
        self._system_prompt_base = system_prompt or ''
        if system_prompt:
            self.system_prompt_template = system_prompt or self.system_prompt_template
        if instructions:
            self.system_prompt_template += f"\n{instructions}"

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 1042-1054, 1118, 2543-2584, 2650
  symbol: prompt assembly / `create_system_prompt` / `_build_prompt`
  excerpt: |
    tmpl = Template(self.system_prompt_template)
    ...
    def _build_prompt(self, ...): ...
    async def create_system_prompt(self, ...):
        result = self._build_prompt(...)

- path: `packages/ai-parrot/src/parrot/bots/chatbot.py`
  lines: 28
  symbol: `class Chatbot(BaseBot)`

- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 14, 110-117, 1256
  symbol: Agent default builder
  excerpt: |
    from .prompts.builder import PromptBuilder
    # Default to composable PromptBuilder for agents unless:
    self._prompt_builder = PromptBuilder.agent()
    class Agent(BasicAgent): ...

## Notes

The `prompt_builder` kwarg is the natural attach point for a
`prompt_caching` flag: it can become a flag on `PromptBuilder` itself
(builder remembers it across `configure()`/`build()` calls), or a sibling
kwarg on `__init__`. Putting it on the builder keeps the surface honest
("caching is a property of how the prompt is built, not of the bot's
identity"), and the bot inherits it automatically when it constructs the
builder via preset.
