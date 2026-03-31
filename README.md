# GPS Bus Rio

Aplicacao web em Dash para visualizacao operacional de onibus no municipio do Rio de Janeiro, com atualizacao em tempo real de posicoes GPS e sobreposicao de dados estaticos GTFS.

## Estado atual da entrega

- Execucao oficial em desenvolvimento e producao: Docker.
- Deploy oficial em producao: Render com runtime Docker (`render.yaml`).
- Endpoint tecnico para monitoramento: `GET /health`.
- Pagina amigavel para suporte operacional: `GET /status`.
- Aba Veiculos aceita busca manual de ID fora da listagem atual do dropdown.
- Reorganizacao estrutural iniciada com pacote `src/` (migracao gradual).

## Visao geral

Principais capacidades:

- Consulta de veiculos SPPO e BRT em tempo real.
- Filtro por linhas e por veiculos especificos.
- Renderizacao de itinerarios e pontos de parada a partir de GTFS local.
- Exclusao de pontos fora do municipio e filtragem de veiculos em garagem.
- Cache de camadas estaticas e dinamicas para reduzir custo de processamento.
- Health check tecnico e status amigavel para operacao.
- Suporte opcional a Redis e Sentry.

## Stack

- Python 3.12.x
- Dash + Flask
- Dash Leaflet
- Pandas + GeoPandas
- Gunicorn
- Redis (opcional)
- Docker / Docker Compose

## Estrutura do repositorio

Estrutura em transicao para boas praticas com `src/`:

- `app.py`: entrypoint atual e servidor Flask/Dash.
- `callbacks_ui.py`, `callbacks_viewport.py`: callbacks de interface e viewport.
- `*_logic.py`, `*_helpers.py`: logica de negocio/utilitarios (legado em raiz durante migracao).
- `src/`: pacote Python oficial em formacao (`config`, `core`, `logic`, `state`, `ui`, `utils`).
- `tests/`: suite de testes automatizados.
- `assets/`: CSS e arquivos estaticos web.

> Observacao: a migracao de modulos para `src/` sera feita de forma gradual para evitar regressao funcional.

## Requisitos

- Docker Desktop (Windows/macOS) ou Docker Engine + Compose plugin (Linux)
- Acesso aos dados locais:
  - `gtfs/gtfs.zip`
  - `gtfs/dicionario_lecd.csv`
  - shapefile de garagens em `garagens/`

## Execucao local (Docker-only)

### Subir stack

```powershell
docker compose up --build
```

Esse comando usa o perfil base (producao-like), sem hot reload.

### Subir stack com hot reload (desenvolvimento)

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Nesse modo, o codigo local e montado no container e o Gunicorn roda com
`--reload`, entao alteracoes em arquivos Python sao aplicadas automaticamente.

Servicos esperados:

- App: `http://localhost:8080`
- Redis: `localhost:6379`

### Endpoints de operacao

- Health tecnico: `http://localhost:8080/health`
- Status amigavel: `http://localhost:8080/status`

## Deploy em producao (Render Docker)

O deploy e feito pelo `render.yaml` com `env: docker` e `dockerfilePath: ./Dockerfile`.

Passos recomendados:

1. Fazer push para o repositorio remoto.
2. Criar/atualizar o servico no Render por Blueprint.
3. Confirmar uso do Docker runtime e variaveis de ambiente.
4. Validar `/health` e `/status` apos deploy.

## Variaveis de ambiente

| Variavel | Obrigatoria | Padrao | Finalidade |
| --- | --- | --- | --- |
| `PORT` | Nao | `8080` | Porta HTTP usada pelo Gunicorn |
| `IN_DOCKER` | Sim (runtime oficial) | `1` | Garante execucao em ambiente containerizado |
| `REDIS_URL` | Nao | vazio | Habilita cache Redis quando configurado |
| `SENTRY_DSN` | Nao | vazio | Habilita envio de erros para Sentry |
| `PERF_LOG_ENABLED` | Nao | `1` local / `0` sugerido em prod | Liga/desliga logs de performance |
| `WEB_CONCURRENCY` | Nao | `2` | Workers do Gunicorn |
| `GUNICORN_THREADS` | Nao | `2` | Threads por worker |
| `GUNICORN_TIMEOUT` | Nao | `180` | Timeout por request |
| `MAP_STATIC_CACHE_TTL_SECONDS` | Nao | `900` | TTL cache camadas estaticas |
| `VEHICLE_LAYERS_CACHE_TTL_SECONDS` | Nao | `120` | TTL cache camadas de veiculos |
| `POLL_INTERVAL_IDLE_MS` | Nao | `90000` | Poll sem selecao ativa |
| `POLL_INTERVAL_LINES_ACTIVE_MS` | Nao | `30000` | Poll com linhas selecionadas |
| `POLL_INTERVAL_VEHICLES_ACTIVE_MS` | Nao | `20000` | Poll com veiculos selecionados |
| `APP_BUILD_ID` | Nao | vazio | ID de build exibido em health/status |

## Busca de veiculos fora da listagem

Na aba Veiculos:

- O dropdown continua priorizando veiculos recentes do snapshot.
- Ao digitar um ID nao presente na lista, aparece uma opcao de busca manual.
- Essa opcao pode ser selecionada para filtrar o mapa sem depender da opcao pre-carregada.

Regras de busca manual:

- Busca por valor completo: `A50001`.
- Busca por sufixo numerico: `50001` tambem encontra `A50001`.

## Deep links (filtros via URL)

Voce pode abrir filtros diretamente pela URL:

- Linha: `https://riob.us/linhas/LECD137`

Comportamento:

- A aba `Linhas` e ativada automaticamente.
- O filtro correspondente e aplicado no carregamento da pagina.

Observacao:

- Deep link de veiculos foi desativado temporariamente para estabilizacao.

## Testes

Execute os testes no ambiente local (ou dentro do container de app):

```powershell
pytest
```

Smoke recomendado apos alteracoes de runtime:

```powershell
curl http://localhost:8080/health
curl http://localhost:8080/status
```

## Observabilidade

`GET /health` retorna JSON com:

- status geral
- GTFS carregado
- timestamp do ultimo update GPS
- indicador de fetch com dados
- estatisticas de cache
- build_id
- uso de memoria (quando `psutil` estiver disponivel)

`GET /status` expoe painel HTML amigavel para suporte e troubleshooting operacional.

## Proximos passos de organizacao

- Migrar modulos legados da raiz para `src/` por dominio.
- Atualizar imports internos e testes para `src`.
- Remover camada legada apos validacao completa.

## Fluxo de commits recomendados

Antes de publicar:

1. Revisar alteracoes: `git status` e `git diff --name-only`.
2. Revisar historico recente: `git log --oneline -5`.
3. Validar testes impactados.

Para publicar commits locais ja criados:

```powershell
git push origin main
```

## Licenca e uso

Se o projeto for publicado externamente, incluir nesta secao a licenca de distribuicao e as restricoes de uso das fontes de dados utilizadas.
