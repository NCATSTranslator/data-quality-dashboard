# graph-metadata-dashboard

A Dash app for visualizing and comparing [ORION](https://github.com/robokopu24/orion)-produced knowledge graph metadata for [Biomedical Data Translator](https://ui.transltr.io/) graphs and [ROBOKOP](https://robokop.renci.org/) graphs.

## Workflow

- Load the latest Biomedical Data Translator knowledge graph metadata files from its [KGX storage release manifest](https://kgx-storage.ci.transltr.io/releases/latest-release-summary.json) for user selection.
- Allow users to upload a local ORION-produced graph metadata JSON file and optional linked schema JSON file.
- Parse graph metadata through ORION's `KGXGraphMetadata` class.
- Keep metadata payloads in a server-side cache, scoped by session.
- Render overview, source and subgraph provenance, node category, and predicate/edge composition Sankey views when one graph is loaded.
- Render comparative visualizations when two or more graphs are loaded (to be implemented).

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

The app listens on the port number set by the `PORT` environment variable or defaults to `8050`.

## Configuration by Environment Variables

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
