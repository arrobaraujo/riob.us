import time
from datetime import datetime
from urllib.parse import unquote, parse_qs

import dash
import json
import pytz
import uuid
from dash import Input, Output, State, html as d_html, ALL
from src.i18n import normalize_locale, t
from src.logic.transitous_logic import fetch_routing, parse_transitous_response, itineraries_to_geojson, fetch_geocoding, RIO_TZ


def _normalize_multi_values(values):
    """Normaliza valores de componente multi para lista de strings não vazias."""
    if values is None:
        return []
    if isinstance(values, str):
        candidates = [values]
    elif isinstance(values, (list, tuple, set)):
        candidates = list(values)
    else:
        candidates = [values]
    normalized = []
    for v in candidates:
        if v is None:
            continue
        text = str(v).strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_vehicle_token(value):
    text = str(value or "").strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    return text, digits


def _filter_values_in_options(values, options):
    selected = _normalize_multi_values(values)
    allowed = {
        str((opt or {}).get("value", "")).strip()
        for opt in (options or [])
        if str((opt or {}).get("value", "")).strip()
    }
    valid = [value for value in selected if value in allowed]
    return selected, valid, allowed


def _resolve_vehicle_alias(options, typed_value):
    raw_full, raw_digits = _normalize_vehicle_token(typed_value)
    if not raw_full:
        return ""

    for opt in options or []:
        value = str((opt or {}).get("value", "")).strip()
        full, _digits = _normalize_vehicle_token(value)
        if full and full == raw_full:
            return value

    if raw_digits:
        for opt in options or []:
            value = str((opt or {}).get("value", "")).strip()
            _full, digits = _normalize_vehicle_token(value)
            if digits and digits == raw_digits:
                return value

    return str(typed_value).strip()


def _split_vehicle_options_with_selected_fallback(options, veiculos_sel):
    selected_list = _normalize_multi_values(veiculos_sel)
    selected_set = set(selected_list)
    known_values = {
        str(o.get("value", "")).strip()
        for o in (options or [])
        if str(o.get("value", "")).strip()
    }

    selected_opts = [
        o for o in (options or []) if str(o.get("value", "")) in selected_set
    ]
    missing_selected_opts = [
        {
            "label": f"{value} · selecionado",
            "value": value,
        }
        for value in selected_list
        if value not in known_values
    ]
    unselected_opts = [
        o for o in (options or []) if str(o.get("value", "")) not in selected_set
    ]

    return missing_selected_opts + selected_opts, unselected_opts, known_values


def _extract_line_tokens_from_query(parsed_qs):
    raw_values = []
    raw_values.extend(parsed_qs.get("linha") or [])
    raw_values.extend(parsed_qs.get("linhas") or [])

    tokens = []
    for raw in raw_values:
        text = unquote(str(raw or "")).strip()
        if not text:
            continue
        for part in text.split(","):
            token = part.strip()
            if token:
                tokens.append(token)

    # Remove duplicados preservando ordem de aparicao.
    deduped = []
    seen = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _parse_deep_link(pathname, search=None):
    query = str(search or "").strip()
    if query:
        if query.startswith("?"):
            query = query[1:]
        parsed_qs = parse_qs(query, keep_blank_values=False)
        line_tokens = _extract_line_tokens_from_query(parsed_qs)
        if line_tokens:
            return "linhas", line_tokens

    text = str(pathname or "").strip()
    if not text:
        return None

    chunks = [unquote(chunk).strip() for chunk in text.split("/") if chunk]
    if len(chunks) < 2:
        return None

    section = chunks[0].lower()
    token = chunks[1]
    if not token:
        return None

    if section == "linhas":
        tokens = [part.strip() for part in token.split(",") if part.strip()]
        if not tokens:
            return None
        return "linhas", tokens
    return None


def _resolve_tab_filter_state(
    tab_value,
    pathname,
    search,
    linhas_sel,
    linhas_opts,
    triggers,
    locale="pt-BR",
):
    """Resolve o estado de tabs e filtros sem depender do runtime do Dash."""
    locale = normalize_locale(locale)
    url_triggered = bool(
        triggers & {"url-router"}
        or any("url-router" in trigger for trigger in triggers)
    )
    if url_triggered:
        parsed = _parse_deep_link(pathname, search)
        if parsed:
            _tab, tokens = parsed
            return "linhas", tokens, [], None

    current_tab = tab_value or "linhas"

    # Troca de aba pelo usuário: preserva linhas ao ir para veículos
    # para manter o contexto ao retornar para a aba Linhas.
    if current_tab == "veiculos":
        return current_tab, dash.no_update, dash.no_update, None

    selected, valid, allowed = _filter_values_in_options(
        linhas_sel,
        linhas_opts,
    )
    if selected and selected != valid:
        if not allowed:
            return "linhas", [], [], (
                t(locale, "warning.restore.pending")
            )

        removed_count = len(selected) - len(valid)
        if valid:
            return "linhas", valid, [], (
                t(locale, "warning.restore.partial")
            )
        return "linhas", [], [], (
            t(locale, "warning.restore.none", removed_count=removed_count)
        )

    return "linhas", dash.no_update, [], None


def register_ui_callbacks(app, get_last_update_ts, get_line_to_color=None):
    @app.callback(
        Output("tabs-filtro", "value"),
        Input("url-router", "pathname"),
        Input("url-router", "search"),
        prevent_initial_call=False,
    )
    def sincronizar_tab_com_url(pathname, search):
        """Permite deep link apenas para /linhas/<id>."""
        parsed = _parse_deep_link(pathname, search)
        if not parsed:
            return dash.no_update
        tab, _tokens = parsed
        return tab

    @app.callback(
        Output("store-tab-filtro", "data"),
        Output("dropdown-linhas", "value"),
        Output("dropdown-veiculos", "value"),
        Output("store-session-warning", "data"),
        Input("tabs-filtro", "value"),
        Input("url-router", "pathname"),
        Input("url-router", "search"),
        State("dropdown-linhas", "value"),
        State("dropdown-linhas", "options"),
        State("store-locale", "data"),
        prevent_initial_call=False,
    )
    def sincronizar_tab_filtro(
        tab_value,
        pathname,
        search,
        linhas_sel,
        linhas_opts,
        locale,
    ):
        """Mantém estado da aba ativa e limpa o outro dropdown ao trocar aba."""
        ctx = dash.callback_context
        triggers = {t["prop_id"].split(".")[0] for t in (ctx.triggered or [])}
        return _resolve_tab_filter_state(
            tab_value,
            pathname,
            search,
            linhas_sel,
            linhas_opts,
            triggers,
            locale=locale,
        )

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
        Output("intervalo-linhas-recenter", "disabled"),
        Output("store-linhas-recenter-token", "data"),
        Input("store-linhas-debounce", "data"),
        Input("store-tab-filtro", "data"),
        Input("intervalo-linhas-recenter", "n_intervals"),
        prevent_initial_call=True,
    )
    def agendar_recenter_linhas(linhas_sel, tab_filtro, _tick):
        """Agenda um segundo recenter curto para foco de linhas no primeiro uso."""
        ctx = dash.callback_context
        trigger = ctx.triggered[0]["prop_id"].split(".")[0] \
            if ctx.triggered else None
        if trigger in ("store-linhas-debounce", "store-tab-filtro"):
            if tab_filtro != "veiculos" and len(linhas_sel or []) > 0:
                return False, dash.no_update
            return True, dash.no_update
        if trigger == "intervalo-linhas-recenter":
            return True, int(time.time() * 1000)
        return dash.no_update, dash.no_update

    @app.callback(
        Output("store-veiculos-debounce", "data"),
        Input("dropdown-veiculos", "value"),
    )
    def sincronizar_veiculos(veiculos_sel):
        """
        Sincroniza seleção de veículos sem debounce para resposta imediata.
        """
        return _normalize_multi_values(veiculos_sel)

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
        selected_opts, unselected_opts, known_values = (
            _split_vehicle_options_with_selected_fallback(options, veiculos_sel)
        )
        selected_set = {
            str(v) for v in _normalize_multi_values(veiculos_sel)
        }

        search = (search_value or "").strip().lower()
        if len(search) >= 2:
            search_terms = search.split()
            typed_full, typed_digits = _normalize_vehicle_token(search_value)

            def _match_option(opt):
                label = str(opt.get("label", "")).lower()
                value_raw = str(opt.get("value", "")).strip()
                value_full, value_digits = _normalize_vehicle_token(value_raw)

                if all(term in label for term in search_terms):
                    return True

                lowered_value = value_raw.lower()
                if all(term in lowered_value for term in search_terms):
                    return True

                if typed_digits and value_digits and typed_digits in value_digits:
                    return True

                if typed_full and value_full and typed_full == value_full:
                    return True

                return False

            matched = [o for o in unselected_opts if _match_option(o)]

            # Fallback: se o texto digitado não está no snapshot, expõe uma
            # opção de busca manual selecionável. Tenta resolver alias numérico
            # (ex.: "50001" → "A50001") antes de criar a opção sintética.
            resolved_value = _resolve_vehicle_alias(options, search_value)
            manual_opt = []
            if (
                resolved_value
                and resolved_value not in selected_set
                and resolved_value not in known_values
            ):
                manual_opt = [{
                    "label": f"{resolved_value} · busca manual",
                    "value": resolved_value,
                }]

            return selected_opts + manual_opt + matched[:200]

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
        Input("store-session-warning", "data"),
    )
    def atualizar_error_banner(error_msg, warning_msg):
        """Mostra/oculta banner de erro quando APIs falham."""
        from dash import html as _html

        if not error_msg:
            if not warning_msg:
                return []
            return _html.Div(
                [_html.Span(str(warning_msg))],
                className="error-banner",
                role="status",
            )
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


    @app.callback(
        Output("store-trajeto-itinerary", "data"),
        Output("store-trajeto-geojson", "data"),
        Output("store-trajeto-bounds", "data"),
        Output("routing-results", "children"),
        Output("store-trajeto-selected-index", "data"),
        Input("btn-buscar-trajeto", "n_clicks"),
        Input({"type": "itinerary-card", "index": ALL}, "n_clicks"),
        State("input-origem", "value"),
        State("input-destino", "value"),
        State("store-locale", "data"),
        State("store-trajeto-itinerary", "data"),
        State("store-trajeto-selected-index", "data"),
        prevent_initial_call=True,
    )
    def gerenciar_trajeto(n_search, n_clicks_list, origem, destino, locale, itineraries_cached, selected_idx):
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        trigger_id = ctx.triggered[0]["prop_id"]
        new_selected_idx = selected_idx
        itineraries = itineraries_cached

        # CASO 1: Clique em um Card de Itinerário
        if "itinerary-card" in trigger_id:
            try:
                new_selected_idx = json.loads(trigger_id.split(".")[0])["index"]
            except:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
        
        # CASO 2: Clique no botão de Busca
        elif "btn-buscar-trajeto" in trigger_id:
            if not origem or not destino:
                return None, None, None, [], -1

            def get_best_coords(val):
                try:
                    parts = str(val).split(",")
                    if len(parts) == 2:
                        return {"lat": float(parts[0]), "lng": float(parts[1])}
                except:
                    pass
                return fetch_geocoding(val)

            start_coords = get_best_coords(origem)
            end_coords = get_best_coords(destino)

            if not start_coords or not end_coords:
                msg = t(locale, "routing.error")
                return None, None, None, [d_html.P(msg, className="p-3 text-error")], -1

            raw_data = fetch_routing(start_coords, end_coords)
            if not raw_data:
                return None, None, None, [d_html.P(t(locale, "routing.error"), className="p-3 text-warning")], -1

            itineraries = parse_transitous_response(raw_data)
            if not itineraries:
                return None, None, None, [d_html.P(t(locale, "routing.no_results"), className="p-3 text-info")], -1
            
            new_selected_idx = 0

        # Se não temos itinerários, não fazemos nada
        if not itineraries:
             return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Geração da lista com as classes corretas baseadas no novo índice
        results_list = []
        for i, it in enumerate(itineraries):
            try:
                def format_time(ts):
                    dt = datetime.fromtimestamp(ts, pytz.UTC).astimezone(RIO_TZ)
                    return dt.strftime("%H:%M")

                dep_time = format_time(it["departure"])
                arr_time = format_time(it["arrival"])
                duration = it["duration"] // 60
                
                is_active = (i == new_selected_idx)
                card_class = f"itinerary-card {'itinerary-card--active' if is_active else ''}"

                compact_steps = []
                detailed_timeline = []
                
                line_to_color = get_line_to_color() if get_line_to_color else {}
                
                for idx_leg, leg in enumerate(it.get("legs", [])):
                    leg_type = leg["type"].upper()
                    is_walk = leg_type == "WALK"
                    icon = "🚶" if is_walk else "🚌"
                    line_label = leg.get('line') or ""
                    
                    if is_walk:
                        leg_color = "#3b82f6"
                    else:
                        leg_color = line_to_color.get(line_label, "#ef4444")
                        
                    badge_style = {
                        "backgroundColor": leg_color,
                        "color": "white",
                        "borderColor": leg_color
                    }
                    
                    def translate_place(name):
                        if name == "__ORIGIN__": return t(locale, "routing.from")
                        if name == "__DESTINATION__": return t(locale, "routing.to")
                        return name

                    # Passo compacto para o resumo
                    compact_steps.append(d_html.Div([
                        d_html.Span(icon, className="mr-1"),
                        d_html.Span(line_label, className="font-black text-[10px]") if line_label else None
                    ], className=f"badge badge-sm badge-outline flex items-center mr-1 mb-1 p-1", style=badge_style))

                    # Item da Timeline detalhada
                    leg_title = t(locale, "routing.walk") if is_walk else f"{t(locale, 'routing.line')} {leg.get('line')}"
                    stop_prefix = t(locale, "routing.stop_prefix") if not is_walk else "" # Apenas prefixo para paradas, não caminhada simples
                    
                    detailed_timeline.append(d_html.Div([
                        d_html.Div([
                            d_html.Div(className="timeline-line"),
                            d_html.Div(icon, className=f"timeline-icon-circle text-white", style=badge_style)
                        ], className="timeline-icon-col"),
                        d_html.Div([
                            d_html.Div(leg_title, className="timeline-title"),
                            d_html.Div([
                                d_html.Span(stop_prefix, className="font-bold mr-1"),
                                d_html.Span(translate_place(leg['from']))
                            ], className="timeline-stop"),
                            # Paradas intermediárias
                            *(
                                [
                                    d_html.Ul([
                                        d_html.Li(
                                            stop["name"],
                                            className="timeline-intermediate-stop"
                                        )
                                        for stop in leg.get("stops", []) if stop.get("name")
                                    ], className="timeline-stops-list")
                                ] if not is_walk and leg.get("stops") else []
                            ),
                            d_html.Div(f"{leg.get('duration', 0)//60} min", className="timeline-duration"),
                            d_html.Div([
                                d_html.Span(stop_prefix, className="font-bold mr-1"),
                                d_html.Span(translate_place(leg['to']))
                            ], className="timeline-stop"),
                        ], className="timeline-content")
                    ], className="timeline-step"))

                results_list.append(d_html.Div(
                    [
                        d_html.Div([
                            d_html.Div([
                                d_html.Span(f"{dep_time}", className="text-xl font-black"),
                                d_html.Span("→", className="mx-2 opacity-20"),
                                d_html.Span(f"{arr_time}", className="text-xl font-black"),
                            ], className="flex items-center"),
                            d_html.Div([
                                d_html.Span(f"{duration} min", className="badge badge-neutral font-bold"),
                            ]),
                        ], className="flex justify-between items-start mb-4"),
                        
                        d_html.Div(compact_steps, className="flex flex-wrap mb-2"),
                        
                        d_html.Div(
                            detailed_timeline, 
                            className="routing-timeline",
                            style={"display": "flex" if is_active else "none"}
                        ),
                        
                        d_html.Div([
                            d_html.Span(f"{it['transfers']} " + t(locale, "routing.transfers"), className="text-[10px] font-bold opacity-30 uppercase tracking-widest")
                        ], className="mt-3 text-right")
                    ],
                    id={"type": "itinerary-card", "index": i},
                    n_clicks=0,
                    className=card_class,
                ))
            except Exception as e:
                print(f"Erro ao parsear itinerário {i}: {e}")

        # Quando seleciona o itinerário
        selected_itinerary = itineraries[new_selected_idx]
        line_to_color = get_line_to_color() if get_line_to_color else {}
        res = itineraries_to_geojson(selected_itinerary, line_to_color)
        
        return itineraries, res["geojson"], res["bounds"], results_list, new_selected_idx


    @app.callback(
        Output("layer-trajeto", "children"),
        Input("store-trajeto-geojson", "data"),
        State("store-locale", "data"),
    )
    def atualizar_mapa_trajeto(geojson_data, locale):
        import dash_leaflet as dl
        if not geojson_data or not geojson_data.get("features"):
            return []
        
        children = []
        features = geojson_data["features"]
        
        for feature in features:
            props = feature["properties"]
            geom_type = feature["geometry"]["type"]
            coords = feature["geometry"]["coordinates"]
            
            if geom_type == "Point":
                # Render stop
                leaflet_coords = [coords[1], coords[0]]
                children.append(dl.CircleMarker(
                    id=f"stop-{uuid.uuid4().hex}",
                    center=leaflet_coords,
                    radius=5,
                    color="white",
                    fillColor=props["color"],
                    fillOpacity=1,
                    weight=1,
                    children=[dl.Tooltip(props.get("name", ""))]
                ))
            else:
                # GeoJSON é [lon, lat], Leaflet quer [lat, lon]
                leaflet_coords = [[c[1], c[0]] for c in coords]
                    
                # 1. Linha do Trajeto (Trecho)
                children.append(dl.Polyline(
                    id=f"poly-{uuid.uuid4().hex}",
                    positions=leaflet_coords,
                    color=props["color"],
                    dashArray=props["dashArray"],
                    weight=props["weight"],
                    opacity=props["opacity"]
                ))
                
                # 2. Marcador de conexão
                children.append(dl.CircleMarker(
                    id=f"conn-{uuid.uuid4().hex}",
                    center=leaflet_coords[0],
                    radius=4,
                    color="white",
                    fillColor=props["color"],
                    fillOpacity=1,
                    weight=2
                ))
            
        # 3. Marcadores de Pontual (Origem e Destino final)
        if features:
            start_pt = features[0]["geometry"]["coordinates"][0]
            end_pt = features[-1]["geometry"]["coordinates"][-1]
            
            # Marcador de Origem
            children.append(dl.CircleMarker(
                id=f"origin-{uuid.uuid4().hex}",
                center=[start_pt[1], start_pt[0]],
                radius=6,
                color="#22c55e",
                fillColor="white",
                fillOpacity=1,
                weight=3,
                children=dl.Tooltip(t(locale, "routing.from"))
            ))
            
            # Marcador de Destino (Ícone de Final)
            children.append(dl.Marker(
                id=f"dest-{uuid.uuid4().hex}",
                position=[end_pt[1], end_pt[0]],
                children=dl.Tooltip(t(locale, "routing.to"))
            ))
            
        return children

    @app.callback(
        Output("input-origem", "value"),
        Output("input-destino", "value"),
        Input("mapa", "click_lat_lng"),
        State("tabs-filtro", "value"),
        State("input-origem", "value"),
        State("input-destino", "value"),
        prevent_initial_call=True
    )
    def capturar_clique_mapa(click_data, tab_ativa, origem, destino):
        if tab_ativa != "trajeto" or not click_data:
            return dash.no_update, dash.no_update
        
        coord_str = f"{click_data[0]:.6f},{click_data[1]:.6f}"
        
        if not origem:
            return coord_str, dash.no_update
        if not destino:
            return dash.no_update, coord_str
        
        return coord_str, None

    @app.callback(
        Output("legenda", "style"),
        Output("btn-localizar", "style"),
        Output("toolbar-card", "style"),
        Input("tabs-filtro", "value"),
        prevent_initial_call=False
    )
    def ocultar_elementos_mapa_na_aba_trajeto(aba_ativa):
        """Esconde legenda e toolbar quando na aba Trajeto."""
        if aba_ativa == "trajeto":
            return {"display": "none"}, {}, {"display": "none"}
        return {}, {}, {}
