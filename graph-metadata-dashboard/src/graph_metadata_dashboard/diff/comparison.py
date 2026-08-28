from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from graph_metadata_dashboard.parsers.models import (
    GraphSchema,
    KnowledgeSource,
    ParsedGraphMetadata,
    SubgraphSource,
    int_or_none,
)

JsonObject = dict[str, Any]
TOP_SCHEMA_DIFFS = 25
TOP_SCHEMA_ROW_MAP_DIFFS = 6


@dataclass(frozen=True)
class CountDelta:
    old: int | None
    new: int | None
    delta: int | None
    percent_change: float | None


@dataclass(frozen=True)
class GraphSummary:
    label: str
    name: str
    release_version: str
    date_created: str
    date_modified: str
    license: str
    biolink_version: str
    babel_version: str
    node_count: int | None
    edge_count: int | None
    source_count: int
    subgraph_count: int
    schema_status: str


@dataclass(frozen=True)
class FieldDifference:
    field: str
    old: str
    new: str


@dataclass(frozen=True)
class SourceChange:
    source_id: str
    name: str
    status: str
    old_version: str
    new_version: str
    old_license: str
    new_license: str


@dataclass(frozen=True)
class SubgraphChange:
    source_id: str
    name: str
    node_delta: CountDelta
    edge_delta: CountDelta
    status: str


@dataclass(frozen=True)
class TypeCountChange:
    label: str
    status: str
    count: CountDelta


@dataclass(frozen=True)
class EdgeTypeCountChange:
    subject_category: str
    predicate: str
    object_category: str
    status: str
    count: CountDelta


@dataclass(frozen=True)
class MapEntryChange:
    label: str
    status: str
    count: CountDelta


@dataclass(frozen=True)
class NodeSchemaChange:
    label: str
    status: str
    count: CountDelta
    id_prefix_changes: tuple[MapEntryChange, ...]
    attribute_changes: tuple[MapEntryChange, ...]


@dataclass(frozen=True)
class EdgeSchemaChange:
    subject_category: str
    predicate: str
    object_category: str
    status: str
    count: CountDelta
    primary_source_changes: tuple[MapEntryChange, ...]
    qualifier_changes: tuple[MapEntryChange, ...]
    attribute_changes: tuple[MapEntryChange, ...]
    subject_id_prefix_changes: tuple[MapEntryChange, ...]
    object_id_prefix_changes: tuple[MapEntryChange, ...]


@dataclass(frozen=True)
class SchemaDiffSummary:
    available: bool
    message: str
    node_total: CountDelta | None = None
    edge_total: CountDelta | None = None
    node_type_count: dict[str, int] | None = None
    edge_type_count: dict[str, int] | None = None
    node_changes: tuple[NodeSchemaChange, ...] = ()
    edge_changes: tuple[EdgeSchemaChange, ...] = ()
    node_diffs: tuple[TypeCountChange, ...] = ()
    edge_diffs: tuple[EdgeTypeCountChange, ...] = ()
    node_id_prefix_changes: tuple[MapEntryChange, ...] = ()
    node_category_id_prefix_changes: tuple[MapEntryChange, ...] = ()
    node_attribute_changes: tuple[MapEntryChange, ...] = ()
    edge_predicate_changes: tuple[MapEntryChange, ...] = ()
    edge_source_changes: tuple[MapEntryChange, ...] = ()
    edge_source_predicate_changes: tuple[MapEntryChange, ...] = ()
    edge_qualifier_changes: tuple[MapEntryChange, ...] = ()
    edge_attribute_changes: tuple[MapEntryChange, ...] = ()
    edge_detail_changes: tuple[MapEntryChange, ...] = ()
    raw: JsonObject | None = None


@dataclass(frozen=True)
class GraphComparison:
    baseline: GraphSummary
    target: GraphSummary
    total_nodes: CountDelta
    total_edges: CountDelta
    field_differences: tuple[FieldDifference, ...]
    source_changes: tuple[SourceChange, ...]
    subgraph_changes: tuple[SubgraphChange, ...]
    schema: SchemaDiffSummary


@dataclass(frozen=True)
class ComparisonResult:
    baseline: GraphSummary
    graphs: tuple[GraphSummary, ...]
    comparisons: tuple[GraphComparison, ...]


def compare(
    graphs: Sequence[ParsedGraphMetadata],
    *,
    labels: Sequence[str] | None = None,
    top_n: int = TOP_SCHEMA_DIFFS,
) -> ComparisonResult:
    """Compare selected graphs using the first graph as the baseline."""
    if len(graphs) < 2:
        msg = "At least two graphs are required for comparison"
        raise ValueError(msg)

    graph_labels = _labels(graphs, labels)
    summaries = tuple(
        _graph_summary(graph, label)
        for graph, label in zip(graphs, graph_labels, strict=True)
    )
    baseline_graph = graphs[0]
    baseline_summary = summaries[0]
    comparisons = tuple(
        _compare_pair(
            baseline_graph,
            target_graph,
            baseline=baseline_summary,
            target=target_summary,
            top_n=top_n,
        )
        for target_graph, target_summary in zip(graphs[1:], summaries[1:], strict=True)
    )
    return ComparisonResult(
        baseline=baseline_summary,
        graphs=summaries,
        comparisons=comparisons,
    )


def _compare_pair(
    old_graph: ParsedGraphMetadata,
    new_graph: ParsedGraphMetadata,
    *,
    baseline: GraphSummary,
    target: GraphSummary,
    top_n: int,
) -> GraphComparison:
    return GraphComparison(
        baseline=baseline,
        target=target,
        total_nodes=_count_delta(old_graph.total_node_count, new_graph.total_node_count),
        total_edges=_count_delta(old_graph.total_edge_count, new_graph.total_edge_count),
        field_differences=_field_differences(old_graph, new_graph),
        source_changes=_source_changes(old_graph.knowledge_sources, new_graph.knowledge_sources),
        subgraph_changes=_subgraph_changes(old_graph.subgraphs, new_graph.subgraphs),
        schema=_schema_diff_summary(old_graph.schema, new_graph.schema, top_n=top_n),
    )


def _labels(
    graphs: Sequence[ParsedGraphMetadata],
    labels: Sequence[str] | None,
) -> tuple[str, ...]:
    if labels is None:
        labels = ()
    output: list[str] = []
    for index, graph in enumerate(graphs):
        candidate = labels[index] if index < len(labels) else ""
        output.append(candidate or graph.name or f"Graph {index + 1}")
    return tuple(output)


def _graph_summary(graph: ParsedGraphMetadata, label: str) -> GraphSummary:
    return GraphSummary(
        label=label,
        name=graph.name,
        release_version=graph.release_version,
        date_created=graph.date_created,
        date_modified=graph.date_modified,
        license=graph.license,
        biolink_version=graph.biolink_version,
        babel_version=graph.babel_version,
        node_count=graph.total_node_count,
        edge_count=graph.total_edge_count,
        source_count=len(graph.knowledge_sources),
        subgraph_count=len(graph.subgraphs),
        schema_status="loaded" if graph.schema is not None else graph.schema_reference.kind,
    )


def _field_differences(
    old_graph: ParsedGraphMetadata,
    new_graph: ParsedGraphMetadata,
) -> tuple[FieldDifference, ...]:
    fields = (
        ("Graph name", "name"),
        ("Release version", "release_version"),
        ("Date created", "date_created"),
        ("Date modified", "date_modified"),
        ("License", "license"),
        ("Biolink version", "biolink_version"),
        ("Babel version", "babel_version"),
    )
    differences = []
    for label, attribute in fields:
        old_value = str(getattr(old_graph, attribute) or "")
        new_value = str(getattr(new_graph, attribute) or "")
        if old_value != new_value:
            differences.append(
                FieldDifference(
                    field=label,
                    old=old_value or "Unknown",
                    new=new_value or "Unknown",
                )
            )
    return tuple(differences)


def _source_changes(
    old_sources: Sequence[KnowledgeSource],
    new_sources: Sequence[KnowledgeSource],
) -> tuple[SourceChange, ...]:
    old_index = {_source_key(source): source for source in old_sources}
    new_index = {_source_key(source): source for source in new_sources}
    changes: list[SourceChange] = []
    for source_id in sorted(set(old_index) | set(new_index)):
        old_source = old_index.get(source_id)
        new_source = new_index.get(source_id)
        if old_source is None and new_source is not None:
            changes.append(_source_change(source_id, None, new_source, "added"))
        elif old_source is not None and new_source is None:
            changes.append(_source_change(source_id, old_source, None, "removed"))
        elif (
            old_source is not None
            and new_source is not None
            and (
                (old_source.version or "") != (new_source.version or "")
                or (old_source.license or "") != (new_source.license or "")
            )
        ):
            changes.append(_source_change(source_id, old_source, new_source, "changed"))
    return tuple(changes)


def _source_change(
    source_id: str,
    old_source: KnowledgeSource | None,
    new_source: KnowledgeSource | None,
    status: str,
) -> SourceChange:
    source = new_source or old_source
    return SourceChange(
        source_id=source_id,
        name=(source.name if source else "") or "Unknown",
        status=status,
        old_version=(old_source.version if old_source else "") or "",
        new_version=(new_source.version if new_source else "") or "",
        old_license=(old_source.license if old_source else "") or "",
        new_license=(new_source.license if new_source else "") or "",
    )


def _source_key(source: KnowledgeSource) -> str:
    return source.id or source.name or "Unknown"


def _subgraph_changes(
    old_subgraphs: Sequence[SubgraphSource],
    new_subgraphs: Sequence[SubgraphSource],
) -> tuple[SubgraphChange, ...]:
    old_index = {_subgraph_key(source): source for source in old_subgraphs}
    new_index = {_subgraph_key(source): source for source in new_subgraphs}
    changes: list[SubgraphChange] = []
    for source_id in sorted(set(old_index) | set(new_index)):
        old_source = old_index.get(source_id)
        new_source = new_index.get(source_id)
        status = _entry_status(old_source, new_source)
        node_delta = _count_delta(
            old_source.node_count if old_source else None,
            new_source.node_count if new_source else None,
        )
        edge_delta = _count_delta(
            old_source.edge_count if old_source else None,
            new_source.edge_count if new_source else None,
        )
        if status == "unchanged" and node_delta.delta == 0 and edge_delta.delta == 0:
            continue
        source = new_source or old_source
        changes.append(
            SubgraphChange(
                source_id=source_id,
                name=(source.name if source else "") or "Unknown",
                node_delta=node_delta,
                edge_delta=edge_delta,
                status=status,
            )
        )
    return tuple(
        sorted(
            changes,
            key=lambda change: max(
                abs(change.node_delta.delta or 0),
                abs(change.edge_delta.delta or 0),
            ),
            reverse=True,
        )
    )


def _subgraph_key(source: SubgraphSource) -> str:
    return source.id or source.name or "Unknown"


def _entry_status(old_entry: object | None, new_entry: object | None) -> str:
    if old_entry is None:
        return "added"
    if new_entry is None:
        return "removed"
    return "changed"


def _schema_diff_summary(
    old_schema: GraphSchema | None,
    new_schema: GraphSchema | None,
    *,
    top_n: int,
) -> SchemaDiffSummary:
    if old_schema is None or new_schema is None:
        missing = []
        if old_schema is None:
            missing.append("baseline")
        if new_schema is None:
            missing.append("comparison")
        return SchemaDiffSummary(
            available=False,
            message=f"Schema diff unavailable: missing schema for {', '.join(missing)} graph.",
        )

    try:
        raw_diff = _diff_schemas(old_schema.raw, new_schema.raw)
    except Exception as error:
        return SchemaDiffSummary(
            available=False,
            message=f"Schema diff unavailable: {error}",
        )

    diff = _mapping(raw_diff.get("diff"))
    node_diff_entries = diff.get("nodes")
    edge_diff_entries = diff.get("edges")
    nodes_summary = _mapping(diff.get("nodes_summary"))
    edges_summary = _mapping(diff.get("edges_summary"))
    return SchemaDiffSummary(
        available=True,
        message="",
        node_total=_count_delta_from_diff(nodes_summary.get("total_count")),
        edge_total=_count_delta_from_diff(edges_summary.get("total_count")),
        node_type_count=_int_mapping(nodes_summary.get("types")),
        edge_type_count=_int_mapping(edges_summary.get("types")),
        node_changes=_node_schema_changes(node_diff_entries, top_n=top_n),
        edge_changes=_edge_schema_changes(edge_diff_entries, top_n=top_n),
        node_diffs=_node_type_changes(node_diff_entries, top_n=top_n),
        edge_diffs=_edge_type_changes(edge_diff_entries, top_n=top_n),
        node_id_prefix_changes=_map_changes(nodes_summary.get("id_prefixes"), top_n=top_n),
        node_category_id_prefix_changes=_entry_map_changes(
            node_diff_entries,
            context_func=_node_entry_label,
            fields=(("id_prefixes", "ID prefix"),),
            top_n=top_n,
        ),
        node_attribute_changes=_map_changes(nodes_summary.get("attributes"), top_n=top_n),
        edge_predicate_changes=_map_changes(edges_summary.get("predicates"), top_n=top_n),
        edge_source_changes=_map_changes(
            edges_summary.get("primary_knowledge_sources"),
            top_n=top_n,
        ),
        edge_source_predicate_changes=_source_predicate_changes(
            edges_summary.get("predicates_by_knowledge_source"),
            top_n=top_n,
        ),
        edge_qualifier_changes=_map_changes(edges_summary.get("qualifiers"), top_n=top_n),
        edge_attribute_changes=_map_changes(edges_summary.get("attributes"), top_n=top_n),
        edge_detail_changes=_entry_map_changes(
            edge_diff_entries,
            context_func=_edge_entry_label,
            fields=(
                ("primary_knowledge_sources", "Primary source"),
                ("qualifiers", "Qualifier"),
                ("attributes", "Attribute"),
                ("subject_id_prefixes", "Subject prefix"),
                ("object_id_prefixes", "Object prefix"),
            ),
            top_n=top_n,
        ),
        raw=raw_diff,
    )


def _node_type_changes(value: Any, *, top_n: int) -> tuple[TypeCountChange, ...]:
    rows = []
    for entry in _sequence_of_mappings(value):
        rows.append(
            TypeCountChange(
                label=_category_label(entry.get("category") or entry.get("node_types")),
                status=str(entry.get("status") or "changed"),
                count=_count_delta_from_diff(entry.get("count")),
            )
        )
    return tuple(_top_count_changes(rows, top_n=top_n))


def _edge_type_changes(value: Any, *, top_n: int) -> tuple[EdgeTypeCountChange, ...]:
    rows = []
    for entry in _sequence_of_mappings(value):
        rows.append(
            EdgeTypeCountChange(
                subject_category=_category_label(entry.get("subject_category")),
                predicate=str(entry.get("predicate") or "unknown"),
                object_category=_category_label(entry.get("object_category")),
                status=str(entry.get("status") or "changed"),
                count=_count_delta_from_diff(entry.get("count")),
            )
        )
    return tuple(_top_count_changes(rows, top_n=top_n))


def _node_schema_changes(value: Any, *, top_n: int) -> tuple[NodeSchemaChange, ...]:
    rows = [
        NodeSchemaChange(
            label=_node_entry_label(entry),
            status=str(entry.get("status") or "changed"),
            count=_count_delta_from_diff(entry.get("count")),
            id_prefix_changes=_limited_map_changes(entry.get("id_prefixes")),
            attribute_changes=_limited_map_changes(entry.get("attributes")),
        )
        for entry in _sequence_of_mappings(value)
    ]
    return tuple(_top_schema_rows(rows, top_n=top_n))


def _edge_schema_changes(value: Any, *, top_n: int) -> tuple[EdgeSchemaChange, ...]:
    rows = [
        EdgeSchemaChange(
            subject_category=_category_label(entry.get("subject_category")),
            predicate=str(entry.get("predicate") or "unknown"),
            object_category=_category_label(entry.get("object_category")),
            status=str(entry.get("status") or "changed"),
            count=_count_delta_from_diff(entry.get("count")),
            primary_source_changes=_limited_map_changes(entry.get("primary_knowledge_sources")),
            qualifier_changes=_limited_map_changes(entry.get("qualifiers")),
            attribute_changes=_limited_map_changes(entry.get("attributes")),
            subject_id_prefix_changes=_limited_map_changes(entry.get("subject_id_prefixes")),
            object_id_prefix_changes=_limited_map_changes(entry.get("object_id_prefixes")),
        )
        for entry in _sequence_of_mappings(value)
    ]
    return tuple(_top_schema_rows(rows, top_n=top_n))


def _limited_map_changes(value: Any) -> tuple[MapEntryChange, ...]:
    return tuple(
        _top_map_changes(
            _map_change_entries(value),
            top_n=TOP_SCHEMA_ROW_MAP_DIFFS,
        )
    )


def _top_schema_rows(
    rows: Sequence[NodeSchemaChange] | Sequence[EdgeSchemaChange],
    *,
    top_n: int,
) -> Sequence[NodeSchemaChange] | Sequence[EdgeSchemaChange]:
    return sorted(rows, key=_schema_row_impact, reverse=True)[:top_n]


def _schema_row_impact(row: NodeSchemaChange | EdgeSchemaChange) -> int:
    map_changes = []
    if isinstance(row, NodeSchemaChange):
        map_changes.extend(row.id_prefix_changes)
        map_changes.extend(row.attribute_changes)
    else:
        map_changes.extend(row.primary_source_changes)
        map_changes.extend(row.qualifier_changes)
        map_changes.extend(row.attribute_changes)
        map_changes.extend(row.subject_id_prefix_changes)
        map_changes.extend(row.object_id_prefix_changes)
    return abs(row.count.delta or 0) + sum(
        abs(change.count.delta or 0) for change in map_changes
    )


def _top_count_changes(
    rows: Sequence[TypeCountChange] | Sequence[EdgeTypeCountChange],
    *,
    top_n: int,
) -> Sequence[TypeCountChange] | Sequence[EdgeTypeCountChange]:
    return sorted(rows, key=lambda row: abs(row.count.delta or 0), reverse=True)[:top_n]


def _map_changes(value: Any, *, top_n: int) -> tuple[MapEntryChange, ...]:
    return tuple(_top_map_changes(_map_change_entries(value), top_n=top_n))


def _entry_map_changes(
    entries: Any,
    *,
    context_func: Callable[[Mapping[str, Any]], str],
    fields: Sequence[tuple[str, str]],
    top_n: int,
) -> tuple[MapEntryChange, ...]:
    rows: list[MapEntryChange] = []
    for entry in _sequence_of_mappings(entries):
        context = context_func(entry)
        for field, label in fields:
            rows.extend(
                _map_change_entries(
                    entry.get(field),
                    label_prefix=f"{context} / {label}",
                )
            )
    return tuple(_top_map_changes(rows, top_n=top_n))


def _source_predicate_changes(value: Any, *, top_n: int) -> tuple[MapEntryChange, ...]:
    diff = _mapping(value)
    rows: list[MapEntryChange] = []
    for source, predicates in _mapping(diff.get("added")).items():
        rows.extend(_plain_nested_entries(str(source), predicates, status="added"))
    for source, predicates in _mapping(diff.get("removed")).items():
        rows.extend(_plain_nested_entries(str(source), predicates, status="removed"))
    for source, predicates in _mapping(diff.get("changed")).items():
        rows.extend(_map_change_entries(predicates, label_prefix=str(source)))
    return tuple(_top_map_changes(rows, top_n=top_n))


def _plain_nested_entries(
    label_prefix: str,
    value: Any,
    *,
    status: str,
) -> list[MapEntryChange]:
    values = _mapping(value)
    if not values:
        count = int_or_none(value) or 0
        return [
            MapEntryChange(
                label=label_prefix,
                status=status,
                count=_entry_count_delta(count, status=status),
            )
        ]
    return [
        MapEntryChange(
            label=_joined_label(label_prefix, str(label)),
            status=status,
            count=_entry_count_delta(int_or_none(count) or 0, status=status),
        )
        for label, count in values.items()
    ]


def _map_change_entries(value: Any, label_prefix: str = "") -> list[MapEntryChange]:
    diff = _mapping(value)
    rows: list[MapEntryChange] = []
    for label, count in _mapping(diff.get("added")).items():
        new = int_or_none(count) or 0
        rows.append(
            MapEntryChange(
                label=_joined_label(label_prefix, str(label)),
                status="added",
                count=CountDelta(old=0, new=new, delta=new, percent_change=None),
            )
        )
    for label, count in _mapping(diff.get("removed")).items():
        old = int_or_none(count) or 0
        rows.append(
            MapEntryChange(
                label=_joined_label(label_prefix, str(label)),
                status="removed",
                count=CountDelta(
                    old=old,
                    new=0,
                    delta=-old,
                    percent_change=-100.0 if old else None,
                ),
            )
        )
    for label, count_diff in _mapping(diff.get("changed")).items():
        rows.append(
            MapEntryChange(
                label=_joined_label(label_prefix, str(label)),
                status="changed",
                count=_count_delta_from_diff(count_diff),
            )
        )
    return rows


def _entry_count_delta(count: int, *, status: str) -> CountDelta:
    if status == "removed":
        return CountDelta(
            old=count,
            new=0,
            delta=-count,
            percent_change=-100.0 if count else None,
        )
    return CountDelta(old=0, new=count, delta=count, percent_change=None)


def _top_map_changes(
    rows: Sequence[MapEntryChange],
    *,
    top_n: int,
) -> list[MapEntryChange]:
    return sorted(rows, key=lambda row: abs(row.count.delta or 0), reverse=True)[:top_n]


def _joined_label(prefix: str, label: str) -> str:
    return f"{prefix} / {label}" if prefix else label


def _node_entry_label(entry: Mapping[str, Any]) -> str:
    return _category_label(entry.get("category") or entry.get("node_types"))


def _edge_entry_label(entry: Mapping[str, Any]) -> str:
    return " - ".join(
        (
            _category_label(entry.get("subject_category")),
            str(entry.get("predicate") or "unknown"),
            _category_label(entry.get("object_category")),
        )
    )


def _count_delta(old: int | None, new: int | None) -> CountDelta:
    if old is None or new is None:
        return CountDelta(old=old, new=new, delta=None, percent_change=None)
    percent_change = None if old == 0 else round(((new - old) / old) * 100, 2)
    return CountDelta(old=old, new=new, delta=new - old, percent_change=percent_change)


def _count_delta_from_diff(value: Any) -> CountDelta:
    diff = _mapping(value)
    if not diff:
        return CountDelta(old=0, new=0, delta=0, percent_change=0.0)
    return CountDelta(
        old=int_or_none(diff.get("old")) or 0,
        new=int_or_none(diff.get("new")) or 0,
        delta=int_or_none(diff.get("delta")) or 0,
        percent_change=_float_or_none(diff.get("percent_change")),
    )


def _category_label(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return ", ".join(str(item) for item in value if item is not None) or "Unknown"
    return "Unknown"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_mapping(value: Any) -> dict[str, int]:
    return {
        str(key): int(parsed)
        for key, count in _mapping(value).items()
        if (parsed := int_or_none(count)) is not None
    }


def _sequence_of_mappings(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _diff_schemas(old_document: JsonObject, new_document: JsonObject) -> JsonObject:
    diff_schemas = _orion_diff_schemas()
    return diff_schemas(old_document, new_document)


@lru_cache(maxsize=1)
def _orion_diff_schemas() -> Callable[[JsonObject, JsonObject], JsonObject]:
    try:
        from orion.kgx_schema_diff import diff_schemas
    except Exception:
        return _fallback_diff_schemas
    return diff_schemas


def _fallback_diff_schemas(old_document: JsonObject, new_document: JsonObject) -> JsonObject:
    old_schema = _schema_section(old_document, "old")
    new_schema = _schema_section(new_document, "new")
    node_diffs = _diff_node_types(old_schema.get("nodes"), new_schema.get("nodes"))
    edge_diffs = _diff_edge_types(old_schema.get("edges"), new_schema.get("edges"))
    return {
        "orion:schemaDiffFormatVersion": "fallback-1.0",
        "old": _document_reference(old_document),
        "new": _document_reference(new_document),
        "diff": {
            "nodes": [entry for entry in node_diffs if entry["status"] != "unchanged"],
            "nodes_summary": _diff_nodes_summary(
                old_schema.get("nodes_summary"),
                new_schema.get("nodes_summary"),
                node_diffs,
            ),
            "edges": [entry for entry in edge_diffs if entry["status"] != "unchanged"],
            "edges_summary": _diff_edges_summary(
                old_schema.get("edges_summary"),
                new_schema.get("edges_summary"),
                edge_diffs,
            ),
        },
    }


def _schema_section(document: JsonObject, label: str) -> JsonObject:
    if _is_schema_section(document):
        return document
    schema = document.get("schema")
    if isinstance(schema, dict) and _is_schema_section(schema):
        return schema
    if isinstance(schema, dict) and schema.get("@id"):
        msg = f"The {label} document references an external schema instead of containing it."
        raise ValueError(msg)
    msg = f"The {label} document is not a KGX schema document."
    raise ValueError(msg)


def _is_schema_section(value: Any) -> bool:
    section_keys = {"nodes", "nodes_summary", "edges", "edges_summary"}
    return isinstance(value, dict) and section_keys <= set(value)


def _document_reference(document: JsonObject) -> JsonObject:
    graph = document.get("isPartOf")
    if isinstance(graph, str):
        graph = {"@id": graph}
    if not isinstance(graph, dict):
        graph = document
    return {
        "schema": {"@id": document.get("@id", "")},
        "graph": {"@id": graph.get("@id", "")},
    }


def _diff_nodes_summary(old: Any, new: Any, node_diffs: Sequence[JsonObject]) -> JsonObject:
    old_summary = _mapping(old)
    new_summary = _mapping(new)
    return {
        "total_count": _raw_count_diff(
            old_summary.get("total_count"),
            new_summary.get("total_count"),
        ),
        "types": _type_diff_summary(node_diffs),
        "id_prefixes": _raw_map_diff(
            old_summary.get("id_prefixes"),
            new_summary.get("id_prefixes"),
        ),
        "attributes": _raw_map_diff(old_summary.get("attributes"), new_summary.get("attributes")),
    }


def _diff_edges_summary(old: Any, new: Any, edge_diffs: Sequence[JsonObject]) -> JsonObject:
    old_summary = _mapping(old)
    new_summary = _mapping(new)
    return {
        "total_count": _raw_count_diff(
            old_summary.get("total_count"),
            new_summary.get("total_count"),
        ),
        "types": _type_diff_summary(edge_diffs),
        "predicates": _raw_map_diff(old_summary.get("predicates"), new_summary.get("predicates")),
        "primary_knowledge_sources": _raw_map_diff(
            old_summary.get("primary_knowledge_sources"),
            new_summary.get("primary_knowledge_sources"),
        ),
        "predicates_by_knowledge_source": _raw_nested_map_diff(
            old_summary.get("predicates_by_knowledge_source"),
            new_summary.get("predicates_by_knowledge_source"),
        ),
        "qualifiers": _raw_map_diff(old_summary.get("qualifiers"), new_summary.get("qualifiers")),
        "attributes": _raw_map_diff(old_summary.get("attributes"), new_summary.get("attributes")),
    }


def _diff_node_types(old_nodes: Any, new_nodes: Any) -> list[JsonObject]:
    old_index = _index_entries(old_nodes, _node_type_key, ("id_prefixes", "attributes"))
    new_index = _index_entries(new_nodes, _node_type_key, ("id_prefixes", "attributes"))
    rows = []
    for key in sorted(set(old_index) | set(new_index)):
        old_entry = old_index.get(key)
        new_entry = new_index.get(key)
        old_entry_safe = old_entry or {}
        new_entry_safe = new_entry or {}
        rows.append(
            {
                "category": list(key),
                "status": _raw_entry_status(old_entry, new_entry),
                "count": _raw_count_diff(old_entry_safe.get("count"), new_entry_safe.get("count")),
                "id_prefixes": _raw_map_diff(
                    old_entry_safe.get("id_prefixes"),
                    new_entry_safe.get("id_prefixes"),
                ),
                "attributes": _raw_map_diff(
                    old_entry_safe.get("attributes"),
                    new_entry_safe.get("attributes"),
                ),
            }
        )
    return _sort_by_impact(rows)


def _diff_edge_types(old_edges: Any, new_edges: Any) -> list[JsonObject]:
    fields = (
        "primary_knowledge_sources",
        "qualifiers",
        "attributes",
        "subject_id_prefixes",
        "object_id_prefixes",
    )
    old_index = _index_entries(old_edges, _edge_type_key, fields)
    new_index = _index_entries(new_edges, _edge_type_key, fields)
    rows = []
    for key in sorted(set(old_index) | set(new_index)):
        old_entry = old_index.get(key)
        new_entry = new_index.get(key)
        old_entry_safe = old_entry or {}
        new_entry_safe = new_entry or {}
        subject_categories, predicate, object_categories = key
        rows.append(
            {
                "subject_category": list(subject_categories),
                "predicate": predicate,
                "object_category": list(object_categories),
                "status": _raw_entry_status(old_entry, new_entry),
                "count": _raw_count_diff(old_entry_safe.get("count"), new_entry_safe.get("count")),
                **{
                    field: _raw_map_diff(old_entry_safe.get(field), new_entry_safe.get(field))
                    for field in fields
                },
            }
        )
    return _sort_by_impact(rows)


def _index_entries(
    entries: Any,
    key_func: Callable[[Mapping[str, Any]], tuple[Any, ...]],
    map_fields: Sequence[str],
) -> dict[tuple[Any, ...], JsonObject]:
    indexed: dict[tuple[Any, ...], JsonObject] = {}
    for entry in _sequence_of_mappings(entries):
        key = key_func(entry)
        existing = indexed.get(key)
        if existing is None:
            indexed[key] = {
                "count": int_or_none(entry.get("count")) or 0,
                **{field: _int_mapping(entry.get(field)) for field in map_fields},
            }
            continue
        existing["count"] += int_or_none(entry.get("count")) or 0
        for field in map_fields:
            for map_key, value in _int_mapping(entry.get(field)).items():
                existing[field][map_key] = existing[field].get(map_key, 0) + value
    return indexed


def _node_type_key(entry: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(_category_values(entry.get("category") or entry.get("node_types"))))


def _edge_type_key(entry: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(sorted(_category_values(entry.get("subject_category")))),
        entry.get("predicate"),
        tuple(sorted(_category_values(entry.get("object_category")))),
    )


def _category_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if item is not None)
    return ()


def _raw_entry_status(old_entry: object | None, new_entry: object | None) -> str:
    if old_entry is None:
        return "added"
    if new_entry is None:
        return "removed"
    return "unchanged" if old_entry == new_entry else "changed"


def _raw_count_diff(old: Any, new: Any) -> JsonObject:
    old_count = int_or_none(old) or 0
    new_count = int_or_none(new) or 0
    return {
        "old": old_count,
        "new": new_count,
        "delta": new_count - old_count,
        "percent_change": None
        if old_count == 0
        else round(((new_count - old_count) / old_count) * 100, 2),
    }


def _raw_map_diff(old: Any, new: Any) -> JsonObject:
    old_map = _int_mapping(old)
    new_map = _int_mapping(new)
    return {
        "added": _sort_count_map(
            {key: value for key, value in new_map.items() if key not in old_map}
        ),
        "removed": _sort_count_map(
            {key: value for key, value in old_map.items() if key not in new_map}
        ),
        "changed": {
            key: _raw_count_diff(old_map[key], value)
            for key, value in sorted(
                (
                    (key, value)
                    for key, value in new_map.items()
                    if key in old_map and old_map[key] != value
                ),
                key=lambda item: -abs(item[1] - old_map[item[0]]),
            )
        },
    }


def _raw_nested_map_diff(old: Any, new: Any) -> JsonObject:
    old_map = _mapping(old)
    new_map = _mapping(new)
    return {
        "added": {
            str(key): _sort_count_map(_int_mapping(value))
            for key, value in new_map.items()
            if key not in old_map
        },
        "removed": {
            str(key): _sort_count_map(_int_mapping(value))
            for key, value in old_map.items()
            if key not in new_map
        },
        "changed": {
            str(key): _raw_map_diff(old_map[key], value)
            for key, value in new_map.items()
            if key in old_map and old_map[key] != value
        },
    }


def _sort_count_map(values: Mapping[str, int]) -> dict[str, int]:
    return dict(sorted(values.items(), key=lambda item: item[1], reverse=True))


def _sort_by_impact(rows: Sequence[JsonObject]) -> list[JsonObject]:
    return sorted(rows, key=lambda row: -abs(_mapping(row.get("count")).get("delta", 0)))


def _type_diff_summary(entries: Sequence[JsonObject]) -> dict[str, int]:
    tally = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for entry in entries:
        status = str(entry.get("status") or "unchanged")
        tally[status] = tally.get(status, 0) + 1
    return {
        "old": tally["removed"] + tally["changed"] + tally["unchanged"],
        "new": tally["added"] + tally["changed"] + tally["unchanged"],
        **tally,
    }
