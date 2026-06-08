# Benchmark Fixtures

This directory contains fixture data for the multimodal embedding benchmark.

## Included Fixtures

### `synthetic_queries.json`

A synthetic dataset of 20 query/document pairs (10 English + 10 Spanish equivalents)
designed as a minimal fallback for end-to-end benchmark runs without real domain data.

Format:
```json
{
  "query_id": "q001",
  "query_text": "a red apple on a wooden table",
  "relevant_doc_id": "d001",
  "doc_text": "Fresh red apple placed on a rustic wooden table",
  "lang": "en"
}
```

## Plugging Real Domain Data

To replace synthetic data with real Spanish domain queries, provide a CSV file with
the following columns:

```
query_id,query_text,relevant_doc_id,doc_text,lang
```

### CSV format example

```csv
query_id,query_text,relevant_doc_id,doc_text,lang
q001,planograma estante Epson,d001,Imagen de planograma de impresoras Epson con referencias SKU,es
q002,informe ventas impresoras Q2,d002,Reporte trimestral Q2 ventas región latinoamérica,es
```

### Passing to the benchmark

```bash
python benchmarks/multimodal_embedding_benchmark.py \
    --domain-data path/to/your_queries.csv \
    --output-dir results/
```

### CSV Requirements

- `query_id`: unique string identifier for each query
- `query_text`: the natural language query
- `relevant_doc_id`: the document ID that is the correct answer
- `doc_text`: the text of the relevant document (used as corpus entry)
- `lang`: ISO 639-1 language code (`en`, `es`, etc.)

**Note**: Each `relevant_doc_id` must appear exactly once in `doc_text`. Non-relevant
corpus entries can be added by including additional rows with `relevant_doc_id` values
that are NOT in the query set — the benchmark treats all corpus entries as candidates.

## Adding Image Fixtures

For cross-modal benchmarks, add images to this directory and reference them in a
CSV with an additional `image_path` column:

```csv
query_id,query_text,relevant_doc_id,image_path,lang
img001,red apple,img_d001,fixtures/red_apple.jpg,en
```

The benchmark will automatically detect the `image_path` column and enable
cross-modal metrics.

## Decision Gate

The benchmark applies the following decision rule (from spec §7):

> **UForm adoption threshold**: UForm multilingual-base nDCG@10 must be within 3%
> of the current text embedder baseline. If it lags by more than 3 percentage points,
> retain the current text-only embedder for pure-text RAG.

Results are written to the output report as a PASS/FAIL decision gate line.
