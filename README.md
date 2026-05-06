# RioB.us

Aplicacao web em Dash para visualizacao operacional de onibus, com atualizacao em tempo real de posicoes GPS, sobreposicao de dados estaticos GTFS e planejamento de rotas intermodais.

## Estado atual da entrega

- Execucao oficial em desenvolvimento e producao: Docker.
- Deploy oficial em producao: Render com runtime Docker (`render.yaml`).
- Endpoint tecnico para monitoramento: `GET /health`.
- Pagina amigavel para suporte operacional: `GET /status`.
- Aba Veiculos aceita busca manual de ID fora da listagem atual do dropdown.
- Selecao de linhas persiste entre sessoes do navegador (localStorage).
- Tema claro/escuro com alternancia no topo da interface.
- Preferencia de tema persiste entre sessoes no navegador.
- Camada base do mapa sincroniza automaticamente com o tema ativo.
- Versionamento unificado por build: runtime, cache PWA e chaves de sessao.
- Build atual exibido no topo da interface, ao lado do titulo.
- Reorganizacao estrutural consolidada em `src/`, sem camada legada na raiz.
- **Interface lateral (sidebar)**: painel de controle fixo ao lado esquerdo do mapa.
- **Aba Trajetos**: planejamento de rotas intermodais com visualizacao no mapa.

## Visao geral

Principais capacidades:

- Consulta de veiculos em tempo real.
- Filtro por linhas e por veiculos especificos.
- Renderizacao de itinerarios e pontos de parada a partir de GTFS local.
- Basemaps: OSM, Carto Claro e Carto Escuro.
- Exclusao de pontos fora do municipio e filtragem de veiculos em garagem.
- Cache de camadas estaticas e dinamicas para reduzir custo de processamento.
- Health check tecnico e status amigavel para operacao.
- Suporte opcional a Redis e Sentry.
- **Planejamento de rotas intermodais** com zoom automatico e visualizacao no mapa.
- **Cores GTFS**: linhas de onibus exibidas com as cores oficiais do GTFS (`route_color`).
- **Paradas intermediarias**: marcadores e lista das paradas percorridas por cada trecho.

## Aba Trajetos (Roteamento)

A aba **Trajetos** permite planejar rotas de transporte publico entre dois enderecos do Rio de Janeiro.

### Como usar

1. Acesse a aba **Trajetos** no painel lateral.
2. Informe o endereco de **Origem** e **Destino**.
3. Clique em **Buscar**.
4. Selecione uma das opcoes de itinerario exibidas.
5. O mapa exibe automaticamente o percurso com zoom ajustado.

### Recursos visuais

- **Cores oficiais**: cada trecho de onibus exibe a cor real da linha conforme o GTFS.
- **Paradas no mapa**: circulos marcam cada parada intermediaria do percurso.
- **Paradas no card**: a timeline detalhada lista todas as paradas do trecho ao expandir o card.
- **Marcadores de origem/destino**: ícones verdes (origem) e roxos (destino) no mapa.
- **Trechos a pe**: exibidos com linha tracejada azul.

### Motor de roteamento

As rotas sao calculadas pela API do **[Transitous](https://transitous.org/)** — projeto de codigo aberto que agrega dados de transporte publico de diversas cidades e oferece planejamento de rotas via MOTIS 2.

> **Recurso experimental**: o roteamento depende de servico externo e pode apresentar variacao de disponibilidade.

## Stack

- Python 3.12.x
- Dash + Flask
- Dash Leaflet
- Pandas + GeoPandas
- Gunicorn
- Redis (opcional)
- Docker / Docker Compose

## Estrutura do repositorio

Estrutura atual do projeto:

- `src/core/app_runtime.py`: entrypoint oficial Flask/Dash usado por Gunicorn.
- `src/`: pacote Python oficial (`config`, `core`, `logic`, `state`, `ui`, `utils`).
- `src/logic/transitous_logic.py`: integracao com a API Transitous (geocoding e roteamento).
- `src/logic/gtfs_static_logic.py`: carregamento e cache do GTFS estatico, incluindo cores das linhas.
- `tests/`: suite de testes automatizados.
- `assets/`: CSS e arquivos estaticos web.

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
- Robots: `http://localhost:8080/robots.txt`
- Sitemap: `http://localhost:8080/sitemap.xml`

## SEO tecnico implementado

Melhorias aplicadas para aumentar indexacao e CTR em buscadores:

- Metadados de SEO no HTML base (`description`, `robots`, `canonical`).
- Metadados sociais (`Open Graph` e `Twitter Cards`) com imagem de preview.
- JSON-LD (`WebApplication`) para dados estruturados.
- Canonicalizacao de URL de linha:
  - `/?linha=LECD137` -> redireciona para `/linhas/LECD137` (301).
  - `/linhas/<token>` e a URL canonica.
  - `/veiculos` e `/trajetos` abrem as abas correspondentes.
  - Prefixos de idioma na URL (`/en/`, `/es/`) foram removidos para simplificacao.
  - O idioma e resolvido automaticamente por `Accept-Language` do navegador com fallback para `pt-BR`.
- Endpoints dedicados para crawler:
  - `/robots.txt`
  - `/sitemap.xml`
- Protecao de indexacao de endpoints tecnicos via `X-Robots-Tag: noindex`
  para `/_dash*`, `/health` e `/status`.

## Operacao SEO (deploy e validacao)

### 1) Validar endpoints apos deploy

Execute localmente (ou em CI) para validar respostas esperadas:

```powershell
curl.exe -sS https://riob.us/robots.txt
curl.exe -sS https://riob.us/sitemap.xml
curl.exe -I "https://riob.us/?linha=LECD137"
curl.exe -I "https://riob.us/?linha=LECD137&lang=en"
curl.exe -sS https://riob.us/linhas/LECD137 | findstr /I "canonical og:url"
```

Resultado esperado:

- `/robots.txt` retorna regras de crawler e `Sitemap:`.
- `/sitemap.xml` retorna XML valido com `<urlset>`.
- `/?linha=LECD137` responde `301` para `/linhas/LECD137`.
- `/?linha=LECD137&lang=en` responde `301` para `/en/linhas/LECD137`.
- HTML de `/linhas/LECD137` contem canonical e `og:url` da propria linha.

Atalho: script de smoke test SEO

```powershell
./scripts/seo_smoke.ps1 -BaseUrl http://localhost:8080 -CanonicalBaseUrl https://riob.us -LineToken LECD137
./scripts/seo_smoke.ps1 -BaseUrl https://www.riob.us -CanonicalBaseUrl https://riob.us -LineToken LECD137
```

### 2) Submeter sitemap no Google Search Console

1. Abrir a propriedade `https://riob.us` no Search Console.
2. Ir em `Sitemaps`.
3. Informar `sitemap.xml` e enviar.
4. Confirmar status `Success` e ausencia de erro de fetch.

Observacao: a submissao exige autenticacao da conta proprietaria do dominio.

### 3) URL Inspection e Rich Results Test

URLs recomendadas para inspecao:

- `https://riob.us/`
- `https://riob.us/linhas/LECD137`
- `https://riob.us/en/linhas/LECD137`
- `https://riob.us/es/linhas/LECD137`

Checklist:

- URL canônica reconhecida pelo Google corresponde a URL publicada.
- Pagina esta `Indexable`.
- Metadados (`title`, `description`, `og:*`, `twitter:*`) presentes.
- JSON-LD (`WebApplication`) detectado no Rich Results Test.

## Deploy em producao (Render Docker)

O deploy e feito pelo `render.yaml` com `runtime: docker` e `dockerfilePath: ./Dockerfile`.

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
| `APP_BUILD_ID` | Nao | vazio | ID de build da aplicacao (usa `RENDER_GIT_COMMIT` como fallback) |
| `RENDER_GIT_COMMIT` | Injetada pelo Render | hash de commit | Fallback automatico de versao quando `APP_BUILD_ID` nao e definido |

## Persistencia de sessao e versao

Comportamento atual da UI para reduzir friccao no retorno do usuario:

- O filtro de `Linhas` e persistido no `localStorage` do navegador.
- Ao abrir o app novamente, o filtro e restaurado automaticamente.
- Ao alternar entre as abas `Linhas` e `Veiculos`, a selecao anterior de linhas e preservada.
- Se alguma linha salva nao existir mais nas opcoes atuais, ela e removida de forma segura.
- Nesses casos, o app mostra um aviso curto no banner superior.

Versionamento unificado no frontend:

- `APP_BUILD_ID` (ou fallback `RENDER_GIT_COMMIT`) e a fonte de verdade da versao.
- Esse build_id controla:
  - invalidacao de estado persistido por build;
  - registro/cache do Service Worker (PWA) por build;
  - refresh automatico quando backend e frontend estao em builds diferentes.
- O build atual fica visivel no topo da interface (badge ao lado de `RioB.us`).

Persistencia de tema no frontend:

- O alternador de tema (claro/escuro) fica no topo da interface.
- A preferencia de tema e salva no `localStorage`.
- Na primeira abertura sem preferencia salva, o app segue `prefers-color-scheme` do navegador/sistema.

Sincronizacao de tema com mapa base:

- Tema claro seleciona automaticamente `Carto Claro`.
- Tema escuro seleciona automaticamente `Carto Escuro`.
- O usuario pode trocar manualmente para outra camada base (ex.: `OSM`) a qualquer momento.

## Busca de veiculos fora da listagem

Na aba Veiculos:

- O dropdown continua priorizando veiculos recentes do snapshot.
- Ao digitar um ID nao presente na lista, aparece uma opcao de busca manual.
- Essa opcao pode ser selecionada para filtrar o mapa sem depender da opcao pre-carregada.

Regras de busca manual:

- Busca por valor completo: `A50001`.
- Busca por sufixo numerico: `50001` tambem encontra `A50001`.

## Deep links (navegação e filtros via URL)

Você pode abrir abas ou aplicar filtros diretamente pela URL:

- Aba Linhas com filtro único: `https://riob.us/linhas/LECD137`
- Aba Linhas com filtro múltiplo (CSV): `https://riob.us/linhas/LECD137,LECD138`
- Aba Linhas com filtro via query: `https://riob.us/?linhas=LECD137,LECD138` ou `https://riob.us/?linha=LECD137&linha=LECD138`
- Aba Veículos: `https://riob.us/veiculos`
- Aba Trajeto: `https://riob.us/trajetos`

Comportamento:

- O componente correspondente (Linhas, Veículos ou Trajeto) é ativado automaticamente.
- Para linhas, o filtro correspondente é aplicado no carregamento da página.
- Não há deep link para veículos específicos; `/veiculos` abre a aba genérica.

Idioma nos deep links:

- **Não utilize** prefixos de idioma na URL (`/en/`, `/es/`).
- O app resolve o idioma automaticamente pelo header `Accept-Language`, preferência do navegador ou fallback `pt-BR`.

## Testes

Fluxo recomendado para ambiente Python local (fora de Docker):

```powershell
pip install -r requirements.txt
pip install -e ".[test]"
```

Esse fluxo garante importacao formal do pacote `src` sem manipulacao manual de `sys.path`.

Execute os testes no ambiente local (ou dentro do container de app):

```powershell
pytest
```

Para mudancas no fluxo de UI/filtros, o conjunto minimo recomendado inclui:

- `tests/test_callbacks_ui.py`
- `tests/test_pipeline_smoke.py`

Cobertura estrutural recente de layout:

- Presenca do botao de tema no cabecalho.
- Presenca dos basemaps `Carto Claro` e `Carto Escuro`.
- Ausencia das opcoes antigas `ESRI Padrão` e `ESRI P&B`.

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

## Comportamento com GPS indisponivel

Quando as APIs publicas de GPS estiverem fora do ar (timeouts/503):

- O app continua respondendo normalmente.
- No modo `Linhas`, o shape/itinerario e a legenda da linha selecionada continuam sendo renderizados a partir do GTFS estatico.
- No modo `Veiculos`, a camada dinamica depende de snapshot recente e pode ficar sem pontos durante a indisponibilidade.

## Proximos passos de organizacao

- Validar operacao em producao/staging apos migracao para `src`.
- Manter cobertura de testes e smoke checks (`/health` e `/status`) a cada lote.

## Fluxo de commits recomendados

Antes de publicar:

1. Revisar alteracoes: `git status` e `git diff --name-only`.
2. Revisar historico recente: `git log --oneline -5`.
3. Validar testes impactados.

Para publicar commits locais ja criados:

```powershell
git push origin main
```

## Licenca

Este projeto e licenciado sob os termos da **GNU General Public License v3 (GPL v3)**.

Veja o arquivo [LICENSE](LICENSE) para detalhes completos.

### Termos importantes

- Este software e fornecido "como esta", sem garantias de qualquer tipo.
- Você pode copiar, distribuir e modificar este software livremente.
- Works derivados devem ser licenciados sob GPL v3.
- O codigo fonte esta disponivel neste repositorio.

## Creditos e dependencias externas

| Servico / Projeto | Uso | Licenca / Tipo |
| --- | --- | --- |
| [Transitous](https://transitous.org/) | Motor de roteamento intermodal (MOTIS 2) | Codigo aberto, dados abertos |
| [Data.Rio](https://data.rio/) | Dados GPS e GTFS do sistema de onibus do Rio | API publica |
| [IBGE](https://servicodados.ibge.gov.br/) | Geometria do municipio do Rio de Janeiro | API publica |
| [Dash Leaflet](https://www.dash-leaflet.com/) | Renderizacao do mapa interativo | MIT |
| [OpenStreetMap](https://www.openstreetmap.org/) | Camada base de mapa | ODbL |
| [Carto](https://carto.com/basemaps/) | Camadas base Carto Claro e Carto Escuro | Gratuito para uso publico |

