from __future__ import annotations

from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata
from graph_metadata_dashboard.parsers.models import EdgeTriple, KnowledgeSourcePredicateCount
from graph_metadata_dashboard.viz.figures import (
    count_bar,
    knowledge_source_predicate_sankey,
    node_category_bar,
    predicate_sankey,
    subgraph_contribution_bar,
    SANKEY_BASE_HEIGHT,
    SANKEY_DEFAULT_NODE_PAD
)
from tests.conftest import load_fixture


def test_node_category_bar_limits_top_n() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    assert parsed.schema is not None

    figure = node_category_bar(parsed.schema.nodes, top_n=5)

    assert len(figure.data[0].x) == 5


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
