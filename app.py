import hashlib
import math
import os
import re
import time
import zipfile
import warnings
import threading
import pickle
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import dash
import dash_leaflet as dl
import geopandas as gpd
import pandas as pd
import requests
import redis
import sentry_sdk
from dash import Input, Output, html
from dash.exceptions import CallbackException
from flask import Response, request, redirect
from urllib.parse import quote
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sentry_sdk.integrations.flask import FlaskIntegration
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.ui.callbacks_ui import register_ui_callbacks
from src.ui.callbacks_viewport import register_viewport_callbacks
from src.config.constants import (
    PALETA_CORES, GPS_CONFIG,
    MARKER_LIMITS_BY_ZOOM, LIGHTWEIGHT_MARKER_THRESHOLD, MAX_STOPS_PER_RENDER,
)
from src.utils.geo_helpers import build_point_mask
from src.logic.gps_data_logic import fetch_gps_data_service
from src.utils.gps_processing import (
    processar_dados_gps as _processar_dados_gps,
    calcular_bearing_df,
    atualizar_historico,
    limpar_historico_antigo as _limpar_historico_antigo,
)
from src.logic.interval_logic import compute_poll_interval_ms
from src.logic.gtfs_static_logic import (
    carregar_dados_estaticos_service,
    recarregar_gtfs_estatico_sob_demanda_service,
)
from src.logic.map_data_logic import (
    construir_legenda_linhas,
    construir_legenda_sem_veiculos,
    construir_legenda_veiculos,
    construir_legenda_vazia,
    construir_secao_icones,
    filtrar_por_veiculos,
    linhas_ativas_por_veiculos,
    montar_opcoes_veiculos,
    split_gps_por_tipo,
)
from src.logic.map_layers_logic import (
    construir_camadas_estaticas,
    construir_camadas_veiculos
)
from src.utils.perf_logging import perf_log
from src.utils.svg_icons import (
    cache_or_generate_svg as _cache_or_generate_svg,
    gerar_svg_usuario as _gerar_svg_usuario,
    make_vehicle_icon,
    STOP_SIGN_ICON,
    get_svg_cache_lock as _get_svg_cache_lock,
    get_svg_cache as _get_svg_cache,
)
from src.ui.ui_layout import APP_INDEX_STRING, build_app_layout
from src.logic.viewport_logic import (
    calcular_viewport_linhas as viewport_logic_calcular_viewport_linhas,
    calcular_viewport_veiculos as viewport_logic_calcular_viewport_veiculos,
    resolver_comando_viewport as viewport_logic_resolver_comando_viewport,
    normalize_map_center as viewport_logic_normalize_map_center,
)

BRT_TZ = ZoneInfo("America/Sao_Paulo")
warnings.filterwarnings("ignore")

# ==============================================================================
# Dados estáticos — inicializados vazios, carregados em thread paralela
# ==============================================================================

# Cache GPS server-side — evita trafegar dados pesados para o browser
_gps_lock = threading.Lock()
_gps_cache = pd.DataFrame()   # último fetch processado
_last_update_ts = None  # timestamp da última atualização bem-sucedida
_last_fetch_had_data = True
_status_lock = threading.Lock()  # protege _last_update_ts
_gtfs_data_lock = threading.Lock()  # protege estruturas GTFS compartilhadas

# ==============================================================================
# Sentry & Redis
# ==============================================================================

sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.5
    )

REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL)
        redis_client.ping()
        print("Redis conectado com sucesso!")
    except Exception as e:
        print(f"Aviso: Falha ao conectar no Redis ({e}). Fallback RAM.")
        redis_client = None
else:
    redis_client = None


class RedisDict:
    """Um wrapper simples para Redis."""
    def __init__(self, client, prefix):
        self.client = client
        self.prefix = prefix

    def _key(self, k):
        h = hashlib.sha256(str(k).encode("utf-8")).hexdigest()[:20]
        return f"{self.prefix}:{h}"

    def get(self, k, default=None):
        if not self.client:
            return default
        try:
            v = self.client.get(self._key(k))
            if v:
                return pickle.loads(v)
        except Exception:
            pass
        return default

    def __setitem__(self, k, v):
        if not self.client:
            return
        try:
            self.client.set(self._key(k), pickle.dumps(v))
        except Exception:
            pass

    def pop(self, k, default=None):
        if not self.client:
            return default
        try:
            self.client.delete(self._key(k))
        except Exception:
            pass
        return default

    def clear(self):
        if not self.client:
            return
        try:
            for key in self.client.scan_iter(f"{self.prefix}:*"):
                self.client.delete(key)
        except Exception:
            pass

    def __len__(self):
        # LRU pruning desativado no modo Redis.
        # Deixa o Redis gerenciar com maxmemory/TTL.
        return 0

    def items(self):
        return []


# Se o Redis falhar, caímos em dicionários locais pra não travar o app.
_map_static_cache = (
    RedisDict(redis_client, "map_static") if redis_client else {}
)
_vehicle_layers_cache = (
    RedisDict(redis_client, "map_vehicles") if redis_client else {}
)

# Cache das camadas estáticas (itinerários/paradas) por conjunto de linhas
_map_static_cache_lock = threading.Lock()
_MAP_STATIC_CACHE_MAX_ITEMS = 64
_MAP_STATIC_CACHE_TTL_SECONDS = int(
    os.getenv("MAP_STATIC_CACHE_TTL_SECONDS", "900")
)

# Cache das camadas dinâmicas de veículos por fingerprint do snapshot.
_vehicle_layers_cache_lock = threading.Lock()
_VEHICLE_LAYERS_CACHE_MAX_ITEMS = 96
_VEHICLE_LAYERS_CACHE_TTL_SECONDS = int(
    os.getenv("VEHICLE_LAYERS_CACHE_TTL_SECONDS", "120")
)

_POLL_INTERVAL_IDLE_MS = int(os.getenv("POLL_INTERVAL_IDLE_MS", "90000"))
_POLL_INTERVAL_LINES_ACTIVE_MS = int(
    os.getenv("POLL_INTERVAL_LINES_ACTIVE_MS", "30000")
)
_POLL_INTERVAL_VEHICLES_ACTIVE_MS = int(
    os.getenv("POLL_INTERVAL_VEHICLES_ACTIVE_MS", "20000")
)

_DEV_ASSETS_AUTO_RELOAD = os.getenv("DEV_ASSETS_AUTO_RELOAD", "0") == "1"

# Janela curta de métricas para p95 operacional.
_perf_metrics_lock = threading.Lock()
_perf_metrics = {
    "atualizar_gps_total_ms": deque(maxlen=120),
    "atualizar_mapa_total_ms": deque(maxlen=120),
    "atualizar_mapa_static_ms": deque(maxlen=120),
    "atualizar_mapa_vehicles_ms": deque(maxlen=120),
}
_vehicle_layer_cache_stats = {
    "hit": 0,
    "miss": 0,
}

# Sincronização para carregamento de dados estáticos
_gtfs_load_event = threading.Event()  # Sinaliza quando GTFS foi carregado
_gtfs_load_event.clear()


# ===== OTIMIZAÇÃO: Histórico estruturado por tipo + timestamp =====
_hist_lock = threading.Lock()
# {ordem: {"lat", "lng", "datahora", "bearing", "ts_add"}}
_hist_sppo_bygps = {}
_hist_brt_bygps = {}   # Mesmo para BRT
_HIST_MAX_AGE_SECONDS = 300  # 5 minutos — remove histórico antigo
rio_polygon = None
garagens_polygon = None
_rio_polygon_prepared = None
_garagens_polygon_prepared = None
gtfs = {}
line_to_shape_ids = {}
line_to_stop_ids = {}
line_to_shape_coords = {}  # {linha: [coords_list]}
# {linha: [{lat, lon, stop_name, stop_code, stop_desc, platform_code}]}
line_to_stops_points = {}
line_to_bounds = {}  # {linha: [[min_lat, min_lon], [max_lat, max_lon]]}
linhas_dict = {}
linhas_short = []
lecd_public_map = {}  # {LECDxxx: numero_publico}
# Cache com TTL: {linha: timestamp} — linhas confirmadas sem shape
_linhas_sem_shapes = {}  # dict com timestamp para expirar
_LINHAS_SEM_SHAPES_TTL = 300  # 5 min — refaz tentativa depois


def _build_retry_session():
    """Cria sessão HTTP com retry/backoff e pool de conexões."""
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=0,
        read=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(
        max_retries=retry, pool_connections=8, pool_maxsize=8
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# Sessões persistentes para reduzir overhead de conexão/TLS.
_http_session_sppo = _build_retry_session()
_http_session_brt = _build_retry_session()

# Versao de build para invalidacao de cache do frontend apos deploy.
APP_BUILD_ID = (
    os.getenv("APP_BUILD_ID")
    or os.getenv("RENDER_GIT_COMMIT")
    or "dev"
)


def _perf_record(metric_name, value_ms):
    with _perf_metrics_lock:
        bucket = _perf_metrics.get(metric_name)
        if bucket is not None:
            bucket.append(float(value_ms))


def _perf_p95(metric_name):
    with _perf_metrics_lock:
        bucket = _perf_metrics.get(metric_name)
        if not bucket:
            return 0.0
        series = pd.Series(list(bucket), dtype="float64")
    return float(series.quantile(0.95)) if len(series) > 0 else 0.0


def _empty_shapes_gdf():
    return gpd.GeoDataFrame(
        {"shape_id": [], "geometry": []},
        geometry="geometry",
        crs="EPSG:4326"
    )


def _empty_stops_gdf():
    return gpd.GeoDataFrame(
        {
            "stop_id": [], "stop_name": [],
            "stop_lat": [], "stop_lon": [], "geometry": []
        },
        geometry="geometry",
        crs="EPSG:4326",
    )


def _normalizar_linha(valor):
    """Normaliza identificador de linha para string segura."""
    if valor is None:
        return ""
    return str(valor).strip()


def linha_publica(valor_linha):
    """Retorna o identificador público da linha
    (quando houver mapeamento LECD).
    """
    ln = _normalizar_linha(valor_linha)
    return lecd_public_map.get(ln, ln)


def linha_exibicao(valor_linha):
    """Rótulo de exibição para listagens:
    publico (LECD) quando houver mapeamento.
    """
    ln = _normalizar_linha(valor_linha)
    pub = linha_publica(ln)
    if ln and pub and ln != pub:
        return f"{pub} ({ln})"
    return pub or ln


def _natural_text_key(value):
    """Chave de ordenacao natural (2 antes de 10, sem perder texto)."""
    txt = _normalizar_linha(value)
    if not txt:
        return (1, ())
    parts = re.split(r"(\d+)", txt)
    key = tuple(
        (0, int(p)) if p.isdigit() else (1, p.casefold())
        for p in parts
        if p != ""
    )
    return (0, key)


def linha_sort_key(valor_linha):
    """Ordena pela linha publica quando houver mapeamento LECD."""
    ln = _normalizar_linha(valor_linha)
    publico = linha_publica(ln)
    return (_natural_text_key(publico), _natural_text_key(ln))


def _normalizar_veiculo(valor):
    """Normaliza identificador de veículo para string segura."""
    if valor is None:
        return ""
    return str(valor).strip()


def veiculo_exibicao(ordem, linha=None, tipo=None):
    """Rótulo de exibição para seleção/listagem de veículos."""
    cod = _normalizar_veiculo(ordem)
    ln = _normalizar_linha(linha)
    linha_lbl = linha_exibicao(ln) if ln else "Sem linha"
    prefixo = _normalizar_linha(tipo) or "GPS"
    if cod:
        return f"{cod} · {linha_lbl} · {prefixo}"
    return f"Sem código · {linha_lbl} · {prefixo}"


def _carregar_dicionario_lecd():
    """Carrega mapeamento LECD -> número público para exibição na UI."""
    global lecd_public_map
    try:
        df = pd.read_csv("gtfs/dicionario_lecd.csv", dtype=str)
        if not {"LECD", "servico"}.issubset(df.columns):
            print("AVISO: dicionario_lecd.csv sem colunas esperadas")
            lecd_public_map = {}
            return

        df = df[["LECD", "servico"]].fillna("")
        mapping = {}
        for row in df.itertuples(index=False):
            lecd = _normalizar_linha(row.LECD)
            serv = _normalizar_linha(row.servico)
            if lecd and serv:
                mapping[lecd] = serv

        lecd_public_map = mapping
    except FileNotFoundError:
        msg = (
            "AVISO: gtfs/dicionario_lecd.csv não encontrado; "
            "usando códigos originais"
        )
        print(msg)
        lecd_public_map = {}
    except Exception as e:
        msg = f"ERRO ao carregar dicionário LECD: {type(e).__name__} - {e}"
        print(msg)
        lecd_public_map = {}


# --- routes.txt carregado de forma SÍNCRONA (rápido, só strings) ---
# Isso garante que o dropdown já tem opções quando o app abre.
_carregar_dicionario_lecd()
try:
    with zipfile.ZipFile("gtfs/gtfs.zip") as _z:
        _names = [
            n for n in _z.namelist()
            if n.endswith("routes.txt")
        ]
        if _names:
            with _z.open(_names[0]) as _f:
                _routes_df = pd.read_csv(_f, dtype=str)
            _cols = {"route_short_name", "route_long_name"}
            if _cols.issubset(_routes_df.columns):
                linhas_dict = dict(zip(
                    _routes_df["route_short_name"],
                    _routes_df["route_long_name"]
                ))
                linhas_short = sorted(
                    _routes_df["route_short_name"].dropna().unique().tolist(),
                    key=linha_sort_key,
                )
except FileNotFoundError:
    print("ERRO: Arquivo gtfs/gtfs.zip não encontrado no startup")
except KeyError:
    print("ERRO: Colunas route_short_name ou route_long_name não encontradas")
except Exception as e:
    print(f"ERRO ao carregar routes (síncrono): {type(e).__name__} - {e}")


def _carregar_dados_estaticos():
    global rio_polygon, garagens_polygon, gtfs
    global line_to_shape_ids, line_to_stop_ids
    global line_to_shape_coords, line_to_stops_points, line_to_bounds
    global _rio_polygon_prepared, _garagens_polygon_prepared

    t0 = time.perf_counter()
    try:
        loaded = carregar_dados_estaticos_service(
            empty_shapes_gdf_fn=_empty_shapes_gdf,
            empty_stops_gdf_fn=_empty_stops_gdf,
        )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        print(
            f"ERRO _carregar_dados_estaticos "
            f"({type(exc).__name__}): {exc} "
            f"ms={ms:.1f}"
        )
        _gtfs_load_event.set()
        return

    rio_polygon = loaded["rio_polygon"]
    _rio_polygon_prepared = loaded["rio_polygon_prepared"]
    garagens_polygon = loaded["garagens_polygon"]
    _garagens_polygon_prepared = loaded["garagens_polygon_prepared"]

    with _gtfs_data_lock:
        gtfs = loaded["gtfs"]
        line_to_shape_ids = loaded["line_to_shape_ids"]
        line_to_stop_ids = loaded["line_to_stop_ids"]
        line_to_shape_coords = loaded["line_to_shape_coords"]
        line_to_stops_points = loaded["line_to_stops_points"]
        line_to_bounds = loaded["line_to_bounds"]

    n_shapes = sum(
        len(v) for v in loaded["line_to_shape_coords"].values()
    )
    print(
        f"GTFS background: {len(loaded['line_to_shape_coords'])} "
        f"linhas com shapes ({n_shapes} segmentos)"
    )

    with _map_static_cache_lock:
        _map_static_cache.clear()

    # Sinaliza que o GTFS foi carregado (mesmo que parcialmente)
    _gtfs_load_event.set()
    ms = (time.perf_counter() - t0) * 1000
    perf_log(f"PERF gtfs_static_load total_ms={ms:.1f}")


def _recarregar_gtfs_estatico_sob_demanda(linhas_sel):
    """Recarrega estruturas estaticas do GTFS se faltarem dados de
    shapes/paradas no runtime.

    Este fallback e util em ambientes onde o carregamento em
    background pode falhar no startup.
    """
    linhas_sel = [str(ln) for ln in (linhas_sel or [])]
    if not linhas_sel:
        return

    now = time.time()
    with _gtfs_data_lock:
        # Expira entradas antigas de _linhas_sem_shapes
        expired = [
            ln for ln, ts in _linhas_sem_shapes.items()
            if (now - ts) > _LINHAS_SEM_SHAPES_TTL
        ]
        for ln in expired:
            _linhas_sem_shapes.pop(ln, None)

        missing = [
            ln for ln in linhas_sel
            if (
                ln not in line_to_shape_coords
                and ln not in _linhas_sem_shapes
            )
        ]
    if not missing:
        return

    t0 = time.perf_counter()
    print(
        f"GTFS on-demand: tentando carregar "
        f"{len(missing)} linhas: {missing[:5]}"
    )
    try:
        loaded = recarregar_gtfs_estatico_sob_demanda_service(
            linhas_sel
        )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        print(
            f"ERRO gtfs_reload ({type(exc).__name__}): "
            f"{exc} ms={ms:.1f}"
        )
        perf_log(
            f"OBS gtfs_on_demand status=erro "
            f"lines_req={len(linhas_sel)} lines_missing={len(missing)} "
            f"ms={ms:.1f} err={type(exc).__name__}"
        )
        return
    if not loaded:
        ms = (time.perf_counter() - t0) * 1000
        print(
            f"GTFS on-demand: retorno vazio "
            f"ms={ms:.1f} lines={linhas_sel[:5]}"
        )
        perf_log(
            f"OBS gtfs_on_demand status=vazio "
            f"lines_req={len(linhas_sel)} lines_missing={len(missing)} "
            f"ms={ms:.1f}"
        )
        return

    loaded_shape_coords = loaded.get("line_to_shape_coords", {}) or {}
    loaded_stops_points = loaded.get("line_to_stops_points", {}) or {}
    loaded_shape_lines = sorted(str(k) for k in loaded_shape_coords.keys())
    loaded_stop_lines = sorted(str(k) for k in loaded_stops_points.keys())
    loaded_segments = sum(
        len(v) for v in loaded_shape_coords.values() if isinstance(v, list)
    )

    with _gtfs_data_lock:
        # Mescla DataFrames no dicionário gtfs
        if "gtfs" in loaded and isinstance(loaded["gtfs"], dict):
            gtfs.update(loaded["gtfs"])

        # Mescla dicionários de mapeamento (o ponto crítico)
        line_to_shape_ids.update(loaded.get("line_to_shape_ids", {}))
        line_to_stop_ids.update(loaded.get("line_to_stop_ids", {}))
        line_to_shape_coords.update(loaded.get("line_to_shape_coords", {}))
        line_to_stops_points.update(loaded.get("line_to_stops_points", {}))
        line_to_bounds.update(loaded.get("line_to_bounds", {}))

        # Atualiza cache de linhas sem shapes
        for ln in missing:
            if ln not in line_to_shape_coords:
                _linhas_sem_shapes[ln] = time.time()

        missing_with_shape = [ln for ln in missing if ln in line_to_shape_coords]
        missing_with_stops_only = [
            ln for ln in missing
            if ln in line_to_stops_points and ln not in line_to_shape_coords
        ]
        still_missing_shape = [ln for ln in missing if ln not in line_to_shape_coords]

    with _map_static_cache_lock:
        _map_static_cache.clear()

    _gtfs_load_event.set()
    ms = (time.perf_counter() - t0) * 1000
    perf_log(
        f"OBS gtfs_on_demand status=ok "
        f"lines_req={len(linhas_sel)} lines_missing={len(missing)} "
        f"loaded_shape_lines={len(loaded_shape_lines)} "
        f"loaded_stop_lines={len(loaded_stop_lines)} "
        f"loaded_segments={loaded_segments} "
        f"resolved_with_shape={len(missing_with_shape)} "
        f"resolved_with_stops_only={len(missing_with_stops_only)} "
        f"still_missing_shape={len(still_missing_shape)} "
        f"lines_loaded_sample={loaded_shape_lines[:5]} "
        f"lines_still_missing_sample={still_missing_shape[:5]} "
        f"ms={ms:.1f}"
    )


# Shapes/stops em background — não bloqueia o servidor nem o dropdown
threading.Thread(target=_carregar_dados_estaticos, daemon=True).start()


# ==============================================================================
# Funções auxiliares
# ==============================================================================

def get_linha_cores(linhas_sel):
    """Mapeia cada linha selecionada para uma cor distinta.

    Atribui cores pela posição na seleção atual, garantindo
    que até 10 linhas simultâneas tenham cores sempre
    diferentes entre si.
    """
    cores = {}
    for i, ln in enumerate(linhas_sel or []):
        cores[ln] = PALETA_CORES[i % len(PALETA_CORES)]
    return cores


def _max_markers_for_zoom(zoom):
    """Retorna limite de marcadores por camada com base no zoom."""
    if zoom is None:
        return 400
    for max_zoom, limit in MARKER_LIMITS_BY_ZOOM:
        if zoom <= max_zoom:
            return limit
    return None  # sem limite em zoom alto


def _limit_df_for_render(df, zoom):
    """Reduz volume de pontos em zoom baixo para manter fluidez."""
    if df.empty:
        return df
    limit = _max_markers_for_zoom(zoom)
    if limit is None or len(df) <= limit:
        return df
    step = max(1, math.ceil(len(df) / limit))
    return df.iloc[::step].head(limit)


def _limit_list_for_render(values, limit):
    """Reduz uma lista grande mantendo amostragem uniforme."""
    if values is None:
        return []
    if limit is None or len(values) <= limit:
        return values
    step = max(1, math.ceil(len(values) / limit))
    return values[::step][:limit]


def _build_geojson_cluster_layer(df, layer_id):
    """Cria uma unica camada GeoJSON clusterizada para reduzir
    custo de renderizacao.
    """
    if df is None or df.empty:
        return []

    features = []
    for row in df.itertuples(index=False):
        row_dict = row._asdict()
        linha = str(row_dict.get("linha", ""))
        ordem = str(row_dict.get("ordem", ""))
        tooltip = f"{linha} · {ordem}" if linha or ordem else "Veiculo"
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        float(row_dict["lng"]),
                        float(row_dict["lat"])
                    ],
                },
                "properties": {"tooltip": tooltip},
            }
        )

    return [
        dl.GeoJSON(
            id=layer_id,
            data={"type": "FeatureCollection", "features": features},
            cluster=True,
            zoomToBounds=False
        )
    ]


def _group_vehicle_markers(markers):
    """Agrupa marcadores com cluster (se disponível); fallback para Group."""
    if not markers:
        return []

    cluster_cls = getattr(dl, "MarkerClusterGroup", None)
    if cluster_cls is not None:
        return [cluster_cls(children=markers)]

    # Compatibilidade com dash-leaflet sem MarkerClusterGroup.
    return [dl.LayerGroup(children=markers)]


def _filtrar_pontos_fora_municipio(df):
    """Mantém apenas pontos dentro do município
    (quando polígono estiver disponível).
    """
    if df.empty or rio_polygon is None:
        return df

    try:
        mask = build_point_mask(
            df,
            lon_col="longitude",
            lat_col="latitude",
            polygon=rio_polygon,
            prepared_polygon=_rio_polygon_prepared,
            predicate="covered_by",
        )
        filtrado = df[mask]
        return filtrado
    except Exception as e:
        print(f"ERRO no filtro de município: {type(e).__name__} - {e}")
        return df


def fetch_gps_data(linhas_sel=None, veiculos_sel=None, modo="linhas"):
    """Busca dados GPS das APIs SPPO e BRT e retorna DataFrame unificado."""
    return fetch_gps_data_service(
        linhas_sel=linhas_sel,
        veiculos_sel=veiculos_sel,
        modo=modo,
        http_session_sppo=_http_session_sppo,
        http_session_brt=_http_session_brt,
        processar_dados_gps_fn=_processar_dados_gps,
        gps_config=GPS_CONFIG,
        linhas_short=linhas_short,
        filtrar_pontos_fora_municipio_fn=_filtrar_pontos_fora_municipio,
        garagens_polygon=garagens_polygon,
        garagens_polygon_prepared=_garagens_polygon_prepared,
        build_point_mask_fn=build_point_mask,
    )


# ==============================================================================
# Layout do App
# ==============================================================================

app = dash.Dash(
    __name__,
    title="🚍 RioB.us 🚍",
    meta_tags=[{
        "name": "viewport",
        "content": "width=device-width, initial-scale=1"
    }],
)
server = app.server  # expõe o servidor Flask para deploy (gunicorn)

# Nota: enable_dev_tools(debug=True) com Gunicorn+gevent causa deadlock
# de greenlets nos callbacks. Hot reload de Python é feito pelo --reload do
# Gunicorn; CSS/assets precisam de Ctrl+F5 manual em dev.

# Otimização Enterprise: Compressão de Respostas (Gzip/Brotli)
# para reduzir tráfego JSON/GeoJSON
Compress(server)

# Otimização Enterprise: Rate Limiting para rotas públicas
limiter = Limiter(
    get_remote_address,
    app=server,
    default_limits=["500 per minute"],
    storage_uri="memory://",
)

MAP_SUPPORTS_VIEWPORT = "viewport" in getattr(dl.Map, "_prop_names", [])

app.index_string = APP_INDEX_STRING


@server.after_request
def _disable_cache_for_dash_endpoints(response):
    """Evita cache do layout para reduzir mismatch apos deploy."""
    path = request.path or ""
    if path in ("/", "/_dash-layout", "/_dash-dependencies"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    if _DEV_ASSETS_AUTO_RELOAD and path.startswith("/assets/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@server.errorhandler(CallbackException)
def _handle_callback_exception(exc):
    """Neutraliza requests de frontend antigo sem stacktrace ruidoso."""
    msg = str(exc)
    if "Inputs do not match callback definition" in msg:
        payload = request.get_json(silent=True) or {}
        output = payload.get("output")
        changed = payload.get("changedPropIds")
        inputs = payload.get("inputs") or []
        states = payload.get("state") or []

        log_msg = (
            "AVISO: Callback com Inputs incompatíveis "
            f"(output={output}, changed={changed}, "
            f"inputs={len(inputs)}, states={len(states)})."
        )
        print(log_msg)
        return ("", 204)
    raise exc


@server.route("/health")
def _health_check():
    """Endpoint de health check para monitoramento e deploy."""
    import json as _json

    status = _build_health_status()
    return _json.dumps(status), 200, {"Content-Type": "application/json"}


def _build_health_status():
    """Consolida estado de health para JSON e página amigável."""
    with _status_lock:
        last_ts = _last_update_ts
        fetch_ok = _last_fetch_had_data
    gtfs_loaded = _gtfs_load_event.is_set()
    with _perf_metrics_lock:
        cache_hits = _vehicle_layer_cache_stats.get("hit", 0)
        cache_misses = _vehicle_layer_cache_stats.get("miss", 0)
    with _map_static_cache_lock:
        static_cache_items = len(_map_static_cache)
    with _vehicle_layers_cache_lock:
        vehicle_cache_items = len(_vehicle_layers_cache)
    with _get_svg_cache_lock():
        svg_cache_items = len(_get_svg_cache())

    status = {
        "status": "healthy",
        "gtfs_loaded": gtfs_loaded,
        "last_gps_update": str(last_ts) if last_ts else None,
        "last_fetch_had_data": fetch_ok,
        "cache": {
            "static_layers_items": static_cache_items,
            "vehicle_layers_items": vehicle_cache_items,
            "svg_items": svg_cache_items,
            "vehicle_layers_hit_rate": round(
                cache_hits / max(1, cache_hits + cache_misses) * 100, 1
            ),
        },
        "build_id": APP_BUILD_ID,
    }

    try:
        import psutil
        proc = psutil.Process()
        status["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        pass

    return status


@server.route("/status")
def _status_page():
    """Página de status legível por humanos para suporte operacional."""
    status = _build_health_status()

    gtfs_badge = "OK" if status.get("gtfs_loaded") else "PENDENTE"
    fetch_badge = "OK" if status.get("last_fetch_had_data") else "SEM DADOS"
    mem_text = f"{status.get('memory_mb')} MB" if "memory_mb" in status else "N/D"
    cache = status.get("cache", {})

    html_body = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Status | RioB.us</title>
    <style>
        body {{
            margin: 0;
            font-family: Segoe UI, Arial, sans-serif;
            background: linear-gradient(150deg, #eef3f9, #dce7f5);
            color: #1f2a37;
        }}
        .wrap {{
            max-width: 920px;
            margin: 20px auto;
            padding: 0 12px;
        }}
        .card {{
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid rgba(26, 46, 73, 0.08);
            border-radius: 14px;
            box-shadow: 0 12px 28px rgba(23, 40, 64, 0.08);
            padding: 16px;
        }}
        .head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
        .badge {{
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
            background: #e7f8ec;
            color: #166534;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 10px;
            margin-top: 14px;
        }}
        .item {{
            background: #f7fbff;
            border: 1px solid #d8e4f3;
            border-radius: 10px;
            padding: 10px;
        }}
        .k {{ font-size: 12px; color: #48607b; margin-bottom: 3px; }}
        .v {{ font-size: 15px; font-weight: 700; }}
        .foot {{ margin-top: 12px; font-size: 12px; color: #567; }}
        a {{ color: #0f5cc0; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="wrap">
        <div class="card">
            <div class="head">
                <h1 style="margin:0; font-size: 20px;">Status da aplicacao RioB.us</h1>
                <span class="badge">{status.get('status', 'unknown').upper()}</span>
            </div>
            <div class="grid">
                <div class="item"><div class="k">GTFS carregado</div><div class="v">{gtfs_badge}</div></div>
                <div class="item"><div class="k">Ultima atualizacao GPS</div><div class="v">{status.get('last_gps_update') or 'N/D'}</div></div>
                <div class="item"><div class="k">Ultimo fetch com dados</div><div class="v">{fetch_badge}</div></div>
                <div class="item"><div class="k">Memoria do processo</div><div class="v">{mem_text}</div></div>
                <div class="item"><div class="k">Cache estatico</div><div class="v">{cache.get('static_layers_items', 0)} itens</div></div>
                <div class="item"><div class="k">Cache veiculos</div><div class="v">{cache.get('vehicle_layers_items', 0)} itens</div></div>
                <div class="item"><div class="k">Cache SVG</div><div class="v">{cache.get('svg_items', 0)} itens</div></div>
                <div class="item"><div class="k">Hit rate cache veiculos</div><div class="v">{cache.get('vehicle_layers_hit_rate', 0)}%</div></div>
            </div>
            <div class="foot">
                Build: {status.get('build_id') or 'N/D'} | JSON tecnico: <a href="/health">/health</a>
            </div>
        </div>
    </div>
</body>
</html>
"""
    return Response(html_body, status=200, mimetype="text/html")


@server.route("/veiculos/<vehicle_token>")
def _deep_link_vehicle(vehicle_token):
    """Deep link de veículos desativado: redireciona para home."""
    return redirect("/", code=302)

@server.route("/linhas/<line_token>")
def _deep_link_line(line_token):
    """Converte deep link por caminho para querystring estável no Dash."""
    token = quote(str(line_token or "").strip(), safe="")
    return redirect(f"/?linha={token}", code=302)


app.layout = build_app_layout(
    linhas_short=linhas_short,
    linha_exibicao=linha_exibicao,
    app_build_id=APP_BUILD_ID,
)


# ==============================================================================
# Callbacks
# ==============================================================================


# Forca refresh unico do browser quando o build do backend mudar.
app.clientside_callback(
    """
    function(buildId) {
        if (!buildId) {
            return window.dash_clientside.no_update;
        }
        try {
            var key = "gps_bus_rio_build_id";
            var prev = window.localStorage.getItem(key);
            if (prev === null) {
                window.localStorage.setItem(key, buildId);
                return window.dash_clientside.no_update;
            }
            if (prev !== buildId) {
                window.localStorage.setItem(key, buildId);
                window.location.reload();
            }
        } catch (e) {
            // sem-op: se localStorage estiver indisponivel, segue normalmente.
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("store-build-sync", "data"),
    Input("store-build-id", "data"),
)


def _get_last_update_ts():
    with _status_lock:
        return _last_update_ts


register_ui_callbacks(app, _get_last_update_ts)


@app.callback(
    Output("intervalo", "interval"),
    Input("store-tab-filtro", "data"),
    Input("store-linhas-debounce", "data"),
    Input("store-veiculos-debounce", "data"),
    prevent_initial_call=False,
)
def ajustar_intervalo_polling(tab_filtro, linhas_sel, veiculos_sel):
    with _status_lock:
        fetch_ok = _last_fetch_had_data
    return compute_poll_interval_ms(
        tab_filtro=tab_filtro,
        linhas_sel=linhas_sel,
        veiculos_sel=veiculos_sel,
        last_fetch_had_data=fetch_ok,
        idle_ms=_POLL_INTERVAL_IDLE_MS,
        lines_active_ms=_POLL_INTERVAL_LINES_ACTIVE_MS,
        vehicles_active_ms=_POLL_INTERVAL_VEHICLES_ACTIVE_MS,
    )


@app.callback(
    Output("store-gps-ts", "data"),
    Output("store-hist-sppo", "data"),
    Output("store-hist-brt", "data"),
    Output("store-veiculos-opcoes", "data"),
    Output("store-fetch-error", "data"),
    Input("intervalo", "n_intervals"),
    Input("btn-atualizar", "n_clicks"),
    Input("store-tab-filtro", "data"),
    Input("store-linhas-debounce", "data"),
    Input("store-veiculos-debounce", "data"),
    running=[
        (Output("btn-atualizar", "disabled"), True, False),
        (Output("span-update-icon", "children"), "🔄", ""),
    ],
    prevent_initial_call=False,
)
def atualizar_gps(_n_int, _n_btn, tab_filtro, linhas_sel, veiculos_sel):
    """Busca GPS, armazena no cache server-side e retorna só timestamp."""
    global _gps_cache, _last_update_ts, _last_fetch_had_data
    global _hist_sppo_bygps, _hist_brt_bygps

    modo = "veiculos" if tab_filtro == "veiculos" else "linhas"
    linhas_sel = linhas_sel or []
    veiculos_sel = veiculos_sel or []

    t0 = time.perf_counter()

    # Em modo veículos, carrega snapshot completo para alimentar
    # o dropdown e o filtro no mapa.
    dados = fetch_gps_data(
        linhas_sel=linhas_sel if modo == "linhas" else None,
        veiculos_sel=None,
        modo=modo,
    )

    t_fetch = time.perf_counter()
    opcoes_veiculos = montar_opcoes_veiculos(dados, veiculo_exibicao)

    # Atualiza timestamp a cada fetch bem-sucedido (API respondeu)
    new_ts = datetime.now(BRT_TZ).replace(tzinfo=None)
    with _status_lock:
        _last_update_ts = new_ts
        if len(dados) > 0:
            _last_fetch_had_data = True

    if len(dados) == 0:
        # Sem linhas em modo linhas -> vazio esperado, não é erro de API
        no_filter = (modo == "linhas" and not linhas_sel)
        if not no_filter:
            with _status_lock:
                _last_fetch_had_data = False
        with _hist_lock:
            _limpar_historico_antigo(_hist_sppo_bygps, tipo="SPPO")
            _limpar_historico_antigo(_hist_brt_bygps, tipo="BRT")
        total_ms = (time.perf_counter() - t0) * 1000
        fetch_ms = (t_fetch - t0) * 1000
        _perf_record("atualizar_gps_total_ms", total_ms)
        perf_log(
            f"PERF atualizar_gps modo={modo} total_ms={total_ms:.1f} "
            "n=0"
        )
        error_msg = (
            None if no_filter else "⚠️ Sem dados para alguma das linhas selecionadas"
        )
        return int(time.time() * 1000), {}, {}, [], error_msg

    # Em modo veículos, aplica filtro por seleção após montar opções.
    if modo == "veiculos" and veiculos_sel:
        dados = filtrar_por_veiculos(dados, veiculos_sel)
        if dados.empty:
            return int(time.time() * 1000), {}, {}, opcoes_veiculos, None

    sppo_df, brt_df = split_gps_por_tipo(dados)

    # Calcula bearing apenas se há dados (otimização de CPU)
    if len(sppo_df) > 0:
        with _hist_lock:
            sppo_df = calcular_bearing_df(sppo_df, _hist_sppo_bygps)
            _hist_sppo_bygps = atualizar_historico(_hist_sppo_bygps, sppo_df)
            _limpar_historico_antigo(_hist_sppo_bygps, tipo="SPPO")
    else:
        with _hist_lock:
            _limpar_historico_antigo(_hist_sppo_bygps, tipo="SPPO")

    if len(brt_df) > 0:
        with _hist_lock:
            brt_df = calcular_bearing_df(brt_df, _hist_brt_bygps)
            _hist_brt_bygps = atualizar_historico(_hist_brt_bygps, brt_df)
            _limpar_historico_antigo(_hist_brt_bygps, tipo="BRT")
    else:
        with _hist_lock:
            _limpar_historico_antigo(_hist_brt_bygps, tipo="BRT")

    dados_final = pd.concat([sppo_df, brt_df], ignore_index=True)
    if not dados_final.empty:
        dados_final["datahora"] = dados_final["datahora"].astype(str)

    # Salva server-side — nenhum dado pesado vai para o browser
    with _gps_lock:
        _gps_cache = dados_final if not dados_final.empty else pd.DataFrame()
    total_ms = (time.perf_counter() - t0) * 1000
    fetch_ms = (t_fetch - t0) * 1000
    _perf_record("atualizar_gps_total_ms", total_ms)
    perf_log(
        f"PERF atualizar_gps modo={modo} total_ms={total_ms:.1f} "
        f"fetch_ms={fetch_ms:.1f} "
        f"p95_total={_perf_p95('atualizar_gps_total_ms'):.1f} "
        f"n={len(dados_final)}"
    )
    # Mantemos stores legados vazios para compatibilidade com clientes.
    return int(time.time() * 1000), {}, {}, opcoes_veiculos, None


def _bounds_to_box(bounds):
    if not bounds or not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
        return None
    try:
        sw = bounds[0]
        ne = bounds[1]
        return {
            "min_lat": float(sw[0]),
            "min_lon": float(sw[1]),
            "max_lat": float(ne[0]),
            "max_lon": float(ne[1]),
        }
    except Exception:
        return None


def _filtrar_df_por_viewport(df, bounds):
    if df is None or df.empty:
        return df
    box = _bounds_to_box(bounds)
    if box is None:
        return df
    lat = pd.to_numeric(df["lat"], errors="coerce")
    lng = pd.to_numeric(df["lng"], errors="coerce")
    mask = (
        lat.between(box["min_lat"], box["max_lat"])
        & lng.between(box["min_lon"], box["max_lon"])
    )
    return df[mask]


def _build_layer_group_children(layer_prefix, layers):
    if not layers:
        return []
    layer_token = int(time.time() * 1000)
    return [
        dl.LayerGroup(
            id=f"{layer_prefix}-inner-{layer_token}",
            children=layers,
        )
    ]


def _resolver_contexto_camadas_estaticas(tab_filtro, linhas_sel, veiculos_sel, dados):
    modo = "veiculos" if tab_filtro == "veiculos" else "linhas"
    linhas_sel = linhas_sel or []
    veiculos_sel = veiculos_sel or []

    if modo == "veiculos":
        if dados is None or dados.empty:
            return modo, [], {}
        if not veiculos_sel:
            return modo, [], {}
        dados_filtrados = filtrar_por_veiculos(dados, veiculos_sel).copy()
        if dados_filtrados.empty:
            return modo, [], {}
        linhas_render = linhas_ativas_por_veiculos(
            dados_filtrados, linhas_short
        )
    else:
        if not linhas_sel:
            return modo, [], {}
        linhas_render = [str(ln) for ln in linhas_sel]

    cores = get_linha_cores(linhas_render)
    return modo, linhas_render, cores


@app.callback(
    Output("layer-itinerarios", "children"),
    Output("layer-paradas", "children"),
    Input("store-gps-ts", "data"),
    Input("store-tab-filtro", "data"),
    Input("store-linhas-debounce", "data"),
    Input("store-veiculos-debounce", "data"),
    Input("mapa", "bounds"),
    prevent_initial_call=False,
)
def atualizar_camadas_estaticas(
    _ts, tab_filtro, linhas_sel, veiculos_sel, map_bounds
):
    """Reconstrói apenas camadas estáticas, reagindo ao viewport atual."""
    t0 = time.perf_counter()
    with _gps_lock:
        dados = _gps_cache
    modo, linhas_render, cores = _resolver_contexto_camadas_estaticas(
        tab_filtro,
        linhas_sel,
        veiculos_sel,
        dados,
    )
    if not linhas_render:
        return [], []

    shapes_layers, paradas_layers = construir_camadas_estaticas(
        modo=modo,
        linhas_render=linhas_render,
        cores=cores,
        recarregar_gtfs_estatico_sob_demanda=(
            _recarregar_gtfs_estatico_sob_demanda
        ),
        gtfs_data_lock=_gtfs_data_lock,
        line_to_shape_coords=line_to_shape_coords,
        line_to_stops_points=line_to_stops_points,
        map_static_cache_lock=_map_static_cache_lock,
        map_static_cache=_map_static_cache,
        map_static_cache_max_items=_MAP_STATIC_CACHE_MAX_ITEMS,
        map_static_cache_ttl_seconds=_MAP_STATIC_CACHE_TTL_SECONDS,
        linha_publica_fn=linha_publica,
        stop_sign_icon=STOP_SIGN_ICON,
        limit_list_for_render_fn=_limit_list_for_render,
        max_stops_per_render=MAX_STOPS_PER_RENDER,
        viewport_bounds=map_bounds,
    )
    total_ms = (time.perf_counter() - t0) * 1000
    _perf_record("atualizar_mapa_static_ms", total_ms)
    perf_log(
        f"PERF atualizar_camadas_estaticas modo={modo} total_ms={total_ms:.1f} "
        f"bounds={'on' if map_bounds else 'off'} lines={len(linhas_render)}"
    )
    return (
        _build_layer_group_children("layer-itinerarios", shapes_layers),
        _build_layer_group_children("layer-paradas", paradas_layers),
    )


@app.callback(
    Output("layer-onibus", "children"),
    Output("layer-brt", "children"),
    Output("legenda", "children"),
    Input("store-gps-ts", "data"),
    Input("store-tab-filtro", "data"),
    Input("store-linhas-debounce", "data"),
    Input("store-veiculos-debounce", "data"),
    prevent_initial_call=False,
)
def atualizar_camadas_dinamicas(_ts, tab_filtro, linhas_sel, veiculos_sel):
    """Reconstrói camadas dinâmicas e legenda sem depender do viewport."""
    t0 = time.perf_counter()
    modo = "veiculos" if tab_filtro == "veiculos" else "linhas"
    linhas_sel = linhas_sel or []
    veiculos_sel = veiculos_sel or []
    selected_lines = set(str(ln) for ln in linhas_sel)
    selected_vehicles = set(str(v) for v in veiculos_sel)

    with _gps_lock:
        dados = _gps_cache
    with _status_lock:
        fetch_ok = _last_fetch_had_data

    secao_icones = construir_secao_icones(_cache_or_generate_svg)

    if dados.empty:
        if modo == "linhas":
            linhas_render = [str(ln) for ln in linhas_sel] if linhas_sel else []
            cores = get_linha_cores(linhas_render) if linhas_render else {}
            legenda = construir_legenda_linhas(
                linhas_render=linhas_render,
                cores=cores,
                linhas_dict=linhas_dict,
                linha_exibicao_fn=linha_exibicao,
                secao_icones=secao_icones,
                contagem_por_linha={},
            )
        else:
            legenda = construir_legenda_vazia(
                modo=modo,
                fetch_ok=fetch_ok,
                secao_icones=secao_icones,
            )
        return [], [], legenda

    if modo == "veiculos":
        if not selected_vehicles:
            legenda = construir_legenda_vazia(
                modo=modo,
                fetch_ok=fetch_ok,
                secao_icones=secao_icones,
            )
            return [], [], legenda

        dados_filtrados = dados[
            dados["ordem"].astype(str).isin(selected_vehicles)
        ].copy()
        if dados_filtrados.empty:
            legenda = construir_legenda_sem_veiculos(
                secao_icones,
                mensagem="Veículo não encontrado nos dados recentes",
            )
            return [], [], legenda

        linhas_render = linhas_ativas_por_veiculos(
            dados_filtrados, linhas_short
        )
        cores = get_linha_cores(linhas_render)
        legenda = construir_legenda_veiculos(
            dados_filtrados=dados_filtrados,
            cores=cores,
            linhas_dict=linhas_dict,
            linha_exibicao_fn=linha_exibicao,
            secao_icones=secao_icones,
        )
    else:
        if not linhas_sel:
            legenda = construir_legenda_linhas(
                linhas_render=[],
                cores={},
                linhas_dict=linhas_dict,
                linha_exibicao_fn=linha_exibicao,
                secao_icones=secao_icones,
                contagem_por_linha={},
            )
            return [], [], legenda

        linhas_render = [str(ln) for ln in linhas_sel]
        cores = get_linha_cores(linhas_render)
        dados_filtrados = dados[
            dados["linha"].astype(str).isin(selected_lines)
        ].copy()
        contagem_por_linha = {}
        if "linha" in dados.columns and "ordem" in dados.columns:
            dados_linhas = dados[
                dados["linha"].astype(str).isin(selected_lines)
            ].copy()
            if not dados_linhas.empty:
                contagem_series = (
                    dados_linhas.groupby(dados_linhas["linha"].astype(str))["ordem"]
                    .nunique(dropna=True)
                )
                contagem_por_linha = {
                    str(k): int(v) for k, v in contagem_series.items()
                }
        legenda = construir_legenda_linhas(
            linhas_render=linhas_render,
            cores=cores,
            linhas_dict=linhas_dict,
            linha_exibicao_fn=linha_exibicao,
            secao_icones=secao_icones,
            contagem_por_linha=contagem_por_linha,
        )

    sppo_df, brt_df = split_gps_por_tipo(dados_filtrados)
    t_split = time.perf_counter()

    sppo_df = _limit_df_for_render(sppo_df, 11)
    brt_df = _limit_df_for_render(brt_df, 11)

    camadas_dinamicas = construir_camadas_veiculos(
        sppo_df=sppo_df,
        brt_df=brt_df,
        cores=cores,
        linhas_render=linhas_render,
        lightweight_marker_threshold=LIGHTWEIGHT_MARKER_THRESHOLD,
        build_geojson_cluster_layer_fn=_build_geojson_cluster_layer,
        group_vehicle_markers_fn=_group_vehicle_markers,
        make_vehicle_icon_fn=make_vehicle_icon,
        linha_publica_fn=linha_publica,
        linhas_dict=linhas_dict,
        vehicle_layers_cache_lock=_vehicle_layers_cache_lock,
        vehicle_layers_cache=_vehicle_layers_cache,
        vehicle_layers_cache_max_items=_VEHICLE_LAYERS_CACHE_MAX_ITEMS,
        vehicle_layers_cache_ttl_seconds=_VEHICLE_LAYERS_CACHE_TTL_SECONDS,
        emit_cache_meta=True,
    )
    onibus_children = camadas_dinamicas[0]
    brt_children = camadas_dinamicas[1]
    cache_meta = camadas_dinamicas[2] if len(camadas_dinamicas) > 2 else {}
    total_ms = (time.perf_counter() - t0) * 1000
    split_ms = (t_split - t0) * 1000
    vehicles_ms = (time.perf_counter() - t_split) * 1000
    _perf_record("atualizar_mapa_total_ms", total_ms)
    _perf_record("atualizar_mapa_vehicles_ms", vehicles_ms)

    with _perf_metrics_lock:
        if cache_meta.get("hit"):
            _vehicle_layer_cache_stats["hit"] += 1
        else:
            _vehicle_layer_cache_stats["miss"] += 1
        hits = _vehicle_layer_cache_stats["hit"]
        misses = _vehicle_layer_cache_stats["miss"]
    total_cache_checks = max(1, hits + misses)
    hit_rate = (hits / total_cache_checks) * 100.0

    perf_log(
        f"PERF atualizar_camadas_dinamicas modo={modo} total_ms={total_ms:.1f} "
        f"split_ms={split_ms:.1f} "
        f"vehicles_ms={vehicles_ms:.1f} hit_rate={hit_rate:.1f}%"
    )
    return onibus_children, brt_children, legenda


# ==============================================================================
# Viewport helpers (module scope)
# Mantidos fora de _resolver_comando_viewport para reduzir risco de NameError
# em refactors e facilitar testes/manutenção.
# ==============================================================================


def _get_gps_snapshot_for_viewport():
    with _gps_lock:
        return _gps_cache.copy() if not _gps_cache.empty else pd.DataFrame()


def _calcular_viewport_linhas(linhas_ativas):
    return viewport_logic_calcular_viewport_linhas(
        linhas_sel=linhas_ativas,
        recarregar_gtfs_estatico_sob_demanda=(
            _recarregar_gtfs_estatico_sob_demanda
        ),
        gtfs_load_event=_gtfs_load_event,
        gtfs_data_lock=_gtfs_data_lock,
        line_to_bounds=line_to_bounds,
        line_to_shape_coords=line_to_shape_coords,
        request=request,
    )


def _calcular_viewport_veiculos(veiculos_ativos):
    return viewport_logic_calcular_viewport_veiculos(
        veiculos_sel=veiculos_ativos,
        get_gps_snapshot=_get_gps_snapshot_for_viewport,
        rio_polygon=rio_polygon,
        rio_polygon_prepared=_rio_polygon_prepared,
        build_point_mask=build_point_mask,
        request=request,
    )


def _resolver_comando_viewport(
    data_localizacao, gps_ts, tab_filtro, linhas_sel,
    linhas_sel_debounce, linhas_recenter_token,
    veiculos_sel, veiculos_recenter_token
):
    return viewport_logic_resolver_comando_viewport(
        data_localizacao=data_localizacao,
        gps_ts=gps_ts,
        tab_filtro=tab_filtro,
        linhas_sel=linhas_sel,
        linhas_sel_debounce=linhas_sel_debounce,
        linhas_recenter_token=linhas_recenter_token,
        veiculos_sel=veiculos_sel,
        veiculos_recenter_token=veiculos_recenter_token,
        gerar_svg_usuario=_gerar_svg_usuario,
        calcular_viewport_linhas_fn=_calcular_viewport_linhas,
        calcular_viewport_veiculos_fn=_calcular_viewport_veiculos,
        get_gps_snapshot=_get_gps_snapshot_for_viewport,
        map_supports_viewport=MAP_SUPPORTS_VIEWPORT,
    )


def _normalize_map_center(center_value):
    return viewport_logic_normalize_map_center(center_value)


register_viewport_callbacks(
    app=app,
    map_supports_viewport=MAP_SUPPORTS_VIEWPORT,
    resolver_comando_viewport=_resolver_comando_viewport,
    normalize_map_center=_normalize_map_center,
)


# ==============================================================================
# Ponto de entrada
# ==============================================================================

if __name__ == "__main__":
    if os.getenv("IN_DOCKER") != "1":
        raise RuntimeError(
            "Execucao nativa desativada. Use Docker: 'docker compose up --build'."
        )
    port = int(os.getenv("PORT", "8080"))
    app.run(debug=False, host="0.0.0.0", port=port)
