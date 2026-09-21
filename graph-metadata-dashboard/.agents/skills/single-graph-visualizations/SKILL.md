---
name: single-graph-visualizations
description: The single-graph MVP visualization list (overview, node categories, provenance, ID-prefix drill-down, attribute fill-rate, predicate Sankey) with the required cardinality-handling pattern for each. Load before adding or changing any chart/table on the single-graph view, or before deciding how to render a large dict/list from schema.json.
---

# Single-graph visualizations

Build in roughly this priority order. **Must handle two very different scales of graph** — small
single-source graphs (e.g. `alliance`) and ROBOKOP KG (~30 merged sources, millions of nodes, tens
of millions of edges, attribute dicts with 1,500+ keys for some categories). Don't design or test
against only the small case. Any list/table/chart of nodes, attributes, or predicates needs a
top-N-plus-search or pagination pattern by default, not "render everything."

1. **Overview panel**: name, version, dates, biolink/babel versions, license, total node/edge
   counts. Use `KGXGraphMetadata`'s accessors for graph-level fields, and
   `schema["nodes_summary"]`/`schema["edges_summary"]` (when `schema.json` is loaded) for total
   counts — don't re-derive totals from the granular `nodes`/`edges` arrays when ORION already
   aggregated them. Must render fully and gracefully with no schema data available.
2. **Node category breakdown** (bar or treemap, log-scale toggle) from `schema.nodes[].count`.
3. **Source/provenance table** from `isBasedOn` (`KGXKnowledgeSource` objects, already parsed by
   `KGXGraphMetadata.from_dict()`), plus a chart of subgraph contribution from `hasPart` (each
   entry needs `KGXKnowledgeGraphSource.from_dict()` first — see `orion-metadata-format` skill).
4. **ID-prefix composition per category** (drill-down from #2) from `schema.nodes[].id_prefixes`.
5. **Attribute fill-rate view per category**, top-N + search. Already sorted descending in the
   source data, so top-N is a slice, not a sort.
6. **Predicate/edge-composition Sankey diagram** (subject category → predicate → object category,
   sized by edge count) — a genuinely useful, proven visualization for KG edge composition, worth
   matching or improving on the existing ROBOKOP KG page's Sankey view, not skipping. Data source
   is `schema.edges[]`. **Cardinality is a real problem at ROBOKOP scale** — a merged graph
   produces far too many subject/predicate/object combinations to read unfiltered. Apply top-N /
   collapse the long tail into an "Other" bucket, and consider letting the user filter to a
   specific subject or object category first. Don't ship the naive "one flow per triple" version.
7. **Optional stretch**: using `schema["edges_summary"]["predicates_by_knowledge_source"]`
   (already aggregated by ORION), a "predicate composition per knowledge source" view. Implemented
   as a Sankey (source → predicate) — this was decided already, don't re-litigate as heatmap/
   stacked-bar/table.

Do not attempt to render actual graph topology (nodes-and-edges diagrams) — metadata visualization
only, per explicit project scope.
