# gps-bus-rio

## Deploy no Render

Este projeto já inclui `render.yaml` com os comandos corretos de build e start.

### O que está configurado

- `buildCommand`: `pip install -r requirements.txt`
- `startCommand`: `gunicorn app:server --bind 0.0.0.0:${PORT:-10000} --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-180} --access-logfile - --error-logfile - --log-level info`
- `PYTHON_VERSION`: `3.12.8`

### Variaveis de ambiente uteis

- `WEB_CONCURRENCY`: numero de workers do Gunicorn.
- `GUNICORN_THREADS`: numero de threads por worker.
- `GUNICORN_TIMEOUT`: timeout em segundos por request.
- `PERF_LOG_ENABLED`: controla logs de performance. No `render.yaml` de producao esta `0` por padrao (silenciado). Em staging/dev, use `1` para habilitar os logs `PERF ...`.
- `MAP_STATIC_CACHE_TTL_SECONDS`: TTL do cache de itinerarios/paradas em segundos (padrao: `900`).
- `VEHICLE_LAYERS_CACHE_TTL_SECONDS`: TTL do cache de camadas de veiculos em segundos (padrao: `120`).
- `POLL_INTERVAL_IDLE_MS`: intervalo de polling quando nao ha selecao ativa (padrao: `90000`).
- `POLL_INTERVAL_LINES_ACTIVE_MS`: intervalo de polling quando ha linhas selecionadas (padrao: `30000`).
- `POLL_INTERVAL_VEHICLES_ACTIVE_MS`: intervalo de polling quando ha veiculos selecionados (padrao: `20000`).

### Perfis recomendados (staging x producao)

Use estes valores como ponto de partida e ajuste conforme consumo real de CPU/memoria:

- Staging:
	- `WEB_CONCURRENCY=1`
	- `GUNICORN_THREADS=2`
	- `GUNICORN_TIMEOUT=180`
	- `PERF_LOG_ENABLED=1`
- Producao:
	- `WEB_CONCURRENCY=1`
	- `GUNICORN_THREADS=2`
	- `GUNICORN_TIMEOUT=180`
	- `PERF_LOG_ENABLED=0`

Notas operacionais:

- Se houver timeout frequente, aumente `GUNICORN_TIMEOUT` primeiro.
- Se houver fila de requests, teste subir `WEB_CONCURRENCY` para `2` e reavalie memoria.
- Mantenha `PERF_LOG_ENABLED=1` apenas em staging/dev ou troubleshooting pontual em producao.

### Como subir

1. Faça push do código com `render.yaml` para o repositório.
2. No Render, use `Blueprints` e conecte/sincronize este repositório.
3. Confirme que o serviço foi criado a partir do `render.yaml`.
4. Execute um deploy completo.

### Observação importante

Se o serviço for criado por Blueprint, evite sobrescrever manualmente o `Start Command` no painel.
Isso evita regressões de porta como `No open HTTP ports detected`.
