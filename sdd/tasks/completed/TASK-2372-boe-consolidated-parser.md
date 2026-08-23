# TASK-2372: BOE consolidated XML parser and versions[] construction

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2369
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 and §2 Data Models. **This is the load-bearing task of the whole feature.**
It builds `versions[]` — the temporal model that finding F011 confirmed has zero precedent
anywhere in `parrot/knowledge/`. Everything else in this spec is wiring around it.

BOE *legislación consolidada* already splits each article into dated wording blocks, and the
norm's *análisis* metadata carries `modifica`/`deroga` relations with BOE ids. The parser's job
is to turn that into flat records the ontology pipeline can upsert, with a fully-built,
gap-free version history per article.

> **Spec open question (§8)**: the source design assumes per-article dated wording blocks are
> uniform across norms. **Verify this against 3 real norms before building the parser.** If
> segmentation is inconsistent, add a normalisation step and widen the fixtures — and record
> the finding in the Completion Note.

---

## Scope

- Define the `ArticleVersion` Pydantic model exactly as specified in spec §2 Data Models.
- Implement `parse_consolidated(xml: str | bytes) -> ParsedNorm` returning:
  - one `norma` record (`boe_id`, title, rank, publication/entry-into-force dates, status)
  - N `articulo` records, each with an ordered, gap-free `versions[]`
  - the `modifica` / `deroga` relations declared in the norm's *análisis* metadata
- Build `versions[]` per spec: `n` 0-based, `valid_to` of version *n* equals `valid_from` of
  version *n+1*, last version has `valid_to=None`, `modified_by=None` for `n=0`,
  `kind="supresion"` implies `text=None`, `source="boe_consolidada"`, `derived=False` always.
- Be **tolerant**: on parse failure, return the error for surfacing in
  `ExtractionResult.errors` — never a silently empty record.
- Check in at least one XML fixture with an article having **≥ 3 versions**.

**NOT in scope**: HTTP fetching (TASK-2373); ontology/graph writes; CELLAR/EUR-Lex diffing;
setting `derived=True` (BOE is authoritative — the flag exists only for the later CELLAR path).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/__init__.py` | CREATE | BOE subpackage marker |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/models.py` | CREATE | `ArticleVersion`, `ParsedNorm` Pydantic models |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/parser.py` | CREATE | Consolidated XML → records |
| `packages/ai-parrot-tools/tests/legal/fixtures/boe_consolidated_sample.xml` | CREATE | Real BOE XML, article with ≥3 versions |
| `packages/ai-parrot-tools/tests/legal/test_boe_parser.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field

# From TASK-2369 (must be completed first):
from parrot_tools.legal.ids import normalize_boe_id, article_key
```

XML parsing: prefer the standard library.

```python
import xml.etree.ElementTree as ET
```

### Existing Signatures to Use

```python
# Target model — spec §2 Data Models. Implement EXACTLY this shape:
class ArticleVersion(BaseModel):
    n: int                       # 0-based version index
    text: str | None             # None when kind == "supresion"
    valid_from: date
    valid_to: date | None        # None = currently in force
    modified_by: str | None      # BOE id of amending norm; None for n == 0
    kind: Literal["redaccion", "adicion", "supresion"]
    source: Literal["boe_consolidada"]
    derived: bool                # ALWAYS False for BOE
```

Downstream consumer (TASK-2373) will wrap these records in:

```python
# packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:18
class ExtractedRecord(BaseModel):
    data: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
```

So `parse_consolidated` must return plain dict-serialisable records.

### Does NOT Exist

- ~~An XML loader in `parrot_loaders`~~ — the package has only `html.py`, `web.py`,
  `webscraping.py`. **Do NOT** try `from parrot_loaders import XMLLoader`. BOE XML parsing
  belongs inside this module.
- ~~Any existing BOE parser, fixture, or legal model~~ — grep for
  `cendoj|eurlex|celex|BOE-A-|ECLI:` across `packages/` returns **zero** matches.
- ~~`parrot.knowledge.ontology` helpers for building version history~~ — the ontology layer
  stores whatever dicts you give it; it has no temporal logic. All version construction is
  yours.
- ~~`derived=True` for any BOE-sourced version~~ — that flag is reserved for CELLAR
  diff-derived versions in a later feature. Setting it here is a spec violation.

---

## Implementation Notes

### Pattern to Follow

Version chaining, per spec §2:

```python
# versions are ordered by valid_from ascending; each closes the previous
versions[n].valid_to = versions[n + 1].valid_from   # exclusive upper bound
versions[-1].valid_to = None                        # currently in force
versions[0].modified_by = None                      # original wording
```

### Key Constraints

- **Async-first** for any I/O; this module is pure parsing, so sync functions are acceptable
  here — but do not add blocking I/O.
- **Pydantic** for every structured record (project standard).
- `self.logger` / module logger, never `print`.
- Google-style docstrings and strict type hints throughout.
- **Boundary representation must match TASK-2371's AQL.** If the traversal compares ISO
  `YYYY-MM-DD` strings, serialise dates that way consistently. Coordinate — a mismatch here
  produces silently wrong results, not an error.
- No network access in this module or its tests. Fixtures only.
- Tolerant parsing: catch structural errors, collect them, keep the raw input available.
  Never return an article with an empty `versions[]` and no error.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/` — sibling toolkit layout conventions
- Spec §2 Data Models — the authoritative `ArticleVersion` definition
- Spec §7 Known Risks — boundary semantics and the `derived` flag

---

## Acceptance Criteria

- [ ] `ArticleVersion` matches spec §2 exactly (all 8 fields, correct types and literals)
- [ ] An un-amended article yields exactly one version: `n=0`, `modified_by=None`, `valid_to=None`
- [ ] An amended article yields ordered versions with contiguous `valid_from`/`valid_to` and **no gaps**
- [ ] `kind="supresion"` yields `text=None` and closes the prior version
- [ ] Every emitted version has `source="boe_consolidada"` and `derived=False`
- [ ] Malformed XML produces a structured error, never a silently empty record
- [ ] `norma` record keyed by normalised BOE id; `articulo` records keyed by `{norma}:{art}`
- [ ] `modifica` / `deroga` relations extracted from *análisis* metadata with amending BOE ids
- [ ] Fixture checked in with an article having ≥ 3 versions
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/test_boe_parser.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_boe_parser.py
from pathlib import Path
import pytest
from parrot_tools.legal.boe.parser import parse_consolidated

FIXTURE = Path(__file__).parent / "fixtures" / "boe_consolidated_sample.xml"


@pytest.fixture
def parsed():
    return parse_consolidated(FIXTURE.read_text(encoding="utf-8"))


class TestBOEParser:
    def test_norma_keyed_by_boe_id(self, parsed):
        assert parsed.norma["boe_id"].startswith("BOE-")

    def test_single_version_article(self, parsed):
        art = next(a for a in parsed.articulos if len(a["versions"]) == 1)
        v = art["versions"][0]
        assert v["n"] == 0 and v["modified_by"] is None and v["valid_to"] is None

    def test_version_chain_has_no_gaps(self, parsed):
        art = next(a for a in parsed.articulos if len(a["versions"]) >= 3)
        vs = art["versions"]
        for prev, nxt in zip(vs, vs[1:]):
            assert prev["valid_to"] == nxt["valid_from"]
        assert vs[-1]["valid_to"] is None

    def test_supresion_has_null_text(self, parsed):
        for a in parsed.articulos:
            for v in a["versions"]:
                if v["kind"] == "supresion":
                    assert v["text"] is None

    def test_all_versions_are_boe_sourced_and_not_derived(self, parsed):
        for a in parsed.articulos:
            for v in a["versions"]:
                assert v["source"] == "boe_consolidada"
                assert v["derived"] is False

    def test_malformed_reports_error_not_silence(self):
        result = parse_consolidated("<not-valid-boe/>")
        assert result.errors, "malformed input must surface an error"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` (§2 Data Models, §7).
2. **Check dependencies** — TASK-2369 must be in `sdd/tasks/completed/`.
3. **FIRST**: verify BOE article segmentation against 3 real norms (spec §8 open question).
   Record what you find in the Completion Note.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
6. **Implement** models, parser, fixture and tests.
7. **Verify** all acceptance criteria.
8. **Move this file** to `sdd/tasks/completed/TASK-2372-boe-consolidated-parser.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** — including the segmentation finding.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-23
**Notes**: Implemented `ArticleVersion`/`ParsedNorm` (models.py) and
`parse_consolidated()` (parser.py) exactly per spec §2. Version chaining
(`valid_to[n] = valid_from[n+1]`, last `valid_to=None`, `modified_by=None`
for n=0), `source="boe_consolidada"`/`derived=False` always, and
`kind="supresion"` implies `text=None` are all enforced as parser
invariants. `modifica` (Norma→Articulo) relations are derived from each
non-original version's `id_norma` attribute (article-level granularity,
which the norma-level `análisis` metadata alone cannot provide); `deroga`
(Norma→Norma) relations are derived from `analisis/referencias/anteriores`
entries with `relacion codigo="210"`. Malformed/structurally incomplete
XML surfaces via `ParsedNorm.errors`, never a silent empty record. 10 unit
tests pass (`pytest -c pytest.ini packages/ai-parrot-tools/tests/legal/test_boe_parser.py -v`).
`ruff check` clean (fixed ISC004 string concat, DTZ007 naive-datetime, and
RUF007 zip-vs-pairwise findings during self-review).

**BOE segmentation finding (spec §8)**: Verified live against the real BOE
datos abiertos `legislacion-consolidada` API
(`https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/<BOE-ID>`,
`Accept: application/xml`) for 3 real norms: BOE-A-2015-10566 (Ley
40/2015), BOE-A-2018-16673 (LOPDGDD), and BOE-A-1889-4763 (Código Civil,
~750KB response). Segmentation IS uniform across all three: `<texto>`
contains `<bloque id="..." tipo="precepto" titulo="...">` per article/
disposición, each with one or more `<version id_norma="..."
fecha_publicacion="..." fecha_vigencia="...">` dated wording blocks in
ascending chronological document order — no normalisation step was needed.
`fecha_vigencia` maps directly to `valid_from`. Amendment annotations
appear as `<blockquote><p class="nota_pie">Se modifica/añade/suprime
...</p></blockquote>` inside each non-original version, giving a reliable
keyword-based `kind` classification signal. One gap: none of the 3 sampled
norms contained a genuine *whole-article* suppression (an entire `<bloque>`
version with empty body) within the portions inspected — Código Civil
Art. 681 showed sub-paragraph-level suppression ("Segundo. Sin contenido.")
but the article itself persisted. The fixture's `Articulo 999` block is
therefore a constructed (clearly XML-commented, non-verbatim) addition
exercising the `kind="supresion"` → `text=None` code path, following the
authentic BOE `nota_pie` annotation convention. `Artículo 50` of Ley
40/2015 is a genuine, hand-verifiable 3-version amendment chain (original
2015 → Real Decreto-ley 36/2020 → Ley 22/2021) checked into the fixture
verbatim, along with real `analisis/referencias/anteriores` DEROGA entries
— useful raw material for TASK-2376's end-to-end amendment-chain test.

**Deviations from spec**: none. One design decision not explicit in the
spec: `modifica` relations are sourced from per-version `id_norma`
(article-level) rather than the norma-level `analisis/referencias`
MODIFICA entries, because the ontology's `modifica` relation (TASK-2370)
is fixed to `Norma → Articulo`, which only the per-version data can supply
at the correct granularity.
