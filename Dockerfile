FROM python:3.11-slim

WORKDIR /app

# Instalar dependências de sistema (caso necessário para extensões C)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Adicionar gevent para workers assíncronos mais eficientes no gunicorn (opcional, recomendado para SSE/Dash)
RUN pip install --no-cache-dir gevent

COPY . .

# Expor porta 8080 configurada no docker-compose
EXPOSE 8080

# Usar Gunicorn com gevent workers
CMD ["gunicorn", "-w", "4", "-k", "gevent", "--timeout", "120", "-b", "0.0.0.0:8080", "app:server"]
