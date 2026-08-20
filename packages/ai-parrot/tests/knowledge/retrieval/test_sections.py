"""Tests for TASK-2279: `SectionSelector` derivation from `QueryClass`.

Spec: sdd/specs/graphindex-retriever.spec.md §6.1, OQ-5, RQ-4.
"""

import pytest
from parrot.knowledge.graphindex.extractors.code import _DEFAULT_TAGS
from parrot.knowledge.retrieval.classifier import QueryClass
from parrot.knowledge.retrieval.sections import (
    GOTCHA_TAGS,
    RATIONALE_TAGS,
    SectionKind,
    selector_for,
)


def test_rationale_class_selector() -> None:
    selector = selector_for(QueryClass.RATIONALE)
    assert selector.include == (SectionKind.RATIONALE, SectionKind.OVERVIEW)


def test_global_summary_class_selector() -> None:
    selector = selector_for(QueryClass.GLOBAL_SUMMARY)
    assert selector.include == (
        SectionKind.OVERVIEW,
        SectionKind.CONTRACTS,
        SectionKind.DEPENDENCIES,
    )


@pytest.mark.parametrize("qc", list(QueryClass))
def test_every_query_class_has_a_selector(qc: QueryClass) -> None:
    selector = selector_for(qc)
    assert selector.include
    assert selector.fill_order


def test_tag_partition_covers_l0_default_tags() -> None:
    assert GOTCHA_TAGS | RATIONALE_TAGS == _DEFAULT_TAGS


def test_tag_partition_is_disjoint() -> None:
    assert GOTCHA_TAGS & RATIONALE_TAGS == frozenset()


def test_gotcha_tags_exact() -> None:
    assert GOTCHA_TAGS == frozenset({"HACK", "TODO", "FIXME", "XXX"})


def test_rationale_tags_exact() -> None:
    assert RATIONALE_TAGS == frozenset({"NOTE", "WHY"})


def test_default_max_tokens_per_section() -> None:
    selector = selector_for(QueryClass.RATIONALE)
    assert selector.max_tokens_per_section == 1_200


def test_selector_frozen_and_forbid_extra() -> None:
    from pydantic import ValidationError

    selector = selector_for(QueryClass.RATIONALE)
    with pytest.raises(ValidationError):
        selector.max_tokens_per_section = 99  # type: ignore[misc]
