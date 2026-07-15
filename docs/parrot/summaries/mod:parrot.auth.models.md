---
type: Wiki Summary
title: parrot.auth.models
id: mod:parrot.auth.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Policy Rule Configuration models for AI-Parrot PBAC.
relates_to:
- concept: class:parrot.auth.models.PolicyRuleConfig
  rel: defines
---

# `parrot.auth.models`

Policy Rule Configuration models for AI-Parrot PBAC.

This module provides the ``PolicyRuleConfig`` Pydantic model for declaring
access rules at the bot/agent level. Rules are converted to the policy dict
format expected by ``PolicyEvaluator.load_policies()``.

Typical usage::

    class MyBot(AbstractBot):
        policy_rules = [
            {"action": "agent:chat", "effect": "allow", "groups": ["engineering"]},
        ]

Or in BotConfig YAML::

    policies:
      - action: agent:chat
        effect: allow
        groups: [engineering, ops]
        priority: 10

Public API:
    - ``PolicyRuleConfig``: Pydantic model for a single policy rule.

## Classes

- **`PolicyRuleConfig(BaseModel)`** — Simple policy rule format for bot-level declaration.
