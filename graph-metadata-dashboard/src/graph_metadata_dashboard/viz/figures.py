from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go

from graph_metadata_dashboard.parsers.models import EdgeTriple, NodeCategory, SubgraphSource

OTHER_LABEL = "Other"
MAX_AXIS_LABEL_LENGTH = 30
MIN_SHARED_PREFIX_LENGTH = 16
SANKEY_BASE_HEIGHT = 700
SANKEY_PIXELS_PER_NODE = 14
SANKEY_MAX_HEIGHT = 4200


def node_category_bar(
    nodes: tuple[NodeCategory, ...],
    *,
    top_n: int = 40,
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
        yaxis=_yaxis_config(log_scale),
    )
    return fig


def subgraph_contribution_bar(
    subgraphs: tuple[SubgraphSource, ...],
    *,
    metric: str = "node_count",
    log_scale: bool = True,
    top_n: int = 40,
) -> go.Figure:
    values: list[tuple[str, str, str, int, int | None, int | None]] = []
    for source in subgraphs:
        count = source.node_count if metric == "node_count" else source.edge_count
        if count is not None:
            values.append(
                (
                    source.name or source.id or "Unknown",
                    _source_id_label(source.id),
                    _subgraph_hover_label(source),
                    count,
                    source.node_count,
                    source.edge_count,
                )
            )
    values = sorted(values, key=lambda item: item[3], reverse=True)[:top_n]
    full_labels = [label for label, _, _, _, _, _ in values]
    fallback_labels = [fallback for _, fallback, _, _, _, _ in values]
    labels = _unique_labels(_shorten_common_labels(full_labels, fallback_labels))
    hover_data = [
        [hover_label, _format_optional_count(node_count), _format_optional_count(edge_count)]
        for _, _, hover_label, _, node_count, edge_count in values
    ]
    counts = [count for _, _, _, count, _, _ in values]
    yaxis_title = "Node count" if metric == "node_count" else "Edge count"

    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=counts,
                customdata=hover_data,
                hovertemplate=(
                    "%{customdata[0]}"
                    "<br>Node count: %{customdata[1]}"
                    "<br>Edge count: %{customdata[2]}"
                    "<extra></extra>"
                ),
                marker_color="#b45309",
            )
        ]
    )
    fig.update_layout(
        title="Top 40 Subgraph Contribution",
        xaxis_title="Subgraph",
        yaxis_title=yaxis_title,
        margin={
            "l": 48,
            "r": 24,
            "t": 56,
            "b": _bottom_margin_for_labels(labels),
        },
        yaxis=_yaxis_config(log_scale),
        xaxis={"automargin": True, "tickangle": -35},
    )
    return fig


def count_bar(
    counts: dict[str, int],
    *,
    title: str,
    xaxis_title: str,
    yaxis_title: str = "Count",
    top_n: int = 40,
    log_scale: bool = True,
    marker_color: str = "#b45309",
) -> go.Figure:
    values = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:top_n]
    fig = go.Figure(
        data=[
            go.Bar(
                x=[label for label, _ in values],
                y=[count for _, count in values],
                marker_color=marker_color,
            )
        ]
    )
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        margin={"l": 48, "r": 24, "t": 56, "b": 120},
        yaxis=_yaxis_config(log_scale),
    )
    return fig


def predicate_sankey(edges: tuple[EdgeTriple, ...], *, top_n: int | None = 40) -> go.Figure:
    selected_edges = _select_sankey_edges(edges, top_n=top_n)
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
        title=_sankey_title(edges, top_n=top_n),
        height=_sankey_height(labels),
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
    )
    return fig


def _select_sankey_edges(
    edges: tuple[EdgeTriple, ...],
    *,
    top_n: int | None,
) -> tuple[EdgeTriple, ...]:
    sorted_edges = tuple(sorted(edges, key=lambda item: item.count, reverse=True))
    if top_n is None or top_n < 0:
        return sorted_edges
    return sorted_edges[:top_n]


def _sankey_title(edges: tuple[EdgeTriple, ...], *, top_n: int | None) -> str:
    if top_n is None or top_n < 0:
        return "All Subject-Predicate-Object Flows"
    return f"Top {min(top_n, len(edges))} Subject-Predicate-Object Flows"


def _sankey_height(labels: list[str]) -> int:
    return min(SANKEY_MAX_HEIGHT, max(SANKEY_BASE_HEIGHT, len(labels) * SANKEY_PIXELS_PER_NODE))


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


def _truncate_label(label: str, *, max_length: int = MAX_AXIS_LABEL_LENGTH) -> str:
    if len(label) <= max_length:
        return label
    if max_length <= 3:
        return "." * max_length
    return f"{label[: max_length - 3]}..."


def _shorten_common_labels(labels: list[str], fallback_labels: list[str]) -> list[str]:
    stripped_prefix = _shared_prefix_to_strip(labels)
    shortened = []
    for index, label in enumerate(labels):
        display_label = label.removeprefix(stripped_prefix).strip() if stripped_prefix else label
        fallback_label = fallback_labels[index] if index < len(fallback_labels) else "Unknown"
        shortened.append(_truncate_label(display_label or fallback_label or "Unknown"))
    return shortened


def _shared_prefix_to_strip(labels: list[str]) -> str:
    if len(labels) < 2:
        return ""
    prefix = _common_prefix(labels)
    if len(prefix.strip()) < MIN_SHARED_PREFIX_LENGTH:
        return ""
    prefix = prefix[: prefix.rfind(" ") + 1]
    if len(prefix.strip()) < MIN_SHARED_PREFIX_LENGTH:
        return ""
    return prefix


def _common_prefix(labels: list[str]) -> str:
    prefix = labels[0]
    for label in labels[1:]:
        while prefix and not label.startswith(prefix):
            prefix = prefix[:-1]
    return prefix


def _bottom_margin_for_labels(labels: list[str]) -> int:
    longest = max((len(label) for label in labels), default=0)
    return max(90, min(150, 36 + longest * 2))


def _yaxis_config(log_scale: bool) -> dict[str, str | int]:
    if not log_scale:
        return {"type": "linear"}
    return {"type": "log", "dtick": 1}


def _source_id_label(source_id: str) -> str:
    parts = source_id.rstrip("/").split("/")
    if len(parts) >= 2:
        return parts[-2]
    return source_id or "Unknown"


def _subgraph_hover_label(source: SubgraphSource) -> str:
    if source.name and source.id:
        return f"{source.name}<br>{source.id}"
    return source.name or source.id or "Unknown"


def _format_optional_count(value: int | None) -> str:
    return f"{value:,}" if value is not None else "Unknown"


def _unique_labels(labels: list[str]) -> list[str]:
    totals: defaultdict[str, int] = defaultdict(int)
    for label in labels:
        totals[label] += 1

    seen: defaultdict[str, int] = defaultdict(int)
    unique_labels = []
    for label in labels:
        seen[label] += 1
        if totals[label] == 1:
            unique_labels.append(label)
        else:
            suffix = f" ({seen[label]})"
            label_max_length = MAX_AXIS_LABEL_LENGTH - len(suffix)
            unique_labels.append(f"{_truncate_label(label, max_length=label_max_length)}{suffix}")
    return unique_labels
