---
id: F001
query_id: Q001
type: read
intent: "Extract the 2026-10-21 decision block and the SemaFlow audit from the two source artifacts"
executed_at: 2026-10-25T10:05:00Z
duration_ms: 4000
parent_id: null
depth: 0
---

# F001 — Source: owner decision supersedes BSL recommendation; SemaFlow audited in code

## Summary

`artifacts/semantic-layer.research.md` opens with a dated decision block: no external semantic-layer library as core; sidemantic discarded (licence + clean-room rule: only public docs and the Cube/dbt formats, code never opened or ported); own compiler Pydantic → IR → sqlglot, accounting model first, generic model second, **no joins in v1**; SemaFlow (MIT) is the attributed derivation source for the Rust/PyO3 phase (`sql_ast.rs` + `dialect/`); BSL/Ibis demoted to "reserved for the joins phase". The brainstorm's Appendix A is a code audit of SemaFlow `main@4055460`: 12.5k Rust lines, 73/73 tests pass on Linux, but `filter:` has no `IN/AND/OR`, DataFrame registration is a full copy behind one `:memory:` connection, planner iterates `HashMap`s (non-deterministic SQL order), no Linux wheels (`ring` via BigQuery), `LICENSE` is the unfilled MIT template.

## Citations

- path: `artifacts/semantic-layer.research.md`
  lines: 3-11
  symbol: `Decisión (2026-10-21)`
  excerpt: |
    > - **sidemantic queda descartado** del todo: ni dependencia, ni referencia de código. [...] solo [...] los esquemas de Cube y dbt MetricFlow [...] consultados en su documentación original.
    > - **Implementación propia** [...] un único compilador Pydantic → IR → sqlglot con gramática cerrada [...] Sin joins en v1.
    > - **SemaFlow (MIT)** es la fuente de código derivado, con acreditación, cuando el compilador pase a Rust/PyO3 (`sql_ast.rs` + `dialect/`)
    > - **BSL/Ibis** [...] pasa a **reservado para la fase de joins**

- path: `artifacts/semantic-layer.research.md`
  lines: 29-46
  symbol: `Tabla comparativa`
  excerpt: |
    | **Implementación propia** (decisión 2026-10-21) | ... | **Adoptado** (v1 sin joins) |
    | **SemaFlow** | 0.1.2 (2026-01-26) | MIT (plantilla sin rellenar) | ... | **Fuente derivada MIT para la fase Rust** |
    | **sidemantic** | 0.12.0 | **AGPL-3.0** | ... | **Descartado** (2026-10-21): licencia; código no se consulta |

- path: `artifacts/semantic-layer.research.md`
  lines: 78-82
  symbol: `## SemaFlow`
  excerpt: |
    Veredicto: no como dependencia (arreglar los tres huecos es escribir el compilador propio), sí como **fuente de código derivado con acreditación** cuando el compilador pase a Rust/PyO3 (`sql_ast.rs` + `dialect/`, ~1.000 líneas que solo dependen de `serde_json`)

- path: `artifacts/semantic-layer.research.md`
  lines: 84-92
  symbol: `## Patrón de integración`
  excerpt: |
    `SemanticQuery` → reescritura RLS desde el contexto PBAC → `await asyncio.to_thread(compile, q)` (compilador propio sobre sqlglot; BSL `.sql(dialect=)` o `ibis.to_sql` en la fase de joins) → `sqlglot.parse_one(sql, read=dialect)` [...] allowlist [...] **positiva**

- path: `artifacts/accounting-metrics-layer.brainstorm.md`
  lines: 383-457
  symbol: `## Appendix A — SemaFlow code audit (2026-10-21)`
  excerpt: |
    | Simple measures with `filter:` | `parse_expr` — **not a parser** [...] No `IN`, `AND`, `OR`, `NOT` | **Gap.** |
    | Deterministic SQL | `query_builder/analysis.rs`: `join_key_mappings: HashMap` [...] | **Unverified / at risk.** |
    ### What is worth deriving (MIT, with attribution)
    - `semaflowrs/src/sql_ast.rs` (322 lines) — AST + renderer.
    - `semaflowrs/src/dialect/{mod,duckdb,postgres,bigquery}.rs` (≈ 830 lines)

## Notes

The two artifacts are uncommitted working copies: `sdd/proposals/semantic-layer.proposal.md` is the pre-decision (2026-10-14) text, and `sdd/proposals/accounting-metrics-layer.brainstorm.md` (accepted) lacks the SemaFlow inspiration line, the attribution constraint and Appendix A that the artifact carries. The accepted brainstorm's §Option B is otherwise the same Option B the decision block adopts.
