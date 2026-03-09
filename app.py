import math
import os
import time
from collections import deque
import zipfile
import urllib.parse
import warnings
import threading
from datetime import datetime, timedelta, timezone

import dash
import dash_leaflet as dl
import geopandas as gpd
import pandas as pd
import requests
from dash import Input, Output, html
from dash.exceptions import CallbackException
from flask import request
from callbacks_ui import register_ui_callbacks
from callbacks_viewport import register_viewport_callbacks
from geo_helpers import build_point_mask
from gps_data_logic import fetch_gps_data_service
from interval_logic import compute_poll_interval_ms
from gtfs_static_logic import (
    carregar_dados_estaticos_service,
    recarregar_gtfs_estatico_sob_demanda_service,
)
from map_data_logic import (
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
from map_layers_logic import construir_camadas_estaticas, construir_camadas_veiculos
from perf_logging import perf_log
from ui_layout import APP_INDEX_STRING, build_app_layout
from viewport_logic import (
    calcular_viewport_linhas as viewport_logic_calcular_viewport_linhas,
    calcular_viewport_veiculos as viewport_logic_calcular_viewport_veiculos,
    resolver_comando_viewport as viewport_logic_resolver_comando_viewport,
    normalize_map_center as viewport_logic_normalize_map_center,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

warnings.filterwarnings("ignore")

# ==============================================================================
# Paleta de cores (10 cores com alto contraste)
# ==============================================================================

PALETA_CORES = [
    "#E63946",  # Vermelho
    "#FF00D9",  # Rosa
    "#FFBE0B",  # Amarelo
    "#4A47A3",  # Índigo
    "#3CB44B",  # Verde
    "#118AB2",  # Azul
    "#00BCD4",  # Ciano Elétrico
    "#8338EC",  # Roxo
    "#455A64",  # Cinza Azulado
    "#8B5E34",  # Marrom
]

# ==============================================================================
# Estilos CSS Centralizados
# ==============================================================================

ESTILOS = {
    "header": {
        "padding": "clamp(6px, 1.4vw, 10px) clamp(10px, 2.2vw, 18px)",
        "backgroundColor": "#1f2a37",
        "color": "white",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
        "borderBottom": "1px solid #16202b",
        "boxShadow": "0 1px 4px rgba(0,0,0,.12)",
    },
    "header_titulo": {
        "margin": 0,
        "fontSize": "clamp(14px, 2.4vw, 19px)",
        "fontWeight": "bold",
        "letterSpacing": "0.2px",
        "textAlign": "center",
    },
    "controles": {
        "padding": "8px 14px",
        "backgroundColor": "#f6f8fb",
        "borderBottom": "1px solid #dee2e6",
        "display": "flex",
        "flexDirection": "column",
        "alignItems": "center",
        "gap": "6px",
        "boxShadow": "0 2px 6px rgba(31,42,55,.06)",
    },
    "label": {
        "fontWeight": "bold",
        "marginBottom": "2px",
        "textAlign": "center",
    },
    "dropdown_wrapper": {
        "position": "relative",
        "zIndex": 9999,
    },
    "dropdown": {
        "width": "min(420px, 90vw)",
    },
    "botao_atualizar": {
        "backgroundColor": "#1366d6",
        "color": "white",
        "border": "none",
        "padding": "8px 18px",
        "borderRadius": "6px",
        "cursor": "pointer",
        "fontWeight": "600",
        "boxShadow": "0 1px 4px rgba(19,102,214,.25)",
    },
    "texto_atualizacao": {
        "color": "#6c757d",
        "fontSize": "12px",
        "margin": "0 0 0 10px",
    },
    "caixa_legenda": {
        "background": "rgba(255,255,255,.96)",
        "padding": "7px 10px",
        "borderRadius": "6px",
        "boxShadow": "0 6px 16px rgba(31,42,55,.16)",
        "border": "1px solid #e7ecf3",
        "fontFamily": "'Segoe UI',sans-serif",
        "fontSize": "clamp(9px, 1.1vw, 12px)",
        "lineHeight": "1.4",
        "maxHeight": "38vh",
        "overflowY": "auto",
        "overflowX": "hidden",
    },
    "botao_localizacao": {
        "width": "34px",
        "height": "34px",
        "backgroundColor": "white",
        "border": "1px solid rgba(31,42,55,0.24)",
        "borderRadius": "6px",
        "cursor": "pointer",
        "fontSize": "16px",
        "lineHeight": "1",
        "boxShadow": "0 1px 5px rgba(0,0,0,.15)",
        "padding": "0",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
    },
    "botao_localizacao_container": {
        "position": "absolute",
        "top": "clamp(76px, 12vh, 128px)",
        "left": "10px",
        "zIndex": 1000,
    },
    "legenda_container": {
        "position": "absolute",
        "bottom": "30px",
        "left": "10px",
        "zIndex": 10000,
        "pointerEvents": "auto",
    },
}

# ==============================================================================
# Dados estáticos — inicializados vazios, carregados em thread paralela
# ==============================================================================

# Cache GPS server-side — evita trafegar dados pesados para o browser
_gps_lock  = threading.Lock()
_gps_cache = pd.DataFrame()   # último fetch processado
_last_update_ts = None  # timestamp da última atualização bem-sucedida
_last_fetch_had_data = True
_status_lock = threading.Lock()  # protege _last_update_ts
_gtfs_data_lock = threading.Lock()  # protege estruturas GTFS compartilhadas

# Cache das camadas estáticas (itinerários/paradas) por conjunto de linhas
_map_static_cache_lock = threading.Lock()
_map_static_cache = {}
_MAP_STATIC_CACHE_MAX_ITEMS = 64
_MAP_STATIC_CACHE_TTL_SECONDS = int(os.getenv("MAP_STATIC_CACHE_TTL_SECONDS", "900"))

# Cache das camadas dinâmicas de veículos por fingerprint do snapshot.
_vehicle_layers_cache_lock = threading.Lock()
_vehicle_layers_cache = {}
_VEHICLE_LAYERS_CACHE_MAX_ITEMS = 96
_VEHICLE_LAYERS_CACHE_TTL_SECONDS = int(os.getenv("VEHICLE_LAYERS_CACHE_TTL_SECONDS", "120"))

_POLL_INTERVAL_IDLE_MS = int(os.getenv("POLL_INTERVAL_IDLE_MS", "90000"))
_POLL_INTERVAL_LINES_ACTIVE_MS = int(os.getenv("POLL_INTERVAL_LINES_ACTIVE_MS", "30000"))
_POLL_INTERVAL_VEHICLES_ACTIVE_MS = int(os.getenv("POLL_INTERVAL_VEHICLES_ACTIVE_MS", "20000"))

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

# ===== OTIMIZAÇÃO: Cache de SVGs pré-gerados (evita recalcular toda renderização) =====
_svg_cache = {}  # {(color, bearing_nan): svg_data_uri}
_svg_cache_lock = threading.Lock()

# ===== OTIMIZAÇÃO: Histórico estruturado por tipo + timestamp para limpeza automática =====
_hist_lock = threading.Lock()
_hist_sppo_bygps = {}  # {ordem: {"lat", "lng", "datahora", "bearing", "ts_add"}}
_hist_brt_bygps = {}   # Mesmo para BRT
_HIST_MAX_AGE_SECONDS = 300  # 5 minutos — remove histórico antigo automaticamente
rio_polygon      = None
garagens_polygon = None
_rio_polygon_prepared = None
_garagens_polygon_prepared = None
gtfs             = {}
shapes_gtfs      = None
stops_gtfs       = None
line_to_shape_ids = {}
line_to_stop_ids  = {}
line_to_shape_coords = {}  # {linha: [coords_list]}
line_to_stops_points = {}  # {linha: [{lat, lon, stop_name, stop_code, stop_desc, platform_code}]}
line_to_bounds = {}  # {linha: [[min_lat, min_lon], [max_lat, max_lon]]}
linhas_dict      = {}
linhas_short     = []
linha_cor_fixa   = {}
lecd_public_map  = {}  # {LECDxxx: numero_publico}


def _build_retry_session():
    """Cria sessão HTTP com retry/backoff e pool de conexões."""
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# Sessões persistentes para reduzir overhead de conexão/TLS.
_http_session_sppo = _build_retry_session()
_http_session_brt = _build_retry_session()

# Versao de build para invalidacao de cache do frontend apos deploy.
APP_BUILD_ID = os.getenv("APP_BUILD_ID") or os.getenv("RENDER_GIT_COMMIT") or "dev"

MARKER_LIMITS_BY_ZOOM = [
    (9, 150),
    (10, 250),
    (11, 400),
    (12, 650),
    (13, 900),
    (14, 1300),
]

# Modo leve para interacao: reduz custo de renderizacao quando ha muitos pontos.
LIGHTWEIGHT_MARKER_THRESHOLD = 220
MAX_STOPS_PER_RENDER = 450


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
    return gpd.GeoDataFrame({"shape_id": [], "geometry": []}, geometry="geometry", crs="EPSG:4326")


def _empty_stops_gdf():
    return gpd.GeoDataFrame(
        {"stop_id": [], "stop_name": [], "stop_lat": [], "stop_lon": [], "geometry": []},
        geometry="geometry",
        crs="EPSG:4326",
    )


def _normalizar_linha(valor):
    """Normaliza identificador de linha para string segura."""
    if valor is None:
        return ""
    return str(valor).strip()


def linha_publica(valor_linha):
    """Retorna o identificador público da linha (quando houver mapeamento LECD)."""
    ln = _normalizar_linha(valor_linha)
    return lecd_public_map.get(ln, ln)


def linha_exibicao(valor_linha):
    """Rótulo de exibição para listagens: publico (LECD) quando houver mapeamento."""
    ln = _normalizar_linha(valor_linha)
    pub = linha_publica(ln)
    if ln and pub and ln != pub:
        return f"{pub} ({ln})"
    return pub or ln


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
            print("AVISO: dicionario_lecd.csv sem colunas esperadas (LECD, servico)")
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
        print("AVISO: gtfs/dicionario_lecd.csv não encontrado; usando códigos originais")
        lecd_public_map = {}
    except Exception as e:
        print(f"ERRO ao carregar dicionário LECD: {type(e).__name__} - {e}")
        lecd_public_map = {}


# --- routes.txt carregado de forma SÍNCRONA (rápido, só strings) ----------------
# Isso garante que o dropdown já tem opções quando o app abre.
_carregar_dicionario_lecd()
try:
    with zipfile.ZipFile("gtfs/gtfs.zip") as _z:
        _names = [n for n in _z.namelist() if n.endswith("routes.txt")]
        if _names:
            with _z.open(_names[0]) as _f:
                _routes_df = pd.read_csv(_f, dtype=str)
            if {"route_short_name", "route_long_name"}.issubset(_routes_df.columns):
                linhas_dict  = dict(zip(_routes_df["route_short_name"], _routes_df["route_long_name"]))
                linhas_short = sorted(_routes_df["route_short_name"].dropna().unique().tolist())
                linha_cor_fixa = {
                    ln: PALETA_CORES[i % len(PALETA_CORES)]
                    for i, ln in enumerate(linhas_short)
                }
except FileNotFoundError:
    print("ERRO: Arquivo gtfs/gtfs.zip não encontrado no startup")
except KeyError:
    print("ERRO: Colunas route_short_name ou route_long_name não encontradas")
except Exception as e:
    print(f"ERRO ao carregar routes (síncrono): {type(e).__name__} - {e}")


def _carregar_dados_estaticos():
    global rio_polygon, garagens_polygon, gtfs, shapes_gtfs
    global stops_gtfs, line_to_shape_ids, line_to_stop_ids
    global line_to_shape_coords, line_to_stops_points, line_to_bounds
    global _rio_polygon_prepared, _garagens_polygon_prepared

    t0 = time.perf_counter()
    loaded = carregar_dados_estaticos_service(
        empty_shapes_gdf_fn=_empty_shapes_gdf,
        empty_stops_gdf_fn=_empty_stops_gdf,
    )

    rio_polygon = loaded["rio_polygon"]
    _rio_polygon_prepared = loaded["rio_polygon_prepared"]
    garagens_polygon = loaded["garagens_polygon"]
    _garagens_polygon_prepared = loaded["garagens_polygon_prepared"]

    with _gtfs_data_lock:
        gtfs = loaded["gtfs"]
        shapes_gtfs = loaded["shapes_gtfs"]
        stops_gtfs = loaded["stops_gtfs"]
        line_to_shape_ids = loaded["line_to_shape_ids"]
        line_to_stop_ids = loaded["line_to_stop_ids"]
        line_to_shape_coords = loaded["line_to_shape_coords"]
        line_to_stops_points = loaded["line_to_stops_points"]
        line_to_bounds = loaded["line_to_bounds"]

    with _map_static_cache_lock:
        _map_static_cache.clear()

    # Sinaliza que o GTFS foi carregado (mesmo que parcialmente)
    _gtfs_load_event.set()
    perf_log(f"PERF gtfs_static_load total_ms={(time.perf_counter() - t0) * 1000:.1f}")


def _recarregar_gtfs_estatico_sob_demanda(linhas_sel):
    """Recarrega estruturas estaticas do GTFS se faltarem dados de shapes/paradas no runtime.

    Este fallback e util em ambientes onde o carregamento em background pode falhar no startup.
    """
    global gtfs, line_to_shape_ids, line_to_stop_ids
    global line_to_shape_coords, line_to_stops_points, line_to_bounds

    linhas_sel = [str(ln) for ln in (linhas_sel or [])]
    if not linhas_sel:
        return

    with _gtfs_data_lock:
        missing = [
            ln for ln in linhas_sel
            if ln not in line_to_shape_coords and ln not in line_to_stops_points
        ]
    if not missing:
        return

    loaded = recarregar_gtfs_estatico_sob_demanda_service(linhas_sel)
    if not loaded:
        return

    with _gtfs_data_lock:
        gtfs = loaded["gtfs"]
        line_to_shape_ids = loaded["line_to_shape_ids"]
        line_to_stop_ids = loaded["line_to_stop_ids"]
        line_to_shape_coords = loaded["line_to_shape_coords"]
        line_to_stops_points = loaded["line_to_stops_points"]
        line_to_bounds = loaded["line_to_bounds"]

    with _map_static_cache_lock:
        _map_static_cache.clear()

    _gtfs_load_event.set()


# Shapes/stops em background — não bloqueia o servidor nem o dropdown
threading.Thread(target=_carregar_dados_estaticos, daemon=True).start()


# ==============================================================================
# Funções auxiliares
# ==============================================================================

def get_linha_cores(linhas_sel):
    """Mapeia cada linha selecionada para uma cor fixa (estável)."""
    cores = {}
    for ln in (linhas_sel or []):
        if ln in linha_cor_fixa:
            cores[ln] = linha_cor_fixa[ln]
        else:
            # Fallback estável para linhas fora do routes.txt
            idx = sum(ord(ch) for ch in str(ln)) % len(PALETA_CORES)
            cores[ln] = PALETA_CORES[idx]
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
    """Cria uma unica camada GeoJSON clusterizada para reduzir custo de renderizacao."""
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
                    "coordinates": [float(row_dict["lng"]), float(row_dict["lat"])],
                },
                "properties": {"tooltip": tooltip},
            }
        )

    return [
        dl.GeoJSON(
            id=layer_id,
            data={"type": "FeatureCollection", "features": features},
            cluster=True,
            zoomToBounds=False,
        )
    ]


def _group_vehicle_markers(markers):
    """Agrupa marcadores com cluster quando disponível; fallback para LayerGroup."""
    if not markers:
        return []

    cluster_cls = getattr(dl, "MarkerClusterGroup", None)
    if cluster_cls is not None:
        return [cluster_cls(children=markers)]

    # Compatibilidade com versões do dash-leaflet sem MarkerClusterGroup.
    return [dl.LayerGroup(children=markers)]


def _gerar_svg_seta(color="#888"):
    """Gera SVG de seta e retorna data-URI codificado."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 28 28">'
        f'<polygon points="14,2 24,24 14,18 4,24" fill="{color}" stroke="black" stroke-width="2"/>'
        f"</svg>"
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def _gerar_svg_circulo(color="#888"):
    """Gera SVG de círculo e retorna data-URI codificado."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 28 28">'
        f'<circle cx="14" cy="14" r="10" fill="{color}" stroke="black" stroke-width="2.5"/>'
        f'<circle cx="14" cy="14" r="4" fill="white"/>'
        f"</svg>"
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def _gerar_svg_usuario():
    """Gera SVG de marcador de usuário e retorna data-URI codificado."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">'
        '<circle cx="11" cy="11" r="9" fill="#0d6efd" stroke="white" stroke-width="2.5"/>'
        '<circle cx="11" cy="11" r="3" fill="white"/>'
        '</svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def _gerar_svg_parada():
    """Gera SVG de placa de parada com icone de onibus e retorna data-URI codificado."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 26 26">'
        '<g transform="translate(2,1)">'
        '<rect x="1" y="1" width="20" height="18" rx="3" fill="#1f2a37" stroke="#ffffff" stroke-width="1.4"/>'
        '<rect x="4.2" y="4.5" width="13.6" height="8.2" rx="1.8" fill="#ffffff"/>'
        '<rect x="5.6" y="6" width="4.8" height="3.6" rx="0.8" fill="#9ec5ff"/>'
        '<rect x="11.6" y="6" width="4.8" height="3.6" rx="0.8" fill="#9ec5ff"/>'
        '<rect x="8.7" y="10.1" width="4.6" height="1.8" rx="0.8" fill="#1f2a37"/>'
        '<circle cx="8" cy="13.9" r="1.25" fill="#1f2a37"/>'
        '<circle cx="14" cy="13.9" r="1.25" fill="#1f2a37"/>'
        '<rect x="10.3" y="19" width="1.4" height="4.7" fill="#1f2a37"/>'
        '</g>'
        '</svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)

def _cache_or_generate_svg(color, bearing):
    """Cache de SVG: retorna do cache ou gera e armazena."""
    is_nan = bearing is None or (isinstance(bearing, float) and math.isnan(bearing))
    # Inclui o angulo no cache para nao reutilizar a mesma seta para bearings diferentes.
    if is_nan:
        cache_key = (color, "circle")
    else:
        try:
            bearing_norm = int(round(float(bearing))) % 360
        except Exception:
            bearing_norm = 0
        cache_key = (color, f"arrow-{bearing_norm}")

    with _svg_cache_lock:
        cached = _svg_cache.get(cache_key)
    if cached is not None:
        return cached

    if is_nan:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 28 28">'
            f'<circle cx="14" cy="14" r="10" fill="{color}" stroke="black" stroke-width="2.5"/>'
            f'<circle cx="14" cy="14" r="4" fill="white"/>'
            f"</svg>"
        )
        result = ("data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg), [19, 19], [9, 9])
    else:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">'
            f'<g transform="rotate({bearing_norm}, 14, 14)">'
            f'<polygon points="14,2 24,24 14,18 4,24" fill="{color}" stroke="black" stroke-width="2"/>'
            f"</g></svg>"
        )
        result = ("data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg), [28, 28], [14, 14])

    with _svg_cache_lock:
        _svg_cache[cache_key] = result
    return result


STOP_SIGN_ICON = {
    "iconUrl": _gerar_svg_parada(),
    "iconSize": [26, 26],
    "iconAnchor": [13, 24],
    "popupAnchor": [0, -22],
}


def _limpar_historico_antigo(hist_dict, tipo="SPPO"):
    """Remove veículos do histórico que não foram atualizados há mais de MAX_AGE_SECONDS."""
    agora = time.time()
    ordens_remover = []
    for ordem, dados in hist_dict.items():
        ts_add = dados.get("ts_add", 0)
        if agora - ts_add > _HIST_MAX_AGE_SECONDS:
            ordens_remover.append(ordem)

    for ordem in ordens_remover:
        del hist_dict[ordem]

def make_vehicle_icon(bearing, color="#1a6faf"):
    """Gera ícone SVG direcional como data-URI.
    Sem direção: círculo 19x19 (2/3). Com direção: seta 28x28.
    Retorna (url, [w, h], [ax, ay]).
    """
    return _cache_or_generate_svg(color, bearing)


def haversine(lat1, lon1, lat2, lon2):
    """Distância em metros entre dois pontos geográficos."""
    R  = 6_371_000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_between(lat1, lon1, lat2, lon2):
    """Bearing em graus (0 = Norte, sentido horário)."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x  = math.sin(dl) * math.cos(p2)
    y  = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# Mapeamento de configurações para processamento de dados GPS
GPS_CONFIG = {
    "sppo": {
        "timestamp_col": "datahora",
        "timestamp_divisor": 1000,
        "lat_col": "latitude",
        "lon_col": "longitude",
        "ordem_col": "ordem",
        "linha_col": "linha",
        "velocidade_col": "velocidade",
        "sentido_col": None,
        "tipo": "SPPO",
        "lat_needs_conversion": True,
        "lon_needs_conversion": True,
    },
    "brt": {
        "timestamp_col": "dataHora",
        "timestamp_divisor": 1000,
        "lat_col": "latitude",
        "lon_col": "longitude",
        "ordem_col": "codigo",
        "linha_col": "linha",
        "velocidade_col": "velocidade",
        "sentido_col": "sentido",
        "tipo": "BRT",
        "lat_needs_conversion": False,
        "lon_needs_conversion": False,
    },
}


def _processar_dados_gps(df, config):
    """
    Processa DataFrame GPS de acordo com configuração de mapeamento.
    
    Args:
        df: DataFrame com dados brutos
        config: Dicionário com mapeamento de colunas
    
    Returns:
        DataFrame processado ou vazio se erro
    """
    try:
        if df.empty or config["ordem_col"] not in df.columns:
            return pd.DataFrame()
        
        df = df.copy()
        
        # Processar timestamp
        ts_col = config["timestamp_col"]
        if ts_col in df.columns:
            df[ts_col] = pd.to_datetime(
                df[ts_col].astype(float) / config["timestamp_divisor"],
                unit="s"
            ) - timedelta(hours=3)
        
        # Renomear coluna ordem se necessário
        if config["ordem_col"] != "ordem":
            df = df.rename(columns={config["ordem_col"]: "ordem"})
        
        # Processar coordenadas
        lat_col = config["lat_col"]
        lon_col = config["lon_col"]
        
        if config["lat_needs_conversion"]:
            df[lat_col] = pd.to_numeric(
                df[lat_col].astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            )
        else:
            df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        
        if config["lon_needs_conversion"]:
            df[lon_col] = pd.to_numeric(
                df[lon_col].astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            )
        else:
            df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
        
        # Processar velocidade
        vel_col = config["velocidade_col"]
        if vel_col in df.columns:
            df[vel_col] = pd.to_numeric(df[vel_col], errors="coerce")
        
        # Selecionar colunas finais
        colunas = ["ordem", ts_col, lat_col, lon_col, config["linha_col"], config["velocidade_col"]]
        if config["sentido_col"]:
            colunas.append(config["sentido_col"])
        
        colunas = [c for c in colunas if c in df.columns]
        df = df[colunas].copy()
        
        # Renomear para nomes padrão
        rename_map = {
            ts_col: "datahora",
            lat_col: "latitude",
            lon_col: "longitude",
            config["linha_col"]: "linha",
            config["velocidade_col"]: "velocidade",
        }
        if config["sentido_col"]:
            rename_map[config["sentido_col"]] = "sentido"
        
        df = df.rename(columns=rename_map)
        df["tipo"] = config["tipo"]
        
        if "sentido" not in df.columns:
            df["sentido"] = None
        
        return df
        
    except Exception as e:
        print(f"ERRO processando {config['tipo']}: {e}")
        return pd.DataFrame()


def calcular_bearing_df(df, hist_list, dist_min=20):
    """
    Adiciona coluna 'direcao' ao DataFrame.
    Só atualiza o bearing quando o veículo andou >= dist_min m;
    caso contrário preserva o último bearing registrado.
    """
    df = df.copy()
    df["direcao"] = float("nan")

    if not hist_list:
        return df

    # Aceita histórico no formato novo (dict) e no legado (lista de dicts)
    hist_map = hist_list if isinstance(hist_list, dict) else {r["ordem"]: r for r in hist_list}
    if not hist_map:
        return df

    hist_df = pd.DataFrame.from_dict(hist_map, orient="index")
    if hist_df.empty:
        return df
    if "bearing" not in hist_df.columns:
        hist_df["bearing"] = hist_df.get("ultimo_bearing")
    hist_df["ordem"] = hist_df.index
    hist_df = hist_df.rename(columns={"lat": "lat_prev", "lng": "lng_prev", "datahora": "datahora_prev"})

    # Junta apenas veículos presentes no histórico para reduzir custo de iteração.
    cand = df.reset_index().merge(
        hist_df[["ordem", "lat_prev", "lng_prev", "datahora_prev", "bearing"]],
        on="ordem",
        how="inner",
    )
    if cand.empty:
        return df

    cand["datahora_prev"] = pd.to_datetime(cand["datahora_prev"], errors="coerce")
    cand["datahora"] = pd.to_datetime(cand["datahora"], errors="coerce")
    cand = cand.dropna(subset=["datahora", "datahora_prev", "lat_prev", "lng_prev", "lat", "lng"])
    if cand.empty:
        return df

    time_diff_min = (cand["datahora"] - cand["datahora_prev"]).abs().dt.total_seconds().div(60)
    cand = cand[time_diff_min < 10]
    if cand.empty:
        return df

    for row in cand.itertuples(index=False):
        dist = haversine(row.lat_prev, row.lng_prev, row.lat, row.lng)
        if dist >= dist_min:
            df.at[row.index, "direcao"] = round(
                bearing_between(row.lat_prev, row.lng_prev, row.lat, row.lng), 0
            )
        elif row.bearing is not None and not (isinstance(row.bearing, float) and math.isnan(row.bearing)):
            df.at[row.index, "direcao"] = row.bearing

    return df


def atualizar_historico(hist_dict, df):
    """
    Mantém apenas a posição mais recente por veículo no histórico.
    Formato novo: {ordem: {"lat", "lng", "datahora", "bearing", "ts_add"}}
    """
    ts_now = time.time()
    # itertuples reduz overhead de iterrows em ciclos frequentes.
    for row in df.itertuples(index=False):
        bearing = getattr(row, "direcao", None)
        # Converte NaN para None
        if bearing is not None and isinstance(bearing, float) and math.isnan(bearing):
            bearing = None

        ordem = str(getattr(row, "ordem", "")).strip()
        if not ordem:
            continue

        hist_dict[ordem] = {
            "lat": float(getattr(row, "lat")),
            "lng": float(getattr(row, "lng")),
            "datahora": str(getattr(row, "datahora")),
            "bearing": bearing,
            "ts_add": ts_now,  # Timestamp para limpeza automática
        }

    return hist_dict


def _filtrar_pontos_fora_municipio(df):
    """Mantém apenas pontos dentro do município (quando polígono estiver disponível)."""
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

app    = dash.Dash(
    __name__,
    title="🚍 Consulta de ônibus - Rio de Janeiro 🚍",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # expõe o servidor Flask para deploy (gunicorn)


MAP_SUPPORTS_VIEWPORT = "viewport" in getattr(dl.Map, "_prop_names", [])

app.index_string = APP_INDEX_STRING


@server.after_request
def _disable_cache_for_dash_endpoints(response):
    """Evita cache do layout/dependencies para reduzir mismatch de callbacks apos deploy."""
    path = request.path or ""
    if path in ("/", "/_dash-layout", "/_dash-dependencies"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@server.errorhandler(CallbackException)
def _handle_callback_exception(exc):
    """Neutraliza requests de frontend antigo (layout/dependencies em cache) sem stacktrace ruidoso."""
    msg = str(exc)
    if "Inputs do not match callback definition" in msg:
        payload = request.get_json(silent=True) or {}
        output = payload.get("output")
        outputs = payload.get("outputs")
        changed = payload.get("changedPropIds")
        inputs = payload.get("inputs") or []
        states = payload.get("state") or []

        print(
            "AVISO: Callback com Inputs incompatíveis "
            f"(output={output}, changed={changed}, inputs={len(inputs)}, states={len(states)})."
        )
        return ("", 204)
    raise exc

app.layout = build_app_layout(
    estilos=ESTILOS,
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
    prevent_initial_call=False,
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
    Output("store-gps-ts",    "data"),
    Output("store-hist-sppo", "data"),
    Output("store-hist-brt", "data"),
    Output("store-veiculos-opcoes", "data"),
    Input("intervalo",        "n_intervals"),
    Input("btn-atualizar",    "n_clicks"),
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
    global _gps_cache, _last_update_ts, _last_fetch_had_data, _hist_sppo_bygps, _hist_brt_bygps

    modo = "veiculos" if tab_filtro == "veiculos" else "linhas"
    linhas_sel = linhas_sel or []
    veiculos_sel = veiculos_sel or []

    t0 = time.perf_counter()

    # Em modo veículos, carrega snapshot completo para alimentar o dropdown e o filtro no mapa.
    dados = fetch_gps_data(
        linhas_sel=linhas_sel if modo == "linhas" else None,
        veiculos_sel=None,
        modo=modo,
    )

    t_fetch = time.perf_counter()
    opcoes_veiculos = montar_opcoes_veiculos(dados, veiculo_exibicao)

    # Atualiza timestamp apenas se fetch foi bem-sucedido
    if len(dados) > 0:
        new_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
        with _status_lock:
            _last_update_ts = new_ts
            _last_fetch_had_data = True

    if len(dados) == 0:
        with _gps_lock:
            _gps_cache = pd.DataFrame()
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
            f"fetch_ms={fetch_ms:.1f} p95_total_ms={_perf_p95('atualizar_gps_total_ms'):.1f} n=0"
        )
        return int(time.time()), {}, {}, []

    # Em modo veículos, aplica filtro por seleção após montar opções.
    if modo == "veiculos" and veiculos_sel:
        dados = filtrar_por_veiculos(dados, veiculos_sel)
        if dados.empty:
            with _gps_lock:
                _gps_cache = pd.DataFrame()
            return int(time.time()), {}, {}, opcoes_veiculos

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
        f"fetch_ms={fetch_ms:.1f} p95_total_ms={_perf_p95('atualizar_gps_total_ms'):.1f} n={len(dados_final)}"
    )
    # Mantemos stores legados vazios para compatibilidade com clientes em cache.
    return int(time.time()), {}, {}, opcoes_veiculos


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
        lat.between(box["min_lat"], box["max_lat"]) &
        lng.between(box["min_lon"], box["max_lon"])
    )
    return df[mask]


@app.callback(
    Output("layer-itinerarios", "children"),
    Output("layer-paradas",     "children"),
    Output("layer-onibus",      "children"),
    Output("layer-brt",         "children"),
    Output("legenda",           "children"),
    Input("store-gps-ts",       "data"),
    Input("store-tab-filtro",   "data"),
    Input("store-linhas-debounce", "data"),
    Input("store-veiculos-debounce", "data"),
    Input("mapa", "bounds"),
    prevent_initial_call=False,
)
def atualizar_mapa(_ts, tab_filtro, linhas_sel, veiculos_sel, map_bounds):
    """Reconstrói as camadas do mapa lendo do cache server-side."""
    t0 = time.perf_counter()
    modo = "veiculos" if tab_filtro == "veiculos" else "linhas"
    linhas_sel = linhas_sel or []
    veiculos_sel = veiculos_sel or []
    selected_lines = set(str(ln) for ln in linhas_sel)
    selected_vehicles = set(str(v) for v in veiculos_sel)
    
    # Lê do cache server-side PRIMEIRO
    with _gps_lock:
        dados = _gps_cache
    with _status_lock:
        fetch_ok = _last_fetch_had_data
    

    # --- Legenda --------------------------------------------------------------
    secao_icones = construir_secao_icones(_cache_or_generate_svg)

    if dados.empty:
        legenda = construir_legenda_vazia(
            modo=modo,
            fetch_ok=fetch_ok,
            secao_icones=secao_icones,
            caixa_legenda_style=ESTILOS["caixa_legenda"],
        )
        return [], [], [], [], legenda

    if modo == "veiculos":
        if not selected_vehicles:
            legenda = construir_legenda_sem_veiculos(secao_icones, ESTILOS["caixa_legenda"])
            return [], [], [], [], legenda

        dados_filtrados = dados[dados["ordem"].astype(str).isin(selected_vehicles)].copy()
        dados_filtrados = _filtrar_df_por_viewport(dados_filtrados, map_bounds)
        if dados_filtrados.empty:
            legenda = construir_legenda_sem_veiculos(
                secao_icones,
                ESTILOS["caixa_legenda"],
                mensagem="Nenhum veículo visível no viewport",
            )
            return [], [], [], [], legenda
        linhas_gtfs_ativas = linhas_ativas_por_veiculos(dados_filtrados, linhas_short)
        linhas_render = linhas_gtfs_ativas
        cores = get_linha_cores(linhas_render)

        legenda = construir_legenda_veiculos(
            dados_filtrados=dados_filtrados,
            cores=cores,
            linhas_dict=linhas_dict,
            linha_exibicao_fn=linha_exibicao,
            secao_icones=secao_icones,
            caixa_legenda_style=ESTILOS["caixa_legenda"],
        )
    else:
        if not linhas_sel:
            legenda = html.Div(
                [
                    html.B("Linhas no mapa:", style={"display": "block", "marginBottom": "3px", "fontSize": "clamp(10px, 1.1vw, 13px)"}),
                    html.Span("Nenhuma linha selecionada", style={"color": "#888", "fontStyle": "italic"}),
                    secao_icones,
                ],
                style={**ESTILOS["caixa_legenda"], "minWidth": "clamp(135px, 18vw, 180px)"},
            )
            return [], [], [], [], legenda

        linhas_render = [str(ln) for ln in linhas_sel]
        cores = get_linha_cores(linhas_render)
        legenda = construir_legenda_linhas(
            linhas_render=linhas_render,
            cores=cores,
            linhas_dict=linhas_dict,
            linha_exibicao_fn=linha_exibicao,
            secao_icones=secao_icones,
            caixa_legenda_style=ESTILOS["caixa_legenda"],
        )
        dados_filtrados = dados[dados["linha"].astype(str).isin(selected_lines)].copy()

    sppo_df, brt_df = split_gps_por_tipo(dados_filtrados)
    sppo_df = _filtrar_df_por_viewport(sppo_df, map_bounds)
    brt_df = _filtrar_df_por_viewport(brt_df, map_bounds)
    t_split = time.perf_counter()

    # Reduz marcadores em zoom baixo para evitar travamentos na renderização
    # Sem Input de zoom no callback para evitar incompatibilidade de payload
    # com alguns clientes Dash/dash-leaflet. Usa zoom padrão do mapa (11).
    sppo_df = _limit_df_for_render(sppo_df, 11)
    brt_df = _limit_df_for_render(brt_df, 11)

    shapes_layers, paradas_layers = construir_camadas_estaticas(
        modo=modo,
        linhas_render=linhas_render,
        cores=cores,
        gtfs_load_event=_gtfs_load_event,
        recarregar_gtfs_estatico_sob_demanda=_recarregar_gtfs_estatico_sob_demanda,
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
        viewport_bounds=map_bounds if modo == "veiculos" else None,
    )
    t_static = time.perf_counter()

    onibus_children, brt_children, cache_meta = construir_camadas_veiculos(
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
    total_ms = (time.perf_counter() - t0) * 1000
    split_ms = (t_split - t0) * 1000
    static_ms = (t_static - t_split) * 1000
    vehicles_ms = (time.perf_counter() - t_static) * 1000
    _perf_record("atualizar_mapa_total_ms", total_ms)
    _perf_record("atualizar_mapa_static_ms", static_ms)
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
        f"PERF atualizar_mapa modo={modo} total_ms={total_ms:.1f} "
        f"split_ms={split_ms:.1f} static_ms={static_ms:.1f} vehicles_ms={vehicles_ms:.1f} "
        f"p95_total_ms={_perf_p95('atualizar_mapa_total_ms'):.1f} "
        f"cache_hit={cache_meta.get('hit')} cache_hit_rate={hit_rate:.1f}% "
        f"cache_fp={cache_meta.get('fingerprint_mode')} cache_evictions={int(cache_meta.get('evictions') or 0)}"
    )

    return shapes_layers, paradas_layers, onibus_children, brt_children, legenda


def _calcular_viewport_linhas(linhas_sel):
    return viewport_logic_calcular_viewport_linhas(
        linhas_sel=linhas_sel,
        recarregar_gtfs_estatico_sob_demanda=_recarregar_gtfs_estatico_sob_demanda,
        gtfs_load_event=_gtfs_load_event,
        gtfs_data_lock=_gtfs_data_lock,
        line_to_bounds=line_to_bounds,
        line_to_shape_coords=line_to_shape_coords,
        request=request,
    )


def _calcular_viewport_veiculos(veiculos_sel):
    def _get_gps_snapshot():
        with _gps_lock:
            return _gps_cache.copy() if not _gps_cache.empty else pd.DataFrame()

    return viewport_logic_calcular_viewport_veiculos(
        veiculos_sel=veiculos_sel,
        get_gps_snapshot=_get_gps_snapshot,
        rio_polygon=rio_polygon,
        rio_polygon_prepared=_rio_polygon_prepared,
        build_point_mask=build_point_mask,
        request=request,
    )


def _resolver_comando_viewport(data_localizacao, gps_ts, tab_filtro, linhas_sel, linhas_sel_debounce, veiculos_sel, veiculos_recenter_token):
    def _get_gps_snapshot():
        with _gps_lock:
            return _gps_cache.copy() if not _gps_cache.empty else pd.DataFrame()

    return viewport_logic_resolver_comando_viewport(
        data_localizacao=data_localizacao,
        gps_ts=gps_ts,
        tab_filtro=tab_filtro,
        linhas_sel=linhas_sel,
        linhas_sel_debounce=linhas_sel_debounce,
        veiculos_sel=veiculos_sel,
        veiculos_recenter_token=veiculos_recenter_token,
        gerar_svg_usuario=_gerar_svg_usuario,
        calcular_viewport_linhas_fn=_calcular_viewport_linhas,
        calcular_viewport_veiculos_fn=_calcular_viewport_veiculos,
        get_gps_snapshot=_get_gps_snapshot,
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
    # No Render, a porta deve vir da variável de ambiente PORT.
    port = int(os.getenv("PORT", "8050"))
    app.run(debug=False, host="0.0.0.0", port=port)