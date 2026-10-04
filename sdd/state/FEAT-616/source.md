---
kind: inline
jira_key: null
fetched_at: 2026-09-30T23:55:00+00:00
summary_oneline: Extend OdooToolkit (or add an OdooHelpdesk mixin) with typed helpdesk tools for the Softhealer helpdesk on Odoo 19 staging
---

# Source (inline, verbatim — Spanish)

Slug requested: `odoo-toolkit-upgrades`

En el Odoo expuesto en staging environment: https://pokemon.helpdesk.staging.trocdigital.io/
con credenciales acequibles via ODOO_HELPDESK_URL, ODOO_HELPDESK_USER, ODOO_HELPDESK_PASSWORD
y ODOO_HELPDESK_APIKEY hay un sistema helpdesk que debemos descubrir cual es (al parecer es un
modulo custom de "softhealer", un partner hindú), necesitamos hacer un research sobre este
Odoo v.19 para ampliar el OdooToolkit ya sea incorporando métodos o extendiendo con un mixin
de OdooHelpdesk para incorporar métodos para operar con el helpdesk system (crear tickets,
transicionar tickets, gestionar las incidencias, definir SLAs, etc), esto incluye model inputs
para los métodos de entrada y gestión de las salidas (structured outputs)

# Paraphrase (English)

The staging Odoo 19 instance (credentials in `ODOO_HELPDESK_*` env vars) runs a helpdesk
system, believed to be a custom Softhealer (Indian partner) module. Research that instance
and the existing `OdooToolkit` to propose how to add helpdesk operations — create tickets,
transition tickets, manage incidents, define SLAs, etc. — either as new toolkit methods or
as an `OdooHelpdesk` mixin/subclass, with typed Pydantic inputs and structured outputs.
