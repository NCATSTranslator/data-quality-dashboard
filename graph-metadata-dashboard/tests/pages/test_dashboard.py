from __future__ import annotations

import base64
import json
from dataclasses import replace
from importlib import import_module

from dash import dcc, html, page_registry

from graph_metadata_dashboard.app import create_app
from graph_metadata_dashboard.cache.memory import InMemoryMetadataCache
from graph_metadata_dashboard.components import comparison as comparison_components
from graph_metadata_dashboard.components.single_graph import (
    primary_knowledge_source_counts,
    provenance_contribution,
    upload_selection_status,
    url_selection_status,
)
from graph_metadata_dashboard.config import Settings
from graph_metadata_dashboard.diff import CountDelta, MapEntryChange
from graph_metadata_dashboard.loaders.kgx_storage import KgxStorageClient
from graph_metadata_dashboard.loaders.url import UrlMetadataClient
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
    source_dialogs = _find_elements_by_type(dashboard, "Dialog")

    assert "Comparison Overview" in text
    assert "Types" in text
    assert "Schema-Level Differences:" in text
    assert "Alliance" in text
    assert "Translator KG Open" in text
    assert len(_find_elements_by_class(dashboard, "comparison-glyph")) > 0
    assert len(_find_elements_by_class(dashboard, "overview-delta")) > 0
    assert len(_find_elements_by_class(dashboard, "source-change-action-row")) == 1
    assert len(_find_elements_by_class(dashboard, "comparison-pair-details")) == 2
    assert len(_find_elements_by_class(dashboard, "schema-table-panel")) > 0
    assert len(source_dialogs) == 1
    source_tables = _find_datatables(source_dialogs[0])
    assert "Show changes" in text
    assert "Alliance Copy" in _flatten_text(overview_table)
    assert "No changes" in _flatten_text(overview_table)
    assert source_tables
    source_column_names = [column["name"] for column in source_tables[0].columns]
    assert "Status" not in source_column_names
    assert "Alliance Version" in source_column_names
    assert "Translator KG Open Version" in source_column_names
    assert "Alliance License" in source_column_names
    assert "Translator KG Open License" in source_column_names


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

    assert "Using Translator KG Open as the baseline" in text
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
    parsed = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
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

    assert "Subgraph Contribution Changes" not in " ".join(_flatten_text(dashboard))


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

    assert "Node Category Changes" in text
    assert "ID prefixes" in text
    assert "Attributes" in text
    assert "Edge Triple Changes" in text
    assert "Primary sources" in text
    assert "Subject prefixes" in text
    assert "Object prefixes" in text
    assert "Overall Node and Edge Composition Summary Changes" in text
    assert "Node type" in text
    assert "Edge type" in text
    assert len(_find_elements_by_class(dashboard, "schema-summary-card")) > 0
    assert len(_find_elements_by_class(dashboard, "schema-summary-card-grid")) > 0
    assert len(_find_elements_by_class(dashboard, "schema-summary-card-column")) > 0
    assert "Nodes:" in overview_text
    assert "Edges:" in overview_text


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
