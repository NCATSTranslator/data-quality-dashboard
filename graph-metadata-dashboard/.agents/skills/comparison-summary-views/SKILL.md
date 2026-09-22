---
name: comparison-summary-views
description: Design and implement compact graph-comparison summary views such as Top Movers, Breaking-Change View, and 3+ graph heatmaps using existing diff outputs.
---

# Comparison Summary Views

Use this skill when adding or changing graph-comparison summaries that sit above detailed diff
tables. These views should help users answer "what changed most?" without replacing the literal
ORION diff browser.

## Design Principles

- Reuse `GraphComparison` / `SchemaDiffSummary` outputs from `diff/`; do not add a parallel diff
  algorithm or call ORION from Dash components.
- Keep summary views top-N by default. ROBOKOP-scale schema diffs can be large, so never render all
  node categories, edge triples, predicates, attributes, or sources in a summary.
- Summaries should be compact and scannable. Use detailed collapsible panels for complete context,
  and avoid standalone summary blocks that duplicate the tables immediately below them.
- Preserve the baseline-vs-selected-graph strategy for 2+ comparisons. For 3+ graphs, summarize
  each baseline-vs-target comparison independently unless explicitly implementing a matrix/heatmap.
- Prefer lightweight HTML/CSS visual encodings already used by the comparison view before adding
  Plotly charts.

## Recommended Views

- **Integrated Top Movers:** Prefer sorting detailed node category, edge triple, and overall
  rollup sections by largest impact so the biggest movers appear first. Add concise notes or
  subtle highlighting rather than a separate duplicate "Top Movers" section unless users need a
  cross-section digest.
- **Breaking-Change View:** Highlight removed schema elements only: node categories, edge triples,
  predicates, ID prefixes, and primary sources.
- **3+ Graph Heatmap:** Compare a baseline against multiple selected graphs for top changed
  categories/predicates. Keep rows top-N and columns to selected comparisons.

## Validation

Add or update tests for rendered labels/classes and sorting/top-N behavior. Before finishing, run:

```bash
uv run ruff check .
uv run pytest
```
