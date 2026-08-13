from __future__ import annotations

from graph_metadata_dashboard.app import create_app
from graph_metadata_dashboard.config import Settings


def test_stylesheet_is_served() -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    response = app.server.test_client().get("/assets/style.css")

    assert response.status_code == 200
    assert b".app-shell" in response.data


def test_sankey_interactions_script_is_served() -> None:
    app = create_app(Settings(cache_dir="/tmp/graph-metadata-dashboard-test-cache"))
    response = app.server.test_client().get("/assets/sankey_interactions.js")

    assert response.status_code == 200
    assert b"sankey-link" in response.data
    assert b"sankey-node" in response.data
    assert b"Plotly.restyle" not in response.data
    assert b"plotly_click" not in response.data
