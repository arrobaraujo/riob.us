# Arquitetura do RioB.us

## Visao geral

A aplicacao renderiza dados de onibus em tempo real no mapa, combinando:

- GPS dinamico (SPPO/BRT)
- dados estaticos GTFS
- filtros de interface por linha/veiculo
- cache para camadas estaticas e dinamicas

## Fluxo de dados

1. Polling dispara callback principal.
2. Dados GPS sao buscados e processados.
3. Snapshot atualizado alimenta stores de UI.
4. Camadas de mapa sao recalculadas com filtros ativos.
5. Viewport e legenda sao ajustados conforme contexto.

## Runtime

- Desenvolvimento: `docker compose up --build`
- Producao: Render Docker (`render.yaml` + `Dockerfile`)
- Endpoint tecnico: `GET /health`
- Endpoint amigavel: `GET /status`

## Deep links

- Suportado: filtro por linha via URL (`/linhas/<token>` e `/?linha=<token>`).
- Desativado temporariamente: deeplink de veiculos, para manter estabilidade do fluxo de inicializacao do frontend.

## Organizacao de codigo

Estado atual:

- Implementacao principal consolidada em `src/`.
- Modulos na raiz permanecem como shims de compatibilidade temporarios.
- `app.py` importa componentes diretamente de `src.*`.

Pacotes alvo em `src/`:

- `src/core`: bootstrap e composicao da aplicacao
- `src/ui`: layout e callbacks
- `src/logic`: regras de negocio e montagem de dados
- `src/utils`: helpers compartilhados
- `src/config`: constantes e parametros
- `src/state`: estruturas de estado compartilhado

## Caching e observabilidade

- Cache de camadas estaticas e camadas de veiculos.
- Hit-rate de cache exposto em `/health` e `/status`.
- Redis opcional via `REDIS_URL`; fallback em memoria.

## Decisoes operacionais

- Execucao nativa via `python app.py` desativada por padrao.
- Caminho oficial unico: container.
- Busca manual de veiculos fora do dropdown foi habilitada para casos fora do snapshot recente.
- Em indisponibilidade da API GPS, o modo Linhas segue renderizando shape e legenda via GTFS estatico.
- Commits devem ser pequenos, tematicos e validaveis com testes focados.
