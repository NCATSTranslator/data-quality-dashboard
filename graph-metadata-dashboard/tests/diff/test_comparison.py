from __future__ import annotations

from dataclasses import replace

from graph_metadata_dashboard.diff import compare
from graph_metadata_dashboard.diff import comparison as comparison_module
from graph_metadata_dashboard.parsers.models import (
    GraphSchema,
    KnowledgeSource,
    ParsedGraphMetadata,
    SchemaReference,
    SubgraphSource,
)


def test_compare_detects_graph_source_and_subgraph_changes() -> None:
    baseline = _parsed_graph(
        name="Baseline",
        release_version="2026_01_01",
        license="MIT",
        sources=(
            KnowledgeSource(
                id="infores:source-a",
                name="Source A",
                description="",
                license="MIT",
                attribution="",
                citation=[],
                version="v1",
            ),
        ),
        subgraphs=(
            SubgraphSource(
                id="infores:subgraph-a",
                name="Subgraph A",
                node_count=10,
                edge_count=20,
            ),
        ),
    )
    target = _parsed_graph(
        name="Target",
        release_version="2026_02_01",
        license="Apache-2.0",
        sources=(
            KnowledgeSource(
                id="infores:source-a",
                name="Source A",
                description="",
                license="MIT",
                attribution="",
                citation=[],
                version="v2",
            ),
            KnowledgeSource(
                id="infores:source-b",
                name="Source B",
                description="",
                license="MIT",
                attribution="",
                citation=[],
                version="v1",
            ),
        ),
        subgraphs=(
            SubgraphSource(
                id="infores:subgraph-a",
                name="Subgraph A",
                node_count=15,
                edge_count=20,
            ),
            SubgraphSource(
                id="infores:subgraph-b",
                name="Subgraph B",
                node_count=5,
                edge_count=2,
            ),
        ),
    )

    result = compare([baseline, target], labels=["baseline", "target"])
    pair = result.comparisons[0]

    assert pair.total_nodes.delta == 10
    assert pair.total_edges.delta == 2
    assert {difference.field for difference in pair.field_differences} >= {
        "Graph name",
        "Release version",
        "License",
    }
    assert [(change.source_id, change.status) for change in pair.source_changes] == [
        ("infores:source-a", "changed"),
        ("infores:source-b", "added"),
    ]
    assert pair.subgraph_changes[0].source_id == "infores:subgraph-a"
    assert pair.subgraph_changes[0].node_delta.delta == 5


def test_compare_summarizes_schema_diffs_with_missing_keys_as_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        comparison_module,
        "_orion_diff_schemas",
        lambda: comparison_module._fallback_diff_schemas,
    )
    baseline = replace(
        _parsed_graph(name="Baseline"),
        schema=_schema(
            nodes=[
                {
                    "category": ["biolink:Gene"],
                    "count": 10,
                    "id_prefixes": {"NCBIGene": 10},
                    "attributes": {"name": 10},
                }
            ],
            edges=[
                {
                    "subject_category": ["biolink:Gene"],
                    "predicate": "biolink:related_to",
                    "object_category": ["biolink:Disease"],
                    "count": 5,
                    "primary_knowledge_sources": {"infores:a": 5},
                    "qualifiers": {},
                    "attributes": {"provided_by": 5},
                    "subject_id_prefixes": {"NCBIGene": 5},
                    "object_id_prefixes": {"MONDO": 5},
                }
            ],
            nodes_summary={
                "total_count": 10,
                "id_prefixes": {"NCBIGene": 10},
                "attributes": {"name": 10},
            },
            edges_summary={
                "total_count": 5,
                "predicates": {"biolink:related_to": 5},
                "primary_knowledge_sources": {"infores:a": 5},
                "predicates_by_knowledge_source": {
                    "infores:a": {"biolink:related_to": 5}
                },
                "qualifiers": {},
                "attributes": {"provided_by": 5},
            },
        ),
    )
    target = replace(
        _parsed_graph(name="Target"),
        schema=_schema(
            nodes=[
                {
                    "category": ["biolink:Gene"],
                    "count": 15,
                    "id_prefixes": {"NCBIGene": 12, "ENSEMBL": 3},
                    "attributes": {"name": 15, "description": 2},
                },
                {
                    "category": ["biolink:Disease"],
                    "count": 7,
                    "id_prefixes": {"MONDO": 7},
                    "attributes": {"name": 7},
                },
            ],
            edges=[
                {
                    "subject_category": ["biolink:Gene"],
                    "predicate": "biolink:related_to",
                    "object_category": ["biolink:Disease"],
                    "count": 8,
                    "primary_knowledge_sources": {"infores:a": 8},
                    "qualifiers": {},
                    "attributes": {"provided_by": 8},
                    "subject_id_prefixes": {"NCBIGene": 8},
                    "object_id_prefixes": {"MONDO": 8},
                },
                {
                    "subject_category": ["biolink:ChemicalEntity"],
                    "predicate": "biolink:treats",
                    "object_category": ["biolink:Disease"],
                    "count": 3,
                    "primary_knowledge_sources": {"infores:b": 3},
                    "qualifiers": {},
                    "attributes": {"provided_by": 3},
                    "subject_id_prefixes": {"CHEBI": 3},
                    "object_id_prefixes": {"MONDO": 3},
                },
            ],
            nodes_summary={
                "total_count": 22,
                "id_prefixes": {"NCBIGene": 12, "ENSEMBL": 3, "MONDO": 7},
                "attributes": {"name": 22, "description": 2},
            },
            edges_summary={
                "total_count": 11,
                "predicates": {"biolink:related_to": 8, "biolink:treats": 3},
                "primary_knowledge_sources": {"infores:a": 8, "infores:b": 3},
                "predicates_by_knowledge_source": {
                    "infores:a": {"biolink:related_to": 8},
                    "infores:b": {"biolink:treats": 3},
                },
                "qualifiers": {},
                "attributes": {"provided_by": 11},
            },
        ),
    )

    schema = compare([baseline, target]).comparisons[0].schema

    assert schema.available
    assert schema.node_total is not None
    assert schema.node_total.delta == 12
    assert schema.node_diffs[0].label == "biolink:Disease"
    assert schema.node_diffs[0].count.old == 0
    assert schema.edge_predicate_changes[0].label == "biolink:treats"
    assert schema.edge_predicate_changes[0].count.old == 0
    gene_node_change = next(
        change for change in schema.node_changes if change.label == "biolink:Gene"
    )
    assert any(change.label == "ENSEMBL" for change in gene_node_change.id_prefix_changes)
    treat_edge_change = next(
        change
        for change in schema.edge_changes
        if change.predicate == "biolink:treats"
    )
    assert any(
        change.label == "infores:b"
        for change in treat_edge_change.primary_source_changes
    )
    assert any(change.label == "CHEBI" for change in treat_edge_change.subject_id_prefix_changes)
    assert any(change.label == "ENSEMBL" for change in schema.node_id_prefix_changes)
    assert any(
        change.label == "biolink:Gene / ID prefix / ENSEMBL"
        for change in schema.node_category_id_prefix_changes
    )
    assert any(
        change.label == "infores:b / biolink:treats"
        for change in schema.edge_source_predicate_changes
    )
    assert any(
        change.label
        == "biolink:ChemicalEntity - biolink:treats - biolink:Disease / "
        "Primary source / infores:b"
        for change in schema.edge_detail_changes
    )
    assert any(
        change.label
        == "biolink:Gene - biolink:related_to - biolink:Disease / "
        "Subject prefix / NCBIGene"
        for change in schema.edge_detail_changes
    )


def test_schema_percent_change_preserves_orion_value(monkeypatch) -> None:
    monkeypatch.setattr(
        comparison_module,
        "_diff_schemas",
        lambda _old, _new: {
            "diff": {
                "nodes": [
                    {
                        "category": ["biolink:Gene"],
                        "status": "changed",
                        "count": {
                            "old": 100,
                            "new": 150,
                            "delta": 50,
                            "percent_change": 12.34,
                        },
                    }
                ],
                "nodes_summary": {
                    "total_count": {
                        "old": 100,
                        "new": 150,
                        "delta": 50,
                        "percent_change": 12.34,
                    }
                },
                "edges": [],
                "edges_summary": {},
            }
        },
    )
    baseline = replace(_parsed_graph(name="Baseline"), schema=_schema_empty())
    target = replace(_parsed_graph(name="Target"), schema=_schema_empty())

    schema = compare([baseline, target]).comparisons[0].schema

    assert schema.node_total is not None
    assert schema.node_total.percent_change == 12.34
    assert schema.node_changes[0].count.percent_change == 12.34


def _parsed_graph(
    *,
    name: str,
    release_version: str = "2026_01_01",
    license: str = "MIT",
    sources: tuple[KnowledgeSource, ...] = (),
    subgraphs: tuple[SubgraphSource, ...] = (),
) -> ParsedGraphMetadata:
    return ParsedGraphMetadata(
        name=name,
        description="",
        release_version=release_version,
        date_created="2026-01-01",
        date_modified="2026-01-02",
        license=license,
        biolink_version="4.2.0",
        babel_version="2026mar24",
        source_ids=tuple(source.id for source in sources),
        knowledge_sources=sources,
        subgraphs=subgraphs,
        schema_reference=SchemaReference(kind="absent"),
        schema=None,
        schema_version_marker="4.2.0",
        raw={"name": name},
    )


def _schema(
    *,
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
    nodes_summary: dict[str, object],
    edges_summary: dict[str, object],
) -> GraphSchema:
    raw = {
        "nodes": nodes,
        "nodes_summary": nodes_summary,
        "edges": edges,
        "edges_summary": edges_summary,
    }
    return GraphSchema(
        nodes=(),
        edges=(),
        source_predicate_counts=(),
        nodes_summary=nodes_summary,
        edges_summary=edges_summary,
        raw=raw,
    )


def _schema_empty() -> GraphSchema:
    return _schema(nodes=[], edges=[], nodes_summary={}, edges_summary={})
