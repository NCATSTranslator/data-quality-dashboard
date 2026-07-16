from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go

from graph_metadata_dashboard.parsers.models import EdgeTriple, NodeCategory, SubgraphSource

OTHER_LABEL = "Other"


def node_category_bar(
    nodes: tuple[NodeCategory, ...],
    *,
    top_n: int = 30,
    log_scale: bool = True,
) -> go.Figure:
    top_nodes = sorted(nodes, key=lambda item: item.count, reverse=True)[:top_n]
    fig = go.Figure(
        data=[
            go.Bar(
                x=[node.category for node in top_nodes],
                y=[node.count for node in top_nodes],
                marker_color="#0f766e",
            )
        ]
    )
    fig.update_layout(
        title=f"Top {min(top_n, len(nodes))} Node Categories",
        xaxis_title="Category",
        yaxis_title="Node count",
        margin={"l": 48, "r": 24, "t": 56, "b": 120},
        yaxis_type="log" if log_scale else "linear",
    )
    return fig


def subgraph_contribution_bar(
    subgraphs: tuple[SubgraphSource, ...],
    *,
    metric: str = "node_count",
    log_scale: bool = True,
) -> go.Figure:
    values: list[tuple[str, int]] = []
    for source in subgraphs:
        count = source.node_count if metric == "node_count" else source.edge_count
        if count is not None:
            values.append((source.name or source.id or "Unknown", count))
    values.sort(key=lambda item: item[1], reverse=True)

    fig = go.Figure(
        data=[
            go.Bar(
                x=[label for label, _ in values],
                y=[count for _, count in values],
                marker_color="#b45309",
            )
        ]
    )
    fig.update_layout(
        title="Subgraph Contribution",
        xaxis_title="Subgraph",
        yaxis_title="Count",
        margin={"l": 48, "r": 24, "t": 56, "b": 120},
        yaxis_type="log" if log_scale else "linear",
    )
    return fig


def predicate_sankey(edges: tuple[EdgeTriple, ...], *, top_n: int = 40) -> go.Figure:
    selected_edges = sorted(edges, key=lambda item: item.count, reverse=True)[:top_n]
    collapsed = _collapse_edges(selected_edges)
    labels = _sankey_labels(collapsed)
    index = {label: position for position, label in enumerate(labels)}

    sources: list[int] = []
    targets: list[int] = []
    values: list[int] = []

    for subject, predicate, obj, count in collapsed:
        subject_label = f"Subject: {subject}"
        predicate_label = f"Predicate: {predicate}"
        object_label = f"Object: {obj}"
        sources.extend([index[subject_label], index[predicate_label]])
        targets.extend([index[predicate_label], index[object_label]])
        values.extend([count, count])

    fig = go.Figure(
        data=[
            go.Sankey(
                node={"label": labels, "pad": 16, "thickness": 16},
                link={"source": sources, "target": targets, "value": values},
            )
        ]
    )
    fig.update_layout(
        title=f"Top {min(top_n, len(edges))} Subject-Predicate-Object Flows",
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
    )
    return fig


def _collapse_edges(
    edges: tuple[EdgeTriple, ...] | list[EdgeTriple],
) -> list[tuple[str, str, str, int]]:
    counts: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    for edge in edges:
        subject = ", ".join(edge.subject_category) or OTHER_LABEL
        obj = ", ".join(edge.object_category) or OTHER_LABEL
        counts[(subject, edge.predicate, obj)] += edge.count
    return [(subject, predicate, obj, count) for (subject, predicate, obj), count in counts.items()]


def _sankey_labels(edges: list[tuple[str, str, str, int]]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for subject, predicate, obj, _ in edges:
        for label in (
            f"Subject: {subject}",
            f"Predicate: {predicate}",
            f"Object: {obj}",
        ):
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return labels
