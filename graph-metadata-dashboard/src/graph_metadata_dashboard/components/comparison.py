from __future__ import annotations

from collections.abc import Iterable

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


def _comparison_pair_section(
    pair: GraphComparison,
    *,
    collapsed: bool,
    open_by_default: bool,
) -> html.Div:
    title = f"Schema-Level Differences: {_graph_title(pair.baseline)} " \
            f"-> {_graph_title(pair.target)}"
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


def _schema_diff_section(pair: GraphComparison) -> html.Div:
    schema = pair.schema
    if not schema.available:
        return html.Div(
            className="comparison-section empty-inline",
            children=[
                html.P(schema.message),
            ],
        )

    return html.Div(
        className="comparison-section schema-diff-section",
        children=[
            html.P(
                f"Schema differences of {_graph_title(pair.target)}" \
                f" relative to the {_graph_title(pair.baseline)}" \
                " baseline, including changes in overall node and " \
                "edge composition summaries, node categories, and edge triples.",
                className="status-line",
            ),
            _schema_summary_table(schema),
            _schema_entry_tables(schema),
        ],
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
