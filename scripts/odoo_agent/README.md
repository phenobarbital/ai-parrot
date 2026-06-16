# Odoo Agent Scripts

Helper scripts for the OdooAgent (FEAT-240).

---

## `fetch_odoo_docs.sh` — Generate Odoo Documentation PDFs

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
