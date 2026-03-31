FROM python:3.12.8-slim

WORKDIR /app

# Dependências de sistema para libs geoespaciais e healthcheck local
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV IN_DOCKER=1

EXPOSE 8080

# Gunicorn usa a porta provida pelo ambiente (Render) ou 8080 local.
CMD ["sh", "-c", "gunicorn src.core.app_runtime:server --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-180} --bind 0.0.0.0:${PORT:-8080} --access-logfile - --error-logfile - --log-level info"]
