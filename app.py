import math
import os
import time
import zipfile
import urllib.parse
import warnings
import threading
from importlib.metadata import version as pkg_version, PackageNotFoundError
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import dash
import dash_leaflet as dl
import geopandas as gpd
import pandas as pd
import requests
from dash import Input, Output, dcc, html
from dash.exceptions import CallbackException
from flask import request
from requests.adapters import HTTPAdapter
from shapely.geometry import LineString, Point, shape as shapely_shape, MultiPolygon
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
        "padding": "10px 18px",
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
        "fontSize": "19px",
        "fontWeight": "bold",
        "letterSpacing": "0.2px",
        "textAlign": "center",
    },
    "controles": {
        "padding": "12px 16px",
        "backgroundColor": "#f6f8fb",
        "borderBottom": "1px solid #dee2e6",
        "display": "flex",
        "flexDirection": "column",
        "alignItems": "center",
        "gap": "10px",
        "boxShadow": "0 2px 6px rgba(31,42,55,.06)",
    },
    "label": {
        "fontWeight": "bold",
        "marginBottom": "4px",
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
        "top": "126px",
        "right": "10px",
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
_status_lock = threading.Lock()  # protege _last_update_ts
_gtfs_data_lock = threading.Lock()  # protege estruturas GTFS compartilhadas

# Cache das camadas estáticas (itinerários/paradas) por conjunto de linhas
_map_static_cache_lock = threading.Lock()
_map_static_cache = {}
_MAP_STATIC_CACHE_MAX_ITEMS = 64

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
gtfs             = {}
shapes_gtfs      = None
stops_gtfs       = None
line_to_shape_ids = {}
line_to_stop_ids  = {}
line_to_shape_coords = {}  # {linha: [coords_list]}
line_to_stops_points = {}  # {linha: [(lat, lon, stop_name)]}
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
print(f"Build ID efetivo: {APP_BUILD_ID}")
print(f"RENDER_GIT_COMMIT detectado: {os.getenv('RENDER_GIT_COMMIT')}")

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
        print(f"Dicionário LECD carregado: {len(lecd_public_map)} mapeamentos")
    except FileNotFoundError:
        print("AVISO: gtfs/dicionario_lecd.csv não encontrado; usando códigos originais")
        lecd_public_map = {}
    except Exception as e:
        print(f"ERRO ao carregar dicionário LECD: {type(e).__name__} - {e}")
        lecd_public_map = {}


# --- routes.txt carregado de forma SÍNCRONA (rápido, só strings) ----------------
# Isso garante que o dropdown já tem opções quando o app abre.
_carregar_dicionario_lecd()
print("Carregando routes (síncrono)...")
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
                print(f"Routes carregadas: {len(linhas_short)} linhas disponíveis no dropdown.")
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

    # --- Limite do Rio de Janeiro (via API IBGE) ------------------------------
    print("Carregando limites do Rio...")
    try:
        _resp = requests.get(
            "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/3304557"
            "?formato=application/vnd.geo%2Bjson",
            timeout=30,
        )
        _resp.raise_for_status()
        _geojson = _resp.json()
        _geometrias = [
            shapely_shape(feat["geometry"])
            for feat in _geojson.get("features", [])
            if feat.get("geometry")
        ]
        if _geometrias:
            rio_polygon = _geometrias[0] if len(_geometrias) == 1 else MultiPolygon(_geometrias)
            print("Limites do Rio carregados via IBGE.")
        else:
            print("AVISO: GeoJSON do IBGE sem geometrias.")
    except requests.RequestException as e:
        print(f"ERRO ao carregar limites do Rio (API): {type(e).__name__} - {e}")
    except Exception as e:
        print(f"ERRO ao carregar limites do Rio: {type(e).__name__} - {e}")

    # --- Garagens -------------------------------------------------------------
    print("Carregando garagens...")
    try:
        garagens_gdf     = gpd.read_file("garagens/Garagens_de_operadores_SPPO.shp")
        garagens_gdf     = garagens_gdf.to_crs("EPSG:4326")
        garagens_polygon = garagens_gdf.geometry.union_all()
        print("Garagens carregadas.")
    except FileNotFoundError:
        print("ERRO: Arquivo Garagens_de_operadores_SPPO.shp não encontrado")
    except Exception as e:
        print(f"ERRO ao carregar garagens: {type(e).__name__} - {e}")

    # --- GTFS otimizado (somente arquivos necessários) ------------------------
    print("Carregando GTFS otimizado...")
    try:
        _gtfs = {}
        _line_to_shape_ids = {}
        _line_to_stop_ids = {}
        _line_to_shape_coords = {}
        _line_to_stops_points = {}
        _line_to_bounds = {}
        with zipfile.ZipFile("gtfs/gtfs.zip") as z:
            _target_files = {
                "routes": {"usecols": ["route_id", "route_short_name"]},
                "trips": {"usecols": ["trip_id", "route_id", "shape_id"]},
                "shapes": {"usecols": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]},
                # stop_name pode não existir em alguns GTFS; manter apenas colunas essenciais.
                "stops": {"usecols": ["stop_id", "stop_lat", "stop_lon"]},
                "stop_times": {"usecols": ["trip_id", "stop_id"]},
            }
            _zip_names = z.namelist()
            for key, opts in _target_files.items():
                names = [n for n in _zip_names if n.endswith(f"{key}.txt")]
                if not names:
                    print(f"  AVISO: {key}.txt não encontrado no GTFS")
                    continue
                try:
                    with z.open(names[0]) as f:
                        _gtfs[key] = pd.read_csv(
                            f,
                            dtype=str,
                            usecols=opts["usecols"],
                            low_memory=False,
                        )
                        print(f"  ✓ {key}: {len(_gtfs[key])} registros")
                except Exception as e:
                    print(f"  ✗ Erro ao ler {key}: {e}")

        _shapes_gtfs = _empty_shapes_gdf()
        _stops_gtfs  = _empty_stops_gdf()

        if "shapes" in _gtfs and not _gtfs["shapes"].empty:
            try:
                df = _gtfs["shapes"].copy()
                df["shape_pt_lat"]      = pd.to_numeric(df["shape_pt_lat"], errors="coerce")
                df["shape_pt_lon"]      = pd.to_numeric(df["shape_pt_lon"], errors="coerce")
                df["shape_pt_sequence"] = pd.to_numeric(df["shape_pt_sequence"], errors="coerce")
                df = df.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
                df = df.sort_values(["shape_id", "shape_pt_sequence"])

                lines = []
                for shape_id, grp in df.groupby("shape_id"):
                    coords = list(zip(grp["shape_pt_lon"], grp["shape_pt_lat"]))
                    # Evita erro de LineString com menos de 2 pontos.
                    if len(coords) < 2:
                        continue
                    lines.append({"shape_id": shape_id, "geometry": LineString(coords)})

                if lines:
                    _shapes_gtfs = gpd.GeoDataFrame(lines, geometry="geometry", crs="EPSG:4326")
                print(f"  Shapes criadas: {len(_shapes_gtfs)} linhas únicas")
            except Exception as e:
                print(f"  ERRO ao processar shapes: {type(e).__name__} - {e}")
        else:
            print(f"  AVISO: shapes.txt não encontrado ou vazio no GTFS")

        if "stops" in _gtfs and not _gtfs["stops"].empty:
            try:
                df = _gtfs["stops"].copy()
                df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
                df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
                df = df.dropna(subset=["stop_lat", "stop_lon"])
                if "stop_name" not in df.columns:
                    df["stop_name"] = ""

                if len(df) > 0:
                    _stops_gtfs = gpd.GeoDataFrame(
                        df,
                        geometry=gpd.points_from_xy(df["stop_lon"], df["stop_lat"]),
                        crs="EPSG:4326",
                    )
                print(f"  Stops criadas: {len(_stops_gtfs)} paradas")
            except Exception as e:
                print(f"  ERRO ao processar stops: {type(e).__name__} - {e}")
        else:
            print(f"  AVISO: stops.txt não encontrado ou vazio no GTFS")

        # Pré-computa índices por linha para reduzir custo no callback do mapa
        if all(k in _gtfs for k in ["routes", "trips"]):
            try:
                rotas = _gtfs["routes"].dropna(subset=["route_id", "route_short_name"])
                trips = _gtfs["trips"].dropna(subset=["trip_id", "route_id"]).merge(
                    rotas, on="route_id", how="inner"
                )

                if "shape_id" in trips.columns:
                    _line_to_shape_ids = (
                        trips.dropna(subset=["shape_id"])
                        .groupby("route_short_name")["shape_id"]
                        .unique()
                        .apply(list)
                        .to_dict()
                    )

                if "stop_times" in _gtfs and not _gtfs["stop_times"].empty:
                    st = _gtfs["stop_times"].dropna(subset=["trip_id", "stop_id"]).merge(
                        trips[["trip_id", "route_short_name"]], on="trip_id", how="inner"
                    )
                    _line_to_stop_ids = (
                        st.groupby("route_short_name")["stop_id"]
                        .unique()
                        .apply(list)
                        .to_dict()
                    )

                print(
                    f"Índices GTFS prontos: {len(_line_to_shape_ids)} linhas com shapes, "
                    f"{len(_line_to_stop_ids)} linhas com paradas"
                )

                # Pré-computa coordenadas de shapes/paradas por linha (lazy render rápido)
                if not _shapes_gtfs.empty and _line_to_shape_ids:
                    shapes_lookup = _shapes_gtfs.set_index("shape_id")
                    for linha_id, shape_ids in _line_to_shape_ids.items():
                        coords_linha = []
                        min_lat = None
                        min_lon = None
                        max_lat = None
                        max_lon = None
                        for shp_id in shape_ids:
                            if shp_id not in shapes_lookup.index:
                                continue
                            try:
                                geom = shapes_lookup.loc[shp_id, "geometry"]
                                if geom is None:
                                    continue
                                coords = [[pt[1], pt[0]] for pt in geom.coords]
                                if len(coords) > 1:
                                    coords_linha.append(coords)
                                    lats = [c[0] for c in coords]
                                    lons = [c[1] for c in coords]
                                    seg_min_lat, seg_max_lat = min(lats), max(lats)
                                    seg_min_lon, seg_max_lon = min(lons), max(lons)
                                    min_lat = seg_min_lat if min_lat is None else min(min_lat, seg_min_lat)
                                    min_lon = seg_min_lon if min_lon is None else min(min_lon, seg_min_lon)
                                    max_lat = seg_max_lat if max_lat is None else max(max_lat, seg_max_lat)
                                    max_lon = seg_max_lon if max_lon is None else max(max_lon, seg_max_lon)
                            except Exception:
                                continue
                        if coords_linha:
                            _line_to_shape_coords[linha_id] = coords_linha
                            if None not in (min_lat, min_lon, max_lat, max_lon):
                                _line_to_bounds[linha_id] = [[min_lat, min_lon], [max_lat, max_lon]]

                if not _stops_gtfs.empty and _line_to_stop_ids:
                    stops_lookup = _stops_gtfs.set_index("stop_id")
                    for linha_id, stop_ids in _line_to_stop_ids.items():
                        pontos_linha = []
                        for stop_id in stop_ids:
                            if stop_id not in stops_lookup.index:
                                continue
                            try:
                                stop_row = stops_lookup.loc[stop_id]
                                stop_name = ""
                                if "stop_name" in stop_row and pd.notna(stop_row["stop_name"]):
                                    stop_name = str(stop_row["stop_name"])
                                pontos_linha.append((
                                    float(stop_row["stop_lat"]),
                                    float(stop_row["stop_lon"]),
                                    stop_name,
                                ))
                            except Exception:
                                continue
                        if pontos_linha:
                            _line_to_stops_points[linha_id] = pontos_linha

                print(
                    f"Pré-cálculo estático pronto: {len(_line_to_shape_coords)} linhas com coords, "
                    f"{len(_line_to_stops_points)} linhas com pontos"
                )
            except Exception as e:
                print(f"ERRO ao montar índices GTFS por linha: {type(e).__name__} - {e}")

        with _gtfs_data_lock:
            gtfs        = _gtfs
            shapes_gtfs = _shapes_gtfs if _shapes_gtfs is not None else _empty_shapes_gdf()
            stops_gtfs  = _stops_gtfs if _stops_gtfs is not None else _empty_stops_gdf()
            line_to_shape_ids = _line_to_shape_ids
            line_to_stop_ids  = _line_to_stop_ids
            line_to_shape_coords = _line_to_shape_coords
            line_to_stops_points = _line_to_stops_points
            line_to_bounds = _line_to_bounds
        with _map_static_cache_lock:
            _map_static_cache.clear()
        print(f"GTFS carregado com arquivos: {list(_gtfs.keys())}")
    except FileNotFoundError:
        print("ERRO: Arquivo gtfs/gtfs.zip não encontrado")
        with _gtfs_data_lock:
            shapes_gtfs = _empty_shapes_gdf()
            stops_gtfs = _empty_stops_gdf()
    except KeyError as e:
        print(f"ERRO ao carregar GTFS (coluna faltante): {e}")
        with _gtfs_data_lock:
            shapes_gtfs = _empty_shapes_gdf()
            stops_gtfs = _empty_stops_gdf()
    except Exception as e:
        print(f"ERRO ao carregar GTFS: {type(e).__name__} - {e}")
        with _gtfs_data_lock:
            shapes_gtfs = _empty_shapes_gdf()
            stops_gtfs = _empty_stops_gdf()

    print("Carregamento inicial concluído.")
    # Sinaliza que o GTFS foi carregado (mesmo que parcialmente)
    _gtfs_load_event.set()


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

    print(f"Fallback GTFS: recarregando estaticos para linhas ausentes: {missing[:8]}")

    try:
        with zipfile.ZipFile("gtfs/gtfs.zip") as z:
            _gtfs = {}
            _target_files = {
                "routes": {"usecols": ["route_id", "route_short_name"]},
                "trips": {"usecols": ["trip_id", "route_id", "shape_id"]},
                "shapes": {"usecols": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]},
                "stops": {"usecols": ["stop_id", "stop_name", "stop_lat", "stop_lon"]},
                "stop_times": {"usecols": ["trip_id", "stop_id"]},
            }
            _zip_names = z.namelist()
            for key, opts in _target_files.items():
                names = [n for n in _zip_names if n.endswith(f"{key}.txt")]
                if not names:
                    continue
                with z.open(names[0]) as f:
                    try:
                        _gtfs[key] = pd.read_csv(
                            f,
                            dtype=str,
                            usecols=opts["usecols"],
                            low_memory=False,
                        )
                    except ValueError:
                        if key == "stops":
                            with z.open(names[0]) as f2:
                                _gtfs[key] = pd.read_csv(
                                    f2,
                                    dtype=str,
                                    usecols=["stop_id", "stop_lat", "stop_lon"],
                                    low_memory=False,
                                )
                            _gtfs[key]["stop_name"] = ""

        if not all(k in _gtfs for k in ["routes", "trips"]):
            print("Fallback GTFS: routes/trips indisponiveis")
            return

        rotas = _gtfs["routes"].dropna(subset=["route_id", "route_short_name"])
        trips = _gtfs["trips"].dropna(subset=["trip_id", "route_id"]).merge(
            rotas, on="route_id", how="inner"
        )

        _line_to_shape_ids = {}
        _line_to_stop_ids = {}
        _line_to_shape_coords = {}
        _line_to_stops_points = {}
        _line_to_bounds = {}

        if "shape_id" in trips.columns:
            _line_to_shape_ids = (
                trips.dropna(subset=["shape_id"])
                .groupby("route_short_name")["shape_id"]
                .unique()
                .apply(list)
                .to_dict()
            )

        shapes_by_id = {}
        shape_bounds_by_id = {}
        if "shapes" in _gtfs and not _gtfs["shapes"].empty:
            df_shapes = _gtfs["shapes"].copy()
            df_shapes["shape_pt_lat"] = pd.to_numeric(df_shapes["shape_pt_lat"], errors="coerce")
            df_shapes["shape_pt_lon"] = pd.to_numeric(df_shapes["shape_pt_lon"], errors="coerce")
            df_shapes["shape_pt_sequence"] = pd.to_numeric(df_shapes["shape_pt_sequence"], errors="coerce")
            df_shapes = df_shapes.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
            df_shapes = df_shapes.sort_values(["shape_id", "shape_pt_sequence"])

            for shape_id, grp in df_shapes.groupby("shape_id"):
                coords = grp[["shape_pt_lat", "shape_pt_lon"]].values.tolist()
                if len(coords) < 2:
                    continue
                shapes_by_id[shape_id] = coords
                lats = [c[0] for c in coords]
                lons = [c[1] for c in coords]
                shape_bounds_by_id[shape_id] = [min(lats), min(lons), max(lats), max(lons)]

        if shapes_by_id and _line_to_shape_ids:
            for linha_id, shape_ids in _line_to_shape_ids.items():
                coords_linha = []
                min_lat = None
                min_lon = None
                max_lat = None
                max_lon = None
                for shp_id in shape_ids:
                    coords = shapes_by_id.get(shp_id)
                    if not coords:
                        continue
                    coords_linha.append(coords)
                    b = shape_bounds_by_id.get(shp_id)
                    if not b:
                        continue
                    min_lat = b[0] if min_lat is None else min(min_lat, b[0])
                    min_lon = b[1] if min_lon is None else min(min_lon, b[1])
                    max_lat = b[2] if max_lat is None else max(max_lat, b[2])
                    max_lon = b[3] if max_lon is None else max(max_lon, b[3])
                if coords_linha:
                    _line_to_shape_coords[linha_id] = coords_linha
                    if None not in (min_lat, min_lon, max_lat, max_lon):
                        _line_to_bounds[linha_id] = [[min_lat, min_lon], [max_lat, max_lon]]

        if "stop_times" in _gtfs and "stops" in _gtfs and not _gtfs["stop_times"].empty:
            st = _gtfs["stop_times"].dropna(subset=["trip_id", "stop_id"]).merge(
                trips[["trip_id", "route_short_name"]], on="trip_id", how="inner"
            )
            _line_to_stop_ids = (
                st.groupby("route_short_name")["stop_id"]
                .unique()
                .apply(list)
                .to_dict()
            )

            stops_df = _gtfs["stops"].copy()
            if "stop_name" not in stops_df.columns:
                stops_df["stop_name"] = ""
            stops_df["stop_lat"] = pd.to_numeric(stops_df["stop_lat"], errors="coerce")
            stops_df["stop_lon"] = pd.to_numeric(stops_df["stop_lon"], errors="coerce")
            stops_df = stops_df.dropna(subset=["stop_lat", "stop_lon", "stop_id"])
            stops_lookup = stops_df.drop_duplicates(subset=["stop_id"]).set_index("stop_id")

            for linha_id, stop_ids in _line_to_stop_ids.items():
                pontos_linha = []
                for stop_id in stop_ids:
                    if stop_id not in stops_lookup.index:
                        continue
                    stop_row = stops_lookup.loc[stop_id]
                    pontos_linha.append((
                        float(stop_row["stop_lat"]),
                        float(stop_row["stop_lon"]),
                        str(stop_row.get("stop_name", "") or ""),
                    ))
                if pontos_linha:
                    _line_to_stops_points[linha_id] = pontos_linha

        with _gtfs_data_lock:
            gtfs = _gtfs
            line_to_shape_ids = _line_to_shape_ids
            line_to_stop_ids = _line_to_stop_ids
            line_to_shape_coords = _line_to_shape_coords
            line_to_stops_points = _line_to_stops_points
            line_to_bounds = _line_to_bounds

        with _map_static_cache_lock:
            _map_static_cache.clear()

        _gtfs_load_event.set()
        print(
            f"Fallback GTFS pronto: {len(_line_to_shape_coords)} linhas com itinerarios, "
            f"{len(_line_to_stops_points)} linhas com paradas"
        )
    except Exception as e:
        print(f"ERRO no fallback GTFS: {type(e).__name__} - {e}")


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

    if ordens_remover:
        print(f"[{tipo}] Removidas {len(ordens_remover)} posições antigas do histórico")


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
        
        print(f"{config['tipo']} processado: {len(df)} registros")
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
    # Iterar apenas sobre linhas do dataframe (mais eficiente)
    for _, row in df.iterrows():
        bearing = row.get("direcao")
        # Converte NaN para None
        if bearing is not None and isinstance(bearing, float) and math.isnan(bearing):
            bearing = None

        hist_dict[row["ordem"]] = {
            "lat": float(row["lat"]),
            "lng": float(row["lng"]),
            "datahora": str(row["datahora"]),
            "bearing": bearing,
            "ts_add": time.time(),  # Timestamp para limpeza automática
        }

    return hist_dict


def fetch_gps_data(linhas_sel=None):
    """Busca dados GPS das APIs SPPO e BRT e retorna DataFrame unificado."""
    # OTIMIZAÇÃO: Sem linhas selecionadas, não busca dados remotos.
    if not linhas_sel:
        return pd.DataFrame()

    # Usar UTC-3 (BRT) explicitamente para compatibilidade local e no Render
    agora  = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
    inicio = agora - timedelta(minutes=3)
    fmt    = "%Y-%m-%d+%H:%M:%S"

    selected_lines = set(str(ln) for ln in (linhas_sel or []))
    sppo_df = pd.DataFrame()
    brt_df  = pd.DataFrame()

    # Sessão compartilhada com headers para simular browser
    _headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.data.rio/",
    }

    def _fetch_sppo():
        url_sppo = (
            f"https://dados.mobilidade.rio/gps/sppo"
            f"?dataInicial={inicio.strftime(fmt)}&dataFinal={agora.strftime(fmt)}"
        )
        try:
            resp = _http_session_sppo.get(url_sppo, headers=_headers, timeout=20)
            print(f"SPPO status: {resp.status_code} | Content-Type: {resp.headers.get('Content-Type','')}")
            if resp.status_code != 200:
                return pd.DataFrame()
            data = resp.json()
            if not isinstance(data, list) or not data:
                return pd.DataFrame()
            if selected_lines:
                data = [r for r in data if str(r.get("linha", "")) in selected_lines]
            print(f"SPPO: {len(data)} registros brutos")
            return pd.DataFrame(data) if data else pd.DataFrame()
        except requests.Timeout:
            print("ERRO API SPPO: Timeout na requisição")
        except requests.RequestException as e:
            print(f"ERRO API SPPO: {type(e).__name__} - {e}")
        except ValueError:
            print("SPPO body nao e JSON valido")
        except Exception as e:
            print(f"ERRO inesperado SPPO: {type(e).__name__} - {e}")
        return pd.DataFrame()

    def _fetch_brt():
        try:
            resp = _http_session_brt.get("https://dados.mobilidade.rio/gps/brt", headers=_headers, timeout=20)
            if resp.status_code != 200:
                return pd.DataFrame()
            veiculos = resp.json().get("veiculos") or []
            if selected_lines:
                veiculos = [r for r in veiculos if str(r.get("linha", "")) in selected_lines]
            print(f"BRT: {len(veiculos)} registros brutos")
            return pd.DataFrame(veiculos) if veiculos else pd.DataFrame()
        except requests.Timeout:
            print("ERRO API BRT: Timeout na requisição")
        except requests.RequestException as e:
            print(f"ERRO API BRT: {type(e).__name__} - {e}")
        except Exception as e:
            print(f"ERRO inesperado BRT: {type(e).__name__} - {e}")
        return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_sppo = ex.submit(_fetch_sppo)
        fut_brt = ex.submit(_fetch_brt)
        sppo_df = fut_sppo.result()
        brt_df = fut_brt.result()

    # Processar SPPO
    if len(sppo_df) > 0:
        sppo_df = _processar_dados_gps(sppo_df, GPS_CONFIG["sppo"])
    else:
        sppo_df = pd.DataFrame()

    # Processar BRT
    if len(brt_df) > 0:
        brt_df = _processar_dados_gps(brt_df, GPS_CONFIG["brt"])
    else:
        brt_df = pd.DataFrame()

    # Combinar e filtrar
    dados = pd.concat([sppo_df, brt_df], ignore_index=True)
    if len(dados) == 0:
        return pd.DataFrame()

    dados = dados.dropna(subset=["latitude", "longitude"])
    dados = dados.sort_values("datahora", ascending=False).drop_duplicates("ordem")
    dados = dados[dados["datahora"] >= inicio]

    # Mantém apenas veículos de linhas presentes no GTFS
    if linhas_short:
        antes = len(dados)
        dados = dados[dados["linha"].isin(linhas_short)]
        print(f"Filtro GTFS: {antes} → {len(dados)} registros")

    # Filtro final por linhas selecionadas (garantia)
    if selected_lines:
        antes = len(dados)
        dados = dados[dados["linha"].astype(str).isin(selected_lines)]
        print(f"Filtro seleção: {antes} → {len(dados)} registros")

    # Remove pontos dentro de garagens (veículos possivelmente recolhidos).
    if len(dados) > 0 and garagens_polygon is not None:
        try:
            antes = len(dados)
            dentro_garagem = dados.apply(
                lambda row: garagens_polygon.contains(Point(float(row["longitude"]), float(row["latitude"]))),
                axis=1,
            )
            dados = dados[~dentro_garagem]
            removidos = antes - len(dados)
            if removidos > 0:
                print(f"Filtro garagens: removidos {removidos} registros dentro de garagem")
        except Exception as e:
            print(f"ERRO no filtro de garagens: {type(e).__name__} - {e}")

    # Conversão rápida de coordenadas (sem geometria custosa)
    dados["linha"] = dados["linha"].astype(str)
    dados["lat"] = dados["latitude"].astype(float)
    dados["lng"] = dados["longitude"].astype(float)
    dados = dados.reset_index(drop=True)
    # Manter apenas colunas necessárias para reduzir tamanho do store
    colunas_uteis = ["ordem", "lat", "lng", "linha", "velocidade", "tipo", "sentido", "datahora"]
    colunas_uteis = [c for c in colunas_uteis if c in dados.columns]
    dados = dados[colunas_uteis]
    print(f"Total após filtros: {len(dados)} registros")
    return dados


# ==============================================================================
# Layout do App
# ==============================================================================

app    = dash.Dash(
    __name__,
    title="🚍 Consulta de ônibus - Rio de Janeiro 🚍",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # expõe o servidor Flask para deploy (gunicorn)


def _safe_pkg_version(pkg_name):
    try:
        return pkg_version(pkg_name)
    except PackageNotFoundError:
        return "not-installed"
    except Exception:
        return "unknown"


print(f"Dash version: {_safe_pkg_version('dash')} | runtime: {getattr(dash, '__version__', 'unknown')}")
print(f"dash-leaflet version: {_safe_pkg_version('dash-leaflet')}")
MAP_SUPPORTS_VIEWPORT = "viewport" in getattr(dl.Map, "_prop_names", [])
print(f"dash-leaflet suporte a 'viewport': {MAP_SUPPORTS_VIEWPORT}")

# CSS global para evitar scroll vertical residual no mobile.
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            html, body, #react-entry-point {
                height: 100%;
                margin: 0;
                padding: 0;
                overflow: hidden;
            }

            body {
                background: linear-gradient(165deg, #eef2f7 0%, #dfe8f5 100%);
            }

            #boot-loader {
                position: fixed;
                inset: 0;
                z-index: 99999;
                display: flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(165deg, #eef2f7 0%, #dfe8f5 100%);
                transition: opacity .35s ease, visibility .35s ease;
            }

            #boot-loader.hide {
                opacity: 0;
                visibility: hidden;
                pointer-events: none;
            }

            .boot-card {
                min-width: 250px;
                padding: 16px 20px;
                border-radius: 12px;
                background: rgba(255,255,255,.92);
                border: 1px solid #d5dfeb;
                box-shadow: 0 10px 30px rgba(31,42,55,.14);
                text-align: center;
                font-family: 'Segoe UI', sans-serif;
                color: #1f2a37;
            }

            .boot-title {
                margin: 0 0 10px 0;
                font-size: 15px;
                font-weight: 700;
            }

            .boot-subtitle {
                margin: 8px 0 0 0;
                font-size: 12px;
                color: #4b5a6b;
            }

            .boot-spinner {
                width: 34px;
                height: 34px;
                margin: 0 auto;
                border-radius: 50%;
                border: 3px solid #c8d8ef;
                border-top-color: #1366d6;
                animation: spin .9s linear infinite;
            }

            @keyframes spin {
                to { transform: rotate(360deg); }
            }

            /* Remove contorno de foco visual ao clicar em elementos do mapa. */
            .leaflet-container:focus {
                outline: none !important;
            }

            .itinerario-polyline:focus,
            .itinerario-polyline:active {
                outline: none !important;
                box-shadow: none !important;
            }
        </style>
    </head>
    <body>
        <div id="boot-loader" aria-live="polite" aria-label="Carregando aplicação">
            <div class="boot-card">
                <p class="boot-title">Consulta de ônibus - Rio de Janeiro</p>
                <div class="boot-spinner"></div>
                <p class="boot-subtitle">Carregando mapa e dados...</p>
            </div>
        </div>
        {%app_entry%}
        <script>
            (function () {
                function hideLoader() {
                    var el = document.getElementById('boot-loader');
                    if (!el) return;
                    el.classList.add('hide');
                    setTimeout(function () {
                        if (el && el.parentNode) el.parentNode.removeChild(el);
                    }, 450);
                }

                function appMounted() {
                    var root = document.getElementById('react-entry-point');
                    if (!root) return false;
                    return root.children && root.children.length > 0;
                }

                var tries = 0;
                var timer = setInterval(function () {
                    tries += 1;
                    if (appMounted()) {
                        clearInterval(timer);
                        hideLoader();
                        return;
                    }
                    if (tries > 240) {
                        clearInterval(timer);
                        hideLoader();
                    }
                }, 50);

                window.addEventListener('load', function () {
                    setTimeout(hideLoader, 600);
                });
            })();
        </script>
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


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

        # Loga um resumo compacto para identificar qual callback/cliente causou mismatch.
        try:
            input_ids = [f"{item.get('id')}.{item.get('property')}" for item in inputs if isinstance(item, dict)]
            state_ids = [f"{item.get('id')}.{item.get('property')}" for item in states if isinstance(item, dict)]
        except Exception:
            input_ids = []
            state_ids = []

        print("AVISO: Callback com Inputs incompatíveis (provável frontend desatualizado).")
        print(f"  output={output} | outputs={outputs}")
        print(f"  changedPropIds={changed}")
        print(f"  inputs({len(input_ids)}): {input_ids[:12]}")
        print(f"  state({len(state_ids)}): {state_ids[:12]}")
        return ("", 204)
    raise exc

app.layout = html.Div(
    [
        dcc.Interval(id="intervalo",        interval=45_000, n_intervals=0),
        dcc.Interval(id="intervalo-linhas-debounce", interval=500, n_intervals=0, disabled=True),

        # Compatibilidade com clientes antigos que ainda chamam callback legado.
        dcc.Store(id="store-hist-sppo", data={}),
        dcc.Store(id="store-hist-brt", data={}),
        dcc.Store(id="store-build-id", data=APP_BUILD_ID),
        dcc.Store(id="store-build-sync", data=None),
        dcc.Store(id="store-linhas-debounce", data=[]),
        dcc.Store(id="store-gps-ts",    data=0),
        dcc.Store(id="store-localizacao", data=None),

        # Cabeçalho
        html.Div(
            html.H4("🚍 Consulta de ônibus - Rio de Janeiro 🚍", style=ESTILOS["header_titulo"]),
            style=ESTILOS["header"],
        ),

        # Controles
        html.Div(
            [
                # Seleção de linha — wrapper com z-index alto para o menu ficar sobre os botões do mapa
                html.Div(
                    [
                        html.Label("Linhas:", style=ESTILOS["label"]),
                        html.Div(
                            dcc.Dropdown(
                                id="dropdown-linhas",
                                options=[{"label": linha_exibicao(ln), "value": ln} for ln in linhas_short],
                                multi=True,
                                placeholder="Selecione uma ou mais linhas...",
                                style=ESTILOS["dropdown"],
                            ),
                            style=ESTILOS["dropdown_wrapper"],
                        ),
                    ],
                    style={"display": "flex", "flexDirection": "column", "alignItems": "center"},
                ),
                # Botão + texto — centralizados e agrupados
                html.Div(
                    [
                        html.Button(
                            "Atualizar 🔄️",
                            id="btn-atualizar",
                            n_clicks=0,
                            style=ESTILOS["botao_atualizar"],
                        ),
                        html.P(
                            "Última atualização:",
                            style=ESTILOS["texto_atualizacao"],
                        ),
                        html.Span(
                            id="span-update-icon",
                            style={"marginLeft": "8px", "fontSize": "14px"},
                            children="",
                        ),
                        html.Span(
                            id="span-update-time",
                            style={"marginLeft": "12px", "fontSize": "12px", "color": "#6c757d"},
                            children="",
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center", "justifyContent": "center",
                           "flexWrap": "wrap", "gap": "6px"},
                ),
            ],
            style=ESTILOS["controles"],
        ),

        # Mapa + legenda flutuante
        html.Div(
            [
                dl.Map(
                    id="mapa",
                    center=[-22.9, -43.2],
                    zoom=11,
                    style={"height": "100%", "width": "100%"},
                    children=[
                        dl.LayersControl(
                            [
                                dl.BaseLayer(
                                    dl.TileLayer(
                                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                        attribution="© OpenStreetMap contributors",
                                    ),
                                    name="OSM", checked=False,
                                ),
                                dl.BaseLayer(
                                    dl.TileLayer(
                                        url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                                        attribution="Esri",
                                    ),
                                    name="ESRI Padrão", checked=True,
                                ),
                                dl.BaseLayer(
                                    dl.TileLayer(
                                        url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                                        attribution="Esri",
                                    ),
                                    name="ESRI P&B", checked=False,
                                ),
                                dl.Overlay(dl.LayerGroup(id="layer-itinerarios"),
                                           name="Itinerários", checked=True),
                                dl.Overlay(dl.LayerGroup(id="layer-paradas"),
                                           name="Paradas", checked=False),
                                dl.Overlay(dl.LayerGroup(id="layer-onibus"),
                                           name="Ônibus", checked=True),
                                dl.Overlay(dl.LayerGroup(id="layer-brt"),
                                           name="BRT", checked=True),
                                dl.Overlay(dl.LayerGroup(id="layer-localizacao"),
                                           name="Minha posição", checked=True),
                            ],
                            position="topright",
                        ),
                    ],
                ),
                # Botão de localização — posicionado abaixo do controle de camadas
                html.Div(
                    html.Button(
                        "📍",
                        id="btn-localizar",
                        n_clicks=0,
                        title="Ir para minha localização",
                        style=ESTILOS["botao_localizacao"],
                    ),
                    style=ESTILOS["botao_localizacao_container"],
                ),
                html.Div(
                    id="legenda",
                    style=ESTILOS["legenda_container"],
                ),
            ],
            style={"position": "relative", "flex": "1 1 auto", "minHeight": 0},
        ),
    ],
    style={
        "fontFamily": "'Segoe UI', 'Helvetica Neue', sans-serif",
        "boxSizing": "border-box",
        "display": "flex",
        "flexDirection": "column",
        "height": "100dvh",
        "overflow": "hidden",
        "maxWidth": "100vw",
        "background": "#eef2f7",
    },
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




@app.callback(
    Output("store-linhas-debounce", "data"),
    Output("intervalo-linhas-debounce", "disabled"),
    Input("dropdown-linhas", "value"),
    Input("intervalo-linhas-debounce", "n_intervals"),
    prevent_initial_call=True,
)
def sincronizar_linhas_com_debounce(linhas_sel, _n_intervals):
    """Sincroniza seleção de linhas com debounce de 500ms."""
    trigger = dash.callback_context.triggered[0]["prop_id"].split(".")[0] if dash.callback_context.triggered else None
    print(f"Debounce linhas: trigger={trigger}, linhas={linhas_sel}, n_intervals={_n_intervals}")
    if trigger == "dropdown-linhas":
        return dash.no_update, False
    if trigger == "intervalo-linhas-debounce":
        return linhas_sel or [], True
    return dash.no_update, dash.no_update


@app.callback(
    Output("store-gps-ts",    "data"),
    Output("store-hist-sppo", "data"),
    Output("store-hist-brt", "data"),
    Input("intervalo",        "n_intervals"),
    Input("btn-atualizar",    "n_clicks"),
    Input("store-linhas-debounce", "data"),
    running=[
        (Output("btn-atualizar", "disabled"), True, False),
        (Output("span-update-icon", "children"), "🔄", ""),
    ],
    prevent_initial_call=False,
)
def atualizar_gps(_n_int, _n_btn, linhas_sel):
    """Busca GPS, armazena no cache server-side e retorna só timestamp."""
    global _gps_cache, _last_update_ts, _hist_sppo_bygps, _hist_brt_bygps

    # OTIMIZAÇÃO: Passa linhas para fetch — se vazio, não gasta banda da API
    dados = fetch_gps_data(linhas_sel=linhas_sel or [])
    
    # Atualiza timestamp apenas se fetch foi bem-sucedido
    if len(dados) > 0:
        new_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
        with _status_lock:
            _last_update_ts = new_ts
    
    if len(dados) == 0:
        with _hist_lock:
            _limpar_historico_antigo(_hist_sppo_bygps, tipo="SPPO")
            _limpar_historico_antigo(_hist_brt_bygps, tipo="BRT")
        return dash.no_update, {}, {}

    sppo_df = dados[dados["tipo"] == "SPPO"].copy()
    brt_df  = dados[dados["tipo"] == "BRT"].copy()

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

    dados_final             = pd.concat([sppo_df, brt_df], ignore_index=True)
    if not dados_final.empty:
        dados_final["datahora"] = dados_final["datahora"].astype(str)

    # Salva server-side — nenhum dado pesado vai para o browser
    with _gps_lock:
        _gps_cache = dados_final if not dados_final.empty else pd.DataFrame()
    # Mantemos stores legados vazios para compatibilidade com clientes em cache.
    return int(time.time()), {}, {}


@app.callback(
    Output("layer-itinerarios", "children"),
    Output("layer-paradas",     "children"),
    Output("layer-onibus",      "children"),
    Output("layer-brt",         "children"),
    Output("legenda",           "children"),
    Input("store-gps-ts",       "data"),
    Input("store-linhas-debounce", "data"),
    prevent_initial_call=False,
)
def atualizar_mapa(_ts, linhas_sel):
    """Reconstrói as camadas do mapa lendo do cache server-side."""
    linhas_sel = linhas_sel or []
    selected_lines = set(str(ln) for ln in linhas_sel)
    cores      = get_linha_cores(linhas_sel)
    
    # Lê do cache server-side PRIMEIRO
    with _gps_lock:
        dados = _gps_cache
    

    # --- Legenda --------------------------------------------------------------
    # Mini-legenda de ícones (sempre presente)
    icone_seta = _cache_or_generate_svg("#888", float("nan"))
    icone_circulo = _cache_or_generate_svg("#888", 0)
    secao_icones = html.Div(
        [
            html.B("Ícones:", style={"display": "block", "marginBottom": "4px", "fontSize": "10px"}),
            html.Div(
                [
                    html.Img(src=icone_seta[0], style={"width": "clamp(14px, 1.4vw, 18px)", "height": "clamp(14px, 1.4vw, 18px)", "flexShrink": 0}),
                    html.Span("Parado/Não atualizado", style={"fontSize": "clamp(9px, 1vw, 11px)"}),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "5px", "marginBottom": "3px"},
            ),
            html.Div(
                [
                    html.Img(src=icone_circulo[0], style={"width": "clamp(14px, 1.4vw, 18px)", "height": "clamp(14px, 1.4vw, 18px)", "flexShrink": 0}),
                    html.Span("Em movimento", style={"fontSize": "clamp(9px, 1vw, 11px)"}),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "5px"},
            ),
        ],
        style={"marginTop": "7px", "paddingTop": "6px", "borderTop": "1px solid #dee2e6"},
    )

    if not linhas_sel:
        legenda = html.Div(
            [
                html.B("Linhas no mapa:",
                       style={"display": "block", "marginBottom": "3px", "fontSize": "clamp(10px, 1.1vw, 13px)"}),
                html.Span("Nenhuma linha selecionada",
                          style={"color": "#888", "fontStyle": "italic"}),
                secao_icones,
            ],
            style={**ESTILOS["caixa_legenda"], "minWidth": "clamp(135px, 18vw, 180px)"},
        )
        # OTIMIZAÇÃO: Retorna early — sem processar shapes/paradas se nada foi selecionado
        return [], [], [], [], legenda

    # Só processa shapes/paradas quando linhas foram selecionadas
    itens = []
    for ln in linhas_sel:
        cor       = cores.get(ln, "#888888")
        nome_long = linhas_dict.get(ln, "")
        linha_label = linha_exibicao(ln)
        itens.append(
            html.Div(
                [
                    html.Span(style={
                        "flexShrink": 0, "marginTop": "2px",
                        "width": "clamp(11px, 1vw, 14px)", "height": "clamp(11px, 1vw, 14px)",
                        "borderRadius": "2px", "background": cor,
                        "display": "inline-block",
                    }),
                    html.Span(
                        [html.B(linha_label)]
                        + ([html.Br(), html.Span(nome_long,
                            style={"color": "#555", "fontSize": "clamp(9px, 1vw, 11px)"})]
                           if nome_long else [])
                    ),
                ],
                style={"display": "flex", "alignItems": "flex-start",
                       "gap": "6px", "marginBottom": "4px"},
            )
        )
    legenda = html.Div(
        [
            html.B("Linhas no mapa:",
                   style={"display": "block", "marginBottom": "4px", "fontSize": "clamp(10px, 1.1vw, 13px)"}),
            *itens,
            secao_icones,
        ],
        style={**ESTILOS["caixa_legenda"], "minWidth": "clamp(135px, 18vw, 180px)", "maxWidth": "clamp(195px, 28vw, 280px)"},
    )

    if dados.empty:
        return [], [], [], [], legenda

    dados_filtrados = dados[dados["linha"].isin(selected_lines)]

    sppo_df = dados_filtrados[dados_filtrados["tipo"] == "SPPO"].copy() if len(dados_filtrados) > 0 else pd.DataFrame()
    brt_df  = dados_filtrados[dados_filtrados["tipo"] == "BRT"].copy()  if len(dados_filtrados) > 0 else pd.DataFrame()

    # Reduz marcadores em zoom baixo para evitar travamentos na renderização
    # Sem Input de zoom no callback para evitar incompatibilidade de payload
    # com alguns clientes Dash/dash-leaflet. Usa zoom padrão do mapa (11).
    sppo_df = _limit_df_for_render(sppo_df, 11)
    brt_df = _limit_df_for_render(brt_df, 11)

    # --- Itinerários ----------------------------------------------------------
    if not _gtfs_load_event.is_set():
        # Nao bloquear callback por muitos segundos; renderiza GPS e legenda imediatamente.
        print("GTFS ainda carregando: renderizando mapa sem shapes/paradas por enquanto.")

    # Fallback no runtime para Render: se as linhas nao tiverem estaticos, tenta recarregar.
    _recarregar_gtfs_estatico_sob_demanda(linhas_sel)

    with _gtfs_data_lock:
        shape_coords_snapshot = dict(line_to_shape_coords)
        stops_points_snapshot = dict(line_to_stops_points)

    cache_key = tuple(sorted(str(ln) for ln in linhas_sel))
    with _map_static_cache_lock:
        cached_layers = _map_static_cache.get(cache_key)

    if cached_layers is not None:
        # Evita mutar listas do cache em renderizações subsequentes.
        shapes_layers = list(cached_layers[0])
        paradas_layers = list(cached_layers[1])
    else:
        shapes_layers = []
        paradas_layers = []

    if cached_layers is None:
        try:
            for linha_id in linhas_sel:
                cor = cores.get(linha_id, "#888888")
                for coords in shape_coords_snapshot.get(linha_id, []):
                    linha_label = linha_publica(linha_id)
                    shapes_layers.append(
                        dl.Polyline(
                            positions=coords,
                            color=cor,
                            weight=4,
                            className="itinerario-polyline",
                            children=dl.Tooltip(f"Linha {linha_label}"),
                        )
                    )

                for stop_lat, stop_lon, stop_name in stops_points_snapshot.get(linha_id, []):
                    paradas_layers.append(
                        dl.CircleMarker(
                            center=[stop_lat, stop_lon],
                            radius=4,
                            color="darkred",
                            fillColor="red",
                            fillOpacity=0.75,
                            children=dl.Popup(stop_name),
                        )
                    )

            # Em selecao ampla, renderiza subconjunto de paradas para manter fluidez.
            paradas_layers = _limit_list_for_render(paradas_layers, MAX_STOPS_PER_RENDER)
        except Exception as e:
            print(f"ERRO ao montar camadas estáticas por linha: {type(e).__name__} - {e}")

        with _map_static_cache_lock:
            if len(_map_static_cache) >= _MAP_STATIC_CACHE_MAX_ITEMS:
                _map_static_cache.clear()
            _map_static_cache[cache_key] = (list(shapes_layers), list(paradas_layers))

    # --- Helper popup ---------------------------------------------------------
    def _popup(row, extra=None):
        try:
            vel = round(float(row.get("velocidade", 0)), 1)
        except Exception:
            vel = 0
        hora = str(row.get("datahora", ""))
        hora = hora[-8:] if len(hora) >= 8 else hora
        items = [
            html.P(f"Número do veículo: {row.get('ordem', '')}",  style={"margin": "2px 0"}),
            html.P(f"Serviço: {linha_publica(row.get('linha', ''))}",  style={"margin": "2px 0"}),
            html.P(f"Vista: {linhas_dict.get(row.get('linha', ''), '')}",
                   style={"margin": "2px 0"}),
            html.P(f"Velocidade: {vel} km/h",         style={"margin": "2px 0"}),
        ]
        if extra:
            items.append(html.P(extra, style={"margin": "2px 0"}))
        items.append(html.P(f"Hora: {hora}", style={"margin": "2px 0"}))
        return dl.Popup(html.Div(items))

    # --- Ônibus/BRT -----------------------------------------------------------
    lightweight_mode = (len(sppo_df) + len(brt_df)) > LIGHTWEIGHT_MARKER_THRESHOLD
    if lightweight_mode:
        onibus_children = _build_geojson_cluster_layer(sppo_df, "geojson-sppo")
        brt_children = _build_geojson_cluster_layer(brt_df, "geojson-brt")
        return shapes_layers, paradas_layers, onibus_children, brt_children, legenda

    # Modo detalhado: marcadores com icone direcional e popup.
    onibus_layers = []
    for row in sppo_df.itertuples(index=False):
        row_dict = row._asdict()
        cor = cores.get(row_dict.get("linha", ""), "#1a6faf") if linhas_sel else "#1a6faf"
        try:
            bearing = float(row_dict.get("direcao", float("nan")))
        except Exception:
            bearing = float("nan")
        onibus_layers.append(
            dl.Marker(
                position=[float(row_dict["lat"]), float(row_dict["lng"])],
                icon=dict(zip(["iconUrl", "iconSize", "iconAnchor"], make_vehicle_icon(bearing, cor))),
                children=_popup(row_dict),
            )
        )

    brt_layers = []
    for row in brt_df.itertuples(index=False):
        row_dict = row._asdict()
        cor = cores.get(row_dict.get("linha", ""), "#e67e00") if linhas_sel else "#e67e00"
        try:
            bearing = float(row_dict.get("direcao", float("nan")))
        except Exception:
            bearing = float("nan")
        brt_layers.append(
            dl.Marker(
                position=[float(row_dict["lat"]), float(row_dict["lng"])],
                icon=dict(zip(["iconUrl", "iconSize", "iconAnchor"], make_vehicle_icon(bearing, cor))),
                children=_popup(row_dict, extra=f"Sentido: {row_dict.get('sentido', '')}"),
            )
        )

    onibus_children = _group_vehicle_markers(onibus_layers)
    brt_children = _group_vehicle_markers(brt_layers)
    return shapes_layers, paradas_layers, onibus_children, brt_children, legenda


# ==============================================================================
# Callbacks de geolocalização
# ==============================================================================

# Clientside callback: chama navigator.geolocation diretamente no browser.
# Funciona em todos os cliques pois sempre grava um objeto novo no store.
app.clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return window.dash_clientside.no_update;
        return new Promise(function(resolve) {
            if (!navigator.geolocation) {
                alert("Geolocalização não suportada neste navegador.");
                resolve(window.dash_clientside.no_update);
                return;
            }

            function toPayload(pos) {
                return {
                    lat: pos.coords.latitude,
                    lon: pos.coords.longitude,
                    ts: Date.now(),
                    acc: pos.coords.accuracy
                };
            }

            // 1a tentativa: força leitura fresca (sem cache) com alta precisão.
            navigator.geolocation.getCurrentPosition(
                function(pos1) {
                    var acc1 = Number(pos1 && pos1.coords ? pos1.coords.accuracy : NaN);

                    // Se precisão já for boa, resolve imediatamente.
                    if (!isNaN(acc1) && acc1 <= 120) {
                        resolve(toPayload(pos1));
                        return;
                    }

                    // 2a tentativa: dá mais tempo para o GPS "fixar" (evita precisar de 2º clique).
                    navigator.geolocation.getCurrentPosition(
                        function(pos2) {
                            var acc2 = Number(pos2 && pos2.coords ? pos2.coords.accuracy : NaN);
                            if (!isNaN(acc2) && (isNaN(acc1) || acc2 <= acc1)) {
                                resolve(toPayload(pos2));
                            } else {
                                resolve(toPayload(pos1));
                            }
                        },
                        function() {
                            resolve(toPayload(pos1));
                        },
                        {enableHighAccuracy: true, timeout: 12000, maximumAge: 0}
                    );
                },
                function(err) {
                    alert("Erro ao obter localização: " + err.message);
                    resolve(window.dash_clientside.no_update);
                },
                {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}
            );
        });
    }
    """,
    Output("store-localizacao", "data"),
    Input("btn-localizar",      "n_clicks"),
    prevent_initial_call=True,
)


def _calcular_viewport_linhas(linhas_sel):
    """Calcula viewport (center, zoom, bounds) para linhas selecionadas com proteção contra outliers."""
    if not linhas_sel:
        print("Zoom linhas: seleção vazia")
        return None, None, None

    _recarregar_gtfs_estatico_sob_demanda(linhas_sel)
    if not _gtfs_load_event.is_set():
        # Primeiro uso pode chegar antes da thread de carga concluir.
        _gtfs_load_event.wait(timeout=1.2)
        if not _gtfs_load_event.is_set():
            print("Zoom linhas: GTFS ainda não disponível para calcular viewport.")
            return None, None, None

    with _gtfs_data_lock:
        bounds_snapshot = dict(line_to_bounds)
        shape_coords_snapshot = dict(line_to_shape_coords)

    all_lats = []
    all_lons = []
    total_points = 0
    kept_points = 0
    rejected_bbox = 0
    rejected_polygon = 0

    # Filtro geográfico amplo do município/região metropolitana para descartar pontos espúrios.
    RIO_LAT_MIN, RIO_LAT_MAX = -23.6, -22.4
    RIO_LON_MIN, RIO_LON_MAX = -44.3, -42.8

    for linha_id in (str(ln) for ln in linhas_sel):
        coords_linha = shape_coords_snapshot.get(linha_id, [])
        for coords in coords_linha:
            if not coords:
                continue
            for pt in coords:
                total_points += 1
                try:
                    lat = float(pt[0])
                    lon = float(pt[1])
                except Exception:
                    continue
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                if not (RIO_LAT_MIN <= lat <= RIO_LAT_MAX and RIO_LON_MIN <= lon <= RIO_LON_MAX):
                    rejected_bbox += 1
                    continue
                if rio_polygon is not None:
                    try:
                        if not rio_polygon.covers(Point(lon, lat)):
                            rejected_polygon += 1
                            continue
                    except Exception:
                        pass
                all_lats.append(lat)
                all_lons.append(lon)
                kept_points += 1

    print(
        f"Zoom linhas debug: linhas={linhas_sel}, total_points={total_points}, "
        f"kept={kept_points}, rej_bbox={rejected_bbox}, rej_polygon={rejected_polygon}"
    )

    # Se não houver pontos válidos, tenta fallback por bounds pré-computados.
    if not all_lats or not all_lons:
        print("Zoom linhas debug: usando fallback por bounds pré-computados")
        min_lat = None
        min_lon = None
        max_lat = None
        max_lon = None
        for linha_id in (str(ln) for ln in linhas_sel):
            b = bounds_snapshot.get(linha_id)
            if not b:
                continue
            sw, ne = b
            min_lat = sw[0] if min_lat is None else min(min_lat, sw[0])
            min_lon = sw[1] if min_lon is None else min(min_lon, sw[1])
            max_lat = ne[0] if max_lat is None else max(max_lat, ne[0])
            max_lon = ne[1] if max_lon is None else max(max_lon, ne[1])
    else:
        # Remove extremos para evitar zoom muito aberto por um ponto espúrio.
        if len(all_lats) >= 25:
            print("Zoom linhas debug: aplicando quantis 5%-95%")
            lat_s = pd.Series(all_lats)
            lon_s = pd.Series(all_lons)
            min_lat = float(lat_s.quantile(0.05))
            max_lat = float(lat_s.quantile(0.95))
            min_lon = float(lon_s.quantile(0.05))
            max_lon = float(lon_s.quantile(0.95))
        else:
            min_lat = min(all_lats)
            max_lat = max(all_lats)
            min_lon = min(all_lons)
            max_lon = max(all_lons)

    if None in (min_lat, min_lon, max_lat, max_lon):
        print(f"Zoom linhas: sem bounds válidos para seleção {linhas_sel}")
        return None, None, None

    lat_span_raw = abs(max_lat - min_lat)
    lon_span_raw = abs(max_lon - min_lon)

    # Margem moderada para caber o itinerário sem abrir demais o zoom.
    lat_pad = max(0.0012, lat_span_raw * 0.08)
    lon_pad = max(0.0012, lon_span_raw * 0.08)
    min_lat -= lat_pad
    max_lat += lat_pad
    min_lon -= lon_pad
    max_lon += lon_pad
    bounds = [[round(min_lat, 6), round(min_lon, 6)], [round(max_lat, 6), round(max_lon, 6)]]

    center = [round((min_lat + max_lat) / 2, 6), round((min_lon + max_lon) / 2, 6)]

    lat_span = max(0.0001, abs(max_lat - min_lat))
    lon_span = max(0.0001, abs(max_lon - min_lon))
    zoom_lat = math.log2(170.0 / lat_span)
    zoom_lon = math.log2(360.0 / lon_span)

    user_agent = (request.headers.get("User-Agent", "") or "").lower()
    is_mobile = any(token in user_agent for token in ["mobile", "android", "iphone", "ipad"])
    min_zoom = 13 if is_mobile else 13
    zoom = int(max(min_zoom, min(15, math.floor(min(zoom_lat, zoom_lon)))))

    print(
        f"Zoom linhas {linhas_sel}: center={center}, "
        f"span_lat={round(lat_span, 5)}, span_lon={round(lon_span, 5)}, "
        f"mobile={is_mobile}, zoom={zoom}"
    )
    print(f"Zoom linhas {linhas_sel}: bounds={bounds}")
    return center, zoom, bounds


def _resolver_comando_viewport(data_localizacao, linhas_sel, linhas_sel_debounce):
    """Resolve comando de viewport (dict com center/zoom ou bounds) e camada de localização."""
    triggered_props = [item.get("prop_id", "") for item in (dash.callback_context.triggered or [])]
    trigger = triggered_props[0].split(".")[0] if triggered_props else None
    has_location_trigger = any(prop.startswith("store-localizacao.") for prop in triggered_props)
    has_dropdown_trigger = any(prop.startswith("dropdown-linhas.") for prop in triggered_props)
    has_debounce_trigger = any(prop.startswith("store-linhas-debounce.") for prop in triggered_props)
    has_lines_trigger = has_dropdown_trigger or has_debounce_trigger

    # Usa a seleção mais recente conforme a origem do trigger.
    if has_debounce_trigger:
        linhas_ativas = linhas_sel_debounce or []
    elif has_dropdown_trigger:
        linhas_ativas = linhas_sel or []
    else:
        linhas_ativas = linhas_sel_debounce or linhas_sel or []

    now_ms = time.time() * 1000.0

    # Evita que atualização de linhas sobrescreva imediatamente a geolocalização recém-clicada.
    recent_location_ms = None
    if isinstance(data_localizacao, dict) and data_localizacao.get("ts") is not None:
        try:
            recent_location_ms = float(data_localizacao.get("ts"))
        except Exception:
            recent_location_ms = None

    delta_loc_ms = None
    if recent_location_ms is not None:
        try:
            delta_loc_ms = round(now_ms - recent_location_ms, 1)
        except Exception:
            delta_loc_ms = None

    print(
        "Viewport debug: "
        f"triggered={triggered_props}, "
        f"has_loc={has_location_trigger}, has_lines={has_lines_trigger}, "
        f"loc_ts={recent_location_ms}, delta_loc_ms={delta_loc_ms}, "
        f"linhas_count={len(linhas_ativas or [])}"
    )

    # Quando inputs chegam juntos, sempre prioriza geolocalização.
    if has_location_trigger or trigger == "store-localizacao":
        if not data_localizacao or data_localizacao.get("lat") is None:
            return dash.no_update, dash.no_update

        lat = float(data_localizacao["lat"])
        lon = float(data_localizacao["lon"])
        icone_usuario = _gerar_svg_usuario()
        marcador = dl.Marker(
            position=[lat, lon],
            icon={"iconUrl": icone_usuario, "iconSize": [22, 22], "iconAnchor": [11, 11]},
            children=dl.Tooltip("Você está aqui"),
        )
        print(f"Viewport localização: center={[lat, lon]}, zoom=15")
        return {"center": [lat, lon], "zoom": 15}, [marcador]

    if has_lines_trigger or trigger in ("dropdown-linhas", "store-linhas-debounce"):
        # Só prioriza geolocalização quando ambos os eventos chegam no mesmo ciclo.
        if has_location_trigger and has_lines_trigger:
            print("Viewport linhas ignorado: trigger simultâneo com geolocalização.")
            return dash.no_update, dash.no_update

        center, zoom, bounds = _calcular_viewport_linhas(linhas_ativas)
        if center is None or zoom is None or bounds is None:
            # Fallback: usa centro dos veículos já carregados para primeira seleção.
            sel = set(str(x) for x in (linhas_ativas or []))
            with _gps_lock:
                gps_snapshot = _gps_cache.copy() if not _gps_cache.empty else pd.DataFrame()
            if not gps_snapshot.empty and sel:
                gps_snapshot = gps_snapshot[gps_snapshot["linha"].astype(str).isin(sel)]
                if not gps_snapshot.empty:
                    center = [
                        round(float(gps_snapshot["lat"].median()), 6),
                        round(float(gps_snapshot["lng"].median()), 6),
                    ]
                    print(f"Viewport linhas fallback GPS: center={center}, zoom=12")
                    return {"center": center, "zoom": 12}, dash.no_update
            return dash.no_update, dash.no_update

        # Em linha, preferir fit por bounds (mais estável que center/zoom em alguns clientes).
        print(f"Viewport linhas apply: bounds-only={bounds}")
        return {"bounds": bounds}, dash.no_update

    return dash.no_update, dash.no_update


if MAP_SUPPORTS_VIEWPORT:
    @app.callback(
        Output("mapa", "viewport"),
        Output("layer-localizacao", "children"),
        Input("store-localizacao", "data"),
        Input("dropdown-linhas", "value"),
        Input("store-linhas-debounce", "data"),
        prevent_initial_call=True,
    )
    def controlar_viewport_mapa(data_localizacao, linhas_sel, linhas_sel_debounce):
        """Controla viewport usando prop nativa 'viewport' quando disponível."""
        return _resolver_comando_viewport(data_localizacao, linhas_sel, linhas_sel_debounce)
else:
    @app.callback(
        Output("mapa", "center"),
        Output("mapa", "zoom"),
        Output("mapa", "bounds"),
        Output("layer-localizacao", "children"),
        Input("store-localizacao", "data"),
        Input("dropdown-linhas", "value"),
        Input("store-linhas-debounce", "data"),
        prevent_initial_call=True,
    )
    def controlar_viewport_mapa(data_localizacao, linhas_sel, linhas_sel_debounce):
        """Fallback compatível: converte comando de viewport para center/zoom/bounds."""
        command, marker_layer = _resolver_comando_viewport(data_localizacao, linhas_sel, linhas_sel_debounce)

        if command is dash.no_update:
            return dash.no_update, dash.no_update, dash.no_update, marker_layer

        if isinstance(command, dict):
            if "bounds" in command:
                return dash.no_update, dash.no_update, command["bounds"], marker_layer
            center = command.get("center", dash.no_update)
            zoom = command.get("zoom", dash.no_update)
            return center, zoom, None, marker_layer

        return dash.no_update, dash.no_update, dash.no_update, marker_layer


# ==============================================================================
# Callback: Atualizar UI do botão e timestamp de atualização
# ==============================================================================

@app.callback(
    Output("span-update-time", "children"),
    Input("store-gps-ts", "data"),
)
def atualizar_ui_atualizacao(_gps_ts):
    """Mostra timestamp da última atualização bem-sucedida."""
    with _status_lock:
        last_ts = _last_update_ts

    tempo_texto = ""
    if last_ts:
        try:
            dt = last_ts if isinstance(last_ts, datetime) else datetime.fromisoformat(str(last_ts))
            tempo_texto = dt.strftime("%H:%M:%S")
        except Exception:
            tempo_texto = ""

    return tempo_texto


# ==============================================================================
# Ponto de entrada
# ==============================================================================

if __name__ == "__main__":
    # No Render, a porta deve vir da variável de ambiente PORT.
    port = int(os.getenv("PORT", "8050"))
    app.run(debug=False, host="0.0.0.0", port=port)