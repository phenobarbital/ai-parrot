---
kind: file
jira_key: null
fetched_at: 2026-06-16
summary_oneline: "GraphIndex Odoo-aware extractor + SQLiteGraphReader for navigable code repositories"
---

Source file: `sdd/proposals/odoo-graphindex-code.brainstorm.md`

Brainstorm proposes three components for the GraphIndex pipeline:

1. **`OdooCodeExtractor`** — subclass of `CodeExtractor` capturing Odoo model semantics
   (_name/_inherit/_inherits, fields.*, @api.*) and emitting EXTENDS edges to canonical model nodes.

2. **`SQLiteGraphReader`** — read-side navigator with HOT topology in rustworkx + COLD source bodies
   via FTS5/BM25 and disk-based line-span resolution.

3. **Prerequisites** — `EdgeKind.EXTENDS` in schema, meta_ontology mapping, projection mapping,
   mtime/sha1/lineno stamping in base CodeExtractor, builder/loader cabling for SQLite backend.

Guide use case: discover what a third-party module adds to a core Odoo model (e.g. res.partner)
without reading code manually — deterministic graph traversal, not semantic similarity.
