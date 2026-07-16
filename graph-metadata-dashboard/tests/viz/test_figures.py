from __future__ import annotations

from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata
from graph_metadata_dashboard.viz.figures import node_category_bar, predicate_sankey
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
