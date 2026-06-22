"""Unit tests for the Layer-2 SDD-process metrics in ``scripts.sdd.insight``.

These cover the AI-Parrot additions to the upstream Claude Insight engine:
``parse_sdd`` (read-only artifact-tree parser) and ``score_sdd`` (0-100 sub-scores
+ overall SDD-adherence band). The upstream Layer-1 fluency engine is exercised by
the vendored ``tests/test_insight.py`` suite and is intentionally not duplicated here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.sdd import insight


def _make_sdd_tree(root: Path, *, n_features: int = 2, with_ac: bool = True,
                   closed: bool = True, reviews: int = 0) -> None:
    """Scaffold a minimal but realistic sdd/ tree under ``root``."""
    (root / "specs").mkdir(parents=True)
    (root / "proposals").mkdir(parents=True)
    (root / "tasks" / "index").mkdir(parents=True)
    (root / "reviews").mkdir(parents=True)
    (root / "state").mkdir(parents=True)

    ac_block = "\n## Acceptance Criteria\n- [ ] it works\n" if with_ac else ""
    for i in range(n_features):
        slug = f"feature-{i}"
        (root / "specs" / f"{slug}.spec.md").write_text(
            f"# Feature Specification: {slug}\n\n**Status**: approved\n{ac_block}"
        )
        (root / "proposals" / f"{slug}.proposal.md").write_text("# proposal\n")
        index = {
            "feature": slug,
            "feature_id": f"FEAT-{i:03d}",
            "spec": f"sdd/specs/{slug}.spec.md",
            "completed_at": "2026-06-20T00:00:00" if closed else None,
            "tasks": [
                {
                    "id": f"TASK-{i}{j}",
                    "status": "done" if closed else "pending",
                    "depends_on": [] if j == 0 else [f"TASK-{i}0"],
                    "parallel": j > 0,
                    "effort": "M",
                    "started_at": "2026-06-20T00:00:00",
                    "completed_at": "2026-06-20T00:30:00" if closed else None,
                }
                for j in range(5)  # 5 tasks/feature -> inside the 3-8 granularity sweet spot
            ],
        }
        (root / "tasks" / "index" / f"{slug}.json").write_text(json.dumps(index))

    for r in range(reviews):
        (root / "reviews" / f"review-{r}.md").write_text("# review\n")


def test_parse_sdd_absent_tree() -> None:
    res = insight.parse_sdd("/nonexistent/path/sdd")
    assert res["present"] is False
    assert insight.score_sdd(res) is None


def test_parse_sdd_counts_and_rates(tmp_path: Path) -> None:
    _make_sdd_tree(tmp_path, n_features=3, with_ac=True, closed=True, reviews=1)
    sdd = insight.parse_sdd(str(tmp_path))

    assert sdd["present"] is True
    c = sdd["counts"]
    assert c["specs"] == 3
    assert c["features"] == 3
    assert c["features_closed"] == 3
    assert c["tasks_total"] == 15
    assert c["tasks_done"] == 15
    assert c["specs_with_ac"] == 3
    assert c["specs_with_tasks"] == 3

    assert sdd["spec_ac_rate"] == pytest.approx(1.0)
    assert sdd["spec_coverage"] == pytest.approx(1.0)
    assert sdd["feat_closure_rate"] == pytest.approx(1.0)
    assert sdd["task_done_rate"] == pytest.approx(1.0)
    assert sdd["decomp"]["median_tasks_per_feature"] == 5
    assert sdd["median_lead_minutes"] == pytest.approx(30.0)


def test_score_sdd_strong_tree_scores_high(tmp_path: Path) -> None:
    _make_sdd_tree(tmp_path, n_features=4, with_ac=True, closed=True, reviews=4)
    res = insight.score_sdd(insight.parse_sdd(str(tmp_path)))

    assert res is not None
    assert 0 <= res["overall"] <= 100
    # Full AC coverage + full review coverage + closed cycle => a high band.
    assert res["overall"] >= 70
    assert res["band"] in {"Rigorous", "Exemplary"}
    assert set(res["sub"]) == set(insight.SDD_WEIGHTS)
    assert res["sub"]["Acceptance"] == 100
    assert res["sub"]["Review"] == 100  # 4 reviews / 4 features = full coverage, squashed at 0.5 target


def test_score_sdd_no_reviews_flags_review_gap(tmp_path: Path) -> None:
    _make_sdd_tree(tmp_path, n_features=5, with_ac=True, closed=True, reviews=0)
    res = insight.score_sdd(insight.parse_sdd(str(tmp_path)))

    # The review gap is the headline finding the panel is meant to surface.
    assert res["sub"]["Review"] == 0
    assert res["sub"]["Acceptance"] == 100


def test_score_sdd_missing_acceptance_lowers_acceptance(tmp_path: Path) -> None:
    _make_sdd_tree(tmp_path, n_features=3, with_ac=False, closed=True, reviews=0)
    res = insight.score_sdd(insight.parse_sdd(str(tmp_path)))
    assert res["sub"]["Acceptance"] == 0


def test_score_sdd_open_features_lower_closure(tmp_path: Path) -> None:
    _make_sdd_tree(tmp_path, n_features=3, with_ac=True, closed=False, reviews=0)
    sdd = insight.parse_sdd(str(tmp_path))
    res = insight.score_sdd(sdd)
    assert sdd["feat_closure_rate"] == pytest.approx(0.0)
    assert sdd["task_done_rate"] == pytest.approx(0.0)
    assert res["sub"]["Closure"] == 0


def test_parse_sdd_handles_mixed_tz_timestamps(tmp_path: Path) -> None:
    """Index timestamps mix tz-aware and naive forms; lead-time must not crash."""
    (tmp_path / "specs").mkdir(parents=True)
    (tmp_path / "tasks" / "index").mkdir(parents=True)
    (tmp_path / "specs" / "f.spec.md").write_text("**Status**: approved\n## Acceptance Criteria\n")
    index = {
        "feature": "f", "spec": "sdd/specs/f.spec.md", "completed_at": "2026-06-20T00:00:00",
        "tasks": [{
            "id": "TASK-1", "status": "done", "depends_on": [], "effort": "S",
            "started_at": "2026-06-20T00:00:00+00:00",   # tz-aware
            "completed_at": "2026-06-20T01:00:00",        # naive
        }],
    }
    (tmp_path / "tasks" / "index" / "f.json").write_text(json.dumps(index))
    sdd = insight.parse_sdd(str(tmp_path))
    assert sdd["median_lead_minutes"] == pytest.approx(60.0)
