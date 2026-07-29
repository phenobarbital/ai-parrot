---
type: Wiki Overview
title: 'Migration Guide: FEAT-202 — ai-parrot-integrations'
id: doc:docs-migration-feat-202-ai-parrot-integrations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-202 extracts messaging channel integrations (Slack, Telegram, MS Teams,
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.auth.oauth2.jira_provider
  rel: mentions
- concept: mod:parrot.auth.oauth2.models
  rel: mentions
- concept: mod:parrot.auth.oauth2.registry
  rel: mentions
- concept: mod:parrot.auth.oauth2.service
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.core.hooks.matrix
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.matrix.client
  rel: mentions
- concept: mod:parrot.integrations.matrix.hook
  rel: mentions
- concept: mod:parrot.integrations.msteams.wrapper
  rel: mentions
- concept: mod:parrot.integrations.slack.wrapper
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
- concept: mod:parrot.integrations.whatsapp.wrapper
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot_tools.zoom.client
  rel: mentions
---

# Migration Guide: FEAT-202 — ai-parrot-integrations

**Date**: 2026-05-28
**Affects**: Any project using `ai-parrot` with messaging channel integrations

---

## Overview

FEAT-202 extracts messaging channel integrations (Slack, Telegram, MS Teams,
WhatsApp, Matrix), the Voice module, and Human Channels into a new satellite
package `ai-parrot-integrations`. This reduces the base install size of `ai-parrot`
by eliminating heavy channel SDKs from core dependencies.

---

## Quick Start

### If you use messaging channels

```bash
# Install the new package with the channels you need
pip install "ai-parrot-integrations[telegram,slack]"
# or
pip install "ai-parrot-integrations[all]"
# or via ai-parrot meta-extra
pip install "ai-parrot[messaging]"
```

### If you only use core AI-Parrot (agents, CLI, embeddings)

No action needed. `pip install ai-parrot` now installs fewer dependencies.

---

## Import Path Changes

### OAuth2 — BREAKING

```python
# OLD — raises ImportError after upgrade
from parrot.integrations.oauth2.service import IntegrationsService
from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry
from parrot.integrations.oauth2.models import EnableResponse
from parrot.integrations.oauth2.jira_provider import JiraOAuth2Provider

# NEW
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.models import EnableResponse
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
```

All 7 oauth2 files moved from `parrot.integrations.oauth2.*` to `parrot.auth.oauth2.*`.

### Zoom — BREAKING

```python
# OLD — raises ImportError after upgrade
from parrot.integrations.zoom.client import ZoomUsInterface

# NEW
from parrot_tools.zoom.client import ZoomUsInterface
```

### Channel Integrations — NOT BREAKING (with satellite installed)

These imports continue to work **unchanged** when `ai-parrot-integrations` is installed:

```python
# These still work — PEP 420 namespace extension
from parrot.integrations import IntegrationBotManager
from parrot.integrations.telegram.wrapper import TelegramWrapper
from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier
from parrot.integrations.slack.wrapper import SlackWrapper
from parrot.integrations.msteams.wrapper import MSTeamsWrapper
from parrot.integrations.whatsapp.wrapper import WhatsAppWrapper
from parrot.integrations.matrix.client import MatrixClientWrapper
from parrot.voice import VoiceTranscriber
from parrot.human import TelegramHumanChannel
```

---

## Extras Reference

| What you need | What to install |
|---|---|
| Telegram bot | `pip install "ai-parrot-integrations[telegram]"` |
| Slack bot | `pip install "ai-parrot-integrations[slack]"` |
| MS Teams bot | `pip install "ai-parrot-integrations[msteams]"` |
| WhatsApp bot | `pip install "ai-parrot-integrations[whatsapp]"` |
| Matrix bot | `pip install "ai-parrot-integrations[matrix]"` |
| Voice processing | `pip install "ai-parrot-integrations[voice]"` |
| All messaging channels | `pip install "ai-parrot-integrations[messaging]"` |
| Everything | `pip install "ai-parrot-integrations[all]"` |
| Backward compat alias | `pip install "ai-parrot[messaging]"` |

---

## Matrix Hook Changes

The `MatrixHook` implementation has moved from core to the satellite package.
The hook now auto-registers with `HookRegistry` on import:

```python
# Trigger auto-registration of MatrixHook
import parrot.integrations.matrix.hook

# Then use via HookRegistry
from parrot.core.hooks import HookRegistry, MatrixHook
```

The `MatrixHook` class in `parrot.core.hooks.matrix` remains as a backward-compat
shim that delegates to the registered implementation.

### New MessagingHook Protocol

```python
from parrot.core.hooks.base import MessagingHook, HookRegistry

# Register a custom messaging hook
class MyHook(MessagingHook):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def on_message(self, message) -> None: ...

HookRegistry.register("my-channel", MyHook)
```

---

## Human Channels ChannelRegistry

```python
from parrot.human.channels import ChannelRegistry

# Discover available channels (when satellite installed)
print(ChannelRegistry.available())  # ['telegram']

# Get a specific channel class
TelegramHumanChannel = ChannelRegistry.get("telegram")
```

---

## Checking for Missing Extras

If a required channel package is not installed, you will see a helpful error:

```
ImportError: 'TelegramWrapper' requires ai-parrot-integrations.
Install with: pip install ai-parrot-integrations[telegram]
```

---

## CI/CD Changes

If your CI pipeline runs `pip install ai-parrot` and then imports channel integrations,
you need to update your install step:

```yaml
# OLD
- run: pip install ai-parrot

# NEW (if you use messaging channels)
- run: pip install "ai-parrot-integrations[all]"
# or more specifically
- run: pip install "ai-parrot-integrations[telegram,slack]"
```

---

## What Did NOT Change

- `parrot.manager.BotManager` — unchanged, stays in `ai-parrot`
- `parrot.integrations.IntegrationBotManager` — unchanged (resolves via PEP 420)
- All `parrot.integrations.*` import paths — unchanged (resolves via PEP 420)
- `parrot.voice.*` import paths — unchanged (resolves via PEP 420)
- `parrot.human.TelegramHumanChannel` — unchanged (resolves via PEP 420)

---

## Related Changes

- FEAT-201: ai-parrot-embeddings (same pattern for vector stores and embeddings)
- FEAT-199: parrot-formdesigner (MS Teams extra now declares `parrot-formdesigner`)
