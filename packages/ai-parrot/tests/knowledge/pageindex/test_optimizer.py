"""Unit tests for parrot.knowledge.pageindex.optimizer (FEAT-846 M1)."""

import pytest

from parrot.knowledge.pageindex.optimizer import (
    OptimizeReport,
    OptimizerSettings,
    OptimizePlan,
    PassStamp,
    assign_ownership,
    expand_at_headings,
    finalize_stamps,
    is_stamped,
    normalize,
    optimizable_roots,
    owned_tokens,
    pass_input,
    plan_deterministic,
    repair_ownership,
    should_expand,
    stamp_input,
    validate_candidate,
)
from parrot.knowledge.pageindex.segments import DocumentRevision, render_body, revision_id, segment_text


@pytest.fixture(autouse=True)
def _stub_tokens(monkeypatch):
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": max(1, len(text) // 4)
    )


@pytest.fixture
def revision() -> DocumentRevision:
    segments = segment_text("# Parent\n\nlead\n\n# First\n\nsmall\n\n# Second\n\ntail", ["Document"])
    return DocumentRevision(
        doc_id="doc",
        revision=revision_id(segments),
        source={"name": "document.md", "kind": "markdown"},
        created_at="2026-01-01T00:00:00Z",
        segments=segments,
    )


def test_owned_tokens_and_scope(revision: DocumentRevision) -> None:
    root = {
        "node_id": "root",
        "nodes": [
            {"node_id": "missing", "doc_id": "missing", "revision": "none", "span": [0, 1], "owned": [[0, 1]]},
            {
                "node_id": "doc",
                "doc_id": "doc",
                "revision": revision.revision,
                "span": [0, 5],
                "owned": [[0, 2], [3, 5]],
            },
            {
                "node_id": "locked",
                "doc_id": "doc",
                "revision": revision.revision,
                "locked": True,
                "span": [0, 1],
                "owned": [[0, 1]],
            },
        ],
    }
    scoped = optimizable_roots(root, {("doc", revision.revision): revision})
    assert scoped == [root["nodes"][1]]
    assert owned_tokens(scoped[0], revision) == sum(
        segment.tokens for segment in revision.segments[:2] + revision.segments[3:5]
    )
    assert optimizable_roots(root, {("doc", revision.revision): revision}, node_id="doc") == [root["nodes"][1]]


def test_repair_gaps_and_reject_overlaps(revision: DocumentRevision) -> None:
    parent = {"node_id": "parent", "span": [0, 5], "owned": [[0, 1], [4, 5]]}
    child = {"node_id": "child", "span": [1, 4], "owned": []}
    report = OptimizeReport()
    assert repair_ownership([parent, child], revision, report) == []
    assert child["owned"] == [[1, 4]]
    assert report.repaired_gaps == 1

    overlap = {"node_id": "overlap", "span": [4, 5], "owned": [[4, 5]]}
    original = list(parent["owned"])
    problems = repair_ownership([parent, overlap], revision, report)
    assert problems and problems[0].startswith("overlap")
    assert parent["owned"] == original


def test_normalize_duplicates_empty_and_tiny(revision: DocumentRevision) -> None:
    children = [
        {"title": "First", "concept_id": "first", "span": [0, 2], "owned": [[0, 2]]},
        {"title": "Duplicate", "concept_id": "duplicate", "span": [0, 2], "owned": [[0, 2]]},
        {"title": "Empty", "span": [2, 2], "owned": []},
        {"title": "Tiny", "concept_id": "tiny", "span": [2, 3], "owned": [[2, 3]]},
        {"title": "Tail", "concept_id": "tail", "span": [3, 5], "owned": [[3, 5]]},
        {"title": "Separate", "span": [8, 9], "owned": [[4, 5]]},
    ]
    report = OptimizeReport()
    normalize(children, revision, OptimizerSettings(min_leaf_tokens=100), report)
    assert [child["title"] for child in children] == ["Tail", "Separate"]
    tail = children[0]
    assert tail["aliases"] == ["tiny", "first", "duplicate"]
    assert {item["label"] for item in tail["key_items"]} >= {"Duplicate", "First", "Tiny"}
    assert {action.reason for action in report.merged} == {"duplicate_span", "under_minimum"}


def test_assign_ownership_residuals(revision: DocumentRevision) -> None:
    parent = {
        "title": "Parent",
        "span": [0, 5],
        "owned": [[0, 5]],
        "nodes": [
            {"title": "First", "span": [1, 2], "owned": [[1, 2]]},
            {"title": "Second", "span": [3, 4], "owned": [[3, 4]]},
        ],
    }
    assign_ownership(parent)
    assert parent["owned"] == [[0, 1], [2, 3], [4, 5]]
    body = render_body(revision, parent, parent["nodes"])
    assert "<!-- continues in: First -->" in body
    assert "<!-- continues in: Second -->" in body


def test_expand_at_headings_and_cost_model(revision: DocumentRevision) -> None:
    root = {
        "title": "Parent",
        "doc_id": "doc",
        "revision": revision.revision,
        "span": [0, 5],
        "owned": [[0, 5]],
        "nodes": [],
    }
    settings = OptimizerSettings(target_leaf_tokens=1, min_leaf_tokens=1, routing_tokens_per_child=0)
    report = OptimizeReport()
    expand_at_headings(root, revision, settings, report, depth=0)
    assert [node["title"] for node in root["nodes"]] == ["First", "Second"]
    assert len(report.expanded) == 1
    assert not should_expand(100, [10, 1], 1, OptimizerSettings(min_leaf_tokens=2))


def test_stamp_idempotence(revision: DocumentRevision) -> None:
    tree = {
        "node_id": "doc",
        "title": "Parent",
        "doc_id": "doc",
        "revision": revision.revision,
        "span": [0, 5],
        "owned": [[0, 5]],
        "nodes": [],
    }
    settings = OptimizerSettings(target_leaf_tokens=9999)
    plan = plan_deterministic(tree, {("doc", revision.revision): revision}, settings, tree_name="tree")
    node = plan.candidate
    assert "optimizer" not in node
    input_hash = stamp_input(node)
    plan.pending_stamps[id(node)] = {
        "headings": {
            "version": "v1",
            "input": input_hash,
            "settings": settings.settings_hash(),
            "execution": "deterministic",
            "at": "2026-01-01T00:00:00Z",
        }
    }
    plan.pending_stamps[id(node)]["headings"] = PassStamp(**plan.pending_stamps[id(node)]["headings"])
    finalize_stamps(plan)
    assert is_stamped(node, settings, pass_name="headings", input_hash=input_hash, execution="deterministic")
    assert node["optimizer"]["passes"]["headings"]["at"] == "2026-01-01T00:00:00Z"
    assert not is_stamped(
        {"optimizer": True}, settings, pass_name="headings", input_hash=input_hash, execution="deterministic"
    )


def test_stamp_summary_dependencies() -> None:
    node = {
        "doc_id": "doc",
        "revision": "rev",
        "title": "Parent",
        "owned": [[0, 2]],
        "key_items": [{"label": "Parent", "seq": 0}],
        "nodes": [{"title": "Child", "span": [0, 2], "summary": "one", "key_items": []}],
    }
    original = pass_input(node, "summary")
    node["nodes"][0]["summary"] = "two"
    assert pass_input(node, "summary") != original
    node["nodes"][0]["summary"] = "one"
    node["key_items"].append({"label": "Again", "seq": 1})
    assert pass_input(node, "summary") != original


def test_validate_candidate_allows_absorbed_alias_but_not_silent_removal(revision: DocumentRevision) -> None:
    base_child = {"node_id": "0002", "concept_id": "a/tiny", "title": "Tiny", "nodes": []}
    base = {"node_id": "0001", "concept_id": "a", "title": "A", "nodes": [base_child]}
    absorbed = {"node_id": "0001", "concept_id": "a", "title": "A", "aliases": ["a/tiny"], "nodes": []}
    removed = {"node_id": "0001", "concept_id": "a", "title": "A", "nodes": []}
    revisions = {("doc", revision.revision): revision}

    ok_plan = OptimizePlan(absorbed, OptimizeReport())
    ok_plan.mutable.add(id(absorbed))
    assert not any("was removed" in e for e in validate_candidate(ok_plan, revisions, base_tree=base))

    bad_plan = OptimizePlan(removed, OptimizeReport())
    bad_plan.mutable.add(id(removed))
    assert any("protected node 0002 was removed" in e for e in validate_candidate(bad_plan, revisions, base_tree=base))


def test_validate_candidate(revision: DocumentRevision) -> None:
    candidate = {
        "node_id": "doc",
        "title": "Parent",
        "doc_id": "doc",
        "revision": revision.revision,
        "span": [0, 5],
        "owned": [[0, 4]],
        "key_items": [{"label": "bad", "seq": 4}],
        "nodes": [],
    }
    plan = OptimizePlan(candidate, OptimizeReport())
    assert len(validate_candidate(plan, {("doc", revision.revision): revision}, base_tree=candidate)) >= 2


def test_refresh_after_counts_tracks_candidate_changes(revision: DocumentRevision) -> None:
    """The report's after-counters follow later structural passes such as LLM heading splits."""
    from parrot.knowledge.pageindex.optimizer import refresh_after_counts

    tree = {"nodes": [{"node_id": "0000", "doc_id": "doc", "revision": revision.revision, "title": "Doc", "nodes": []}]}
    plan = plan_deterministic(tree, {("doc", revision.revision): revision}, OptimizerSettings(), tree_name="t")
    before = plan.report.nodes_after

    plan.candidate["nodes"][0]["nodes"].append({"title": "Added", "nodes": []})
    refresh_after_counts(plan, {("doc", revision.revision): revision}, OptimizerSettings())

    assert plan.report.nodes_after == before + 1


# --- FEAT-853 TASK-5391: normalization identity and key-item anchor integrity -------------------------------------


def _doc_node(revision: DocumentRevision, title: str, span: list[int], owned: list[list[int]], **extra) -> dict:
    """Return a document-revision node with the given span and owned ranges."""
    return {
        "doc_id": "doc",
        "revision": revision.revision,
        "title": title,
        "span": span,
        "owned": owned,
        "nodes": [],
        **extra,
    }


def _owns(node: dict, seq: int) -> bool:
    return any(int(start) <= seq < int(end) for start, end in node.get("owned") or [])


def test_normalize_absorbs_empty_leaf_into_parent(revision: DocumentRevision) -> None:
    """With a parent, an empty leaf is removed and its concept id survives as a parent alias."""
    parent = _doc_node(revision, "Doc", [0, 6], [[0, 1]], concept_id="doc")
    preface = _doc_node(revision, "Preface", [0, 0], [], concept_id="doc/preface", node_id="0001")
    body = _doc_node(revision, "Body", [1, 6], [[1, 6]], concept_id="doc/body")
    parent["nodes"] = [preface, body]
    report = OptimizeReport()

    normalize(parent["nodes"], revision, OptimizerSettings(min_leaf_tokens=0), report, parent=parent)

    assert [child["title"] for child in parent["nodes"]] == ["Body"]
    assert parent["aliases"] == ["doc/preface"]
    assert parent["span"] == [0, 6]
    assert "key_items" not in parent
    assert [(m.reason, m.absorbed_concept_id, m.into_concept_id) for m in report.merged] == [
        ("empty", "doc/preface", "doc")
    ]


def test_normalize_keeps_published_empty_leaf_without_concept_id(revision: DocumentRevision) -> None:
    """A published empty leaf without an identity to alias is kept rather than removed."""
    parent = _doc_node(revision, "Doc", [0, 6], [[0, 1]], concept_id="doc")
    blank = _doc_node(revision, "Blank", [0, 0], [], node_id="0002")
    body = _doc_node(revision, "Body", [1, 6], [[1, 6]], concept_id="doc/body")
    parent["nodes"] = [blank, body]
    report = OptimizeReport()

    normalize(parent["nodes"], revision, OptimizerSettings(min_leaf_tokens=0), report, parent=parent)

    assert [child["title"] for child in parent["nodes"]] == ["Blank", "Body"]
    assert report.merged == []


def test_validate_accepts_preface_shaped_tree(revision: DocumentRevision) -> None:
    """A published root with an empty first leaf plans and validates (issue:33ad15e686e9)."""
    root = _doc_node(revision, "Doc", [0, 6], [[0, 6]], concept_id="doc", node_id="0000")
    root["nodes"] = [_doc_node(revision, "Preface", [0, 0], [], concept_id="doc/preface", node_id="0001")]
    base = {"nodes": [root]}
    revisions = {("doc", revision.revision): revision}

    plan = plan_deterministic(base, revisions, OptimizerSettings(), tree_name="t")
    errors = validate_candidate(plan, revisions, base_tree=base)

    assert not any("was removed" in error for error in errors), errors
    assert errors == []
    assert "doc/preface" in plan.candidate["nodes"][0]["aliases"]
    assert [m.reason for m in plan.report.merged] == ["empty"]


def test_absorb_widens_span_and_keeps_title_anchor(revision: DocumentRevision) -> None:
    """An under-minimum merge keeps the absorbed range and its title key item after assign_ownership."""
    tiny = _doc_node(revision, "Tiny", [0, 1], [[0, 1]], concept_id="doc/tiny")
    body = _doc_node(revision, "Body", [1, 6], [[1, 6]], concept_id="doc/body")
    parent = _doc_node(revision, "Doc", [0, 6], [], concept_id="doc", nodes=[tiny, body])
    report = OptimizeReport()

    normalize(parent["nodes"], revision, OptimizerSettings(min_leaf_tokens=3), report, parent=parent)
    assign_ownership(parent)

    (absorber,) = parent["nodes"]
    assert absorber["title"] == "Body"
    assert absorber["span"] == [0, 6]
    assert [item["seq"] for item in absorber["key_items"] if item["label"] == "Tiny"] == [0]
    assert all(_owns(absorber, item["seq"]) for item in absorber["key_items"])
    assert parent["owned"] == []


def test_split_moves_key_items_to_pieces(revision: DocumentRevision) -> None:
    """Key items of a split leaf move to the piece that owns their anchor (issue:66f376157327)."""
    from parrot.knowledge.pageindex.optimizer import split_at

    leaf = _doc_node(
        revision,
        "Doc",
        [0, 6],
        [[0, 6]],
        key_items=[
            {"label": "lead", "kind": "literal", "seq": 1},
            {"label": "small", "kind": "literal", "seq": 3},
            {"label": "tail", "kind": "literal", "seq": 5},
        ],
    )
    report = OptimizeReport()
    settings = OptimizerSettings(min_leaf_tokens=0, routing_tokens_per_child=0)

    pieces = split_at(leaf, revision, [2, 4], source="layout", settings=settings, report=report)

    assert [piece["title"] for piece in pieces] == ["First", "Second"]
    assert [item["seq"] for item in leaf["key_items"]] == [1]
    assert [item["seq"] for item in pieces[0]["key_items"]] == [3]
    assert [item["seq"] for item in pieces[1]["key_items"]] == [5]
    assert report.key_items_rehomed == 2
    plan = OptimizePlan({"nodes": [leaf]}, OptimizeReport())
    errors = validate_candidate(plan, {("doc", revision.revision): revision}, base_tree={"nodes": []})
    assert not any("key_item anchor" in error for error in errors), errors


def test_expand_at_headings_moves_persisted_key_items(revision: DocumentRevision) -> None:
    """The deterministic heading split also moves persisted key items to the pieces."""
    leaf = _doc_node(
        revision,
        "Doc",
        [0, 6],
        [[0, 6]],
        key_items=[{"label": "tail", "kind": "literal", "seq": 5}],
    )
    report = OptimizeReport()
    settings = OptimizerSettings(target_leaf_tokens=1, min_leaf_tokens=0, routing_tokens_per_child=0)

    expand_at_headings(leaf, revision, settings, report, depth=0)

    assert leaf["nodes"], "the leaf was expected to split at its headings"
    assert "key_items" not in leaf
    owner = next(piece for piece in leaf["nodes"] if _owns(piece, 5))
    assert [item["seq"] for item in owner["key_items"]] == [5]


def test_reconcile_rehomes_or_drops(revision: DocumentRevision) -> None:
    """Misplaced anchors move to a mutable owner or are dropped; non-mutable nodes are untouched."""
    from parrot.knowledge.pageindex.optimizer import reconcile_key_items

    stray = [
        {"label": "x", "kind": "abstractive", "seq": 0},
        {"label": "y", "kind": "abstractive", "seq": 4},
        {"label": "z", "kind": "abstractive", "seq": 2},
    ]
    child = _doc_node(revision, "Child", [2, 4], [[2, 4]], key_items=list(stray))
    frozen = _doc_node(revision, "Frozen", [4, 6], [[4, 6]])
    root = _doc_node(revision, "Doc", [0, 6], [[0, 2]], nodes=[child, frozen])
    report = OptimizeReport()

    reconcile_key_items(root, revision, {id(root), id(child)}, report)

    assert [item["label"] for item in root["key_items"]] == ["x"]
    assert [item["label"] for item in child["key_items"]] == ["z"]
    assert "key_items" not in frozen
    assert report.key_items_rehomed == 1
    assert report.rejected_proposals == 1


# --- FEAT-853 TASK-5392: heading-text rule and pseudo-heading fallback --------------------------------------------

_PROSE = "Una frase larga de prosa que ocupa espacio suficiente para superar el presupuesto de la hoja. " * 30


def _markdown_tree(text: str, title: str = "Libro") -> tuple[dict, dict]:
    """Return a one-leaf optimizer tree and its revisions for a markdown text."""
    segments = segment_text(text, [title])
    revision = DocumentRevision(
        doc_id="libro",
        revision=revision_id(segments),
        source={"name": "libro.md", "kind": "markdown"},
        created_at="2026-01-01T00:00:00Z",
        segments=segments,
    )
    tree = {
        "nodes": [
            {
                "doc_id": "libro",
                "revision": revision.revision,
                "title": title,
                "span": [0, len(segments)],
                "owned": [[0, len(segments)]],
                "nodes": [],
            }
        ]
    }
    return tree, {("libro", revision.revision): revision}


def test_is_heading_text_rules() -> None:
    """Fragments, trailing conjunctions and list markers are not headings; numbered and caps titles are."""
    from parrot.knowledge.pageindex.optimizer import is_heading_text

    rejected = [
        "",
        "the system shall enforce the access policy; and",
        "Scope:",
        "Notes,",
        "A sentence.",
        "(a) Policy and procedures",
        "a) Policy",
        "(iv) Review",
        "- item",
        "• bullet",
        "Ends with y",
        "Read or",
        " ".join(["word"] * 21),
    ]
    accepted = ["1. Introduction", "Chapter 3", "SEGUNDA PARTE", "Topic heading", "Appendix E", "Capítulo I"]
    assert [title for title in rejected if is_heading_text(title)] == []
    assert [title for title in accepted if not is_heading_text(title)] == []


def test_pseudo_headings_expand_bold_and_caps_lines() -> None:
    """A leaf with no `#` headings is split at standalone bold and upper-case lines (issue:0a693a57b138)."""
    tree, revisions = _markdown_tree(
        f"**P****ROLOGO**\n\n{_PROSE}\n\nSEGUNDA PARTE\n\n{_PROSE}\n\n**Capítulo I**\n\n{_PROSE}"
    )
    settings = OptimizerSettings(target_leaf_tokens=100, min_leaf_tokens=20)

    plan = plan_deterministic(tree, revisions, settings, tree_name="t")

    root = plan.candidate["nodes"][0]
    assert [node["title"] for node in root["nodes"]] == ["PROLOGO", "SEGUNDA PARTE", "Capítulo I"]
    assert [action.source for action in plan.report.expanded] == ["layout"]
    assert validate_candidate(plan, revisions, base_tree={"nodes": []}) == []


def test_pseudo_headings_ignore_running_lines_and_real_headings() -> None:
    """A caps line repeated three times is a running line; a leaf with `#` headings ignores pseudo-headings."""
    from parrot.knowledge.pageindex.layout_structure import heading_title
    from parrot.knowledge.pageindex.optimizer import pseudo_heading_segments

    running = f"CRITICA DE LA RAZON PURA\n\n{_PROSE}\n\n" * 3 + f"**Prólogo**\n\n{_PROSE}"
    tree, revisions = _markdown_tree(running)
    leaf = tree["nodes"][0]
    revision = next(iter(revisions.values()))
    assert [heading_title(s.text) for s in pseudo_heading_segments(leaf, revision)] == ["Prólogo"]

    mixed, mixed_revisions = _markdown_tree(f"# Real\n\n{_PROSE}\n\n**FAKE**\n\n{_PROSE}\n\n# Other\n\n{_PROSE}")
    plan = plan_deterministic(
        mixed, mixed_revisions, OptimizerSettings(target_leaf_tokens=100, min_leaf_tokens=20), tree_name="t"
    )
    assert [node["title"] for node in plan.candidate["nodes"][0]["nodes"]] == ["Real", "Other"]


def test_coalesce_split_points_merges_tiny_pieces() -> None:
    """A short stray line no longer vetoes the split: its piece is merged and every piece meets the minimum."""
    text = f"**Uno**\n\n{_PROSE}\n\n**Dos**\n\nbreve\n\n**Tres**\n\n{_PROSE}\n\n**Cuatro**\n\n{_PROSE}\n\n**FIN**"
    tree, revisions = _markdown_tree(text)
    settings = OptimizerSettings(target_leaf_tokens=100, min_leaf_tokens=20)

    plan = plan_deterministic(tree, revisions, settings, tree_name="t")

    revision = next(iter(revisions.values()))
    pieces = plan.candidate["nodes"][0]["nodes"]
    assert [node["title"] for node in pieces] == ["Uno", "Dos", "Cuatro"]
    assert all(owned_tokens(piece, revision) >= settings.min_leaf_tokens for piece in pieces)
