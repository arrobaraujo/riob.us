# GPS Bus Rio

Aplicação web em Dash para visualização operacional de ônibus no município do Rio de Janeiro, com atualização em tempo real de posições GPS e sobreposição de dados estáticos de GTFS.

O sistema combina dados públicos de mobilidade, geometria municipal e arquivos locais de apoio para permitir filtragem por linha ou veículo, renderização em mapa e monitoramento básico de saúde da aplicação.

## Visão geral

Principais capacidades do projeto:

- Consulta de veículos SPPO e BRT em tempo real.
- Filtro por linhas e por veículos específicos.
- Renderização de itinerários e pontos de parada a partir de GTFS local.
- Exclusão de pontos fora do município e filtragem de veículos em garagem.
- Cache de camadas estáticas e dinâmicas para reduzir custo de processamento.
- Endpoint de health check para deploy e monitoramento.
- Suporte opcional a Redis e Sentry.

## Arquitetura resumida

Stack principal:

- Python 3.12
- Dash + Flask
- Dash Leaflet para visualização cartográfica
- Pandas e GeoPandas para processamento tabular e geoespacial
- Gunicorn para execução em produção
- Redis opcional para cache compartilhado

Fontes de dados utilizadas pela aplicação:

- API pública de GPS SPPO: `https://dados.mobilidade.rio/gps/sppo`
- API pública de GPS BRT: `https://dados.mobilidade.rio/gps/brt`
- Malha municipal do IBGE para limite do Rio de Janeiro
- GTFS local em `gtfs/gtfs.zip`
- Shapefile local de garagens em `garagens/`

## Estrutura do repositório

Arquivos e diretórios mais relevantes:

- `app.py`: ponto de entrada da aplicação e servidor Flask exposto para Gunicorn.
- `ui_layout.py`: composição do layout principal.
- `callbacks_ui.py` e `callbacks_viewport.py`: callbacks da interface e do mapa.
- `gps_data_logic.py`: integração e consolidação dos dados GPS em tempo real.
- `gtfs_static_logic.py`: carga e cache dos dados estáticos de GTFS e geometrias.
- `map_data_logic.py` e `map_layers_logic.py`: preparação das legendas, filtros e camadas do mapa.
- `perf_logging.py`: controle dos logs de performance.
- `tests/`: suíte de testes unitários e smoke tests.
- `assets/`: CSS, service worker e manifesto do frontend.

## Requisitos

Para execução local sem Docker:

- Python 3.12.x recomendado
- `pip` atualizado
- Dependências do `requirements.txt`

Compatibilidade observada no repositório:

- A pipeline de CI valida o projeto em Python 3.11 e 3.12.

Observação:

- O projeto usa bibliotecas geoespaciais como GeoPandas, Shapely, PyProj e Pyogrio. Em ambientes Windows, isso pode exigir toolchain e wheels compatíveis. Se quiser reduzir atrito de setup, prefira a execução via Docker.

## Execução local

### 1. Criar e ativar ambiente virtual

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Instalar dependências

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Iniciar a aplicação

```powershell
python app.py
```

Por padrão, a aplicação sobe em:

- `http://localhost:8050`

O endpoint de health check fica disponível em:

- `http://localhost:8050/health`

## Execução com Docker

O repositório inclui `Dockerfile` e `docker-compose.yml` para execução containerizada.

### Subir a stack

```powershell
docker compose up --build
```

Serviços esperados:

- Aplicação web em `http://localhost:8080`
- Redis em `localhost:6379`

Health check da aplicação em Docker:

- `http://localhost:8080/health`

## Testes

As dependências de teste não estão listadas em `requirements.txt`. Se necessário, instale-as antes de executar a suíte:

```powershell
pip install pytest pytest-cov
```

Para executar a suíte de testes:

```powershell
pytest
```

Se quiser rodar um arquivo específico:

```powershell
pytest tests/test_pipeline_smoke.py
```

## Variáveis de ambiente

Variáveis suportadas pelo código e pela operação em produção:

| Variável | Obrigatória | Padrão | Finalidade |
| --- | --- | --- | --- |
| `PORT` | Não | `8050` local / fornecida pelo host em produção | Porta HTTP usada pela aplicação |
| `REDIS_URL` | Não | vazio | Habilita cache em Redis quando configurada |
| `SENTRY_DSN` | Não | vazio | Habilita envio de erros para o Sentry |
| `PERF_LOG_ENABLED` | Não | `1` no código | Liga ou desliga logs de performance |
| `MAP_STATIC_CACHE_TTL_SECONDS` | Não | `900` | TTL do cache de camadas estáticas |
| `VEHICLE_LAYERS_CACHE_TTL_SECONDS` | Não | `120` | TTL do cache de camadas de veículos |
| `POLL_INTERVAL_IDLE_MS` | Não | `90000` | Intervalo de polling sem seleção ativa |
| `POLL_INTERVAL_LINES_ACTIVE_MS` | Não | `30000` | Intervalo de polling com linhas selecionadas |
| `POLL_INTERVAL_VEHICLES_ACTIVE_MS` | Não | `20000` | Intervalo de polling com veículos selecionados |
| `APP_BUILD_ID` | Não | vazio | Identificador de build exposto no health check |
| `RENDER_GIT_COMMIT` | Não | vazio | Commit de deploy usado como fallback de build id |
| `WEB_CONCURRENCY` | Não | `1` | Número de workers do Gunicorn |
| `GUNICORN_THREADS` | Não | `2` | Threads por worker do Gunicorn |
| `GUNICORN_TIMEOUT` | Não | `180` | Timeout por request no Gunicorn |

## Health check e observabilidade

O endpoint `GET /health` retorna um payload JSON com informações operacionais como:

- status geral
- indicação de carga do GTFS
- timestamp do último update GPS
- presença de dados no último fetch
- estatísticas de cache
- `build_id`
- uso de memória do processo, quando `psutil` estiver disponível

Esse endpoint é usado tanto para monitoramento quanto para health checks de infraestrutura.

## Deploy no Render

O projeto já inclui `render.yaml` com configuração pronta para deploy como Web Service.

Configuração declarada atualmente:

- `buildCommand`: `pip install -r requirements.txt`
- `startCommand`: `gunicorn app:server --bind 0.0.0.0:${PORT:-10000} --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-180} --access-logfile - --error-logfile - --log-level info`
- `PYTHON_VERSION`: `3.12.8`

### Passos recomendados

1. Faça push do código para o repositório remoto.
2. No Render, crie o serviço a partir de `Blueprints` usando o `render.yaml`.
3. Confirme que o serviço foi provisionado com o `startCommand` definido no arquivo.
4. Execute o deploy completo.

### Observação operacional importante

Se o serviço for criado por Blueprint, evite sobrescrever manualmente o Start Command no painel do Render. Isso reduz o risco de regressão de bind de porta, incluindo erros como `No open HTTP ports detected on 0.0.0.0`.

### Perfil inicial sugerido para produção

Use estes valores como ponto de partida e ajuste com base em consumo real de CPU, memória e latência:

- `WEB_CONCURRENCY=1`
- `GUNICORN_THREADS=2`
- `GUNICORN_TIMEOUT=180`
- `PERF_LOG_ENABLED=0`

Para staging ou troubleshooting:

- `PERF_LOG_ENABLED=1`

## Dados locais esperados

O funcionamento completo da aplicação depende destes artefatos versionados ou disponibilizados no ambiente:

- `gtfs/gtfs.zip`
- `gtfs/dicionario_lecd.csv`
- shapefile de garagens em `garagens/`

Além disso, o projeto pode gerar ou reutilizar cache local em:

- `gtfs/gtfs_static_cache.pkl`

## Observações de manutenção

- O cache estático de GTFS depende da assinatura dos arquivos de origem. Alterações em `gtfs/gtfs.zip` ou no shapefile de garagens invalidam automaticamente o cache persistido.
- Sem `REDIS_URL`, a aplicação opera com fallback para cache em memória do processo.
- Sem `SENTRY_DSN`, o envio de erros para Sentry permanece desabilitado.

## Licença e uso

Se este projeto for publicado externamente, vale incluir nesta seção a licença de distribuição e eventuais restrições de uso dos dados consumidos.
