# gps-bus-rio

## Deploy no Render

Este projeto já inclui `render.yaml` com os comandos corretos de build e start.

### O que está configurado

- `buildCommand`: `pip install -r requirements.txt`
- `startCommand`: `gunicorn app:server --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 2 --timeout 180 --access-logfile - --error-logfile - --log-level info`
- `PYTHON_VERSION`: `3.12.8`

### Como subir

1. Faça push do código com `render.yaml` para o repositório.
2. No Render, use `Blueprints` e conecte/sincronize este repositório.
3. Confirme que o serviço foi criado a partir do `render.yaml`.
4. Execute um deploy completo.

### Observação importante

Se o serviço for criado por Blueprint, evite sobrescrever manualmente o `Start Command` no painel.
Isso evita regressões de porta como `No open HTTP ports detected`.
