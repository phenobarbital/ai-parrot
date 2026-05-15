---
id: F007
query: "Integration handlers ctx usage"
type: grep
files: parrot/integrations/{slack,telegram,msteams,whatsapp}/
---

Integration handlers (Slack, Telegram, Teams, WhatsApp) call agent.ask() DIRECTLY
without using retrieval() or RequestBot. No ctx is passed.

This means:
- They bypass PBAC enforcement
- They bypass concurrency limiting (semaphore)
- With ContextVar approach, they could optionally adopt session() to get ctx
  propagation without code changes in the ask() path
