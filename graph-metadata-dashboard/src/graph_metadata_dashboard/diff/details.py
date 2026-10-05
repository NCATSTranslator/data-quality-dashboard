from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from graph_metadata_dashboard.diff.comparison import (
    TOP_SCHEMA_DIFFS,
    TOP_SCHEMA_ROW_MAP_DIFFS,
    ComparisonResult,
    EdgeSchemaChange,
    MapEntryChange,
    NodeSchemaChange,
)

INLINE_GRACE = 2
SCHEMA_PAGE_SIZE = 50

SCHEMA_SECTIONS = {
    "node_changes": "Node Category Changes",
    "edge_changes": "Edge Triple Changes",
    "node_id_prefix_changes": "Node ID prefixes",
    "node_attribute_changes": "Node attributes",
    "edge_predicate_changes": "Edge predicates",
    "edge_source_changes": "Edge primary sources",
    "edge_source_predicate_changes": "Edge source-predicate composition",
    "edge_qualifier_changes": "Edge qualifiers",
    "edge_attribute_changes": "Edge attributes",
}
NODE_DETAILS = {"id_prefix_changes": "ID prefixes", "attribute_changes": "Attributes"}
EDGE_DETAILS = {
    "primary_source_changes": "Primary sources",
    "qualifier_changes": "Qualifiers",
    "attribute_changes": "Attributes",
    "subject_id_prefix_changes": "Subject prefixes",
    "object_id_prefix_changes": "Object prefixes",
}


@dataclass(frozen=True)
class SchemaChangeSource:
    pair_index: int
    category: str
    title: str
    baseline_label: str
    target_label: str
    changes: tuple[NodeSchemaChange | EdgeSchemaChange | MapEntryChange, ...]


@dataclass(frozen=True)
class SchemaChangeDetails:
    pair_index: int
    category: str
    title: str
    baseline_label: str
    target_label: str
    changes: tuple[NodeSchemaChange | EdgeSchemaChange | MapEntryChange, ...]
    total: int
    inline_count: int
    remaining_count: int
    remaining_status: str | None
    page_index: int
    page_count: int
    start_index: int


def adaptive_inline_count(total: int, limit: int) -> int:
    return total if total <= limit + INLINE_GRACE else limit


def split_map_changes(
    changes: tuple[MapEntryChange, ...], limit: int,
) -> tuple[tuple[MapEntryChange, ...], tuple[MapEntryChange, ...]]:
    totals = Counter(change.status for change in changes)
    counts: Counter[str] = Counter()
    visible = []
    remaining = []
    for change in changes:
        counts[change.status] += 1
        if counts[change.status] <= adaptive_inline_count(totals[change.status], limit):
            visible.append(change)
        else:
            remaining.append(change)
    return tuple(visible), tuple(remaining)


def remaining_schema_changes(
    result: ComparisonResult, pair_index: int, category: str, page_index: int = 0,
) -> SchemaChangeDetails:
    if not isinstance(category, str):
        raise ValueError("Unknown schema category.")
    source = schema_change_source(result, pair_index, category.split("/")[0])
    return schema_change_page(schema_detail_source(source, category), page_index)


def schema_change_source(
    result: ComparisonResult, pair_index: int, category: str,
) -> SchemaChangeSource:
    if type(pair_index) is not int or not 0 <= pair_index < len(result.comparisons):
        raise ValueError("Unknown graph comparison.")
    if category not in SCHEMA_SECTIONS:
        raise ValueError("Unknown schema category.")
    pair = result.comparisons[pair_index]
    return SchemaChangeSource(
        pair_index=pair_index, category=category, title=SCHEMA_SECTIONS[category],
        baseline_label=pair.baseline.label, target_label=pair.target.label,
        changes=getattr(pair.schema, category),
    )


def schema_detail_source(source: SchemaChangeSource, category: str) -> SchemaChangeSource:
    if category == source.category:
        return source
    parts = category.split("/")
    section = parts[0]
    if section != source.category or len(parts) != 3:
        raise ValueError("Unknown schema category.")
    details = NODE_DETAILS if section == "node_changes" else EDGE_DETAILS
    if section not in {"node_changes", "edge_changes"} or parts[2] not in details:
        raise ValueError("Unknown schema detail category.")
    if not parts[1].isdigit() or not 0 <= int(parts[1]) < len(source.changes):
        raise ValueError("Unknown schema row.")
    row = source.changes[int(parts[1])]
    label = (
        row.label if isinstance(row, NodeSchemaChange)
        else f"{row.subject_category} / {row.predicate} / {row.object_category}"
    )
    return replace(source, category=category, title=f"{label}: {details[parts[2]]}",
                   changes=getattr(row, parts[2]))


def schema_change_page(source: SchemaChangeSource, page_index: int = 0) -> SchemaChangeDetails:
    if type(page_index) is not int:
        raise ValueError("Invalid page number.")
    changes = source.changes
    inline_limit = TOP_SCHEMA_ROW_MAP_DIFFS if "/" in source.category else TOP_SCHEMA_DIFFS
    if source.category not in {"node_changes", "edge_changes"}:
        visible, remaining = split_map_changes(changes, inline_limit)
    else:
        inline_limit = adaptive_inline_count(len(changes), inline_limit)
        visible, remaining = changes[:inline_limit], changes[inline_limit:]
    page_count = max(1, (len(remaining) - INLINE_GRACE + SCHEMA_PAGE_SIZE - 1) // SCHEMA_PAGE_SIZE)
    page_index = max(0, min(page_index, page_count - 1))
    start = page_index * SCHEMA_PAGE_SIZE
    end = len(remaining) if page_index == page_count - 1 else start + SCHEMA_PAGE_SIZE
    statuses = {change.status for change in remaining}
    return SchemaChangeDetails(
        pair_index=source.pair_index,
        category=source.category,
        title=source.title,
        baseline_label=source.baseline_label,
        target_label=source.target_label,
        changes=remaining[start:end],
        total=len(changes),
        inline_count=len(visible),
        remaining_count=len(remaining),
        remaining_status=next(iter(statuses)) if len(statuses) == 1 else None,
        page_index=page_index,
        page_count=page_count,
        start_index=start,
    )
