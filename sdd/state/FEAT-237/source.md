---
kind: file
jira_key: null
fetched_at: "2026-06-15T12:00:00-04:00"
summary_oneline: "PageIndex Embedding Router — add dense semantic signal + CPU latency micro-benchmark for PageIndex retrieval"
---

Source: `sdd/proposals/pageindex-embedding-router.brainstorm.md`

Rich brainstorm document proposing:
1. Dense embedding signal fused into HybridPageIndexSearch RRF (Phase A)
2. Embedding-guided beam walk as LLM-walk replacement/pre-filter (Phase B)
3. Content-addressed NodeEmbeddingStore with per-tree materialized matrices
4. CPU latency micro-benchmark on a real compliance corpus (SOC 2 + HIPAA)
5. Compliance corpus as first knowledge bank for ComplianceEvidenceAgent

Brainstorm includes:
- 10 open questions (Q1–Q7 + verification items V1–V7)
- 3 architecture options (A, B, C) with recommendation for phased C
- 4 candidate embedding models
- Detailed codebase anchors (grep symbols, file paths)
- Module layout and acceptance criteria
