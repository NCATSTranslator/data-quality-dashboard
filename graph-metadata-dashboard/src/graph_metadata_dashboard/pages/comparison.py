from __future__ import annotations

from dash import Dash, html, register_page


def layout() -> html.Div:
    return html.Div(
        className="content-card",
        children=[
            html.P("Deferred workflow", className="eyebrow"),
            html.H2("Graph Comparison"),
            html.P(
                "Comparison mode is now selected implicitly on the main page: load two or "
                "more graphs and the dashboard will switch to the comparison placeholder. "
                "The actual diff visualizations remain deferred until the ORION comparison "
                "module is available."
            ),
        ],
    )


register_page(__name__, path="/comparison", name="Comparison")


def register_callbacks(app: Dash) -> None:
    del app
