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
from graph_metadata_dashboard.diff import CountDelta, MapEntryChange, SourceChange, SubgraphChange
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
            assert f"Using {selection[1]['label']} as the baseline" in " ".join(
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
    assert not _find_elements_by_type(dashboard, "Dialog")
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
