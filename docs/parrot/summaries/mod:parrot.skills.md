---
type: Wiki Summary
title: parrot.skills
id: mod:parrot.skills
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AI-Parrot Skills Module (top-level namespace).
relates_to:
- concept: mod:parrot
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.tools
  rel: references
---

# `parrot.skills`

AI-Parrot Skills Module (top-level namespace).

Git-like versioned skill/knowledge registry that enables agents to:
- Document learned skills and patterns
- Version control with unified diffs
- Search and discover relevant skills
- Auto-extract skills from conversations

Usage:
    from parrot.skills import (
        SkillRegistry,
        SkillRegistryMixin,
        create_skill_tools,
    )

    # Option 1: Use mixin
    class MyAgent(SkillRegistryMixin, AbstractBot):
        enable_skill_registry = True

    # Option 2: Use registry directly
    registry = SkillRegistry(namespace="my_org/my_agent")
    await registry.configure()

    skill, version = await registry.upload_skill(
        name="Database Query Pattern",
        content="# How to query efficiently...",
        agent_id="my_agent",
    )
