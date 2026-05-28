# ai-parrot-integrations

Messaging channel integrations for [AI-Parrot](https://github.com/phenobarbital/ai-parrot):
Slack, Telegram, MS Teams, WhatsApp, Matrix, and Voice.

This package uses **PEP 420 namespace extension** to contribute modules under the
`parrot.integrations.*`, `parrot.voice.*`, and `parrot.human.channels.*` namespaces.
All existing import paths remain unchanged.

> **IMPORTANT**: Do NOT create a `src/parrot/__init__.py` in this package.
> It would break the PEP 420 namespace extension provided by `ai-parrot`'s
> `parrot/__init__.py:extend_path`. This is a known maintenance hazard.

## Installation

Install only the channels you need:

```bash
# Core AI-Parrot only (no channel SDKs)
pip install ai-parrot

# Individual channels
pip install "ai-parrot-integrations[slack]"
pip install "ai-parrot-integrations[telegram]"
pip install "ai-parrot-integrations[msteams]"
pip install "ai-parrot-integrations[whatsapp]"
pip install "ai-parrot-integrations[matrix]"
pip install "ai-parrot-integrations[voice]"

# Combo extras
pip install "ai-parrot-integrations[messaging]"   # slack + telegram + msteams + whatsapp
pip install "ai-parrot-integrations[all]"         # messaging + matrix + voice
```

## Extras Reference

| Extra | SDK(s) installed |
|---|---|
| `slack` | `slack-sdk>=3.0`, `slack-bolt>=1.18` |
| `telegram` | `aiogram>=3.12` |
| `msteams` | `azure-teambots>=0.1.1`, `parrot-formdesigner` |
| `whatsapp` | `pywa>=3.8.0` |
| `matrix` | `mautrix>=0.20`, `python-olm>=3.2.16` |
| `voice` | `faster-whisper`, `openai` |
| `messaging` | slack + telegram + msteams + whatsapp |
| `all` | messaging + matrix + voice |

## Import Paths (unchanged)

```python
from parrot.integrations import IntegrationBotManager
from parrot.integrations.telegram.wrapper import TelegramWrapper
from parrot.integrations.slack.wrapper import SlackWrapper
from parrot.integrations.msteams.wrapper import MSTeamsWrapper
from parrot.integrations.whatsapp.wrapper import WhatsAppWrapper
from parrot.integrations.matrix.client import MatrixClientWrapper
from parrot.voice import VoiceTranscriber
from parrot.human.channels import ChannelRegistry
```

## Migration Guide

See [docs/migration/feat-202-ai-parrot-integrations.md](../../docs/migration/feat-202-ai-parrot-integrations.md)
for full migration details.

### Breaking changes from `ai-parrot` core

- `from parrot.integrations.oauth2.X import Y` is now `from parrot.auth.oauth2.X import Y`
- `from parrot.integrations.zoom.client import ZoomUsInterface` is now `from parrot_tools.zoom.client import ZoomUsInterface`
- `pywa`, `aiogram`, `azure-teambots`, `mautrix` are no longer installed with `pip install ai-parrot`
