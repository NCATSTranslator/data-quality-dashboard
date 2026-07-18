from __future__ import annotations

from dataclasses import replace

from dash import dcc, html

from graph_metadata_dashboard.components.single_graph import (
    primary_knowledge_source_counts,
    provenance_contribution,
    upload_selection_status,
)
from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata, parse_schema
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


def test_upload_selection_status_lists_selected_files() -> None:
    status = upload_selection_status("graph-metadata.json", "schema.json")

    assert all(isinstance(item, html.P) for item in status)
    assert "graph-metadata.json" in status[0].children
    assert "schema.json" in status[1].children


def test_upload_selection_status_is_empty_before_files_are_selected() -> None:
    assert upload_selection_status(None, None) == []
