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

GraphState = dict[str, Any]
LoadGraphResult = tuple[object, object, object, object, object, object, object]


def layout() -> html.Div:
    return html.Div(
        children=[
            dcc.Store(id="loaded-graph-state", storage_type="session"),
            html.Section(
                className="hero",
                children=[
                    html.Div(
                        [
                            html.P("ORION Graph Metadata", className="eyebrow"),
                            html.H2("Explore graph structure and provenance through metadata"),
                            html.P(
                                "Select one or more graph releases from the Biomedical Data "
                                "Translator KGX storage, or upload your own graph-metadata.json "
                                "(optionally with schema.json). Selecting a single graph "
                                "summarizes and visualizes its metadata, while selecting multiple "
                                "graphs compares their metadata."
                            ),
                        ]
                    ),
                ],
            ),
            html.Section(
                className="content-card selector-card",
                children=[
                    html.Div(
                        className="selector-intro",
                        children=[
                            html.H3("Select Metadata"),
                            html.P(
                                "Choose from KGX releases, upload local metadata, or combine both "
                                "before loading selected metadata.",
                                className="status-line",
                            ),
                        ]
                    ),
                    html.Div(
                        className="selector-grid",
                        children=[
                            html.Div(
                                className="selector-subsection",
                                children=[
                                    html.H4("KGX Storage Release"),
                                    dcc.Dropdown(
                                        id="kgx-release-dropdown",
                                        placeholder="Select one or more graph metadata releases",
                                        multi=True,
                                        optionHeight=44,
                                    ),
                                    html.Div(id="release-status", className="status-line"),
                                ],
                            ),
                            html.Div(
                                className="selector-subsection",
                                children=[
                                    html.H4("Upload Metadata"),
                                    dcc.Upload(
                                        id="upload-graph-metadata",
                                        className="upload-box",
                                        children=html.Div(
                                            ["Drop or select graph metadata json from local disk"]
                                        ),
                                        multiple=False,
                                    ),
                                    dcc.Upload(
                                        id="upload-schema",
                                        className="upload-box secondary",
                                        children=html.Div(
                                            [
                                                "Drop or select graph schema json if needed "
                                                "(optional)"
                                            ]
                                        ),
                                        multiple=False,
                                    ),
                                    html.Div(
                                        id="upload-selection-status",
                                        className="upload-selection",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="button-row selection-actions",
                        children=[
                            html.Button(
                                "Load selected metadata",
                                id="load-selected-metadata",
                                n_clicks=0,
                                type="button",
                                disabled=True,
                                className="button button-primary",
                            ),
                            html.Button(
                                "Reset selection",
                                id="reset-selection",
                                n_clicks=0,
                                type="button",
                                disabled=True,
                                className="button button-quiet reset-selection-button",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="results-region",
                children=[
                    html.Div(id="load-status", className="status-line"),
                    html.Div(id="loaded-graphs-panel"),
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
                                                "Sankey chart built from schema "
                                                "edge triples and loaded on request. "
                                                "Click the button to see the Sankey chart.",
                                                className="status-line",
                                            ),
                                        ]
                                    ),
                                    html.Button(
                                        "Show Sankey chart",
                                        id="show-sankey",
                                        n_clicks=0,
                                        type="button",
                                        className="button button-secondary",
                                    ),
                                ],
                            ),
                            dcc.Loading(
                                html.Div(
                                    id="sankey-panel-body",
                                    className="sankey-scroll-panel",
                                ),
                                parent_className="sankey-loading",
                            ),
                        ],
                    ),
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
        Input("url", "pathname"),
    )
    def populate_releases(pathname: str | None) -> tuple[list[dict[str, str]], str]:
        del pathname
        try:
            releases = kgx_client.latest_releases()
        except Exception as error:
            return [], f"Could not load KGX manifest: {error}"
        options = [{"label": release.label, "value": release.source_id} for release in releases]
        return options, f"{len(options)} graphs available for selection"

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
        Output("load-selected-metadata", "disabled"),
        Output("reset-selection", "disabled"),
        Input("kgx-release-dropdown", "value"),
        Input("upload-graph-metadata", "filename"),
        Input("upload-schema", "filename"),
        Input("loaded-graph-state", "data"),
    )
    def toggle_reset_selection(
        selected_source: str | list[str] | None,
        graph_filename: str | None,
        schema_filename: str | None,
        graph_states: list[GraphState] | GraphState | None,
    ) -> tuple[bool, bool]:
        has_loadable_selection = bool(_selected_source_ids(selected_source) or graph_filename)
        has_resettable_selection = bool(
            has_loadable_selection
            or schema_filename
            or _normalize_graph_states(graph_states)
        )
        return not has_loadable_selection, not has_resettable_selection

    @app.callback(
        Output("loaded-graph-state", "data"),
        Output("load-status", "children"),
        Output("kgx-release-dropdown", "value"),
        Output("upload-graph-metadata", "contents"),
        Output("upload-graph-metadata", "filename"),
        Output("upload-schema", "contents"),
        Output("upload-schema", "filename"),
        Input("load-selected-metadata", "n_clicks"),
        Input("reset-selection", "n_clicks"),
        Input("kgx-release-dropdown", "value"),
        State("upload-graph-metadata", "contents"),
        State("upload-graph-metadata", "filename"),
        State("upload-schema", "contents"),
        State("upload-schema", "filename"),
        State("session-id", "data"),
        State("loaded-graph-state", "data"),
    )
    def load_graph(
        load_clicks: int,
        reset_clicks: int,
        selected_source: str | list[str] | None,
        graph_contents: str | None,
        graph_filename: str | None,
        schema_contents: str | None,
        schema_filename: str | None,
        session_id: str | None,
        graph_states: list[GraphState] | GraphState | None,
    ) -> LoadGraphResult:
        del load_clicks, reset_clicks, schema_filename
        session_id = session_id or uuid4().hex
        trigger = callback_context.triggered_id
        if trigger is None:
            return _load_graph_result(graph_state=[])
        if trigger == "reset-selection":
            return _load_graph_result(
                graph_state=[],
                status="",
                kgx_value=[],
                upload_contents=None,
                upload_filename=None,
                schema_contents=None,
                schema_filename=None,
            )
        if trigger == "kgx-release-dropdown":
            return _load_graph_result(
                graph_state=_prune_unselected_kgx_states(graph_states, selected_source)
            )

        if trigger != "load-selected-metadata":
            return _load_graph_result(status="")

        try:
            selected_sources = _selected_source_ids(selected_source)
            if not selected_sources and not graph_contents:
                return _load_graph_result(status="")

            loaded_states = []
            for source_id in selected_sources:
                loaded_states.append(_load_kgx_graph(cache, kgx_client, session_id, source_id))

            if graph_contents:
                loaded_states.append(
                    _load_uploaded_graph(
                        cache,
                        session_id,
                        graph_contents,
                        graph_filename,
                        schema_contents,
                    )
                )

            if len(loaded_states) == 1:
                return _load_graph_result(
                    graph_state=loaded_states,
                    status=f"Loaded {loaded_states[0]['label']}.",
                )
            return _load_graph_result(
                graph_state=loaded_states,
                status=f"Loaded {len(loaded_states)} graphs for comparison.",
            )
        except Exception as error:
            return _load_graph_result(status=f"Could not load graph metadata: {error}")

    @app.callback(
        Output("loaded-graphs-panel", "children"),
        Input("loaded-graph-state", "data"),
    )
    def render_loaded_graphs(
        graph_states: list[GraphState] | GraphState | None,
    ) -> Any:
        states = _normalize_graph_states(graph_states)
        if not states:
            return ""
        return _loaded_graphs_summary(states)

    @app.callback(
        Output("overview-panel", "children"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_overview(
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> Any:
        states = _normalize_graph_states(graph_states)
        if len(states) > 1:
            return _comparison_placeholder(states)
        graph_state = _single_graph_state(states)
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
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> Any:
        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
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
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> Any:
        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
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
                dcc.Graph(figure=node_category_bar(parsed.schema.nodes)),
            ],
        )

    @app.callback(
        Output("sankey-action-card", "style"),
        Input("loaded-graph-state", "data"),
    )
    def toggle_sankey_action(graph_states: list[GraphState] | GraphState | None) -> dict[str, str]:
        return {} if len(_normalize_graph_states(graph_states)) == 1 else {"display": "none"}

    @app.callback(
        Output("sankey-panel-body", "children"),
        Output("show-sankey", "disabled"),
        Input("show-sankey", "n_clicks"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_sankey_panel(
        show_clicks: int | None,
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[Any, bool]:
        if callback_context.triggered_id != "show-sankey" or not show_clicks:
            return "", False

        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return "", False
        parsed = _ensure_schema_loaded(cache, kgx_client, session_id, graph_state, parsed)
        if parsed.schema is None:
            return (
                html.Div(
                    className="empty-inline",
                    children=[
                        html.H4("Sankey unavailable"),
                        html.P(
                            "Schema metadata is required for the Sankey diagram, but it could "
                            "not be loaded for this graph."
                        ),
                    ],
                ),
                False,
            )
        return (
            dcc.Graph(
                figure=predicate_sankey(parsed.schema.edges, top_n=None),
                className="inline-sankey-graph",
                config={"responsive": True},
            ),
            True,
        )


def _load_graph_result(
    graph_state: object = no_update,
    status: object = no_update,
    kgx_value: object = no_update,
    upload_contents: object = no_update,
    upload_filename: object = no_update,
    schema_contents: object = no_update,
    schema_filename: object = no_update,
) -> LoadGraphResult:
    return (
        graph_state,
        status,
        kgx_value,
        upload_contents,
        upload_filename,
        schema_contents,
        schema_filename,
    )


def _load_kgx_graph(
    cache: MetadataCache,
    kgx_client: KgxStorageClient,
    session_id: str,
    source_id: str,
) -> GraphState:
    release = kgx_client.release_for_source(source_id)
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
    return state


def _load_uploaded_graph(
    cache: MetadataCache,
    session_id: str,
    graph_contents: str,
    graph_filename: str | None,
    schema_contents: str | None,
) -> GraphState:
    graph_data = decode_dash_upload(graph_contents, context=graph_filename or "upload")
    schema_data = (
        decode_dash_upload(schema_contents, context="schema upload") if schema_contents else None
    )
    source = UploadedMetadata(
        graph_metadata=graph_data,
        schema=schema_data,
        filename=graph_filename or "uploaded graph-metadata.json",
    )
    parsed = parse_graph_metadata(source.load_graph_metadata(), schema_data=schema_data)
    upload_cache_key = f"{source.source_key}:{uuid4().hex}"
    state = _cache_graph(cache, session_id, upload_cache_key, parsed)
    state.update({"kind": "upload", "label": source.label})
    return state


def _cache_graph(
    cache: MetadataCache,
    session_id: str,
    cache_key: str,
    parsed: ParsedGraphMetadata,
) -> GraphState:
    cache.set(session_id, cache_key, parsed)
    return {"cache_key": cache_key}


def _selected_source_ids(selected_source: str | list[str] | None) -> list[str]:
    if isinstance(selected_source, str):
        return [selected_source]
    if isinstance(selected_source, list):
        return [source_id for source_id in selected_source if isinstance(source_id, str)]
    return []


def _normalize_graph_states(
    graph_states: list[GraphState] | GraphState | None,
) -> list[GraphState]:
    if isinstance(graph_states, dict):
        return [graph_states] if isinstance(graph_states.get("cache_key"), str) else []
    if not isinstance(graph_states, list):
        return []
    return [
        state
        for state in graph_states
        if isinstance(state, dict) and isinstance(state.get("cache_key"), str)
    ]


def _single_graph_state(graph_states: list[GraphState]) -> GraphState | None:
    return graph_states[0] if len(graph_states) == 1 else None


def _prune_unselected_kgx_states(
    graph_states: list[GraphState] | GraphState | None,
    selected_source: str | list[str] | None,
) -> list[GraphState]:
    selected_sources = set(_selected_source_ids(selected_source))
    pruned: list[GraphState] = []
    for state in _normalize_graph_states(graph_states):
        if state.get("kind") != "kgx" or state.get("source_id") in selected_sources:
            pruned.append(state)
    return pruned


def _get_cached_graph(
    cache: MetadataCache,
    session_id: str | None,
    graph_state: GraphState | None,
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
    graph_state: GraphState | None,
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


def _loaded_graphs_summary(graph_states: list[GraphState]) -> html.Div:
    return html.Div(
        className="content-card selection-summary",
        children=[
            html.Div(
                className="section-heading-row",
                children=[
                    html.Div(
                        children=[
                            html.P("Active selection", className="eyebrow"),
                            html.H3(_mode_label(len(graph_states))),                            
                        ]
                    ),
                ],
            ),
            html.Div(
                className="graph-chip-row",
                children=[_graph_chip(state) for state in graph_states],
            ),
        ],
    )


def _graph_chip(graph_state: GraphState) -> html.Div:
    return html.Div(
        className="graph-chip",
        children=[
            html.Strong(_graph_label(graph_state)),
            html.Span(_graph_metadata_line(graph_state)),
        ],
    )


def _comparison_placeholder(graph_states: list[GraphState]) -> html.Div:
    return html.Div(
        className="content-card comparison-placeholder",
        children=[
            html.P("Graph Comparison", className="eyebrow"),
            html.H2("Graph comparison visualizations"),
            html.P(
                "To be implemented"
            ),
            html.Div(
                className="graph-chip-row",
                children=[_graph_chip(state) for state in graph_states],
            ),
        ],
    )


def _empty_state() -> html.Div:
    return html.Div(
        className="content-card empty-state",
        children=[
            html.H3("No graph loaded"),
            html.P(
                "Select one graph to inspect its metadata, or load two or more graphs to "
                "prepare a comparison."
            ),
        ],
    )


def _mode_label(selection_count: int) -> str:
    if selection_count == 1:
        return "Single graph selected"
    return f"{selection_count} graphs selected"


def _graph_label(graph_state: GraphState) -> str:
    label = graph_state.get("label")
    return label if isinstance(label, str) and label else "Unnamed graph"


def _graph_metadata_line(graph_state: GraphState) -> str:
    kind = graph_state.get("kind")
    if kind == "kgx":
        source_id = graph_state.get("source_id")
        release_version = graph_state.get("release_version")
        if isinstance(source_id, str) and isinstance(release_version, str):
            return f"KGX storage - {source_id} - {release_version}"
        return "KGX storage"
    if kind == "upload":
        return "Uploaded metadata"
    return "Loaded metadata"


def _overview(parsed: ParsedGraphMetadata) -> html.Div:
    return html.Div(
        className="content-card overview-card",
        children=[
            html.Div(
                className="overview-heading",
                children=[
                    html.H2(
                        [
                            parsed.name or "Unnamed graph",
                            " ",
                            html.Span(
                                _schema_badge_label(parsed),
                                className="schema-badge",
                            ),
                        ]
                    ),
                    html.P(
                        parsed.description or "No graph description provided.",
                        className="overview-description",
                    ),
                ],
            ),
            html.Div(
                className="overview-info-grid",
                children=[
                    html.Div(
                        className="overview-key-values",
                        children=[
                            _overview_value("Nodes", _format_count(parsed.total_node_count)),
                            _overview_value("Edges", _format_count(parsed.total_edge_count)),
                            _overview_value("Biolink", parsed.biolink_version or "Unknown"),
                            _overview_value("Babel", parsed.babel_version or "Unknown"),
                            _overview_value(
                                "Data sources",
                                _format_count(len(parsed.knowledge_sources)),
                            ),
                            _overview_value("Subgraphs", _format_count(len(parsed.subgraphs))),
                        ],
                    ),
                    _definition_list(
                        {
                            "Release version": parsed.release_version,
                            "Date created": parsed.date_created,
                            "Date modified": parsed.date_modified,
                            "License": parsed.license,
                        }
                    ),
                ],
            ),
        ],
    )


def _schema_badge_label(parsed: ParsedGraphMetadata) -> str:
    return f"{parsed.schema_reference.kind.upper()} SCHEMA"


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


def _overview_value(label: str, value: str) -> html.Div:
    return html.Div(
        className="overview-value",
        children=[
            html.P(label, className="overview-value-label"),
            html.Strong(value),
        ],
    )


def _definition_list(values: dict[str, str]) -> html.Dl:
    children: list[Any] = []
    for label, value in values.items():
        children.extend([html.Dt(label), html.Dd(value or "Unknown")])
    return html.Dl(className="definition-grid", children=children)


def _format_count(value: int | None) -> str:
    return "Unknown" if value is None else f"{value:,}"
