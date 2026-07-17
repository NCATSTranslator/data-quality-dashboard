# graph-metadata-dashboard

A Dash app for visualizing ORION-produced knowledge graph metadata for Biomedical Data Translator
graphs.

## Current Scope

This first pass implements the single-graph workflow:

- Load the latest KGX-storage releases from the manifest.
- Upload a local `graph-metadata.json` and optional `schema.json`.
- Parse graph metadata through ORION's `KGXGraphMetadata`.
- Keep metadata payloads in a server-side cache, scoped by session.
- Render overview, provenance, node-category, and Sankey views.

The comparison page is present as a placeholder only. Comparison visualizations are deferred until
the ORION comparison module is available.

## Open Visualization Scope

The following AGENTS.md visualization items are intentionally still open:

- ID-prefix composition drill-down per node category.
- Attribute fill-rate view per category with top-N plus search.
- Predicate composition per knowledge source from `predicates_by_knowledge_source`.

## Local Development

Install dependencies:

```bash
uv sync --extra dev
```

Run tests:

```bash
uv run pytest
```

Start the Dash development server:

```bash
uv run graph-metadata-dashboard
```

The app listens on `PORT` or defaults to `8050`.

## Configuration

Configuration is environment-variable based:

- `KGX_STORAGE_BASE_URL`: defaults to `https://kgx-storage.ci.transltr.io/releases`
- `METADATA_CACHE_BACKEND`: defaults to `diskcache`
- `METADATA_CACHE_DIR`: defaults to `/tmp/graph-metadata-dashboard-cache`
- `METADATA_CACHE_TTL_SECONDS`: defaults to `3600`
- `REQUESTS_TIMEOUT_SECONDS`: defaults to `20`
- `PORT`: defaults to `8050`
- `DASH_DEBUG`: defaults to `false`

## Container and Helm

Build the container:

```bash
docker build -t graph-metadata-dashboard:latest .
```

Render the Helm chart:

```bash
helm template graph-metadata-dashboard charts/graph-metadata-dashboard
```
