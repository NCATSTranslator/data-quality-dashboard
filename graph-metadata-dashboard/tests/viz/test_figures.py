from __future__ import annotations

from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata
from graph_metadata_dashboard.parsers.models import EdgeTriple, KnowledgeSourcePredicateCount
from graph_metadata_dashboard.viz.figures import (
    SANKEY_BASE_HEIGHT,
    SANKEY_DEFAULT_NODE_PAD,
    count_bar,
    filter_source_predicate_counts,
    knowledge_source_predicate_sankey,
    node_category_bar,
    predicate_sankey,
    qualifier_counts_for_edges,
    sankey_highlight_colors,
    selected_predicate_sankey_edges,
    subgraph_contribution_bar,
    subject_object_category_pair_bar,
)
from tests.conftest import load_fixture


def test_node_category_bar_limits_top_n() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None

    figure = node_category_bar(parsed.schema.nodes, top_n=5)

    assert len(figure.data[0].x) == 5


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

    figure = subject_object_category_pair_bar(edges, top_n=1)

    assert list(figure.data[0].x) == [0]
    assert list(figure.data[0].y) == [125]
    assert figure.data[0].orientation is None
    assert figure.layout.xaxis.ticktext[0] == "biolink:Gene -> biolink:Disease"
    assert "(" not in figure.layout.xaxis.ticktext[0]
    assert figure.data[0].customdata[0][0] == "biolink:Gene"
    assert figure.data[0].customdata[0][1] == "biolink:Disease"
    assert figure.data[0].customdata[0][3] == "2"


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

    unfiltered = predicate_sankey(edges)
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


def test_selected_predicate_sankey_edges_preserve_qualifier_context() -> None:
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

    selected_edges = selected_predicate_sankey_edges(
        edges,
        top_n=None,
        source_filters=("infores:source-a",),
    )
    qualifier_counts = qualifier_counts_for_edges(selected_edges)

    assert len(selected_edges) == 1
    assert selected_edges[0].count == 25
    assert qualifier_counts == [("qualified_predicate", 8)]


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
    assert figure.layout.margin.b <= 150
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
