import time
from datetime import datetime

import dash
from dash import Input, Output, State


def register_ui_callbacks(app, get_last_update_ts):
    def _bounds_to_box(bounds):
        if not bounds or not isinstance(bounds, (list, tuple)) or \
                len(bounds) < 2:
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

    @app.callback(
        Output("store-tab-filtro", "data"),
        Output("texto-ajuda-tab", "children"),
        Output("dropdown-linhas", "value"),
        Output("dropdown-veiculos", "value"),
        Input("tabs-filtro", "value"),
        prevent_initial_call=False,
    )
    def sincronizar_tab_filtro(tab_value):
        """Mantém estado da aba ativa e texto de ajuda do filtro."""
        tab = tab_value or "linhas"
        if tab == "veiculos":
            return (
                tab,
                "Pesquise pelo número do veículo ou linha.",
                [],
                dash.no_update
            )
        return "linhas", "Pesquise pelo número da linha.", dash.no_update, []

    @app.callback(
        Output("store-linhas-debounce", "data"),
        Output("intervalo-linhas-debounce", "disabled"),
        Input("dropdown-linhas", "value"),
        Input("intervalo-linhas-debounce", "n_intervals"),
        prevent_initial_call=False,
    )
    def sincronizar_linhas_com_debounce(linhas_sel, _n_intervals):
        """Sincroniza seleção de linhas com debounce de 500ms."""
        ctx = dash.callback_context
        trigger = ctx.triggered[0]["prop_id"].split(".")[0] \
            if ctx.triggered else None
        if trigger == "dropdown-linhas":
            return dash.no_update, False
        if trigger == "intervalo-linhas-debounce":
            return linhas_sel or [], True
        # Chamada inicial: popula o store com a seleção atual
        return linhas_sel or [], True

    @app.callback(
        Output("store-veiculos-debounce", "data"),
        Input("dropdown-veiculos", "value"),
    )
    def sincronizar_veiculos(veiculos_sel):
        """
        Sincroniza seleção de veículos sem debounce para resposta imediata.
        """
        return [str(v) for v in (veiculos_sel or []) if str(v).strip()]

    @app.callback(
        Output("intervalo-veiculos-recenter", "disabled"),
        Output("store-veiculos-recenter-token", "data"),
        Input("store-veiculos-debounce", "data"),
        Input("store-tab-filtro", "data"),
        Input("intervalo-veiculos-recenter", "n_intervals"),
        prevent_initial_call=True,
    )
    def agendar_recenter_veiculos(veiculos_sel, tab_filtro, _tick):
        """
        Agenda um segundo comando de recenter curto para evitar
        corrida no primeiro ciclo.
        """
        ctx = dash.callback_context
        trigger = ctx.triggered[0]["prop_id"].split(".")[0] \
            if ctx.triggered else None
        if trigger in ("store-veiculos-debounce", "store-tab-filtro"):
            if tab_filtro == "veiculos" and len(veiculos_sel or []) > 0:
                return False, dash.no_update
            return True, dash.no_update
        if trigger == "intervalo-veiculos-recenter":
            return True, int(time.time() * 1000)
        return dash.no_update, dash.no_update

    @app.callback(
        Output("dropdown-veiculos", "options"),
        Input("store-veiculos-opcoes", "data"),
        Input("dropdown-veiculos", "search_value"),
        State("dropdown-veiculos", "value"),
    )
    def atualizar_opcoes_veiculos(opcoes, search_value, veiculos_sel):
        """
        Busca server-side: por padrão os 150 mais recentes;
        com texto filtra todos.
        """
        options = opcoes or []
        selected_set = set(
            str(v) for v in (veiculos_sel or []) if str(v).strip()
        )

        # Veículos selecionados têm prioridade — sempre aparecem no topo
        selected_opts = [
            o for o in options if str(o.get("value", "")) in selected_set
        ]
        unselected_opts = [
            o for o in options if str(o.get("value", "")) not in selected_set
        ]

        search = (search_value or "").strip().lower()
        if len(search) >= 2:
            search_terms = search.split()
            # Filtra garantindo que todos os termos digitados apareçam no label
            matched = [
                o for o in unselected_opts
                if all(
                    term in str(o.get("label", "")).lower()
                    for term in search_terms
                )
            ]
            return selected_opts + matched[:200]

        # Sem busca: retorna selecionados + primeiros 150 do snapshot
        return selected_opts + unselected_opts[:150]

    @app.callback(
        Output("span-update-time", "children"),
        Input("store-gps-ts", "data"),
    )
    def atualizar_ui_atualizacao(_gps_ts):
        """Mostra timestamp da última atualização bem-sucedida."""
        last_ts = get_last_update_ts()
        tempo_texto = ""
        if last_ts:
            try:
                if isinstance(last_ts, datetime):
                    dt = last_ts
                else:
                    dt = datetime.fromisoformat(str(last_ts))
                tempo_texto = dt.strftime("%H:%M:%S")
            except Exception:
                tempo_texto = ""
        return tempo_texto

    @app.callback(
        Output("error-banner-container", "children"),
        Input("store-fetch-error", "data"),
    )
    def atualizar_error_banner(error_msg):
        """Mostra/oculta banner de erro quando APIs falham."""
        if not error_msg:
            return []
        from dash import html as _html
        return _html.Div(
            [_html.Span(str(error_msg))],
            className="error-banner",
            role="alert",
        )

    # Zoom tracking via clientside callback para renderização zoom-aware.
    app.clientside_callback(
        """
        function(bounds) {
            if (!bounds || !Array.isArray(bounds) || bounds.length < 2) {
                return window.dash_clientside.no_update;
            }
            var map = window.__gps_leaflet_map || null;
            if (map && typeof map.getZoom === 'function') {
                return map.getZoom();
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("store-zoom-atual", "data"),
        Input("mapa", "bounds"),
        prevent_initial_call=True,
    )

    # Loading overlay toggle via clientside callback.
    # NOTA: usa store-loading-ack (store dedicado) para não conflitar com o
    # callback store-build-sync registrado em app.py.
    app.clientside_callback(
        """
        function(gpsTs) {
            var el = document.getElementById('map-loading-overlay');
            if (el) { el.style.display = 'none'; }
            return window.dash_clientside.no_update;
        }
        """,
        Output("store-loading-ack", "data"),
        Input("store-gps-ts", "data"),
        prevent_initial_call=True,
    )
