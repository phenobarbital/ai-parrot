---
id: F007
query_id: Q008
type: read
intent: Locate the Telegram integration and confirm whether a WhatsApp channel exists in ai-parrot-integrations
executed_at: 2026-08-23T09:28:00Z
depth: 0
parent_id: null
---

# F007 — Telegram and WhatsApp both ship; WhatsApp has two transports, and Telegram already handles document uploads

## Summary

`ai-parrot-integrations` ships wrappers for telegram, whatsapp, slack, msteams,
matrix, a2a, agentd and liveavatar, all started from one YAML-driven
`IntegrationBotManager` (`integrations_bots.yaml`, falling back to
`telegram_bots.yaml`). WhatsApp has **two** transports: `wrapper.py`
(`WhatsAppAgentWrapper`, pywa + Meta Cloud API webhook — needs a WhatsApp
Business number) and `bridge_wrapper.py` (`WhatsAppBridgeWrapper`, a Go
whatsmeow bridge POSTing to a local webhook — works with a personal number).
The source says "le asignaré un número de teléfono", which selects between them.

Most importantly for the Excel-upload requirement: `TelegramAgentWrapper`
already registers a `handle_document` handler and threads uploaded files through
to the agent as `attachments=[local_paths]` on `agent.ask()`, and sends
documents/images/tables/charts back out via `_send_attachments`.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/`
  lines: 1-1
  symbol: "channel inventory"
  excerpt: |
    a2a/  agentd/  core/  liveavatar/  matrix/  mcp/  msagentsdk/
    msteams/  slack/  telegram/  whatsapp/
    manager.py  models.py  parser.py  utils.py  a2ui_resume.py

- path: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
  lines: 38-41, 79-82, 173-179, 205-272
  symbol: `IntegrationBotManager`
  excerpt: |
    from .telegram.wrapper import TelegramAgentWrapper
    from .whatsapp.wrapper import WhatsAppAgentWrapper
    self.telegram_bots: Dict[str, Tuple[Bot, Dispatcher, 'TelegramAgentWrapper']]
    self.whatsapp_bots: Dict[str, 'WhatsAppAgentWrapper'] = {}
    await self._start_telegram_bot(name, agent_config)
    await self._start_whatsapp_bot(name, agent_config)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 67, 300, 1461-1552, 3075-3120
  symbol: `TelegramAgentWrapper`
  excerpt: |
    class TelegramAgentWrapper(OperatorCommandsMixin):        # 67
        self.handle_document,                                 # 300
        attachments: Optional[List[str]] = None,              # 1461
            ... agent.ask(..., attachments=attachments)       # 1526/1552
        async def _send_attachments(self, chat_id, parsed)    # 3075
            for doc_path in parsed.documents:                 # 3120

- path: `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_wrapper.py`
  lines: 1-16
  symbol: `WhatsAppBridgeWrapper`
  excerpt: |
    Connects AI-Parrot agents to WhatsApp via the Go whatsmeow bridge.
    WhatsApp ─► Go Bridge ─(HTTP POST)─► WhatsAppBridgeWrapper
                                              │  agent.ask()
    WhatsApp ◄─ Go Bridge ◄─(POST /send)──────┘

- path: `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py`
  lines: 37-359
  symbol: `WhatsAppAgentWrapper`
  excerpt: |
    class WhatsAppAgentWrapper:
        async def _handle_verify / _handle_webhook       # Meta webhook
        def _on_message(self, client: WhatsApp, ...)     # pywa sync callback
        def _is_authorized(self, wa_id: str) -> bool

- path: `packages/ai-parrot/src/parrot/core/hooks/messaging.py`
  lines: 1-1
  symbol: "Messaging platform hooks — Telegram, WhatsApp, MS Teams."

## Notes

`_is_authorized(wa_id)` on the WhatsApp side and the Telegram auth module
(`telegram/auth.py`) matter more than usual here: this agent can spend money and
file tax-relevant records, so channel-level allowlisting is a security control,
not a convenience.
