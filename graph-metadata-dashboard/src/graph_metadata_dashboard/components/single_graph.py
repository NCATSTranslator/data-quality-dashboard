from __future__ import annotations

from typing import Any

from dash import dcc, html
from plotly.graph_objects import Figure

from graph_metadata_dashboard.parsers.models import ParsedGraphMetadata, SubgraphSource
from graph_metadata_dashboard.viz.figures import contribution_chart_style, subgraph_contribution_bar


def provenance_contribution(parsed: ParsedGraphMetadata) -> html.Div:
    if parsed.subgraphs:
        has_node_counts = any(source.node_count is not None for source in parsed.subgraphs)
        has_edge_counts = any(source.edge_count is not None for source in parsed.subgraphs)
        if len(parsed.subgraphs) == 1 and (has_node_counts or has_edge_counts):
            return _single_subgraph_statement(parsed.subgraphs[0])
        if has_node_counts:
            return html.Div(
                className=(
                    "contribution-panel contribution-panel-with-metric"
                    if has_edge_counts else "contribution-panel"
                ),
                children=_contribution_chart(parsed),
            )
        if has_edge_counts:
            return html.Div(
                className="contribution-panel",
                children=[
                    html.P(
                        "Subgraph node counts were not provided. Showing edge counts by "
                        "contributing subgraph instead.",
                        className="status-line",
                    ),
                    *_contribution_chart(parsed),
                ]
            )
        primary_source_contribution = _primary_source_contribution(parsed)
        if primary_source_contribution is not None:
            return primary_source_contribution
        if len(parsed.subgraphs) == 1:
            return _single_subgraph_statement(parsed.subgraphs[0])
        return html.Div(
            className="empty-inline",
            children=[
                html.P(
                    "Subgraphs are listed, but no subgraph contribution counts are "
                    "available for this metadata payload.",
                    className="status-line",
                )
            ],
        )

    primary_source_contribution = _primary_source_contribution(parsed)
    if primary_source_contribution is not None:
        return primary_source_contribution

    return html.Div(
        className="empty-inline",
        children=[
            html.P(
                "No subgraph contribution counts are available for this metadata payload.",
                className="status-line",
            )
        ],
    )


def _primary_source_contribution(parsed: ParsedGraphMetadata) -> html.Div | None:
    primary_sources = primary_knowledge_source_counts(parsed)
    if primary_sources:
        src_len = len(primary_sources)
        if src_len == 1:
            source, count = next(iter(primary_sources.items()))
            return _single_primary_source_statement(source, count)

        return html.Div(
            className="contribution-panel",
            children=[
                html.P(
                    "No subgraph counts were provided. Showing edge counts by "
                    "primary knowledge source from schema summary instead.",
                    className="status-line",
                ),
                *_contribution_chart(parsed),
            ]
        )
    return None


def contribution_sources(
    parsed: ParsedGraphMetadata,
) -> tuple[tuple[SubgraphSource, ...], str, str]:
    if any(source.node_count is not None for source in parsed.subgraphs):
        return parsed.subgraphs, "node_count", "Subgraph"
    if any(source.edge_count is not None for source in parsed.subgraphs):
        return parsed.subgraphs, "edge_count", "Subgraph"
    sources = tuple(
        SubgraphSource(id=source, name=source, node_count=None, edge_count=count)
        for source, count in primary_knowledge_source_counts(parsed).items()
    )
    return sources, "edge_count", "Primary knowledge source"


def contribution_figure(
    parsed: ParsedGraphMetadata, metric: str | None = None,
) -> Figure:
    sources, default_metric, label = contribution_sources(parsed)
    selected_metric = metric if metric in {"node_count", "edge_count"} else default_metric
    if not any(getattr(source, selected_metric) is not None for source in sources):
        selected_metric = default_metric
    return subgraph_contribution_bar(
        sources, metric=selected_metric, contribution_label=label,
    )


def _contribution_chart(parsed: ParsedGraphMetadata) -> list[Any]:
    sources, metric, label = contribution_sources(parsed)
    figure = contribution_figure(parsed)
    children: list[Any] = []
    if label == "Subgraph" and all(
        any(getattr(source, count_metric) is not None for source in sources)
        for count_metric in ("node_count", "edge_count")
    ):
        children.append(dcc.RadioItems(
            id="subgraph-contribution-metric",
            options=[
                {"label": "Nodes", "value": "node_count"},
                {"label": "Edges", "value": "edge_count"},
            ],
            value=metric,
            inline=True,
            className="contribution-metric-toggle",
        ))
    children.append(
        dcc.Graph(
            id="contribution-chart", figure=figure, responsive=True,
            style=contribution_chart_style(figure),
            className="contribution-chart",
        )
    )
    return children


def _single_subgraph_statement(subgraph: SubgraphSource) -> html.Div:
    label = subgraph.name or subgraph.id or "Unknown source"
    counts = []
    if subgraph.node_count is not None:
        counts.append(f"{subgraph.node_count:,} nodes")
    if subgraph.edge_count is not None:
        counts.append(f"{subgraph.edge_count:,} edges")
    count_text = f" ({', '.join(counts)})" if counts else ""
    return html.Div(
        className="empty-inline",
        children=[
            html.P(
                f"This metadata reports one contributing subgraph: {label}{count_text}.",
                className="status-line",
            )
        ],
    )


def _single_primary_source_statement(source: str, count: int) -> html.Div:
    return html.Div(
        className="empty-inline",
        children=[
            html.P(
                "No subgraph counts were provided. Schema summary reports one "
                f"primary knowledge source: {source} ({count:,} edges).",
                className="status-line",
            )
        ],
    )


def primary_knowledge_source_counts(parsed: ParsedGraphMetadata) -> dict[str, int]:
    if parsed.schema is None:
        return {}
    value = parsed.schema.edges_summary.get("primary_knowledge_sources")
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for source, count in value.items():
        parsed_count = _int_from_summary_count(count)
        if parsed_count is not None:
            counts["Unknown" if source is None else str(source)] = parsed_count
    return counts


def upload_selection_status(
    graph_filename: str | None,
    schema_filename: str | None,
) -> list[html.P]:
    if not graph_filename and not schema_filename:
        return []

    messages = []
    if graph_filename:
        messages.append(html.P(f"Selected graph metadata: {graph_filename}"))
    else:
        messages.append(html.P("Graph metadata file is required."))

    if schema_filename:
        messages.append(html.P(f"Selected schema: {schema_filename}"))
    else:
        messages.append(html.P("Optional schema file not selected."))
    return messages


def url_selection_status(
    graph_url: str | None,
    schema_url: str | None,
) -> list[html.P]:
    items: list[html.P] = []
    selected_graph_url = _clean_string(graph_url)
    selected_schema_url = _clean_string(schema_url)
    if selected_graph_url:
        items.append(html.P(f"Graph metadata URL: {selected_graph_url}"))
    if selected_schema_url:
        items.append(html.P(f"Schema URL: {selected_schema_url}"))
    return items


def _clean_string(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _int_from_summary_count(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
