from __future__ import annotations

from importlib import import_module
from types import ModuleType

from dash import Dash, dcc, html, page_container, page_registry

from graph_metadata_dashboard.cache.factory import create_metadata_cache
from graph_metadata_dashboard.config import Settings
from graph_metadata_dashboard.loaders.kgx_storage import KgxStorageClient


def create_app(settings: Settings | None = None) -> Dash:
    settings = settings or Settings.from_env()
    app = Dash(
        __name__,
        use_pages=True,
        title="Graph Metadata Dashboard",
        suppress_callback_exceptions=True,
    )

    cache = create_metadata_cache(settings)
    kgx_client = KgxStorageClient(
        base_url=settings.kgx_storage_base_url,
        timeout_seconds=settings.requests_timeout_seconds,
    )

    single_graph = _discovered_page_module("single_graph")
    comparison = _discovered_page_module("comparison")
    single_graph.register_callbacks(app, cache=cache, kgx_client=kgx_client)
    comparison.register_callbacks(app)

    app.layout = html.Div(
        className="app-shell",
        children=[
            dcc.Location(id="url"),
            dcc.Store(id="session-id", storage_type="session"),
            html.Header(
                className="site-header",
                children=[
                    html.Div([
                        html.P("Knowledge Graph Metadata Dashboard", className="eyebrow"),
                        html.H1([
                            "Metadata Dashboard for Graphs Built with ",
                            html.A("ORION", href="https://github.com/RobokopU24/ORION",
                            target="_blank", rel="noopener"),
                        ]),
                    ]),
                ],
            ),
            html.Main(className="page", children=[page_container]),
        ],
    )
    return app


def create_server():
    return create_app().server


def _discovered_page_module(module_basename: str) -> ModuleType:
    for page in page_registry.values():
        module_name = page["module"]
        if module_name.endswith(f".{module_basename}"):
            return import_module(module_name)
    msg = f"Dash did not discover page module ending in {module_basename!r}"
    raise RuntimeError(msg)
