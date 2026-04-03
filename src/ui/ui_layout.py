import dash_leaflet as dl
from dash import dcc, html
from urllib.parse import quote


APP_INDEX_STRING = """
<!DOCTYPE html>
<html lang="pt-BR">
    <head>
        <meta charset="utf-8">
        {%metas%}
        <title>{%title%}</title>
        <meta name="description" content="Acompanhe ônibus em tempo real no Rio de Janeiro com mapa interativo, dados GPS e linhas SPPO e BRT.">
        <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
        <meta name="author" content="RioB.us">
        <meta property="og:site_name" content="RioB.us">
        <meta property="og:locale" content="pt_BR">
        <meta property="og:type" content="website">
        <meta property="og:title" content="RioB.us | Ônibus em tempo real no Rio de Janeiro">
        <meta property="og:description" content="Mapa em tempo real com ônibus SPPO e BRT no Rio de Janeiro, filtros por linha e monitoramento operacional.">
        <meta property="og:image" content="https://riob.us/assets/screenshot-wide.png">
        <meta id="og-url" property="og:url" content="https://riob.us/">
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="RioB.us | Ônibus em tempo real no Rio de Janeiro">
        <meta name="twitter:description" content="Veja posições de ônibus SPPO e BRT no mapa em tempo real.">
        <meta name="twitter:image" content="https://riob.us/assets/screenshot-wide.png">
        <link id="canonical-link" rel="canonical" href="https://riob.us/">
        <link
            rel="stylesheet"
            href="https://cdn.jsdelivr.net/npm/daisyui@latest"
        >
        <link rel="manifest" href="/assets/manifest.json">
        <meta name="theme-color" content="#1f2a37">
          <meta name="apple-mobile-web-app-capable" content="yes">
          <meta name="apple-mobile-web-app-status-bar-style"
              content="default">
          <meta name="apple-mobile-web-app-title" content="Ônibus RJ">
          <link rel="apple-touch-icon" href="/assets/icon-192.png">
        {%favicon%}
        {%css%}
                <script type="application/ld+json">
                        {
                            "@context": "https://schema.org",
                            "@type": "WebApplication",
                            "name": "RioB.us",
                            "description": "Acompanhamento operacional de ônibus em tempo real no Rio de Janeiro.",
                            "url": "https://riob.us/",
                            "applicationCategory": "TravelApplication",
                            "operatingSystem": "Web",
                            "offers": {
                                "@type": "Offer",
                                "price": "0",
                                "priceCurrency": "BRL"
                            }
                        }
                </script>
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

            body[data-theme="dark-riob"] {
                background: linear-gradient(165deg, #0f1726 0%, #111d31 100%);
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

            body[data-theme="dark-riob"] #boot-loader {
                background: linear-gradient(165deg, #0f1726 0%, #111d31 100%);
            }

            #boot-loader.hide {
                opacity: 0;
                visibility: hidden;
                pointer-events: none;
            }

            .boot-card {
                min-width: 250px;
                padding: 18px 22px;
                border-radius: 16px;
                background: rgba(255, 255, 255, 0.78);
                border: 1px solid rgba(255, 255, 255, 0.82);
                box-shadow: 0 22px 46px rgba(31, 42, 55, 0.18);
                backdrop-filter: blur(16px);
                text-align: center;
                font-family: 'Segoe UI', sans-serif;
                color: #1f2a37;
            }

            body[data-theme="dark-riob"] .boot-card {
                background: rgba(17, 31, 51, 0.92);
                border-color: rgba(93, 132, 189, 0.3);
                box-shadow: 0 22px 46px rgba(2, 8, 20, 0.55);
                color: #dce8fa;
            }

            .boot-title {
                margin: 0 0 10px 0;
                font-size: 15px;
                font-weight: 700;
            }

            .boot-subtitle {
                margin: 8px 0 0 0;
                font-size: 12px;
                color: #4d5f73;
            }

            body[data-theme="dark-riob"] .boot-subtitle {
                color: #a4b8d4;
            }

            .boot-spinner {
                width: 36px;
                height: 36px;
                margin: 0 auto;
                border-radius: 50%;
                border: 3px solid #c7d7ec;
                border-top-color: #176edc;
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

                .leaflet-tooltip {
                    display: none !important;
                }

                .leaflet-popup {
                    max-width: 220px !important;
                }

                .leaflet-popup-content-wrapper {
                    max-width: 220px !important;
                    border-radius: 10px !important;
                }

                .leaflet-popup-content {
                    margin: 8px 10px !important;
                    max-width: 200px !important;
                    font-size: 11px !important;
                    line-height: 1.35 !important;
                    word-break: break-word;
                    overflow-wrap: anywhere;
                }

                .leaflet-popup-content p {
                    margin: 2px 0 !important;
                    font-size: 11px !important;
                    line-height: 1.3 !important;
                }
            }

            ._dash-loading,
            ._dash-loading-callback {
                display: none !important;
            }

            .error-banner {
                border: none;
                border-bottom: 1px solid color-mix(in oklab, oklch(79% 0.16 78) 35%, white);
                background: color-mix(in oklab, oklch(79% 0.16 78) 16%, white);
                color: color-mix(in oklab, oklch(31% 0.06 52) 90%, oklch(26% 0.028 246));
                padding: 7px 12px;
                font-size: 12px;
                text-align: center;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 6px;
            }
        </style>
    </head>
    <body data-theme="riob">
        <script>
            (function () {
                var mode = null;
                try {
                    mode = window.localStorage.getItem('riobus_theme_mode');
                } catch (e) {
                    mode = null;
                }

                if (mode !== 'light' && mode !== 'dark') {
                    var prefersDark = false;
                    if (window.matchMedia) {
                        prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                    }
                    mode = prefersDark ? 'dark' : 'light';
                    try {
                        window.localStorage.setItem('riobus_theme_mode', mode);
                    } catch (e) {
                        // sem-op
                    }
                }

                var themeName = mode === 'dark' ? 'dark-riob' : 'riob';
                document.body.setAttribute('data-theme', themeName);

                var metaThemeColor = document.querySelector('meta[name="theme-color"]');
                if (metaThemeColor) {
                    metaThemeColor.setAttribute('content', mode === 'dark' ? '#0f1726' : '#1f2a37');
                }
            })();
        </script>
        <div id="boot-loader" aria-live="polite"
             aria-label="Carregando aplicação">
            <div class="boot-card">
                <p class="boot-title">
                    Consulta de ônibus - Rio de Janeiro
                </p>
                <div class="boot-spinner"></div>
                <p class="boot-subtitle">Carregando mapa e dados...</p>
            </div>
        </div>
        <noscript>
            <main style="padding:16px;font-family:Segoe UI,Arial,sans-serif;line-height:1.45;">
                <h1 style="margin:0 0 8px 0;font-size:20px;">RioB.us - Ônibus em tempo real no Rio de Janeiro</h1>
                <p style="margin:0 0 8px 0;">
                    O RioB.us permite acompanhar linhas e veículos SPPO e BRT em mapa interativo,
                    com atualização operacional frequente.
                </p>
                <p style="margin:0;">
                    Ative o JavaScript para carregar o mapa e os filtros da aplicação.
                </p>
            </main>
        </noscript>
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
                    var l = window.L;
                    if (!l || !l.Map || window.__gps_map_capture_patched) {
                        return;
                    }
                    var originalInit = l.Map.prototype.initialize;
                    l.Map.prototype.initialize = function () {
                        var out = originalInit.apply(this, arguments);
                        window.__gps_leaflet_map = this;
                        return out;
                    };
                    window.__gps_map_capture_patched = true;
                }

                function isMobileDevice() {
                    var smallViewport = false;
                    var coarseNoHover = false;
                    try {
                        if (window.matchMedia) {
                            smallViewport = window.matchMedia(
                                '(max-width: 768px)'
                            ).matches;
                            coarseNoHover = (
                                window.matchMedia('(pointer: coarse)').matches &&
                                window.matchMedia('(hover: none)').matches
                            );
                        }
                    } catch (e) {
                        // sem-op
                    }
                    var touchPoints = Number(
                        navigator.maxTouchPoints || 0
                    );
                    return smallViewport || (coarseNoHover && touchPoints > 0);
                }

                function configureMobileMapBehavior() {
                    var map = window.__gps_leaflet_map || null;
                    if (!map || map.__gps_mobile_behavior_bound) {
                        return;
                    }

                    if (!isMobileDevice()) {
                        return;
                    }

                    try {
                        var l = window.L;
                        if (l && l.Popup && l.Popup.prototype &&
                                l.Popup.prototype.options) {
                            l.Popup.prototype.options.autoPan = false;
                            l.Popup.prototype.options.keepInView = false;
                        }
                    } catch (e) {
                        // sem-op
                    }

                    map.__gps_mobile_behavior_bound = true;
                    map.__gps_last_open_popup = null;

                    map.on('tooltipopen', function (evt) {
                        try {
                            if (evt && evt.tooltip && map.closeTooltip) {
                                map.closeTooltip(evt.tooltip);
                            }
                        } catch (e) {
                            // sem-op
                        }
                    });

                    map.on('popupopen', function (evt) {
                        try {
                            var popup = evt ? evt.popup : null;
                            var prev = map.__gps_last_open_popup;

                            if (prev && popup && prev !== popup) {
                                map.closePopup(prev);
                            }

                            map.__gps_last_open_popup = popup || null;
                        } catch (e) {
                            // sem-op
                        }
                    });

                    map.on('popupclose', function (evt) {
                        try {
                            var popup = evt ? evt.popup : null;
                            if (map.__gps_last_open_popup === popup) {
                                map.__gps_last_open_popup = null;
                            }
                        } catch (e) {
                            // sem-op
                        }
                    });
                }

                patchLeafletMapCapture();
                var patchTry = 0;
                var patchTimer = setInterval(function () {
                    patchTry += 1;
                    patchLeafletMapCapture();
                    configureMobileMapBehavior();
                    var map = window.__gps_leaflet_map || null;
                    var mobileReady = (
                        !isMobileDevice() ||
                        (map && map.__gps_mobile_behavior_bound)
                    );
                    if ((window.__gps_map_capture_patched && mobileReady) ||
                            patchTry > 120) {
                        clearInterval(patchTimer);
                    }
                }, 100);

                configureMobileMapBehavior();

                if (
                    location.hostname === 'localhost' ||
                    location.hostname === '127.0.0.1'
                ) {
                    try {
                        if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
                            navigator.serviceWorker.getRegistrations().then(function (regs) {
                                regs.forEach(function (reg) {
                                    reg.unregister();
                                });
                            });
                        }
                        if (window.caches && window.caches.keys) {
                            window.caches.keys().then(function (keys) {
                                keys.forEach(function (key) {
                                    window.caches.delete(key);
                                });
                            });
                        }
                    } catch (e) {
                        // sem-op
                    }
                }
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


def build_app_layout(linhas_short, linha_exibicao, app_build_id):
    sw_build_id = quote(str(app_build_id or "dev"), safe="")
    sw_script_url = f"/assets/sw.js?v={sw_build_id}"
    app_build_text = str(app_build_id or "dev").strip()
    if len(app_build_text) > 12:
        app_build_label = f"versão: {app_build_text[:7]}"
    else:
        app_build_label = f"versão: {app_build_text}"

    dropdown_opts = [
        {"label": linha_exibicao(ln), "value": ln}
        for ln in linhas_short
    ]
    line_placeholder = "Selecione uma ou mais linhas..."
    vehicle_placeholder = "Selecione um ou mais veículos..."

    def _build_filter_dropdown(
        dropdown_id,
        options,
        placeholder,
        persistence_key=None,
    ):
        return html.Div(
            dcc.Dropdown(
                id=dropdown_id,
                options=options,
                multi=True,
                placeholder=placeholder,
                className="dropdown",
                persistence=persistence_key,
                persistence_type="local",
                persisted_props=["value"],
            ),
            className="dropdown-wrapper",
        )

    def _build_filter_tab(
        label,
        value,
        dropdown_id,
        options,
        placeholder,
        persistence_key=None,
    ):
        return dcc.Tab(
            label=label,
            value=value,
            className="tabs-filtro-item",
            selected_className=(
                "tabs-filtro-item "
                "tabs-filtro-item--selected"
            ),
            children=html.Div(
                [
                    _build_filter_dropdown(
                        dropdown_id=dropdown_id,
                        options=options,
                        placeholder=placeholder,
                        persistence_key=persistence_key,
                    ),
                ],
                className="tabs-panel-content",
            ),
        )

    app_layout = html.Div(
        [
            dcc.Location(id="url-router", refresh=False),
            dcc.Interval(id="intervalo", interval=45_000, n_intervals=0),
            dcc.Interval(
                id="intervalo-linhas-debounce",
                interval=500,
                n_intervals=0,
                disabled=True
            ),
            dcc.Interval(
                id="intervalo-veiculos-recenter",
                interval=300,
                n_intervals=0,
                disabled=True
            ),
            dcc.Interval(
                id="intervalo-linhas-recenter",
                interval=350,
                n_intervals=0,
                disabled=True
            ),
            dcc.Store(id="store-hist-sppo", data={}),
            dcc.Store(id="store-hist-brt", data={}),
            dcc.Store(id="store-build-id", data=app_build_id),
            dcc.Store(id="store-build-sync", data=None),
            dcc.Store(id="store-theme-mode", data=None),
            dcc.Store(id="store-theme-dom-sync", data=None),

            dcc.Store(id="store-force-map-view", data=None),
            dcc.Store(id="store-force-map-view-ack", data=None),
            dcc.Store(id="store-tab-filtro", data="linhas"),
            dcc.Store(id="store-linhas-debounce", data=[]),
            dcc.Store(id="store-linhas-recenter-token", data=0),
            dcc.Store(id="store-veiculos-debounce", data=[]),
            dcc.Store(id="store-veiculos-recenter-token", data=0),
            dcc.Store(id="store-veiculos-opcoes", data=[]),
            dcc.Store(id="store-gps-ts", data=0),
            dcc.Store(id="store-localizacao", data=None),
            dcc.Store(id="store-fetch-error", data=None),
            dcc.Store(id="store-session-warning", data=None),
            dcc.Store(id="store-zoom-atual", data=11),
            html.Div(id="error-banner-container", className="shell-banner"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span("🚍", className="header-icon"),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.H1(
                                                        "RioB.us",
                                                        className="header-titulo"
                                                    ),
                                                    html.Span(
                                                        app_build_label,
                                                        className="header-build-badge",
                                                        title=f"Build ID: {app_build_text}",
                                                    ),
                                                ],
                                                className="header-title-row"
                                            ),
                                            html.P(
                                                "Consulta em tempo real dos ônibus",
                                                className="header-subtitulo"
                                            ),
                                        ],
                                        className="header-copy"
                                    ),
                                ],
                                className="header-brand"
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "🌙",
                                        id="btn-toggle-theme",
                                        n_clicks=0,
                                        className="btn-theme-toggle",
                                        title="Alternar para tema escuro",
                                        **{"aria-label": "Alternar tema"},
                                    ),
                                ],
                                className="header-actions"
                            ),
                        ],
                        className="navbar shell-navbar"
                    ),
                ],
                className="header",
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
                                children=[
                                    _build_filter_tab(
                                        label="Linhas",
                                        value="linhas",
                                        dropdown_id="dropdown-linhas",
                                        options=dropdown_opts,
                                        placeholder=line_placeholder,
                                        persistence_key=(
                                            f"linhas::{app_build_id}"
                                        ),
                                    ),
                                    _build_filter_tab(
                                        label="Veículos",
                                        value="veiculos",
                                        dropdown_id="dropdown-veiculos",
                                        options=[],
                                        placeholder=vehicle_placeholder,
                                    ),
                                ],
                            ),
                        ],
                        className="card card-border card-compact controls-card"
                    ),
                    html.Div(
                        [
                            html.Button(
                                [
                                    html.Span("Atualizar"),
                                    html.Span(
                                        "⟳",
                                        className="refresh-button-icon"
                                    ),
                                ],
                                id="btn-atualizar",
                                n_clicks=0, className="botao-atualizar"
                            ),
                            html.Div(
                                [
                                    html.Span(
                                        [
                                            html.Span(
                                                "Última atualização",
                                                className="update-label-full"
                                            ),
                                            html.Span(
                                                "Atualizado",
                                                className="update-label-short"
                                            ),
                                        ],
                                        className="texto-atualizacao"
                                    ),
                                    html.Span(
                                        id="span-update-time",
                                        className="update-time-value",
                                        children="--"
                                    ),
                                    html.Span(
                                        id="span-update-icon",
                                        className="update-time-icon",
                                        children=""
                                    ),
                                ],
                                className="update-status-chip"
                            ),
                        ],
                        className="card card-border card-compact toolbar-card"
                    ),
                ],
                className="controles",
            ),
            html.Div(
                [
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
                                                    url=(
                                                        "https://{s}.tile"
                                                        ".openstreetmap.org"
                                                        "/{z}/{x}/{y}.png"
                                                    ),
                                                    attribution=(
                                                        "© OpenStreetMap contributors"
                                                    )
                                                ),
                                                name="OSM",
                                                checked=False,
                                            ),
                                            dl.BaseLayer(
                                                dl.TileLayer(
                                                    url=(
                                                        "https://cartodb-basemaps-{s}"
                                                        ".global.ssl.fastly.net"
                                                        "/light_all/{z}/{x}/{y}.png"
                                                    ),
                                                    attribution="© CartoDB contributors"
                                                ),
                                                name="Carto Claro",
                                                checked=True,
                                            ),
                                            dl.BaseLayer(
                                                dl.TileLayer(
                                                    url=(
                                                        "https://cartodb-basemaps-{s}"
                                                        ".global.ssl.fastly.net"
                                                        "/dark_all/{z}/{x}/{y}.png"
                                                    ),
                                                    attribution="© CartoDB contributors"
                                                ),
                                                name="Carto Escuro",
                                                checked=False,
                                            ),
                                            dl.Overlay(
                                                dl.LayerGroup(id="layer-itinerarios"),
                                                name="Itinerários", checked=True
                                            ),
                                            dl.Overlay(
                                                dl.LayerGroup(id="layer-paradas"),
                                                name="Paradas", checked=False
                                            ),
                                            dl.Overlay(
                                                dl.LayerGroup(id="layer-onibus"),
                                                name="Ônibus", checked=True
                                            ),
                                            dl.Overlay(
                                                dl.LayerGroup(id="layer-brt"),
                                                name="BRT", checked=True
                                            ),
                                            dl.Overlay(
                                                dl.LayerGroup(id="layer-localizacao"),
                                                name="Minha posição", checked=True
                                            ),
                                        ],
                                        position="topright",
                                    ),
                                ],
                            ),
                        ],
                        className="card card-border map-frame",
                        style={"flex": "1 1 auto", "minHeight": 0},
                    ),
                    html.Div(
                        html.Button(
                            "📍", id="btn-localizar", n_clicks=0,
                            title="Ir para minha localização",
                            className="botao-localizacao",
                            **{"aria-label": "Ir para minha localização"}
                        ),
                        className="botao-localizacao-container",
                    ),
                    html.Div(
                        html.Button(
                            "Instalar app",
                            id="btn-instalar-pwa",
                            n_clicks=0,
                            title="Instalar aplicativo",
                            className="botao-instalar",
                            style={"display": "none"},
                            **{"aria-label": "Instalar aplicativo"}
                        ),
                        className="botao-instalar-container",
                    ),
                    html.Div(
                        id="legenda", className="legenda-container",
                        role="complementary",
                        **{"aria-label": "Legenda do mapa"}
                    ),
                ],

                style={
                    "position": "relative", "flex": "1 1 auto",
                    "minHeight": 0, "display": "flex",
                    "flexDirection": "column"
                },
            ),
        ],
        className="app-shell",
    )

    # Injetamos o script do service worker diretamente no final do componente
    # raiz/HTML. Isso garante que registrará o SW em clientes que suportem.
    sw_script = html.Script('''
            var deferredInstallPrompt = null;

            function getInstallButton() {
                return document.getElementById('btn-instalar-pwa');
            }

            function hideInstallButton() {
                var btn = getInstallButton();
                if (!btn) return;
                btn.style.display = 'none';
            }

            function showInstallButton() {
                var btn = getInstallButton();
                if (!btn) return;
                btn.style.display = 'inline-flex';
            }

            function bindInstallButton() {
                var btn = getInstallButton();
                if (!btn || btn.__pwa_install_bound) {
                    return;
                }

                btn.addEventListener('click', function () {
                    if (!deferredInstallPrompt) {
                        return;
                    }

                    deferredInstallPrompt.prompt();
                    deferredInstallPrompt.userChoice
                        .then(function () {
                            deferredInstallPrompt = null;
                            hideInstallButton();
                        })
                        .catch(function () {
                            deferredInstallPrompt = null;
                            hideInstallButton();
                        });
                });

                btn.__pwa_install_bound = true;
            }

            window.addEventListener('beforeinstallprompt', function (event) {
                event.preventDefault();
                deferredInstallPrompt = event;
                bindInstallButton();
                showInstallButton();
            });

            window.addEventListener('appinstalled', function () {
                deferredInstallPrompt = null;
                hideInstallButton();
            });

            var isLocalHost = (
                location.hostname === 'localhost' ||
                location.hostname === '127.0.0.1'
            );

            if ('serviceWorker' in navigator && !isLocalHost) {
                window.addEventListener('load', function() {
                    bindInstallButton();
                    navigator.serviceWorker.register(
                        '__SW_SCRIPT_URL__'
                    ).then(function(reg) {
                        console.log(
                            'SW registration successful '
                            + 'with scope: ', reg.scope
                        );
                    }, function(err) {
                        console.log(
                            'SW registration failed: ', err
                        );
                    });
                });
            }
        '''.replace('__SW_SCRIPT_URL__', sw_script_url))

    children = app_layout.children
    if children is None:
        app_layout.children = [sw_script]
    elif isinstance(children, list):
        children.append(sw_script)
    else:
        app_layout.children = [children, sw_script]

    return app_layout
