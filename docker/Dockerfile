FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HA_SEARCH_VERSIONS_ROOT=/versions
ENV HA_SEARCH_CLI=/app/engine.py
ENV HA_SEARCH_TIMEOUT=15
ENV HA_SEARCH_MAX_QUERY_LEN=200

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src

RUN pip install --no-cache-dir .

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app \
    && chmod -R u+rX /app

USER appuser

EXPOSE 8099

CMD ["python3", "-m", "ha_archive_search.webapp"]