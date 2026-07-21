---
type: Wiki Summary
title: parrot.bots.prompts
id: mod:parrot.bots.prompts
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Collection of useful prompts for Chatbots.
relates_to:
- concept: mod:parrot.bots
  rel: references
---

# `parrot.bots.prompts`

Collection of useful prompts for Chatbots.

This package provides both the new composable prompt layer system
and legacy prompt templates for backward compatibility.

New API (recommended):
    from parrot.bots.prompts import PromptLayer, PromptBuilder, LayerPriority
    from parrot.bots.prompts import get_preset, register_preset, list_presets

Legacy API (still supported):
    from parrot.bots.prompts import BASIC_SYSTEM_PROMPT, AGENT_PROMPT
