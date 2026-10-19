# ai-parrot-semantic

Governed semantic layer for AI-Parrot agents: metric queries compiled by sidemantic,
authorized/filtered/masked by ai-parrot's sqlglot governance pipeline (PBAC, RLS push-down,
column lineage, positive SQL guard, signed audit).

## Install
    pip install ai-parrot-semantic[duckdb]      # or [bigquery]

## License notice: sidemantic is AGPL-3.0
This package is MIT-licensed, but it depends on `sidemantic==0.12.0`, which is **AGPL-3.0**.
Section 13 of the AGPL (the "network clause") applies when software is offered to users over a
network: if you expose the semantic layer through an HTTP handler, an MCP server or any other
remote interface, you must offer those users the corresponding source code of sidemantic,
including any modifications you made to it. Merely importing an unmodified sidemantic still
makes the combined work subject to the AGPL's terms when it is conveyed or served remotely.
This distribution is opt-in and confines every `sidemantic` import to `packages/ai-parrot-semantic/`
(enforced by ruff TID251), so the core `ai-parrot` packages never depend on it.
Legal sign-off: Jesus Lara, 2026-10-19 (FEAT-704 spec §8 Q1).
