from __future__ import annotations

from dataclasses import replace
from typing import Any
from urllib.parse import urlparse
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
from graph_metadata_dashboard.components.comparison import comparison_dashboard
from graph_metadata_dashboard.components.single_graph import (
    provenance_contribution,
    upload_selection_status,
    url_selection_status,
)
from graph_metadata_dashboard.loaders.kgx_storage import (
    KgxRelease,
    KgxStorageClient,
    KgxStorageRelease,
)
from graph_metadata_dashboard.loaders.uploaded import UploadedMetadata, decode_dash_upload
from graph_metadata_dashboard.loaders.url import UrlMetadata, UrlMetadataClient
from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata, parse_schema
from graph_metadata_dashboard.parsers.models import (
    EdgeTriple,
    KnowledgeSourcePredicateCount,
    ParsedGraphMetadata,
)
from graph_metadata_dashboard.viz.figures import (
    filter_predicate_sankey_edges,
    filter_source_predicate_counts,
    knowledge_source_predicate_sankey,
    node_category_bar,
    predicate_sankey,
    qualifier_counts_for_edges,
    selected_predicate_sankey_edges,
    subject_object_category_pair_bar,
)

GraphState = dict[str, Any]
LoadGraphResult = tuple[object, object, object, object, object, object, object, object, object]
ALL_SUBJECT_CATEGORIES_VALUE = "__all_categories__"
ALL_CATEGORY_SANKEY_TOP_N = 40
SUBJECT_CATEGORY_SANKEY_TOP_N = 200
SOURCE_PREDICATE_SANKEY_TOP_N = 100


def layout() -> html.Div:
    return html.Div(
        children=[
            dcc.Store(id="loaded-graph-state", storage_type="session"),
            dcc.Store(id="source-predicate-sankey-visible"),
            dcc.Store(id="subject-sankey-visible"),
            dcc.Store(id="category-pair-summary-visible"),
            html.Section(
                className="intro-card",
                children=[
                    html.Div(
                        [
                            html.P(
                                "Select one or more graph releases from the Biomedical Data "
                                "Translator KGX storage, paste a trusted metadata URL, or upload "
                                "local metadata JSON. Select a single graph to summarize and "
                                "visualize its metadata, or select multiple graphs to compare "
                                "their metadata."
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
                                "Choose from KGX releases, trusted URLs, local uploads, or combine "
                                "sources before adding selected metadata.",
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
                                    html.H4("Metadata URL"),
                                    html.P(
                                        "Input a URL to add to selection; input another to add "
                                        "more to selection if needed.",
                                        className="selector-help",
                                    ),
                                    dcc.Input(
                                        id="graph-metadata-url",
                                        className="metadata-url-input",
                                        type="url",
                                        debounce=True,
                                        placeholder="https://.../graph-metadata.json",
                                    ),
                                    dcc.Input(
                                        id="schema-url",
                                        className="metadata-url-input secondary",
                                        type="url",
                                        debounce=True,
                                        placeholder="Optional https://.../schema.json",
                                    ),
                                    html.Div(
                                        id="url-selection-status",
                                        className="url-selection",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="selector-subsection",
                                children=[
                                    html.H4("Upload Metadata"),
                                    html.P(
                                        "Upload one metadata/schema pair at a time to add to "
                                        "selection; the files clear after adding so another "
                                        "upload can be added.",
                                        className="selector-help",
                                    ),
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
                                "Add selected metadata",
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
                            html.Div(
                                id="load-status",
                                className="status-line load-status-inline",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="results-region",
                children=[
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
                                            html.H3("Predicate Composition"),
                                            html.P(
                                                "View this graph's predicates from two "
                                                "perspectives. One shows which knowledge "
                                                "sources contribute to each predicate type. "
                                                "The other shows which entity types those "
                                                "predicates connect. Click a Sankey node "
                                                "to select it with its connected flows "
                                                "highlighted; click it again to deselect "
                                                "it and reset the view.",
                                                className="status-line",
                                            ),
                                        ],
                                    ),
                                    html.Button(
                                        "Show subject-object category pairs",
                                        id="show-category-pair-summary",
                                        n_clicks=0,
                                        type="button",
                                        className=(
                                            "button button-secondary "
                                            "category-pair-toggle-button"
                                        ),
                                    ),
                                ],
                            ),
                            html.Div(
                                id="category-pair-summary-panel",
                                hidden=True,
                            ),
                            html.Div(
                                className="sankey-control-grid",
                                children=[
                                    html.Div(
                                        className="sankey-control-block",
                                        children=[
                                            html.H4("Knowledge Source to Predicate"),
                                            html.P(
                                                "A two-column Sankey chart showing which knowledge "
                                                "sources contribute to each predicate type. Use "
                                                "the filters and slider to focus on selected "
                                                "sources, predicates, or the highest-count flows.",
                                                className="status-line",
                                            ),
                                            html.Div(
                                                className="sankey-filter-grid",
                                                children=[
                                                    html.Div(
                                                        className="sankey-filter-field",
                                                        children=[
                                                            html.Label(
                                                                "Source",
                                                                htmlFor=(
                                                                    "source-predicate-source-filter"
                                                                ),
                                                            ),
                                                            dcc.Dropdown(
                                                                id=(
                                                                    "source-predicate-source-filter"
                                                                ),
                                                                multi=True,
                                                                placeholder="All sources",
                                                            ),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        className="sankey-filter-field",
                                                        children=[
                                                            html.Label(
                                                                "Predicate",
                                                                htmlFor=(
                                                                    "source-predicate-predicate-filter"
                                                                ),
                                                            ),
                                                            dcc.Dropdown(
                                                                id=(
                                                                    "source-predicate-predicate-filter"
                                                                ),
                                                                multi=True,
                                                                placeholder="All predicates",
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            ),
                                            html.Div(
                                                className="sankey-slider-field",
                                                children=[
                                                    html.Label(
                                                        "Top sources and predicates",
                                                        htmlFor="source-predicate-top-n-slider",
                                                    ),
                                                    dcc.Slider(
                                                        id="source-predicate-top-n-slider",
                                                        min=1,
                                                        max=SOURCE_PREDICATE_SANKEY_TOP_N,
                                                        step=1,
                                                        value=SOURCE_PREDICATE_SANKEY_TOP_N,
                                                        updatemode="mouseup",
                                                        marks=_sankey_slider_marks(
                                                            SOURCE_PREDICATE_SANKEY_TOP_N,
                                                            defaults=(
                                                                SOURCE_PREDICATE_SANKEY_TOP_N,
                                                            ),
                                                        ),
                                                        tooltip={
                                                            "placement": "bottom",
                                                            "always_visible": False,
                                                        },
                                                    ),
                                                ],
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
                                            html.H4("Subject to Predicate to Object"),
                                            html.P(
                                                "A subject category-scoped three-column chart. "
                                                "Choose one subject category to view "
                                                "relationship triples within that selected "
                                                "subject category, or select "
                                                '"All categories"  to view relationship '
                                                "triples across the whole graph. Refine by source, "
                                                "predicate, and object category, then use the "
                                                "slider to control how many highest-count triples "
                                                "are shown.",
                                                className="status-line",
                                            ),
                                            dcc.Dropdown(
                                                id="sankey-subject-category-dropdown",
                                                placeholder="Select subject category",
                                                clearable=False,
                                            ),
                                            html.Div(
                                                className=(
                                                    "sankey-filter-grid "
                                                    "sankey-filter-grid-compact"
                                                ),
                                                children=[
                                                    html.Div(
                                                        className="sankey-filter-field",
                                                        children=[
                                                            html.Label(
                                                                "Source",
                                                                htmlFor="sankey-source-filter",
                                                            ),
                                                            dcc.Dropdown(
                                                                id="sankey-source-filter",
                                                                multi=True,
                                                                optionHeight=58,
                                                                placeholder="All sources",
                                                            ),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        className="sankey-filter-field",
                                                        children=[
                                                            html.Label(
                                                                "Predicate",
                                                                htmlFor="sankey-predicate-filter",
                                                            ),
                                                            dcc.Dropdown(
                                                                id="sankey-predicate-filter",
                                                                multi=True,
                                                                optionHeight=58,
                                                                placeholder="All predicates",
                                                            ),
                                                        ],
                                                    ),
                                                    html.Div(
                                                        className="sankey-filter-field",
                                                        children=[
                                                            html.Label(
                                                                "Object category",
                                                                htmlFor="sankey-object-category-filter",
                                                            ),
                                                            dcc.Dropdown(
                                                                id="sankey-object-category-filter",
                                                                multi=True,
                                                                optionHeight=58,
                                                                placeholder="All object categories",
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            ),
                                            html.Div(
                                                className="sankey-slider-field",
                                                children=[
                                                    html.Label(
                                                        "Top relationship triples",
                                                        htmlFor="sankey-top-n-slider",
                                                    ),
                                                    dcc.Slider(
                                                        id="sankey-top-n-slider",
                                                        min=1,
                                                        max=SUBJECT_CATEGORY_SANKEY_TOP_N,
                                                        step=1,
                                                        value=SUBJECT_CATEGORY_SANKEY_TOP_N,
                                                        updatemode="mouseup",
                                                        marks=_sankey_slider_marks(
                                                            SUBJECT_CATEGORY_SANKEY_TOP_N,
                                                            defaults=(
                                                                ALL_CATEGORY_SANKEY_TOP_N,
                                                                SUBJECT_CATEGORY_SANKEY_TOP_N,
                                                            ),
                                                        ),
                                                        tooltip={
                                                            "placement": "bottom",
                                                            "always_visible": False,
                                                        },
                                                    ),
                                                ],
                                            ),
                                            html.Button(
                                                "Show subject-predicate-object Sankey",
                                                id="show-sankey",
                                                n_clicks=0,
                                                type="button",
                                                className="button button-secondary sankey-button",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                id="source-predicate-panel-body",
                                className="sankey-scroll-panel",
                                hidden=True,
                            ),
                            html.Div(
                                id="sankey-panel-body",
                                className="sankey-scroll-panel",
                                hidden=True,
                            ),
                        ],
                    ),
                ],
            ),
        ]
    )


register_page(__name__, path="/", name="Dashboard")


def register_callbacks(
    app: Dash,
    *,
    cache: MetadataCache,
    kgx_client: KgxStorageClient,
    url_client: UrlMetadataClient,
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
        Output("url-selection-status", "children"),
        Input("graph-metadata-url", "value"),
        Input("schema-url", "value"),
    )
    def render_url_selection(
        graph_url: str | None,
        schema_url: str | None,
    ) -> list[html.P]:
        return url_selection_status(graph_url, schema_url)

    @app.callback(
        Output("load-selected-metadata", "disabled"),
        Output("reset-selection", "disabled"),
        Output("kgx-release-dropdown", "disabled"),
        Output("graph-metadata-url", "disabled"),
        Output("schema-url", "disabled"),
        Output("upload-graph-metadata", "disabled"),
        Output("upload-schema", "disabled"),
        Input("kgx-release-dropdown", "value"),
        Input("upload-graph-metadata", "filename"),
        Input("upload-schema", "filename"),
        Input("graph-metadata-url", "value"),
        Input("schema-url", "value"),
        Input("loaded-graph-state", "data"),
    )
    def toggle_reset_selection(
        selected_source: str | list[str] | None,
        graph_filename: str | None,
        schema_filename: str | None,
        graph_url: str | None,
        schema_url: str | None,
        graph_states: list[GraphState] | GraphState | None,
    ) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
        return _selection_control_state(
            selected_source=selected_source,
            graph_filename=graph_filename,
            schema_filename=schema_filename,
            graph_url=graph_url,
            schema_url=schema_url,
            graph_states=graph_states,
        )

    @app.callback(
        Output("loaded-graph-state", "data"),
        Output("load-status", "children"),
        Output("kgx-release-dropdown", "value"),
        Output("upload-graph-metadata", "contents"),
        Output("upload-graph-metadata", "filename"),
        Output("upload-schema", "contents"),
        Output("upload-schema", "filename"),
        Output("graph-metadata-url", "value"),
        Output("schema-url", "value"),
        Input("load-selected-metadata", "n_clicks"),
        Input("reset-selection", "n_clicks"),
        Input("kgx-release-dropdown", "value"),
        Input("graph-metadata-url", "value"),
        State("upload-graph-metadata", "contents"),
        State("upload-graph-metadata", "filename"),
        State("upload-schema", "contents"),
        State("upload-schema", "filename"),
        State("schema-url", "value"),
        State("session-id", "data"),
        State("loaded-graph-state", "data"),
    )
    def load_graph(
        load_clicks: int,
        reset_clicks: int,
        selected_source: str | list[str] | None,
        graph_url: str | None,
        graph_contents: str | None,
        graph_filename: str | None,
        schema_contents: str | None,
        schema_filename: str | None,
        schema_url: str | None,
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
                graph_url="",
                schema_url="",
            )
        if trigger == "kgx-release-dropdown":
            return _load_graph_result(
                graph_state=_normalize_graph_states(graph_states)
            )
        if trigger == "graph-metadata-url":
            return _load_graph_result(
                graph_state=_normalize_graph_states(graph_states)
            )

        if trigger != "load-selected-metadata":
            return _load_graph_result(status="")

        try:
            selected_sources = _selected_source_ids(selected_source)
            selected_graph_url = _clean_url(graph_url)
            selected_schema_url = _clean_url(schema_url)
            if not selected_sources and not graph_contents and not selected_graph_url:
                return _load_graph_result(status="")

            existing_states = _normalize_graph_states(graph_states)
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

            if selected_graph_url:
                loaded_states.append(
                    _load_url_graph(
                        cache,
                        url_client,
                        session_id,
                        selected_graph_url,
                        selected_schema_url,
                    )
                )

            merged_states = _merge_graph_states(existing_states, loaded_states)
            reset_one_time_inputs = {
                "upload_contents": None,
                "upload_filename": None,
                "schema_contents": None,
                "schema_filename": None,
                "graph_url": "",
                "schema_url": "",
            }

            if len(loaded_states) == 1:
                return _load_graph_result(
                    graph_state=merged_states,
                    status=f"Loaded {loaded_states[0]['label']}.",
                    **reset_one_time_inputs,
                )
            return _load_graph_result(
                graph_state=merged_states,
                status=f"Loaded {len(loaded_states)} graphs.",
                **reset_one_time_inputs,
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
        Input("comparison-baseline-selector", "value"),
        State("session-id", "data"),
    )
    def render_overview(
        graph_states: list[GraphState] | GraphState | None,
        baseline_cache_key: str | None,
        session_id: str | None,
    ) -> Any:
        states = _normalize_graph_states(graph_states)
        if len(states) > 1:
            return _comparison_dashboard(
                cache,
                kgx_client,
                url_client,
                session_id,
                states,
                baseline_cache_key,
            )
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
        parsed = _ensure_schema_loaded(
            cache, kgx_client, url_client, session_id, graph_state, parsed
        )
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
        Output("category-pair-summary-visible", "data"),
        Output("show-category-pair-summary", "children"),
        Input("show-category-pair-summary", "n_clicks"),
        Input("loaded-graph-state", "data"),
        State("category-pair-summary-visible", "data"),
    )
    def toggle_category_pair_summary(
        show_clicks: int | None,
        graph_states: list[GraphState] | GraphState | None,
        visible: bool | None,
    ) -> tuple[bool, str]:
        del graph_states
        if callback_context.triggered_id == "loaded-graph-state":
            return False, "Show subject-object category pairs"
        visible = bool(visible)
        if callback_context.triggered_id == "show-category-pair-summary" and show_clicks:
            visible = not visible
        if not visible:
            return False, "Show subject-object category pairs"
        return True, "Hide subject-object category pairs"

    @app.callback(
        Output("category-pair-summary-panel", "hidden"),
        Output("category-pair-summary-panel", "children"),
        Input("category-pair-summary-visible", "data"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_category_pair_summary(
        visible: bool | None,
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[bool, Any]:
        if not visible:
            return True, ""
        parsed = _single_cached_graph_with_schema(
            cache, kgx_client, url_client, session_id, graph_states
        )
        if parsed is None or parsed.schema is None:
            return False, _sankey_unavailable_message()
        if not parsed.schema.edges:
            return False, html.Div(
                className="empty-inline",
                children=[
                    html.P("No schema edge triples are available for this graph."),
                ],
            )
        return False, html.Div(
            className="category-pair-summary",
            children=[
                html.H4("Subject-Object Category Pairs"),
                dcc.Graph(figure=subject_object_category_pair_bar(parsed.schema.edges)),
            ],
        )

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
        parsed = _ensure_schema_loaded(
            cache, kgx_client, url_client, session_id, graph_state, parsed
        )
        if parsed.schema is None or not parsed.schema.edges:
            return [], None, True

        options = _subject_category_options(parsed.schema.edges)
        default_value = options[1]["value"] if len(options) > 1 else ALL_SUBJECT_CATEGORIES_VALUE
        return options, default_value, False

    @app.callback(
        Output("source-predicate-source-filter", "options"),
        Output("source-predicate-source-filter", "value"),
        Output("source-predicate-source-filter", "disabled"),
        Output("source-predicate-predicate-filter", "options"),
        Output("source-predicate-predicate-filter", "value"),
        Output("source-predicate-predicate-filter", "disabled"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def configure_source_predicate_filters(
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[
        list[dict[str, str]],
        list[str],
        bool,
        list[dict[str, str]],
        list[str],
        bool,
    ]:
        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return [], [], True, [], [], True
        parsed = _ensure_schema_loaded(
            cache, kgx_client, url_client, session_id, graph_state, parsed
        )
        if parsed.schema is None or not parsed.schema.source_predicate_counts:
            return [], [], True, [], [], True
        source_options, predicate_options = _source_predicate_filter_options(
            parsed.schema.source_predicate_counts
        )
        return source_options, [], False, predicate_options, [], False

    @app.callback(
        Output("sankey-source-filter", "options"),
        Output("sankey-source-filter", "value"),
        Output("sankey-source-filter", "disabled"),
        Output("sankey-predicate-filter", "options"),
        Output("sankey-predicate-filter", "value"),
        Output("sankey-predicate-filter", "disabled"),
        Output("sankey-object-category-filter", "options"),
        Output("sankey-object-category-filter", "value"),
        Output("sankey-object-category-filter", "disabled"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def configure_predicate_sankey_filters(
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[
        list[dict[str, str]],
        list[str],
        bool,
        list[dict[str, str]],
        list[str],
        bool,
        list[dict[str, str]],
        list[str],
        bool,
    ]:
        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return [], [], True, [], [], True, [], [], True
        parsed = _ensure_schema_loaded(
            cache, kgx_client, url_client, session_id, graph_state, parsed
        )
        if parsed.schema is None or not parsed.schema.edges:
            return [], [], True, [], [], True, [], [], True
        source_options, predicate_options, object_options = _predicate_sankey_filter_options(
            parsed.schema.edges
        )
        return source_options, [], False, predicate_options, [], False, object_options, [], False

    @app.callback(
        Output("sankey-top-n-slider", "value"),
        Output("sankey-top-n-slider", "max"),
        Output("sankey-top-n-slider", "marks"),
        Input("sankey-subject-category-dropdown", "value"),
        Input("sankey-source-filter", "value"),
        Input("sankey-predicate-filter", "value"),
        Input("sankey-object-category-filter", "value"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def configure_sankey_top_n_slider(
        selected_subject: str | None,
        selected_sources: list[str] | str | None,
        selected_predicates: list[str] | str | None,
        selected_objects: list[str] | str | None,
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[int, int, dict[int, str]]:
        subject_filter = (
            None
            if selected_subject in {None, ALL_SUBJECT_CATEGORIES_VALUE}
            else selected_subject
        )
        default_top_n = _predicate_sankey_top_n(subject_filter)
        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return _sankey_slider_config(default_top_n, default_top_n)
        parsed = _ensure_schema_loaded(
            cache, kgx_client, url_client, session_id, graph_state, parsed
        )
        if parsed.schema is None:
            return _sankey_slider_config(default_top_n, default_top_n)
        filtered_edges = filter_predicate_sankey_edges(
            parsed.schema.edges,
            subject_filter=subject_filter,
            source_filters=_dropdown_values(selected_sources),
            predicate_filters=_dropdown_values(selected_predicates),
            object_filters=_dropdown_values(selected_objects),
        )
        max_top_n = max(1, len(filtered_edges))
        return _sankey_slider_config(
            default_top_n,
            max_top_n,
            defaults=(ALL_CATEGORY_SANKEY_TOP_N, SUBJECT_CATEGORY_SANKEY_TOP_N),
        )

    @app.callback(
        Output("source-predicate-top-n-slider", "value"),
        Output("source-predicate-top-n-slider", "max"),
        Output("source-predicate-top-n-slider", "marks"),
        Input("source-predicate-source-filter", "value"),
        Input("source-predicate-predicate-filter", "value"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def configure_source_predicate_top_n_slider(
        selected_sources: list[str] | str | None,
        selected_predicates: list[str] | str | None,
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[int, int, dict[int, str]]:
        graph_state = _single_graph_state(_normalize_graph_states(graph_states))
        parsed = _get_cached_graph(cache, session_id, graph_state)
        if parsed is None:
            return _sankey_slider_config(
                SOURCE_PREDICATE_SANKEY_TOP_N,
                SOURCE_PREDICATE_SANKEY_TOP_N,
            )
        parsed = _ensure_schema_loaded(
            cache, kgx_client, url_client, session_id, graph_state, parsed
        )
        if parsed.schema is None:
            return _sankey_slider_config(
                SOURCE_PREDICATE_SANKEY_TOP_N,
                SOURCE_PREDICATE_SANKEY_TOP_N,
            )
        filtered_counts = filter_source_predicate_counts(
            parsed.schema.source_predicate_counts,
            source_filters=_dropdown_values(selected_sources),
            predicate_filters=_dropdown_values(selected_predicates),
        )
        max_top_n = _source_predicate_top_n_limit(filtered_counts)
        return _sankey_slider_config(
            SOURCE_PREDICATE_SANKEY_TOP_N,
            max_top_n,
            defaults=(SOURCE_PREDICATE_SANKEY_TOP_N,),
        )

    @app.callback(
        Output("source-predicate-sankey-visible", "data"),
        Output("show-source-predicate-sankey", "children"),
        Input("show-source-predicate-sankey", "n_clicks"),
        Input("loaded-graph-state", "data"),
        State("source-predicate-sankey-visible", "data"),
    )
    def toggle_source_predicate_sankey_panel(
        show_clicks: int | None,
        graph_states: list[GraphState] | GraphState | None,
        visible: bool | None,
    ) -> tuple[bool, str]:
        del graph_states
        if callback_context.triggered_id == "loaded-graph-state":
            return False, "Show source-predicate Sankey"
        visible = bool(visible)
        if callback_context.triggered_id == "show-source-predicate-sankey" and show_clicks:
            visible = not visible
        if not visible:
            return False, "Show source-predicate Sankey"
        return True, "Hide source-predicate Sankey"

    @app.callback(
        Output("source-predicate-panel-body", "hidden"),
        Output("source-predicate-panel-body", "children"),
        Input("source-predicate-sankey-visible", "data"),
        Input("source-predicate-source-filter", "value"),
        Input("source-predicate-predicate-filter", "value"),
        Input("source-predicate-top-n-slider", "value"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_source_predicate_sankey_panel(
        visible: bool | None,
        selected_sources: list[str] | str | None,
        selected_predicates: list[str] | str | None,
        top_n_value: int | float | None,
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[bool, Any]:
        if not visible:
            return True, ""
        parsed = _single_cached_graph_with_schema(
            cache, kgx_client, url_client, session_id, graph_states
        )
        if parsed is None or parsed.schema is None:
            return False, _sankey_unavailable_message()
        if not parsed.schema.source_predicate_counts:
            return False, _source_predicate_unavailable_message()
        source_filters = _dropdown_values(selected_sources)
        predicate_filters = _dropdown_values(selected_predicates)
        filtered_counts = filter_source_predicate_counts(
            parsed.schema.source_predicate_counts,
            source_filters=source_filters,
            predicate_filters=predicate_filters,
        )
        if not filtered_counts:
            return False, _empty_sankey_filter_message()
        qualifier_edges = filter_predicate_sankey_edges(
            parsed.schema.edges,
            source_filters=source_filters,
            predicate_filters=predicate_filters,
        )
        return (
            False,
            html.Div(
                children=[
                    _qualifier_context_summary(
                        qualifier_edges,
                        scope_label="displayed source-predicate flows",
                    ),
                    dcc.Graph(
                        id="source-predicate-sankey-graph",
                        figure=knowledge_source_predicate_sankey(
                            filtered_counts,
                            top_n_sources=_slider_top_n(
                                top_n_value,
                                default=SOURCE_PREDICATE_SANKEY_TOP_N,
                            ),
                            top_n_predicates=_slider_top_n(
                                top_n_value,
                                default=SOURCE_PREDICATE_SANKEY_TOP_N,
                            ),
                        ),
                        className="inline-sankey-graph",
                        config={"responsive": True},
                    ),
                ],
            ),
        )

    @app.callback(
        Output("subject-sankey-visible", "data"),
        Output("show-sankey", "children"),
        Input("show-sankey", "n_clicks"),
        Input("loaded-graph-state", "data"),
        State("subject-sankey-visible", "data"),
    )
    def toggle_subject_sankey_panel(
        show_clicks: int | None,
        graph_states: list[GraphState] | GraphState | None,
        visible: bool | None,
    ) -> tuple[bool, str]:
        del graph_states
        if callback_context.triggered_id == "loaded-graph-state":
            return False, "Show subject-predicate-object Sankey"
        visible = bool(visible)
        if callback_context.triggered_id == "show-sankey" and show_clicks:
            visible = not visible
        if not visible:
            return False, "Show subject-predicate-object Sankey"
        return True, "Hide subject-predicate-object Sankey"

    @app.callback(
        Output("sankey-panel-body", "hidden"),
        Output("sankey-panel-body", "children"),
        Output("show-sankey", "disabled"),
        Input("subject-sankey-visible", "data"),
        Input("sankey-subject-category-dropdown", "value"),
        Input("sankey-source-filter", "value"),
        Input("sankey-predicate-filter", "value"),
        Input("sankey-object-category-filter", "value"),
        Input("sankey-top-n-slider", "value"),
        Input("loaded-graph-state", "data"),
        State("session-id", "data"),
    )
    def render_sankey_panel(
        visible: bool | None,
        selected_subject: str | None,
        selected_sources: list[str] | str | None,
        selected_predicates: list[str] | str | None,
        selected_objects: list[str] | str | None,
        top_n_value: int | float | None,
        graph_states: list[GraphState] | GraphState | None,
        session_id: str | None,
    ) -> tuple[bool, Any, bool]:
        if not visible:
            return True, "", False

        parsed = _single_cached_graph_with_schema(
            cache, kgx_client, url_client, session_id, graph_states
        )
        if parsed is None or parsed.schema is None:
            return False, _sankey_unavailable_message(), True
        subject_filter = (
            None
            if selected_subject in {None, ALL_SUBJECT_CATEGORIES_VALUE}
            else selected_subject
        )
        top_n = _slider_top_n(
            top_n_value,
            default=_predicate_sankey_top_n(subject_filter),
        )
        if subject_filter is None and selected_subject != ALL_SUBJECT_CATEGORIES_VALUE:
            return True, "", False
        if not parsed.schema.edges:
            return (
                False,
                html.Div(
                    className="empty-inline",
                    children=[html.P("No schema edge triples are available for this graph.")],
                ),
                True,
            )
        source_filters = _dropdown_values(selected_sources)
        predicate_filters = _dropdown_values(selected_predicates)
        object_filters = _dropdown_values(selected_objects)
        selected_edges = selected_predicate_sankey_edges(
            parsed.schema.edges,
            top_n=top_n,
            subject_filter=subject_filter,
            source_filters=source_filters,
            predicate_filters=predicate_filters,
            object_filters=object_filters,
        )
        if not selected_edges:
            return False, _empty_sankey_filter_message(), False
        return (
            False,
            html.Div(
                children=[
                    _qualifier_context_summary(
                        selected_edges,
                        scope_label="displayed subject-predicate-object flows",
                    ),
                    dcc.Graph(
                        id="subject-predicate-object-sankey-graph",
                        figure=predicate_sankey(
                            parsed.schema.edges,
                            top_n=top_n,
                            subject_filter=subject_filter,
                            source_filters=source_filters,
                            predicate_filters=predicate_filters,
                            object_filters=object_filters,
                        ),
                        className="inline-sankey-graph",
                        config={"responsive": True},
                    ),
                ],
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
    graph_url: object = no_update,
    schema_url: object = no_update,
) -> LoadGraphResult:
    return (
        graph_state,
        status,
        kgx_value,
        upload_contents,
        upload_filename,
        schema_contents,
        schema_filename,
        graph_url,
        schema_url,
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
    state.update(
        {
            "kind": "upload",
            "label": parsed.name or source.label,
            "release_version": parsed.release_version,
        }
    )
    return state


def _load_url_graph(
    cache: MetadataCache,
    url_client: UrlMetadataClient,
    session_id: str,
    graph_url: str,
    schema_url: str | None,
) -> GraphState:
    source = UrlMetadata(
        client=url_client,
        graph_metadata_url=graph_url,
        schema_url=schema_url,
    )
    schema_data = source.load_schema() if schema_url else None
    parsed = parse_graph_metadata(source.load_graph_metadata(), schema_data=schema_data)
    state = _cache_graph(cache, session_id, source.source_key, parsed)
    state.update(
        {
            "kind": "url",
            "graph_url": graph_url,
            "schema_url": schema_url,
            "release_version": parsed.release_version,
            "label": parsed.name or source.label,
        }
    )
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


def _clean_url(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


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


def _merge_graph_states(
    existing_states: list[GraphState],
    loaded_states: list[GraphState],
) -> list[GraphState]:
    merged = list(existing_states)
    index_by_cache_key = {
        state["cache_key"]: index
        for index, state in enumerate(merged)
        if isinstance(state.get("cache_key"), str)
    }
    for state in loaded_states:
        cache_key = state.get("cache_key")
        if not isinstance(cache_key, str):
            continue
        existing_index = index_by_cache_key.get(cache_key)
        if existing_index is None:
            index_by_cache_key[cache_key] = len(merged)
            merged.append(state)
        else:
            merged[existing_index] = state
    return merged


def _single_graph_state(graph_states: list[GraphState]) -> GraphState | None:
    return graph_states[0] if len(graph_states) == 1 else None


def _selection_control_state(
    *,
    selected_source: str | list[str] | None,
    graph_filename: str | None,
    schema_filename: str | None,
    graph_url: str | None,
    schema_url: str | None,
    graph_states: list[GraphState] | GraphState | None,
) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    loaded_states = _normalize_graph_states(graph_states)
    if loaded_states:
        return True, False, True, True, True, True, True
    has_loadable_selection = bool(
        _selected_source_ids(selected_source)
        or graph_filename
        or _clean_url(graph_url)
    )
    has_resettable_selection = bool(
        has_loadable_selection
        or schema_filename
        or _clean_url(schema_url)
        or loaded_states
    )
    return (
        not has_loadable_selection,
        not has_resettable_selection,
        False,
        False,
        False,
        False,
        False,
    )


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
    url_client: UrlMetadataClient,
    session_id: str | None,
    graph_state: GraphState | None,
    parsed: ParsedGraphMetadata,
) -> ParsedGraphMetadata:
    if parsed.schema is not None or not session_id or not graph_state:
        return parsed
    kind = graph_state.get("kind")
    cache_key = graph_state.get("cache_key")
    if not isinstance(cache_key, str):
        return parsed
    if kind == "url":
        schema_url = graph_state.get("schema_url") or parsed.schema_reference.url
        if not isinstance(schema_url, str) or not schema_url:
            return parsed
        schema_data = url_client.load_json(schema_url)
        schema = parse_schema(schema_data)
        updated = replace(parsed, schema=schema)
        cache.set(session_id, cache_key, updated)
        return updated
    if kind != "kgx":
        return parsed
    source_id = graph_state.get("source_id")
    release_version = graph_state.get("release_version")
    data_url = graph_state.get("data_url")
    required_values = (source_id, release_version, data_url)
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
    url_client: UrlMetadataClient,
    session_id: str | None,
    graph_states: list[GraphState] | GraphState | None,
) -> ParsedGraphMetadata | None:
    graph_state = _single_graph_state(_normalize_graph_states(graph_states))
    parsed = _get_cached_graph(cache, session_id, graph_state)
    if parsed is None:
        return None
    return _ensure_schema_loaded(cache, kgx_client, url_client, session_id, graph_state, parsed)


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
            "label": "All categories",
            "value": ALL_SUBJECT_CATEGORIES_VALUE,
        },
        *[{"label": subject, "value": subject} for subject in ordered_subjects],
    ]


def _source_predicate_filter_options(
    counts: tuple[KnowledgeSourcePredicateCount, ...],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    source_totals: dict[str, int] = {}
    predicate_totals: dict[str, int] = {}
    for count in counts:
        source_totals[count.source] = source_totals.get(count.source, 0) + count.count
        predicate_totals[count.predicate] = (
            predicate_totals.get(count.predicate, 0) + count.count
        )
    return _count_options(source_totals), _count_options(predicate_totals)


def _predicate_sankey_filter_options(
    edges: tuple[EdgeTriple, ...],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    source_totals: dict[str, int] = {}
    predicate_totals: dict[str, int] = {}
    object_totals: dict[str, int] = {}
    for edge in edges:
        predicate_totals[edge.predicate] = predicate_totals.get(edge.predicate, 0) + edge.count
        object_label = _edge_object_label(edge)
        object_totals[object_label] = object_totals.get(object_label, 0) + edge.count
        for source, count in edge.primary_knowledge_sources.items():
            source_totals[source] = source_totals.get(source, 0) + count
    return (
        _count_options(source_totals),
        _count_options(predicate_totals),
        _count_options(object_totals),
    )


def _count_options(totals: dict[str, int]) -> list[dict[str, str]]:
    return [
        {"label": f"{label} ({count:,})", "value": label}
        for label, count in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def _edge_subject_label(edge: EdgeTriple) -> str:
    return ", ".join(edge.subject_category) or "Other"


def _edge_object_label(edge: EdgeTriple) -> str:
    return ", ".join(edge.object_category) or "Other"


def _dropdown_values(value: list[str] | str | None) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _predicate_sankey_top_n(subject_filter: str | None) -> int:
    if subject_filter is None:
        return ALL_CATEGORY_SANKEY_TOP_N
    return SUBJECT_CATEGORY_SANKEY_TOP_N


def _source_predicate_top_n_limit(
    counts: tuple[KnowledgeSourcePredicateCount, ...],
) -> int:
    sources = {count.source for count in counts}
    predicates = {count.predicate for count in counts}
    return max(1, len(sources), len(predicates))


def _sankey_slider_config(
    default_value: int,
    max_value: int,
    *,
    defaults: tuple[int, ...] = (),
) -> tuple[int, int, dict[int, str]]:
    safe_max = max(1, max_value)
    return (
        min(default_value, safe_max),
        safe_max,
        _sankey_slider_marks(safe_max, defaults=defaults),
    )


def _sankey_slider_marks(max_value: int, *, defaults: tuple[int, ...]) -> dict[int, str]:
    safe_max = max(1, max_value)
    mark_values = {safe_max}
    mark_values.update(value for value in defaults if 1 <= value <= safe_max)
    if _should_show_slider_min_mark(safe_max, mark_values):
        mark_values.add(1)
    return {
        value: f"{value} (all)" if value == safe_max else str(value)
        for value in sorted(mark_values)
    }


def _should_show_slider_min_mark(max_value: int, mark_values: set[int]) -> bool:
    min_mark = 1
    if min_mark in mark_values:
        return True
    # Hide the minimum label when another mark is too close to the left edge; on large
    # sliders, labels like "1" and "40" overlap and become illegible.
    return all((value - min_mark) / max_value >= 0.08 for value in mark_values)


def _slider_top_n(value: int | float | None, *, default: int) -> int:
    if value is None:
        return default
    return max(1, int(value))


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


def _empty_sankey_filter_message() -> html.Div:
    return html.Div(
        className="empty-inline",
        children=[
            html.H4("No matching Sankey flows"),
            html.P("Adjust or clear the Sankey filters to show matching relationship flows."),
        ],
    )


def _qualifier_context_summary(
    edges: tuple[EdgeTriple, ...],
    *,
    scope_label: str,
) -> html.Div:
    qualifier_counts = qualifier_counts_for_edges(edges, top_n=5)
    edge_count = sum(edge.count for edge in edges)
    children: list[Any] = [
        html.P(
            f"Qualifier context for {edge_count:,} edges from {len(edges):,} {scope_label}: "
        ),
    ]
    if qualifier_counts:
        children.append(
            html.Ul(
                [
                    html.Li(f"{qualifier}: {count:,}")
                    for qualifier, count in qualifier_counts
                ]
            )
        )
    else:
        children.append(html.P("No qualifier counts are reported for these flows."))
    return html.Div(className="qualifier-summary", children=children)


def _loaded_graphs_summary(graph_states: list[GraphState]) -> html.Div:
    baseline_selector = (
        html.Div(
            className="baseline-selector",
            children=[
                html.Label("Comparison baseline", htmlFor="comparison-baseline-selector"),
                dcc.Dropdown(
                    id="comparison-baseline-selector",
                    options=_baseline_selector_options(graph_states),
                    value=graph_states[0]["cache_key"],
                    clearable=False,
                ),
            ],
        )
        if len(graph_states) > 1
        else ""
    )
    return html.Div(
        className="content-card selection-summary",
        children=[
            html.Div(
                className="section-heading-row",
                children=[
                    html.Div(
                        children=[
                            html.P("Active selection", className="eyebrow"),
                            html.Div(
                                className="selection-heading-line",
                                children=[
                                    html.H3(_mode_label(len(graph_states))),
                                    html.P(
                                        "Click Reset selection button above to clear this "
                                        "selection before choosing a new set of graphs.",
                                        className="selection-reset-note",
                                    ),
                                ],
                            ),
                        ]
                    ),
                    baseline_selector,
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


def _baseline_selector_options(graph_states: list[GraphState]) -> list[dict[str, str]]:
    label_counts: dict[str, int] = {}
    for state in graph_states:
        label = _graph_label(state)
        label_counts[label] = label_counts.get(label, 0) + 1
    return [
        {
            "label": _baseline_selector_label(
                state,
                duplicated=label_counts[_graph_label(state)] > 1,
            ),
            "value": state["cache_key"],
        }
        for state in graph_states
        if isinstance(state.get("cache_key"), str)
    ]


def _baseline_selector_label(graph_state: GraphState, *, duplicated: bool) -> str:
    label = _graph_label(graph_state)
    if not duplicated:
        return label
    release = graph_state.get("release_version")
    if isinstance(release, str) and release:
        return f"{label} - {release}"
    return f"{label} - {_compact_graph_state_context(graph_state)}"


def _compact_graph_state_context(graph_state: GraphState) -> str:
    graph_url = graph_state.get("graph_url")
    if isinstance(graph_url, str) and graph_url:
        parsed_url = urlparse(graph_url)
        parts = [part for part in parsed_url.path.split("/") if part]
        compact_path = "/".join(parts[-3:]) if parts else parsed_url.netloc
        return compact_path or parsed_url.netloc
    return _graph_metadata_line(graph_state)


def _comparison_dashboard(
    cache: MetadataCache,
    kgx_client: KgxStorageClient,
    url_client: UrlMetadataClient,
    session_id: str | None,
    graph_states: list[GraphState],
    baseline_cache_key: str | None = None,
) -> html.Div:
    graph_states = _order_graph_states_for_baseline(graph_states, baseline_cache_key)
    parsed_graphs: list[ParsedGraphMetadata] = []
    labels: list[str] = []
    load_errors: list[str] = []
    for state in graph_states:
        label = _graph_label(state)
        parsed = _get_cached_graph(cache, session_id, state)
        if parsed is None:
            load_errors.append(f"{label}: metadata was not found in the session cache.")
            continue
        try:
            parsed = _ensure_schema_loaded(cache, kgx_client, url_client, session_id, state, parsed)
        except Exception as error:
            load_errors.append(f"{label}: schema could not be loaded ({error}).")
        parsed_graphs.append(parsed)
        labels.append(label)

    return comparison_dashboard(parsed_graphs, labels, load_errors)


def _order_graph_states_for_baseline(
    graph_states: list[GraphState],
    baseline_cache_key: str | None,
) -> list[GraphState]:
    if not baseline_cache_key:
        return graph_states
    baseline_index = next(
        (
            index
            for index, state in enumerate(graph_states)
            if state.get("cache_key") == baseline_cache_key
        ),
        None,
    )
    if baseline_index is None:
        return graph_states
    baseline = graph_states[baseline_index]
    return [
        baseline,
        *graph_states[:baseline_index],
        *graph_states[baseline_index + 1 :],
    ]


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
        return "Single graph selected."
    return f"{selection_count} graphs selected."


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
    if kind == "url":
        return graph_state.get("graph_url")
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
