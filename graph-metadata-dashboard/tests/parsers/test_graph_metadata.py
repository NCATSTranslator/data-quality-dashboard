from __future__ import annotations

from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata, parse_schema
from tests.conftest import load_fixture


def test_parse_small_single_source_fixture() -> None:
    parsed = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))

    assert parsed.name
    assert parsed.description
    assert parsed.release_version
    assert parsed.biolink_version
    assert parsed.schema_reference.kind in {"inline", "absent"}
    assert parsed.total_node_count is None or parsed.total_node_count > 0


def test_parse_inline_schema_fixture() -> None:
    parsed = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))

    assert parsed.schema_reference.kind == "inline"
    assert parsed.schema is not None
    assert parsed.schema.total_node_count is not None
    assert parsed.schema.total_edge_count is not None
    assert len(parsed.schema.nodes) > 0
    assert len(parsed.schema.edges) > 0


def test_parse_pointer_schema_fixture_without_eager_schema() -> None:
    parsed = parse_graph_metadata(load_fixture("robokopkg.graph-metadata.json"))

    assert parsed.schema_reference.kind == "pointer"
    assert parsed.schema_reference.url is not None
    assert parsed.schema is None


def test_parse_pointer_schema_fixture_when_schema_supplied() -> None:
    parsed = parse_graph_metadata(
        load_fixture("robokopkg.graph-metadata.json"),
        schema_data=load_fixture("robokopkg.schema.json"),
    )

    assert parsed.schema is not None
    assert parsed.schema.total_node_count is not None
    assert parsed.schema.total_edge_count is not None
    assert len(parsed.schema.nodes) > 0
    assert len(parsed.schema.edges) > 0


def test_parse_registry_schema_wrapper() -> None:
    schema = parse_schema(load_fixture("robokopkg.schema.json"))

    assert schema is not None
    assert schema.total_node_count is not None
    assert schema.total_edge_count is not None
    assert len(schema.nodes) > 0


def test_parse_predicates_by_knowledge_source_nested_shape() -> None:
    schema = parse_schema(
        {
            "edges_summary": {
                "predicates_by_knowledge_source": {
                    "infores:source-a": {
                        "biolink:related_to": 12,
                        "biolink:treats": "7",
                    },
                    None: {
                        None: 3,
                        "bad-count": "not an integer",
                    },
                }
            }
        }
    )

    assert schema is not None
    assert schema.source_predicate_counts[0].source == "infores:source-a"
    assert schema.source_predicate_counts[0].predicate == "biolink:related_to"
    assert schema.source_predicate_counts[0].count == 12
    assert schema.source_predicate_counts[1].count == 7
    assert schema.source_predicate_counts[2].source == "Unknown"
    assert schema.source_predicate_counts[2].predicate == "Unknown"
    assert len(schema.source_predicate_counts) == 3


def test_parse_missing_predicates_by_knowledge_source_as_absent() -> None:
    schema = parse_schema({"edges_summary": {}})

    assert schema is not None
    assert schema.source_predicate_counts == ()
