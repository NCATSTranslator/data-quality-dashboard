FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml README.md uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8050
ENV METADATA_CACHE_DIR=/tmp/graph-metadata-dashboard-cache

RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --from=builder /app /app

USER appuser
EXPOSE 8050

CMD ["gunicorn", "--bind", "0.0.0.0:8050", "graph_metadata_dashboard.app:create_server()"]
