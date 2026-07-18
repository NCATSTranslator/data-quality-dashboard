from __future__ import annotations

from dash import Dash, html, register_page


def layout() -> html.Div:
    return html.Div(
        className="content-card",
        children=[
            html.P("Graph comparison", className="eyebrow"),
            html.H2("Graph Comparison"),
            html.P(
                "To be implemented"
            ),
        ],
    )


register_page(__name__, path="/comparison", name="Comparison")


def register_callbacks(app: Dash) -> None:
    del app
