import dash_leaflet as dl
from dash import dcc, html


APP_INDEX_STRING = """
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

            .leaflet-container:focus {
                outline: none !important;
            }

            .itinerario-polyline:focus,
            .itinerario-polyline:active {
                outline: none !important;
                box-shadow: none !important;
            }

            .tabs-filtro-parent {
                width: 100%;
            }

            .tabs-filtro-container {
                display: flex !important;
                flex-wrap: nowrap !important;
                width: 100%;
            }

            .tabs-filtro-item {
                display: inline-flex !important;
                align-items: center !important;
                justify-content: center !important;
                flex: 1 1 50% !important;
                width: 50% !important;
                max-width: 50% !important;
                white-space: nowrap;
            }

            @media (max-width: 768px) {
                .tabs-filtro-item {
                    font-size: 11px !important;
                    padding: 4px 6px !important;
                    min-height: 30px !important;
                    line-height: 18px !important;
                }
            }

            ._dash-loading,
            ._dash-loading-callback {
                display: none !important;
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

                function patchLeafletMapCapture() {
                    if (!window.L || !window.L.Map || window.__gps_map_capture_patched) return;
                    var originalInit = window.L.Map.prototype.initialize;
                    window.L.Map.prototype.initialize = function () {
                        var out = originalInit.apply(this, arguments);
                        window.__gps_leaflet_map = this;
                        return out;
                    };
                    window.__gps_map_capture_patched = true;
                }

                patchLeafletMapCapture();
                var patchTry = 0;
                var patchTimer = setInterval(function () {
                    patchTry += 1;
                    patchLeafletMapCapture();
                    if (window.__gps_map_capture_patched || patchTry > 120) {
                        clearInterval(patchTimer);
                    }
                }, 100);
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


def build_app_layout(estilos, linhas_short, linha_exibicao, app_build_id):
    return html.Div(
        [
            dcc.Interval(id="intervalo", interval=45_000, n_intervals=0),
            dcc.Interval(id="intervalo-linhas-debounce", interval=500, n_intervals=0, disabled=True),
            dcc.Interval(id="intervalo-veiculos-recenter", interval=300, n_intervals=0, disabled=True),
            dcc.Store(id="store-hist-sppo", data={}),
            dcc.Store(id="store-hist-brt", data={}),
            dcc.Store(id="store-build-id", data=app_build_id),
            dcc.Store(id="store-build-sync", data=None),
            dcc.Store(id="store-force-map-view", data=None),
            dcc.Store(id="store-force-map-view-ack", data=None),
            dcc.Store(id="store-tab-filtro", data="linhas"),
            dcc.Store(id="store-linhas-debounce", data=[]),
            dcc.Store(id="store-veiculos-debounce", data=[]),
            dcc.Store(id="store-veiculos-recenter-token", data=0),
            dcc.Store(id="store-veiculos-opcoes", data=[]),
            dcc.Store(id="store-gps-ts", data=0),
            dcc.Store(id="store-localizacao", data=None),
            html.Div(
                html.H4("🚍 Consulta de ônibus - Rio de Janeiro 🚍", style=estilos["header_titulo"]),
                style=estilos["header"],
            ),
            html.Div(
                [
                    html.Div(
                        [
                            dcc.Tabs(
                                id="tabs-filtro",
                                value="linhas",
                                mobile_breakpoint=0,
                                parent_className="tabs-filtro-parent",
                                className="tabs-filtro-container",
                                style={"height": "32px", "width": "100%", "display": "flex", "flexWrap": "nowrap"},
                                children=[
                                    dcc.Tab(
                                        label="Linhas",
                                        value="linhas",
                                        className="tabs-filtro-item",
                                        selected_className="tabs-filtro-item tabs-filtro-item--selected",
                                        style={"display": "inline-flex", "flex": "1 1 50%", "justifyContent": "center", "alignItems": "center", "padding": "4px 12px", "height": "32px", "lineHeight": "20px", "fontSize": "12px"},
                                        selected_style={"display": "inline-flex", "flex": "1 1 50%", "justifyContent": "center", "alignItems": "center", "padding": "4px 12px", "height": "32px", "lineHeight": "20px", "fontSize": "12px", "fontWeight": "700"},
                                        children=html.Div(
                                            [
                                                html.Label("Linhas:", style=estilos["label"]),
                                                html.Div(
                                                    dcc.Dropdown(
                                                        id="dropdown-linhas",
                                                        options=[{"label": linha_exibicao(ln), "value": ln} for ln in linhas_short],
                                                        multi=True,
                                                        placeholder="Selecione uma ou mais linhas...",
                                                        style=estilos["dropdown"],
                                                    ),
                                                    style=estilos["dropdown_wrapper"],
                                                ),
                                            ],
                                            style={"paddingTop": "4px", "display": "flex", "flexDirection": "column", "alignItems": "center", "width": "100%"},
                                        ),
                                    ),
                                    dcc.Tab(
                                        label="Veículos",
                                        value="veiculos",
                                        className="tabs-filtro-item",
                                        selected_className="tabs-filtro-item tabs-filtro-item--selected",
                                        style={"display": "inline-flex", "flex": "1 1 50%", "justifyContent": "center", "alignItems": "center", "padding": "4px 12px", "height": "32px", "lineHeight": "20px", "fontSize": "12px"},
                                        selected_style={"display": "inline-flex", "flex": "1 1 50%", "justifyContent": "center", "alignItems": "center", "padding": "4px 12px", "height": "32px", "lineHeight": "20px", "fontSize": "12px", "fontWeight": "700"},
                                        children=html.Div(
                                            [
                                                html.Label("Veículos:", style=estilos["label"]),
                                                html.Div(
                                                    dcc.Dropdown(
                                                        id="dropdown-veiculos",
                                                        options=[],
                                                        multi=True,
                                                        placeholder="Selecione um ou mais veículos...",
                                                        style=estilos["dropdown"],
                                                    ),
                                                    style=estilos["dropdown_wrapper"],
                                                ),
                                            ],
                                            style={"paddingTop": "4px", "display": "flex", "flexDirection": "column", "alignItems": "center", "width": "100%"},
                                        ),
                                    ),
                                ],
                            ),
                            html.Div(id="texto-ajuda-tab", style={"fontSize": "11px", "color": "#5a6573", "textAlign": "center", "marginTop": "2px"}),
                        ],
                        style={"display": "flex", "flexDirection": "column", "alignItems": "center", "width": "min(460px, 94vw)"},
                    ),
                    html.Div(
                        [
                            html.Button("Atualizar 🔄️", id="btn-atualizar", n_clicks=0, style=estilos["botao_atualizar"]),
                            html.P("Última atualização:", style=estilos["texto_atualizacao"]),
                            html.Span(id="span-update-icon", style={"marginLeft": "8px", "fontSize": "14px"}, children=""),
                            html.Span(id="span-update-time", style={"marginLeft": "12px", "fontSize": "12px", "color": "#6c757d"}, children=""),
                        ],
                        style={"display": "flex", "alignItems": "center", "justifyContent": "center", "flexWrap": "wrap", "gap": "6px", "width": "min(460px, 94vw)", "margin": "0 auto", "textAlign": "center"},
                    ),
                ],
                style=estilos["controles"],
            ),
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
                                        dl.TileLayer(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attribution="© OpenStreetMap contributors"),
                                        name="OSM",
                                        checked=False,
                                    ),
                                    dl.BaseLayer(
                                        dl.TileLayer(url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", attribution="Esri"),
                                        name="ESRI Padrão",
                                        checked=True,
                                    ),
                                    dl.BaseLayer(
                                        dl.TileLayer(url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", attribution="Esri"),
                                        name="ESRI P&B",
                                        checked=False,
                                    ),
                                    dl.Overlay(dl.LayerGroup(id="layer-itinerarios"), name="Itinerários", checked=True),
                                    dl.Overlay(dl.LayerGroup(id="layer-paradas"), name="Paradas", checked=False),
                                    dl.Overlay(dl.LayerGroup(id="layer-onibus"), name="Ônibus", checked=True),
                                    dl.Overlay(dl.LayerGroup(id="layer-brt"), name="BRT", checked=True),
                                    dl.Overlay(dl.LayerGroup(id="layer-localizacao"), name="Minha posição", checked=True),
                                ],
                                position="topright",
                            ),
                        ],
                    ),
                    html.Div(
                        html.Button("📍", id="btn-localizar", n_clicks=0, title="Ir para minha localização", style=estilos["botao_localizacao"]),
                        style=estilos["botao_localizacao_container"],
                    ),
                    html.Div(id="legenda", style=estilos["legenda_container"]),
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
