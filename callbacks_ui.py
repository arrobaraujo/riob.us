import time
from datetime import datetime

import dash
from dash import Input, Output


def register_ui_callbacks(app, get_last_update_ts):
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
            return tab, "Pesquise pelo número do veículo ou linha.", [], dash.no_update
        return "linhas", "Pesquise pelo número da linha.", dash.no_update, []

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
        if trigger == "dropdown-linhas":
            return dash.no_update, False
        if trigger == "intervalo-linhas-debounce":
            return linhas_sel or [], True
        return dash.no_update, dash.no_update

    @app.callback(
        Output("store-veiculos-debounce", "data"),
        Input("dropdown-veiculos", "value"),
    )
    def sincronizar_veiculos(veiculos_sel):
        """Sincroniza seleção de veículos sem debounce para resposta imediata."""
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
        """Agenda um segundo comando de recenter curto para evitar corrida no primeiro ciclo."""
        trigger = dash.callback_context.triggered[0]["prop_id"].split(".")[0] if dash.callback_context.triggered else None
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
        Input("mapa", "bounds"),
    )
    def atualizar_opcoes_veiculos(opcoes, map_bounds):
        """Atualiza opções do dropdown de veículos com snapshot das APIs."""
        options = opcoes or []
        box = _bounds_to_box(map_bounds)
        if box is None:
            return options

        filtered = []
        for opt in options:
            lat = opt.get("lat") if isinstance(opt, dict) else None
            lng = opt.get("lng") if isinstance(opt, dict) else None
            if lat is None or lng is None:
                filtered.append(opt)
                continue
            try:
                latf = float(lat)
                lngf = float(lng)
            except Exception:
                continue
            if box["min_lat"] <= latf <= box["max_lat"] and box["min_lon"] <= lngf <= box["max_lon"]:
                filtered.append(opt)
        return filtered

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
                dt = last_ts if isinstance(last_ts, datetime) else datetime.fromisoformat(str(last_ts))
                tempo_texto = dt.strftime("%H:%M:%S")
            except Exception:
                tempo_texto = ""
        return tempo_texto
