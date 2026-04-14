# Arquitetura do RioB.us

## Visao geral

A aplicacao renderiza dados de onibus em tempo real no mapa, combinando:

- GPS dinamico (SPPO/BRT)
- dados estaticos GTFS (shapes, paradas, tarifas, cores de linha)
- filtros de interface por linha/veiculo
- cache para camadas estaticas e dinamicas
- planejamento de rotas intermodais via API externa (Transitous)

## Layout da interface

A interface e organizada em **sidebar + mapa**:

- Sidebar esquerda fixa: abas de filtro (Linhas, Veiculos, Trajetos) e resultados.
- Mapa ocupa o restante da tela e responde aos filtros e selecoes.
- O botao de localizacao (`📍`) e acessivel em todas as abas.
- A toolbar de atualizacao e a legenda sao ocultadas na aba Trajetos.

## Fluxo de dados — modo realtime (Linhas / Veiculos)

1. Polling dispara callback principal.
2. Dados GPS sao buscados e processados.
3. Snapshot atualizado alimenta stores de UI.
4. Camadas de mapa sao recalculadas com filtros ativos.
5. Viewport e legenda sao ajustados conforme contexto.

## Fluxo de dados — modo Trajetos (Roteamento)

1. Usuario preenche Origem e Destino e clica em Buscar.
2. `fetch_geocoding` (Transitous API) resolve os enderecos para coordenadas.
3. `fetch_routing` (Transitous MOTIS 2) calcula itinerarios intermodais.
4. `parse_transitous_response` normaliza a resposta, extraindo legs e paradas intermediarias.
5. O usuario seleciona um card de itinerario.
6. `itineraries_to_geojson` converte o itinerario selecionado em GeoJSON com:
   - cores oficiais das linhas a partir do `line_to_color` (GTFS `route_color`)
   - pontos de parada intermediaria como features `Point`
7. O GeoJSON e armazenado em `store-trajeto-geojson`.
8. `atualizar_mapa_trajeto` renderiza as polylines e marcadores no `layer-trajeto`.
9. O viewport e ajustado via `force_view` com `fitBounds` animado.

## Integracao com Transitous

- API base: `https://api.transitous.org` (MOTIS 2)
- Modulo: `src/logic/transitous_logic.py`
- Endpoints utilizados:
  - `GET /geocode` — resolucao de enderecos
  - `POST /api/v1/plan` — calculo de itinerarios
- Polylines decodificadas com `polyline.decode(..., precision=7)`.
- Recurso **experimental**: dependencia de servico externo sem garantia de SLA.

## Cores GTFS por linha

- Carregadas em background por `_carregar_dados_estaticos` a partir de `routes.txt`.
- Mapeamento: `route_short_name` -> `#RRGGBB` (normalizado de hex sem `#`).
- Disponibilizado via `_get_line_to_color()` (thread-safe com `_gtfs_data_lock`).
- Usado em `itineraries_to_geojson` e na renderizacao dos cards da aba Trajetos.
- Fallback: azul (`#3b82f6`) para trechos a pe, vermelho (`#ef4444`) para onibus sem cor GTFS.

## Runtime

- Desenvolvimento: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`
- Producao: Render Docker (`render.yaml` + `Dockerfile`)
- Endpoint tecnico: `GET /health`
- Endpoint amigavel: `GET /status`

## Deep links

- Suportado: filtro por linha via URL (`/linhas/<token>` e `/?linha=<token>`).
- Desativado temporariamente: deeplink de veiculos, para manter estabilidade do fluxo de inicializacao do frontend.

## Organizacao de codigo

Pacotes em `src/`:

- `src/core`: bootstrap e composicao da aplicacao (`app_runtime.py`)
- `src/ui`: layout (`ui_layout.py`) e callbacks (`callbacks_ui.py`, `callbacks_viewport.py`)
- `src/logic`: regras de negocio e montagem de dados
  - `gtfs_static_logic.py`: carregamento GTFS, cache, cores de linha, tarifas
  - `transitous_logic.py`: geocoding, roteamento, GeoJSON de itinerarios
  - `viewport_logic.py`: calculo de viewport e bounds do mapa
  - `map_layers_logic.py`, `map_data_logic.py`: camadas de onibus e shapes
- `src/utils`: helpers compartilhados
- `src/config`: constantes e parametros
- `src/state`: estruturas de estado compartilhado

## Caching e observabilidade

- Cache de camadas estaticas e camadas de veiculos.
- Cache GTFS estatico em disco (`gtfs/gtfs_static_cache.pkl`) com versionamento por `GTFS_STATIC_CACHE_VERSION`.
- Hit-rate de cache exposto em `/health` e `/status`.
- Redis opcional via `REDIS_URL`; fallback em memoria.

## Versionamento de build (unificado)

- Fonte de verdade: `APP_BUILD_ID` com fallback para `RENDER_GIT_COMMIT`.
- O mesmo build_id e usado em runtime e frontend para evitar estado misto.
- O valor e exposto em `/health` e `/status`.
- O frontend faz refresh controlado quando detecta mudanca de build.
- O Service Worker usa cache versionado por build para invalidacao automatica.

## Persistencia de sessao no frontend

- O filtro de linhas usa persistencia em `localStorage`.
- A chave de persistencia e escopada por build para isolar deploys.
- A selecao de linhas permanece preservada ao alternar para a aba `Veiculos` e voltar.
- Valores restaurados sao saneados contra opcoes atuais de linha.
- Entradas invalidas sao removidas automaticamente com aviso em banner.

## Tema e mapa base no frontend

- A interface possui alternador de tema claro/escuro no cabecalho.
- A escolha de tema e persistida em `localStorage`.
- Sem preferencia salva, o frontend usa `prefers-color-scheme` como comportamento inicial.
- O mapa base e sincronizado com o tema:
  - tema claro -> `Carto Claro`
  - tema escuro -> `Carto Escuro`
- O usuario continua podendo selecionar manualmente outras bases (ex.: `OSM`).

## Decisoes operacionais

- Execucao nativa via Python local desativada por padrao.
- Caminho oficial unico: container.
- Busca manual de veiculos fora do dropdown foi habilitada para casos fora do snapshot recente.
- Em indisponibilidade da API GPS, o modo Linhas segue renderizando shape e legenda via GTFS estatico.
- IDs unicos (`uuid4`) sao atribuidos a cada componente Leaflet de roteamento para evitar reutilizacao incorreta pelo React (bug de cores misturadas ao trocar itinerarios).
- Commits devem ser pequenos, tematicos e validaveis com testes focados.


