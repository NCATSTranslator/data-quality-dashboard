from __future__ import annotations

from dataclasses import replace

import pytest

from graph_metadata_dashboard.constants import ALL_NODE_CATEGORIES_VALUE
from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata
from graph_metadata_dashboard.parsers.models import (
    EdgeTriple,
    KnowledgeSourcePredicateCount,
    NodeCategory,
)
from graph_metadata_dashboard.viz.figures import (
    SANKEY_BASE_HEIGHT,
    SANKEY_DEFAULT_NODE_PAD,
    contribution_chart_style,
    count_bar,
    filter_predicate_sankey_edges,
    filter_source_predicate_counts,
    knowledge_source_predicate_sankey,
    node_attribute_completeness_bar,
    node_attribute_selection,
    node_category_bar,
    predicate_sankey,
    sankey_highlight_colors,
    subgraph_contribution_bar,
    subject_object_category_pair_bar,
)
from tests.conftest import load_fixture


def test_node_attribute_selection_uses_summary_or_exact_category() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None
    schema = parsed.schema
    label, count, attributes = node_attribute_selection(schema, ALL_NODE_CATEGORIES_VALUE)
    assert label == "All categories"
    assert count == schema.total_node_count
    assert attributes == schema.nodes_summary["attributes"]
    node = schema.nodes[0]
    assert node_attribute_selection(schema, node.category) == (
        node.category, node.count, node.attributes,
    )
    assert node_attribute_selection(schema, "invalid") == (label, count, attributes)


def test_node_attribute_chart_bounds_search_and_reports_exact_coverage() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"),
                                  schema_data=load_fixture("robokopkg.schema.json"))
    assert parsed.schema is not None
    node = max(parsed.schema.nodes, key=lambda node: len(node.attributes))
    figure = node_attribute_completeness_bar(node.attributes, node.count)
    assert len(figure.data[0].x) == min(50, len(node.attributes))
    assert figure.data[0].orientation == "h"
    assert figure.layout.bargap == 0
    assert figure.layout.bargroupgap == 0
    assert figure.data[0].marker.line.width == 1
    first_attribute, first_count = next(iter(node.attributes.items()))
    assert figure.data[0].x[0] == pytest.approx(100 * first_count / node.count)
    assert list(figure.data[0].customdata[0]) == [first_attribute, first_count, node.count]
    attributes = {f"attribute-{index}": 2000 - index for index in range(1600)}
    bounded = node_attribute_completeness_bar(attributes, 2000)
    assert len(bounded.data[0].x) == 50
    assert len(bounded.to_json()) < 20000
    searched = node_attribute_completeness_bar(attributes, 2000, search=" ATTRIBUTE-1599 ")
    assert list(searched.data[0].x) == [pytest.approx(20.05)]
    assert list(searched.data[0].customdata[0]) == ["attribute-1599", 401, 2000]
    assert list(node_attribute_completeness_bar({"absent": 0}, 100).data[0].x) == [0]


@pytest.mark.parametrize("attributes,count,search,message", [
    ({}, 100, None, "No node attribute counts"),
    ({"name": 100}, 100, "no-match", "No attributes match"),
    ({"name": 1}, None, None, "Node count unavailable"),
    ({"name": 0}, 0, None, "No nodes in this selection"),
])
def test_node_attribute_chart_empty_states(
    attributes: dict[str, int], count: int | None, search: str | None, message: str,
) -> None:
    figure = node_attribute_completeness_bar(attributes, count, search=search)
    assert not figure.data[0].x
    assert message in figure.layout.annotations[0].text


def test_tiny_nonzero_attribute_coverage_has_visible_marker_without_distorting_bars() -> None:
    attributes = {"name": 1000000, "small": 500, "inheritance": 223, "absent": 0}
    figure = node_attribute_completeness_bar(attributes, 1000000)
    assert list(figure.data[0].x) == [100, 0.05, 0.0223, 0]
    assert len(figure.data) == 2
    assert figure.data[1].type == "scatter"
    assert list(figure.data[1].x) == [0.05, 0.0223]
    assert list(figure.data[1].y) == [1, 2]
    assert figure.data[1].marker.size == 8
    assert list(figure.data[1].customdata[1]) == ["inheritance", 223, 1000000]
    assert "%{x:.4f}%" in figure.data[1].hovertemplate
    zero = node_attribute_completeness_bar({"absent": 0}, 1000000)
    assert len(zero.data) == 1


def test_node_category_bar_shows_all_categories_with_compact_labels() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None

    figure = node_category_bar(parsed.schema.nodes)

    sorted_nodes = sorted(parsed.schema.nodes, key=lambda node: node.count, reverse=True)
    assert list(figure.data[0].x) == [node.category for node in sorted_nodes]
    assert list(figure.data[0].y) == [node.count for node in sorted_nodes]
    full_labels = [node.category.replace("biolink:", "") for node in sorted_nodes]
    assert list(figure.layout.xaxis.ticktext) == [
        label if len(label) <= 30 else f"{label[:27]}..." for label in full_labels
    ]
    assert figure.layout.title.text == f"{len(sorted_nodes)} Node Category Contribution"
    assert figure.layout.bargap == 0
    assert figure.layout.bargroupgap == 0
    assert figure.data[0].marker.line.width == 1
    assert figure.layout.xaxis.tickangle == -55
    assert figure.layout.xaxis.tickfont.size == 10
    assert figure.layout.height - figure.layout.margin.t - figure.layout.margin.b >= 267
    assert figure.layout.yaxis.type == "log"
    assert "%{customdata}" in figure.data[0].hovertemplate
    assert list(figure.data[0].customdata) == [node.category for node in sorted_nodes]


def test_node_category_bar_has_no_cutoff_and_preserves_distinct_category_ids() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"),
                                  schema_data=load_fixture("robokopkg.schema.json"))
    assert parsed.schema is not None
    template = parsed.schema.nodes[0]
    nodes = tuple(replace(template, category=f"biolink:Category{index}", count=index)
                  for index in range(65)) + (
        replace(template, category="Gene", count=200),
        replace(template, category="biolink:Gene", count=100),
        replace(template, category="custom:Category", count=0),
    )
    figure = node_category_bar(nodes, log_scale=False)
    assert len(figure.data[0].x) == 68
    assert figure.layout.title.text == "68 Node Category Contribution"
    assert list(figure.layout.xaxis.tickvals)[:2] == ["Gene", "biolink:Gene"]
    assert list(figure.layout.xaxis.ticktext)[:2] == ["Gene", "Gene"]
    assert "custom:Category" in figure.layout.xaxis.ticktext
    assert figure.layout.yaxis.type == "linear"


def test_node_category_bar_handles_empty_schema() -> None:
    nodes: tuple[NodeCategory, ...] = ()
    figure = node_category_bar(nodes)
    assert not figure.data[0].x
    assert figure.layout.title.text == "0 Node Category Contribution"


def test_node_category_labels_strip_all_prefixes_and_height_adapts_to_long_labels() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None
    template = parsed.schema.nodes[0]
    short = node_category_bar((replace(template, category="biolink:Gene"),))
    combined_category = "biolink:Protein,biolink:Drug"
    combined = node_category_bar((replace(template, category=combined_category),))
    assert list(combined.layout.xaxis.ticktext) == ["Protein,Drug"]
    assert list(combined.data[0].x) == [combined_category]
    long_category = ",".join(["biolink:MacromolecularComplex"] * 20)
    long = node_category_bar((replace(template, category=long_category),))
    assert "biolink:" not in long.layout.xaxis.ticktext[0]
    assert len(long.layout.xaxis.ticktext[0]) == 30
    assert long.layout.xaxis.ticktext[0].endswith("...")
    assert list(long.data[0].x) == [long_category]
    assert list(long.data[0].customdata) == [long_category]
    assert long.layout.height > combined.layout.height > short.layout.height
    for figure in (short, combined, long):
        assert figure.layout.margin.b == 24
        assert figure.layout.xaxis.automargin
        assert figure.layout.height - figure.layout.margin.t - figure.layout.margin.b >= 267


def test_contribution_charts_share_adaptive_height_and_width_rules() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"),
                                  schema_data=load_fixture("robokopkg.schema.json"))
    assert parsed.schema is not None
    node_template = parsed.schema.nodes[0]
    source_template = parsed.subgraphs[0]
    heights = []
    for label in ("Gene", "MacromolecularComplex"):
        nodes = tuple(replace(node_template, category=f"biolink:{label}{index}", count=index)
                      for index in range(65))
        sources = tuple(replace(source_template, name=f"{label}{index}",
                                id=f"urn:source:{index}", node_count=index)
                        for index in range(65))
        node_figure = node_category_bar(nodes)
        source_figure = subgraph_contribution_bar(sources)
        assert node_figure.layout.height == source_figure.layout.height
        assert node_figure.layout.xaxis.tickangle == source_figure.layout.xaxis.tickangle
        assert node_figure.layout.xaxis.tickfont.size == source_figure.layout.xaxis.tickfont.size
        assert contribution_chart_style(node_figure) == contribution_chart_style(source_figure)
        assert contribution_chart_style(node_figure)["width"] == "max(100%, 1660px)"
        assert node_figure.layout.margin.b == source_figure.layout.margin.b == 24
        heights.append(node_figure.layout.height)
    assert heights[1] > heights[0]


def test_subject_object_category_pair_bar_aggregates_pairs() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:causes",
            object_category=("biolink:Disease",),
            count=25,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:ChemicalEntity",),
            predicate="biolink:treats",
            object_category=("biolink:Disease",),
            count=50,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )

    figure = subject_object_category_pair_bar(edges)

    assert list(figure.data[0].x) == [0, 1]
    assert list(figure.data[0].y) == [125, 50]
    assert figure.data[0].orientation is None
    assert figure.layout.xaxis.ticktext[0] == "Gene -> Disease"
    assert "(" not in figure.layout.xaxis.ticktext[0]
    assert figure.data[0].customdata[0][0] == "biolink:Gene"
    assert figure.data[0].customdata[0][1] == "biolink:Disease"
    assert figure.data[0].customdata[0][3] == "2"
    assert figure.layout.title.text == "2 Subject-Object Category Pair Contribution"
    assert figure.layout.bargap == 0
    assert figure.layout.bargroupgap == 0
    assert figure.data[0].marker.line.width == 1
    assert figure.layout.xaxis.tickangle == -55
    assert figure.layout.xaxis.tickfont.size == 10
    assert figure.layout.margin.b == 24


def test_category_pair_chart_bounds_rendering_and_strips_compound_category_prefixes() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"),
                                  schema_data=load_fixture("robokopkg.schema.json"))
    assert parsed.schema is not None
    template = parsed.schema.edges[0]
    edges = tuple(replace(
        template, subject_category=("biolink:Protein", "biolink:Drug"),
        object_category=(f"biolink:Category{index}",), count=index,
    ) for index in range(65))
    figure = subject_object_category_pair_bar(edges)
    assert len(figure.data[0].x) == 50
    assert list(figure.data[0].y) == list(reversed(range(15, 65)))
    assert figure.layout.title.text == "65 Subject-Object Category Pair Contribution (Top 50)"
    assert all("biolink:" not in label for label in figure.layout.xaxis.ticktext)
    assert "Protein" in figure.layout.xaxis.ticktext[0]
    assert "Drug" in figure.layout.xaxis.ticktext[0]
    assert "biolink:Protein" in figure.data[0].customdata[0][0]
    assert figure.data[0].customdata[0][1] == "biolink:Category64"
    labels = tuple(replace(parsed.schema.nodes[0], category=label, count=index)
                   for index, label in enumerate(figure.layout.xaxis.ticktext))
    node_figure = node_category_bar(labels)
    assert contribution_chart_style(figure) == contribution_chart_style(node_figure)
    assert contribution_chart_style(figure)["width"] == "max(100%, 1300px)"
    smaller = subject_object_category_pair_bar(edges, top_n=10)
    assert len(smaller.data[0].x) == 10
    assert smaller.layout.title.text == "65 Subject-Object Category Pair Contribution (Top 10)"


def test_category_chart_labels_truncate_only_past_limit_and_keep_full_tooltips() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"),
                                  schema_data=load_fixture("robokopkg.schema.json"))
    assert parsed.schema is not None
    node_template = parsed.schema.nodes[0]
    edge_template = parsed.schema.edges[0]
    for length in (29, 30, 31, 100):
        category = "biolink:" + "A" * length
        node_figure = node_category_bar((replace(node_template, category=category),))
        label = node_figure.layout.xaxis.ticktext[0]
        assert label == ("A" * length if length <= 30 else "A" * 27 + "...")
        assert node_figure.data[0].customdata[0] == category
        subject = "biolink:" + "A" * (length - 5)
        obj = "biolink:B"
        pair_figure = subject_object_category_pair_bar((replace(
            edge_template, subject_category=(subject,), object_category=(obj,),
        ),))
        full_label = subject.replace("biolink:", "") + " -> B"
        expected = full_label if length <= 30 else full_label[:27] + "..."
        assert pair_figure.layout.xaxis.ticktext[0] == expected
        assert pair_figure.data[0].customdata[0][0] == subject
        assert pair_figure.data[0].customdata[0][1] == obj
        assert "%{customdata[0]}" in pair_figure.data[0].hovertemplate
        assert "%{customdata[1]}" in pair_figure.data[0].hovertemplate


def test_category_pair_chart_bounds_real_robokop_payload() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"),
                                  schema_data=load_fixture("robokopkg.schema.json"))
    assert parsed.schema is not None
    figure = subject_object_category_pair_bar(parsed.schema.edges)
    assert len(figure.data[0].x) == 50
    assert figure.layout.title.text == "406 Subject-Object Category Pair Contribution (Top 50)"
    assert len(figure.to_json()) < 25000
    assert contribution_chart_style(figure)["width"] == "max(100%, 1300px)"


def test_all_contribution_chart_heights_preserve_user_adjusted_plot_height() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"),
                                  schema_data=load_fixture("robokopkg.schema.json"))
    assert parsed.schema is not None
    for figure in (node_category_bar(parsed.schema.nodes),
                   subgraph_contribution_bar(parsed.subgraphs),
                   subject_object_category_pair_bar(parsed.schema.edges)):
        assert 376 <= figure.layout.height <= 661
        assert contribution_chart_style(figure)["height"] == f"{figure.layout.height}px"
    assert node_category_bar(()).layout.height == 376


def test_category_pair_chart_handles_empty_edges() -> None:
    figure = subject_object_category_pair_bar(())
    assert not figure.data[0].x
    assert figure.layout.title.text == "0 Subject-Object Category Pair Contribution"


def test_predicate_sankey_builds_limited_flows() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None

    figure = predicate_sankey(parsed.schema.edges, top_n=3)

    assert len(figure.data) == 1
    assert len(figure.data[0].link.value) <= 6    


def test_predicate_sankey_can_render_all_flows() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None

    limited = predicate_sankey(parsed.schema.edges, top_n=3)
    unfiltered = predicate_sankey(parsed.schema.edges, top_n=None)
    negative_unfiltered = predicate_sankey(parsed.schema.edges, top_n=-1)

    assert len(unfiltered.data[0].link.value) >= len(limited.data[0].link.value)
    assert len(negative_unfiltered.data[0].link.value) == len(unfiltered.data[0].link.value)
    assert str(unfiltered.layout.title.text).startswith("All ")
    assert unfiltered.layout.height >= 700


def test_predicate_sankey_can_scope_to_subject_category() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None
    subject = ", ".join(parsed.schema.edges[0].subject_category)

    figure = predicate_sankey(parsed.schema.edges, subject_filter=subject, top_n=40)

    labels = [str(label) for label in figure.data[0].node.label]
    hover_labels = [str(customdata[0]) for customdata in figure.data[0].node.customdata]
    assert any(label == subject for label in labels)
    assert all(not label.startswith(("Subject: ", "Predicate: ", "Object: ")) for label in labels)
    assert any(label.startswith(f"Subject: {subject}") for label in hover_labels)


def test_predicate_sankey_keeps_all_category_cap_but_allows_filtered_relationships() -> None:
    edges = tuple(
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate=f"biolink:predicate_{index}",
            object_category=(f"biolink:Object{index}",),
            count=100 - index,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        )
        for index in range(50)
    )

    unfiltered = predicate_sankey(edges, top_n=40)
    filtered = predicate_sankey(edges, subject_filter="biolink:Gene", top_n=200)

    assert len(unfiltered.data[0].link.value) == 80
    assert len(filtered.data[0].link.value) == 100


def test_predicate_sankey_uses_consistent_all_category_compression() -> None:
    edges = tuple(
        EdgeTriple(
            subject_category=(f"biolink:Subject{index % 5}",),
            predicate=f"biolink:predicate_{index}",
            object_category=(f"biolink:Object{index}",),
            count=100_000_000 if index == 0 else max(12, 10_000 - index),
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        )
        for index in range(100)
    )

    default_view = predicate_sankey(edges)
    expanded_view = predicate_sankey(edges, top_n=100)
    
    assert max(default_view.data[0].link.value) < 100_000_000
    assert max(expanded_view.data[0].link.value) < 100_000_000
    assert round(max(expanded_view.data[0].link.value), 1) == 464.2
    assert expanded_view.data[0].link.customdata[0][1] == "100,000,000"


def test_predicate_sankey_filters_by_source_predicate_and_object_category() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={"infores:source-a": 30, "infores:source-b": 70},
            qualifiers={"qualified_predicate": 8},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:treats",
            object_category=("biolink:Disease",),
            count=80,
            primary_knowledge_sources={"infores:source-a": 80},
            qualifiers={"object_aspect_qualifier": 5},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:PhenotypicFeature",),
            count=60,
            primary_knowledge_sources={"infores:source-a": 10},
            qualifiers={"qualified_predicate": 2},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )

    figure = predicate_sankey(
        edges,
        top_n=None,
        source_filters=("infores:source-a",),
        predicate_filters=("biolink:related_to",),
        object_filters=("biolink:Disease",),
    )

    assert len(figure.data[0].link.value) == 2
    assert figure.data[0].link.customdata[0][1] == "30"


def test_predicate_sankey_source_filter_preserves_edge_metadata() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={"infores:source-a": 25},
            qualifiers={"qualified_predicate": 8},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:treats",
            object_category=("biolink:Disease",),
            count=80,
            primary_knowledge_sources={"infores:source-b": 80},
            qualifiers={"object_aspect_qualifier": 5},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )

    selected_edges = filter_predicate_sankey_edges(
        edges,
        source_filters=("infores:source-a",),
    )

    assert len(selected_edges) == 1
    assert selected_edges[0].count == 25
    assert selected_edges[0].qualifiers == {"qualified_predicate": 8}


def test_predicate_sankey_highlights_links_connected_to_selected_node() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:ChemicalEntity",),
            predicate="biolink:treats",
            object_category=("biolink:Disease",),
            count=50,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )

    figure = predicate_sankey(
        edges,
        top_n=None,
        selected_node_label="Predicate: biolink:related_to",
    )

    assert str(figure.data[0].link.color[0]).endswith(", 0.82)")
    assert str(figure.data[0].link.color[1]).endswith(", 0.82)")
    assert str(figure.data[0].link.color[2]).endswith(", 0.06)")
    assert str(figure.data[0].link.color[3]).endswith(", 0.06)")


def test_predicate_sankey_can_highlight_from_displayed_node_label() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:ChemicalEntity",),
            predicate="biolink:treats",
            object_category=("biolink:PhenotypicFeature",),
            count=50,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )

    figure = predicate_sankey(edges, top_n=None, selected_node_label="biolink:related_to")

    assert str(figure.data[0].link.color[0]).endswith(", 0.82)")
    assert str(figure.data[0].link.color[1]).endswith(", 0.82)")
    assert str(figure.data[0].link.color[2]).endswith(", 0.06)")
    assert str(figure.data[0].link.color[3]).endswith(", 0.06)")


def test_sankey_highlight_colors_handles_node_click_data() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
        EdgeTriple(
            subject_category=("biolink:ChemicalEntity",),
            predicate="biolink:treats",
            object_category=("biolink:PhenotypicFeature",),
            count=50,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )
    figure = predicate_sankey(edges, top_n=None)

    colors = sankey_highlight_colors(
        figure.to_dict(),
        {"points": [{"label": "biolink:related_to"}]},
    )

    assert colors is not None
    link_colors, node_colors = colors
    assert link_colors[0].endswith(", 0.82)")
    assert link_colors[1].endswith(", 0.82)")
    assert link_colors[2].endswith(", 0.06)")
    assert link_colors[3].endswith(", 0.06)")
    assert any(color.endswith(", 0.2)") for color in node_colors)
    customdata = next(
        value for value in figure.to_dict()["data"][0]["node"]["customdata"]
        if value[0] == "Predicate: biolink:related_to"
    )
    assert sankey_highlight_colors(
        figure.to_dict(), {"points": [{"customdata": customdata}]},
    ) == colors
    for invalid_customdata in (None, [], [None], "Predicate: biolink:related_to"):
        assert sankey_highlight_colors(
            figure.to_dict(), {"points": [{"customdata": invalid_customdata}]},
        ) is None


def test_sankey_highlight_colors_ignores_link_click_data() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )
    figure = predicate_sankey(edges, top_n=None)

    colors = sankey_highlight_colors(
        figure.to_dict(),
        {"points": [{"pointNumber": 0, "source": 0, "target": 1}]},
    )

    assert colors is None


def test_sankey_highlight_colors_ignores_bare_point_number() -> None:
    edges = (
        EdgeTriple(
            subject_category=("biolink:Gene",),
            predicate="biolink:related_to",
            object_category=("biolink:Disease",),
            count=100,
            primary_knowledge_sources={},
            qualifiers={},
            attributes={},
            subject_id_prefixes={},
            object_id_prefixes={},
        ),
    )
    figure = predicate_sankey(edges, top_n=None)

    colors = sankey_highlight_colors(
        figure.to_dict(),
        {"points": [{"pointNumber": 0}]},
    )

    assert colors is None


def test_knowledge_source_predicate_sankey_default_caps_show_robokop_sized_vocab() -> None:
    counts = tuple(
        KnowledgeSourcePredicateCount(
            source=f"infores:source-{index}",
            predicate=f"biolink:predicate-{index}",
            count=1000 - index,
        )
        for index in range(77)
    )

    figure = knowledge_source_predicate_sankey(counts)

    labels = list(figure.data[0].node.label)
    hover_labels = [customdata[0] for customdata in figure.data[0].node.customdata]
    assert "Source: Other" not in hover_labels
    assert "Predicate: Other" not in hover_labels
    assert all(not str(label).startswith(("Source: ", "Predicate: ")) for label in labels)
    assert figure.layout.height > 2000
    assert figure.data[0].node.pad == 8


def test_knowledge_source_predicate_sankey_keeps_room_for_smaller_graphs() -> None:
    counts = tuple(
        KnowledgeSourcePredicateCount(
            source=f"infores:source-{index}",
            predicate=f"biolink:predicate-{index}",
            count=100 - index,
        )
        for index in range(6)
    )

    figure = knowledge_source_predicate_sankey(counts)

    assert figure.layout.height == SANKEY_BASE_HEIGHT
    assert figure.data[0].node.pad == SANKEY_DEFAULT_NODE_PAD


def test_knowledge_source_predicate_sankey_compresses_skewed_link_widths() -> None:
    counts = (
        KnowledgeSourcePredicateCount(
            source="infores:ubergraph",
            predicate="biolink:related_to",
            count=100_000_000,
        ),
        KnowledgeSourcePredicateCount(
            source="infores:next-source",
            predicate="biolink:treats",
            count=1_000_000,
        ),
    )

    figure = knowledge_source_predicate_sankey(counts)

    assert list(figure.data[0].link.value) == [10_000.0, 1_000.0]
    assert figure.data[0].link.customdata[0][2] == "100,000,000"


def test_knowledge_source_predicate_sankey_uses_stronger_compression_for_tiny_flows() -> None:
    counts = (
        KnowledgeSourcePredicateCount(
            source="infores:ubergraph",
            predicate="biolink:related_to",
            count=100_000_000,
        ),
        KnowledgeSourcePredicateCount(
            source="infores:tiny-source",
            predicate="biolink:contributes_to",
            count=16,
        ),
    )

    figure = knowledge_source_predicate_sankey(counts)

    assert list(figure.data[0].link.value) == [100.0, 2.0]
    assert figure.data[0].link.customdata[1][2] == "16"


def test_filter_source_predicate_counts_filters_both_columns() -> None:
    counts = (
        KnowledgeSourcePredicateCount(
            source="infores:source-a",
            predicate="biolink:related_to",
            count=100,
        ),
        KnowledgeSourcePredicateCount(
            source="infores:source-a",
            predicate="biolink:treats",
            count=50,
        ),
        KnowledgeSourcePredicateCount(
            source="infores:source-b",
            predicate="biolink:related_to",
            count=30,
        ),
    )

    filtered = filter_source_predicate_counts(
        counts,
        source_filters=("infores:source-a",),
        predicate_filters=("biolink:related_to",),
    )

    assert filtered == (counts[0],)


def test_knowledge_source_predicate_sankey_highlights_selected_source_links() -> None:
    counts = (
        KnowledgeSourcePredicateCount(
            source="infores:source-a",
            predicate="biolink:related_to",
            count=100,
        ),
        KnowledgeSourcePredicateCount(
            source="infores:source-b",
            predicate="biolink:treats",
            count=50,
        ),
    )

    figure = knowledge_source_predicate_sankey(
        counts,
        selected_node_label="Source: infores:source-a",
    )

    assert str(figure.data[0].link.color[0]).endswith(", 0.82)")
    assert str(figure.data[0].link.color[1]).endswith(", 0.06)")


def test_knowledge_source_predicate_sankey_can_highlight_from_displayed_node_label() -> None:
    counts = (
        KnowledgeSourcePredicateCount(
            source="infores:source-a",
            predicate="biolink:related_to",
            count=100,
        ),
        KnowledgeSourcePredicateCount(
            source="infores:source-b",
            predicate="biolink:treats",
            count=50,
        ),
    )

    figure = knowledge_source_predicate_sankey(
        counts,
        selected_node_label="infores:source-a",
    )

    assert str(figure.data[0].link.color[0]).endswith(", 0.82)")
    assert str(figure.data[0].link.color[1]).endswith(", 0.06)")


def test_knowledge_source_predicate_sankey_collapses_other_bucket() -> None:
    counts = tuple(
        KnowledgeSourcePredicateCount(
            source=f"infores:source-{index}",
            predicate=f"biolink:predicate-{index}",
            count=100 - index,
        )
        for index in range(5)
    )

    figure = knowledge_source_predicate_sankey(
        counts,
        top_n_sources=2,
        top_n_predicates=2,
    )

    labels = list(figure.data[0].node.label)
    hover_labels = [customdata[0] for customdata in figure.data[0].node.customdata]
    assert "Other" in labels
    assert "Source: Other" in hover_labels
    assert "Predicate: Other" in hover_labels


def test_count_bar_limits_top_n() -> None:
    figure = count_bar(
        {"source-a": 10, "source-b": 30, "source-c": 20},
        title="Sources",
        xaxis_title="Source",
        top_n=2,
    )

    assert list(figure.data[0].x) == ["source-b", "source-c"]
    assert figure.layout.yaxis.type == "log"
    assert figure.layout.yaxis.dtick == 1


def test_subgraph_contribution_keeps_vertical_layout_with_short_labels() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))

    figure = subgraph_contribution_bar(parsed.subgraphs)

    assert figure.data[0].orientation is None
    assert figure.layout.yaxis.type == "log"
    assert figure.layout.yaxis.dtick == 1
    assert figure.layout.margin.b == 24
    assert figure.layout.xaxis.automargin
    assert figure.layout.xaxis.title.standoff == 8
    assert figure.layout.title.text == f"{len(figure.data[0].x)} Subgraph Contribution"
    assert figure.layout.xaxis.tickangle == -55
    assert figure.layout.xaxis.tickfont.size == 10
    assert figure.layout.xaxis.tickmode == "array"
    assert list(figure.layout.xaxis.tickvals) == list(figure.data[0].x)
    assert figure.layout.bargap == 0
    assert figure.layout.bargroupgap == 0
    assert figure.data[0].marker.line.width == 1
    assert figure.data[0].marker.line.color == "#78350f"
    assert all(
        not str(label).startswith("A ROBOKOP Knowledge Graph based on")
        for label in figure.data[0].x
    )
    assert all(len(str(label)) <= 30 for label in figure.data[0].x)
    assert "Unspecified source" not in figure.data[0].x
    assert any(
        "A ROBOKOP Knowledge Graph based on" in str(label)
        for label, _, _ in figure.data[0].customdata
    )
    assert any(
        "https://robokop.renci.org/graphs/" in str(label)
        for label, _, _ in figure.data[0].customdata
    )
    assert "Node count:" in figure.data[0].hovertemplate
    assert "Edge count:" in figure.data[0].hovertemplate
    assert "Count:" not in figure.data[0].hovertemplate


def test_subgraph_contribution_title_counts_only_displayed_sources() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))
    template = parsed.subgraphs[0]
    sources = tuple(
        replace(template, name=f"Source {index}", id=f"urn:source:{index}", node_count=index)
        for index in range(65)
    ) + (replace(template, name="Source missing", node_count=None),)

    default = subgraph_contribution_bar(sources)
    assert len(default.data[0].x) == 65
    assert default.layout.title.text == "65 Subgraph Contribution"
    assert list(default.data[0].y) == list(reversed(range(65)))
    missing = subgraph_contribution_bar((replace(template, node_count=None),))
    assert not missing.data[0].x
    assert missing.layout.title.text == "0 Subgraph Contribution"
    assert missing.layout.annotations[0].text
    empty = subgraph_contribution_bar(())
    assert empty.layout.title.text == "0 Subgraph Contribution"
