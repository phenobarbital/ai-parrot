# Source — brainstorm session (2026-07-30, Cowork)

Kind: `inline` (brainstorm conversation) + `file` (3 reference schemas under
`references/`).

## Original request (verbatim, es)

> En este escrito sobre Wiki LLM que permitió la creación de LLMWIKI basado en
> GraphIndex en ai-parrot: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
> habla de "assisted ingestion" o de "supervised ingestion", por ahora, comandos
> como "wikitoolkit build" solo hacen unsupervised ingestion y para folders
> llenos de documentos (que no son datos), puede ser un problema.
> ¿Qué se me ocurre? que el LLM Ingestion tenga un intent router que permita
> evaluar el contenido por encima, clasificarlo (categorizar) pero a su vez
> evaluar el propio contenido contra las reglas de scoring para verificar si es
> relevante y ante cualquier duda, el CLI ejecutar un HITL call mostrando el
> documento, el briefing y preguntar al usuario si ese documento debe ir (o no)
> al wiki, imagina el caso de usar wikitoolkit no para código sino para toda la
> vida digital corporativa (meetings, summaries, etc) y ocurre el caso de si en
> una reunión solo se contaron chistes, se debería descartar del wiki, pero
> trato de imaginar la manera de filtrarlo pre-ingestion.

## Design refinements agreed during brainstorm

1. Separate *classification* from *admission*; three-band thresholding
   (admit / gray-zone-defer / reject) — selective prediction with reject option.
2. The admission policy is a first-class artifact: an **editorial charter**
   (YAML) per wiki. See `references/charter.example.yaml`.
3. Scoring dimensions: density / novelty / durability. LLM scores dimensions,
   code computes the weighted composite.
4. Unit of admission is the **claim**, not the document (partial extraction).
5. Reject ≠ delete: three destinations (wiki / archive / discard).
6. HITL decoupled from terminal blocking: `--dry-run` emits a JSONL
   **manifest** (see `references/manifest.example.jsonl`), user edits/reviews,
   `--review manifest.jsonl` applies.
7. Calibration in `--auto` mode: **stratified** 5% audit sample
   (60% near-threshold + 40% uniform); agreement rate below `min_agreement`
   widens the gray zone; disagreements feed few-shots and charter amendments
   (`autotune: propose`).
8. Reference Pydantic models for all of the above: `references/schemas.py`.

## Initial signals (extracted, not interpreted)

- Verbs: "evaluar", "clasificar", "filtrarlo pre-ingestion" → feature (enrichment), not a bug.
- Named entities: `wikitoolkit build`, LLM Wiki, GraphIndex, HITL, intent router, Karpathy gist.
- Components: `parrot.knowledge.wiki`, `parrot.knowledge.graphindex`, CLI.
- Acceptance criteria provided: no (brainstorm-level).
