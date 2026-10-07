---
name: single-graph-visualizations
description: Single-graph visualization scope and resolved UI decisions, including contribution-bar sizing, label truncation, category-pair caps, and Sankey cardinality controls. Load before adding or changing any chart/table on the single-graph view, or before deciding how to render a large dict/list from schema.json.
---

# Single-graph visualizations

Build in roughly this priority order. **Must handle two very different scales of graph** — small
single-source graphs (e.g. `alliance`) and ROBOKOP KG (~30 merged sources, millions of nodes, tens
of millions of edges, attribute dicts with 1,500+ keys for some categories). Don't design or test
against only the small case. Use top-N, search, pagination, or drill-down for large lists by
default. The approved exceptions are the subgraph/source and node-category contribution bars,
which show all available contributions with compact bars and horizontal scrolling. This does
not extend to subject-object category pairs or Sankey flows; see the resolved decisions below.

1. **Overview panel**: name, version, dates, biolink/babel versions, license, total node/edge
   counts. Use `KGXGraphMetadata`'s accessors for graph-level fields, and
   `schema["nodes_summary"]`/`schema["edges_summary"]` (when `schema.json` is loaded) for total
   counts — don't re-derive totals from the granular `nodes`/`edges` arrays when ORION already
   aggregated them. Must render fully and gracefully with no schema data available.
2. **Node category breakdown**: contribution bar from `schema.nodes[].count`, sorted by count,
   with logarithmic scale by default and no top-N cutoff.
3. **Source/provenance table** from `isBasedOn` (`KGXKnowledgeSource` objects, already parsed by
   `KGXGraphMetadata.from_dict()`), plus a chart of subgraph contribution from `hasPart` (each
   entry needs `KGXKnowledgeGraphSource.from_dict()` first — see `orion-metadata-format` skill).
4. **ID-prefix composition per category** (drill-down from #2) from `schema.nodes[].id_prefixes`.
5. **Attribute fill-rate view per category**, top-N + search. Already sorted descending in the
   source data, so top-N is a slice, not a sort.
6. **Predicate Composition panel** has three perspectives: an inline subject-object category
   pair contribution bar, a knowledge-source → predicate Sankey, and a subject-category →
   predicate → object-category Sankey. The pair chart has no Show/Hide toggle or visibility store;
   it renders with the selected single graph, independently of the Sankey Show/Hide controls.
   **Predicate/edge-composition Sankey diagram** (subject category → predicate → object category,
   sized by edge count) — a genuinely useful, proven visualization for KG edge composition, worth
   matching or improving on the existing ROBOKOP KG page's Sankey view, not skipping. Data source
   is `schema.edges[]`. **Cardinality is a real problem at ROBOKOP scale** — a merged graph
   produces far too many subject/predicate/object combinations to read unfiltered. Apply top-N /
   collapse the long tail into an "Other" bucket, and consider letting the user filter to a
   specific subject or object category first. Don't ship the naive "one flow per triple" version.
7. **Knowledge-source predicate composition**: using
   `schema["edges_summary"]["predicates_by_knowledge_source"]` (already aggregated by ORION).
   Implemented
   as a Sankey (source → predicate) — this was decided already, don't re-litigate as heatmap/
   stacked-bar/table.

Do not attempt to render actual graph topology (nodes-and-edges diagrams) — metadata visualization
only, per explicit project scope.

## Resolved contribution-chart decisions

- `viz/figures.py` owns figure construction. Reuse `_contribution_chart_height()` and
  `contribution_chart_style()` for subgraph/source, node-category, and subject-object pair bars;
  avoid separate sizing formulas in callbacks or components.
- Shared layout: 24px per displayed bar plus 100px padding, at least 700px wide or the full
  container width, with horizontal overflow in `.contribution-panel`. Bars have no inter-bar
  gaps and thin borders. Axis labels use 10px text at -55 degrees, an 8px axis-title standoff,
  and a compact 24px bottom margin with automatic label margins.
- Height is data-adaptive: the shared helper currently reserves a 240px plotting-height budget
  and adds top/label space based on the longest displayed label. Preserve the user's tuned
  formula rather than reinstating a fixed 550px height or an additional scaling factor. Set the
  returned height explicitly on the `dcc.Graph` container: `responsive=True` does not preserve
  figure height by itself. Longer labels can still warrant a taller chart under the same rule.
- Node-category and pair axis labels strip **every** `biolink:` occurrence, including prefixes
  after commas, then truncate to `MAX_AXIS_LABEL_LENGTH` (currently 30 characters including
  `...`). Only display labels change; keep full identifiers in bar tooltips. Node bars use
  explicit full-category `customdata`; pair bars retain full subject/object hover fields.
  Keep labels below the bars, not inside them. Subgraph labels retain the existing source-name
  shortening logic; do not add a new category-style truncation policy to them.
- Subgraph and primary-knowledge-source fallback charts show all contributions with available
  counts, sorted descending. Prefer node counts; fall back to edge counts when no node counts
  exist, then schema primary-source counts when subgraph counts are absent. Preserve single-source
  statements instead of drawing a one-bar chart. No top-N/search inputs for these charts or the
  node-category chart in this first pass.
- Titles count displayed bars, e.g. `29 Subgraph Contribution` or `65 Node Category Contribution`.
  Do not restore the former shown/available/missing-count subtitle.
- Subject-object pair bars aggregate counts across predicates for each typed category pair,
  rank by edge count, and render only the top `DEFAULT_TOP_COUNT` (currently 50). The title
  includes the **total distinct pair count before truncation**, e.g.
  `1,409 Subject-Object Category Pair Contribution (Top 50)`; omit the top-N suffix when all
  pairs fit. Only construct labels, hover previews, and bar arrays for selected pairs.
- Rendering all category pairs caused a browser "Page unresponsive" prompt. Horizontal
  scrolling still renders every bar and tick label; it is not virtualization. Keep pair
  rendering bounded. A bounded top-N selector, subject/object filtering, or a paginated table
  are possible follow-ups, not approved first-pass features. Python figure-build timing alone
  does not establish browser rendering performance.

## Retained top-N and validation policy

- Do not remove `DEFAULT_TOP_COUNT` just because subgraph and node-category bars no longer use
  it. It still supplies defaults for category pairs, generic count bars, and predicate-Sankey
  figure/selection helpers.
- Preserve the separate Sankey UI defaults: `ALL_CATEGORY_SANKEY_TOP_N = 40`,
  `SUBJECT_CATEGORY_SANKEY_TOP_N = 200`, and `SOURCE_PREDICATE_SANKEY_TOP_N = 100`. Keep existing
  filters and adjustable sliders. Dense crossing links do not become legible merely by adding
  scrolling or increasing height; do not automatically render every flow.
- Validate changes in `tests/viz/test_figures.py` and `tests/pages/test_dashboard.py`, covering
  all three real fixture tiers, labels at/beyond the truncation boundary, full prefixed hover
  identifiers, bounded pair payloads with correct total-count titles, and shared container
  sizing. Preserve unavailable-schema and empty-data behavior. Browser appearance/performance
  is a separate check; passing Python tests is not visual confirmation.
