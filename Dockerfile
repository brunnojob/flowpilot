# syntax=docker/dockerfile:1
# ---------------------------------------------------------------- build stage
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# -------------------------------------------------------------- runtime stage
FROM python:3.12-slim
LABEL org.opencontainers.image.title="flowpilot" \
      org.opencontainers.image.description="Lightweight self-hosted workflow automation with first-class Telegram support" \
      org.opencontainers.image.source="https://github.com/mrzroot/flowpilot" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLOWPILOT_PROJECT=/app \
    FLOWPILOT_HOST=0.0.0.0 \
    FLOWPILOT_PORT=8080 \
    TZ=UTC

COPY --from=build /dist/*.whl /tmp/
RUN pip install "$(ls /tmp/*.whl)[socks]" && rm -f /tmp/*.whl \
    && useradd --create-home --uid 1000 flowpilot \
    && mkdir -p /app && chown flowpilot:flowpilot /app

USER flowpilot
WORKDIR /app
VOLUME ["/app"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)" || exit 1

# Scaffold a project on first start if the volume is empty, then serve.
CMD ["sh", "-c", "[ -d workflows ] || flowpilot init . ; exec flowpilot serve"]
