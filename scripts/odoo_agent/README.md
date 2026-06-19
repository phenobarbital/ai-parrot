# Odoo Agent Scripts

Helper scripts for the OdooAgent (FEAT-240).

---

## ⚠️ Read first — how the PageIndex is actually built

The **recommended source for the documentation PageIndex is the official
`.rst` sources**, ingested with `build_rst_pageindex.py` (see below). The
original PDF route (`fetch_odoo_docs.sh` → `build_odoo_pageindex.py`) does
**not** produce a usable documentation index, for a concrete reason:

> The Odoo docs repo scopes `latex_documents` (in its `conf.py`) to the
> **legal** documents only (`legal/terms/...`). So `make latexpdf` renders
> ~14 small legal PDFs (enterprise agreement, terms of sale, …) and **none**
> of the technical/admin/developer documentation — including the
> `odoo-bin` / CLI reference. Ingesting those PDFs yields a PageIndex of
> license agreements, which is useless for the agent.

The `.rst` sources, by contrast, carry the full technical docs as plain
UTF-8 text and ingest cleanly via `PageIndexToolkit.import_folder`.

**Current materialised trees** (under `agents/odoo_agent/documentation/`):

| Tree        | Source                                             | Status |
|-------------|----------------------------------------------------|--------|
| `odoo_18`   | Odoo 18.0 `.rst` sources (≈1016/1064 files)        | built — 7947 nodes |
| `odoo_book` | Cybrosys "Odoo Book" PDF (`docs/…cybrosys….pdf`)   | built — 16 nodes |
| `odoo_16`   | Odoo 16.0 `.rst` sources                            | not built yet |
| `odoo_19`   | Odoo 19.0 `.rst` sources                            | not built yet |

> **Retrieval note (large trees):** `odoo_18` has ~7947 nodes, which is too
> large for PageIndex's `use_llm_walk=True` mode — the LLM walk packs the whole
> tree into one prompt and hits Gemini's 1,048,576-token input limit
> (`400 INVALID_ARGUMENT`). Query large trees with **`use_llm_walk=False`**
> (BM25 + optional rerank), which returns well-ranked results, or split a
> version into smaller per-section trees (e.g. `developer`, `applications`).

---

## `build_rst_pageindex.py` — Build the PageIndex from `.rst` sources (recommended)

Ingests the official Odoo documentation `.rst` sources into a per-version
PageIndex tree (`odoo_<major>`) via `PageIndexToolkit.import_folder`. This is
the robust path (see the note above).

```bash
source .venv/bin/activate

# 1. Make sure the docs repo is cloned and on the right version branch.
#    fetch_odoo_docs.sh clones it (the make-latexpdf step will fail harmlessly;
#    the clone under scripts/odoo_agent/.cache/documentation is what we need).
#    Then checkout the version branch:
git -C scripts/odoo_agent/.cache/documentation checkout 18.0

# 2. Validate cheaply on a single subdir first (writes tree odoo_18_ref):
python scripts/odoo_agent/build_rst_pageindex.py --version 18.0 \
    --subdir developer/reference --tree-name odoo_18_ref --force

# 3. Build the full version tree (writes tree odoo_18; ~1h for 18.0):
python scripts/odoo_agent/build_rst_pageindex.py --version 18.0 --tree-name odoo_18 --force
```

### Notes

- Requires `GOOGLE_API_KEY` resolvable (env or navconfig).
- Default model is `gemini-2.5-flash-lite` (the legacy `gemini-2.0-flash-lite`
  is retired by Google and 404s — see `MEMORY` notes for FEAT-240).
- A handful of very large `.rst` files (~4.5% for 18.0) fail the per-file
  structured-output extraction and are skipped with a WARNING; the rest ingest
  fine. Use `--dry-run` to count files without ingesting.

---

## `fetch_odoo_docs.sh` — Generate Odoo Documentation PDFs (legacy / legal docs only)

> **Note:** kept for reference and to clone the docs repo. Its `make latexpdf`
> step only renders the legal PDFs (see the warning at the top of this file).
> For the documentation PageIndex, use `build_rst_pageindex.py` instead.


Clones the official [Odoo documentation repository](https://github.com/odoo/documentation)
and builds PDF documentation for Odoo 16, 18, and 19 using `make latexpdf`.
The resulting PDFs are placed under `agents/odoo_agent/documentation/<version>/`.

### Prerequisites

| Tool | Install (Debian/Ubuntu) | Install (macOS) |
|------|-------------------------|-----------------|
| `git` | `apt-get install git` | `brew install git` |
| `make` | `apt-get install build-essential` | `xcode-select --install` |
| `pdflatex` | `apt-get install texlive-full` | `brew install --cask mactex` |
| Python 3.8+ | `apt-get install python3` | `brew install python` |

The Odoo documentation repo also needs Sphinx and Odoo-specific Sphinx extensions,
which are installed automatically from the repo's `requirements.txt`.

### Usage

```bash
# Build all versions (skips versions whose PDF already exists)
./scripts/odoo_agent/fetch_odoo_docs.sh

# Force rebuild even if PDFs already exist
./scripts/odoo_agent/fetch_odoo_docs.sh --force

# Build only Odoo 18
./scripts/odoo_agent/fetch_odoo_docs.sh --versions 18.0

# Build 16 and 18 only
./scripts/odoo_agent/fetch_odoo_docs.sh --versions 16.0,18.0

# Use a custom output directory
./scripts/odoo_agent/fetch_odoo_docs.sh --out-dir /tmp/odoo_docs
```

### Output

```
agents/odoo_agent/documentation/
├── 16.0/
│   └── odoo_16_0_docs.pdf
├── 18.0/
│   └── odoo_18_0_docs.pdf
└── 19.0/
    └── odoo_19_0_docs.pdf
```

Each per-version PDF contains the full official documentation for that release,
including the `odoo-bin` / `odoo-cli` command-line reference.

### Notes on Large PDFs

The generated PDFs can be hundreds of megabytes each.  They are **not**
committed to source control by default — only a `.gitkeep` placeholder is
tracked in `agents/odoo_agent/documentation/`.  Consider:

- Storing them in Git LFS if you need versioned PDFs.
- Regenerating them on-demand using this script.
- Keeping them in a network share / S3 bucket and symlinking locally.

---

## `build_odoo_pageindex.py` — Build the PageIndex from PDFs

After `fetch_odoo_docs.sh` has generated the PDFs, run this script to ingest
them into the AI-Parrot PageIndex.  See script docstring for full usage.

```bash
source .venv/bin/activate
python scripts/odoo_agent/build_odoo_pageindex.py
```

### Requirements

- `GOOGLE_API_KEY` (or equivalent) must be set for the LLM adapter.
- PDFs must already exist under `agents/odoo_agent/documentation/<version>/`.
- Run from the repository root.
