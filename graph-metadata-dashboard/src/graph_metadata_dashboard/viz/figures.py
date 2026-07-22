from __future__ import annotations

from collections import defaultdict
from math import sqrt

import plotly.graph_objects as go

from graph_metadata_dashboard.parsers.models import (
    EdgeTriple,
    KnowledgeSourcePredicateCount,
    NodeCategory,
    SubgraphSource,
)

OTHER_LABEL = "Other"
MAX_AXIS_LABEL_LENGTH = 30
MIN_SHARED_PREFIX_LENGTH = 16
SANKEY_BASE_HEIGHT = 700
SANKEY_PIXELS_PER_NODE = 14
SANKEY_MAX_HEIGHT = 4200
SOURCE_PREDICATE_NODE_BODY_PIXELS = 24
SOURCE_PREDICATE_HEIGHT_PADDING = 120
SANKEY_DEFAULT_NODE_PAD = 16
SANKEY_MEDIUM_NODE_PAD = 12
SANKEY_DENSE_NODE_PAD = 8
SANKEY_VERY_DENSE_NODE_PAD = 6
SOURCE_PREDICATE_COMPRESSION_RATIO = 25
SOURCE_PREDICATE_STRONG_COMPRESSION_RATIO = 1_000
PREDICATE_SANKEY_COMPRESSION_RATIO = 25
PREDICATE_SANKEY_STRONG_COMPRESSION_RATIO = 1_000


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
    if len(nodes) <= top_n:
        title = f"{len(nodes)} Node Category Contribution"
    else:
        title = f"Top {top_n} Node Category Contribution"
    fig.update_layout(
        title=title,
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
    if len(subgraphs) <= top_n:
        title = f"{len(subgraphs)} Subgraph Contribution"
    else:
        title = f"Top {top_n} Subgraph Contribution"
    fig.update_layout(
        title=title,
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


# A qualitative palette distinct enough to stay readable at ~35% link opacity against a white
# background. Deterministic assignment (sorted labels -> palette index) so the same category
# gets the same color across renders/filters.
_SUBJECT_PALETTE = [
    "#2563eb", "#dc2626", "#059669", "#7c3aed", "#ea580c",
    "#0891b2", "#db2777", "#65a30d", "#9333ea", "#0d9488",
    "#c2410c", "#4338ca", "#be123c", "#15803d", "#a16207",
]
_NODE_DEFAULT_COLOR = "#64748b"  # predicate/object nodes: neutral slate, not competing with links
_LINK_ALPHA = 0.35


def _assign_palette(labels: list[str]) -> dict[str, str]:
    return {label: _SUBJECT_PALETTE[i % len(_SUBJECT_PALETTE)] for i, label in enumerate(labels)}


def _with_alpha(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def predicate_sankey(
    edges: tuple[EdgeTriple, ...],
    *,
    top_n: int | None = 40,
    subject_filter: str | None = None,
) -> go.Figure:
    # Compute the palette from the FULL subject vocabulary, before top-N filtering, so a
    # category's color is stable regardless of top_n or any future category filter
    all_subject_categories = sorted({
        ", ".join(edge.subject_category) or OTHER_LABEL for edge in edges
    })
    subject_color = _assign_palette(all_subject_categories)

    candidate_edges = _filter_edges_by_subject(edges, subject_filter=subject_filter)
    selected_edges = _select_sankey_edges(candidate_edges, top_n=top_n)
    collapsed = _collapse_edges(selected_edges)
    labels = _sankey_labels(collapsed)
    index = {label: position for position, label in enumerate(labels)}

    # Every triple's two link segments (subject->predicate, predicate->object) share one
    # color, keyed off the *subject* category — this is what lets a viewer visually trace a
    # single subject's flows all the way through the predicate column to its objects
    subject_categories = sorted({subject for subject, _, _, _ in collapsed})
    node_colors = [_NODE_DEFAULT_COLOR] * len(labels)
    for subject in subject_categories:
        node_colors[index[f"Subject: {subject}"]] = subject_color[subject]


    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    link_colors: list[str] = []
    link_customdata: list[list[str]] = []
    node_totals: defaultdict[str, int] = defaultdict(int)
    value_transform = _predicate_sankey_value_transform(
        candidate_edges,
        subject_filter=subject_filter,
    )

    for subject, predicate, obj, count in collapsed:
        subject_label = f"Subject: {subject}"
        predicate_label = f"Predicate: {predicate}"
        object_label = f"Object: {obj}"
        color = _with_alpha(subject_color[subject], _LINK_ALPHA)
        path = f"{subject} -[{predicate}]-> {obj}"
        display_count = _display_count_value(count, value_transform)
        sources.extend([index[subject_label], index[predicate_label]])
        targets.extend([index[predicate_label], index[object_label]])
        values.extend([display_count, display_count])
        link_colors.extend([color, color])
        link_customdata.extend([[path, f"{count:,}"], [path, f"{count:,}"]])
        node_totals[subject_label] += count
        node_totals[predicate_label] += count
        node_totals[object_label] += count

    node_display_labels = [_sankey_display_label(label) for label in labels]
    node_customdata = [[label, f"{node_totals[label]:,}"] for label in labels]
    max_column_nodes = _predicate_sankey_max_column_nodes(collapsed)
    node_pad = _sankey_node_pad(max_column_nodes)

    fig = go.Figure(
        data=[
            go.Sankey(
                node={
                    "label": node_display_labels,
                    "customdata": node_customdata,
                    "hovertemplate": (
                        "%{customdata[0]}"
                        "<br>%{customdata[1]} edges"
                        "<extra></extra>"
                    ),
                    "color": node_colors,
                    "pad": node_pad,
                    "thickness": 16,
                    "line": {"color": "rgba(15, 23, 42, 0.25)", "width": 0.5},
                },
                link={
                    "source": sources,
                    "target": targets,
                    "value": values,
                    "color": link_colors,
                    "customdata": link_customdata,
                    "hovertemplate": (
                        "%{customdata[0]}: %{customdata[1]} edges"
                        "<extra></extra>"
                    ),
                },
            )
        ]
    )
    title = _sankey_title(
        candidate_edges,
        selected_edges,
        top_n=top_n,
        subject_filter=subject_filter,
    )
    fig.update_layout(
        title=title,
        height=_columnar_sankey_height(max_column_nodes, node_pad),
        font={"size": 12},
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
    )
    return fig


def knowledge_source_predicate_sankey(
    counts: tuple[KnowledgeSourcePredicateCount, ...],
    *,
    top_n_sources: int | None = 100,
    top_n_predicates: int | None = 100,
) -> go.Figure:
    source_color = _assign_palette(sorted({count.source for count in counts}))
    collapsed = _collapse_source_predicate_counts(
        counts,
        top_n_sources=top_n_sources,
        top_n_predicates=top_n_predicates,
    )
    labels = _source_predicate_labels(collapsed)
    index = {label: position for position, label in enumerate(labels)}

    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    link_colors: list[str] = []
    link_customdata: list[list[str]] = []
    node_totals: defaultdict[str, int] = defaultdict(int)
    value_transform = _source_predicate_value_transform(collapsed)

    for source, predicate, count in collapsed:
        source_label = f"Source: {source}"
        predicate_label = f"Predicate: {predicate}"
        color = source_color.get(source, _NODE_DEFAULT_COLOR)
        sources.append(index[source_label])
        targets.append(index[predicate_label])
        values.append(_display_count_value(count, value_transform))
        link_colors.append(_with_alpha(color, _LINK_ALPHA))
        link_customdata.append([source, predicate, f"{count:,}"])
        node_totals[source_label] += count
        node_totals[predicate_label] += count

    node_display_labels = [_sankey_display_label(label) for label in labels]
    node_colors = []
    for label in labels:
        if label.startswith("Source: "):
            source = label.removeprefix("Source: ")
            node_colors.append(source_color.get(source, _NODE_DEFAULT_COLOR))
        else:
            node_colors.append(_NODE_DEFAULT_COLOR)
    node_customdata = [[label, f"{node_totals[label]:,}"] for label in labels]
    max_column_nodes = _source_predicate_max_column_nodes(collapsed)
    node_pad = _sankey_node_pad(max_column_nodes)

    fig = go.Figure(
        data=[
            go.Sankey(
                node={
                    "label": node_display_labels,
                    "customdata": node_customdata,
                    "hovertemplate": (
                        "%{customdata[0]}"
                        "<br>%{customdata[1]} edges"
                        "<extra></extra>"
                    ),
                    "color": node_colors,
                    "pad": node_pad,
                    "thickness": 18,
                    "line": {"color": "rgba(15, 23, 42, 0.25)", "width": 0.5},
                },
                link={
                    "source": sources,
                    "target": targets,
                    "value": values,
                    "color": link_colors,
                    "customdata": link_customdata,
                    "hovertemplate": (
                        "%{customdata[0]} -> %{customdata[1]}: %{customdata[2]} edges"
                        "<extra></extra>"
                    ),
                },
                arrangement="snap",
            )
        ]
    )
    fig.update_layout(
        title="Knowledge Source to Predicate Sankey Chart",
        height=_columnar_sankey_height(max_column_nodes, node_pad),
        font={"size": 12},
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
    )
    return fig


def _filter_edges_by_subject(
    edges: tuple[EdgeTriple, ...],
    *,
    subject_filter: str | None,
) -> tuple[EdgeTriple, ...]:
    if subject_filter is None:
        return edges
    return tuple(
        edge
        for edge in edges
        if (", ".join(edge.subject_category) or OTHER_LABEL) == subject_filter
    )


def _select_sankey_edges(
    edges: tuple[EdgeTriple, ...],
    *,
    top_n: int | None,
) -> tuple[EdgeTriple, ...]:
    sorted_edges = tuple(sorted(edges, key=lambda item: item.count, reverse=True))
    if top_n is None or top_n < 0:
        return sorted_edges
    return sorted_edges[:top_n]


def _sankey_title(
    candidate_edges: tuple[EdgeTriple, ...],
    selected_edges: tuple[EdgeTriple, ...],
    *,
    top_n: int | None,
    subject_filter: str | None,
) -> str:
    if subject_filter is not None:
        relationship_count = len(candidate_edges)
        if len(selected_edges) < relationship_count:
            return (
                f"Showing top {len(selected_edges)} of {relationship_count} relationship triples "
                f"within {subject_filter} subject category"
            )
        return f"Showing {relationship_count} relationship triples within {subject_filter}" \
        " subject category"

    if top_n is None or top_n < 0 or len(candidate_edges) <= top_n:
        return "All Subject-Predicate-Object Relationship Triple Sankey Chart"

    return f"Top {top_n} Subject-Predicate-Object Relationship Triple Sankey Chart"


def _sankey_height(labels: list[str]) -> int:
    return min(SANKEY_MAX_HEIGHT, max(SANKEY_BASE_HEIGHT, len(labels) * SANKEY_PIXELS_PER_NODE))


def _predicate_sankey_max_column_nodes(edges: list[tuple[str, str, str, int]]) -> int:
    subjects = {subject for subject, _, _, _ in edges}
    predicates = {predicate for _, predicate, _, _ in edges}
    objects = {obj for _, _, obj, _ in edges}
    return max(len(subjects), len(predicates), len(objects), 1)


def _source_predicate_max_column_nodes(edges: list[tuple[str, str, int]]) -> int:
    sources = {source for source, _, _ in edges}
    predicates = {predicate for _, predicate, _ in edges}
    return max(len(sources), len(predicates), 1)


def _sankey_node_pad(max_column_nodes: int) -> int:
    if max_column_nodes >= 100:
        return SANKEY_VERY_DENSE_NODE_PAD
    if max_column_nodes >= 60:
        return SANKEY_DENSE_NODE_PAD
    if max_column_nodes >= 30:
        return SANKEY_MEDIUM_NODE_PAD
    return SANKEY_DEFAULT_NODE_PAD


def _columnar_sankey_height(max_column_nodes: int, node_pad: int) -> int:
    column_height = (
        max_column_nodes * (SOURCE_PREDICATE_NODE_BODY_PIXELS + node_pad)
        + SOURCE_PREDICATE_HEIGHT_PADDING
    )
    return min(SANKEY_MAX_HEIGHT, max(SANKEY_BASE_HEIGHT, column_height))


def _predicate_sankey_value_transform(
    edges: tuple[EdgeTriple, ...],
    *,
    subject_filter: str | None,
) -> str:
    if subject_filter is not None:
        return "linear"
    return _count_value_transform(
        [edge.count for edge in edges],
        compression_ratio=PREDICATE_SANKEY_COMPRESSION_RATIO,
        strong_compression_ratio=PREDICATE_SANKEY_STRONG_COMPRESSION_RATIO,
        strong_transform="cube_root",
    )


def _source_predicate_value_transform(edges: list[tuple[str, str, int]]) -> str:
    return _count_value_transform(
        [count for _, _, count in edges],
        compression_ratio=SOURCE_PREDICATE_COMPRESSION_RATIO,
        strong_compression_ratio=SOURCE_PREDICATE_STRONG_COMPRESSION_RATIO,
        strong_transform="fourth_root",
    )


def _count_value_transform(
    counts: list[int],
    *,
    compression_ratio: int,
    strong_compression_ratio: int,
    strong_transform: str,
) -> str:
    positive_counts = [count for count in counts if count > 0]
    if not positive_counts:
        return "linear"
    min_count = min(positive_counts)
    max_count = max(positive_counts)
    count_ratio = max_count / min_count
    if count_ratio >= strong_compression_ratio:
        return strong_transform
    if count_ratio >= compression_ratio:
        return "sqrt"
    return "linear"


def _display_count_value(count: int, transform: str) -> float:
    if transform == "fourth_root":
        return max(1.0, count ** 0.25)
    if transform == "cube_root":
        return max(1.0, count ** (1 / 3))
    if transform == "sqrt":
        return max(1.0, sqrt(count))
    return float(count)


def _sankey_display_label(label: str) -> str:
    for prefix in ("Source: ", "Subject: ", "Predicate: ", "Object: "):
        if label.startswith(prefix):
            return label.removeprefix(prefix)
    return label


def _collapse_source_predicate_counts(
    counts: tuple[KnowledgeSourcePredicateCount, ...],
    *,
    top_n_sources: int | None,
    top_n_predicates: int | None,
) -> list[tuple[str, str, int]]:
    source_totals: defaultdict[str, int] = defaultdict(int)
    predicate_totals: defaultdict[str, int] = defaultdict(int)
    for count in counts:
        source_totals[count.source] += count.count
        predicate_totals[count.predicate] += count.count

    selected_sources = _top_labels(source_totals, top_n=top_n_sources)
    selected_predicates = _top_labels(predicate_totals, top_n=top_n_predicates)
    collapsed: defaultdict[tuple[str, str], int] = defaultdict(int)
    for count in counts:
        source = count.source if count.source in selected_sources else OTHER_LABEL
        predicate = count.predicate if count.predicate in selected_predicates else OTHER_LABEL
        collapsed[(source, predicate)] += count.count

    return [
        (source, predicate, count)
        for (source, predicate), count in sorted(
            collapsed.items(),
            key=lambda item: (item[0][0] == OTHER_LABEL, -item[1], item[0][0], item[0][1]),
        )
    ]


def _top_labels(counts: dict[str, int], *, top_n: int | None) -> set[str]:
    if top_n is None or top_n < 0:
        return set(counts)
    return {
        label
        for label, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:top_n]
    }


def _collapse_edges(
    edges: tuple[EdgeTriple, ...] | list[EdgeTriple],
) -> list[tuple[str, str, str, int]]:
    counts: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    for edge in edges:
        subject = ", ".join(edge.subject_category) or OTHER_LABEL
        obj = ", ".join(edge.object_category) or OTHER_LABEL
        counts[(subject, edge.predicate, obj)] += edge.count
    return [(subject, predicate, obj, count) for (subject, predicate, obj), count in counts.items()]


def _source_predicate_labels(edges: list[tuple[str, str, int]]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for source, predicate, _ in edges:
        for label in (f"Source: {source}", f"Predicate: {predicate}"):
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return labels


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
