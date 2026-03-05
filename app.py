# ==============================================================================
# GPS BRT-SPPO - SMTR/RJ  |  Python + Dash
# Equivalente ao app.R em Shiny
#
# Estrutura esperada da pasta:
#   app.py
#   requirements.txt
#   Procfile
#   gtfs/
#     gtfs.zip
# ==============================================================================

import math
import os
import time
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
from dash import Input, Output, State, dcc, html
from shapely.geometry import LineString, shape as shapely_shape, MultiPolygon

warnings.filterwarnings("ignore")

# ==============================================================================
# Paleta de cores (15 cores com alto contraste)
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
        "padding": "8px 16px",
        "backgroundColor": "#343a40",
        "color": "white",
        "display": "flex",
        "alignItems": "center",
    },
    "header_titulo": {
        "margin": 0,
        "fontSize": "18px",
        "fontWeight": "bold",
    },
    "controles": {
        "padding": "10px 16px",
        "backgroundColor": "#f8f9fa",
        "borderBottom": "1px solid #dee2e6",
        "display": "flex",
        "flexDirection": "column",
        "alignItems": "center",
        "gap": "10px",
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
        "backgroundColor": "#0d6efd",
        "color": "white",
        "border": "none",
        "padding": "8px 16px",
        "borderRadius": "4px",
        "cursor": "pointer",
    },
    "texto_atualizacao": {
        "color": "#6c757d",
        "fontSize": "12px",
        "margin": "0 0 0 10px",
    },
    "caixa_legenda": {
        "background": "white",
        "padding": "10px 14px",
        "borderRadius": "4px",
        "boxShadow": "0 1px 5px rgba(0,0,0,.4)",
        "font": "12px/1.5 Arial,sans-serif",
    },
    "botao_localizacao": {
        "width": "34px",
        "height": "34px",
        "backgroundColor": "white",
        "border": "2px solid rgba(0,0,0,0.3)",
        "borderRadius": "4px",
        "cursor": "pointer",
        "fontSize": "16px",
        "lineHeight": "1",
        "boxShadow": "none",
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
        "zIndex": 1000,
        "pointerEvents": "none",
    },
}

# ==============================================================================
# Dados estáticos — inicializados vazios, carregados em thread paralela
# ==============================================================================

# Cache GPS server-side — evita trafegar dados pesados para o browser
_gps_lock  = threading.Lock()
_gps_cache = pd.DataFrame()   # último fetch processado

# Cache das camadas estáticas (itinerários/paradas) por conjunto de linhas
_map_static_cache_lock = threading.Lock()
_map_static_cache = {}
_MAP_STATIC_CACHE_MAX_ITEMS = 64

# Sincronização para carregamento de dados estáticos
_gtfs_load_event = threading.Event()  # Sinaliza quando GTFS foi carregado
_gtfs_load_event.clear()

rio_polygon      = None
garagens_polygon = None
gtfs             = {}
shapes_gtfs      = None
stops_gtfs       = None
line_to_shape_ids = {}
line_to_stop_ids  = {}
linhas_dict      = {}
linhas_short     = []
linha_cor_fixa   = {}

MARKER_LIMITS_BY_ZOOM = [
    (9, 150),
    (10, 250),
    (11, 400),
    (12, 650),
    (13, 900),
    (14, 1300),
]


# --- routes.txt carregado de forma SÍNCRONA (rápido, só strings) ----------------
# Isso garante que o dropdown já tem opções quando o app abre.
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
        with zipfile.ZipFile("gtfs/gtfs.zip") as z:
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

        _shapes_gtfs = None
        _stops_gtfs  = None

        if "shapes" in _gtfs and not _gtfs["shapes"].empty:
            try:
                df = _gtfs["shapes"].copy()
                df["shape_pt_lat"]      = pd.to_numeric(df["shape_pt_lat"], errors="coerce")
                df["shape_pt_lon"]      = pd.to_numeric(df["shape_pt_lon"], errors="coerce")
                df["shape_pt_sequence"] = pd.to_numeric(df["shape_pt_sequence"], errors="coerce")
                df = df.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
                lines = (
                    df.sort_values("shape_pt_sequence")
                    .groupby("shape_id")
                    .apply(lambda x: LineString(zip(x["shape_pt_lon"], x["shape_pt_lat"])),
                           include_groups=False)
                    .reset_index()
                )
                lines.columns = ["shape_id", "geometry"]
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
            except Exception as e:
                print(f"ERRO ao montar índices GTFS por linha: {type(e).__name__} - {e}")

        gtfs        = _gtfs
        shapes_gtfs = _shapes_gtfs
        stops_gtfs  = _stops_gtfs
        line_to_shape_ids = _line_to_shape_ids
        line_to_stop_ids  = _line_to_stop_ids
        with _map_static_cache_lock:
            _map_static_cache.clear()
        print(f"GTFS carregado com arquivos: {list(_gtfs.keys())}")
    except FileNotFoundError:
        print("ERRO: Arquivo gtfs/gtfs.zip não encontrado")
    except KeyError as e:
        print(f"ERRO ao carregar GTFS (coluna faltante): {e}")
    except Exception as e:
        print(f"ERRO ao carregar GTFS: {type(e).__name__} - {e}")

    print("Carregamento inicial concluído.")
    # Sinaliza que o GTFS foi carregado (mesmo que parcialmente)
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


def make_vehicle_icon(bearing, color="#1a6faf"):
    """Gera ícone SVG direcional como data-URI.
    Sem direção: círculo 19x19 (2/3). Com direção: seta 28x28.
    Retorna (url, [w, h], [ax, ay]).
    """
    is_nan = bearing is None or (isinstance(bearing, float) and math.isnan(bearing))
    if is_nan:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 28 28">'
            f'<circle cx="14" cy="14" r="10" fill="{color}" stroke="black" stroke-width="2.5"/>'
            f'<circle cx="14" cy="14" r="4" fill="white"/>'
            f"</svg>"
        )
        return ("data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg), [19, 19], [9, 9])
    else:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">'
            f'<g transform="rotate({bearing:.0f}, 14, 14)">'
            f'<polygon points="14,2 24,24 14,18 4,24" fill="{color}" stroke="black" stroke-width="2"/>'
            f"</g></svg>"
        )
        return ("data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg), [28, 28], [14, 14])


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
                df[lat_col].astype(str).str.replace(",", "."),
                errors="coerce"
            )
        else:
            df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        
        if config["lon_needs_conversion"]:
            df[lon_col] = pd.to_numeric(
                df[lon_col].astype(str).str.replace(",", "."),
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
    
    hist_map = {r["ordem"]: r for r in hist_list}
    ordens_presentes = df["ordem"].isin(hist_map.keys())
    
    if not ordens_presentes.any():
        return df
    
    # Processar apenas veículos com histórico
    for idx in df[ordens_presentes].index:
        row = df.loc[idx]
        ant = hist_map.get(row["ordem"])
        if ant is None:
            continue
        
        t_atual = pd.to_datetime(row["datahora"])
        t_ant = pd.to_datetime(ant["datahora"])
        time_diff = abs((t_atual - t_ant).total_seconds() / 60)
        
        if time_diff >= 10:
            continue
        
        dist = haversine(ant["lat"], ant["lng"], row["lat"], row["lng"])
        if dist >= dist_min:
            df.at[idx, "direcao"] = round(
                bearing_between(ant["lat"], ant["lng"], row["lat"], row["lng"]), 0
            )
        else:
            ub = ant.get("ultimo_bearing")
            if ub is not None:
                df.at[idx, "direcao"] = ub
    
    return df


def atualizar_historico(hist_list, df):
    """Mantém apenas a posição mais recente por veículo no histórico."""
    hist_map = {r["ordem"]: r for r in (hist_list or [])}
    
    # Iterar apenas sobre linhas do dataframe (mais eficiente)
    for _, row in df.iterrows():
        direcao = row.get("direcao")
        ub = (
            direcao
            if direcao is not None and not (isinstance(direcao, float) and math.isnan(direcao))
            else hist_map.get(row["ordem"], {}).get("ultimo_bearing")
        )
        hist_map[row["ordem"]] = {
            "ordem":          row["ordem"],
            "datahora":       str(row["datahora"]),
            "lat":            row["lat"],
            "lng":            row["lng"],
            "ultimo_bearing": ub,
        }
    return list(hist_map.values())


def fetch_gps_data():
    """Busca dados GPS das APIs SPPO e BRT e retorna DataFrame unificado."""
    # Usar UTC-3 (BRT) explicitamente para compatibilidade local e no Render
    agora  = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
    inicio = agora - timedelta(minutes=3)
    fmt    = "%Y-%m-%d+%H:%M:%S"

    sppo_df = pd.DataFrame()
    brt_df  = pd.DataFrame()

    # Sessão compartilhada com headers para simular browser
    _headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.data.rio/",
    }
    session = requests.Session()
    session.headers.update(_headers)

    # SPPO
    url_sppo = (
        f"https://dados.mobilidade.rio/gps/sppo"
        f"?dataInicial={inicio.strftime(fmt)}&dataFinal={agora.strftime(fmt)}"
    )
    try:
        resp = session.get(url_sppo, timeout=30)
        print(f"SPPO status: {resp.status_code} | Content-Type: {resp.headers.get('Content-Type','')}")
        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, list) and data:
                    sppo_df = pd.DataFrame(data)
            except ValueError:
                print(f"SPPO body nao e JSON valido")
        print(f"SPPO: {len(sppo_df)} registros brutos")
    except requests.Timeout:
        print("ERRO API SPPO: Timeout na requisição")
    except requests.RequestException as e:
        print(f"ERRO API SPPO: {type(e).__name__} - {e}")
    except Exception as e:
        print(f"ERRO inesperado SPPO: {type(e).__name__} - {e}")

    # BRT
    try:
        resp = session.get("https://dados.mobilidade.rio/gps/brt", timeout=30)
        if resp.status_code == 200:
            veiculos = resp.json().get("veiculos") or []
            if veiculos:
                brt_df = pd.DataFrame(veiculos)
        print(f"BRT: {len(brt_df)} registros brutos")
    except requests.Timeout:
        print("ERRO API BRT: Timeout na requisição")
    except requests.RequestException as e:
        print(f"ERRO API BRT: {type(e).__name__} - {e}")
    except Exception as e:
        print(f"ERRO inesperado BRT: {type(e).__name__} - {e}")

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

    # Filtro espacial — dentro do município do Rio, fora das garagens
    if (rio_polygon is not None or garagens_polygon is not None) and len(dados) > 0:
        gdf = gpd.GeoDataFrame(
            dados,
            geometry=gpd.points_from_xy(dados["longitude"], dados["latitude"]),
            crs="EPSG:4326",
        )
        # Mantém apenas pontos dentro do Rio (se limite carregado)
        if rio_polygon is not None:
            gdf = gdf[gdf.geometry.within(rio_polygon)]
        # Remove pontos dentro das garagens (se shapefile carregado)
        if garagens_polygon is not None and len(gdf) > 0:
            gdf = gdf[~gdf.geometry.within(garagens_polygon)]
        dados = gdf.drop(columns="geometry").copy()

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
    title="Consulta de ônibus no mapa - Rio de Janeiro",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # expõe o servidor Flask para deploy (gunicorn)

app.layout = html.Div(
    [
        dcc.Interval(id="intervalo",        interval=30_000, n_intervals=0),

        dcc.Store(id="store-hist-sppo", data=[]),
        dcc.Store(id="store-hist-brt",  data=[]),
        dcc.Store(id="store-gps-ts",    data=0),
        dcc.Store(id="store-localizacao", data=None),

        # Cabeçalho
        html.Div(
            html.H4("Consulta de ônibus no mapa - Rio de Janeiro", style=ESTILOS["header_titulo"]),
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
                                options=[{"label": ln, "value": ln} for ln in linhas_short],
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
                            "Atualizar posições",
                            id="btn-atualizar",
                            n_clicks=0,
                            style=ESTILOS["botao_atualizar"],
                        ),
                        html.P(
                            "Atualizações a cada 30 segs.",
                            style=ESTILOS["texto_atualizacao"],
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
                    style={"height": "calc(100vh - 130px)", "width": "100%"},
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
                                    name="ESRI Padrão", checked=False,
                                ),
                                dl.BaseLayer(
                                    dl.TileLayer(
                                        url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                                        attribution="Esri",
                                    ),
                                    name="ESRI P&B", checked=True,
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
            style={"position": "relative"},
        ),
    ],
    style={"fontFamily": "Arial, sans-serif", "boxSizing": "border-box",
            "overflowX": "hidden", "maxWidth": "100vw"},
)


# ==============================================================================
# Callbacks
# ==============================================================================




@app.callback(
    Output("store-gps-ts",    "data"),
    Output("store-hist-sppo", "data"),
    Output("store-hist-brt",  "data"),
    Input("intervalo",        "n_intervals"),
    Input("btn-atualizar",    "n_clicks"),
    State("store-hist-sppo",  "data"),
    State("store-hist-brt",   "data"),
    prevent_initial_call=False,
)
def atualizar_gps(_n_int, _n_btn, hist_sppo, hist_brt):
    """Busca GPS, armazena no cache server-side e retorna só timestamp."""
    global _gps_cache

    dados = fetch_gps_data()
    if len(dados) == 0:
        return dash.no_update, hist_sppo or [], hist_brt or []

    sppo_df = dados[dados["tipo"] == "SPPO"].copy()
    brt_df  = dados[dados["tipo"] == "BRT"].copy()

    if len(sppo_df) > 0:
        sppo_df   = calcular_bearing_df(sppo_df, hist_sppo)
        hist_sppo = atualizar_historico(hist_sppo, sppo_df)

    if len(brt_df) > 0:
        brt_df   = calcular_bearing_df(brt_df, hist_brt)
        hist_brt = atualizar_historico(hist_brt, brt_df)

    dados_final             = pd.concat([sppo_df, brt_df], ignore_index=True)
    dados_final["datahora"] = dados_final["datahora"].astype(str)

    # Salva server-side — nenhum dado pesado vai para o browser
    with _gps_lock:
        _gps_cache = dados_final

    return int(time.time()), hist_sppo, hist_brt


@app.callback(
    Output("layer-itinerarios", "children"),
    Output("layer-paradas",     "children"),
    Output("layer-onibus",      "children"),
    Output("layer-brt",         "children"),
    Output("legenda",           "children"),
    Input("store-gps-ts",       "data"),
    Input("dropdown-linhas",    "value"),
    prevent_initial_call=False,
)
def atualizar_mapa(_ts, linhas_sel):
    """Reconstrói as camadas do mapa lendo do cache server-side."""
    linhas_sel = linhas_sel or []
    cores      = get_linha_cores(linhas_sel)
    
    # Lê do cache server-side PRIMEIRO
    with _gps_lock:
        dados = _gps_cache.copy()
    

    # --- Legenda --------------------------------------------------------------
    # Mini-legenda de ícones (sempre presente)
    icone_seta_svg = _gerar_svg_seta()
    icone_circulo_svg = _gerar_svg_circulo()
    secao_icones = html.Div(
        [
            html.B("Ícones:", style={"display": "block", "marginBottom": "5px", "fontSize": "13px"}),
            html.Div(
                [
                    html.Img(src=icone_seta_svg, style={"width": "18px", "height": "18px", "flexShrink": 0}),
                    html.Span("Com direção", style={"fontSize": "11px"}),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "7px", "marginBottom": "4px"},
            ),
            html.Div(
                [
                    html.Img(src=icone_circulo_svg, style={"width": "18px", "height": "18px", "flexShrink": 0}),
                    html.Span("Sem direção (parado)", style={"fontSize": "11px"}),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "7px"},
            ),
        ],
        style={"marginTop": "10px", "paddingTop": "8px", "borderTop": "1px solid #dee2e6"},
    )

    if not linhas_sel:
        legenda = html.Div(
            [
                html.B("Linhas no mapa:",
                       style={"display": "block", "marginBottom": "4px", "fontSize": "13px"}),
                html.Span("Nenhuma linha selecionada",
                          style={"color": "#888", "fontStyle": "italic"}),
                secao_icones,
            ],
            style={**ESTILOS["caixa_legenda"], "minWidth": "180px"},
        )
    else:
        itens = []
        for ln in linhas_sel:
            cor       = cores.get(ln, "#888888")
            nome_long = linhas_dict.get(ln, "")
            itens.append(
                html.Div(
                    [
                        html.Span(style={
                            "flexShrink": 0, "marginTop": "2px",
                            "width": "14px", "height": "14px",
                            "borderRadius": "3px", "background": cor,
                            "display": "inline-block",
                        }),
                        html.Span(
                            [html.B(ln)]
                            + ([html.Br(), html.Span(nome_long,
                                style={"color": "#555", "fontSize": "11px"})]
                               if nome_long else [])
                        ),
                    ],
                    style={"display": "flex", "alignItems": "flex-start",
                           "gap": "8px", "marginBottom": "5px"},
                )
            )
        legenda = html.Div(
            [
                html.B("Linhas no mapa:",
                       style={"display": "block", "marginBottom": "6px", "fontSize": "13px"}),
                *itens,
                secao_icones,
            ],
            style={**ESTILOS["caixa_legenda"], "minWidth": "180px", "maxWidth": "260px",
                   "maxHeight": "40vh", "overflowY": "auto"},
        )

    if dados.empty:
        return [], [], [], [], legenda

    if not linhas_sel:
        # Nenhuma linha selecionada — não renderiza veículos
        return [], [], [], [], legenda

    dados_filtrados = dados[dados["linha"].isin(linhas_sel)]

    sppo_df = dados_filtrados[dados_filtrados["tipo"] == "SPPO"].copy() if len(dados_filtrados) > 0 else pd.DataFrame()
    brt_df  = dados_filtrados[dados_filtrados["tipo"] == "BRT"].copy()  if len(dados_filtrados) > 0 else pd.DataFrame()

    # Reduz marcadores em zoom baixo para evitar travamentos na renderização
    # Sem Input de zoom no callback para evitar incompatibilidade de payload
    # com alguns clientes Dash/dash-leaflet. Usa zoom padrão do mapa (11).
    sppo_df = _limit_df_for_render(sppo_df, 11)
    brt_df = _limit_df_for_render(brt_df, 11)

    # --- Itinerários ----------------------------------------------------------
    cache_key = tuple(sorted(str(ln) for ln in linhas_sel))
    with _map_static_cache_lock:
        cached_layers = _map_static_cache.get(cache_key)

    if cached_layers is not None:
        shapes_layers, paradas_layers = cached_layers
    else:
        shapes_layers = []
        paradas_layers = []
    
    # Aguarda o carregamento do GTFS (máximo 15 segundos)
    if linhas_sel and not _gtfs_load_event.is_set():
        print("Aguardando carregamento de GTFS para renderizar shapes/paradas...")
        _gtfs_load_event.wait(timeout=15)

    if linhas_sel and shapes_gtfs is not None and len(shapes_gtfs) > 0:
        if line_to_shape_ids:
            try:
                for linha_id in linhas_sel:
                    cor = cores.get(linha_id, "#888888")
                    shp_ids = line_to_shape_ids.get(linha_id, [])
                    if not shp_ids:
                        continue
                    sh = shapes_gtfs[shapes_gtfs["shape_id"].isin(shp_ids)]
                    for row in sh.itertuples(index=False):
                        try:
                            coords = [[pt[1], pt[0]] for pt in row.geometry.coords]
                            if len(coords) > 1:
                                shapes_layers.append(
                                    dl.Polyline(
                                        positions=coords,
                                        color=cor,
                                        weight=4,
                                        children=dl.Tooltip(f"Linha {linha_id}"),
                                    )
                                )
                        except Exception as e:
                            print(f"ERRO ao processar shape {linha_id}: {e}")
            except Exception as e:
                print(f"ERRO shapes: {type(e).__name__} - {e}")
    else:
        if linhas_sel and shapes_gtfs is None:
            print("AVISO: shapes_gtfs não carregado (arquivo gtfs.zip pode estar corrompido)")
        elif linhas_sel:
            print("AVISO: shapes_gtfs vazio - nenhuma shape para as linhas selecionadas")

    if linhas_sel and stops_gtfs is not None and len(stops_gtfs) > 0:
        if line_to_stop_ids:
            try:
                stop_ids = set()
                for linha_id in linhas_sel:
                    stop_ids.update(line_to_stop_ids.get(linha_id, []))

                if stop_ids:
                    stops_f = stops_gtfs[stops_gtfs["stop_id"].isin(stop_ids)]
                    for row in stops_f.itertuples(index=False):
                        try:
                            paradas_layers.append(
                                dl.CircleMarker(
                                    center=[float(row.stop_lat), float(row.stop_lon)],
                                    radius=5,
                                    color="darkred",
                                    fillColor="red",
                                    fillOpacity=0.8,
                                    children=dl.Popup(str(getattr(row, "stop_name", ""))),
                                )
                            )
                        except Exception as e:
                            print(f"ERRO ao processar parada: {e}")
            except Exception as e:
                print(f"ERRO paradas: {type(e).__name__} - {e}")
    else:
        if linhas_sel and stops_gtfs is None:
            print("AVISO: stops_gtfs não carregado (arquivo gtfs.zip pode estar corrompido)")
        elif linhas_sel:
            print("AVISO: stops_gtfs vazio - nenhuma parada para as linhas selecionadas")

    with _map_static_cache_lock:
        if len(_map_static_cache) >= _MAP_STATIC_CACHE_MAX_ITEMS:
            _map_static_cache.clear()
        _map_static_cache[cache_key] = (shapes_layers, paradas_layers)

    # --- Helper popup ---------------------------------------------------------
    def _popup(row, extra=None):
        try:
            vel = round(float(row.get("velocidade", 0)), 1)
        except Exception:
            vel = 0
        hora = str(row.get("datahora", ""))
        hora = hora[-8:] if len(hora) >= 8 else hora
        items = [
            html.P(f"Ordem: {row.get('ordem', '')}",  style={"margin": "2px 0"}),
            html.P(f"Linha: {row.get('linha', '')}",  style={"margin": "2px 0"}),
            html.P(f"Nome: {linhas_dict.get(row.get('linha', ''), '')}",
                   style={"margin": "2px 0"}),
            html.P(f"Velocidade: {vel} km/h",         style={"margin": "2px 0"}),
        ]
        if extra:
            items.append(html.P(extra, style={"margin": "2px 0"}))
        items.append(html.P(f"Hora: {hora}", style={"margin": "2px 0"}))
        return dl.Popup(html.Div(items))

    # --- Ônibus SPPO ----------------------------------------------------------
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
                icon=dict(zip(["iconUrl","iconSize","iconAnchor"], make_vehicle_icon(bearing, cor))),
                children=_popup(row_dict),
            )
        )

    # --- BRT ------------------------------------------------------------------
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
                icon=dict(zip(["iconUrl","iconSize","iconAnchor"], make_vehicle_icon(bearing, cor))),
                children=_popup(row_dict, extra=f"Sentido: {row_dict.get('sentido', '')}"),
            )
        )

    return shapes_layers, paradas_layers, onibus_layers, brt_layers, legenda


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
            navigator.geolocation.getCurrentPosition(
                function(pos) {
                    resolve({
                        lat: pos.coords.latitude,
                        lon: pos.coords.longitude,
                        ts:  Date.now()
                    });
                },
                function(err) {
                    alert("Erro ao obter localização: " + err.message);
                    resolve(window.dash_clientside.no_update);
                },
                {enableHighAccuracy: true, timeout: 10000}
            );
        });
    }
    """,
    Output("store-localizacao", "data"),
    Input("btn-localizar",      "n_clicks"),
    prevent_initial_call=True,
)


@app.callback(
    Output("mapa",              "center"),
    Output("mapa",              "zoom"),
    Output("layer-localizacao", "children"),
    Input("store-localizacao",  "data"),
    prevent_initial_call=True,
)
def centralizar_na_posicao(data):
    """Centraliza o mapa e adiciona marcador na posição do usuário."""
    if not data or data.get("lat") is None:
        return dash.no_update, dash.no_update, []

    lat, lon = data["lat"], data["lon"]

    icone_usuario = _gerar_svg_usuario()
    marcador = dl.Marker(
        position=[lat, lon],
        icon={"iconUrl": icone_usuario, "iconSize": [22, 22], "iconAnchor": [11, 11]},
        children=dl.Tooltip("Você está aqui"),
    )
    return [lat, lon], 15, [marcador]


# ==============================================================================
# Ponto de entrada
# ==============================================================================

if __name__ == "__main__":
    # No Render, a porta deve vir da variável de ambiente PORT.
    port = int(os.getenv("PORT", "8050"))
    app.run(debug=False, host="0.0.0.0", port=port)