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
import zipfile
import urllib.parse
import warnings
from datetime import datetime, timedelta

import dash
import dash_leaflet as dl
import geopandas as gpd
import pandas as pd
import requests
from dash import Input, Output, State, dcc, html
from shapely.geometry import LineString

warnings.filterwarnings("ignore")

# ==============================================================================
# Paleta de cores
# ==============================================================================

PALETA_CORES = [
    "#E63946", "#F4A261", "#2A9D8F", "#457B9D", "#6A0572",
    "#F77F00", "#06D6A0", "#118AB2", "#EF476F", "#FFD166",
    "#8338EC", "#FB5607", "#3A86FF", "#FFBE0B", "#FF006E",
    "#43AA8B", "#90BE6D", "#F94144", "#577590", "#277DA1",
]

# ==============================================================================
# Carregar dados estáticos (executado uma vez na inicialização)
# ==============================================================================

# --- Limite do Rio de Janeiro (via API IBGE — sem dependência extra) ----------
print("Carregando limites do Rio...")
rio_polygon = None
try:
    import json
    from shapely.geometry import shape as shapely_shape, MultiPolygon
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
except Exception as e:
    print(f"ERRO ao carregar limites do Rio: {e}")

# --- Garagens ----------------------------------------------------------------
print("Carregando garagens...")
garagens_polygon = None
try:
    garagens_gdf     = gpd.read_file("garagens/Garagens_de_operadores_SPPO.shp")
    garagens_gdf     = garagens_gdf.to_crs("EPSG:4326")
    garagens_polygon = garagens_gdf.geometry.union_all()
    print("Garagens carregadas.")
except Exception as e:
    print(f"ERRO ao carregar garagens: {e}")

# --- GTFS --------------------------------------------------------------------
print("Carregando GTFS...")
gtfs         = {}
shapes_gtfs  = None
stops_gtfs   = None
linhas_dict  = {}
linhas_short = []

try:
    with zipfile.ZipFile("gtfs/gtfs.zip") as z:
        for name in z.namelist():
            if not name.endswith(".txt"):
                continue
            key = name.replace(".txt", "").split("/")[-1]
            with z.open(name) as f:
                gtfs[key] = pd.read_csv(f, dtype=str)

    # Shapes → GeoDataFrame de LineStrings
    if "shapes" in gtfs:
        df = gtfs["shapes"].copy()
        df["shape_pt_lat"]      = df["shape_pt_lat"].astype(float)
        df["shape_pt_lon"]      = df["shape_pt_lon"].astype(float)
        df["shape_pt_sequence"] = df["shape_pt_sequence"].astype(int)
        lines = (
            df.sort_values("shape_pt_sequence")
            .groupby("shape_id")
            .apply(lambda x: LineString(zip(x["shape_pt_lon"], x["shape_pt_lat"])),
                   include_groups=False)
            .reset_index()
        )
        lines.columns = ["shape_id", "geometry"]
        shapes_gtfs   = gpd.GeoDataFrame(lines, geometry="geometry", crs="EPSG:4326")

    # Stops → GeoDataFrame de pontos
    if "stops" in gtfs:
        df = gtfs["stops"].copy()
        df["stop_lat"] = df["stop_lat"].astype(float)
        df["stop_lon"] = df["stop_lon"].astype(float)
        stops_gtfs = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df["stop_lon"], df["stop_lat"]),
            crs="EPSG:4326",
        )

    # Dicionário de linhas
    if "routes" in gtfs:
        routes = gtfs["routes"]
        if {"route_short_name", "route_long_name"}.issubset(routes.columns):
            linhas_dict  = dict(zip(routes["route_short_name"], routes["route_long_name"]))
            linhas_short = sorted(routes["route_short_name"].dropna().unique().tolist())
            print(f"Linhas GTFS carregadas: {len(linhas_short)}")

    print("GTFS carregado com sucesso.")
except Exception as e:
    print(f"ERRO ao carregar GTFS: {e}")


# ==============================================================================
# Funções auxiliares
# ==============================================================================

def get_linha_cores(linhas_sel):
    """Mapeia cada linha selecionada para uma cor da paleta."""
    return {ln: PALETA_CORES[i % len(PALETA_CORES)] for i, ln in enumerate(linhas_sel or [])}


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


def calcular_bearing_df(df, hist_list, dist_min=20):
    """
    Adiciona coluna 'direcao' ao DataFrame.
    Só atualiza o bearing quando o veículo andou >= dist_min m;
    caso contrário preserva o último bearing registrado.
    """
    df       = df.copy()
    df["direcao"] = float("nan")
    hist_map = {r["ordem"]: r for r in (hist_list or [])}

    for idx, row in df.iterrows():
        ant = hist_map.get(row["ordem"])
        if ant is None:
            continue
        t_atual = pd.to_datetime(row["datahora"])
        t_ant   = pd.to_datetime(ant["datahora"])
        if abs((t_atual - t_ant).total_seconds() / 60) >= 10:
            continue
        dist = haversine(ant["lat"], ant["lng"], row["lat"], row["lng"])
        if dist >= dist_min:
            df.at[idx, "direcao"] = round(
                bearing_between(ant["lat"], ant["lng"], row["lat"], row["lng"]), 0
            )
        else:
            ub = ant.get("ultimo_bearing")
            df.at[idx, "direcao"] = ub if ub is not None else float("nan")

    return df


def atualizar_historico(hist_list, df):
    """Mantém apenas a posição mais recente por veículo no histórico."""
    hist_map = {r["ordem"]: r for r in (hist_list or [])}
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
    from datetime import timezone
    agora  = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
    inicio = agora - timedelta(minutes=5)
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
            except Exception:
                print(f"SPPO body nao e JSON: {resp.text[:200]}")
        print(f"SPPO: {len(sppo_df)} registros brutos")
    except Exception as e:
        print(f"ERRO API SPPO: {e}")

    # BRT
    try:
        resp = session.get("https://dados.mobilidade.rio/gps/brt", timeout=30)
        if resp.status_code == 200:
            veiculos = resp.json().get("veiculos") or []
            if veiculos:
                brt_df = pd.DataFrame(veiculos)
        print(f"BRT: {len(brt_df)} registros brutos")
    except Exception as e:
        print(f"ERRO API BRT: {e}")

    # Processar SPPO
    if len(sppo_df) > 0 and "ordem" in sppo_df.columns:
        try:
            sppo_df["datahora"]   = pd.to_datetime(sppo_df["datahora"].astype(float) / 1000, unit="s") - timedelta(hours=3)
            sppo_df["velocidade"] = pd.to_numeric(sppo_df["velocidade"], errors="coerce")
            sppo_df["longitude"]  = pd.to_numeric(
                sppo_df["longitude"].astype(str).str.replace(",", "."), errors="coerce"
            )
            sppo_df["latitude"]   = pd.to_numeric(
                sppo_df["latitude"].astype(str).str.replace(",", "."), errors="coerce"
            )
            sppo_df = sppo_df[["ordem", "datahora", "latitude", "longitude", "linha", "velocidade"]].copy()
            sppo_df["tipo"]    = "SPPO"
            sppo_df["sentido"] = None
            print(f"SPPO processado: {len(sppo_df)} registros")
        except Exception as e:
            print(f"ERRO processando SPPO: {e}")
            sppo_df = pd.DataFrame()
    else:
        sppo_df = pd.DataFrame()

    # Processar BRT
    if len(brt_df) > 0 and "codigo" in brt_df.columns:
        try:
            brt_df["datahora"]   = pd.to_datetime(brt_df["dataHora"].astype(float) / 1000, unit="s") - timedelta(hours=3)
            brt_df               = brt_df.rename(columns={"codigo": "ordem"})
            brt_df["latitude"]   = pd.to_numeric(brt_df["latitude"],  errors="coerce")
            brt_df["longitude"]  = pd.to_numeric(brt_df["longitude"], errors="coerce")
            brt_df["velocidade"] = pd.to_numeric(brt_df["velocidade"], errors="coerce")
            brt_df = brt_df[["ordem", "datahora", "latitude", "longitude",
                              "linha", "velocidade", "sentido"]].copy()
            brt_df["tipo"] = "BRT"
            print(f"BRT processado: {len(brt_df)} registros")
        except Exception as e:
            print(f"ERRO processando BRT: {e}")
            brt_df = pd.DataFrame()
    else:
        brt_df = pd.DataFrame()

    # Combinar e filtrar
    dados = pd.concat([sppo_df, brt_df], ignore_index=True)
    if len(dados) == 0:
        return pd.DataFrame()

    dados = dados.dropna(subset=["latitude", "longitude"])
    dados = dados.sort_values("datahora", ascending=False).drop_duplicates("ordem")
    dados = dados[dados["datahora"] >= inicio]

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
    print(f"Total após filtros: {len(dados)} registros")
    return dados


# ==============================================================================
# Layout do App
# ==============================================================================

app    = dash.Dash(
    __name__,
    title="GPS BRT-SPPO - SMTR/RJ",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # expõe o servidor Flask para deploy (gunicorn)

app.layout = html.Div(
    [
        dcc.Interval(id="intervalo", interval=30_000, n_intervals=0),
        dcc.Store(id="store-hist-sppo", data=[]),
        dcc.Store(id="store-hist-brt",  data=[]),
        dcc.Store(id="store-gps",       data=None),
        dcc.Store(id="store-localizacao", data=None),

        # Cabeçalho
        html.Div(
            html.H4("GPS BRT-SPPO - SMTR/RJ",
                    style={"margin": 0, "fontSize": "18px", "fontWeight": "bold"}),
            style={
                "padding": "8px 16px", "backgroundColor": "#343a40",
                "color": "white", "display": "flex", "alignItems": "center",
            },
        ),

        # Controles
        html.Div(
            [
                # Seleção de linha — wrapper com z-index alto para o menu ficar sobre os botões do mapa
                html.Div(
                    [
                        html.Label("Linhas:", style={"fontWeight": "bold", "marginBottom": "4px",
                                                      "textAlign": "center"}),
                        html.Div(
                            dcc.Dropdown(
                                id="dropdown-linhas",
                                options=[{"label": ln, "value": ln} for ln in linhas_short],
                                multi=True,
                                placeholder="Selecione uma ou mais linhas...",
                                style={"width": "min(420px, 90vw)"},
                            ),
                            style={"position": "relative", "zIndex": 9999},
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
                            style={
                                "backgroundColor": "#0d6efd", "color": "white",
                                "border": "none", "padding": "8px 16px",
                                "borderRadius": "4px", "cursor": "pointer",
                            },
                        ),
                        html.P(
                            "Atualização a cada 30s",
                            style={"color": "#6c757d", "fontSize": "12px", "margin": "0 0 0 10px"},
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center", "justifyContent": "center",
                           "flexWrap": "wrap", "gap": "6px"},
                ),
            ],
            style={
                "padding": "10px 16px", "backgroundColor": "#f8f9fa",
                "borderBottom": "1px solid #dee2e6",
                "display": "flex", "flexDirection": "column",
                "alignItems": "center", "gap": "10px",
            },
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
                        style={
                            "width": "34px", "height": "34px",
                            "backgroundColor": "white", "border": "2px solid rgba(0,0,0,0.3)",
                            "borderRadius": "4px", "cursor": "pointer",
                            "fontSize": "16px", "lineHeight": "1",
                            "boxShadow": "none", "padding": "0",
                            "display": "flex", "alignItems": "center", "justifyContent": "center",
                        },
                    ),
                    style={
                        "position": "absolute", "top": "126px", "right": "10px",
                        "zIndex": 1000,
                    },
                ),
                html.Div(
                    id="legenda",
                    style={
                        "position": "absolute", "bottom": "30px", "left": "10px",
                        "zIndex": 1000, "pointerEvents": "none",
                    },
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
    Output("store-gps",       "data"),
    Output("store-hist-sppo", "data"),
    Output("store-hist-brt",  "data"),
    Input("intervalo",        "n_intervals"),
    Input("btn-atualizar",    "n_clicks"),
    State("store-hist-sppo",  "data"),
    State("store-hist-brt",   "data"),
    prevent_initial_call=False,
)
def atualizar_gps(_n_int, _n_btn, hist_sppo, hist_brt):
    """Busca GPS, calcula bearings e atualiza os stores."""
    dados = fetch_gps_data()
    if len(dados) == 0:
        return None, hist_sppo or [], hist_brt or []

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
    return dados_final.to_dict("records"), hist_sppo, hist_brt


@app.callback(
    Output("layer-itinerarios", "children"),
    Output("layer-paradas",     "children"),
    Output("layer-onibus",      "children"),
    Output("layer-brt",         "children"),
    Output("legenda",           "children"),
    Input("store-gps",          "data"),
    Input("dropdown-linhas",    "value"),
    prevent_initial_call=False,
)
def atualizar_mapa(gps_data, linhas_sel):
    """Reconstrói as camadas do mapa e a legenda."""
    linhas_sel = linhas_sel or []
    cores      = get_linha_cores(linhas_sel)

    # --- Legenda --------------------------------------------------------------
    estilo_caixa = {
        "background": "white", "padding": "10px 14px",
        "borderRadius": "4px", "boxShadow": "0 1px 5px rgba(0,0,0,.4)",
        "font": "12px/1.5 Arial,sans-serif",
    }

    # Mini-legenda de ícones (sempre presente)
    icone_seta_svg = (
        "data:image/svg+xml;charset=utf-8,"
        + urllib.parse.quote(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 28 28">'
            '<polygon points="14,2 24,24 14,18 4,24" fill="#888" stroke="black" stroke-width="2"/>'
            "</svg>"
        )
    )
    icone_circulo_svg = (
        "data:image/svg+xml;charset=utf-8,"
        + urllib.parse.quote(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 28 28">'
            '<circle cx="14" cy="14" r="10" fill="#888" stroke="black" stroke-width="2.5"/>'
            '<circle cx="14" cy="14" r="4" fill="white"/>'
            "</svg>"
        )
    )
    secao_icones = html.Div(
        [
            html.B("Ícones", style={"display": "block", "marginBottom": "5px", "fontSize": "13px"}),
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
                    html.Span("Sem direção / parado", style={"fontSize": "11px"}),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "7px"},
            ),
        ],
        style={"marginTop": "10px", "paddingTop": "8px", "borderTop": "1px solid #dee2e6"},
    )

    if not linhas_sel:
        legenda = html.Div(
            [
                html.B("Linhas no mapa",
                       style={"display": "block", "marginBottom": "4px", "fontSize": "13px"}),
                html.Span("Nenhuma linha selecionada",
                          style={"color": "#888", "fontStyle": "italic"}),
                secao_icones,
            ],
            style={**estilo_caixa, "minWidth": "180px"},
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
                html.B("Linhas no mapa",
                       style={"display": "block", "marginBottom": "6px", "fontSize": "13px"}),
                *itens,
                secao_icones,
            ],
            style={**estilo_caixa, "minWidth": "180px", "maxWidth": "260px",
                   "maxHeight": "40vh", "overflowY": "auto"},
        )

    if not gps_data:
        return [], [], [], [], legenda

    dados   = pd.DataFrame(gps_data)
    if linhas_sel:
        dados = dados[dados["linha"].isin(linhas_sel)]
    else:
        # Nenhuma linha selecionada — não renderiza veículos para não sobrecarregar o mapa
        return [], [], [], [], legenda

    sppo_df = dados[dados["tipo"] == "SPPO"].copy() if len(dados) > 0 else pd.DataFrame()
    brt_df  = dados[dados["tipo"] == "BRT"].copy()  if len(dados) > 0 else pd.DataFrame()

    # --- Itinerários ----------------------------------------------------------
    shapes_layers = []
    if linhas_sel and shapes_gtfs is not None and "routes" in gtfs and "trips" in gtfs:
        try:
            rotas = gtfs["routes"][gtfs["routes"]["route_short_name"].isin(linhas_sel)]
            trips = (
                gtfs["trips"][gtfs["trips"]["route_id"].isin(rotas["route_id"])]
                .merge(rotas[["route_id", "route_short_name"]], on="route_id")
            )
            for linha_id in linhas_sel:
                cor     = cores.get(linha_id, "#888888")
                shp_ids = trips[trips["route_short_name"] == linha_id]["shape_id"].unique()
                sh      = shapes_gtfs[shapes_gtfs["shape_id"].isin(shp_ids)]
                for _, row in sh.iterrows():
                    coords = [[pt[1], pt[0]] for pt in row.geometry.coords]
                    shapes_layers.append(
                        dl.Polyline(positions=coords, color=cor, weight=4,
                                    children=dl.Tooltip(linha_id))
                    )
        except Exception as e:
            print(f"ERRO shapes: {e}")

    # --- Paradas --------------------------------------------------------------
    paradas_layers = []
    if (linhas_sel and stops_gtfs is not None
            and all(k in gtfs for k in ["routes", "trips", "stop_times"])):
        try:
            rotas    = gtfs["routes"][gtfs["routes"]["route_short_name"].isin(linhas_sel)]
            trips    = gtfs["trips"][gtfs["trips"]["route_id"].isin(rotas["route_id"])]
            stop_ids = (
                gtfs["stop_times"][gtfs["stop_times"]["trip_id"].isin(trips["trip_id"])]
                ["stop_id"].unique()
            )
            stops_f = stops_gtfs[stops_gtfs["stop_id"].isin(stop_ids)]
            for _, row in stops_f.iterrows():
                paradas_layers.append(
                    dl.CircleMarker(
                        center=[float(row["stop_lat"]), float(row["stop_lon"])],
                        radius=5, color="darkred",
                        fillColor="red", fillOpacity=0.8,
                        children=dl.Popup(str(row.get("stop_name", ""))),
                    )
                )
        except Exception as e:
            print(f"ERRO paradas: {e}")

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
    for _, row in sppo_df.iterrows():
        cor = cores.get(row.get("linha", ""), "#1a6faf") if linhas_sel else "#1a6faf"
        try:
            bearing = float(row.get("direcao", float("nan")))
        except Exception:
            bearing = float("nan")
        onibus_layers.append(
            dl.Marker(
                position=[float(row["lat"]), float(row["lng"])],
                icon=dict(zip(["iconUrl","iconSize","iconAnchor"], make_vehicle_icon(bearing, cor))),
                children=_popup(row),
            )
        )

    # --- BRT ------------------------------------------------------------------
    brt_layers = []
    for _, row in brt_df.iterrows():
        cor = cores.get(row.get("linha", ""), "#e67e00") if linhas_sel else "#e67e00"
        try:
            bearing = float(row.get("direcao", float("nan")))
        except Exception:
            bearing = float("nan")
        brt_layers.append(
            dl.Marker(
                position=[float(row["lat"]), float(row["lng"])],
                icon=dict(zip(["iconUrl","iconSize","iconAnchor"], make_vehicle_icon(bearing, cor))),
                children=_popup(row, extra=f"Sentido: {row.get('sentido', '')}"),
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

    icone_usuario = (
        "data:image/svg+xml;charset=utf-8,"
        + urllib.parse.quote(
            '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">'
            '<circle cx="11" cy="11" r="9" fill="#0d6efd" stroke="white" stroke-width="2.5"/>'
            '<circle cx="11" cy="11" r="3" fill="white"/>'
            '</svg>'
        )
    )
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
    app.run(debug=False, host="0.0.0.0", port=8050)