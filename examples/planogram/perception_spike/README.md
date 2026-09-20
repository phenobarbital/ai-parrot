# Planogram perception spike (FEAT-574)

## Purpose

Measure whether the profile-driven classical-CV proposer
(`parrot_pipelines.planogram.perception.propose_shapes`) finds the objects a
product-on-shelves planogram needs — product bodies, boxes, price/fact tags and
backlit zones — well enough to replace the LLM detector as the *perceive* stage.
The candidate profiles in `run_spike.py` (`CANDIDATE_PROFILES`) are the spike's
**hypothesis**; they ship in the package only if the gates pass.

The gates are provisional engineering gates on a small private sample, not
population accuracy claims.

## Privacy rules

- Only `*.py` files and this `README.md` are tracked in this folder
  (`.gitignore` re-ignores everything else dropped here).
- Never commit photos, annotations, crops, per-photo filenames, store names or
  paths. Keep the private sample **outside** the repository or in this folder
  (where it stays ignored).
- The report (`docs/pipelines/planogram-perception-spike.md`) contains aggregates
  only; photos are referred to by an anonymous index (`photo 1`, `photo 2`, …).

## Annotation format

One JSON file per photo, with the **same stem** as the photo
(`store_a.jpg` ↔ `store_a.json`), boxes in **source-image pixels**
`[x1, y1, x2, y2]`:

```json
{
  "image": "photo.jpg",
  "image_size": [1280, 955],
  "conditions": ["full_view", "adjacent_fixture"],
  "objects": [
    {"id": "p1", "kind": "product", "box": [412, 380, 560, 520], "membership": "on_fixture", "slot_target": true},
    {"id": "t1", "kind": "price_tag", "box": [430, 528, 520, 560], "membership": "on_fixture", "slot_target": false},
    {"id": "d1", "kind": "product", "box": [20, 400, 140, 540], "membership": "off_fixture", "slot_target": false}
  ]
}
```

- `kind`: `product`, `box`, `price_tag`, `backlit` (must match a profile `kind`).
- `membership`: `on_fixture`, `off_fixture` or `uncertain`.
- `slot_target`: `true` for each product a planogram slot is expected to cover.
- `conditions` vocabulary: `full_view`, `partial_view`, `adjacent_fixture`,
  `absent_anchors`, `repeated_skus`, `ambiguous_membership`.

## How to annotate

1. Enumerate every object of the **target fixture** — products, boxes, price and
   fact tags, the backlit header — with tight boxes.
2. Also annotate the **neighbouring distractors** (products on adjacent
   fixtures, other aisles) with `membership: "off_fixture"`: they are what the
   membership gate measures.
3. Mark `slot_target: true` only on the products the planogram expects.
4. Record the conditions the photo exercises (a cut-off shelf is `partial_view`,
   a photo without tags or header is `absent_anchors`, …).

## Run

With the worktree sources on the path:

```bash
source .venv/bin/activate
export PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src
# No private sample: synthetic cases only (outcome is "inconclusive").
python examples/planogram/perception_spike/run_spike.py --out docs/pipelines/planogram-perception-spike.md
# With the private sample and an optional fixture-membership module exposing admit(candidates, image_size):
python examples/planogram/perception_spike/run_spike.py \
  --photos-dir /private/photos --annotations-dir /private/annotations \
  --membership-module my_membership_module \
  --out docs/pipelines/planogram-perception-spike.md
```

Other options: `--iou` (matching threshold, default 0.5) and `--work-width`
(proposer work width, default 2048).

## Reading the report

- **Gates**: product-slot recall and precision ≥ 0.90 on every evaluable photo;
  zero off-fixture observations admitted (`untested` without a membership
  module); synthetic cases (partial shelf, absent anchors, adjacent fixture).
- **Outcome**: `passed` only when every gate passes; `inconclusive` with fewer
  than three evaluable photos, a required condition never exercised
  (`partial_view`, `adjacent_fixture`, `absent_anchors`) or any `untested`
  gate; otherwise `failed` when a gate fails.
- **Consequence**: `ProductOnShelves` keeps `perception_mode="llm_detector"`
  unless the outcome is `passed`; the `## Accepted profiles` JSON list is empty
  otherwise.
