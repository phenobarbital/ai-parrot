---
kind: file
jira_key: null
fetched_at: 2026-10-25T10:00:00Z
summary_oneline: "FEAT-704 rev2 — drop sidemantic (AGPL), own sqlglot compiler as sole engine, SemaFlow (MIT) for the Rust phase, BSL reserved for joins"
files:
  - artifacts/semantic-layer.research.md        # revised research with the 2026-10-21 decision block (primary)
  - artifacts/accounting-metrics-layer.brainstorm.md   # Appendix A — SemaFlow code audit (2026-10-21)
related_committed_docs:
  - sdd/proposals/semantic-layer.proposal.md    # original 2026-10-14 research (pre-decision)
  - sdd/specs/semantic-layer.spec.md            # FEAT-704, approved rev 0.2, sidemantic core
  - sdd/specs/accounting-metrics-layer.spec.md  # FEAT-713, draft
---

# Source — `/sdd-proposal semantic-layer-rev2`

## Inline instructions (verbatim, 2026-10-25)

> en el artefacto `artifacts/accounting-metrics-layer.brainstorm.md` evaluamos la posibilidad de eliminar sidemantic (AGPLv3) del feature de capa semántica FEAT-704, hay que re-hacer el research enfocando más en semaflow + capa propia en Rust según las siguientes reglas: Bloque de decisión al inicio (2026-10-21) que supersede la recomendación original: implementación propia, sidemantic fuera, SemaFlow como fuente MIT para la fase Rust, BSL reservado para joins.
>
> Sidemantic: su sección pasa a "descartado por licencia" con la regla clean-room explícita (solo documentación pública y los formatos de Cube/dbt consultados en origen; su código no se abre ni se porta). Eliminé las tres referencias que lo usaban como plano de implementación: mcp_server.py como "mejor referencia de contrato de herramientas", sus adaptadores como "referencia para escribir el conversor Ossie", y la frase final de "reabriría sidemantic si legal acepta AGPL".
>
> Nueva sección SemaFlow con el resumen de la auditoría y enlace al Appendix A del brainstorm.
>
> Tabla: fila nueva "Implementación propia (Adoptado)", fila SemaFlow, veredictos de BSL ("Reservado para la fase de joins") y sidemantic ("Descartado") actualizados.
>
> Patrón de integración y conclusión reescritos para el compilador propio; el pipeline de ejecución, el guard sqlglot positivo, SemanticQuery y la superficie MCP se conservan tal cual porque siguen siendo válidos con cualquier motor. y según este research: `artifacts/semantic-layer.research.md`

## Mid-run decision (verbatim, 2026-10-25)

Asked implicitly by the finding that `origin/feat-FEAT-704-semantic-layer` already implements all 20 tasks with sidemantic as the core, the owner answered:

> we can discard that branch because was focused on sidemantic, that is discarded, or re-used the code no related to sidemantic

## Primary source — decision block of `artifacts/semantic-layer.research.md` (lines 3-11)

> **Decisión (2026-10-21) — supersede la recomendación original de este documento.**
> Tras la auditoría de código de SemaFlow (`claude/accounting-metrics-layer.brainstorm.md`, Appendix A) y la revisión legal pendiente de AGPL, ai-parrot **no adopta ninguna librería de capa semántica como núcleo**:
> - **sidemantic queda descartado** del todo: ni dependencia, ni referencia de código. [...] De sidemantic solo se usa lo que es público y no suyo: los esquemas de Cube y dbt MetricFlow que importa, consultados en su documentación original.
> - **Implementación propia** (brainstorm *Accounting Metrics Layer*, Option B): un único compilador Pydantic → IR → sqlglot con gramática cerrada, primero para el modelo contable [...] y después para el modelo genérico (measures con filtro, dimensiones, grano temporal, catálogo con PBAC) sobre el mismo IR. Sin joins en v1.
> - **SemaFlow (MIT)** es la fuente de código derivado, con acreditación, cuando el compilador pase a Rust/PyO3 (`sql_ast.rs` + `dialect/`); en v1 es referencia de diseño acreditada.
> - **BSL/Ibis (MIT/Apache-2.0)** deja de ser "recomendado" y pasa a **reservado para la fase de joins** (multi-hop, fan-out, agregados simétricos): es la frontera donde una librería externa entra como backend opcional de ejecución, no como núcleo.
> - La gobernanza (RLS desde PBAC, allowlist por rol, guard sqlglot positivo, AuditLedger) es código de ai-parrot con cualquier motor; esa parte del research sigue vigente íntegra.

The full artifacts (106 and 457 lines) stay in `artifacts/` (uncommitted working copies); this proposal cites them by line.
