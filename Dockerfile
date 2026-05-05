FROM python:3.12.8-slim

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Sao_Paulo

# Dependências de sistema para libs geoespaciais, timezone e healthcheck local
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    tzdata \
    && ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y build-essential \
    && apt-get autoremove -y \
    && apt-get clean

COPY . .

ENV IN_DOCKER=1

EXPOSE 8080

# Gunicorn usa a porta provida pelo ambiente (Render) ou 8080 local.
CMD ["sh", "-c", "gunicorn src.core.app_runtime:server --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-180} --bind 0.0.0.0:${PORT:-8080} --access-logfile - --error-logfile - --log-level info"]
