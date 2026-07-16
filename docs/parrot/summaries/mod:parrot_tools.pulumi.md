---
type: Wiki Summary
title: parrot_tools.pulumi
id: mod:parrot_tools.pulumi
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pulumi Toolkit for infrastructure deployment.
relates_to:
- concept: mod:parrot_tools
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.pulumi`

Pulumi Toolkit for infrastructure deployment.

Provides agent tools for Pulumi operations:
- pulumi_plan: Preview changes
- pulumi_apply: Apply changes
- pulumi_destroy: Tear down resources
- pulumi_status: Check stack state

Example:
    from parrot_tools.pulumi import PulumiToolkit

    toolkit = PulumiToolkit()
    agent = Agent(tools=toolkit.get_tools())

Or with custom configuration:
    from parrot_tools.pulumi import PulumiToolkit, PulumiConfig

    config = PulumiConfig(
        default_stack="staging",
        use_docker=True,
    )
    toolkit = PulumiToolkit(config)
