# Compliance Corpus — SOC 2 + HIPAA

This corpus provides PageIndex trees for SOC 2 + HIPAA compliance reference,
used as the benchmark fixture for FEAT-237 and as the knowledge base for the
future `ComplianceEvidenceAgent`.

## Sources

| Source | Format | License | Redistributable |
|---|---|---|---|
| NIST SP 800-53 Rev 5 | JSON | Public Domain (NIST) | Yes |
| NIST CSF 2.0 | PDF | Public Domain (NIST) | Yes |
| AICPA Trust Services Criteria 2017 | PDF | AICPA — internal only | **NO** |
| HIPAA Security Rule (45 CFR Part 164) | PDF | Public Domain (US Gov) | Yes |

## Directory Layout

```
corpus/compliance_soc2_hipaa/
├── manifest.yaml        # Source URLs, SHA-256 checksums, license flags
├── fetch.py             # Manifest-driven downloader
├── build_tree.py        # PageIndex tree builder
├── README.md            # This file
├── raw/                 # Downloaded source files (gitignored)
│   ├── nist_800_53_r5.json
│   ├── nist_csf_2_0.pdf
│   ├── aicpa_tsc_2017.pdf    ← manual placement; NEVER commit
│   └── hipaa_45cfr164_2023.pdf
└── trees/               # Built PageIndex trees (gitignored)
    ├── nist_800_53.json
    ├── nist_csf_2_0.json
    ├── aicpa_tsc.json        ← internal only; NEVER publish
    └── hipaa_security_rule.json
```

## Quick Start

### 1. Download Sources

```bash
# Download all redistributable sources:
python -m corpus.compliance_soc2_hipaa.fetch

# Print SHA-256 (to fill in manifest.yaml placeholders):
python -m corpus.compliance_soc2_hipaa.fetch --compute-sha
```

AICPA TSC must be placed manually at `raw/aicpa_tsc_2017.pdf` after downloading
from the [AICPA member portal](https://www.aicpa-cima.com/resources).

### 2. Build Trees

```python
# From your agent code:
from corpus.compliance_soc2_hipaa.build_tree import build_trees

# With dense embedding (FEAT-237):
await build_trees(
    storage_dir=Path("corpus/compliance_soc2_hipaa/trees"),
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    use_vec_rank=True,
    adapter=my_pageindex_adapter,
)
```

### 3. Warm the Cache

After building trees, warm the embedding cache for each tree:

```python
toolkit.embedding_store.build_tree_matrix(
    tree_name="nist_800_53",
    nodes=all_nodes,
    embed_fn=toolkit._embed_fn,
)
```

## Licensing Constraints

- **AICPA TSC** (`redistributable: false`): Do NOT publish tree JSON files built
  from this source. Treat them with the same confidentiality as the source document.
- **NIST sources**: Public domain — trees may be published freely.
- **HIPAA Security Rule**: Published by the US Government — public domain.

## Benchmark Use

The FEAT-237 CPU latency benchmark (TASK-1551) uses the `nist_800_53` tree
(largest, most representative). Ensure it is built before running:

```bash
python -m tests.benchmarks.test_pageindex_latency \
    --tree nist_800_53 \
    --storage-dir corpus/compliance_soc2_hipaa/trees
```
