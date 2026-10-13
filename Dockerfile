# python:3.12-slim multi-arch index digest resolved 2026-10-11. Refresh deliberately after review with:
#   docker buildx imagetools inspect python:3.12-slim
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
USER 65532:65532
EXPOSE 8080
# Cloud Run sends SIGTERM and, ten seconds later, SIGKILL: finish in-flight requests within eight.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "8"]
