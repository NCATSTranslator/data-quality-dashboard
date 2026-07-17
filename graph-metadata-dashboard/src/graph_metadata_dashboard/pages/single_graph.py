from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from dash import (
    Dash,
    Input,
    Output,
    State,
    callback_context,
    dash_table,
    dcc,
    html,
    no_update,
    register_page,
)

from graph_metadata_dashboard.cache import MetadataCache
from graph_metadata_dashboard.components.single_graph import (
    provenance_contribution,
    upload_selection_status,
)
from graph_metadata_dashboard.loaders.kgx_storage import (
    KgxRelease,
    KgxStorageClient,
    KgxStorageRelease,
)
from graph_metadata_dashboard.loaders.uploaded import UploadedMetadata, decode_dash_upload
from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata, parse_schema
from graph_metadata_dashboard.parsers.models import ParsedGraphMetadata
from graph_metadata_dashboard.viz.figures import (
    node_category_bar,
    predicate_sankey,
)


def layout() -> html.Div:
    return html.Div(
        children=[
            dcc.Store(id="loaded-graph-state", storage_type="session"),
            html.Section(
                className="hero",
                children=[
                    html.Div(
                        [
                            html.P("ORION JSON-LD metadata", className="eyebrow"),
                            html.H2("Inspect one graph without loading the graph itself"),
                            html.P(
                                "Choose the latest Biomedical Data Translator KGX-storage release "
                                "or upload a graph-metadata.json file."
                            ),
                        ]
                    ),
                ],
            ),
            html.Section(
                className="selector-grid",
                children=[
                    html.Div(
                        className="content-card",
                        children=[
                            html.H3("KGX Storage Release"),
                            html.Div(
                                className="button-row",
                                children=[
                                    html.Button(
                                        "Refresh releases",
                                        id="refresh-releases",
                                        n_clicks=0,
                                    ),
                                    html.Button("Load selected graph", id="load-kgx", n_clicks=0),
                                ],
                            ),
                            dcc.Dropdown(
                                id="kgx-release-dropdown",
                                placeholder="Select a graph release",
                                optionHeight=44,
                            ),
                            html.Div(id="release-status", className="status-line"),
                        ],
                    ),
                    html.Div(
                        className="content-card",
                        children=[
                            html.H3("Upload Metadata"),
                            dcc.Upload(
                                id="upload-graph-metadata",
                                className="upload-box",
                                children=html.Div(["Drop or select graph-metadata.json"]),
                                multiple=False,
                            ),
                            dcc.Upload(
                                id="upload-schema",
                                className="upload-box secondary",
                                children=html.Div(["Optional schema.json"]),
                                multiple=False,
                            ),
                            html.Div(id="upload-selection-status", className="upload-selection"),
                            html.Button("Load upload", id="load-upload", n_clicks=0),
                        ],
                    ),
                ],
            ),
            html.Div(id="load-status", className="status-line"),
            html.Div(id="overview-panel"),
            html.Div(id="provenance-panel"),
            html.Div(id="node-categories-panel"),
            html.Div(
                id="sankey-action-card",
                className="content-card",
                style={"display": "none"},
                children=[
                    html.Div(
                        className="section-heading-row",
                        children=[
                            html.Div(
                                children=[
                                    html.H3("Predicate / Edge Composition"),
                                    html.P(
                                        "Open the Sankey diagram as an overlay without "
                                        "leaving the current summary page.",
                                        className="status-line",
                                    ),
                                ]
                            ),
                            html.Button(
                                "Open Sankey diagram",
                                id="open-sankey",
                                n_clicks=0,
                                className="secondary-button",
                            ),
                        ],
                    )
                ],
            ),
            html.Div(
                id="sankey-modal-container",
                className="modal-backdrop",
                style={"display": "none"},
                children=[
                    html.Div(
                        className="modal-panel",
                        children=[
                            html.Div(
                                className="modal-header",
                                children=[
                                    html.H3("Predicate / Edge Composition"),
                                    html.Button("Close", id="close-sankey", n_clicks=0),
                                ],
                            ),
                            html.Div(id="sankey-modal-body", className="modal-body"),
                        ],
                    )
                ],
            ),
        ]
    )


register_page(__name__, path="/", name="Single Graph")


def register_callbacks(
    app: Dash,
    *,
    cache: MetadataCache,
    kgx_client: KgxStorageClient,
) -> None:
    @app.callback(
        Output("session-id", "data"),
        Input("url", "pathname"),
        State("session-id", "data"),
    )
    def ensure_session_id(pathname: str | None, current_session_id: str | None) -> str:
        del pathname
        return current_session_id or uuid4().hex

    @app.callback(
        Output("kgx-release-dropdown", "options"),
        Output("release-status", "children"),
        Input("refresh-releases", "n_clicks"),
    )
    def populate_releases(n_clicks: int) -> tuple[list[dict[str, str]], str]:
        del n_clicks
        try:
            releases = kgx_client.latest_releases()
        except Exception as error:
            return [], f"Could not load KGX manifest: {error}"
        options = [{"label": release.label, "value": release.source_id} for release in releases]
        return options, f"Loaded {len(options)} latest releases."

    @app.callback(
        Output("upload-selection-status", "children"),
        Input("upload-graph-metadata", "filename"),
        Input("upload-schema", "filename"),
    )
    def render_upload_selection(
        graph_filename: str | None,
        schema_filename: str | None,
    ) -> list[html.P]:
        return upload_selection_status(graph_filename, schema_filename)

    @app.callback(
        Output("loaded-graph-state", "data"),
        Output("load-status", "children"),
        Input("load-kgx", "n_clicks"),
        Input("load-upload", "n_clicks"),
        State("kgx-release-dropdown", "value"),
        State("upload-graph-metadata", "contents"),
        State("upload-graph-metadata", "filename"),
        State("upload-schema", "contents"),
        State("upload-schema", "filename"),
        State("session-id", "data"),
        prevent_initial_call=True,
    )
    def load_graph(
        kgx_clicks: int,
        upload_clicks: int,
        selected_source: str | None,
        graph_contents: str | None,
        graph_filename: str | None,
        schema_contents: str | None,
        schema_filename: str | None,
        session_id: str | None,
    ) -> tuple[dict[str, Any] | object, str]:
        del kgx_clicks, upload_clicks, schema_filename
        session_id = session_id or uuid4().hex
        trigger = callback_context.triggered_id
        try:
            if trigger == "load-kgx":
                if not selected_source:
                    return no_update, "Select a KGX release first."
                release = kgx_client.release_for_source(selected_source)
                source = KgxStorageRelease(client=kgx_client, release=release)
                parsed = parse_graph_metadata(source.load_graph_metadata())
                state = _cache_graph(cache, session_id, source.source_key, parsed)
                state.update(
                    {
                        "kind": "kgx",
                        "source_id": release.source_id,
                        "release_version": release.release_version,
                        "data_url": release.data_url,
                        "label": source.label,
                    }
                )
                return state, f"Loaded {source.label}."

            if trigger == "load-upload":
                if not graph_contents:
                    return no_update, "Upload graph-metadata.json first."
                graph_data = decode_dash_upload(graph_contents, context=graph_filename or "upload")
                schema_data = (
                    decode_dash_upload(schema_contents, context="schema upload")
                    if schema_contents
                    else None
                )
                source = UploadedMetadata(
                    graph_metadata=graph_data,
                    schema=schema_data,
                    filename=graph_filename or "uploaded graph-metadata.json",
                )
                parsed = parse_graph_metadata(source.load_graph_metadata(), schema_data=schema_data)
                state = _cache_graph(cache, session_id, source.source_key, parsed)
                state.update({"kind": "upload", "label": source.label})
                return state, f"Loaded {source.label}."
        except Exception as error:
            return no_update, f"Could not load graph metadata: {error}"
        return no_update, ""

    @app.callback(
        Output("overview-panel", "children"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_overview(
        graph_state: dict[str, Any] | None,
        session_id: str | None,
    ) -> Any:
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return _empty_state()
        return _overview(parsed)

    @app.callback(
        Output("provenance-panel", "children"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_provenance(
        graph_state: dict[str, Any] | None,
        session_id: str | None,
    ) -> Any:
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return ""
        return _provenance(parsed)

    @app.callback(
        Output("node-categories-panel", "children"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_node_categories(
        graph_state: dict[str, Any] | None,
        session_id: str | None,
    ) -> Any:
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return ""
        parsed = _ensure_schema_loaded(cache, kgx_client, session_id, graph_state, parsed)
        if parsed.schema is None:
            return html.Div(
                className="content-card",
                children=[
                    html.H3("Schema unavailable"),
                    html.P(
                        "This graph metadata does not include inline schema data, and no "
                        "external schema.json could be loaded for this release."
                    ),
                ],
            )
        return html.Div(
            className="content-card",
            children=[
                html.H3("Node Categories"),
                html.P(
                    "Top node category counts from schema metadata.",
                    className="status-line",
                ),
                dcc.Graph(figure=node_category_bar(parsed.schema.nodes, top_n=30)),
            ],
        )

    @app.callback(
        Output("sankey-action-card", "style"),
        Input("loaded-graph-state", "data"),
    )
    def toggle_sankey_action(graph_state: dict[str, Any] | None) -> dict[str, str]:
        return {} if graph_state else {"display": "none"}

    @app.callback(
        Output("sankey-modal-container", "style"),
        Output("sankey-modal-body", "children"),
        Input("open-sankey", "n_clicks"),
        Input("close-sankey", "n_clicks"),
        State("loaded-graph-state", "data"),
        State("session-id", "data"),
        prevent_initial_call=True,
    )
    def render_sankey_modal(
        open_clicks: int | None,
        close_clicks: int | None,
        graph_state: dict[str, Any] | None,
        session_id: str | None,
    ) -> tuple[dict[str, str], Any]:
        del open_clicks, close_clicks
        if callback_context.triggered_id == "close-sankey":
            return {"display": "none"}, ""

        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return {"display": "none"}, ""
        parsed = _ensure_schema_loaded(cache, kgx_client, session_id, graph_state, parsed)
        if parsed.schema is None:
            return (
                {},
                [
                    html.H4("Sankey unavailable"),
                    html.P(
                        "Schema metadata is required for the Sankey diagram, but it could "
                        "not be loaded for this graph."
                    ),
                ],
            )
        return (
            {},
            [
                dcc.Graph(
                    figure=predicate_sankey(parsed.schema.edges, top_n=40),
                    className="modal-graph",
                )
            ],
        )


def _cache_graph(
    cache: MetadataCache,
    session_id: str,
    cache_key: str,
    parsed: ParsedGraphMetadata,
) -> dict[str, Any]:
    cache.set(session_id, cache_key, parsed)
    return {"cache_key": cache_key}


def _get_cached_graph(
    cache: MetadataCache,
    session_id: str | None,
    graph_state: dict[str, Any] | None,
) -> ParsedGraphMetadata | None:
    if not session_id or not graph_state:
        return None
    cache_key = graph_state.get("cache_key")
    if not isinstance(cache_key, str):
        return None
    value = cache.get(session_id, cache_key)
    return value if isinstance(value, ParsedGraphMetadata) else None


def _ensure_schema_loaded(
    cache: MetadataCache,
    kgx_client: KgxStorageClient,
    session_id: str | None,
    graph_state: dict[str, Any] | None,
    parsed: ParsedGraphMetadata,
) -> ParsedGraphMetadata:
    if parsed.schema is not None or not session_id or not graph_state:
        return parsed
    if graph_state.get("kind") != "kgx":
        return parsed
    source_id = graph_state.get("source_id")
    release_version = graph_state.get("release_version")
    data_url = graph_state.get("data_url")
    cache_key = graph_state.get("cache_key")
    required_values = (source_id, release_version, data_url, cache_key)
    if not all(isinstance(value, str) for value in required_values):
        return parsed
    release = KgxRelease(source_id=source_id, release_version=release_version, data_url=data_url)
    schema_data = kgx_client.load_release_schema(release, parsed.schema_reference.url)
    schema = parse_schema(schema_data)
    updated = replace(parsed, schema=schema)
    cache.set(session_id, cache_key, updated)
    return updated


def _empty_state() -> html.Div:
    return html.Div(
        className="content-card empty-state",
        children=[
            html.H3("No graph loaded"),
            html.P("Select a KGX release or upload metadata to start."),
        ],
    )


def _overview(parsed: ParsedGraphMetadata) -> html.Div:
    return html.Div(
        className="content-card",
        children=[
            html.Div(
                className="overview-heading",
                children=[
                    html.P(
                        parsed.schema_reference.kind.capitalize() + " schema",
                        className="eyebrow",
                    ),
                    html.H2(parsed.name or "Unnamed graph"),
                    html.P(parsed.release_version or "No release version provided"),
                ],
            ),
            html.Div(
                className="metric-grid",
                children=[
                    _metric("Nodes", _format_count(parsed.total_node_count)),
                    _metric("Edges", _format_count(parsed.total_edge_count)),
                    _metric("Biolink", parsed.biolink_version or "Unknown"),
                    _metric("Babel", parsed.babel_version or "Unknown"),
                ],
            ),
            _definition_list(
                {
                    "Build version": parsed.build_version,
                    "Build time": parsed.build_time,
                    "Date created": parsed.date_created,
                    "Date modified": parsed.date_modified,
                    "License": parsed.license,
                    "Schema marker": parsed.schema_version_marker,
                }
            ),
        ],
    )


def _provenance(parsed: ParsedGraphMetadata) -> html.Div:
    source_rows = [
        {
            "id": source.id,
            "name": source.name or "Unknown",
            "version": source.version,
            "license": source.license,
        }
        for source in parsed.knowledge_sources
    ]
    return html.Div(
        className="content-card",
        children=[
            html.H3("Sources and Subgraphs"),
            provenance_contribution(parsed),
            html.H4("Underlying Data Sources"),
            dash_table.DataTable(
                columns=[
                    {"name": "ID", "id": "id"},
                    {"name": "Name", "id": "name"},
                    {"name": "Version", "id": "version"},
                    {"name": "License", "id": "license"},
                ],
                data=source_rows,
                page_size=12,
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "left", "fontFamily": "inherit", "fontSize": "14px"},
            ),
        ],
    )


def _metric(label: str, value: str) -> html.Div:
    return html.Div(
        className="metric-card",
        children=[html.P(label, className="metric-label"), html.Strong(value)],
    )


def _definition_list(values: dict[str, str]) -> html.Dl:
    children: list[Any] = []
    for label, value in values.items():
        children.extend([html.Dt(label), html.Dd(value or "Unknown")])
    return html.Dl(className="definition-grid", children=children)


def _format_count(value: int | None) -> str:
    return "Unknown" if value is None else f"{value:,}"
