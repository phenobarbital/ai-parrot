# TASK-3350: CLI entry point `planogram_check.py`, README and example catalog

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3349, TASK-3339
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12 (CLI half)** and §2 "User-facing behaviour". `planogram_check.py`
is the deliverable the user asked for by name: a *thin* entry point that parses
arguments, builds a `Settings`, calls `run_check` from
`examples/planogram/plancheck/pipeline.py` (TASK-3349) and maps the outcome to the
exit codes `0 / 1 / 2`. It also owns the user documentation (`README.md`) and a
**synthetic** `catalog.example.json` showing the required catalog format, plus the
`--emit-catalog-template` short-circuit built on
`examples/planogram/plancheck/reference.py` (TASK-3339).

---

## Scope

- Implement `build_parser()` and `main(argv) -> int` in `examples/planogram/planogram_check.py`
  with the option set of spec §2, exactly.
- Exit codes: `0` complete · `2` complete with recorded errors (`report.run.errors`) · `1` invalid input.
  **argparse's own error path must exit 1, not its default 2.**
- `--catalog` is required for a run but NOT for `--emit-catalog-template` → validate by hand; the
  message must name `--emit-catalog-template`.
- `--emit-catalog-template <path>`: load the planogram, write the template, exit 0 — no images, no LLM.
- Image discovery for `--images-dir`: non-recursive, sorted by file name, extensions
  jpg/jpeg/png/webp/bmp/tif/tiff (case-insensitive); missing or empty → exit 1.
- `logging` only (configure it in `main`); no `print`.
- Write `examples/planogram/README.md` with the sections required by spec §5 (last criterion).
- Write `examples/planogram/catalog.example.json` — **synthetic SKUs only**.
- Write `examples/planogram/tests/test_plancheck_cli.py`.

**NOT in scope**: orchestration, concurrency, verify-pass *defaulting* (TASK-3349 — the CLI only passes
`None`/`True`/`False` through); any stage logic; `.gitignore` (TASK-3336 already re-includes these three
paths); a weights flag (not in the spec's option list — see Implementation Notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/planogram_check.py` | CREATE | CLI: `build_parser`, `main`, exit codes |
| `examples/planogram/README.md` | CREATE | Install, catalog format, CLI, outputs, scoring, local recipe, A/B section |
| `examples/planogram/catalog.example.json` | CREATE | Synthetic 3-item catalog in the `Catalog` schema |
| `examples/planogram/tests/test_plancheck_cli.py` | CREATE | CLI unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import argparse                          # stdlib — argparse.BooleanOptionalAction exists (Python ≥ 3.9; verified)
import asyncio                           # stdlib
import logging                           # stdlib
import sys                               # stdlib
from collections.abc import Sequence     # stdlib
from pathlib import Path                 # stdlib
from typing import NoReturn              # stdlib
import json, types                       # stdlib (tests)
import pytest                            # tests only
```

### Existing Signatures to Use
None from the pre-existing repository. Facts that bind this task:
- `.gitignore` (after TASK-3336) re-includes exactly `examples/planogram/planogram_check.py`,
  `examples/planogram/README.md`, `examples/planogram/catalog.example.json` and `tests/**/*.py`
  (spec §7 block) — do not add other files at this level, they would be silently ignored.
- The repository is **PUBLIC**; `planogram_page1.json` and the photos are never tracked (spec §8 Q1).
- `argparse.ArgumentParser.error()` exits with status **2** by default — conflicts with this tool's
  meaning of 2, hence the subclass below.

#### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/pipeline.py — TASK-3349
async def run_check(settings: Settings, *, backend_factory: Callable[..., Any] | None = None) -> ComplianceReport
#   raises FileExistsError (output exists), FileNotFoundError / ValueError (bad inputs)
# examples/planogram/plancheck/reference.py — TASK-3339
def load_planogram(path: Path) -> PlanogramRef                          # ValueError on malformed input
def emit_catalog_template(planogram: PlanogramRef, path: Path) -> None   # FileExistsError if path exists
# examples/planogram/plancheck/vision.py — TASK-3342
class VisionError(RuntimeError)   # raised at backend __aenter__ when the client has no vision method → exit 1
# examples/planogram/plancheck/models.py — TASK-3337 / TASK-3338
class Settings(StrictModel):
    images: list[str]; planogram: str; catalog: str; output: str
    prices: str | None = None; llm: str = "google:gemini-3.8-flash"; ocr_llm: str | None = None
    base_url: str | None = None; roi: tuple[float, float, float, float] | None = None
    verify_pass: bool | None = None; marks: bool = True; concurrency: int = Field(default=4, ge=1, le=16)
    cache_dir: str; visit_id: str = "visit"; work_width: int = Field(default=2048, ge=256)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
class Catalog(StrictModel): items: list[CatalogItem]
class CatalogItem(StrictModel): sku, brand, display_name, family=None, xl=False, colors=[], pack=1, identifiers=[], aliases=[], provenance=None
#   report.run.errors: list[str]; report.compliance.strict_pct / lenient_pct / coverage
```
The script imports them as `from plancheck.… import …` (the script's own directory is `sys.path[0]` when
run as `python examples/planogram/planogram_check.py`; in tests, conftest from TASK-3337 adds it, so
`import planogram_check` works).

Catalog file shape = `Catalog.model_dump(mode="json")`, i.e. `{"items": [ {CatalogItem…}, … ]}`.
**Confirm against `load_catalog` in `examples/planogram/plancheck/reference.py` (TASK-3339) before
writing the example**; if TASK-3339 chose another shape, follow it and note the deviation.

### Does NOT Exist
- ~~`--weights` / `--api-key` / `--verbose` / `--work-width` flags~~ — not in spec §2's option list; do not add.
- ~~`argparse` "required=True" on `--catalog` / `--output`~~ — would break `--emit-catalog-template`; validate by hand.
- ~~`print(...)`~~ — AC: no `print(` in `planogram_check.py`. Use `logging`; do not call `parser.print_help()` yourself.
- ~~`import inkcheck`~~, ~~`import parrot`~~, ~~provider SDK imports~~ — the CLI imports only stdlib + `plancheck.*`.
- ~~LLM catalog enrichment~~ — out of scope; the template is a skeleton for a human to fill.
- ~~real part numbers (`C2P04AN#140`, …), brand layouts or prices from `planogram_page1.json`~~ in the README,
  the example catalog or tests — synthetic only (`AC-11`, "Acme 10 Black", …).
- ~~`sys.exit()` inside `main`~~ — `main` **returns** the code; only the `__main__` guard calls `sys.exit(main())`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/planogram_check.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/README.md",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/catalog.example.json",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_cli.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Decided details (do not re-decide)
- Defaults are resolved relative to the **script's directory** (`HERE = Path(__file__).resolve().parent`),
  never the CWD: `--images-dir HERE/images`, `--planogram HERE/planogram_page1.json`,
  `--cache-dir HERE/results/.plancheck_cache`.
- `--images-dir` and `--images` are a mutually exclusive group; neither given → the `--images-dir` default.
- `--verify-pass / --no-verify-pass` = one `argparse.BooleanOptionalAction` with `default=None`
  (tri-state: `None` lets TASK-3349 pick on-for-cloud / off-for-local).
- `--no-marks` = `action="store_false", dest="marks"`.
- `--concurrency` int, default 4, validated 1..16 (→ exit 1 otherwise).
- `--roi L T R B` four floats with `0 <= L < R <= 1` and `0 <= T < B <= 1`.
- Every path is made absolute in `main` before `run_check` (the pipeline absolutizes again — harmless,
  and required by spec §7 because importing parrot `chdir`s).
- Exceptions → exit 1: `FileExistsError`, `FileNotFoundError`, `ValueError` (includes
  `pydantic.ValidationError`), `VisionError`. Anything else propagates (a bug must not look like bad input).
- Weights: spec §2 says they are "overridable from the CLI settings" but lists no flag; `Settings.weights`
  stays at its default here. Do not invent a flag — record this in the Completion Note.

### Key Constraints
- Thin: no stage logic, no cv2, no parrot import in this file.
- Google-style docstrings, strict type hints, black line length 120.
- README is documentation for a PUBLIC repo: no store names, no photo file names, no real SKUs.

---

## Implementation Blueprint

### Steps (in order)
1. Write `catalog.example.json` — *why*: it is fully mechanical and the README + a test reference it.
2. Create `planogram_check.py` part 1 (parser) — *why*: `build_parser` is pure and pins the option set of spec §2.
3. Create part 2 (`_discover_images`, `_settings_from_args`, `main`) — *why*: all input validation lives here so every bad input funnels to exit 1.
4. Write the tests, monkeypatching `planogram_check.run_check` — *why*: the CLI must be testable without the pipeline doing real work.
5. Write the README from the skeleton — *why*: spec §5's last criterion enumerates its sections.
6. Run the validation command, `ruff check`, and `grep -n "print(" examples/planogram/planogram_check.py` (must be empty) — *why*: merge gate + AC.

### `examples/planogram/catalog.example.json` (CREATE)
```json
{
  "items": [
    {
      "sku": "AC-11",
      "brand": "Acme",
      "display_name": "Acme 10 Black",
      "family": "10",
      "xl": false,
      "colors": ["black"],
      "pack": 1,
      "identifiers": ["AC-11"],
      "aliases": ["Acme 10 Black"],
      "provenance": "synthetic example — not a real product"
    },
    {
      "sku": "AC-12",
      "brand": "Acme",
      "display_name": "Acme 10XL Black",
      "family": "10",
      "xl": true,
      "colors": ["black"],
      "pack": 1,
      "identifiers": ["AC-12"],
      "aliases": ["Acme 10XL Black", "Acme 10 XL"],
      "provenance": "synthetic example — not a real product"
    },
    {
      "sku": "AC-13",
      "brand": "Acme",
      "display_name": "Acme 10 Tri-color",
      "family": "10",
      "xl": false,
      "colors": ["tri-color"],
      "pack": 1,
      "identifiers": ["AC-13"],
      "aliases": ["Acme 10 Tri-color"],
      "provenance": "synthetic example — not a real product"
    }
  ]
}
```
**Why this shape**: it is `Catalog.model_dump(mode="json")` and shows the three things the resolver
never merges (standard vs XL, colour variants) using the same synthetic naming as the test fixtures.

### `examples/planogram/planogram_check.py` (CREATE) — part 1/2
```python
#!/usr/bin/env python3
"""Autonomous planogram compliance check (FEAT-565) — thin CLI over ``plancheck.pipeline.run_check``.

Example:
    python examples/planogram/planogram_check.py --catalog my_catalog.json --output results/run1
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from plancheck.models import Settings
from plancheck.pipeline import run_check
from plancheck.reference import emit_catalog_template, load_planogram
from plancheck.vision import VisionError

logger = logging.getLogger("planogram_check")
HERE = Path(__file__).resolve().parent
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})
EXIT_OK, EXIT_INVALID, EXIT_ERRORS = 0, 1, 2


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors exit 1 (argparse's default 2 means 'completed with errors' here)."""

    def error(self, message: str) -> NoReturn:
        logger.error("%s: %s", self.prog, message)
        raise SystemExit(EXIT_INVALID)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser — option set fixed by spec §2 'User-facing behaviour'."""
    parser = _Parser(prog="planogram_check", description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--images-dir", type=Path, default=None, help=f"Photo directory (default: {HERE / 'images'})")
    source.add_argument("--images", type=Path, nargs="+", default=None, help="Explicit photo files")
    parser.add_argument("--planogram", type=Path, default=HERE / "planogram_page1.json")
    parser.add_argument("--catalog", type=Path, default=None, help="REQUIRED for a run: part-number ↔ descriptor catalog")
    parser.add_argument("--output", type=Path, default=None, help="NEW directory for the artefacts (must not exist)")
    parser.add_argument("--llm", default="google:gemini-3.8-flash", help="provider:model for identification")
    parser.add_argument("--ocr-llm", default=None, help="provider:model for the price fallback (default: --llm)")
    parser.add_argument("--base-url", default=None, help="Base URL for local OpenAI-compatible servers")
    parser.add_argument("--prices", type=Path, default=None, help="Optional {sku: price} JSON → price compliance")
    parser.add_argument("--roi", type=float, nargs=4, metavar=("L", "T", "R", "B"), default=None)
    parser.add_argument("--verify-pass", action=argparse.BooleanOptionalAction, default=None,
                        help="Closed-set verification pass (default: on for cloud, off for local backends)")
    parser.add_argument("--no-marks", dest="marks", action="store_false", help="Send strips without Set-of-Marks outlines")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--cache-dir", type=Path, default=HERE / "results" / ".plancheck_cache")
    parser.add_argument("--visit-id", default="visit")
    parser.add_argument("--emit-catalog-template", type=Path, default=None, metavar="PATH",
                        help="Write a catalog skeleton for the planogram and exit")
    return parser
```
**Why this shape**: `_Parser.error` is the only way to keep "invalid input → 1" true for argparse-level
mistakes (unknown flag, `--images-dir` with `--images`, non-float ROI). `BooleanOptionalAction` with
`default=None` yields exactly `--verify-pass` / `--no-verify-pass` and the tri-state the pipeline needs.
`--catalog`/`--output` are optional at the argparse level because `--emit-catalog-template` needs neither.

### `examples/planogram/planogram_check.py` (CREATE) — part 2/2
```python
def _discover_images(args: argparse.Namespace) -> list[Path]:
    """Resolve the photo list. Raises ``ValueError``/``FileNotFoundError`` on a missing or empty selection."""
    # FILL IN: --images → those files (each must exist); else directory = args.images_dir or HERE/"images":
    #   must exist, non-recursive, keep files whose suffix.lower() is in IMAGE_SUFFIXES, sorted by name,
    #   empty → ValueError. Return absolute paths. Bounded by "Decided details" + test_cli_empty_images_dir.
    raise NotImplementedError


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Validate run arguments and build ``Settings`` with absolute paths. Raises ``ValueError``."""
    if args.catalog is None:
        raise ValueError(
            "--catalog is required. Create one with --emit-catalog-template <path>, fill it in, then pass it."
        )
    if args.output is None:
        raise ValueError("--output <new directory> is required.")
    # FILL IN: validate roi (0 <= L < R <= 1, 0 <= T < B <= 1) and 1 <= concurrency <= 16 → ValueError;
    #   return Settings(images=[str(p) ...], planogram/catalog/output/cache_dir/prices as absolute str
    #   (Path.expanduser().resolve()), llm, ocr_llm, base_url, roi=tuple|None, verify_pass=args.verify_pass,
    #   marks=args.marks, concurrency, visit_id). Do NOT pre-check that output exists — run_check does.
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        0 complete · 2 complete with recorded model/OCR errors (results written) · 1 invalid input.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # _Parser.error → 1 ; --help → 0
        return int(exc.code or 0)
    try:
        if args.emit_catalog_template is not None:
            planogram = load_planogram(args.planogram.expanduser().resolve())
            emit_catalog_template(planogram, args.emit_catalog_template.expanduser().resolve())
            logger.info("Catalog template written to %s", args.emit_catalog_template)
            return EXIT_OK
        settings = _settings_from_args(args)
        report = asyncio.run(run_check(settings))
    except (FileExistsError, FileNotFoundError, ValueError, VisionError) as exc:
        logger.error("Invalid input: %s", exc)
        return EXIT_INVALID
    # FILL IN: log one summary line (strict %, lenient %, coverage, output dir) and, when
    #   report.run.errors is non-empty, log each error at WARNING and return EXIT_ERRORS; else EXIT_OK.
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: `main` returns instead of exiting so tests can assert the code. The exception tuple
is the complete "invalid input" set — `VisionError` is there because a client with no vision method
(today: `llamacpp:` until feature `localllm-ask-to-image` lands) must exit 1 *before any work* (spec §5).
Unknown exceptions are deliberately not caught. The emit-template branch runs before any run validation,
so it needs neither `--catalog` nor `--output`.

### `examples/planogram/tests/test_plancheck_cli.py` (CREATE)
```python
"""Unit tests for the planogram_check CLI (FEAT-565, TASK-3350) — the pipeline is always faked."""
from __future__ import annotations

import json
import logging
import types
from pathlib import Path

import pytest

import planogram_check
from plancheck.models import Catalog


def _fake_report(errors: list[str]) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        run=types.SimpleNamespace(errors=errors),
        compliance=types.SimpleNamespace(strict_pct=50.0, lenient_pct=75.0, coverage=0.9),
    )


def _patch_run(monkeypatch, *, errors: list[str] | None = None, raises: Exception | None = None) -> list:
    """Replace planogram_check.run_check; return the list that captures the Settings it received."""
    seen: list = []

    async def _run(settings, **_kw):
        seen.append(settings)
        if raises is not None:
            raise raises
        return _fake_report(errors or [])

    monkeypatch.setattr(planogram_check, "run_check", _run)
    return seen


def _run_args(tmp_path: Path) -> list[str]:
    # FILL IN: create tmp_path/"imgs"/a.png (any bytes — the pipeline is faked), a planogram file and a
    #   catalog file; return ["--images-dir", ..., "--planogram", ..., "--catalog", ..., "--output",
    #   str(tmp_path / "out"), "--cache-dir", str(tmp_path / "cache")].
    raise NotImplementedError


def test_cli_requires_catalog(tmp_path, monkeypatch, caplog) -> None:
    # FILL IN: args without --catalog → main(...) == 1, run_check never called,
    #   "--emit-catalog-template" appears in caplog.text (caplog.set_level(logging.ERROR)).
    raise NotImplementedError


def test_cli_exit_codes(tmp_path, monkeypatch) -> None:
    # FILL IN: no errors → 0; errors=["row failed"] → 2; raises=FileExistsError("x") → 1;
    #   raises=ValueError("x") → 1; an unknown flag → 1 (NOT argparse's 2).
    raise NotImplementedError


def test_cli_verify_pass_tristate() -> None:
    parser = planogram_check.build_parser()
    assert parser.parse_args([]).verify_pass is None
    assert parser.parse_args(["--verify-pass"]).verify_pass is True
    assert parser.parse_args(["--no-verify-pass"]).verify_pass is False
    assert parser.parse_args([]).marks is True and parser.parse_args(["--no-marks"]).marks is False


def test_cli_settings_passthrough(tmp_path, monkeypatch) -> None:
    # FILL IN: with --llm llamacpp:occupancy --base-url http://127.0.0.1:8089/v1 --roi 0.1 0 0.9 1
    #   --no-marks --visit-id v1 → the captured Settings has those values, verify_pass is None,
    #   every path field is absolute and images are sorted by name.
    raise NotImplementedError


def test_cli_images_mutually_exclusive_and_bad_roi(tmp_path, monkeypatch) -> None:
    # FILL IN: --images-dir together with --images → 1; --roi 0.9 0 0.1 1 → 1; --concurrency 0 → 1.
    raise NotImplementedError


def test_cli_empty_images_dir(tmp_path, monkeypatch) -> None:
    # FILL IN: empty directory → 1 and run_check never called; a directory holding only "notes.txt" → 1.
    raise NotImplementedError


def test_cli_emit_catalog_template(tmp_path, monkeypatch, mini_planogram_data, mini_planogram) -> None:
    # FILL IN: dump mini_planogram_data to a file; main(["--planogram", p, "--emit-catalog-template", out]) == 0
    #   WITHOUT --catalog/--output; run_check never called; the written file lists every identity-required
    #   SKU of mini_planogram exactly once (CLOSEOUT excluded); a second call on the same path → 1.
    raise NotImplementedError


def test_catalog_example_is_valid_and_synthetic() -> None:
    path = Path(planogram_check.__file__).resolve().parent / "catalog.example.json"
    catalog = Catalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert {item.brand for item in catalog.items} == {"Acme"}
    assert all("synthetic" in (item.provenance or "") for item in catalog.items)
```
**Why this shape**: `run_check` is patched on the `planogram_check` module (that is the name `main`
resolves), so no image decoding, OCR or LLM ever runs. `test_cli_requires_catalog` and
`test_cli_exit_codes` are the two names fixed by spec §4 for M12; the rest pin the option semantics of
spec §2 and the "synthetic only" rule for the public repo.

### `examples/planogram/README.md` (CREATE)
````markdown
# Planogram compliance check (label-anchored, autonomous)

<!-- FILL IN: 3–5 sentence overview of the 8 stages (tags → slots → prices → pass 1 → registration →
     pass 2 → merge/score → report). Bounded by spec §2 Overview. No store names, no real SKUs. -->

## What stays local
Photos, `planogram_page1.json`, PDFs, videos and every result directory are git-ignored on purpose
(this repository is public). Only code, tests, this README and the synthetic `catalog.example.json` are tracked.

## Install
<!-- FILL IN: activate the repo venv (`source .venv/bin/activate`); packages used: opencv-python, numpy,
     rapidocr + onnxruntime (optional — without it prices are read by the LLM only), rapidfuzz, pydantic,
     pillow, ai-parrot + ai-parrot-client-google (+ -local). Credentials via environment variables only
     (e.g. GOOGLE_API_KEY). Bounded by spec §7 External Dependencies. -->

## The catalog (required)
<!-- FILL IN: why it is needed (planogram has part numbers, packages show consumer names); the
     `--emit-catalog-template` workflow; field-by-field table of CatalogItem; point to catalog.example.json;
     the three resolution rules and "XL / colour / pack are never fuzzy-merged". Bounded by spec §2 Decided semantics. -->

## Usage
```bash
python examples/planogram/planogram_check.py --emit-catalog-template my_catalog.json
python examples/planogram/planogram_check.py --catalog my_catalog.json --output examples/planogram/results/run1
```
<!-- FILL IN: option table — one row per flag of build_parser() with default and meaning; exit codes 0/1/2;
     `--output` must not exist; `--cache-dir` makes a second identical run perform zero LLM calls. -->

## Outputs
<!-- FILL IN: compliance.json top-level keys (run, images, slots, positions, shelves, brands, compliance,
     notes), annotated_<image_id>.jpg colour legend (STATUS_COLORS), slots/, tags/, run.snapshot.json. -->

## Scoring semantics
<!-- FILL IN: the ten position statuses (not_visible vs not_assessed vs empty!), strict vs lenient credits
     and default weights 0.5/0.5/0.5/1.0, coverage, occupancy, brand share (facings + linear), reference
     confidence (`*_direct_reference`, `run.reference_provisional`), optional price compliance.
     Bounded by spec §2 Decided semantics — copy the definitions, do not paraphrase the numbers. -->

## Local server recipe
<!-- FILL IN: `--llm llamacpp:<alias> --base-url http://127.0.0.1:8089/v1`; PREREQUISITE: feature
     `localllm-ask-to-image` (adds ask_to_image() to LocalLLMClient) — until it is merged this exits 1 with a
     message naming it; local defaults: sub-strips of ≤ 8 slots, verify pass off, concurrency 1;
     llama.cpp + LFM2.5-VL needs `cache_prompt: false` with JSON-schema constraints. -->

## Data egress
Cloud backends (the default `google:gemini-3.8-flash`) receive **strips of your store photos** and tag
contact sheets. Use a local backend if the photos must not leave the machine.

## Set-of-Marks A/B
Marks are on by default. Fill this table from the first real run (`--no-marks` on the same cached images);
flip the default if marks hurt.

| Run | Marks | Direct resolutions | Unknown slot ids dropped | Strict % | Lenient % | Notes |
|---|---|---|---|---|---|---|
| | on | | | | | |
| | off | | | | | |

## Tests
```bash
pytest examples/planogram/tests/test_plancheck_cli.py -q
```
<!-- FILL IN: one line on the worktree PYTHONPATH prefix (spec §5 first criterion). -->

## Limitations
<!-- FILL IN: axis-aligned boxes (no rectification); no accuracy claim (no ground truth); the reference
     planogram is a draft; bottom-shelf tags out of frame → no price there. Bounded by spec §1 Non-Goals + §7. -->
````
**Why this shape**: every heading maps to a clause of spec §5's last criterion (install, catalog format,
CLI, outputs, scoring semantics, local-server recipe incl. the `localllm-ask-to-image` prerequisite, an
empty "Set-of-Marks A/B" section) plus the cloud data-egress note required by spec §7. The three literal
paragraphs ("What stays local", "Data egress", the A/B table) are complete on purpose — do not reword
them into something weaker.

### FILL IN checklist
- [ ] `planogram_check.py::_discover_images` — discovery rules in "Decided details"
- [ ] `planogram_check.py::_settings_from_args` — ROI/concurrency validation + absolute paths
- [ ] `planogram_check.py::main` — summary log line + exit 0/2 from `report.run.errors`
- [ ] `test_plancheck_cli.py` — `_run_args` and six test bodies, each bounded by its comment
- [ ] `README.md` — nine FILL IN comments, each bounded by the spec section it names (remove the comments when done)

---

## Acceptance Criteria

- [ ] Option set equals spec §2 exactly (no extra flags); `--images-dir`/`--images` mutually exclusive.
- [ ] Without `--catalog`: exit 1 and the message names `--emit-catalog-template`.
- [ ] `--emit-catalog-template` works without `--catalog`/`--output`, lists every identity-required SKU once, exits 0; refuses to overwrite (exit 1).
- [ ] Exit codes: 0 / 2 (`report.run.errors`) / 1 (invalid input **including argparse errors**).
- [ ] `--verify-pass`/`--no-verify-pass` is tri-state (`None` when unset); `--no-marks` sets `marks=False`.
- [ ] All paths reaching `run_check` are absolute; defaults are relative to the script directory.
- [ ] `grep -n "print(" examples/planogram/planogram_check.py` returns nothing; no `parrot`/`inkcheck`/SDK import.
- [ ] `catalog.example.json` validates as `Catalog` and is synthetic; README has all required sections, no real SKUs/store names.
- [ ] `ruff check examples/planogram/planogram_check.py examples/planogram/tests/test_plancheck_cli.py` clean.
- [ ] All tests pass: `pytest examples/planogram/tests/test_plancheck_cli.py -q`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_cli.py -q`

---

## Test Specification

Fixed names from spec §4 (M12): `test_cli_requires_catalog`, `test_cli_exit_codes`. Added here:
`test_cli_verify_pass_tristate`, `test_cli_settings_passthrough`,
`test_cli_images_mutually_exclusive_and_bad_roi`, `test_cli_empty_images_dir`,
`test_cli_emit_catalog_template`, `test_catalog_example_is_valid_and_synthetic`.
(`test_verify_pass_auto_default` — the cloud/local *defaulting* — lives in
`examples/planogram/tests/test_plancheck_pipeline.py`, TASK-3349.) Scaffold and bounds are in the blueprint.

---

## Agent Instructions

1. **Read the spec** (§2 User-facing behaviour, §3 Module 12, §5, §7, §8 Q1/Q4/Q6/Q7).
2. **Check dependencies** — TASK-3349 and TASK-3339 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract**: confirm `run_check`, `load_planogram`, `emit_catalog_template`,
   `VisionError`, `Settings` and the catalog file shape accepted by `load_catalog`; update the contract first if any differs.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:` / `<!-- FILL IN -->`; never change a fixed signature or path.
6. **Verify** all acceptance criteria and run the validation command.
7. **Move this file** to `sdd/tasks/completed/TASK-3350-cli-readme.md` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below (mention the weights-flag ambiguity).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
