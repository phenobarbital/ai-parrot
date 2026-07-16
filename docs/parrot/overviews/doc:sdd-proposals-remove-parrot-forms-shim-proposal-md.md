---
type: Wiki Overview
title: FEAT-199 — Cerrar migración `parrot.forms` → `parrot-formdesigner`
id: doc:sdd-proposals-remove-parrot-forms-shim-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ningún paquete del workspace).
relates_to:
- concept: mod:parrot.forms
  rel: mentions
- concept: mod:parrot.forms.extractors.tool
  rel: mentions
- concept: mod:parrot.forms.renderers
  rel: mentions
- concept: mod:parrot.forms.tools
  rel: mentions
- concept: mod:parrot.forms.validators
  rel: mentions
---

---
id: FEAT-199
title: Cerrar migración parrot.forms → parrot-formdesigner (eliminar shim, tests legacy y package-data)
slug: remove-parrot-forms-shim
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-28
  summary_oneline: "Remove parrot.forms shim — migration to parrot-formdesigner is complete"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-199/
created: 2026-05-28
updated: 2026-05-28
---

# FEAT-199 — Cerrar migración `parrot.forms` → `parrot-formdesigner`

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — solicitud del usuario para finalizar la migración del paquete `forms`
> **Audit**: [`sdd/state/FEAT-199/`](../state/FEAT-199/)

---

## 0. Origin

> El paquete `parrot.forms` fue migrado a `parrot-formdesigner`. Actualmente
> `parrot/forms/__init__.py` es solo un shim de re-export desde
> `parrot_formdesigner.core` y submódulos. Los únicos consumidores internos
> son 8 archivos en `parrot/integrations/msteams/`. Objetivo: cerrar la
> migración, mover esos imports a `parrot_formdesigner.*` y eliminar el
> directorio `parrot/forms/` por completo, junto con docs/examples/tests
> residuales.

**Initial signals**:
- Verbos: "cerrar migración", "eliminar", "remover" → cleanup/refactor.
- Named entities: `parrot.forms`, `parrot-formdesigner`, `msteams dialogs`.
- Acceptance criteria provided: implícitos (sin referencias residuales en
  ningún paquete del workspace).

---

## 1. Synthesis Summary

La migración no está cerrada como sugería el brief inicial. `parrot/forms/__init__.py`
no es un shim puro: tiene un fallback `except ImportError` con 25 archivos
de código real (`schema`, `validators`, `cache`, `storage`, `registry`,
`constraints`, `options`, `style`, `types`, más subpaquetes `extractors/`,
`renderers/` y `tools/`). `parrot-formdesigner` **no está declarado como
dependency** de `ai-parrot`, por eso existe el fallback. Los 8 consumidores
en `parrot/integrations/msteams/` usan mayormente imports de submódulos
(`parrot.forms.renderers`, `parrot.forms.validators`,
`parrot.forms.extractors.tool`, `parrot.forms.tools`) que **bypassan** el
re-export del `__init__.py` y resuelven directamente al fallback local.
Hay además 19 tests legacy en `tests/unit/forms/` que validan ese
fallback, y una entrada de `package-data` en `pyproject.toml:542`.

**Decisión de scope (resuelve U2)**: msteams se moverá a un futuro
`ai-parrot-integrations`, así que la dep a `parrot-formdesigner` viaja
**con msteams** a ese paquete; `ai-parrot` core no necesita conocerla.
Re-verificación con grep sobre todo el workspace confirma **cero
consumidores de `parrot.forms` fuera de los 8 archivos de msteams + 19
tests legacy** — no hay nada "común" que deba quedarse. El trabajo neto
en ai-parrot core se reduce a: eliminar el directorio `parrot/forms/`,
eliminar la línea de package-data, y eliminar los tests legacy. La
migración de imports en msteams ocurre como parte de la extracción de
`ai-parrot-integrations` (FEAT futuro), no aquí.

---

## 2. Codebase Findings

> Todas las entradas están grounded en `sdd/state/FEAT-199/findings/`.

### 2.1 Localization

| # | Path | Símbolo | Líneas | Rol | Evidencia |
|---|------|---------|--------|-----|-----------|
| 1 | `packages/ai-parrot/src/parrot/forms/__init__.py` | shim try/except | 1-90 | Shim de re-export con fallback local | F001 |
| 2 | `packages/ai-parrot/src/parrot/forms/` (25 archivos) | — | — | Implementación local legacy completa | F002 |
| 3 | `packages/ai-parrot/src/parrot/integrations/msteams/wrapper.py` | imports | 36-39 | Consumidor msteams (4 imports `parrot.forms.*`) | F003 |
| 4 | `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/orchestrator.py` | imports | 17-22, 208 | Consumidor msteams (6 imports, incluye submódulos) | F003 |
| 5 | `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/factory.py` | imports | 4 | Consumidor msteams | F003 |
| 6 | `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/presets/{base,wizard,wizard_summary,conversational,simple_form}.py` | imports | varias | 5 dialog presets, idéntico patrón | F003 |
| 7 | `packages/ai-parrot/tests/unit/forms/` (19 archivos) | — | — | Tests legacy contra fallback local | F003 |
| 8 | `packages/ai-parrot/pyproject.toml` | package-data | 542 | `"parrot.forms.renderers" = ["templates/*.j2"]` | F004, F005 |

### 2.2 Constraints Discovered

- **`parrot-formdesigner` no es dependency declarada de `ai-parrot`.**
  Está como workspace member pero ningún `pyproject.toml` lo lista como
  runtime dep. Por eso el shim necesita fallback.
  *Implicación*: borrar el fallback requiere declarar la dep en el extra
  apropiado (`integrations`, un nuevo `forms`, o diferir hasta extraer
  `ai-parrot-integrations`).
  *Evidencia*: F004

- **msteams importa submódulos que bypassan el shim.**
  `parrot.forms.renderers`, `parrot.forms.validators`,
  `parrot.forms.extractors.tool`, `parrot.forms.tools` se resuelven contra
  los archivos `.py` locales, no contra el re-export de `__init__.py`.
  *Implicación*: hoy esos imports SIEMPRE corren código local stale,
  aunque `parrot-formdesigner` esté instalado. Migración a
  `parrot_formdesigner.*` directa es obligatoria antes de borrar.
  *Evidencia*: F001, F003

- **`parrot/forms/` está dormante; toda la actividad reciente
  (incluyendo FEAT-188 lifecycle-events) ocurre en `parrot-formdesigner`.**
  *Implicación*: el fallback local está atrasado respecto a la
  funcionalidad upstream — caller que dependa silenciosamente del
  fallback está corriendo versión vieja sin saberlo.
  *Evidencia*: F006

- **19 tests legacy validan el fallback local, no `parrot-formdesigner`.**
  *Implicación*: auditar 1:1 contra cobertura existente en
  `packages/parrot-formdesigner/tests/`. Borrar duplicados, portar
  faltantes.
  *Evidencia*: F003

- **Solo un activo no-código a limpiar**: la línea
  `"parrot.forms.renderers" = ["templates/*.j2"]` en
  `packages/ai-parrot/pyproject.toml:542`. No hay referencias en docs,
  examples, ni otros paquetes del workspace.
  *Evidencia*: F005

### 2.3 Recent History

| Commit | When | Author | Message | Archivos |
|--------|------|--------|---------|----------|
| `6c75db3f` | reciente | (sdd) | sdd: close FEAT-188 — formdesigner-lifecycle-events (9/9 tasks) | parrot-formdesigner |
| `837278cc` | reciente | (sdd) | fix(formdesigner): address code-review issues for FEAT-188 | parrot-formdesigner |
| `460b0631..f4269046` | reciente | (sdd) | TASK-1265 → TASK-1273 (toda la cadena de lifecycle-events) | parrot-formdesigner |

Ningún commit reciente toca `packages/ai-parrot/src/parrot/forms/`.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **Dep obligatoria a `parrot-formdesigner`** en el extra de `ai-parrot`
  que cubra msteams (a definir en U2).

### What Changes

- **`parrot/integrations/msteams/wrapper.py`** — reemplazar 4 imports.
  *Evidencia*: F003
- **`parrot/integrations/msteams/dialogs/orchestrator.py`** — reemplazar
  6 imports (incluye `local import` en línea 208). *Evidencia*: F003
- **`parrot/integrations/msteams/dialogs/factory.py`** — reemplazar 1 import.
  *Evidencia*: F003
- **`parrot/integrations/msteams/dialogs/presets/{base,wizard,wizard_summary,conversational,simple_form}.py`** —
  reemplazar 3 imports cada uno (5 archivos × 3). *Evidencia*: F003
- **`packages/ai-parrot/pyproject.toml`** — eliminar línea 542
  (`"parrot.forms.renderers" = ["templates/*.j2"]`). *Evidencia*: F005
- **`packages/ai-parrot/tests/unit/forms/`** — auditar y borrar/portar
  los 19 tests legacy (decisión por U1). *Evidencia*: F003

### What's Removed

- **`packages/ai-parrot/src/parrot/forms/` completo** (25 archivos):
  - top-level: `schema.py`, `validators.py`, `cache.py`, `storage.py`,
    `registry.py`, `constraints.py`, `options.py`, `style.py`,
    `types.py`, `__init__.py`
  - `extractors/`: `jsonschema.py`, `pydantic.py`, `yaml.py`, `tool.py`,
    `__init__.py`
  - `renderers/`: `base.py`, `adaptive_card.py`, `html5.py`,
    `jsonschema.py`, `__init__.py`, `templates/form.html.j2`
  - `tools/`: `create_form.py`, `database_form.py`, `request_form.py`,
    `__init__.py`

### Non-Goals

- No modificar `parrot-formdesigner` ni su API.
- No cambiar comportamiento para consumidores que ya importen de
  `parrot_formdesigner`.
- No reorganizar msteams ni extraerlo a `ai-parrot-integrations` (eso es
  trabajo separado de la propuesta de modularización).

### Patterns to Follow

- **Mapeo de imports directo según el try-branch de F001:**
  - `from parrot.forms import …` (top-level symbols)
    → `from parrot_formdesigner.core import …` o `.services` según símbolo
  - `from parrot.forms.renderers import AdaptiveCardRenderer`
    → `from parrot_formdesigner.renderers import AdaptiveCardRenderer`
  - `from parrot.forms.validators import FormValidator`
    → `from parrot_formdesigner.services import FormValidator`
  - `from parrot.forms.extractors.tool import ToolExtractor`
    → `from parrot_formdesigner.extractors import ToolExtractor`
  - `from parrot.forms.tools import RequestFormTool`
    → `from parrot_formdesigner.tools import RequestFormTool`
  - `from parrot.forms import FormCache`
    → `from parrot_formdesigner.services import FormCache`

### Integration Risks

- **Consumidores externos** que importen `parrot.forms.*` (otros repos
  del workspace que no estén bajo esta investigación) se romperán al
  desaparecer el paquete. *Mitigación*: nota explícita en `CHANGELOG.md`
  de `ai-parrot`; búsqueda previa en repos cliente conocidos.
- **Tests/handlers que indirectamente caían en el fallback** (porque
  `parrot-formdesigner` no estaba instalado) pasarán a fallar con
  `ImportError` si la dep no se declara correctamente.
  *Mitigación*: cubrir con la decisión de U2 antes de borrar.

---

## 4. Confidence Map

| ID | Claim | Evidencia | Confianza | Razonamiento |
|----|-------|-----------|-----------|--------------|
| C1 | `parrot.forms` es un shim con fallback local activo | F001 | high | Lectura directa del `__init__.py` confirma branches |
| C2 | `parrot/forms/` contiene 25 archivos de implementación local | F002 | high | Inventario directo |
| C3 | Solo msteams (8 archivos) y `tests/unit/forms` (19 archivos) consumen `parrot.forms` en el repo | F003 | high | grep exhaustivo sobre `packages/` |
| C4 | msteams usa submódulos directos que siempre resuelven al fallback | F001, F003 | high | Cruce: el `__init__.py` solo cubre símbolos top-level; los imports de submódulo no atraviesan el `try/except` |
| C5 | `parrot-formdesigner` no es dependency declarada de `ai-parrot` | F004 | high | grep en pyproject.toml retorna cero matches en deps |
| C6 | Toda actividad reciente ocurre en `parrot-formdesigner`; `parrot/forms` está dormante | F006 | high | git log directo |
| C7 | Solo un activo no-código requiere limpieza en pyproject | F005 | high | grep exhaustivo en docs/examples/configs |
| C8 | Los 19 tests legacy necesitan auditoría de cobertura equivalente antes de borrarse | F003, F006 | medium | Inferido — no verifiqué 1:1 los tests de `parrot-formdesigner` |

Distribución: **7** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U2: ¿Dónde declarar `parrot-formdesigner` como dep obligatoria?**
  — *Resuelto*: msteams se moverá a `ai-parrot-integrations` (paquete
  futuro). La dep a `parrot-formdesigner` viaja con msteams y se declara
  **solo allí**. `ai-parrot` core no necesita conocer a
  `parrot-formdesigner`.
  *Resuelve*: C5
  *Implicación de scheduling*: FEAT-199 queda **acoplado temporalmente**
  a la extracción de `ai-parrot-integrations`. Ver §6 para alternativas
  de secuenciación.
  *Verificación adicional*: re-corrió grep sobre todo el workspace —
  cero consumidores de `parrot.forms` fuera de los 8 archivos de msteams
  + 19 tests legacy. **No hay nada "común" que deba quedarse en
  ai-parrot**; todo el código de `parrot/forms/` se elimina y la
  funcionalidad la provee `parrot-formdesigner` desde
  `ai-parrot-integrations`.

### Unresolved (defer to spec / implementation)

- [ ] **U1: ¿Los 19 tests legacy en `tests/unit/forms/` tienen ya
  equivalente en `packages/parrot-formdesigner/tests/`?** — *Owner*: tbd
  *Bloquea*: C8
  *Respuestas plausibles*:
  a) Borrar tras auditar 1:1 (probable — los tests son contra el
     fallback local que también desaparece).
  b) Portar a `parrot-formdesigner` antes de borrar local.
  c) Mantener algunos como tests de integración en
     `ai-parrot-integrations` (msteams + formdesigner end-to-end).

- [ ] **U3 (nueva): ¿Cómo secuenciar FEAT-199 con la extracción de
  `ai-parrot-integrations`?**
  — *Owner*: tbd
  *Bloquea*: ejecución de FEAT-199
  *Respuestas plausibles*:
  a) Hacer FEAT-199 **después** de extraer `ai-parrot-integrations`:
     msteams ya vive en su paquete con la dep a `parrot-formdesigner`,
     los imports ya están migrados a `parrot_formdesigner.*`, y
     FEAT-199 solo borra el directorio + package-data + tests legacy
     (trivial, sin riesgo).
  b) Hacer FEAT-199 **al mismo tiempo** que la extracción de
     `ai-parrot-integrations` (bundle): un solo PR mueve msteams +
     migra imports + borra `parrot/forms/`. Más coordinado pero más
     grande.
  c) Hacer FEAT-199 **antes**: migrar los imports de msteams a
     `parrot_formdesigner.*` in-situ en ai-parrot (declarando la dep
     temporalmente en el extra `integrations` de ai-parrot), borrar
     `parrot/forms/`, y luego mover msteams. **Coste**: ai-parrot
     adquiere temporalmente la dep a `parrot-formdesigner` (justo lo
     que se quería evitar). *No recomendado*.

---

## 6. Recommended Next Step

**Pre-requisito**: este FEAT-199 está **acoplado temporalmente** a la
extracción futura de `ai-parrot-integrations` (decisión U2). La
recomendación depende del path elegido en U3:

- **Si U3.a (FEAT-199 después de extraer `ai-parrot-integrations`)** —
  *recomendado por riesgo mínimo*: esperar. Cuando msteams ya viva en
  su paquete con sus imports migrados a `parrot_formdesigner.*`,
  `/sdd-task FEAT-199` es suficiente — el trabajo se reduce a 3
  operaciones triviales (borrar `parrot/forms/`, borrar línea 542 de
  `pyproject.toml`, borrar `tests/unit/forms/`).

- **Si U3.b (bundle con la extracción de integrations)** — fusionar el
  spec de FEAT-199 con el de `ai-parrot-integrations` (una propuesta
  separada todavía no abierta).

- **Si U3.c (FEAT-199 antes)** — `/sdd-spec FEAT-199` para tratar la
  dep temporal en el extra `[integrations]`. **No recomendado** porque
  contradice la decisión U2 de no acoplar ai-parrot core con
  formdesigner.

### Alternatives

- **`/sdd-brainstorm FEAT-199`** — no recomendado; no hay arquitectura
  por explorar.
- **Esperar** y revisar este proposal cuando se abra la propuesta de
  `ai-parrot-integrations`.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-199/state.json` |
| Source (raw) | `sdd/state/FEAT-199/source.md` |
| Research plan | `sdd/state/FEAT-199/research_plan.json` |
| Findings | `sdd/state/FEAT-199/findings/F001..F006-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-199/synthesis.json` |

**Budget consumed** (perfil `default`):
- Files read: 4 / 40
- Grep calls: 5 / 25
- Git calls: 1 / 10
- Wall time: ~180s / 300s
- Truncated: **no**

**Mode determination**: `auto` → `enrichment` (la solicitud nombra el
target, las áreas afectadas y el alcance; no hay misterio que investigar
sino un trabajo a estructurar).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Opus 4.7 (1M context) |
