from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class SchemaReference:
    kind: Literal["inline", "pointer", "absent"]
    url: str | None = None


@dataclass(frozen=True)
class KnowledgeSource:
    id: str
    name: str
    description: str
    license: str
    attribution: str
    citation: list[str]
    version: str


@dataclass(frozen=True)
class SubgraphSource:
    id: str
    name: str
    node_count: int | None
    edge_count: int | None


@dataclass(frozen=True)
class NodeCategory:
    category: str
    count: int
    id_prefixes: dict[str, int]
    attributes: dict[str, int]


@dataclass(frozen=True)
class EdgeTriple:
    subject_category: tuple[str, ...]
    predicate: str
    object_category: tuple[str, ...]
    count: int
    primary_knowledge_sources: dict[str, int]
    qualifiers: dict[str, int]
    attributes: dict[str, int]
    subject_id_prefixes: dict[str, int]
    object_id_prefixes: dict[str, int]


@dataclass(frozen=True)
class GraphSchema:
    nodes: tuple[NodeCategory, ...]
    edges: tuple[EdgeTriple, ...]
    nodes_summary: JsonObject
    edges_summary: JsonObject
    raw: JsonObject

    @property
    def total_node_count(self) -> int | None:
        return int_or_none(self.nodes_summary.get("total_count", None))

    @property
    def total_edge_count(self) -> int | None:
        return int_or_none(self.edges_summary.get("total_count", None))


@dataclass(frozen=True)
class ParsedGraphMetadata:
    name: str
    description: str
    release_version: str
    build_version: str
    build_time: str
    date_created: str
    date_modified: str
    license: str
    biolink_version: str
    babel_version: str
    source_ids: tuple[str, ...]
    knowledge_sources: tuple[KnowledgeSource, ...]
    subgraphs: tuple[SubgraphSource, ...]
    schema_reference: SchemaReference
    schema: GraphSchema | None
    schema_version_marker: str
    raw: JsonObject

    @property
    def total_node_count(self) -> int | None:
        if self.schema is not None:
            return self.schema.total_node_count
        values = [source.node_count for source in self.subgraphs if source.node_count is not None]
        return sum(values) if values else None

    @property
    def total_edge_count(self) -> int | None:
        if self.schema is not None:
            return self.schema.total_edge_count
        values = [source.edge_count for source in self.subgraphs if source.edge_count is not None]
        return sum(values) if values else None


def int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
