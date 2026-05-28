---
kind: inline
jira_key: null
fetched_at: 2026-05-28T13:11:03+02:00
summary_oneline: "Remove parrot.forms shim — migration to parrot-formdesigner is complete"
---

# Source — remove-parrot-forms-shim

Contexto: el paquete `parrot.forms` fue migrado a `parrot-formdesigner`.
Actualmente `parrot/forms/__init__.py` es solo un shim de re-export
(90 líneas, puro try/except) desde `parrot_formdesigner.core` y submódulos.
Los únicos consumidores internos que aún importan `parrot.forms` son los
dialogs de MS Teams:

- parrot/integrations/msteams/wrapper.py
- parrot/integrations/msteams/dialogs/orchestrator.py
- parrot/integrations/msteams/dialogs/factory.py
- parrot/integrations/msteams/dialogs/presets/base.py
- parrot/integrations/msteams/dialogs/presets/wizard.py
- parrot/integrations/msteams/dialogs/presets/wizard_summary.py
- parrot/integrations/msteams/dialogs/presets/conversational.py
- parrot/integrations/msteams/dialogs/presets/simple_form.py

Objetivo: cerrar la migración de forms. Reemplazar los imports en msteams
por imports directos a `parrot_formdesigner.core` (y submódulos donde
aplique según FEAT-152) y eliminar por completo el directorio
`packages/ai-parrot/src/parrot/forms/`, incluyendo `extractors/`,
`renderers/`, `tools/`, `validators.py`, `cache.py`, `constraints.py`,
`options.py`, `registry.py`, `schema.py`, `storage.py`, `style.py`,
`types.py`.

Confirmar también que no quedan referencias a `parrot.forms` en docs,
examples, tests, ni en otros paquetes del workspace
(`ai-parrot-tools`, `ai-parrot-loaders`, `ai-parrot-pipelines`).

Resultado esperado: `parrot.forms` deja de existir, `parrot-formdesigner`
queda como única ubicación. Reducción de superficie en ai-parrot core
sin cambios funcionales para consumidores que ya importan de
`parrot_formdesigner`.
