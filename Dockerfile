# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build stage
# Build wheels for the package and its dependencies so the runtime image installs offline and
# carries no compilers, caches or source tree. The sample corpus (Markdown, CSV, PDF, PNG +
# metadata) ships inside the omniknow wheel as package data.
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels .

# -------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="OmniKnow AI" \
      org.opencontainers.image.description="Multimodal enterprise knowledge agent: ACL-aware hybrid RAG with cited answers" \
      org.opencontainers.image.source="https://github.com/bharatkumar00797/omniknow-ai-multimodal-rag" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    OMNIKNOW_PROVIDER=mock

RUN groupadd --system --gid 10001 omniknow \
 && useradd --system --uid 10001 --gid omniknow --home-dir /app --shell /usr/sbin/nologin omniknow

COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels omniknow-ai-multimodal-rag \
 && rm -rf /wheels \
 && python -c "from omniknow.ingest import load_corpus; assert len(load_corpus()) >= 9"

WORKDIR /app
USER omniknow
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)"]

# Shell form only to expand $PORT (Render, Railway, Fly and Cloud Run inject it).
CMD ["sh", "-c", "exec omniknow serve --host 0.0.0.0 --port \"${PORT:-8000}\""]
