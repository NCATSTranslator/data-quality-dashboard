from __future__ import annotations

from collections.abc import Iterable

from dash import dash_table, html

from graph_metadata_dashboard.diff import (
    CountDelta,
    EdgeSchemaChange,
    GraphComparison,
    MapEntryChange,
    NodeSchemaChange,
    SchemaDiffSummary,
    SourceChange,
    SubgraphChange,
    compare,
)
from graph_metadata_dashboard.parsers.models import ParsedGraphMetadata


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
                "other loaded graph against it.",
                className="status-line",
            ),
            _message_list(load_errors),
            _n_way_overview(result.comparisons),
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
            ]
        ),
    ]
    max_node_delta = _max_abs_delta(pair.total_nodes for pair in comparisons)
    max_edge_delta = _max_abs_delta(pair.total_edges for pair in comparisons)
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
                            max_delta=max_node_delta,
                        )
                    ),
                    html.Td(
                        _metric_delta_cell(
                            _format_count(pair.target.edge_count),
                            pair.total_edges,
                            max_delta=max_edge_delta,
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


def _comparison_pair_section(
    pair: GraphComparison,
    *,
    collapsed: bool,
    open_by_default: bool,
) -> html.Div:
    contents = []
    if pair.subgraph_changes:
        contents.append(_subgraph_changes_table(pair.subgraph_changes))
    contents.append(_schema_diff_section(pair.schema))
    if collapsed:
        return html.Details(
            className="comparison-pair-card",
            open=open_by_default,
            children=[
                html.Summary(f"{pair.baseline.label} -> {pair.target.label}"),
                *contents,
            ],
        )
    return html.Div(
        className="comparison-pair-card",
        children=[
            html.H3(f"{pair.baseline.label} -> {pair.target.label}"),
            *contents,
        ],
    )


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
            "old_version": change.old_version or "None",
            "new_version": change.new_version or "None",
            "old_license": change.old_license or "None",
            "new_license": change.new_license or "None",
        }
        for change in changes
    ]
    return _table_section(
        "Underlying Data Source Changes",
        rows,
        columns=[
            {"name": "ID", "id": "id"},
            {"name": "Name", "id": "name"},
            {"name": f"{baseline_label} Version", "id": "old_version"},
            {"name": f"{comparison_label} Version", "id": "new_version"},
            {"name": f"{baseline_label} License", "id": "old_license"},
            {"name": f"{comparison_label} License", "id": "new_license"},
        ],
        empty_message="No source additions, removals, version changes, or license changes found.",
        heading_level=heading_level,
    )


def _subgraph_changes_table(changes: tuple[SubgraphChange, ...]) -> html.Div:
    rows = [
        {
            "status": change.status,
            "id": change.source_id,
            "name": change.name,
            "old_nodes": _format_count(change.node_delta.old),
            "new_nodes": _format_count(change.node_delta.new),
            "node_delta": _format_delta(change.node_delta),
            "old_edges": _format_count(change.edge_delta.old),
            "new_edges": _format_count(change.edge_delta.new),
            "edge_delta": _format_delta(change.edge_delta),
        }
        for change in changes[:25]
    ]
    return _table_section(
        "Subgraph Contribution Changes",
        rows,
        columns=[
            {"name": "Status", "id": "status"},
            {"name": "ID", "id": "id"},
            {"name": "Name", "id": "name"},
            {"name": "Baseline Nodes", "id": "old_nodes"},
            {"name": "Comparison Nodes", "id": "new_nodes"},
            {"name": "Node Delta", "id": "node_delta"},
            {"name": "Baseline Edges", "id": "old_edges"},
            {"name": "Comparison Edges", "id": "new_edges"},
            {"name": "Edge Delta", "id": "edge_delta"},
        ],
        empty_message="No subgraph contribution count changes found.",
    )


def _schema_diff_section(schema: SchemaDiffSummary) -> html.Div:
    if not schema.available:
        return html.Div(
            className="comparison-section empty-inline",
            children=[
                html.H4("Schema-Level Differences"),
                html.P(schema.message),
            ],
        )

    return html.Div(
        className="comparison-section schema-diff-section",
        children=[
            html.H4("Schema-Level Differences"),
            html.P(
                "Node and edge rows summarize ORION schema diff entries; the aggregate table "
                "below summarizes schema-level rollups such as predicates and source-predicate "
                "composition.",
                className="status-line",
            ),
            _schema_entry_tables(schema),
            _schema_change_table(schema),
        ],
    )


def _schema_change_table(schema: SchemaDiffSummary) -> html.Div:
    rows = _schema_change_rows(schema)
    return _table_section(
        "Aggregate Schema Summary Changes",
        rows,
        columns=[
            {"name": "Area", "id": "area"},
            {"name": "Schema Item", "id": "item"},
            {"name": "Status", "id": "status"},
            {"name": "Baseline", "id": "old"},
            {"name": "Comparison", "id": "new"},
            {"name": "Delta", "id": "delta"},
        ],
        empty_message="No aggregate schema summary changes found.",
        heading_level=5,
        page_size=20,
        sortable=True,
        filterable=True,
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


def _node_schema_table(changes: tuple[NodeSchemaChange, ...]) -> html.Div | None:
    if not changes:
        return None
    max_count_delta = _max_count_delta(change.count for change in changes)
    return html.Div(
        className="schema-entry-section",
        children=[
            html.H5("Node Category Changes"),
            html.P(
                "One row per changed node category. Count, ID-prefix, and attribute diffs are "
                "shown together.",
                className="comparison-table-note",
            ),
            _schema_rich_table(
                headers=("Node category", "Node count", "ID prefixes", "Attributes"),
                rows=[
                    (
                        html.Strong(change.label),
                        _schema_count_cell(change.count, max_delta=max_count_delta),
                        _schema_map_cell(change.id_prefix_changes),
                        _schema_map_cell(change.attribute_changes),
                    )
                    for change in changes
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
            html.H5("Edge Triple Changes"),
            html.P(
                "One row per changed subject-predicate-object category triple. Count, "
                "provenance, qualifier, attribute, and prefix diffs are grouped together.",
                className="comparison-table-note",
            ),
            _schema_rich_table(
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
                        _schema_count_cell(change.count, max_delta=max_count_delta),
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
    )


def _schema_rich_table(
    *,
    headers: tuple[str, ...],
    rows: list[tuple[object, ...]],
) -> html.Div:
    return html.Div(
        className="schema-rich-table-wrap",
        children=[
            html.Table(
                className="schema-rich-table",
                children=[
                    html.Thead(html.Tr([html.Th(header) for header in headers])),
                    html.Tbody(
                        [html.Tr([html.Td(cell) for cell in row]) for row in rows]
                    ),
                ],
            )
        ],
    )


def _schema_count_cell(delta: CountDelta, *, max_delta: int) -> html.Div:
    children: list[object] = [html.Strong(_format_delta(delta))]
    if delta.delta:
        children.insert(0, _delta_bar(delta.delta, max_value=max_delta))
        children.append(
            html.Span(
                f"{_format_count(delta.old)} -> {_format_count(delta.new)}",
                className="schema-map-summary",
            )
        )
    else:
        children.append(html.Span("No count change", className="schema-map-summary"))
    return html.Div(className="schema-count-cell", children=children)


def _schema_map_cell(changes: tuple[MapEntryChange, ...]) -> html.Div:
    if not changes:
        return html.Div(className="schema-map-cell muted-cell", children="No changes")
    max_delta = _max_count_delta(change.count for change in changes)
    return html.Div(
        className="schema-map-cell",
        children=[
            *[
                _schema_map_group(status, grouped_changes, max_delta=max_delta)
                for status, grouped_changes in _group_map_changes(changes)
            ],
        ],
    )


def _schema_map_group(
    status: str,
    changes: tuple[MapEntryChange, ...],
    *,
    max_delta: int,
) -> html.Div:
    return html.Div(
        className=f"schema-map-group schema-map-group-{status}",
        children=[
            html.Span(
                f"{len(changes):,} {status}",
                className="schema-map-group-heading",
            ),
            *[
                html.Div(
                    className=f"schema-map-row schema-map-row-{change.status}",
                    children=[
                        html.Span(change.label, className="schema-map-label"),
                        html.Div(
                            className="schema-map-delta",
                            children=[
                                _delta_bar(change.count.delta or 0, max_value=max_delta),
                                html.Span(_format_delta(change.count)),
                            ],
                        ),
                    ],
                )
                for change in changes
            ],
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


def _schema_change_rows(schema: SchemaDiffSummary) -> list[dict[str, str]]:
    rows: list[tuple[int, dict[str, str]]] = []
    rows.extend(_map_change_rows("Node ID prefix", schema.node_id_prefix_changes))
    rows.extend(_map_change_rows("Node attribute", schema.node_attribute_changes))
    rows.extend(_map_change_rows("Edge predicate", schema.edge_predicate_changes))
    rows.extend(_map_change_rows("Edge primary source", schema.edge_source_changes))
    rows.extend(_map_change_rows("Edge source predicate", schema.edge_source_predicate_changes))
    rows.extend(_map_change_rows("Edge qualifier", schema.edge_qualifier_changes))
    rows.extend(_map_change_rows("Edge attribute", schema.edge_attribute_changes))
    ranked = sorted(rows, key=lambda item: item[0], reverse=True)
    return [row for _, row in ranked[:75]]


def _map_change_rows(
    area: str,
    changes: tuple[MapEntryChange, ...],
) -> list[tuple[int, dict[str, str]]]:
    return [_ranked_row(area, change.label, change.status, change.count) for change in changes]


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
    *,
    max_delta: int,
) -> html.Div:
    children: list[object] = [
        html.Strong(value),
        html.Span(_format_delta(delta), className="comparison-overview-note"),
    ]
    if delta.delta:
        children.insert(1, _delta_bar(delta.delta, max_value=max_delta))
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


def _source_change_cell(
    pair: GraphComparison,
    *,
    index: int,
) -> html.Div:
    change_count = len(pair.source_changes)
    children: list[object] = [
        html.Strong(_format_count(pair.target.source_count)),
        html.Span(
            f"{change_count:,} sources changed" if change_count else "No changes",
            className="comparison-overview-note",
        ),
    ]
    if change_count:
        dialog_id = f"source-changes-dialog-{index}"
        children.append(
            html.Button(
                "Show changed sources",
                type="button",
                className="button button-tertiary comparison-dialog-open",
                **{"data-dialog-target": dialog_id},
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
                                                "records changed. These are graph-level "
                                                "isBasedOn records, not edge primary source "
                                                "counts from the schema.",
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
    return html.Div(className="comparison-overview-cell", children=children)


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
) -> html.Div:
    width = max(3, round((abs(value) / max_value) * 100)) if max_value > 0 else 0
    direction_class = "neutral" if neutral else ("positive" if value > 0 else "negative")
    return html.Div(
        className=f"comparison-glyph comparison-glyph-{direction_class}",
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


def _ranked_row(
    area: str,
    item: str,
    status: str,
    delta: CountDelta,
) -> tuple[int, dict[str, str]]:
    return (
        abs(delta.delta or 0),
        {
            "area": area,
            "item": item,
            "status": status,
            "old": _format_count(delta.old),
            "new": _format_count(delta.new),
            "delta": _format_delta(delta),
        },
    )


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
