---
kind: inline
jira_key: null
fetched_at: 2026-08-23T09:14:05Z
summary_oneline: "Browser-automation toolkit (DSL) + autonomous agent over Hooba (no-API Spanish accounting SaaS), reachable via Telegram/WhatsApp, with wiki+Obsidian memory"
invocation_slug: web-authomation-infra
language: es
---

# Source (verbatim, inline)

> Por legislación española debo utilizar un software de gestión en la nube
> llamado Hooba (`https://app.hooba.com/`) el problema es que Hooba no cuenta
> con API de ningún tipo, así que la automatización de cosas (crar clientes,
> registrar gastos, CRM, emisión de facturas) depende de interacción en
> browser, ya contamos con un DSL para WebscrapingToolkit, dos drivers
> selenium + playwright e integración con el MCP de google chrome (chrome dev
> tools), asi que se me ocurre 1.- con el mismo DSL crear un toolkit de
> browser automation (lenguaje json para definir directivas de accion como
> "ingresar credenciales, go to dashboard, click en CRM ... ") 2.- crear
> entonces un agente que con acceso a: BrowserAutomationToolkit + Chrome Dev
> Tools MCP + WikiToolkit (crear un cerebro autonomo de trabajo) +
> ObsidianToolkit (notas de trabajo) + TelegramWrapper (usar
> ai-parrot-integrations para exponerlo via telegram y poder interactuar con
> él y Whatsapp, le asignaré un número de teléfono) me permitirá hablar con un
> agente via telegram/whatsapp y pedirle que gestione operaciones como montar
> facturas draft, crear registros de clientes, crear registros de gastos,
> coordinar recordatorios de fechas clave (presentación de impuestos, etc,
> aquí imagino que debería integrarlo a mi Google Calendar), permitir subir el
> excel de gastos de la cuenta bancaria para que use un flow (un agente puede
> invocar un AgentsFlow como si fuera un tool) para procesar y regisrar
> iterativamente los gastos y todo ello generando un LLM wiki local con espejo
> en el Obsidian que me permite saber como va la gestión de mi autonomía.

## Extracted signals (not interpreted)

**Named entities**: Hooba (`https://app.hooba.com/`), WebscrapingToolkit,
BrowserAutomationToolkit, Chrome DevTools MCP, WikiToolkit, ObsidianToolkit,
TelegramWrapper, `ai-parrot-integrations`, WhatsApp, Google Calendar,
AgentsFlow, Selenium, Playwright, LLM wiki.

**Verbs (polarity: positive / greenfield-additive)**: crear, automatizar,
registrar, emitir, gestionar, coordinar, subir, procesar, espejar.
One negation, about the *external* system, not our code: "Hooba no cuenta con
API de ningún tipo".

**Business operations named**: crear clientes, registrar gastos, CRM, emisión
de facturas (draft), recordatorios de fechas clave (impuestos), ingesta de
Excel bancario, seguimiento de la gestión del autónomo.

**Acceptance criteria provided**: no (0).

**Explicit architectural asks by the user**:
1. Reuse the existing WebscrapingToolkit DSL to build a JSON-defined
   browser-automation directive language.
2. Compose one agent over: BrowserAutomationToolkit + Chrome DevTools MCP +
   WikiToolkit + ObsidianToolkit + Telegram/WhatsApp wrapper.
3. Agent-invokes-AgentsFlow-as-a-tool for iterative bank-Excel expense
   ingestion.
4. Local LLM wiki mirrored into Obsidian as the durable work brain.
