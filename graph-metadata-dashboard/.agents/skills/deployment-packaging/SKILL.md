---
name: deployment-packaging
description: Dockerfile, Helm chart, and k8s deployment conventions for this app - multi-stage build, gunicorn, non-root user, env-var configuration, Helm chart layout. Load before touching Dockerfile, helm/, __main__.py's server entrypoint, or config.py's env-var surface.
---

# Containerization & deployment

The app must be dockerized and deployable to the team's k8s cluster via Helm. **The deliverable is
a working Helm chart** — ITRB handles the Translator-ITRB-AWS-specific parts of deployment on their
end, provided the chart deploys cleanly to k8s. Don't guess at ITRB-specific conventions (approved
base images, registries, etc.) — that's out of scope for this repo; build against standard k8s
conventions instead.

- Multi-stage `Dockerfile`: a build stage (installs dependencies via `uv`) and a slim runtime stage
  — don't ship build tooling in the final image.
- Serve with a production WSGI server (`gunicorn`) behind Dash/Flask, not the Dash/Flask dev
  server — the dev server is single-threaded and not meant for anything beyond local development.
- Run as a **non-root user** in the container — a common baseline requirement for k8s deployments.
- **Configuration via environment variables** (kgx-storage base URL, ORION version pin if it needs
  to be runtime-configurable, cache backend selection, port) — nothing environment-specific
  hardcoded, so the same image runs in different environments (local, CI, prod) via env vars
  alone. See `README.md` for the current env-var surface
  (`KGX_STORAGE_BASE_URL`, `METADATA_CACHE_BACKEND`, `METADATA_CACHE_DIR`,
  `METADATA_CACHE_TTL_SECONDS`, `REQUESTS_TIMEOUT_SECONDS`,
  `REMOTE_METADATA_ALLOWED_URL_PREFIXES`, `REMOTE_METADATA_MAX_BYTES`, `PORT`, `DASH_DEBUG`).
- **Log to stdout/stderr**, not to a file — standard expectation for container log collection in
  k8s.
- If `diskcache` is in use, its storage path should be a container-writable directory (and ideally
  configurable) — see the `caching-layer` skill for why.
- Provide a standard Helm chart (Deployment, Service, ConfigMap for env vars, resource
  requests/limits with sane defaults) — parameterize image tag, replica count, and resource limits
  via `values.yaml` so ITRB can override them for their environment without editing the chart.

## Entrypoint

Deployment entrypoint is an application factory: Gunicorn targets
`graph_metadata_dashboard.app:create_server()`. There is no module-level
`server = create_app().server` — the app must not be constructed at import time.
