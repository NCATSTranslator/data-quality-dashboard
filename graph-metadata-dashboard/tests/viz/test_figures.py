from __future__ import annotations

from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata
from graph_metadata_dashboard.parsers.models import KnowledgeSourcePredicateCount
from graph_metadata_dashboard.viz.figures import (
    count_bar,
    knowledge_source_predicate_sankey,
    node_category_bar,
    predicate_sankey,
    subgraph_contribution_bar,
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
    assert "of the flows shown" in figure.data[0].node.hovertemplate
    assert "of the flows shown" in figure.data[0].link.hovertemplate


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

    assert str(figure.layout.title.text).startswith(f"Showing: {subject}")
    assert all(
        str(label).startswith((f"Subject: {subject}", "Predicate: ", "Object: "))
        for label in figure.data[0].node.label
    )


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
    assert "Source: Other" in labels
    assert "Predicate: Other" in labels
    assert "of the flows shown" in figure.data[0].node.hovertemplate
    assert "of the flows shown" in figure.data[0].link.hovertemplate


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
