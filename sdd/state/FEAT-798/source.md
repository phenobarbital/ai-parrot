---
kind: inline
jira_key: null
fetched_at: 2026-11-04T01:33:46Z
summary_oneline: "google-migration: upgrade google-genai, retire gemini-2.5-{pro,flash} (deprecated 2026-12-01) from GoogleModel, parrot.conf defaults and pre-built parrot.bots agents; adopt Gemini 4 Argon"
---

# Source (inline)

Slug requested: `google-migration`

> Actualmente Google Gemini ha lanzado un deprecated de gemini-2.5-{pro,flash} para 1 de
> diciembre de 2026 (falta un mes), pero además gemini 4 argon ha sido lanzado, entonces
> necesitamos hacer un upgrade de la actual librería google-genai y a su vez hacer un retiro
> de gemini-2.5-{pro,flash} no solo del GoogleModel enum, sino como default en parrot.conf y
> en agentes pre-hechos en parrot.bots

## Extracted signals

- Deadline: gemini-2.5-pro / gemini-2.5-flash deprecated by Google on **2026-12-01** (one month out).
- Gemini 4 "Argon" is released.
- Asks: (1) upgrade the `google-genai` library; (2) retire `gemini-2.5-{pro,flash}` from the
  `GoogleModel` enum; (3) retire them as defaults in `parrot.conf`; (4) retire them as defaults
  in the pre-built agents under `parrot.bots`.
- Polarity: additive/migration ("upgrade", "retiro") → enrichment-shaped.
