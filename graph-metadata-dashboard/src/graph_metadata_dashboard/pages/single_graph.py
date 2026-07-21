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
from graph_metadata_dashboard.parsers.models import EdgeTriple, ParsedGraphMetadata
from graph_metadata_dashboard.viz.figures import (
    knowledge_source_predicate_sankey,
    node_category_bar,
    predicate_sankey,
)

GraphState = dict[str, Any]
LoadGraphResult = tuple[object, object, object, object, object, object, object]
ALL_SUBJECT_CATEGORIES_VALUE = "__all_categories__"


def layout() -> html.Div:
    return html.Div(
        children=[
            dcc.Store(id="loaded-graph-state", storage_type="session"),
            dcc.Store(id="source-predicate-sankey-visible"),
            dcc.Store(id="subject-sankey-visible"),
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
                            html.H3("Predicate / Edge Composition"),
                            html.P(
                                "Sankey charts are loaded on request because merged graphs can "
                                "contain many source, predicate, and category combinations.",
                                className="status-line",
                            ),
                            html.Div(
                                className="sankey-control-grid",
                                children=[
                                    html.Div(
                                        className="sankey-control-block",
                                        children=[
                                            html.H4("Knowledge Source to Predicate"),
                                            html.P(
                                                "A two-column orientation chart using "
                                                "pre-aggregated schema summary counts.",
                                                className="status-line",
                                            ),
                                            html.Button(
                                                "Show source-predicate Sankey",
                                                id="show-source-predicate-sankey",
                                                n_clicks=0,
                                                type="button",
                                                className="button button-secondary",
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="sankey-control-block",
                                        children=[
                                            html.H4("Subject Category to Predicate to Object"),
                                            html.P(
                                                "A category-scoped three-column chart. Choose "
                                                "one subject category, or explicitly request "
                                                "the all-category top-40 view.",
                                                className="status-line",
                                            ),
                                            dcc.Dropdown(
                                                id="sankey-subject-category-dropdown",
                                                placeholder="Select subject category",
                                                clearable=False,
                                            ),
                                            html.Button(
                                                "Show category Sankey",
                                                id="show-sankey",
                                                n_clicks=0,
                                                type="button",
                                                className="button button-secondary sankey-button",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            dcc.Loading(
                                html.Div(
                                    id="source-predicate-panel-body",
                                    className="sankey-scroll-panel",
                                ),
                                parent_className="sankey-loading",
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
        Output("sankey-subject-category-dropdown", "options"),
        Output("sankey-subject-category-dropdown", "value"),
        Output("sankey-subject-category-dropdown", "disabled"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def configure_sankey_subject_dropdown(
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[list[dict[str, str]], str | None, bool]:
        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return [], None, True
        parsed = _ensure_schema_loaded(cache, kgx_client, session_id, graph_state, parsed)
        if parsed.schema is None or not parsed.schema.edges:
            return [], None, True

        options = _subject_category_options(parsed.schema.edges)
        default_value = options[1]["value"] if len(options) > 1 else ALL_SUBJECT_CATEGORIES_VALUE
        return options, default_value, False

    @app.callback(
        Output("source-predicate-sankey-visible", "data"),
        Output("source-predicate-panel-body", "children"),
        Output("show-source-predicate-sankey", "disabled"),
        Output("show-source-predicate-sankey", "children"),
        Input("show-source-predicate-sankey", "n_clicks"),
        Input("loaded-graph-state", "data"),
        State("source-predicate-sankey-visible", "data"),
        State("session-id", "data"),
    )
    def render_source_predicate_sankey_panel(
        show_clicks: int | None,
        graph_states: list[GraphState] | GraphState | None,
        visible: bool | None,
        session_id: str | None,
    ) -> tuple[bool, Any, bool, str]:
        if callback_context.triggered_id == "loaded-graph-state":
            return False, "", False, "Show source-predicate Sankey"
        visible = bool(visible)
        if callback_context.triggered_id == "show-source-predicate-sankey" and show_clicks:
            visible = not visible
        if not visible:
            return False, "", False, "Show source-predicate Sankey"

        parsed = _single_cached_graph_with_schema(cache, kgx_client, session_id, graph_states)
        if parsed is None or parsed.schema is None:
            return visible, _sankey_unavailable_message(), False, "Hide source-predicate Sankey"
        if not parsed.schema.source_predicate_counts:
            return (
                visible,
                _source_predicate_unavailable_message(),
                False,
                "Hide source-predicate Sankey",
            )
        return (
            True,
            dcc.Graph(
                figure=knowledge_source_predicate_sankey(parsed.schema.source_predicate_counts),
                className="inline-sankey-graph",
                config={"responsive": True},
            ),
            False,
            "Hide source-predicate Sankey",
        )

    @app.callback(
        Output("subject-sankey-visible", "data"),
        Output("sankey-panel-body", "children"),
        Output("show-sankey", "disabled"),
        Input("show-sankey", "n_clicks"),
        Input("sankey-subject-category-dropdown", "value"),
        Input("loaded-graph-state", "data"),
        State("subject-sankey-visible", "data"),
        State("session-id", "data"),
    )
    def render_sankey_panel(
        show_clicks: int | None,
        selected_subject: str | None,
        graph_states: list[GraphState] | GraphState | None,
        visible: bool | None,
        session_id: str | None,
    ) -> tuple[bool, Any, bool]:
        if callback_context.triggered_id == "loaded-graph-state":
            return False, "", False
        visible = bool(visible)
        if callback_context.triggered_id == "show-sankey" and show_clicks:
            visible = True
        if not visible:
            return False, "", False

        parsed = _single_cached_graph_with_schema(cache, kgx_client, session_id, graph_states)
        if parsed is None or parsed.schema is None:
            return visible, _sankey_unavailable_message(), True
        subject_filter = (
            None
            if selected_subject in {None, ALL_SUBJECT_CATEGORIES_VALUE}
            else selected_subject
        )
        top_n = 40
        if subject_filter is None and selected_subject != ALL_SUBJECT_CATEGORIES_VALUE:
            return visible, "", False
        if not parsed.schema.edges:
            return (
                visible,
                html.Div(
                    className="empty-inline",
                    children=[html.P("No schema edge triples are available for this graph.")],
                ),
                True,
            )
        return (
            True,
            dcc.Graph(
                figure=predicate_sankey(
                    parsed.schema.edges,
                    top_n=top_n,
                    subject_filter=subject_filter,
                ),
                className="inline-sankey-graph",
                config={"responsive": True},
            ),
            False,
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


def _single_cached_graph_with_schema(
    cache: MetadataCache,
    kgx_client: KgxStorageClient,
    session_id: str | None,
    graph_states: list[GraphState] | GraphState | None,
) -> ParsedGraphMetadata | None:
    graph_state = _single_graph_state(_normalize_graph_states(graph_states))
    parsed = _get_cached_graph(cache, session_id, graph_state)
    if parsed is None:
        return None
    return _ensure_schema_loaded(cache, kgx_client, session_id, graph_state, parsed)


def _subject_category_options(edges: tuple[EdgeTriple, ...]) -> list[dict[str, str]]:
    totals: dict[str, int] = {}
    for edge in edges:
        label = _edge_subject_label(edge)
        totals[label] = totals.get(label, 0) + edge.count
    ordered_subjects = [
        subject
        for subject, _ in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]
    return [
        {
            "label": "All categories (top 40 by volume)",
            "value": ALL_SUBJECT_CATEGORIES_VALUE,
        },
        *[{"label": subject, "value": subject} for subject in ordered_subjects],
    ]


def _edge_subject_label(edge: EdgeTriple) -> str:
    return ", ".join(edge.subject_category) or "Other"


def _sankey_unavailable_message() -> html.Div:
    return html.Div(
        className="empty-inline",
        children=[
            html.H4("Sankey unavailable"),
            html.P(
                "Schema metadata is required for this Sankey chart, but it could not be "
                "loaded for this graph."
            ),
        ],
    )


def _source_predicate_unavailable_message() -> html.Div:
    return html.Div(
        className="empty-inline",
        children=[
            html.H4("Source-predicate Sankey unavailable"),
            html.P(
                "This graph's schema metadata does not include "
                "predicates_by_knowledge_source summary data."
            ),
        ],
    )


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
