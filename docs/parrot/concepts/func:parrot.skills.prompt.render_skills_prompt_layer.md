---
type: Concept
title: render_skills_prompt_layer()
id: func:parrot.skills.prompt.render_skills_prompt_layer
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a static ``<available_skills>`` XML PromptLayer from the registry.
---

# render_skills_prompt_layer

```python
def render_skills_prompt_layer(registry: SkillFileRegistry, max_skills: Optional[int]=None, priority: int=45) -> PromptLayer
```

Build a static ``<available_skills>`` XML PromptLayer from the registry.

Reads all skills from ``registry`` and emits an XML block listing each
skill's name, description, and a ``load_skill(name="...")`` hint. Skills
that declare ``triggers`` also include an "Also triggerable via: /cmd" line.

The returned :class:`~parrot.bots.prompts.PromptLayer` uses
``phase=RenderPhase.CONFIGURE`` so it is resolved once at boot and cached;
there is no per-request evaluation overhead.

Args:
    registry: The :class:`~parrot.skills.file_registry.SkillFileRegistry`
        to read skills from.
    max_skills: If set, truncate to this many skills (first N from registry).
        ``None`` means include all.
    priority: Integer priority for the layer. Default ``45`` places the
        layer between ``USER_SESSION`` (40) and ``TOOLS`` (50).

Returns:
    A frozen :class:`~parrot.bots.prompts.PromptLayer` with:

    - ``name="available_skills"``
    - ``template`` containing the ``<available_skills>`` XML block, or
      an empty string if the registry has no skills.
    - ``phase=RenderPhase.CONFIGURE``
