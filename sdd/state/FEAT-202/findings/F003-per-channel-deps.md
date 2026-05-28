---
id: F003
query_id: Q004
type: grep
intent: Dependencias de terceros por canal
executed_at: 2026-05-28T13:40:35+02:00
depth: 0
---

# F003 — Deps por canal (SDK específico por cada uno)

## Summary

Cada canal tiene su SDK propio: telegram=aiogram, msteams=botbuilder.*,
whatsapp=pywa, matrix=mautrix+python-olm, slack=aiohttp+slack-sdk
(transitivo), zoom=aiohttp (no SDK). La declaración en pyproject de
ai-parrot es inconsistente: **`pywa` está en BASE deps**, `aiogram`
viene transitivo vía `async-notify[default]` (también BASE), mientras
`mautrix` está en extra `[matrix]` y `azure-teambots` en extra
`[integrations]`.

## Citations

- path: `packages/ai-parrot/src/parrot/integrations/telegram/`
  excerpt: |
    from aiogram import Bot, Dispatcher, Router, F
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ChatAction, ChatType, ParseMode
    from aiogram.filters import Command, CommandStart
    from aiogram.filters.base import Filter

- path: `packages/ai-parrot/src/parrot/integrations/msteams/`
  excerpt: |
    from botbuilder.core import MemoryStorage, ...
    from botbuilder.core.teams import TeamsInfo
    from botbuilder.dialogs import DialogSet, DialogTurnStatus
    from botbuilder.integration.aiohttp import ...
    from botbuilder.schema import Activity, ActivityTypes, ChannelAccount, Attachment

- path: `packages/ai-parrot/src/parrot/integrations/whatsapp/`
  excerpt: |
    from pywa import WhatsApp
    from pywa.handlers import MessageHandler as PyWaMessageHandler
    from pywa.types import Message as WhatsAppMessage, MessageType

- path: `packages/ai-parrot/src/parrot/integrations/slack/`
  excerpt: |
    from aiohttp import web, ClientSession, ClientTimeout
    from navconfig import config
    import hmac
    # slack_sdk transitive via async-notify

- path: `packages/ai-parrot/src/parrot/integrations/matrix/`
  excerpt: |
    from pydantic import BaseModel, Field
    import yaml, importlib
    # mautrix + python-olm imported in client.py / appservice.py

- path: `packages/ai-parrot/src/parrot/integrations/zoom/`
  excerpt: |
    import aiohttp
    from navconfig.logging import logging
    # No SDK — direct REST API client

- path: `packages/ai-parrot/pyproject.toml`
  lines: 80-83, 112, 461, 404
  excerpt: |
    # BASE deps
    "async-notify[default]>=1.4.2",
    "pywa>=3.8.0",                    # ← FUGA (WhatsApp en core)
    # Extra notify-all
    "async-notify[all]>=1.4.2",       # ← trae aiogram, slack-sdk transitivos
    # Extra integrations
    "async-notify[all]>=1.5.2",
    "azure-teambots>=0.1.1",
    # Extra matrix
    "mautrix>=0.20",
    "python-olm>=3.2.16",

## Notes

Mapa propuesto de extras de `ai-parrot-integrations`:

| Extra | Deps | Canales |
|---|---|---|
| `slack` | `slack-sdk>=3.0`, `slack-bolt>=1.18` (opt) | slack/* |
| `telegram` | `aiogram>=3.12` | telegram/* |
| `msteams` | `azure-teambots>=0.1.1`, `botbuilder-core>=4.16`, `botbuilder-dialogs`, `botbuilder-integration-aiohttp`, `parrot-formdesigner>=…` (← FEAT-199) | msteams/* |
| `whatsapp` | `pywa>=3.8.0` | whatsapp/* |
| `matrix` | `mautrix>=0.20`, `python-olm>=3.2.16` | matrix/* |
| `zoom` | (sin deps adicionales — solo aiohttp del core) | zoom/* |
| `oauth2` | (decisión: queda en core o en este paquete; ver F002) | oauth2/* |
| `voice` | (depende de decisión sobre parrot.voice; ver F007) | msteams/voice/, telegram (transcripción) |
| `messaging` | combo: telegram + slack + msteams + whatsapp | todos los canales chat |
| `all` | todos los anteriores | — |

Cambios necesarios en `packages/ai-parrot/pyproject.toml`:
1. Eliminar `pywa>=3.8.0` de BASE deps (línea 83) — sale con whatsapp.
2. Reemplazar `async-notify[default]>=1.4.2` en BASE deps por algo
   más minimalista, o cambiarlo a un extra. Investigar qué symbols del
   core lo requieren (puede ser solo para integraciones).
3. Eliminar `azure-teambots` del extra `integrations`.
4. Mover `mautrix` y `python-olm` del extra `matrix` al nuevo paquete.
