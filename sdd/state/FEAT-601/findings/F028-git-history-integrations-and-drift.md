---
id: F028
query_id: Q028
type: git_log
intent: Churn in models/responses.py + integrations parser/msteams/telegram (90 days) and drift d2244e5..HEAD
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F028 — Integrations are warm (Teams formdesigner, Telegram); drift since d2244e5 does not touch any FEAT-601 seam

## Summary
In 90 days there are 30+ commits on responses.py and the integrations paths (capped at 30). The recent ones: telegram /add_mcp gating (2026-09-23), speech-report-models FEAT-591 (2026-09-23), msteams formdesigner FEAT-551 (2026-09-15), token-budget InvokeResult (2026-09-11), a2ui-v1 dialect Adaptive Cards (2026-08-29), and Telegram multi-auth (2026-08-31). There are 15 commits in `d2244e5..HEAD`. Only three of them touch `packages/`: `553a96217` (knowledge/wiki/{claude_code,codex,google}/bookstore.py, +21/-4), `1814adc2b` (planogram pipelines) and merge `daca1bac7`. None touches knowledge/contracts, ontology, pageindex, models/responses.py, parrot_tools/contracts, integrations or loaders.

## Citations
- 4ea69592b9 2026-09-23 Jesus Lara — fix(telegram): gate /add_mcp DocumentDB persistence behind USE_DOCUMENTDB
- 021ae3032e / 7eab199f33 / 537110c0de 2026-09-23 Jesus Lara — speech-report-models FEAT-591 / TASK-3621
- 0ac7dd798e / f013e6f288 / 3644889021 / 798a21d2fe / f575d7c8a7 2026-09-15 Jesus Lara — FEAT-551 msteams formdesigner (_handle_card_submission branch, formdesigner_submit.py)
- 69eff7771b 2026-09-11 Jesus Lara — token-budget-bedrock TASK-3132 (InvokeResult.budget_report)
- 6b3f0ad74c 2026-09-03 Jesus Lara — wip: fixing max tokens on llm clients
- 8701ccc0b2 2026-08-31 Jesus — Telegram multi-auth support
- 05aa27beba / 0ad7d9c3a9 2026-08-29 Jesus Lara — a2ui-v1-dialect TASK-2545/2546 (Adaptive Cards native inputs, Action.Submit{a2ui_action}, Teams wrapper routes a2ui_action)
- 2f6e8dbad8 2026-08-23 — audio-notes-obsidian TASK-2377 (telegram_chat_scope)
- f2c34cb44d 2026-08-20 Jesus — fix(security): 121 CodeQL alerts
- 3b178195de 2026-08-01 — tokens-observability TASK-2031 (CompletionUsage.__add__, AIMessage.total_usage)
- 4c44252e77 2026-07-31 — formdesigner-field-uid TASK-2007
- Drift `d2244e5..HEAD` (15 commits): 4025699ed / 05d5664bd / 66f16aa75 sdd reservations; 72334e1ed, af4f41abd, 4cb7286a8, d24193d44, a0377ef67 FEAT-600 sdd artifacts; acd66e1aa SendMessage in sdd-worker; 553a96217 2026-09-24 fix over bookstore mcp plugin for wiki (packages/ai-parrot/src/parrot/knowledge/wiki/{claude_code,codex,google}/bookstore.py); 00915580b test plugins; 1814adc2b planogram/nova2 per-slot RapidOCR (ai-parrot-pipelines); 0384596cf / 345d88cfa / daca1bac7 merges. Overall diff: 50 files, +4688/-93.

## Notes
- The brainstorm's verification point (main@d2244e5) is still valid for every FEAT-601 seam.
- The Teams card submission path (`MSTeamsAgentWrapper._handle_card_submission`) was changed recently by FEAT-551 and a2ui-v1. If guided mode uses Adaptive Card submits, it must go through that router.
