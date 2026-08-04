FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FITNESS_DB_PATH=/data/fitness/fitness.db \
    FRONTEND_DIST=/app/frontend/dist \
    UVICORN_FORWARDED_ALLOW_IPS=127.0.0.1
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY api ./api
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /data/fitness \
    && chown -R appuser:appuser /app /data/fitness
EXPOSE 8092
USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8092/api/health', timeout=3).read()" || exit 1
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port 8092 --proxy-headers --forwarded-allow-ips \"${UVICORN_FORWARDED_ALLOW_IPS}\""]
