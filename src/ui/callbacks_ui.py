import time
from datetime import datetime
from urllib.parse import unquote, parse_qs

import dash
from dash import Input, Output, State
from src.i18n import normalize_locale, t


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


def register_ui_callbacks(app, get_last_update_ts):
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


