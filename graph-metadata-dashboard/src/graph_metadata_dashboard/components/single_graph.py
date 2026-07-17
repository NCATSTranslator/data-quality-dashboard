from __future__ import annotations

from typing import Any

from dash import dcc, html

from graph_metadata_dashboard.parsers.models import ParsedGraphMetadata
from graph_metadata_dashboard.viz.figures import count_bar, subgraph_contribution_bar


def provenance_contribution(parsed: ParsedGraphMetadata) -> html.Div:
    if parsed.subgraphs:
        return html.Div(
            children=[
                dcc.Graph(figure=subgraph_contribution_bar(parsed.subgraphs)),
            ]
        )

    primary_sources = primary_knowledge_source_counts(parsed)
    if primary_sources:
        return html.Div(
            children=[
                html.P(
                    "No hasPart subgraph counts were provided. Showing edge counts by "
                    "primary knowledge source from schema summary instead.",
                    className="status-line",
                ),
                dcc.Graph(
                    figure=count_bar(
                        primary_sources,
                        title="Primary Knowledge Source Contribution",
                        xaxis_title="Primary knowledge source",
                        top_n=30,
                    )
                ),
            ]
        )

    return html.Div(
        className="empty-inline",
        children=[
            html.P(
                "No subgraph contribution counts are available for this metadata payload.",
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
        return [html.P("No upload files selected yet.")]

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


def _int_from_summary_count(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
