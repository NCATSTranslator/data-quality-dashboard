from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from dash import dash_table, html

from graph_metadata_dashboard.diff import (
    CountDelta,
    EdgeSchemaChange,
    GraphComparison,
    GraphSummary,
    MapEntryChange,
    NodeSchemaChange,
    SchemaDiffSummary,
    SourceChange,
    SubgraphChange,
    compare,
)
from graph_metadata_dashboard.parsers.models import ParsedGraphMetadata

HEATMAP_ROW_LIMIT = 20


@dataclass(frozen=True)
class _HeatmapCell:
    count: CountDelta
    status: str
    detail: str = ""


@dataclass(frozen=True)
class _HeatmapRow:
    key: str
    group: str
    label: str
    cells: tuple[_HeatmapCell | None, ...]
    impact: float


@dataclass(frozen=True)
class _HeatmapScale:
    absolute: float


def comparison_dashboard(
    parsed_graphs: list[ParsedGraphMetadata],
    labels: list[str],
    load_errors: list[str],
) -> html.Div:
    if len(parsed_graphs) < 2:
        return html.Div(
            className="content-card comparison-dashboard",
            children=[
                html.P("Graph Comparison", className="eyebrow"),
                html.H2("Graph comparison unavailable"),
                html.P(
                    "At least two cached graph metadata documents are required for comparison.",
                    className="status-line",
                ),
                _message_list(load_errors),
            ],
        )

    result = compare(parsed_graphs, labels=labels)
    return html.Div(
        className="content-card comparison-dashboard",
        children=[
            html.P("Graph Comparison", className="eyebrow"),
            html.P(
                f"Using {result.baseline.label} as the baseline and comparing each "
                "other loaded graph against it. Change the baseline from the "
                "dropdown box above if needed.",
                className="status-line",
            ),
            _message_list(load_errors),
            _n_way_overview(result.comparisons),
            _comparison_heatmap(result.comparisons),
            *[
                _comparison_pair_section(
                    pair,
                    collapsed=len(result.comparisons) > 1,
                    open_by_default=index == 0,
                )
                for index, pair in enumerate(result.comparisons)
            ],
        ],
    )


def _n_way_overview(comparisons: tuple[GraphComparison, ...]) -> html.Div:
    if not comparisons:
        return html.Div()
    rows = [
        html.Tr(
            children=[
                html.Th("Graph"),
                html.Th("Release"),
                html.Th("Nodes"),
                html.Th("Edges"),
                html.Th("Sources"),
                html.Th("Subgraphs"),
                html.Th("Types"),
            ]
        ),
        html.Tr(
            children=[
                html.Td(comparisons[0].baseline.label),
                html.Td(_baseline_cell(comparisons[0].baseline.release_version or "Unknown")),
                html.Td(_baseline_cell(_format_count(comparisons[0].baseline.node_count))),
                html.Td(_baseline_cell(_format_count(comparisons[0].baseline.edge_count))),
                html.Td(_baseline_cell(_format_count(comparisons[0].baseline.source_count))),
                html.Td(_baseline_cell(_format_count(comparisons[0].baseline.subgraph_count))),
                html.Td(_baseline_schema_type_overview_cell(comparisons)),
            ]
        ),
    ]
    max_subgraph_changes = max((len(pair.subgraph_changes) for pair in comparisons), default=0)

    for index, pair in enumerate(comparisons, start=1):
        rows.append(
            html.Tr(
                children=[
                    html.Td(pair.target.label),
                    html.Td(_metadata_release_cell(pair)),
                    html.Td(
                        _metric_delta_cell(
                            _format_count(pair.target.node_count),
                            pair.total_nodes,
                        )
                    ),
                    html.Td(
                        _metric_delta_cell(
                            _format_count(pair.target.edge_count),
                            pair.total_edges,
                        )
                    ),
                    html.Td(
                        _source_change_cell(
                            pair,
                            index=index,
                        )
                    ),
                    html.Td(
                        _change_count_cell(
                            _format_count(pair.target.subgraph_count),
                            len(pair.subgraph_changes),
                            max_count=max_subgraph_changes,
                        )
                    ),
                    html.Td(
                        _schema_type_overview_cell(
                            pair.schema,
                        )
                    ),
                ]
            )
        )

    return html.Div(
        className="comparison-section",
        children=[
            html.H4("Comparison Overview"),
            html.Table(className="comparison-overview-table", children=rows),
        ],
    )


def _comparison_heatmap(comparisons: tuple[GraphComparison, ...]) -> html.Div | str:
    rows = _heatmap_rows(comparisons)
    if not rows:
        return ""
    scale = _heatmap_scale(rows)
    return html.Div(
        className="comparison-section comparison-heatmap-section",
        children=[
            html.H4("Top Change Heatmap"),
            html.P(
                "Largest cross-cutting changes across graph totals, source metadata, "
                "node categories, edge triples, and schema rollups. Cell color uses one "
                "sequential scale for normalized changes across all rows. Rows are capped "
                f"at {HEATMAP_ROW_LIMIT}.",
                className="comparison-table-note",
            ),
            _heatmap_legend(),
            html.Div(
                className="comparison-heatmap-wrap",
                children=[
                    html.Table(
                        className="comparison-heatmap-table",
                        children=[
                            html.Thead(
                                html.Tr(
                                    [
                                        html.Th("Type"),
                                        html.Th("Attribute"),
                                        *[
                                            html.Th(
                                                f"{_graph_title(pair.baseline)} -> "
                                                f"{_graph_title(pair.target)}"
                                            )
                                            for pair in comparisons
                                        ],
                                    ]
                                )
                            ),
                            html.Tbody(
                                [
                                    html.Tr(
                                        [
                                            html.Th(
                                                row.group,
                                                className="heatmap-row-group-cell",
                                            ),
                                            html.Th(
                                                row.label,
                                                className="heatmap-row-label-cell",
                                            ),
                                            *[
                                                _heatmap_cell(
                                                    cell,
                                                    scale=scale,
                                                )
                                                for cell in row.cells
                                            ],
                                        ]
                                    )
                                    for row in rows
                                ]
                            ),
                        ],
                    )
                ],
            ),
        ],
    )


def _heatmap_rows(comparisons: tuple[GraphComparison, ...]) -> tuple[_HeatmapRow, ...]:
    drafts: dict[str, tuple[str, str, list[_HeatmapCell | None]]] = {}
    for index, pair in enumerate(comparisons):
        for key, group, label, cell in _heatmap_pair_cells(pair):
            _, _, cells = drafts.setdefault(
                key,
                (group, label, [None for _ in comparisons]),
            )
            cells[index] = cell
    rows = tuple(
        _HeatmapRow(
            key=key,
            group=group,
            label=label,
            cells=tuple(cells),
            impact=0.0,
        )
        for key, (group, label, cells) in drafts.items()
    )
    scale = _heatmap_scale(rows)
    scored_rows = tuple(
        _HeatmapRow(
            key=row.key,
            group=row.group,
            label=row.label,
            cells=row.cells,
            impact=sum(
                _heatmap_cell_visual_ratio(
                    cell,
                    scale=scale,
                )
                for cell in row.cells
                if cell
            ),
        )
        for row in rows
    )
    return _rank_heatmap_rows(
        scored_rows,
        scale=scale,
        comparison_count=len(comparisons),
    )


def _rank_heatmap_rows(
    rows: tuple[_HeatmapRow, ...],
    *,
    scale: _HeatmapScale,
    comparison_count: int,
) -> tuple[_HeatmapRow, ...]:
    if not rows:
        return ()
    if comparison_count > 1:
        return _rank_heatmap_rows_global_first(
            rows,
            scale=scale,
            comparison_count=comparison_count,
        )
    return _rank_heatmap_rows_pair_balanced(
        rows,
        scale=scale,
        comparison_count=comparison_count,
    )


def _rank_heatmap_rows_pair_balanced(
    rows: tuple[_HeatmapRow, ...],
    *,
    scale: _HeatmapScale,
    comparison_count: int,
) -> tuple[_HeatmapRow, ...]:
    selected: dict[str, _HeatmapRow] = {}
    per_comparison_quota = max(1, HEATMAP_ROW_LIMIT // max(1, comparison_count))
    for index in range(comparison_count):
        candidates = sorted(
            (row for row in rows if index < len(row.cells) and row.cells[index] is not None),
            key=lambda row: (
                -_heatmap_cell_visual_ratio(row.cells[index], scale=scale),
                -_heatmap_cell_absolute_impact(row.cells[index]),
                row.group,
                row.label,
            ),
        )
        for row in candidates[:per_comparison_quota]:
            selected[row.key] = row
    for row in _sort_heatmap_rows(rows):
        if len(selected) >= HEATMAP_ROW_LIMIT:
            break
        selected.setdefault(row.key, row)
    return _sort_heatmap_rows(tuple(selected.values()))[:HEATMAP_ROW_LIMIT]


def _rank_heatmap_rows_global_first(
    rows: tuple[_HeatmapRow, ...],
    *,
    scale: _HeatmapScale,
    comparison_count: int,
) -> tuple[_HeatmapRow, ...]:
    selected: dict[str, _HeatmapRow] = {}
    global_rows = tuple(row for row in rows if _heatmap_row_coverage(row) > 1)
    for row in sorted(global_rows, key=_heatmap_global_sort_key):
        if len(selected) >= HEATMAP_ROW_LIMIT:
            break
        selected[row.key] = row
    if len(selected) >= HEATMAP_ROW_LIMIT:
        return tuple(selected.values())[:HEATMAP_ROW_LIMIT]

    per_column_candidates = [
        sorted(
            (
                row
                for row in rows
                if row.key not in selected
                and index < len(row.cells)
                and row.cells[index] is not None
            ),
            key=lambda row: (
                -_heatmap_cell_visual_ratio(row.cells[index], scale=scale),
                -_heatmap_cell_absolute_impact(row.cells[index]),
                row.group,
                row.label,
            ),
        )
        for index in range(comparison_count)
    ]
    positions = [0 for _ in range(comparison_count)]
    while len(selected) < HEATMAP_ROW_LIMIT:
        added = False
        for index, candidates in enumerate(per_column_candidates):
            while positions[index] < len(candidates):
                row = candidates[positions[index]]
                positions[index] += 1
                if row.key in selected:
                    continue
                selected[row.key] = row
                added = True
                break
            if len(selected) >= HEATMAP_ROW_LIMIT:
                break
        if not added:
            break
    return tuple(selected.values())[:HEATMAP_ROW_LIMIT]


def _sort_heatmap_rows(rows: tuple[_HeatmapRow, ...]) -> tuple[_HeatmapRow, ...]:
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                -row.impact,
                -_heatmap_row_magnitude_impact(row),
                row.group,
                row.label,
            ),
        )
    )


def _heatmap_global_sort_key(row: _HeatmapRow) -> tuple[int, float, float, str, str]:
    return (
        -_heatmap_row_coverage(row),
        -row.impact,
        -_heatmap_row_magnitude_impact(row),
        row.group,
        row.label,
    )


def _heatmap_row_coverage(row: _HeatmapRow) -> int:
    return sum(1 for cell in row.cells if cell is not None)


def _heatmap_pair_cells(
    pair: GraphComparison,
) -> Iterable[tuple[str, str, str, _HeatmapCell]]:
    yield from _heatmap_count_candidate(
        "graph:total_nodes",
        "Graph totals",
        "Total nodes",
        pair.total_nodes,
    )
    yield from _heatmap_count_candidate(
        "graph:total_edges",
        "Graph totals",
        "Total edges",
        pair.total_edges,
    )
    yield from _heatmap_metadata_candidate(
        "metadata:graph_fields",
        "Graph metadata",
        "Graph fields",
        len(pair.field_differences),
    )
    yield from _heatmap_metadata_candidate(
        "metadata:sources",
        "Graph metadata",
        "Underlying sources",
        len(pair.source_changes),
    )
    yield from _heatmap_metadata_candidate(
        "metadata:subgraphs",
        "Graph metadata",
        "Subgraph sources",
        len(pair.subgraph_changes),
    )
    if pair.schema.available:
        for change in pair.schema.node_changes:
            yield from _heatmap_count_candidate(
                f"node:{change.label}",
                "Node categories",
                change.label,
                change.count,
                status=change.status,
            )
        for change in pair.schema.edge_changes:
            label = _edge_schema_change_label(change)
            yield from _heatmap_count_candidate(
                f"edge:{label}",
                "Edge triples",
                label,
                change.count,
                status=change.status,
            )
        yield from _heatmap_map_candidates(
            "node-prefix",
            "Node ID prefixes",
            pair.schema.node_id_prefix_changes,
        )
        yield from _heatmap_map_candidates(
            "node-attribute",
            "Node attributes",
            pair.schema.node_attribute_changes,
        )
        yield from _heatmap_map_candidates(
            "edge-predicate",
            "Edge predicates",
            pair.schema.edge_predicate_changes,
        )
        yield from _heatmap_map_candidates(
            "edge-source",
            "Edge primary sources",
            pair.schema.edge_source_changes,
        )
        yield from _heatmap_map_candidates(
            "edge-source-predicate",
            "Edge source-predicate",
            pair.schema.edge_source_predicate_changes,
        )
        yield from _heatmap_map_candidates(
            "edge-qualifier",
            "Edge qualifiers",
            pair.schema.edge_qualifier_changes,
        )
        yield from _heatmap_map_candidates(
            "edge-attribute",
            "Edge attributes",
            pair.schema.edge_attribute_changes,
        )


def _heatmap_count_candidate(
    key: str,
    group: str,
    label: str,
    count: CountDelta | None,
    *,
    status: str = "changed",
) -> Iterable[tuple[str, str, str, _HeatmapCell]]:
    if count is None or not count.delta:
        return
    yield key, group, label, _HeatmapCell(count=count, status=status)


def _heatmap_metadata_candidate(
    key: str,
    group: str,
    label: str,
    count: int,
) -> Iterable[tuple[str, str, str, _HeatmapCell]]:
    if not count:
        return
    yield key, group, label, _HeatmapCell(
        count=CountDelta(old=0, new=count, delta=count, percent_change=None),
        status="metadata",
        detail=f"{count:,} changed",
    )


def _heatmap_map_candidates(
    key_prefix: str,
    group: str,
    changes: tuple[MapEntryChange, ...],
) -> Iterable[tuple[str, str, str, _HeatmapCell]]:
    for change in changes:
        yield from _heatmap_count_candidate(
            f"{key_prefix}:{change.label}",
            group,
            change.label,
            change.count,
            status=change.status,
        )


def _heatmap_scale(rows: tuple[_HeatmapRow, ...]) -> _HeatmapScale:
    absolute = max(
        (_heatmap_cell_absolute_impact(cell) for row in rows for cell in row.cells if cell),
        default=0.0,
    )
    return _HeatmapScale(absolute=absolute)


def _heatmap_legend() -> html.Div:
    return html.Div(
        className="heatmap-legend",
        children=[
            html.Div(
                className="heatmap-gradient-legend",
                children=[
                    html.Span("Normalized changes", className="heatmap-legend-heading"),
                    html.Div(
                        className="heatmap-gradient-wrap",
                        children=[
                            html.Div(className="heatmap-gradient-bar"),
                            html.Div(
                                className="heatmap-gradient-ticks",
                                children=[
                                    html.Span("0"),
                                    html.Span("0.5"),
                                    html.Span("1.0"),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="heatmap-direction-legend",
                children=[
                    html.Span(
                        className="heatmap-direction-item heatmap-direction-positive",
                        children=[
                            html.Span(className="heatmap-direction-mark"),
                            html.Span("Blue stripe: increase"),
                        ],
                    ),
                    html.Span(
                        className="heatmap-direction-item heatmap-direction-negative",
                        children=[
                            html.Span(className="heatmap-direction-mark"),
                            html.Span("Red stripe: decrease"),
                        ],
                    ),
                ],
            ),
        ],
    )


def _heatmap_cell(
    cell: _HeatmapCell | None,
    *,
    scale: _HeatmapScale,
) -> html.Td:
    if cell is None:
        return html.Td(className="heatmap-cell heatmap-cell-empty", children="")
    tooltip = (
        cell.detail
        if cell.status == "metadata"
        else _schema_delta_tooltip(cell.count, status=cell.status)
    )
    children: list[object] = [
        html.Strong(_heatmap_cell_value(cell)),
    ]
    if (percent := _heatmap_cell_percent_text(cell)) is not None:
        children.append(
            html.Span(
                percent,
                className="heatmap-percent",
                title=tooltip,
            )
        )
    if cell.status in {"added", "removed", "metadata"}:
        children.append(
            html.Span(
                "changed" if cell.status == "metadata" else cell.status,
                className=f"heatmap-status heatmap-status-{cell.status}",
            )
        )
    return html.Td(
        className=(
            "heatmap-cell "
            f"heatmap-cell-{_heatmap_cell_direction(cell)}"
        ),
        title=tooltip,
        style=_heatmap_cell_style(
            cell,
            scale=scale,
        ),
        children=children,
    )


def _heatmap_cell_value(cell: _HeatmapCell) -> str:
    if cell.status == "metadata":
        return _format_count(cell.count.new)
    if cell.status == "changed":
        return _format_delta(
            CountDelta(
                old=cell.count.old,
                new=cell.count.new,
                delta=cell.count.delta,
                percent_change=None,
            )
        )
    return _format_schema_delta(cell.count, status=cell.status)


def _heatmap_cell_percent_text(cell: _HeatmapCell) -> str | None:
    if cell.status != "changed" or cell.count.percent_change is None:
        return None
    sign = "+" if cell.count.percent_change > 0 else ""
    return f"{sign}{cell.count.percent_change:,.2f}%"


def _heatmap_cell_direction(cell: _HeatmapCell) -> str:
    if cell.status == "metadata":
        return "metadata"
    if cell.status == "removed" or (cell.count.delta is not None and cell.count.delta < 0):
        return "negative"
    if cell.status == "added" or (cell.count.delta is not None and cell.count.delta > 0):
        return "positive"
    return "neutral"


def _heatmap_cell_style(
    cell: _HeatmapCell,
    *,
    scale: _HeatmapScale,
) -> dict[str, str]:
    ratio = _heatmap_cell_visual_ratio(
        cell,
        scale=scale,
    )
    if ratio <= 0:
        return {}
    return {"background": _heatmap_fill_color(ratio)}


def _heatmap_cell_visual_ratio(
    cell: _HeatmapCell,
    *,
    scale: _HeatmapScale,
) -> float:
    if scale.absolute <= 0:
        return 0.0
    relative = _heatmap_cell_relative_impact(cell)
    absolute_ratio = _heatmap_cell_absolute_impact(cell) / scale.absolute
    return min(1.0, relative * math.sqrt(absolute_ratio))


def _heatmap_cell_percent_impact(cell: _HeatmapCell) -> float | None:
    if cell.status == "changed" and cell.count.percent_change is not None:
        return abs(cell.count.percent_change)
    return None


def _heatmap_cell_relative_impact(cell: _HeatmapCell) -> float:
    delta = abs(cell.count.delta or 0)
    denominator = max(abs(cell.count.old or 0), abs(cell.count.new or 0), delta)
    if denominator > 0:
        return min(1.0, delta / denominator)
    percent_impact = _heatmap_cell_percent_impact(cell)
    if percent_impact is not None:
        return min(1.0, percent_impact / 100)
    return 0.0


def _heatmap_cell_absolute_impact(cell: _HeatmapCell) -> float:
    value = abs(cell.count.delta or 0)
    if value <= 0:
        value = cell.count.new or cell.count.old or 0
    return float(value) if value > 0 else 0.0


def _heatmap_row_magnitude_impact(row: _HeatmapRow) -> float:
    return sum(_heatmap_cell_absolute_impact(cell) for cell in row.cells if cell)


def _heatmap_fill_color(ratio: float) -> str:
    stops = (
        (0.0, (229, 245, 249)),
        (0.5, (153, 216, 201)),
        (1.0, (44, 162, 95)),
    )
    bounded = max(0.0, min(1.0, ratio))
    for (left_position, left_color), (right_position, right_color) in zip(
        stops,
        stops[1:],
        strict=True,
    ):
        if bounded <= right_position:
            span = right_position - left_position
            weight = (bounded - left_position) / span if span else 0.0
            rgb = tuple(
                round(left + ((right - left) * weight))
                for left, right in zip(left_color, right_color, strict=True)
            )
            return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
    red, green, blue = stops[-1][1]
    return f"rgb({red}, {green}, {blue})"


def _comparison_pair_section(
    pair: GraphComparison,
    *,
    collapsed: bool,
    open_by_default: bool,
) -> html.Div:
    title = (
        f"Schema-Level Differences: {_graph_title(pair.baseline)} "
        f"-> {_graph_title(pair.target)}"
    )
    contents = []
    if pair.subgraph_changes:
        contents.append(_subgraph_changes_table(pair.subgraph_changes))
    contents.append(_schema_diff_section(pair))
    if collapsed:
        return html.Details(
            className="comparison-pair-card comparison-pair-details",
            open=open_by_default,
            children=[
                html.Summary(title),
                *contents,
            ],
        )
    return html.Div(
        className="comparison-pair-card",
        children=[
            html.H3(title),
            *contents,
        ],
    )


def _graph_title(graph: GraphSummary) -> str:
    if graph.release_version and graph.release_version not in graph.label:
        return f"{graph.label} ({graph.release_version})"
    return graph.label


def _source_changes_table(
    changes: tuple[SourceChange, ...],
    *,
    heading_level: int = 4,
    baseline_label: str = "Baseline",
    comparison_label: str = "Comparison",
) -> html.Div:
    rows = [
        {
            "id": change.source_id,
            "name": change.name,
            "changed_fields": ", ".join(change.changed_fields),
            "old_values": change.old_values,
            "new_values": change.new_values,
        }
        for change in changes
    ]
    return _table_section(
        "Underlying Data Source Changes",
        rows,
        columns=[
            {"name": "ID", "id": "id"},
            {"name": "Name", "id": "name"},
            {"name": "Changed Fields", "id": "changed_fields"},
            {"name": f"{baseline_label} Values", "id": "old_values"},
            {"name": f"{comparison_label} Values", "id": "new_values"},
        ],
        empty_message="No source additions, removals, or source metadata changes found.",
        heading_level=heading_level,
        style_data_conditional=[
            {"if": {"column_id": "old_values"}, "whiteSpace": "pre-line"},
            {"if": {"column_id": "new_values"}, "whiteSpace": "pre-line"},
        ],
    )


def _subgraph_changes_table(changes: tuple[SubgraphChange, ...]) -> html.Div:
    displayed_changes = changes[:25]
    show_changed_fields = any(change.status == "changed" for change in displayed_changes)
    rows = [
        {
            "status": change.status,
            "id": change.source_id,
            "name": change.name,
            **(
                {"changed_fields": ", ".join(change.changed_fields)}
                if show_changed_fields
                else {}
            ),
            "old_values": change.old_values,
            "new_values": change.new_values,
        }
        for change in displayed_changes
    ]
    columns = [
        {"name": "Status", "id": "status"},
        {"name": "ID", "id": "id"},
        {"name": "Name", "id": "name"},
        {"name": "Baseline Metadata", "id": "old_values"},
        {"name": "Comparison Metadata", "id": "new_values"},
    ]
    if show_changed_fields:
        columns.insert(3, {"name": "Changed Fields", "id": "changed_fields"})
    return _table_section(
        "Subgraph Source Changes",
        rows,
        columns=columns,
        empty_message="No subgraph additions, removals, or metadata changes found.",
        style_data_conditional=[
            {"if": {"column_id": "old_values"}, "whiteSpace": "pre-line"},
            {"if": {"column_id": "new_values"}, "whiteSpace": "pre-line"},
        ],
    )


def _schema_diff_section(pair: GraphComparison) -> html.Div:
    schema = pair.schema
    if not schema.available:
        return html.Div(
            className="comparison-section empty-inline",
            children=[
                html.P(schema.message),
            ],
        )

    children: list[object] = [
        html.P(
            f"Schema differences of {_graph_title(pair.target)}"
            f" relative to the {_graph_title(pair.baseline)}"
            " baseline, including changes in overall node and "
            "edge composition summaries, node categories, and edge triples.",
            className="status-line",
        ),
    ]
    children.extend(
        [
            _schema_summary_table(schema),
            _schema_entry_tables(schema),
        ]
    )
    return html.Div(
        className="comparison-section schema-diff-section",
        children=children,
    )


def _schema_entry_tables(schema: SchemaDiffSummary) -> html.Div:
    sections = [
        _node_schema_table(schema.node_changes),
        _edge_schema_table(schema.edge_changes),
    ]
    sections = [section for section in sections if section is not None]
    if not sections:
        return html.Div(
            className="empty-inline",
            children=[html.P("No row-level node category or edge triple schema changes found.")],
        )
    return html.Div(className="schema-entry-grid", children=sections)


def _schema_summary_table(schema: SchemaDiffSummary) -> html.Div:
    card_specs = [
        (
            _schema_type_weight(schema.node_type_count),
            _schema_summary_card("Node type", _schema_type_cell(schema.node_type_count)),
        ),
        (
            _schema_type_weight(schema.edge_type_count),
            _schema_summary_card("Edge type", _schema_type_cell(schema.edge_type_count)),
        ),
        (
            len(schema.node_id_prefix_changes),
            _schema_summary_card(
                "Node ID prefixes",
                _schema_map_cell(schema.node_id_prefix_changes),
            ),
        ),
        (
            len(schema.node_attribute_changes),
            _schema_summary_card(
                "Node attributes",
                _schema_map_cell(schema.node_attribute_changes),
            ),
        ),
        (
            len(schema.edge_predicate_changes),
            _schema_summary_card(
                "Edge predicates",
                _schema_map_cell(schema.edge_predicate_changes),
            ),
        ),
        (
            len(schema.edge_source_changes),
            _schema_summary_card(
                "Edge primary sources",
                _schema_map_cell(schema.edge_source_changes),
            ),
        ),
        (
            len(schema.edge_source_predicate_changes),
            _schema_summary_card(
                "Edge source-predicate composition",
                _schema_map_cell(schema.edge_source_predicate_changes),
            ),
        ),
        (
            len(schema.edge_qualifier_changes),
            _schema_summary_card(
                "Edge qualifiers",
                _schema_map_cell(schema.edge_qualifier_changes),
            ),
        ),
        (
            len(schema.edge_attribute_changes),
            _schema_summary_card(
                "Edge attributes",
                _schema_map_cell(schema.edge_attribute_changes),
            ),
        ),
    ]
    weighted_cards = sorted(
        (item for item in card_specs if item[1] is not None),
        key=lambda item: item[0],
        reverse=True,
    )
    if not weighted_cards:
        return html.Div(
            className="comparison-section empty-inline",
            children=[
                html.H5("Overall Schema Summary"),
                html.P("No aggregate schema summary changes found."),
            ],
        )
    columns: list[list[html.Div]] = [[], [], []]
    column_weights = [0, 0, 0]
    for weight, card in weighted_cards:
        column_index = min(range(len(columns)), key=lambda index: column_weights[index])
        columns[column_index].append(card)
        column_weights[column_index] += max(weight, 1)
    card_columns = [
        html.Div(className="schema-summary-card-column", children=column)
        for column in columns
        if column
    ]
    return html.Div(
        className="schema-entry-section schema-summary",
        children=[
            html.Details(
                className="schema-table-panel",
                children=[
                    html.Summary("Overall Node and Edge Composition Summary Changes"),
                    html.P(
                        "Within each category, items are sorted by change magnitude "
                        "in descending order.",
                        className="comparison-table-note",
                    ),
                    html.Div(className="schema-summary-card-grid", children=card_columns),
                ],
            ),
        ],
    )


def _schema_summary_card(
    title: str,
    content: object | None,
) -> html.Div | None:
    if content is None:
        return None
    return html.Div(
        className="schema-summary-card",
        children=[
            html.H5(title),
            content,
        ],
    )


def _schema_type_weight(type_count: dict[str, int] | None) -> int:
    if not type_count:
        return 0
    return sum(
        1
        for key in ("added", "removed", "changed", "unchanged")
        if type_count.get(key, 0)
    )


def _node_schema_table(changes: tuple[NodeSchemaChange, ...]) -> html.Div | None:
    if not changes:
        return None
    max_count_delta = _max_count_delta(change.count for change in changes)
    return html.Div(
        className="schema-entry-section",
        children=[
            html.Details(
                className="schema-table-panel",
                children=[
                    html.Summary("Node Category Changes"),
                    html.P(
                        "Rows are sorted by the combined magnitude of changes in "
                        "node-count, ID-prefix, and attributes in descending order.",
                        className="comparison-table-note",
                    ),
                    _schema_rich_table(
                        class_name="schema-node-table",
                        headers=("Node category", "Node count", "ID prefixes", "Attributes"),
                        rows=[
                            (
                                html.Strong(change.label),
                                _schema_count_cell(
                                    change.count,
                                    max_delta=max_count_delta,
                                    status=change.status,
                                ),
                                _schema_map_cell(change.id_prefix_changes),
                                _schema_map_cell(change.attribute_changes),
                            )
                            for change in changes
                        ],
                    ),
                ],
            ),
        ],
    )


def _edge_schema_table(changes: tuple[EdgeSchemaChange, ...]) -> html.Div | None:
    if not changes:
        return None
    max_count_delta = _max_count_delta(change.count for change in changes)
    return html.Div(
        className="schema-entry-section",
        children=[
            html.Details(
                className="schema-table-panel",
                children=[
                    html.Summary("Edge Triple Changes"),
                    html.P(
                        "Rows are sorted by the combined magnitude of changes in edge-count, "
                        "source, qualifier, attribute, and ID-prefix in descending order.",
                        className="comparison-table-note",
                    ),
                    _schema_rich_table(
                        class_name="schema-edge-table",
                        headers=(
                            "Edge triple",
                            "Edge count",
                            "Primary sources",
                            "Qualifiers",
                            "Attributes",
                            "Subject prefixes",
                            "Object prefixes",
                        ),
                        rows=[
                            (
                                html.Strong(_edge_schema_change_label(change)),
                                _schema_count_cell(
                                    change.count,
                                    max_delta=max_count_delta,
                                    status=change.status,
                                ),
                                _schema_map_cell(change.primary_source_changes),
                                _schema_map_cell(change.qualifier_changes),
                                _schema_map_cell(change.attribute_changes),
                                _schema_map_cell(change.subject_id_prefix_changes),
                                _schema_map_cell(change.object_id_prefix_changes),
                            )
                            for change in changes
                        ],
                    ),
                ],
            ),
        ],
    )


def _schema_rich_table(
    *,
    headers: tuple[str, ...],
    rows: list[tuple[object, ...]],
    class_name: str = "",
) -> html.Div:
    return html.Div(
        className="schema-rich-table-wrap",
        children=[
            html.Table(
                className=f"schema-rich-table {class_name}".strip(),
                children=[
                    html.Thead(html.Tr([html.Th(header) for header in headers])),
                    html.Tbody(
                        [html.Tr([html.Td(cell) for cell in row]) for row in rows]
                    ),
                ],
            )
        ],
    )
def _schema_type_cell(input: dict[str, int] | None) -> html.Div | None:
    if not input:
        return None
    labels = (
        ("added", "Added"),
        ("removed", "Removed"),
        ("changed", "Changed"),
        ("unchanged", "Unchanged"),
    )
    values = [(label, input.get(key, 0)) for key, label in labels if input.get(key, 0)]
    if not values:
        return None
    return html.Div(
        className="schema-type-cell",
        children=[
            html.Div(
                className=f"schema-type-item schema-type-{label.lower()}",
                children=[
                    html.Strong(f"{value:,}"),
                    html.Span(label),
                ],
            )
            for label, value in values
        ],
    )

def _schema_count_cell(
    delta: CountDelta,
    *,
    max_delta: int,
    status: str = "changed",
) -> html.Div:
    tooltip = _schema_delta_tooltip(delta, status=status)
    children: list[object] = [
        html.Strong(_format_schema_delta(delta, status=status), title=tooltip)
    ]
    if delta.delta:
        children.insert(0, _delta_bar(delta.delta, max_value=max_delta, title=tooltip))
        children.append(
            html.Span(
                f"{_format_count(delta.old)} -> {_format_count(delta.new)}",
                className="schema-map-summary",
                title=tooltip,
            )
        )
    else:
        children.append(html.Span("No count change", className="schema-map-summary"))
    return html.Div(className="schema-count-cell", children=children)


def _schema_map_cell(
    changes: tuple[MapEntryChange, ...],
) -> html.Div:
    if not changes:
        return html.Div(className="schema-map-cell muted-cell", children="No changes")
    max_delta = _max_count_delta(change.count for change in changes)
    children: list[object] = [
        _schema_map_group(status, grouped_changes, max_delta=max_delta)
        for status, grouped_changes in _group_map_changes(changes)
    ]
    return html.Div(
        className="schema-map-cell",
        children=children,
    )


def _schema_map_group(
    status: str,
    changes: tuple[MapEntryChange, ...],
    *,
    max_delta: int,
) -> html.Div:
    rows = []
    for change in changes:
        tooltip = _schema_delta_tooltip(change.count, status=change.status)
        rows.append(
            html.Div(
                className=f"schema-map-row schema-map-row-{change.status}",
                children=[
                    html.Span(change.label, className="schema-map-label"),
                    html.Div(
                        className="schema-map-delta",
                        title=tooltip,
                        children=[
                            _delta_bar(
                                change.count.delta or 0,
                                max_value=max_delta,
                                title=tooltip,
                            ),
                            html.Span(
                                _format_schema_delta(change.count, status=change.status),
                                title=tooltip,
                            ),
                        ],
                    ),
                ],
            )
        )
    return html.Div(
        className=f"schema-map-group schema-map-group-{status}",
        children=[
            html.Span(
                f"{len(changes):,} {status}",
                className="schema-map-group-heading",
            ),
            *rows,
        ],
    )


def _group_map_changes(
    changes: tuple[MapEntryChange, ...],
) -> list[tuple[str, tuple[MapEntryChange, ...]]]:
    return [
        (status, matching)
        for status in ("added", "removed", "changed")
        if (matching := tuple(change for change in changes if change.status == status))
    ]


def _baseline_cell(value: str) -> html.Div:
    return html.Div(
        className="comparison-overview-cell",
        children=[
            html.Strong(value),
        ],
    )


def _metric_delta_cell(
    value: str,
    delta: CountDelta,
) -> html.Div:
    children: list[object] = [
        html.Strong(value),
        _overview_delta(delta),
    ]
    return html.Div(
        className="comparison-overview-cell",
        children=children,
    )


def _change_count_cell(
    value: str,
    change_count: int,
    *,
    max_count: int,
) -> html.Div:
    children: list[object] = [
        html.Strong(value),
        html.Span(
            f"{change_count:,} changed" if change_count else "No changes",
            className="comparison-overview-note",
        ),
    ]
    if change_count:
        children.insert(1, _delta_bar(change_count, max_value=max_count, neutral=True))
    return html.Div(
        className="comparison-overview-cell",
        children=children,
    )


def _baseline_schema_type_overview_cell(
    comparisons: tuple[GraphComparison, ...],
) -> html.Div:
    schema = next((pair.schema for pair in comparisons if pair.schema.available), None)
    if schema is None:
        return html.Div(
            className="comparison-overview-cell",
            children=[html.Strong("Unavailable")],
        )
    rows = [
        _schema_type_baseline_line("Nodes", schema.node_type_count),
        _schema_type_baseline_line("Edges", schema.edge_type_count),
    ]
    rows = [row for row in rows if row is not None]
    if not rows:
        return html.Div(
            className="comparison-overview-cell",
            children=[html.Strong("Unavailable")],
        )
    return html.Div(
        className="comparison-overview-cell schema-type-overview",
        children=rows,
    )


def _schema_type_overview_cell(
    schema: SchemaDiffSummary,
) -> html.Div:
    if not schema.available:
        return html.Div(
            className="comparison-overview-cell",
            children=[html.Strong("Unavailable")],
        )
    node_summary = _type_count_summary(
        schema.node_type_count,
        label="Nodes",
    )
    edge_summary = _type_count_summary(
        schema.edge_type_count,
        label="Edges",
    )
    if not node_summary and not edge_summary:
        return html.Div(
            className="comparison-overview-cell",
            children=[html.Strong("Unavailable")],
        )
    return html.Div(
        className="comparison-overview-cell schema-type-overview",
        children=[item for item in (node_summary, edge_summary) if item],
    )


def _schema_type_baseline_line(
    label: str,
    type_count: dict[str, int] | None,
) -> html.Div | None:
    if not type_count:
        return None
    old = type_count.get("old")
    if old is None:
        return None
    return html.Div(
        className="schema-type-overview-line",
        children=[
            html.Span(f"{label}:"),
            html.Strong(_format_count(old)),
        ],
    )


def _type_count_summary(
    type_count: dict[str, int] | None,
    *,
    label: str,
) -> html.Div | None:
    delta = _type_count_delta(type_count)
    if delta is None:
        return None
    children: list[object] = [
        html.Span(f"{label}:"),
        html.Strong(_format_count(delta.new)),
    ]
    if delta.delta:
        children.append(_overview_delta(delta))
    return html.Div(
        className="schema-type-overview-line",
        children=children,
    )


def _type_count_delta(type_count: dict[str, int] | None) -> CountDelta | None:
    if not type_count:
        return None
    old = type_count.get("old")
    new = type_count.get("new")
    if old is None or new is None:
        return None
    return CountDelta(
        old=old,
        new=new,
        delta=new - old,
        percent_change=None,
    )


def _overview_delta(delta: CountDelta) -> html.Span:
    direction = _delta_direction(delta)
    arrow = {"positive": "↑", "negative": "↓"}.get(direction)
    children: list[object] = []
    if arrow:
        children.append(html.Span(arrow, className="overview-delta-arrow"))
    children.append(html.Span(_format_delta(delta)))
    return html.Span(
        className=f"comparison-overview-note overview-delta overview-delta-{direction}",
        children=children,
    )


def _delta_direction(delta: CountDelta) -> str:
    if delta.delta is None or delta.delta == 0:
        return "neutral"
    return "positive" if delta.delta > 0 else "negative"


def _source_change_cell(
    pair: GraphComparison,
    *,
    index: int,
) -> html.Div:
    change_count = len(pair.source_changes)
    children: list[object] = [
        html.Strong(_format_count(pair.target.source_count)),
    ]
    if change_count:
        dialog_id = f"source-changes-dialog-{index}"
        children.append(
            html.Div(
                className="source-change-action-row",
                children=[
                    html.Span(
                        f"{change_count:,} changed",
                        className="comparison-overview-note",
                    ),
                    html.Button(
                        "Show changes",
                        type="button",
                        className="button button-tertiary comparison-dialog-open",
                        **{"data-dialog-target": dialog_id},
                    ),
                ],
            )
        )
        children.append(
            html.Dialog(
                id=dialog_id,
                className="comparison-dialog",
                children=[
                    html.Div(
                        className="comparison-dialog-card",
                        children=[
                            html.Div(
                                className="section-heading-row",
                                children=[
                                    html.Div(
                                        children=[
                                            html.H4(
                                                f"Changed Sources: "
                                                f"{pair.baseline.label} -> {pair.target.label}"
                                            ),
                                            html.P(
                                                f"{change_count:,} underlying data source "
                                                f"records changed in {pair.target.label} " 
                                                f"relative to {pair.baseline.label} baseline.",
                                                className="status-line",
                                            ),
                                        ]
                                    ),
                                    html.Button(
                                        "Close",
                                        type="button",
                                        className="button button-quiet comparison-dialog-close",
                                        **{"data-dialog-close": dialog_id},
                                    ),
                                ],
                            ),
                            _source_changes_table(
                                pair.source_changes,
                                heading_level=5,
                                baseline_label=pair.baseline.label,
                                comparison_label=pair.target.label,
                            ),
                        ],
                    )
                ],
            )
        )
    else:
        children.append(
            html.Span(
                "No changes",
                className="comparison-overview-note",
            )
        )
    return html.Div(className="comparison-overview-cell source-overview-cell", children=children)


def _metadata_release_cell(pair: GraphComparison) -> html.Div:
    release = pair.target.release_version or "Unknown"
    return html.Div(
        className="comparison-overview-cell",
        children=[
            html.Strong(release),
        ],
    )


def _delta_bar(
    value: int,
    *,
    max_value: int,
    neutral: bool = False,
    title: str | None = None,
) -> html.Div:
    width = max(3, round((abs(value) / max_value) * 100)) if max_value > 0 else 0
    direction_class = "neutral" if neutral else ("positive" if value > 0 else "negative")
    return html.Div(
        className=f"comparison-glyph comparison-glyph-{direction_class}",
        title=title,
        children=[
            html.Span(
                className="comparison-glyph-bar",
                style={"width": f"{width}%"},
            )
        ],
    )


def _max_abs_delta(deltas: Iterable[CountDelta]) -> int:
    return max((abs(delta.delta or 0) for delta in deltas), default=0)


def _max_count_delta(deltas: Iterable[CountDelta]) -> int:
    return max((abs(delta.delta or 0) for delta in deltas), default=0)


def _edge_schema_change_label(change: EdgeSchemaChange) -> str:
    return f"{change.subject_category} - {change.predicate} - {change.object_category}"


def _table_section(
    title: str,
    rows: list[dict[str, str]],
    *,
    columns: list[dict[str, str]],
    empty_message: str,
    heading_level: int = 4,
    page_size: int = 10,
    sortable: bool = False,
    filterable: bool = False,
    style_data_conditional: list[dict[str, object]] | None = None,
) -> html.Div:
    heading = html.H5(title) if heading_level == 5 else html.H4(title)
    if not rows:
        return html.Div(
            className="comparison-section empty-inline",
            children=[heading, html.P(empty_message)],
        )
    return html.Div(
        className="comparison-section",
        children=[
            heading,
            dash_table.DataTable(
                columns=columns,
                data=rows,
                page_size=page_size,
                sort_action="native" if sortable else "none",
                filter_action="native" if filterable else "none",
                style_table={"overflowX": "auto"},
                style_cell=_table_cell_style(),
                style_data_conditional=style_data_conditional or [],
            ),
        ],
    )


def _format_count(value: int | None) -> str:
    return "Unknown" if value is None else f"{value:,}"


def _format_delta(delta: CountDelta) -> str:
    if delta.delta is None:
        return "Unknown"
    sign = "+" if delta.delta > 0 else ""
    value = f"{sign}{delta.delta:,}"
    if delta.percent_change is None:
        return value
    percent_sign = "+" if delta.percent_change > 0 else ""
    return f"{value} ({percent_sign}{delta.percent_change:,.2f}%)"


def _format_schema_delta(delta: CountDelta, *, status: str) -> str:
    if status in {"added", "removed"}:
        return _format_delta(
            CountDelta(
                old=delta.old,
                new=delta.new,
                delta=delta.delta,
                percent_change=None,
            )
        )
    return _format_delta(delta)


def _schema_delta_tooltip(delta: CountDelta, *, status: str) -> str:
    return "\n".join(
        [
            f"Baseline: {_format_count(delta.old)}",
            f"Comparison: {_format_count(delta.new)}",
            f"Delta: {_format_schema_delta(delta, status=status)}",
        ]
    )


def _message_list(messages: list[str]) -> html.Div | str:
    if not messages:
        return ""
    return html.Div(
        className="comparison-warning-list",
        children=[html.P(message) for message in messages],
    )


def _table_cell_style() -> dict[str, str]:
    return {
        "textAlign": "left",
        "fontFamily": "inherit",
        "fontSize": "14px",
        "whiteSpace": "normal",
        "height": "auto",
    }
