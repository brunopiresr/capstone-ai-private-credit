# syntax=docker/dockerfile:1
FROM python:3.14-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock .python-version README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra ml --no-install-project

# Keep the editable source layout: paths.py resolves bundled data from /app.
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra ml

FROM python:3.14-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYDANTIC_AI_NO_BANNER=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

COPY --from=builder /app/.venv/ ./.venv/
COPY --from=builder /app/src/ ./src/
COPY .streamlit/ ./.streamlit/
COPY scripts/ ./scripts/
COPY data/app/ ./data/app/
COPY data/models/ ./data/models/

RUN mkdir -p data/runtime data/cache/sec \
    && chown -R app:app data/runtime data/cache

USER app
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()"]

CMD ["streamlit", "run", "src/credit_monitoring/web_v2/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--server.fileWatcherType=none"]
