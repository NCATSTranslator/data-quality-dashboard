from __future__ import annotations

import base64
import json
from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace

import pytest
from dash import Patch, dcc, html, page_registry
from dash.exceptions import PreventUpdate
from plotly.utils import PlotlyJSONEncoder

from graph_metadata_dashboard.app import create_app
from graph_metadata_dashboard.cache.comparison import load_comparison, store_comparison
from graph_metadata_dashboard.cache.memory import InMemoryMetadataCache
from graph_metadata_dashboard.components import comparison as comparison_components
from graph_metadata_dashboard.components.single_graph import (
    contribution_figure,
    primary_knowledge_source_counts,
    provenance_contribution,
    upload_selection_status,
    url_selection_status,
)
from graph_metadata_dashboard.config import Settings
from graph_metadata_dashboard.constants import (
    ALL_NODE_CATEGORIES_VALUE,
    ALL_SUBJECT_CATEGORIES_VALUE,
)
from graph_metadata_dashboard.diff import CountDelta, MapEntryChange, SourceChange, SubgraphChange
from graph_metadata_dashboard.diff.details import (
    adaptive_inline_count,
    remaining_schema_changes,
    split_map_changes,
)
from graph_metadata_dashboard.loaders.kgx_storage import KgxStorageClient
from graph_metadata_dashboard.loaders.url import UrlMetadataClient
from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata, parse_schema
from graph_metadata_dashboard.parsers.models import SubgraphSource
from tests.conftest import load_fixture


def test_provenance_contribution_falls_back_to_primary_sources() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))

    contribution = provenance_contribution(parsed)

    assert any(isinstance(child, dcc.Graph) for child in contribution.children)
    assert primary_knowledge_source_counts(parsed)


def test_provenance_contribution_describes_single_primary_source_without_chart() -> None:
    parsed = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    schema = parse_schema(
        {
            "edges_summary": {
                "primary_knowledge_sources": {
                    "infores:alliance": 123,
                }
            }
        }
    )
    parsed = replace(parsed, subgraphs=(), schema=schema)

    contribution = provenance_contribution(parsed)

    assert not any(isinstance(child, dcc.Graph) for child in contribution.children)
    assert "infores:alliance" in contribution.children[0].children


def test_provenance_contribution_uses_edge_counts_when_subgraph_node_counts_missing() -> None:
    parsed = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    parsed = replace(
        parsed,
        subgraphs=(
            SubgraphSource(
                id="https://kgx-storage.example/releases/source-a/1.0.0/",
                name="source-a",
                node_count=None,
                edge_count=25,
                release_version="1.0.0",
                build_version="source-a-build",
            ),
            SubgraphSource(
                id="https://kgx-storage.example/releases/source-b/1.0.0/",
                name="source-b",
                node_count=None,
                edge_count=10,
                release_version="1.0.0",
                build_version="source-b-build",
            ),
        ),
    )

    contribution = provenance_contribution(parsed)
    graphs = [child for child in contribution.children if isinstance(child, dcc.Graph)]

    assert "Subgraph node counts were not provided" in contribution.children[0].children
    assert graphs
    assert graphs[0].figure.layout.yaxis.title.text == "Edge count"
    assert list(graphs[0].figure.data[0].y) == [25, 10]


def test_provenance_contribution_falls_back_when_subgraph_counts_missing() -> None:
    parsed = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    schema = parse_schema(
        {
            "edges_summary": {
                "primary_knowledge_sources": {
                    "infores:source-a": 25,
                    "infores:source-b": 10,
                }
            }
        }
    )
    parsed = replace(
        parsed,
        subgraphs=(
            SubgraphSource(
                id="https://kgx-storage.example/releases/source-a/1.0.0/",
                name="source-a",
                node_count=None,
                edge_count=None,
                release_version="1.0.0",
                build_version="source-a-build",
            ),
        ),
        schema=schema,
    )

    contribution = provenance_contribution(parsed)
    text = " ".join(_flatten_text(contribution))

    assert "No subgraph counts were provided" in text
    assert "primary knowledge source" in text


@pytest.mark.parametrize("graph_id", ["translator_kg_open"])
def test_contribution_chart_preserves_real_fixture_behavior(graph_id: str) -> None:
    parsed = parse_graph_metadata(load_fixture(f"{graph_id}.graph-metadata.json"))
    contribution = provenance_contribution(parsed)
    inputs = _find_elements_by_type(contribution, "Input")
    graphs = _find_elements_by_type(contribution, "Graph")
    assert not inputs
    toggles = _find_elements_by_type(contribution, "RadioItems")
    if graph_id == "robokopkg":
        assert len(toggles) == 1
        assert toggles[0].value == "node_count"
    else:
        assert not toggles
    assert "contribution-panel" in contribution.className.split()
    assert ("contribution-panel-with-metric" in contribution.className.split()) == bool(toggles)
    assert graphs[0].figure.layout.title.text.startswith(f"{len(graphs[0].figure.data[0].x)} ")
    assert "<sup>" not in graphs[0].figure.layout.title.text
    assert graphs[0].responsive
    assert graphs[0].style["width"].startswith("max(100%,")
    assert graphs[0].figure.layout.bargap == 0
    assert graphs[0].figure.layout.xaxis.tickangle == -55
    assert graphs[0].figure.layout.xaxis.tickfont.size == 10
    assert graphs[0].style["height"] == f"{graphs[0].figure.layout.height}px"


@pytest.mark.parametrize("source_count", [65, 250])
def test_contribution_chart_shows_all_sources_with_compact_scroll_width(source_count: int) -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    source = parsed.subgraphs[0]
    parsed = replace(parsed, subgraphs=tuple(
        replace(source, name=f"Source {index}", id=f"urn:source:{index}", node_count=index)
        for index in range(source_count)
    ))
    contribution = provenance_contribution(parsed)
    graph = _find_elements_by_type(contribution, "Graph")[0]
    assert len(graph.figure.data[0].x) == source_count
    assert graph.style["width"] == f"max(100%, {source_count * 24 + 100}px)"
    assert list(graph.figure.data[0].y) == list(reversed(range(source_count)))
    assert not _find_elements_by_type(contribution, "Input")


def test_single_subgraph_keeps_statement_without_chart_controls() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    source = parsed.subgraphs[0]
    contribution = provenance_contribution(replace(parsed, subgraphs=(source,)))
    assert not _find_elements_by_type(contribution, "Graph")
    assert not _find_elements_by_type(contribution, "Input")
    assert "one contributing subgraph" in " ".join(_flatten_text(contribution))


def test_primary_source_contribution_shows_all_sources_without_controls() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None
    parsed = replace(parsed, subgraphs=(), schema=replace(
        parsed.schema, edges_summary={"primary_knowledge_sources": {
            f"infores:source-{index}": index for index in range(65)
        }},
    ))
    contribution = provenance_contribution(parsed)
    figure = _find_elements_by_type(contribution, "Graph")[0].figure
    assert len(figure.data[0].x) == 65
    assert figure.layout.title.text == "65 Primary knowledge source Contribution"
    assert figure.layout.yaxis.title.text == "Edge count"
    assert list(figure.data[0].y) == list(reversed(range(65)))
    assert not _find_elements_by_type(contribution, "Input")
    assert not _find_elements_by_type(contribution, "RadioItems")


def test_subgraph_metric_toggle_ranks_each_metric_and_handles_missing_counts() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    template = parsed.subgraphs[0]
    parsed = replace(parsed, subgraphs=(
        replace(template, name="Source A", id="urn:a", node_count=100, edge_count=10),
        replace(template, name="Source B", id="urn:b", node_count=20, edge_count=200),
        replace(template, name="Source C", id="urn:c", node_count=None, edge_count=0),
        replace(template, name="Source D", id="urn:d", node_count=5, edge_count=None),
    ))
    panel = provenance_contribution(parsed)
    toggle = _find_elements_by_type(panel, "RadioItems")[0]
    assert "contribution-panel-with-metric" in panel.className.split()
    assert toggle.value == "node_count"
    assert toggle.options == [
        {"label": "Nodes", "value": "node_count"},
        {"label": "Edges", "value": "edge_count"},
    ]
    nodes = contribution_figure(parsed, "node_count")
    edges = contribution_figure(parsed, "edge_count")
    assert list(nodes.data[0].x) == ["Source A", "Source B", "Source D"]
    assert list(nodes.data[0].y) == [100, 20, 5]
    assert list(edges.data[0].x) == ["Source B", "Source A", "Source C"]
    assert list(edges.data[0].y) == [200, 10, 0]
    assert nodes.layout.yaxis.title.text == "Node count"
    assert edges.layout.yaxis.title.text == "Edge count"
    assert edges.layout.title.text == "3 Subgraph Contribution"
    assert edges.layout.yaxis.type == "log"
    assert "Node count:" in edges.data[0].hovertemplate
    assert "Edge count:" in edges.data[0].hovertemplate
    assert contribution_figure(parsed, "invalid").layout.yaxis.title.text == "Node count"


@pytest.mark.parametrize("metric", ["node_count", "edge_count"])
def test_subgraph_metric_toggle_hidden_for_single_metric_and_single_source(metric: str) -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    template = parsed.subgraphs[0]
    sources = tuple(replace(
        template, name=f"Source {index}",
        node_count=index if metric == "node_count" else None,
        edge_count=index if metric == "edge_count" else None,
    ) for index in range(2))
    parsed = replace(parsed, subgraphs=sources)
    panel = provenance_contribution(parsed)
    assert not _find_elements_by_type(panel, "RadioItems")
    assert panel.className == "contribution-panel"
    expected_title = "Node count" if metric == "node_count" else "Edge count"
    assert _find_elements_by_type(panel, "Graph")[0].figure.layout.yaxis.title.text == (
        expected_title
    )
    other_metric = "edge_count" if metric == "node_count" else "node_count"
    assert contribution_figure(parsed, other_metric).layout.yaxis.title.text == expected_title
    assert not _find_elements_by_type(
        provenance_contribution(replace(parsed, subgraphs=sources[:1])), "RadioItems",
    )


def test_subgraph_metric_callback_uses_session_cache_and_resets_on_graph_change() -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    template = parsed.subgraphs[0]
    parsed = replace(parsed, subgraphs=tuple(replace(
        template, name=f"Source {index}", node_count=index, edge_count=100 - index,
    ) for index in range(65)))
    cache.set("metric-session", "graph", parsed)
    page_module.register_callbacks(
        app, cache=cache,
        kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    update = next(entry["callback"].__wrapped__ for key, entry in app.callback_map.items()
                  if "contribution-chart.figure" in key)
    state = [{"cache_key": "graph"}]
    figure, style = update("edge_count", state, "metric-session")
    assert figure.layout.yaxis.title.text == "Edge count"
    assert list(figure.data[0].y) == list(range(100, 35, -1))
    assert style["width"] == "max(100%, 1660px)"
    assert style["height"] == f"{figure.layout.height}px"
    for missing_states, session in ((state, "other-session"), ([], "metric-session"),
                                    (state * 2, "metric-session"),
                                    ([{"cache_key": "expired"}], "metric-session")):
        with pytest.raises(PreventUpdate):
            update("edge_count", missing_states, session)
    render = app.callback_map["provenance-panel.children"]["callback"].__wrapped__
    for key in ("graph", "another-graph"):
        cache.set("metric-session", key, parsed)
        panel = render([{"cache_key": key}], "metric-session")
        assert _find_elements_by_type(panel, "RadioItems")[0].value == "node_count"
        assert _find_elements_by_type(panel, "Graph")[0].figure.layout.yaxis.title.text == (
            "Node count"
        )


def test_provenance_callback_uses_session_cache_and_updates_on_graph_change() -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    session_id = "contribution-session"
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    source = parsed.subgraphs[0]
    parsed = replace(parsed, subgraphs=tuple(
        replace(source, name=f"Source {index}", node_count=index)
        for index in range(65)
    ))
    cache.set(session_id, "large", parsed)
    small = replace(parsed, subgraphs=parsed.subgraphs[:3])
    cache.set(session_id, "small", small)
    page_module.register_callbacks(
        app, cache=cache,
        kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    assert any("contribution-chart.figure" in key for key in app.callback_map)
    render = app.callback_map["provenance-panel.children"]["callback"].__wrapped__
    states = [{"cache_key": "large"}]
    for unavailable_states, unavailable_session in (
        (states, "another-session"), ([], session_id),
        ([{"cache_key": "expired"}], session_id),
        (states * 2, session_id),
    ):
        assert render(unavailable_states, unavailable_session) == ""
    for graph_key, expected_count in (("small", 3), ("large", 65)):
        panel = render([{"cache_key": graph_key}], session_id)
        assert not _find_elements_by_type(panel, "Input")
        graph = _find_elements_by_type(panel, "Graph")[0]
        assert len(graph.figure.data[0].x) == expected_count


@pytest.mark.parametrize("graph_id", ["alliance", "translator_kg_open", "robokopkg"])
def test_node_category_panel_renders_uncapped_scrollable_chart(graph_id: str) -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    parsed = parse_graph_metadata(
        load_fixture(f"{graph_id}.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json") if graph_id == "robokopkg" else None,
    )
    if graph_id == "robokopkg":
        assert parsed.schema is not None
        template = parsed.schema.nodes[0]
        parsed = replace(parsed, schema=replace(parsed.schema, nodes=tuple(
            replace(template, category=f"biolink:Category{index}", count=index)
            for index in range(65)
        )))
    cache.set("category-session", graph_id, parsed)
    page_module.register_callbacks(
        app, cache=cache,
        kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    render = app.callback_map["node-categories-panel.children"]["callback"].__wrapped__
    state = [{"cache_key": graph_id, "kind": "upload"}]
    assert render(state, "another-session") == ""
    assert render([], "category-session") == ""
    panel = render(state, "category-session")
    graphs = _find_elements_by_type(panel, "Graph")
    if parsed.schema is None:
        assert not graphs
        assert "Schema unavailable" in " ".join(_flatten_text(panel))
    else:
        assert len(graphs) == 2
        graph = next(graph for graph in graphs if graph.id == "node-category-contribution-chart")
        assert len(graph.figure.data[0].x) == len(parsed.schema.nodes)
        assert graph.responsive
        assert graph.style["height"] == f"{graph.figure.layout.height}px"
        assert (
            graph.figure.layout.height
            - graph.figure.layout.margin.t - graph.figure.layout.margin.b >= 267
        )
        assert graph.style["width"] == (
            f"max(100%, {max(700, len(parsed.schema.nodes) * 24 + 100)}px)"
        )
        assert _find_elements_by_class(panel, "contribution-panel")
        assert all("biolink:" not in label
                   for label in graph.figure.layout.xaxis.ticktext)


def test_node_attribute_callbacks_link_bar_clicks_dropdown_and_reset() -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None
    cache.set("attribute-session", "graph", parsed)
    page_module.register_callbacks(
        app, cache=cache,
        kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    state = [{"cache_key": "graph"}]
    select = app.callback_map["node-attribute-category.value"]["callback"].__wrapped__
    update = next(entry["callback"].__wrapped__ for key, entry in app.callback_map.items()
                  if "node-attribute-chart.figure" in key)
    node = next(node for node in parsed.schema.nodes if node.count > 0 and node.attributes)
    click = {"points": [{"customdata": node.category, "x": node.category}]}
    assert select(click, state, "attribute-session") == node.category
    assert select({"points": [{"x": node.category}]}, state, "attribute-session") == (
        node.category
    )
    figure, style, status, viewport_style, contribution = update(
        node.category, "", state, "attribute-session",
    )
    assert node.category in status
    assert f"{node.count:,} nodes" in status
    assert style["height"] == f"{figure.layout.height}px"
    assert viewport_style["height"] == f"{contribution.layout.height}px"
    assert list(figure.data[0].customdata[0])[2] == node.count
    selected_index = list(contribution.data[0].x).index(node.category)
    assert contribution.data[0].marker.color[selected_index] == "#b45309"
    reset_category = select({"reset": True, "sequence": 1}, state, "attribute-session")
    assert reset_category == ALL_NODE_CATEGORIES_VALUE
    all_view = update(reset_category, "", state, "attribute-session")
    assert "All categories" in all_view[2]
    assert set(all_view[4].data[0].marker.color) == {"#0f766e"}
    search = update(node.category, "no-such-attribute", state, "attribute-session")
    assert not search[0].data[0].x
    assert "Showing 0 of 0 matching" in search[2]
    cleared = update(node.category, "", state, "attribute-session")
    assert len(cleared[0].data[0].x) == min(50, len(node.attributes))
    assert "matching" not in cleared[2]
    assert cleared[3] == search[3]
    assert "All categories" in update("stale-category", "", state, "attribute-session")[2]
    for invalid_click in (None, {}, {"points": []}, {"points": [None]},
                          {"points": [{"x": "unknown-category"}]}):
        with pytest.raises(PreventUpdate):
            select(invalid_click, state, "attribute-session")
    for states, session in (([], "attribute-session"), (state * 2, "attribute-session"),
                            (state, "another-session"),
                            ([{"cache_key": "expired"}], "attribute-session")):
        with pytest.raises(PreventUpdate):
            update(node.category, "", states, session)
        with pytest.raises(PreventUpdate):
            select(click, states, session)
    render = app.callback_map["node-categories-panel.children"]["callback"].__wrapped__
    for key in ("graph", "new-graph"):
        cache.set("attribute-session", key, parsed)
        panel = render([{"cache_key": key}], "attribute-session")
        dropdown = next(item for item in _find_elements_by_type(panel, "Dropdown")
                        if item.id == "node-attribute-category")
        assert dropdown.value == ALL_NODE_CATEGORIES_VALUE
        assert len(dropdown.options) == len(parsed.schema.nodes) + 1
        assert len(_find_elements_by_type(panel, "Dropdown")) == 1
        assert "Attributes to show" not in " ".join(_flatten_text(panel))
        search_input = _find_elements_by_type(panel, "Input")[0]
        assert search_input.value == ""
        assert search_input.debounce is False
        viewport = _find_elements_by_class(panel, "node-attribute-scroll")[0]
        category_graph = next(graph for graph in _find_elements_by_type(panel, "Graph")
                              if graph.id == "node-category-contribution-chart")
        assert viewport.style["height"] == f"{category_graph.figure.layout.height}px"


@pytest.mark.parametrize("graph_id", ["alliance", "translator_kg_open", "robokopkg"])
def test_category_pair_panel_uses_bounded_adaptive_chart(graph_id: str) -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    parsed = parse_graph_metadata(
        load_fixture(f"{graph_id}.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json") if graph_id == "robokopkg" else None,
    )
    if graph_id == "robokopkg":
        assert parsed.schema is not None
        template = parsed.schema.edges[0]
        parsed = replace(parsed, schema=replace(parsed.schema, edges=tuple(
            replace(template, subject_category=("biolink:Protein", "biolink:Drug"),
                    object_category=(f"biolink:Object{index}",), count=index)
            for index in range(65)
        )))
    cache.set("pair-session", graph_id, parsed)
    page_module.register_callbacks(
        app, cache=cache,
        kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    callback = app.callback_map["category-pair-summary-panel.children"]
    assert callback["inputs"] == [{"id": "loaded-graph-state", "property": "data"}]
    render = callback["callback"].__wrapped__
    state = [{"cache_key": graph_id, "kind": "upload"}]
    assert render([], "pair-session") == ""
    assert render(state * 2, "pair-session") == ""
    panel = render(state, "pair-session")
    graphs = _find_elements_by_type(panel, "Graph")
    if parsed.schema is None:
        assert not graphs
    else:
        assert len(graphs) == 1
        graph = graphs[0]
        if graph_id == "robokopkg":
            assert len(graph.figure.data[0].x) == 50
            assert graph.style["width"] == "max(100%, 1300px)"
            assert graph.figure.layout.title.text == (
                "65 Subject-Object Category Pair Contribution (Top 50)"
            )
        assert graph.responsive
        assert graph.style["height"] == f"{graph.figure.layout.height}px"
        assert graph.figure.layout.bargap == 0
        assert graph.figure.layout.xaxis.tickangle == -55
        assert all("biolink:" not in label for label in graph.figure.layout.xaxis.ticktext)
        assert _find_elements_by_class(panel, "contribution-panel")


@pytest.mark.parametrize("graph_id", ["alliance", "translator_kg_open", "robokopkg"])
def test_sankey_sliders_and_renderers_allow_all_matching_patterns(graph_id: str) -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    parsed = parse_graph_metadata(
        load_fixture(f"{graph_id}.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json") if graph_id == "robokopkg" else None,
    )
    cache.set("sankey-session", graph_id, parsed)
    state = [{"cache_key": graph_id, "kind": "upload"}]
    page_module.register_callbacks(
        app, cache=cache, kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    def callback_for(output: str) -> object:
        return next(callback["callback"].__wrapped__ for key, callback in app.callback_map.items()
                    if output in key)

    source_config = callback_for("source-predicate-top-n-slider.value")
    subject_dropdown = callback_for("sankey-subject-category-dropdown.value")
    options, selected_subject, disabled = subject_dropdown(state, "sankey-session")
    assert selected_subject == ALL_SUBJECT_CATEGORIES_VALUE
    assert options[0] == {"label": "All categories", "value": ALL_SUBJECT_CATEGORIES_VALUE}
    assert disabled is False
    assert subject_dropdown([], "sankey-session") == ([], None, True)
    subject_config = callback_for("sankey-top-n-slider.value")
    render_source = callback_for("source-predicate-panel-body.children")
    render_subject = callback_for("sankey-panel-body.children")
    for sources, predicates in (([], []), ([parsed.schema.source_predicate_counts[0].source], [])):
        value, maximum, marks, _ = source_config(
            sources, predicates, state, 100, "sankey-session", None,
        )
        candidates = [count for count in parsed.schema.source_predicate_counts
                      if not sources or count.source in sources]
        assert maximum == len({(count.source, count.predicate) for count in candidates})
        assert value == min(100, maximum)
        assert marks[maximum] == f"{maximum} (all)"
        for selected_count in (1, maximum):
            hidden, chart = render_source(True, sources, predicates, selected_count,
                                           state, "sankey-session")
            assert hidden is False
            assert len(chart.figure.data[0].link.value) == selected_count
            assert "Other" not in chart.figure.data[0].node.label
            assert chart.id == "source-predicate-sankey-graph"
    for subject in (ALL_SUBJECT_CATEGORIES_VALUE,
                    ", ".join(parsed.schema.edges[0].subject_category)):
        value, maximum, marks = subject_config(subject, [], [], [], state, "sankey-session")
        expected_count = sum(subject == ALL_SUBJECT_CATEGORIES_VALUE
                             or ", ".join(edge.subject_category) == subject
                             for edge in parsed.schema.edges)
        assert maximum == expected_count
        assert value == min(100, maximum)
        assert marks[maximum] == f"{maximum} (all)"
        hidden, chart, disabled = render_subject(True, subject, [], [], [], maximum,
                                                state, "sankey-session")
        assert hidden is False
        assert disabled is False
        assert len(chart.figure.data[0].link.value) == maximum * 2


def test_predicate_composition_includes_inline_pairs_without_toggle() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    layout = page_module.layout()
    card = next(item for item in _find_elements_by_type(layout, "Div")
                if getattr(item, "id", None) == "sankey-action-card")
    text = " ".join(_flatten_text(card))
    assert "three perspectives" in text
    assert "Top source-predicate connections" in text
    pair_panel = next(item for item in _find_elements_by_type(card, "Div")
                      if getattr(item, "id", None) == "category-pair-summary-panel")
    assert not getattr(pair_panel, "hidden", False)
    assert not any(getattr(item, "id", None) == "category-pair-summary-visible"
                   for item in _find_elements_by_type(layout, "Store"))


def test_upload_selection_status_lists_selected_files() -> None:
    status = upload_selection_status("graph-metadata.json", "schema.json")

    assert all(isinstance(item, html.P) for item in status)
    assert "graph-metadata.json" in status[0].children
    assert "schema.json" in status[1].children


def test_upload_selection_status_is_empty_before_files_are_selected() -> None:
    assert upload_selection_status(None, None) == []


def test_url_selection_status_lists_selected_urls() -> None:
    status = url_selection_status(
        " https://metadata.example/graph-metadata.json ",
        "https://metadata.example/schema.json",
    )

    assert all(isinstance(item, html.P) for item in status)
    assert "https://metadata.example/graph-metadata.json" in status[0].children
    assert "https://metadata.example/schema.json" in status[1].children


def test_comparison_dashboard_replaces_placeholder_for_multiple_graphs() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    cache = InMemoryMetadataCache()
    session_id = "test-session"
    first = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    second = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    third = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    cache.set(session_id, "first", first)
    cache.set(session_id, "second", second)
    cache.set(session_id, "third", third)

    dashboard = page_module._comparison_dashboard(
        cache,
        KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id,
        [
            {"cache_key": "first", "kind": "upload", "label": "Alliance"},
            {"cache_key": "second", "kind": "upload", "label": "Translator KG Open"},
            {"cache_key": "third", "kind": "upload", "label": "Alliance Copy"},
        ],
    )
    text = " ".join(_flatten_text(dashboard))
    overview_table = _find_elements_by_class(dashboard, "comparison-overview-table")[0]
    source_dialogs = [
        dialog
        for dialog in _find_elements_by_type(dashboard, "Dialog")
        if dialog.id.startswith("source-changes-dialog-")
    ]

    assert "Comparison Overview" in text
    assert "Types" in text
    assert "Schema-Level Differences:" in text
    assert "Alliance" in text
    assert "Translator KG Open" in text
    assert len(_find_elements_by_class(dashboard, "comparison-glyph")) > 0
    assert len(_find_elements_by_class(dashboard, "overview-delta")) > 0
    assert len(_find_elements_by_class(dashboard, "metadata-change-action-row")) == 1
    assert len(_find_elements_by_class(dashboard, "comparison-download-button")) == 2
    assert len(_find_elements_by_class(dashboard, "comparison-pair-details")) == 2
    assert not _find_elements_by_class(overview_table, "comparison-glyph")
    assert len(_find_elements_by_class(dashboard, "schema-table-panel")) > 0
    assert len(source_dialogs) == 1
    source_tables = _find_datatables(source_dialogs[0])
    assert "Show changes" in text
    assert "Alliance Copy" in _flatten_text(overview_table)
    assert "No changes" in _flatten_text(overview_table)
    overview_rows = _find_elements_by_type(overview_table, "Tr")[1:]
    for row, graph in zip(overview_rows, (first, second, third), strict=True):
        release_cell = row.children[1].children
        assert release_cell.className == "comparison-overview-cell"
        assert _find_elements_by_type(release_cell, "Strong")[0].children == (
            graph.release_version or "Unknown"
        )
    assert source_tables
    source_column_names = [column["name"] for column in source_tables[0].columns]
    assert source_column_names[0] == "Status"
    assert "Changed Fields" in source_column_names
    assert "Alliance Values" in source_column_names
    assert "Translator KG Open Values" in source_column_names
    assert {"if": {"column_id": "old_values"}, "whiteSpace": "pre-line"} in (
        source_tables[0].style_data_conditional
    )


def test_comparison_dashboard_uses_selected_baseline() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    cache = InMemoryMetadataCache()
    session_id = "test-session"
    first = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    second = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    cache.set(session_id, "first", first)
    cache.set(session_id, "second", second)

    dashboard = page_module._comparison_dashboard(
        cache,
        KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id,
        [
            {"cache_key": "first", "kind": "upload", "label": "Alliance"},
            {"cache_key": "second", "kind": "upload", "label": "Translator KG Open"},
        ],
        "second",
    )
    text = " ".join(_flatten_text(dashboard))

    assert "Use Translator KG Open as the baseline" in text
    assert "Translator KG Open -> Alliance" in text


def test_loaded_graphs_summary_includes_baseline_selector() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    summary = page_module._loaded_graphs_summary(
        [
            {"cache_key": "first", "kind": "upload", "label": "Alliance"},
            {"cache_key": "second", "kind": "upload", "label": "Translator KG Open"},
        ]
    )
    text = " ".join(_flatten_text(summary))
    dropdowns = _find_elements_by_type(summary, "Dropdown")

    assert "Comparison baseline" in text
    assert dropdowns
    assert dropdowns[0].id == "comparison-baseline-selector"
    assert dropdowns[0].value == "first"
    assert [option["label"] for option in dropdowns[0].options] == [
        "Alliance",
        "Translator KG Open",
    ]


def test_initial_layout_includes_hidden_baseline_selector() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    layout = page_module.layout()
    selectors = [
        dropdown
        for dropdown in _find_elements_by_type(layout, "Dropdown")
        if dropdown.id == "comparison-baseline-selector"
    ]

    assert len(selectors) == 1
    assert selectors[0].value is None
    assert selectors[0].options == []
    assert _find_elements_by_class(layout, "selection-summary")[0].style == {"display": "none"}


def test_loading_indicator_only_covers_overview_rendering_after_one_second() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    layout = page_module.layout()
    indicators = _find_elements_by_type(layout, "Loading")

    assert len(indicators) == 1
    indicator = indicators[0]
    assert indicator.delay_show == 1000
    assert indicator.show_initially is False
    assert indicator.target_components == {
        "overview-panel": "children",
    }
    assert {child.id for child in indicator.children} == set(indicator.target_components)
    assert not _find_elements_by_type(indicator, "Store")
    results_region = _find_elements_by_class(layout, "results-region")[0]
    assert results_region.children[0].id == "loaded-graphs-panel"
    assert results_region.children[1] is indicator
    stores = _find_elements_by_type(layout, "Store")
    graph_stores = [store for store in stores if store.id == "loaded-graph-state"]
    assert len(graph_stores) == 1
    assert graph_stores[0].storage_type == "session"
    assert indicator.custom_spinner.role == "status"
    assert indicator.custom_spinner.style["alignSelf"] == "flex-start"
    assert "Loading graph metadata" in " ".join(_flatten_text(indicator.custom_spinner))
    assert "No graph loaded" not in " ".join(_flatten_text(indicator.custom_spinner))


def test_overview_follows_selection_and_reset_without_missing_inputs() -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    session_id = "overview-selection-session"
    graph_states = []
    parsed_graphs = []
    for graph_id in ("alliance", "translator_kg_open", "robokopkg"):
        parsed = parse_graph_metadata(load_fixture(f"{graph_id}.graph-metadata.json"))
        cache.set(session_id, graph_id, parsed)
        parsed_graphs.append(parsed)
        graph_states.append({"cache_key": graph_id, "kind": "upload", "label": parsed.name})
    page_module.register_callbacks(
        app,
        cache=cache,
        kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    render_summary = app.callback_map["loaded-graphs-panel.children"]["callback"].__wrapped__
    overview_callback = app.callback_map["overview-panel.children"]
    render_overview = overview_callback["callback"].__wrapped__

    selections = [
        None,
        [graph_states[0]],
        [],
        graph_states[:2],
        [],
        [graph_states[0]],
        [],
        [graph_states[1]],
        [graph_states[2]],
        [],
    ]
    for selection in selections:
        summary = render_summary(selection)
        dropdowns = _find_elements_by_type(summary, "Dropdown")
        assert len(dropdowns) == 1
        selector = dropdowns[0]
        assert {"id": selector.id, "property": "value"} in overview_callback["inputs"]
        assert summary.style == ({} if selection else {"display": "none"})
        selector_container = _find_elements_by_class(summary, "baseline-selector")[0]
        comparison_mode = bool(selection and len(selection) > 1)
        assert selector_container.style == ({} if comparison_mode else {"display": "none"})
        assert selector.options == page_module._baseline_selector_options(selection or [])
        assert selector.value == (selection[0]["cache_key"] if selection else None)

        overview = render_overview(selection, selector.value, session_id)
        text = " ".join(_flatten_text(overview))
        if not selection:
            assert "No graph loaded" in text
            assert not _find_elements_by_class(overview, "overview-card")
            assert not _find_elements_by_class(overview, "comparison-dashboard")
        elif comparison_mode:
            assert "Comparison Overview" in text
            changed_baseline = render_overview(selection, selection[1]["cache_key"], session_id)
            assert f"Use {selection[1]['label']} as the baseline" in " ".join(
                _flatten_text(changed_baseline)
            )
        else:
            assert _find_elements_by_class(overview, "overview-card")
            headings = _find_elements_by_type(overview, "H2")
            assert headings[0].children[0] == selection[0]["label"]
            for parsed in parsed_graphs:
                if parsed.name != selection[0]["label"]:
                    assert parsed.name not in text


def test_loaded_selection_locks_kgx_and_upload_but_allows_url_append() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    assert page_module._selection_count_status(3) == "3 graphs selected."
    assert page_module._selection_control_state(
        selected_source=["alliance", "ctd"],
        graph_filename=None,
        schema_filename=None,
        graph_url=None,
        schema_url=None,
        graph_states=[],
    ) == (False, False, False, False, False, False, False)
    assert page_module._selection_control_state(
        selected_source=["alliance", "ctd"],
        graph_filename=None,
        schema_filename=None,
        graph_url=None,
        schema_url=None,
        graph_states=[
            {
                "cache_key": "alliance",
                "kind": "kgx",
                "source_id": "alliance",
                "label": "Alliance",
            }
        ],
    ) == (True, False, True, False, False, True, True)
    assert page_module._selection_control_state(
        selected_source=["alliance", "ctd"],
        graph_filename=None,
        schema_filename=None,
        graph_url="https://metadata.example/graph-metadata.json",
        schema_url=None,
        graph_states=[
            {
                "cache_key": "alliance",
                "kind": "kgx",
                "source_id": "alliance",
                "label": "Alliance",
            }
        ],
    ) == (False, False, True, False, False, True, True)
    assert page_module._selection_control_state(
        selected_source=[],
        graph_filename=None,
        schema_filename=None,
        graph_url=None,
        schema_url=None,
        graph_states=[],
    ) == (True, True, False, False, False, False, False)


def test_baseline_selector_disambiguates_duplicate_graph_names() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    options = page_module._baseline_selector_options(
        [
            {
                "cache_key": "first",
                "kind": "url",
                "label": "ROBOKOP",
                "release_version": "2026-01-01",
            },
            {
                "cache_key": "second",
                "kind": "url",
                "label": "ROBOKOP",
                "release_version": "2026-02-01",
            },
            {
                "cache_key": "third",
                "kind": "url",
                "label": "Translator KG Open",
                "release_version": "2026-02-01",
            },
        ]
    )

    assert [option["label"] for option in options] == [
        "ROBOKOP - 2026-01-01",
        "ROBOKOP - 2026-02-01",
        "Translator KG Open",
    ]


def test_baseline_selector_uses_compact_url_fallback_for_duplicate_graph_names() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    options = page_module._baseline_selector_options(
        [
            {
                "cache_key": "first",
                "kind": "url",
                "label": "ROBOKOP",
                "graph_url": (
                    "https://kgx-storage.ci.transltr.io/releases/RobokopKG/"
                    "2026_01_01/graph-metadata.json"
                ),
            },
            {
                "cache_key": "second",
                "kind": "url",
                "label": "ROBOKOP",
                "graph_url": (
                    "https://kgx-storage.ci.transltr.io/releases/RobokopKG/"
                    "2026_02_01/graph-metadata.json"
                ),
            },
        ]
    )

    assert [option["label"] for option in options] == [
        "ROBOKOP - RobokopKG/2026_01_01/graph-metadata.json",
        "ROBOKOP - RobokopKG/2026_02_01/graph-metadata.json",
    ]


def test_uploaded_graph_state_keeps_parsed_release_version() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    payload = {
        "name": "Example Graph",
        "version": "2026_05_07",
    }
    contents = (
        "data:application/json;base64,"
        + base64.b64encode(json.dumps(payload).encode()).decode()
    )

    state = page_module._load_uploaded_graph(
        cache,
        "test-session",
        contents,
        "graph-metadata.json",
        None,
    )

    assert state["label"] == "Example Graph"
    assert state["release_version"] == "2026_05_07"


def test_url_graph_state_keeps_parsed_release_version() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    url_client = _FakeUrlClient(
        {
            "https://metadata.example/graph-metadata.json": {
                "name": "Example Graph",
                "version": "2026_05_07",
            }
        }
    )

    state = page_module._load_url_graph(
        cache,
        url_client,
        "test-session",
        "https://metadata.example/graph-metadata.json",
        None,
    )

    assert state["label"] == "Example Graph"
    assert state["release_version"] == "2026_05_07"


def test_merge_graph_states_appends_new_and_replaces_existing() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    merged = page_module._merge_graph_states(
        [
            {"cache_key": "first", "label": "First"},
            {"cache_key": "second", "label": "Old second"},
        ],
        [
            {"cache_key": "second", "label": "New second"},
            {"cache_key": "third", "label": "Third"},
        ],
    )

    assert [state["cache_key"] for state in merged] == ["first", "second", "third"]
    assert merged[1]["label"] == "New second"


def test_url_input_edit_preserves_loaded_url_graphs() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    states = [
        {
            "cache_key": "url:first",
            "kind": "url",
            "graph_url": "https://metadata.example/first/graph-metadata.json",
        },
        {
            "cache_key": "url:second",
            "kind": "url",
            "graph_url": "https://metadata.example/second/graph-metadata.json",
        },
    ]

    preserved = page_module._normalize_graph_states(states)

    assert preserved == states


def test_comparison_dashboard_hides_unchanged_subgraph_section() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    cache = InMemoryMetadataCache()
    session_id = "test-session"
    parsed = replace(
        parse_graph_metadata(load_fixture("alliance.graph-metadata.json")),
        schema=None,
    )
    cache.set(session_id, "first", parsed)
    cache.set(session_id, "second", parsed)

    dashboard = page_module._comparison_dashboard(
        cache,
        KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id,
        [
            {"cache_key": "first", "kind": "upload", "label": "Alliance"},
            {"cache_key": "second", "kind": "upload", "label": "Alliance Copy"},
        ],
    )

    assert "Subgraph Source Changes" not in " ".join(_flatten_text(dashboard))
    assert "Schema-Level Differences:" not in " ".join(_flatten_text(dashboard))
    assert all(
        dialog.id == "schema-changes-dialog"
        for dialog in _find_elements_by_type(dashboard, "Dialog")
    )
    subgraph_cell = _find_elements_by_class(dashboard, "subgraph-overview-cell")[0]
    assert "No changes" in _flatten_text(subgraph_cell)
    assert not _find_elements_by_type(subgraph_cell, "Button")
    assert _find_elements_by_class(dashboard, "schema-diff-download-button")[0].disabled


def test_subgraph_changes_use_overview_dialogs_for_each_comparison() -> None:
    graphs = [
        replace(
            parse_graph_metadata(load_fixture(f"{name}.graph-metadata.json")),
            schema=None,
        )
        for name in ("robokopkg", "alliance", "translator_kg_open")
    ]
    labels = ["ROBOKOP", "Alliance", "Translator KG Open"]
    result = comparison_components.compare(graphs, labels=labels)
    dashboard = comparison_components.comparison_dashboard(graphs, labels, [])
    overview = _find_elements_by_class(dashboard, "comparison-overview-table")[0]
    cells = _find_elements_by_class(overview, "subgraph-overview-cell")
    all_dialogs = _find_elements_by_type(dashboard, "Dialog")

    assert len(cells) == 2
    assert len({dialog.id for dialog in all_dialogs}) == len(all_dialogs)
    assert not _find_elements_by_class(overview, "comparison-glyph")
    assert not _find_elements_by_class(dashboard, "comparison-pair-card")
    assert "Schema-Level Differences:" not in " ".join(_flatten_text(dashboard))
    for index, (cell, pair) in enumerate(zip(cells, result.comparisons, strict=True), start=1):
        dialog = _find_elements_by_type(cell, "Dialog")[0]
        buttons = _find_elements_by_type(cell, "Button")
        table = _find_datatables(dialog)[0]

        assert dialog.id == f"subgraph-changes-dialog-{index}"
        assert buttons[0].children == "Show changes"
        assert getattr(buttons[0], "data-dialog-target") == dialog.id
        assert buttons[1].children == "Close"
        assert getattr(buttons[1], "data-dialog-close") == dialog.id
        assert f"{len(pair.subgraph_changes):,} changed" in _flatten_text(cell)
        assert f"Changed Subgraphs: ROBOKOP -> {pair.target.label}" in _flatten_text(dialog)
        assert len(table.data) == len(pair.subgraph_changes)
        assert {row["id"] for row in table.data} == {
            change.source_id for change in pair.subgraph_changes
        }
        assert {"name": "ROBOKOP Metadata", "id": "old_values"} in table.columns
        assert {"name": f"{pair.target.label} Metadata", "id": "new_values"} in table.columns
        assert table.page_size == 10
        assert table.filter_action == "none"
        assert pair.schema.message in _flatten_text(dashboard)


def test_subgraph_changes_table_paginates_all_large_graph_changes() -> None:
    baseline = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    target = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    pair = comparison_components.compare([baseline, target]).comparisons[0]
    table = _find_datatables(
        comparison_components._subgraph_changes_table(pair.subgraph_changes)
    )[0]

    assert len(pair.subgraph_changes) > 25
    assert len(table.data) == len(pair.subgraph_changes)
    assert table.page_size == 10
    assert table.sort_action == "native"
    assert table.filter_action == "none"


def test_source_changes_table_hides_changed_fields_for_added_removed_only() -> None:
    changes = tuple(
        SourceChange(
            source_id=f"infores:{status}",
            name=status,
            status=status,
            changed_fields=(status.title(),),
            old_values="Version: old" if status == "removed" else "None",
            new_values="Version: new" if status == "added" else "None",
            field_differences=(),
        )
        for status in ("added", "removed")
    )
    for selected_changes in ((changes[0],), (changes[1],), changes):
        table = comparison_components._source_changes_table(selected_changes)
        datatable = _find_datatables(table)[0]

        assert datatable.columns[0] == {"name": "Status", "id": "status"}
        assert {"name": "Changed Fields", "id": "changed_fields"} not in datatable.columns
        assert [row["status"] for row in datatable.data] == [
            change.status for change in selected_changes
        ]
        assert all("changed_fields" not in row for row in datatable.data)
        assert datatable.page_size == 10


def test_source_changes_table_shows_fields_only_for_modified_records() -> None:
    changes = tuple(
        SourceChange(
            source_id=f"infores:{status}",
            name=status,
            status=status,
            changed_fields=("Version", "License") if status == "changed" else (status.title(),),
            old_values="Version: old" if status != "added" else "None",
            new_values="Version: new" if status != "removed" else "None",
            field_differences=(),
        )
        for status in ("removed", "changed", "added")
    )
    table = comparison_components._source_changes_table(
        changes, baseline_label="Baseline KG", comparison_label="Target KG"
    )
    datatable = _find_datatables(table)[0]

    assert datatable.columns == [
        {"name": "Status", "id": "status"},
        {"name": "ID", "id": "id"},
        {"name": "Name", "id": "name"},
        {"name": "Changed Fields", "id": "changed_fields"},
        {"name": "Baseline KG Values", "id": "old_values"},
        {"name": "Target KG Values", "id": "new_values"},
    ]
    assert [row["status"] for row in datatable.data] == ["removed", "changed", "added"]
    assert [row["changed_fields"] for row in datatable.data] == ["", "Version, License", ""]
    assert datatable.data[0]["new_values"] == "None"
    assert datatable.data[2]["old_values"] == "None"


def test_subgraph_changes_table_renders_metadata_differences() -> None:
    table = comparison_components._subgraph_changes_table(
        (
            SubgraphChange(
                source_id="alliance",
                name="alliance",
                status="changed",
                changed_fields=("Release version", "Build version", "Node count", "Edge count"),
                old_values=(
                    "Release version: 1.0.0\nBuild version: old-build\n"
                    "Node count: 0\nEdge count: 123"
                ),
                new_values=(
                    "Release version: 1.0.1\nBuild version: new-build\n"
                    "Node count: Not provided\nEdge count: Not provided"
                ),
            ),
        )
    )
    text = " ".join(_flatten_text(table))
    datatable = _find_datatables(table)[0]

    assert "Subgraph Source Changes" in text
    assert {"name": "Changed Fields", "id": "changed_fields"} in datatable.columns
    assert datatable.data[0]["changed_fields"] == (
        "Release version, Build version, Node count, Edge count"
    )
    assert "Node count: 0" in datatable.data[0]["old_values"]
    assert "Edge count: 123" in datatable.data[0]["old_values"]
    assert "Node count: Not provided" in datatable.data[0]["new_values"]
    assert "Edge count: Not provided" in datatable.data[0]["new_values"]
    assert "Release version: 1.0.0" in datatable.data[0]["old_values"]
    assert "Build version: new-build" in datatable.data[0]["new_values"]
    for column_id in ("old_values", "new_values"):
        assert {
            "if": {"column_id": column_id},
            "whiteSpace": "pre-line",
            "overflowWrap": "anywhere",
            "wordBreak": "break-word",
            "minWidth": "16rem",
            "maxWidth": "28rem",
            "height": "auto",
        } in datatable.style_data_conditional


def test_subgraph_changes_table_hides_changed_fields_for_added_removed_only() -> None:
    table = comparison_components._subgraph_changes_table(
        (
            SubgraphChange(
                source_id="ctd",
                name="ctd",
                status="removed",
                changed_fields=("Removed",),
                old_values="Release version: 1.0.0",
                new_values="None",
            ),
        )
    )
    datatable = _find_datatables(table)[0]

    assert {"name": "Changed Fields", "id": "changed_fields"} not in datatable.columns
    assert "changed_fields" not in datatable.data[0]


def test_comparison_dashboard_renders_schema_change_visuals() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    cache = InMemoryMetadataCache()
    session_id = "test-session"
    first = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    second = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )
    cache.set(session_id, "first", first)
    cache.set(session_id, "second", second)

    dashboard = page_module._comparison_dashboard(
        cache,
        KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id,
        [
            {"cache_key": "first", "kind": "upload", "label": "Translator KG Open"},
            {"cache_key": "second", "kind": "upload", "label": "ROBOKOP"},
        ],
    )
    text = " ".join(_flatten_text(dashboard))
    overview_table = _find_elements_by_class(dashboard, "comparison-overview-table")[0]
    overview_text = " ".join(_flatten_text(overview_table))
    schema_sections = _find_elements_by_class(dashboard, "comparison-pair-card")

    assert schema_sections
    assert "Schema-Level Differences:" in " ".join(_flatten_text(schema_sections[0]))
    assert "Subgraph Source Changes" not in " ".join(_flatten_text(schema_sections[0]))
    assert _find_elements_by_class(schema_sections[0], "schema-diff-section")

    assert "Node Category Changes" in text
    assert "ID prefixes" in text
    assert "Attributes" in text
    assert "Edge Triple Changes" in text
    assert "Primary sources" in text
    assert "Subject prefixes" in text
    assert "Object prefixes" in text
    assert "Top Change Heatmap" in text
    assert "Attribute" in text
    assert "Translator KG Open -> ROBOKOP" in text
    assert "one sequential scale for normalized changes" in text
    assert "0.5" in text
    assert "1.0" in text
    assert "Blue stripe: increase" in text
    assert "Red stripe: decrease" in text
    assert len(_find_elements_by_class(dashboard, "comparison-heatmap-table")) == 1
    assert len(_find_elements_by_class(dashboard, "heatmap-legend")) == 1
    legend = _find_elements_by_class(dashboard, "heatmap-legend")[0]
    limit_input = _find_elements_by_type(legend, "Input")[0]
    assert limit_input.id == "heatmap-row-limit"
    assert limit_input.value == 20
    assert limit_input.min == 1
    assert "max" not in limit_input.to_plotly_json()["props"]
    assert limit_input.step == 1
    assert limit_input.debounce is True
    limit_control = _find_elements_by_class(legend, "heatmap-row-limit-control")[0]
    hint = _find_elements_by_class(limit_control, "heatmap-row-limit-hint")[0]
    assert hint.children == "Press Enter or click outside to apply."
    assert "TOP ITEMS (20 by default)." in text
    error = _find_elements_by_class(limit_control, "heatmap-row-limit-error")[0]
    assert error.children == "Enter a positive whole number."
    assert error.role == "alert"
    assert "Overall Node and Edge Composition Summary Changes" in text
    assert "Node type" in text
    assert "Edge type" in text
    assert len(_find_elements_by_class(dashboard, "schema-summary-card")) > 0
    assert len(_find_elements_by_class(dashboard, "schema-summary-card-grid")) > 0
    assert len(_find_elements_by_class(dashboard, "schema-summary-card-column")) > 0
    assert "Nodes:" in overview_text
    assert "Edges:" in overview_text
    json_button = _find_elements_by_class(dashboard, "schema-diff-download-button")[0]
    report_button = _find_elements_by_class(dashboard, "comparison-report-download-button")[0]
    assert json_button.children == "Download JSON"
    assert json_button.title == (
        "Selected graph schema difference will be downloaded as JSON."
    )
    assert not json_button.disabled
    assert report_button.children == "Download report"
    assert report_button.title == (
        "Download a static HTML report for this graph comparison."
    )
    

def test_schema_diff_download_data_exports_orion_diff_json() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    cache = InMemoryMetadataCache()
    session_id = "test-session"
    first = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    second = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )
    cache.set(session_id, "first", first)
    cache.set(session_id, "second", second)

    data = page_module._schema_diff_download_data(
        cache,
        KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id,
        [
            {"cache_key": "first", "kind": "upload", "label": "Translator KG Open"},
            {"cache_key": "second", "kind": "upload", "label": "ROBOKOP"},
        ],
    )
    payload = json.loads(data["content"])

    assert data["filename"] == "schema-diff-translator-kg-open.json"
    assert data["type"] == "application/json"
    assert payload["comparisons"][0]["baseline"]["label"] == "Translator KG Open"
    assert payload["comparisons"][0]["comparison"]["label"] == "ROBOKOP"
    assert "diff" in payload["comparisons"][0]["schema_diff"]
    assert "nodes_summary" in payload["comparisons"][0]["schema_diff"]["diff"]
    

def test_comparison_report_download_data_exports_static_html_report() -> None:
    create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")

    cache = InMemoryMetadataCache()
    session_id = "test-session"
    first = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    second = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )
    cache.set(session_id, "first", first)
    cache.set(session_id, "second", second)

    data = page_module._comparison_report_download_data(
        cache,
        KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id,
        [
            {"cache_key": "first", "kind": "upload", "label": "Translator KG Open"},
            {"cache_key": "second", "kind": "upload", "label": "ROBOKOP"},
        ],
    )

    assert data["filename"] == "comparison-report-translator-kg-open.html"
    assert data["type"] == "text/html"
    assert data["content"].startswith("<!doctype html>")
    assert "Comparison Overview" in data["content"]
    assert "Top Change Heatmap" in data["content"]
    assert "Overall Node and Edge Composition Summary Changes" in data["content"]
    assert "Node Category Changes" in data["content"]
    assert "Edge Triple Changes" in data["content"]
    assert "Schema-Level Differences:" in data["content"]
    assert "Translator KG Open" in data["content"]
    assert "ROBOKOP" in data["content"]


def test_schema_difference_panels_hide_added_removed_percentages() -> None:
    added_count = CountDelta(old=0, new=5, delta=5, percent_change=100.0)
    removed_count = CountDelta(old=7, new=0, delta=-7, percent_change=-100.0)
    changed_count = CountDelta(old=10, new=12, delta=2, percent_change=20.0)

    added_cell = comparison_components._schema_count_cell(
        added_count,
        max_delta=7,
        status="added",
    )
    removed_group = comparison_components._schema_map_group(
        "removed",
        (
            MapEntryChange(
                label="obsolete",
                status="removed",
                count=removed_count,
            ),
        ),
        max_delta=7,
    )
    changed_group = comparison_components._schema_map_group(
        "changed",
        (
            MapEntryChange(
                label="updated",
                status="changed",
                count=changed_count,
            ),
        ),
        max_delta=7,
    )

    assert "100.00%" not in " ".join(_flatten_text(added_cell))
    assert "100.00%" not in " ".join(_flatten_text(removed_group))
    assert "+20.00%" in " ".join(_flatten_text(changed_group))
    assert "Baseline: 0" in _find_elements_by_class(added_cell, "comparison-glyph")[0].title
    assert "Percent change" not in _find_elements_by_class(
        removed_group,
        "schema-map-delta",
    )[0].title
    assert "Baseline: 10" in _find_elements_by_class(
        changed_group,
        "schema-map-delta",
    )[0].title
    assert "Comparison: 12" in _find_elements_by_class(
        changed_group,
        "schema-map-delta",
    )[0].title
    assert "Percent change" not in _find_elements_by_class(
        changed_group,
        "schema-map-delta",
    )[0].title


@pytest.mark.parametrize("baseline_name,target_name", [
    ("alliance", "translator_kg_open"),
    ("alliance", "robokopkg"),
    ("translator_kg_open", "robokopkg"),
])
def test_schema_summary_keeps_type_cards_together_in_lightest_column(
    baseline_name: str, target_name: str,
) -> None:
    graphs = [parse_graph_metadata(
        load_fixture(f"{name}.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json") if name == "robokopkg" else None,
    ) for name in (baseline_name, target_name)]
    schema = comparison_components.compare(graphs).comparisons[0].schema
    summary = comparison_components._schema_summary_table(schema, pair_index=0)
    columns = _find_elements_by_class(summary, "schema-summary-card-column")
    type_group = _find_elements_by_class(summary, "schema-summary-type-group")[0]
    assert [card.children[0].children for card in type_group.children] == ["Node type", "Edge type"]
    weights = []
    for column in columns:
        cards = [card for card in column.children if card is not type_group]
        weights.append(sum(
            3 + len(_find_elements_by_class(card, "schema-map-row"))
            + 2 * len(_find_elements_by_class(card, "schema-map-group-heading"))
            + 2 * len(_find_elements_by_class(card, "schema-more-button"))
            for card in cards
        ))
    lightest = min(range(len(columns)), key=lambda index: weights[index])
    assert columns[lightest].children[-1] is type_group
    titles = [card.children[0].children
              for card in _find_elements_by_class(summary, "schema-summary-card")]
    assert len(titles) == len(set(titles))

    map_fields = (
        "node_id_prefix_changes", "node_attribute_changes", "edge_predicate_changes",
        "edge_source_changes", "edge_source_predicate_changes", "edge_qualifier_changes",
        "edge_attribute_changes",
    )
    populated = [field for field in map_fields if getattr(schema, field)]
    for map_count in (0, 1, 2):
        reduced = replace(schema, **{
            field: () for field in map_fields if field not in populated[:map_count]
        })
        reduced_summary = comparison_components._schema_summary_table(reduced, pair_index=0)
        assert len(_find_elements_by_class(
            reduced_summary, "schema-summary-card-column",
        )) == 3
        assert len(_find_elements_by_class(reduced_summary, "schema-summary-type-group")) == 1
        assert len(_find_elements_by_class(
            reduced_summary, "schema-summary-card",
        )) == len(map_fields) + 2
        assert _flatten_text(reduced_summary).count("No changes") == len(map_fields) - map_count
    single_type = replace(reduced, node_type_count=None)
    single_summary = comparison_components._schema_summary_table(single_type)
    single_group = _find_elements_by_class(single_summary, "schema-summary-type-group")[0]
    assert [card.children[0].children for card in single_group.children] == ["Edge type"]
    empty = replace(schema, node_type_count=None, edge_type_count=None,
                    **dict.fromkeys(map_fields, ()))
    empty_summary = comparison_components._schema_summary_table(empty)
    assert not _find_elements_by_class(empty_summary, "schema-summary-type-group")
    assert _flatten_text(empty_summary).count("No changes") == len(map_fields)


def test_heatmap_row_limit_callback_uses_cached_graphs_and_selected_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    session_id = "heatmap-row-limit-session"
    states = []
    for graph_id in ("alliance", "translator_kg_open", "robokopkg"):
        graph = parse_graph_metadata(
            load_fixture(f"{graph_id}.graph-metadata.json"),
            schema_data=load_fixture("robokopkg.schema.json") if graph_id == "robokopkg" else None,
        )
        cache.set(session_id, graph_id, graph)
        states.append({"cache_key": graph_id, "kind": "upload", "label": graph_id})
    page_module.register_callbacks(
        app,
        cache=cache,
        kgx_client=KgxStorageClient("https://kgx-storage.example/releases"),
        url_client=UrlMetadataClient(("https://metadata.example",)),
    )
    callback = app.callback_map["comparison-heatmap-content.children"]
    update_heatmap = callback["callback"].__wrapped__
    dashboard = page_module._comparison_dashboard(
        cache, KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id, states, "translator_kg_open",
    )
    token = next(
        store.data for store in _find_elements_by_type(dashboard, "Store")
        if store.id == "comparison-result-token"
    )
    page_module._comparison_dashboard(
        cache, KgxStorageClient("https://kgx-storage.example/releases"),
        UrlMetadataClient(("https://metadata.example",)),
        session_id, states, "robokopkg",
    )
    render_overview = app.callback_map["overview-panel.children"]["callback"].__wrapped__
    render_overview([], None, session_id)
    def unexpected_compare(*args: object, **kwargs: object) -> None:
        raise AssertionError("A heatmap update must reuse the comparison snapshot")

    monkeypatch.setattr(page_module, "compare", unexpected_compare)

    assert callback["inputs"] == [{"id": "heatmap-row-limit", "property": "value"}]
    for row_limit, expected_rows in ((5, 5), (35, 35), (150, 150), (None, 20)):
        table = update_heatmap(row_limit, token, session_id)
        assert len(_find_elements_by_type(table, "Tbody")[0].children) == expected_rows
        assert "translator_kg_open" in _flatten_text(table.children[0])[2]
        assert "alliance" in _flatten_text(table.children[0])[2]
        assert not _find_elements_by_type(table, "Input")

    for selected_token, selected_session in (
        (None, session_id), ("stale-token", session_id), (token, None)
    ):
        message = update_heatmap(5, selected_token, selected_session)
        assert "Comparison expired or changed" in " ".join(_flatten_text(message))


def test_schema_dialog_pages_large_remaining_data_without_recomputing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    page_module = _registered_page_module("dashboard")
    cache = InMemoryMetadataCache()
    session_id = "schema-detail-session"
    states = []
    for name in ("alliance", "translator_kg_open", "robokopkg"):
        graph = parse_graph_metadata(
            load_fixture(f"{name}.graph-metadata.json"),
            schema_data=load_fixture("robokopkg.schema.json") if name == "robokopkg" else None,
        )
        cache.set(session_id, name, graph)
        states.append({"cache_key": name, "kind": "upload", "label": name})
    kgx_client = KgxStorageClient("https://kgx-storage.example/releases")
    url_client = UrlMetadataClient(("https://metadata.example",))
    page_module.register_callbacks(app, cache=cache, kgx_client=kgx_client, url_client=url_client)
    dashboard = page_module._comparison_dashboard(
        cache, kgx_client, url_client, session_id, states
    )
    stores = _find_elements_by_type(dashboard, "Store")
    token = next(store.data for store in stores if store.id == "comparison-result-token")
    assert isinstance(token, str)
    assert all(isinstance(getattr(store, "data", None), (str, type(None))) for store in stores)
    result = load_comparison(cache, session_id, token)
    assert result is not None
    schema = result.comparisons[1].schema
    assert len(schema.node_attribute_changes) > 1000
    for table in _find_elements_by_class(dashboard, "schema-edge-table"):
        assert len(_find_elements_by_type(table, "Tbody")[0].children) == 25
        assert len(_find_elements_by_class(table, "schema-map-row")) <= 27 * 5 * 8 * 3

    dialog = next(
        item for item in _find_elements_by_type(dashboard, "Dialog")
        if item.id == "schema-changes-dialog"
    )
    assert not _find_elements_by_class(dialog, "schema-map-row")
    assert not _find_elements_by_class(dialog, "schema-rich-table")
    assert [button.children for button in _find_elements_by_type(dialog, "Button")] == ["Close"]
    assert _find_elements_by_type(dialog, "Store")[0].id == "schema-detail-selection"
    more_buttons = _find_elements_by_class(dashboard, "schema-more-button")
    button = next(
        item for item in more_buttons
        if item.id == {"type": "schema-more", "pair": 1, "category": "node_attribute_changes"}
    )
    remaining = split_map_changes(schema.node_attribute_changes, 25)[1]
    assert len(remaining) > 1000
    assert button.children == f"View remaining changes ({len(remaining):,})"
    assert getattr(button, "data-dialog-target") == "schema-changes-dialog"
    assert len({json.dumps(item.id, sort_keys=True) for item in more_buttons}) == len(more_buttons)

    def unexpected_compare(*args: object, **kwargs: object) -> None:
        raise AssertionError("Opening details must not rerun comparison")

    monkeypatch.setattr(page_module, "compare", unexpected_compare)
    monkeypatch.setattr(page_module, "load_comparison", unexpected_compare)
    context = SimpleNamespace(triggered=[{"value": 1}], triggered_id=button.id)
    monkeypatch.setattr(page_module, "callback_context", context)
    registered_callback = next(
        entry["callback"].__wrapped__ for key, entry in app.callback_map.items()
        if "schema-detail-content.children" in key
    )
    dialog_views = None
    responses = []

    def callback(*args: object) -> tuple[object, object]:
        nonlocal dialog_views
        response, current_selection = registered_callback(*args)
        responses.append(response)
        if isinstance(response, Patch):
            assert isinstance(dialog_views, list)
            for operation in response.to_plotly_json()["operations"]:
                assert operation["operation"] == "Assign"
                index, props, attribute = operation["location"]
                assert props == "props"
                setattr(dialog_views[index], attribute, operation["params"]["value"])
        else:
            dialog_views = response
        if isinstance(dialog_views, list):
            active = int(bool(current_selection and current_selection.get("parents")))
            return dialog_views[active].children, current_selection
        return dialog_views, current_selection

    content, selection = callback([1], [], None, token, session_id)
    assert len(json.dumps(selection)) < 512
    assert "alliance -> robokopkg" in _flatten_text(content)
    header = _find_elements_by_class(content, "schema-dialog-header")[0]
    assert "Node attributes" in _flatten_text(header)
    assert "alliance -> robokopkg" in _flatten_text(header)
    controls = _find_elements_by_type(header, "Button")
    assert [getattr(item, "aria-label", item.children) for item in controls] == [
        "First page", "Previous page", "Next page", "Last page", "Close"
    ]
    assert [item.disabled for item in controls[:4]] == [True, True, False, False]
    for control in controls[:4]:
        assert control.title == getattr(control, "aria-label")
        assert getattr(control.children, "aria-hidden") == "true"
    assert [item.children.children for item in controls[:4]] == ["«", "‹", "›", "»"]
    assert not _find_elements_by_class(content, "schema-map-group-heading")
    assert len(_find_elements_by_class(content, "schema-map-row")) == 50
    labels = [item.children for item in _find_elements_by_class(content, "schema-map-label")]
    assert labels == [
        change.label for _, group in comparison_components._group_map_changes(remaining[:50])
        for change in group
    ]
    summary = " ".join(_flatten_text(content))
    assert f"Showing 1–50 of {len(remaining):,} remaining additions" in summary
    assert "Showing all" not in " ".join(_flatten_text(content))
    assert not _find_elements_by_class(content, "schema-more-button")
    assert len(json.dumps(content, cls=PlotlyJSONEncoder)) < 200_000

    context.triggered_id = {"type": "schema-page", "direction": "next"}
    following, next_selection = callback([1], [1], selection, token, session_id)
    assert next_selection["page"] == 1
    assert all(
        not item.disabled for item in _find_elements_by_class(following, "schema-page-button")
    )
    following_labels = _find_elements_by_class(following, "schema-map-label")
    assert {item.children for item in following_labels} == {
        item.label for item in remaining[50:100]
    }
    context.triggered_id = {"type": "schema-page", "direction": "previous"}
    previous, _ = callback([1], [1], next_selection, token, session_id)
    assert _flatten_text(previous) == _flatten_text(content)
    context.triggered_id = {"type": "schema-page", "direction": "next"}
    with pytest.raises(PreventUpdate):
        callback([1], [1], dict(selection, token="stale-token"), token, session_id)
    context.triggered_id = {"type": "schema-page", "direction": "last"}
    last, last_selection = callback([1], [1], selection, token, session_id)
    details = remaining_schema_changes(result, 1, "node_attribute_changes")
    assert last_selection["page"] == details.page_count - 1
    assert 3 <= len(_find_elements_by_class(last, "schema-map-row")) <= 52
    last_controls = _find_elements_by_type(
        _find_elements_by_class(last, "schema-dialog-header")[0], "Button"
    )
    assert [item.disabled for item in last_controls[:4]] == [False, False, True, True]
    assert {item.children for item in _find_elements_by_class(last, "schema-map-label")} == {
        item.label for item in remaining[last_selection["page"] * 50:]
    }
    context.triggered_id = {"type": "schema-page", "direction": "first"}
    first, first_selection = callback([1], [1], last_selection, token, session_id)
    assert first_selection == selection
    assert _flatten_text(first) == _flatten_text(content)

    context.triggered_id = {"type": "schema-more", "pair": 1, "category": "edge_changes"}
    edge_content, edge_selection = callback([1], [], last_selection, token, session_id)
    assert edge_selection["page"] == 0
    edge_table = _find_elements_by_class(edge_content, "schema-edge-table")[0]
    edge_rows = _find_elements_by_type(edge_table, "Tbody")[0].children
    assert len(edge_rows) == 50
    assert all(
        item.id["category"] != "edge_changes"
        for item in _find_elements_by_class(edge_content, "schema-more-button")
    )
    assert _find_elements_by_type(edge_content, "Details")[0].open is True
    context.triggered_id = {"type": "schema-page", "direction": "next"}
    next_edges, next_edge_selection = callback([1], [1], edge_selection, token, session_id)
    assert all(
        75 <= int(item.id["category"].split("/")[1]) < 125
        for item in _find_elements_by_class(next_edges, "schema-more-button")
    )
    child_button = _find_elements_by_class(next_edges, "schema-more-button")[0]
    context.triggered_id = child_button.id
    child, child_selection = callback([1], [], next_edge_selection, token, session_id)
    assert dialog_views[0].children is next_edges
    assert dialog_views[0].style == {"display": "none"}
    mounted_buttons = _find_elements_by_type(dialog_views, "Button")
    mounted_ids = [json.dumps(item.id, sort_keys=True) for item in mounted_buttons
                   if hasattr(item, "id")]
    assert len(mounted_ids) == len(set(mounted_ids))
    context.triggered_id = {"type": "schema-page", "direction": "next", "level": 0}
    with pytest.raises(PreventUpdate):
        callback([1], [1], child_selection, token, session_id)
    assert child_selection["parents"] == [{"pair": 1, "category": "edge_changes", "page": 1}]
    assert len(json.dumps(child_selection)) < 512
    child_header = _find_elements_by_class(child, "schema-dialog-header")[0]
    child_buttons = [item.children for item in _find_elements_by_type(child_header, "Button")]
    assert "Back" in child_buttons
    assert "Close" not in child_buttons
    context.triggered_id = {"type": "schema-page", "direction": "next"}
    _, child_next_selection = callback([1], [1], child_selection, token, session_id)
    assert child_next_selection["parents"] == child_selection["parents"]
    context.triggered_id = {"type": "schema-page", "direction": "last"}
    _, child_last_selection = callback([1], [1], child_next_selection, token, session_id)
    assert child_last_selection["parents"] == child_selection["parents"]
    context.triggered_id = {"type": "schema-page", "direction": "first"}
    _, child_next_selection = callback([1], [1], child_last_selection, token, session_id)
    assert child_next_selection == child_selection
    context.triggered_id = {"type": "schema-page", "direction": "back"}
    with monkeypatch.context() as back_context:
        back_context.setattr(page_module, "schema_detail_content", unexpected_compare)
        parent, restored_selection = callback([1], [1], child_next_selection, token, session_id)
    assert parent is next_edges
    assert dialog_views[0].style == {}
    assert dialog_views[1].children is None
    assert len(json.dumps(responses[-1], cls=PlotlyJSONEncoder)) < 512
    assert restored_selection == next_edge_selection
    assert _flatten_text(parent) == _flatten_text(next_edges)
    assert not restored_selection["parents"]
    with pytest.raises(PreventUpdate):
        callback([1], [1], dict(child_selection, token="stale"), token, session_id)
    with pytest.raises(PreventUpdate):
        callback([1], [1], restored_selection, token, session_id)
    context.triggered_id = {"type": "schema-more", "pair": 1,
                            "category": "edge_changes/0/attribute_changes"}
    inline_child, inline_selection = callback([1], [], restored_selection, token, session_id)
    assert not inline_selection["parents"]
    inline_header = _find_elements_by_class(inline_child, "schema-dialog-header")[0]
    assert "Back" not in [item.children for item in _find_elements_by_type(inline_header, "Button")]

    context.triggered_id = {"type": "schema-more", "pair": 0, "category": "node_attribute_changes"}
    small, small_selection = callback([1], [], edge_selection, token, session_id)
    assert small_selection["page"] == 0
    assert not small_selection["parents"]
    assert not _find_elements_by_class(small, "schema-map-row")
    assert [button.children for button in _find_elements_by_type(small, "Button")] == ["Close"]
    context.triggered_id = button.id
    denied, _ = callback([1], [], selection, token, "another-session")
    assert "Comparison expired or changed" in " ".join(_flatten_text(denied))
    assert [button.children for button in _find_elements_by_type(denied, "Button")] == ["Close"]
    context.triggered_id = {"type": "schema-more", "pair": 1, "category": "invalid"}
    unavailable, _ = callback([1], [], selection, token, session_id)
    assert "The requested schema category is unavailable." in _flatten_text(unavailable)
    unavailable_buttons = _find_elements_by_type(unavailable, "Button")
    assert [button.children for button in unavailable_buttons] == ["Close"]
    context.triggered = [{"value": 0}]
    with pytest.raises(PreventUpdate):
        callback([0], [], selection, token, session_id)
    context.triggered = [{"value": [0, 0]}]
    context.triggered_id = {"type": "schema-page", "direction": ["ALL"]}
    with pytest.raises(PreventUpdate):
        callback([1], [0, 0], selection, token, session_id)
    context.triggered = [{"value": 1}]
    row_index = max(
        range(len(schema.node_changes)),
        key=lambda index: len(schema.node_changes[index].attribute_changes),
    )
    context.triggered_id = {
        "type": "schema-more", "pair": 1,
        "category": f"node_changes/{row_index}/attribute_changes",
    }
    nested, nested_selection = callback([1], [], next_selection, token, session_id)
    assert nested_selection["page"] == 0
    labels = [item.children for item in _find_elements_by_class(nested, "schema-map-label")]
    nested_remaining = split_map_changes(schema.node_changes[row_index].attribute_changes, 6)[1]
    assert set(labels) == {change.label for change in nested_remaining[:50]}
    assert len(labels) == 50
    assert len(nested_remaining) > 1000
    context.triggered_id = button.id
    store_comparison(cache, session_id, result)
    refreshed, _ = callback([1], [], selection, token, session_id)
    assert len(_find_elements_by_class(refreshed, "schema-map-row")) == 50
    cache.delete(session_id, f"comparison:{token}:index")
    context.triggered_id = {"type": "schema-page", "direction": "back", "level": 1}
    expired, expired_selection = callback([1], [1], child_selection, token, session_id)
    assert expired_selection is None
    assert "Comparison expired or changed" in " ".join(_flatten_text(expired))
    assert not isinstance(responses[-1], Patch)


def test_heatmap_complete_candidates_include_changes_beyond_old_schema_cutoff() -> None:
    baseline = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    target = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )
    pair = comparison_components.compare([baseline, target]).comparisons[0]
    candidates = tuple(comparison_components._heatmap_pair_cells(pair))
    attribute_labels = {label for _, group, label, _ in candidates if group == "Node attributes"}
    assert len(attribute_labels) == len(pair.schema.node_attribute_changes)
    assert len(attribute_labels) > 1000
    assert pair.schema.node_attribute_changes[-1].label in attribute_labels


def test_compact_schema_groups_keep_status_labels_only_when_needed() -> None:
    baseline = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    target = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )
    schema = comparison_components.compare([baseline, target]).comparisons[0].schema
    changes = schema.node_id_prefix_changes
    groups = comparison_components._group_map_changes(changes)
    assert len(groups) > 1
    mixed = comparison_components._schema_map_cell(changes, limit=None, compact_headings=True)
    headings = _find_elements_by_class(mixed, "schema-map-group-heading")
    assert [heading.children for heading in headings] == [status for status, _ in groups]
    assert len(_find_elements_by_class(mixed, "schema-map-row")) == len(changes)
    for _, group in groups:
        single = comparison_components._schema_map_cell(group, limit=None, compact_headings=True)
        assert not _find_elements_by_class(single, "schema-map-group-heading")
        assert len(_find_elements_by_class(single, "schema-map-row")) == len(group)


def test_adaptive_inline_and_modal_rendering_boundaries() -> None:
    baseline = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    target = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )
    result = comparison_components.compare([baseline, target])
    pair = result.comparisons[0]
    changes = tuple(
        change for change in pair.schema.node_attribute_changes if change.status == "added"
    )
    for limit in (6, 25):
        for extra in (1, 2, 3):
            cell = comparison_components._schema_map_cell(
                changes[:limit + extra], limit=limit, pair_index=0,
                category="node_attribute_changes",
            )
            rows = _find_elements_by_class(cell, "schema-map-row")
            buttons = _find_elements_by_class(cell, "schema-more-button")
            assert len(rows) == (limit + extra if extra <= 2 else limit)
            if extra <= 2:
                assert not buttons
            else:
                assert buttons[0].children == "View remaining changes (3)"
    for section, render in (
        ("node_changes", comparison_components._node_schema_table),
        ("edge_changes", comparison_components._edge_schema_table),
    ):
        for extra in (1, 2, 3):
            table = render(getattr(pair.schema, section)[:25 + extra], pair_index=0)
            rows = _find_elements_by_type(table, "Tbody")[0].children
            assert len(rows) == (25 + extra if extra <= 2 else 25)
            buttons = [item for item in _find_elements_by_class(table, "schema-more-button")
                       if item.id["category"] == section]
            assert bool(buttons) == (extra == 3)
    for remaining_count in (3, 51, 52, 53, 102):
        selected_pair = replace(pair, schema=replace(
            pair.schema, node_attribute_changes=changes[:25 + remaining_count]
        ))
        selected_result = replace(result, comparisons=(selected_pair,))
        details = remaining_schema_changes(selected_result, 0, "node_attribute_changes")
        content = comparison_components.schema_detail_content(details)
        header = _find_elements_by_class(content, "schema-dialog-header")[0]
        buttons = _find_elements_by_type(header, "Button")
        assert [getattr(item, "aria-label", item.children) for item in buttons] == (
            ["Close"] if remaining_count <= 52 else
            ["First page", "Previous page", "Next page", "Last page", "Close"]
        )
        expected_rows = remaining_count if remaining_count <= 52 else 50
        assert len(_find_elements_by_class(content, "schema-map-row")) == expected_rows
        child_content = comparison_components.schema_detail_content(details, has_parent=True)
        child_header = _find_elements_by_class(child_content, "schema-dialog-header")[0]
        child_buttons = _find_elements_by_type(child_header, "Button")
        assert [getattr(item, "aria-label", item.children) for item in child_buttons] == (
            ["Back"] if remaining_count <= 52 else
            ["Back", "First page", "Previous page", "Next page", "Last page"]
        )


@pytest.mark.parametrize("reverse, noun", [(False, "additions"), (True, "removals")])
def test_schema_dialog_summary_identifies_remaining_status(reverse: bool, noun: str) -> None:
    graphs = [
        parse_graph_metadata(load_fixture("alliance.graph-metadata.json")),
        parse_graph_metadata(
            load_fixture("robokopkg.graph-metadata.json"),
            schema_data=load_fixture("robokopkg.schema.json"),
        ),
    ]
    result = comparison_components.compare(graphs[::-1] if reverse else graphs)
    pair = result.comparisons[0]
    status = "removed" if reverse else "added"
    changes = tuple(
        change for change in pair.schema.node_attribute_changes if change.status == status
    )
    for remaining_count in (3, 53):
        selected_pair = replace(pair, schema=replace(
            pair.schema, node_attribute_changes=changes[:25 + remaining_count]
        ))
        selected = replace(result, comparisons=(selected_pair,))
        first = remaining_schema_changes(selected, 0, "node_attribute_changes")
        for page in range(first.page_count):
            details = remaining_schema_changes(selected, 0, "node_attribute_changes", page)
            content = comparison_components.schema_detail_content(details)
            summary = _find_elements_by_class(content, "comparison-table-note")[0].children
            assert f"remaining {noun}" in summary
            assert "total changes" in summary
            assert not _find_elements_by_class(content, "schema-map-group-heading")


@pytest.mark.parametrize("limit", [6, 25])
def test_schema_status_headings_include_changes_beyond_inline_limit(limit: int) -> None:
    baseline = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    target = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )
    schema = comparison_components.compare([baseline, target]).comparisons[0].schema
    truncated_groups = 0
    for category in (
        "node_id_prefix_changes", "node_attribute_changes", "edge_predicate_changes",
        "edge_source_changes", "edge_attribute_changes",
    ):
        changes = getattr(schema, category)
        cell = comparison_components._schema_map_cell(
            changes, limit=limit, pair_index=0, category=category,
        )
        inline_count = 0
        for status in {change.status for change in changes}:
            total = sum(change.status == status for change in changes)
            visible = adaptive_inline_count(total, limit)
            inline_count += visible
            group = _find_elements_by_class(cell, f"schema-map-group-{status}")[0]
            heading = _find_elements_by_class(group, "schema-map-group-heading")[0]
            assert heading.children == f"{total:,} {status}"
            assert len(_find_elements_by_class(group, "schema-map-row")) == visible
            if visible < total:
                truncated_groups += 1
                assert f"Showing {visible:,} of {total:,}" in " ".join(_flatten_text(group))
            assert visible > 0
        assert len(_find_elements_by_class(cell, "schema-map-row")) == inline_count
        if len(changes) > inline_count:
            button = _find_elements_by_class(cell, "schema-more-button")[0]
            assert button.children == f"View remaining changes ({len(changes) - inline_count:,})"
        else:
            assert not _find_elements_by_class(cell, "schema-more-button")
    assert truncated_groups > 0


def test_heatmap_changed_cell_shows_percent_and_scales_by_shared_changes() -> None:
    small_change = comparison_components._HeatmapCell(
        count=CountDelta(
            old=100_000,
            new=58_839,
            delta=-41_161,
            percent_change=-10.0,
        ),
        status="changed",
    )
    large_change = comparison_components._HeatmapCell(
        count=CountDelta(
            old=5_000_000,
            new=2_745_844,
            delta=-2_254_156,
            percent_change=-10.0,
        ),
        status="changed",
    )
    rows = (
        comparison_components._HeatmapRow(
            key="small",
            group="Edge triples",
            label="Small absolute change",
            cells=(small_change,),
            impact=0,
        ),
        comparison_components._HeatmapRow(
            key="large",
            group="Edge triples",
            label="Large absolute change",
            cells=(large_change,),
            impact=0,
        ),
    )
    scale = comparison_components._heatmap_scale(rows)

    small_cell = comparison_components._heatmap_cell(
        small_change,
        scale=scale,
    )
    large_cell = comparison_components._heatmap_cell(
        large_change,
        scale=scale,
    )

    assert "-41,161" in " ".join(_flatten_text(small_cell))
    assert "-10.00%" in " ".join(_flatten_text(small_cell))
    assert "-2,254,156" in " ".join(_flatten_text(large_cell))
    assert "-10.00%" in " ".join(_flatten_text(large_cell))
    assert small_cell.style["background"] != large_cell.style["background"]


def test_heatmap_removed_cell_hides_percent_but_scales_by_magnitude() -> None:
    small_removed = comparison_components._HeatmapCell(
        count=CountDelta(
            old=41_161,
            new=0,
            delta=-41_161,
            percent_change=None,
        ),
        status="removed",
    )
    large_removed = comparison_components._HeatmapCell(
        count=CountDelta(
            old=2_254_156,
            new=0,
            delta=-2_254_156,
            percent_change=None,
        ),
        status="removed",
    )
    rows = (
        comparison_components._HeatmapRow(
            key="small",
            group="Edge triples",
            label="Small removed",
            cells=(small_removed,),
            impact=0,
        ),
        comparison_components._HeatmapRow(
            key="large",
            group="Edge triples",
            label="Large removed",
            cells=(large_removed,),
            impact=0,
        ),
    )
    scale = comparison_components._heatmap_scale(rows)

    small_ratio = comparison_components._heatmap_cell_visual_ratio(
        small_removed,
        scale=scale,
    )
    large_ratio = comparison_components._heatmap_cell_visual_ratio(
        large_removed,
        scale=scale,
    )
    small_cell = comparison_components._heatmap_cell(
        small_removed,
        scale=scale,
    )
    large_cell = comparison_components._heatmap_cell(
        large_removed,
        scale=scale,
    )

    assert comparison_components._heatmap_cell_percent_text(large_removed) is None
    assert large_ratio > small_ratio
    assert "-41,161" in " ".join(_flatten_text(small_cell))
    assert "-2,254,156" in " ".join(_flatten_text(large_cell))
    assert "100.00%" not in " ".join(_flatten_text(large_cell))
    assert small_cell.style["background"] != large_cell.style["background"]


def test_heatmap_ranking_reserves_rows_for_each_comparison_column() -> None:
    first_comparison_rows = tuple(
        comparison_components._HeatmapRow(
            key=f"first-{index}",
            group="Edge triples",
            label=f"First comparison row {index}",
            cells=(
                comparison_components._HeatmapCell(
                    count=CountDelta(
                        old=10_000_000 - index,
                        new=0,
                        delta=-(10_000_000 - index),
                        percent_change=None,
                    ),
                    status="removed",
                ),
                None,
            ),
            impact=0,
        )
        for index in range(25)
    )
    second_comparison_rows = tuple(
        comparison_components._HeatmapRow(
            key=f"second-{index}",
            group="Node categories",
            label=f"Second comparison row {index}",
            cells=(
                None,
                comparison_components._HeatmapCell(
                    count=CountDelta(
                        old=1_000 - index,
                        new=0,
                        delta=-(1_000 - index),
                        percent_change=None,
                    ),
                    status="removed",
                ),
            ),
            impact=0,
        )
        for index in range(5)
    )
    rows = first_comparison_rows + second_comparison_rows
    scale = comparison_components._heatmap_scale(rows)
    scored_rows = tuple(
        comparison_components._HeatmapRow(
            key=row.key,
            group=row.group,
            label=row.label,
            cells=row.cells,
            impact=sum(
                comparison_components._heatmap_cell_visual_ratio(cell, scale=scale)
                for cell in row.cells
                if cell
            ),
        )
        for row in rows
    )

    ranked = comparison_components._rank_heatmap_rows(
        scored_rows,
        scale=scale,
        comparison_count=2,
    )

    assert len(ranked) == comparison_components.HEATMAP_ROW_LIMIT
    assert sum(1 for row in ranked if row.cells[1] is not None) == 5
    for row_limit, expected_count in (
        (2, 2), (7.0, 7), (30, 30), (None, 20), (0, 20), (-1, 20), (1.5, 20),
        (True, 20), (float("nan"), 20), (float("inf"), 20), (1000, 30)
    ):
        limited = comparison_components._rank_heatmap_rows(
            scored_rows, scale=scale, comparison_count=2, row_limit=row_limit
        )
        assert len(limited) == expected_count
        if expected_count >= 2:
            assert any(row.cells[0] is not None for row in limited)
            assert any(row.cells[1] is not None for row in limited)
    many_rows = tuple(
        replace(row, key=f"{row.key}-{index}") for index in range(4) for row in scored_rows
    )
    for comparison_count in (1, 2):
        for row_limit, expected_count in ((110, 110), (1000, 120), (10**1000, 120)):
            expanded = comparison_components._rank_heatmap_rows(
                many_rows, scale=scale, comparison_count=comparison_count, row_limit=row_limit
            )
            assert len(expanded) == expected_count
            assert len({row.key for row in expanded}) == expected_count


def test_heatmap_ranking_uses_global_rows_first_for_multi_column_comparison() -> None:
    pair_specific_rows = tuple(
        comparison_components._HeatmapRow(
            key=f"pair-specific-{index}",
            group="Edge triples",
            label=f"Pair-specific row {index}",
            cells=(
                comparison_components._HeatmapCell(
                    count=CountDelta(
                        old=10_000_000 - index,
                        new=0,
                        delta=-(10_000_000 - index),
                        percent_change=None,
                    ),
                    status="removed",
                ),
                None,
            ),
            impact=0,
        )
        for index in range(25)
    )
    global_rows = tuple(
        comparison_components._HeatmapRow(
            key=f"global-{index}",
            group="Node categories",
            label=f"Global row {index}",
            cells=(
                comparison_components._HeatmapCell(
                    count=CountDelta(
                        old=100 + index,
                        new=0,
                        delta=-(100 + index),
                        percent_change=None,
                    ),
                    status="removed",
                ),
                comparison_components._HeatmapCell(
                    count=CountDelta(
                        old=90 + index,
                        new=0,
                        delta=-(90 + index),
                        percent_change=None,
                    ),
                    status="removed",
                ),
            ),
            impact=0,
        )
        for index in range(3)
    )
    rows = pair_specific_rows + global_rows
    scale = comparison_components._heatmap_scale(rows)
    scored_rows = tuple(
        comparison_components._HeatmapRow(
            key=row.key,
            group=row.group,
            label=row.label,
            cells=row.cells,
            impact=sum(
                comparison_components._heatmap_cell_visual_ratio(cell, scale=scale)
                for cell in row.cells
                if cell
            ),
        )
        for row in rows
    )

    ranked = comparison_components._rank_heatmap_rows(
        scored_rows,
        scale=scale,
        comparison_count=2,
    )

    ranked_keys = {row.key for row in ranked}
    assert all(row.key in ranked_keys for row in global_rows)
    assert all(row.key.startswith("global") for row in ranked[: len(global_rows)])
    assert all(
        comparison_components._heatmap_row_coverage(row) > 1
        for row in ranked[: len(global_rows)]
    )
    assert sum(1 for row in ranked if row.key.startswith("pair-specific")) < (
        comparison_components.HEATMAP_ROW_LIMIT
    )
    limited = comparison_components._rank_heatmap_rows(
        scored_rows, scale=scale, comparison_count=2, row_limit=2
    )
    assert len(limited) == 2
    assert all(row.key.startswith("global") for row in limited)


def _registered_page_module(module_basename: str) -> object:
    for page in page_registry.values():
        module_name = page["module"]
        if module_name.endswith(f".{module_basename}"):
            return import_module(module_name)
    raise AssertionError(f"Page module {module_basename!r} was not registered")


def _flatten_text(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    children = getattr(value, "children", None)
    if children is None:
        return []
    if isinstance(children, list):
        output = []
        for child in children:
            output.extend(_flatten_text(child))
        return output
    return _flatten_text(children)


def _find_datatables(value: object) -> list[object]:
    if value.__class__.__name__ == "DataTable":
        return [value]
    children = getattr(value, "children", None)
    if children is None:
        return []
    if isinstance(children, list):
        output = []
        for child in children:
            output.extend(_find_datatables(child))
        return output
    return _find_datatables(children)


def _find_elements_by_class(value: object, class_name: str) -> list[object]:
    classes = str(getattr(value, "className", "") or "").split()
    found = [value] if class_name in classes else []
    children = getattr(value, "children", None)
    if children is None:
        return found
    if isinstance(children, list):
        for child in children:
            found.extend(_find_elements_by_class(child, class_name))
        return found
    found.extend(_find_elements_by_class(children, class_name))
    return found


def _find_elements_by_type(value: object, type_name: str) -> list[object]:
    found = [value] if value.__class__.__name__ == type_name else []
    children = getattr(value, "children", None)
    if children is None:
        return found
    if isinstance(children, list):
        for child in children:
            found.extend(_find_elements_by_type(child, type_name))
        return found
    found.extend(_find_elements_by_type(children, type_name))
    return found


class _FakeUrlClient:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self.payloads = payloads

    def load_json(self, url: str) -> dict[str, object]:
        return self.payloads[url]
