from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from graph_metadata_dashboard.diff import ComparisonResult, compare
from graph_metadata_dashboard.diff.details import (
    SCHEMA_SECTIONS,
    adaptive_inline_count,
    remaining_schema_changes,
    split_map_changes,
)
from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata
from tests.conftest import load_fixture


@pytest.fixture(scope="module")
def complete_comparison() -> ComparisonResult:
    names = ("alliance", "translator_kg_open", "robokopkg")
    return compare([
        parse_graph_metadata(
            load_fixture(f"{name}.graph-metadata.json"),
            schema_data=load_fixture("robokopkg.schema.json") if name == "robokopkg" else None,
        )
        for name in names
    ], labels=list(names))


def test_comparison_preserves_large_schema_candidate_sets(
    complete_comparison: ComparisonResult,
) -> None:
    schema = complete_comparison.comparisons[1].schema
    assert len(schema.edge_changes) > 1000
    assert len(schema.node_attribute_changes) > 1000
    assert max(len(row.attribute_changes) for row in schema.node_changes) > 1000
    assert schema.raw is not None


@pytest.mark.parametrize("pair_index", [0, 1])
@pytest.mark.parametrize("category", list(SCHEMA_SECTIONS))
def test_details_include_all_remaining_items(
    complete_comparison: ComparisonResult, pair_index: int, category: str,
) -> None:
    changes = getattr(complete_comparison.comparisons[pair_index].schema, category)
    details = remaining_schema_changes(complete_comparison, pair_index, category)
    assert details.total == len(changes)
    assert details.target_label == complete_comparison.comparisons[pair_index].target.label
    paged = tuple(
        change
        for index in range(details.page_count)
        for change in remaining_schema_changes(
            complete_comparison, pair_index, category, index
        ).changes
    )
    if category in {"node_changes", "edge_changes"}:
        assert paged == changes[adaptive_inline_count(len(changes), 25):]
    else:
        visible, remaining = split_map_changes(changes, 25)
        assert paged == remaining
        assert details.inline_count == len(visible)
        for status in {change.status for change in changes}:
            group = tuple(change for change in changes if change.status == status)
            cutoff = adaptive_inline_count(len(group), 25)
            assert tuple(change for change in visible if change.status == status) == group[:cutoff]
            assert tuple(
                change for change in remaining if change.status == status
            ) == group[cutoff:]
    assert details.inline_count + len(paged) == len(changes)
    assert details.remaining_count == len(paged)
    statuses = {change.status for change in paged}
    expected_status = next(iter(statuses)) if len(statuses) == 1 else None
    for index in range(details.page_count):
        page = remaining_schema_changes(complete_comparison, pair_index, category, index)
        assert len(page.changes) <= 52
        assert page.page_index == index
        assert page.remaining_status == expected_status
        if page.page_count > 1:
            assert len(page.changes) >= 3
    assert remaining_schema_changes(complete_comparison, pair_index, category, -1).page_index == 0
    assert remaining_schema_changes(
        complete_comparison, pair_index, category, 99999
    ).page_index == details.page_count - 1


@pytest.mark.parametrize("section, field", [
    ("node_changes", "attribute_changes"),
    ("node_changes", "id_prefix_changes"),
    ("edge_changes", "attribute_changes"),
    ("edge_changes", "primary_source_changes"),
    ("edge_changes", "qualifier_changes"),
    ("edge_changes", "subject_id_prefix_changes"),
    ("edge_changes", "object_id_prefix_changes"),
])
def test_nested_details_preserve_all_remaining_items(
    complete_comparison: ComparisonResult, section: str, field: str,
) -> None:
    rows = getattr(complete_comparison.comparisons[1].schema, section)
    row_index = max(range(len(rows)), key=lambda index: len(getattr(rows[index], field)))
    category = f"{section}/{row_index}/{field}"
    details = remaining_schema_changes(complete_comparison, 1, category)
    changes = getattr(rows[row_index], field)
    visible, remaining = split_map_changes(changes, 6)
    assert details.inline_count == len(visible)
    if section == "node_changes" and field == "attribute_changes":
        assert details.total > 1000
        assert details.remaining_count > 1000
    paged = tuple(
        change for index in range(details.page_count)
        for change in remaining_schema_changes(complete_comparison, 1, category, index).changes
    )
    assert paged == remaining
    for status in {change.status for change in changes}:
        group = tuple(change for change in changes if change.status == status)
        cutoff = adaptive_inline_count(len(group), 6)
        assert tuple(change for change in visible if change.status == status) == group[:cutoff]
        assert tuple(change for change in remaining if change.status == status) == group[cutoff:]


@pytest.mark.parametrize("limit", [6, 25])
@pytest.mark.parametrize("extra", [0, 1, 2, 3])
def test_inline_limits_absorb_only_small_remainders(
    complete_comparison: ComparisonResult, limit: int, extra: int,
) -> None:
    changes = tuple(
        change for change in complete_comparison.comparisons[1].schema.node_attribute_changes
        if change.status == "added"
    )[:limit + extra]
    visible, remaining = split_map_changes(changes, limit)
    expected_visible = limit + extra if extra <= 2 else limit
    assert len(visible) == expected_visible
    assert remaining == changes[expected_visible:]
    assert visible + remaining == changes


@pytest.mark.parametrize("remaining_count, sizes", [
    (0, [0]), (1, [0]), (2, [0]), (3, [3]),
    (49, [49]), (50, [50]), (51, [51]), (52, [52]), (53, [50, 3]),
    (100, [50, 50]), (101, [50, 51]), (102, [50, 52]), (103, [50, 50, 3]),
])
def test_modal_pages_absorb_small_final_remainders(
    complete_comparison: ComparisonResult, remaining_count: int, sizes: list[int],
) -> None:
    pair = complete_comparison.comparisons[1]
    changes = tuple(
        change for change in pair.schema.node_attribute_changes if change.status == "added"
    )
    pair = replace(pair, schema=replace(
        pair.schema, node_attribute_changes=changes[:25 + remaining_count]
    ))
    result = replace(complete_comparison, comparisons=(pair,))
    first = remaining_schema_changes(result, 0, "node_attribute_changes")
    pages = [remaining_schema_changes(result, 0, "node_attribute_changes", index)
             for index in range(first.page_count)]
    assert [len(page.changes) for page in pages] == sizes
    assert tuple(change for page in pages for change in page.changes) == changes[
        first.inline_count:25 + remaining_count
    ]


@pytest.mark.parametrize("page", ["1", None, True, 1.5])
def test_details_reject_invalid_page_numbers(
    complete_comparison: ComparisonResult, page: Any,
) -> None:
    with pytest.raises(ValueError):
        remaining_schema_changes(complete_comparison, 0, "node_changes", page)


@pytest.mark.parametrize("pair, category", [
    (-1, "node_changes"),
    (2, "node_changes"),
    ("0", "node_changes"),
    (0, "raw"),
    (0, "node_changes/-1/attribute_changes"),
    (0, "node_changes/999999/attribute_changes"),
    (0, "node_changes/0/__dict__"),
    (0, "node_attribute_changes/0/count"),
    (0, None),
])
def test_details_reject_invalid_requests(
    complete_comparison: ComparisonResult, pair: Any, category: Any,
) -> None:
    with pytest.raises(ValueError):
        remaining_schema_changes(complete_comparison, pair, category)
