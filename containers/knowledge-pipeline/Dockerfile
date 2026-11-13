# syntax=docker/dockerfile:1
# Knowledge-Pipeline: kb-sync (Trilium -> Qdrant Indexer) und knowledge-service
# (REST + MCP Query-Schicht). Ein Image, zwei Entry-Points:
#   python -m knowledge_pipeline.kb_sync            (Deployment ueberpraegt CMD)
#   python -m knowledge_pipeline.knowledge_service  (Default-CMD)
# Liveness/Readiness sind K8s-Probes (kb-sync: 9101/healthz, service: 8000/healthz).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY knowledge_pipeline/ ./knowledge_pipeline/

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER 1000

# knowledge-service API (8000); kb-sync exposing METRICS_PORT (9101)
EXPOSE 8000 9101

CMD ["python", "-m", "knowledge_pipeline.knowledge_service"]
