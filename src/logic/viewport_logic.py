import math
import time

import dash
import dash_leaflet as dl
import pandas as pd


def calcular_viewport_linhas(
    linhas_sel,
    recarregar_gtfs_estatico_sob_demanda,
    gtfs_load_event,
    gtfs_data_lock,
    line_to_bounds,
    line_to_shape_coords,
    request,
):
    """Calcula viewport (center, zoom, bounds) para linhas
    selecionadas com proteção contra outliers."""
    if not linhas_sel:
        return None, None, None

    recarregar_gtfs_estatico_sob_demanda(linhas_sel)
    if not gtfs_load_event.is_set():
        # Evita falhar no primeiro clique: tenta aguardar um pouco,
        # mas segue com o que já estiver disponível mesmo sem sinal.
        gtfs_load_event.wait(timeout=2.5)

    with gtfs_data_lock:
        bounds_snapshot = dict(line_to_bounds)
        shape_coords_snapshot = dict(line_to_shape_coords)

    RIO_LAT_MIN, RIO_LAT_MAX = -23.6, -22.4
    RIO_LON_MIN, RIO_LON_MAX = -44.3, -42.8

    min_lat = None
    min_lon = None
    max_lat = None
    max_lon = None
    missing_bounds = []

    for linha_id in (str(ln) for ln in linhas_sel):
        b = bounds_snapshot.get(linha_id)
        if not b:
            missing_bounds.append(linha_id)
            continue
        sw, ne = b
        if not (RIO_LAT_MIN <= sw[0] <= RIO_LAT_MAX and
                RIO_LAT_MIN <= ne[0] <= RIO_LAT_MAX):
            continue
        if not (RIO_LON_MIN <= sw[1] <= RIO_LON_MAX and
                RIO_LON_MIN <= ne[1] <= RIO_LON_MAX):
            continue
        min_lat = sw[0] if min_lat is None else min(min_lat, sw[0])
        min_lon = sw[1] if min_lon is None else min(min_lon, sw[1])
        max_lat = ne[0] if max_lat is None else max(max_lat, ne[0])
        max_lon = ne[1] if max_lon is None else max(max_lon, ne[1])

    if missing_bounds:
        for linha_id in missing_bounds:
            coords_linha = shape_coords_snapshot.get(linha_id, [])
            for coords in coords_linha:
                if not coords:
                    continue
                try:
                    lats = [float(pt[0]) for pt in coords]
                    lons = [float(pt[1]) for pt in coords]
                except Exception:
                    continue

                seg_min_lat, seg_max_lat = min(lats), max(lats)
                seg_min_lon, seg_max_lon = min(lons), max(lons)
                if not (RIO_LAT_MIN <= seg_min_lat <= RIO_LAT_MAX and
                        RIO_LAT_MIN <= seg_max_lat <= RIO_LAT_MAX):
                    continue
                if not (RIO_LON_MIN <= seg_min_lon <= RIO_LON_MAX and
                        RIO_LON_MIN <= seg_max_lon <= RIO_LON_MAX):
                    continue

                min_lat = seg_min_lat if min_lat is None else \
                    min(min_lat, seg_min_lat)
                min_lon = seg_min_lon if min_lon is None else \
                    min(min_lon, seg_min_lon)
                max_lat = seg_max_lat if max_lat is None else \
                    max(max_lat, seg_max_lat)
                max_lon = seg_max_lon if max_lon is None else \
                    max(max_lon, seg_max_lon)

    if None in (min_lat, min_lon, max_lat, max_lon):
        return None, None, None

    user_agent = (request.headers.get("User-Agent", "") or "").lower()
    is_mobile = any(
        token in user_agent
        for token in ["mobile", "android", "iphone", "ipad"]
    )

    lat_span_raw = abs(max_lat - min_lat)
    lon_span_raw = abs(max_lon - min_lon)

    pad_factor = 0.14 if is_mobile else 0.08
    min_pad = 0.0022 if is_mobile else 0.0012
    lat_pad = max(min_pad, lat_span_raw * pad_factor)
    lon_pad = max(min_pad, lon_span_raw * pad_factor)
    min_lat -= lat_pad
    max_lat += lat_pad
    min_lon -= lon_pad
    max_lon += lon_pad
    bounds = [
        [round(min_lat, 6), round(min_lon, 6)],
        [round(max_lat, 6), round(max_lon, 6)]
    ]

    center = [
        round((min_lat + max_lat) / 2, 6),
        round((min_lon + max_lon) / 2, 6)
    ]

    lat_span = max(0.0001, abs(max_lat - min_lat))
    lon_span = max(0.0001, abs(max_lon - min_lon))
    zoom_lat = math.log2(170.0 / lat_span)
    zoom_lon = math.log2(360.0 / lon_span)

    min_zoom = 13 if is_mobile else (14 if len(linhas_sel) == 1 else 13)
    zoom_base = math.floor(min(zoom_lat, zoom_lon))
    zoom_offset = 1 if is_mobile else 2
    zoom = int(max(min_zoom, min(17, zoom_base + zoom_offset)))

    return center, zoom, bounds


def calcular_viewport_veiculos(
    veiculos_sel,
    get_gps_snapshot,
    rio_polygon,
    rio_polygon_prepared,
    build_point_mask,
    request,
):
    """
    Calcula viewport para veículos selecionados usando heurística
    similar à aba de linhas.
    """
    if not veiculos_sel:
        return None, None, None

    gps_snapshot = get_gps_snapshot()
    if gps_snapshot.empty:
        return None, None, None

    sel_set = set(str(v) for v in veiculos_sel)
    filtrado = gps_snapshot[
        gps_snapshot["ordem"].astype(str).isin(sel_set)
    ]
    if filtrado.empty:
        return None, None, None

    filtrado = filtrado.copy()
    filtrado["lat"] = pd.to_numeric(filtrado["lat"], errors="coerce")
    filtrado["lng"] = pd.to_numeric(filtrado["lng"], errors="coerce")
    filtrado = filtrado.dropna(subset=["lat", "lng"])
    filtrado = filtrado[
        filtrado["lat"].between(-90, 90)
        & filtrado["lng"].between(-180, 180)
    ]
    if filtrado.empty:
        return None, None, None

    RIO_LAT_MIN, RIO_LAT_MAX = -23.6, -22.4
    RIO_LON_MIN, RIO_LON_MAX = -44.3, -42.8
    filtrado = filtrado[
        filtrado["lat"].between(RIO_LAT_MIN, RIO_LAT_MAX)
        & filtrado["lng"].between(RIO_LON_MIN, RIO_LON_MAX)
    ]
    if filtrado.empty:
        return None, None, None

    if rio_polygon is not None:
        try:
            inside_mask = build_point_mask(
                filtrado,
                lon_col="lng",
                lat_col="lat",
                polygon=rio_polygon,
                prepared_polygon=rio_polygon_prepared,
                predicate="covered_by",
            )
            filtrado = filtrado[inside_mask]
        except Exception:
            pass

    if filtrado.empty:
        return None, None, None

    if len(filtrado) == 1:
        row = filtrado.iloc[0]
        min_lat = max_lat = float(row["lat"])
        min_lon = max_lon = float(row["lng"])
    elif len(filtrado) >= 30:
        min_lat = float(filtrado["lat"].quantile(0.02))
        max_lat = float(filtrado["lat"].quantile(0.98))
        min_lon = float(filtrado["lng"].quantile(0.02))
        max_lon = float(filtrado["lng"].quantile(0.98))
    else:
        min_lat = float(filtrado["lat"].min())
        max_lat = float(filtrado["lat"].max())
        min_lon = float(filtrado["lng"].min())
        max_lon = float(filtrado["lng"].max())

    lat_span_raw = abs(max_lat - min_lat)
    lon_span_raw = abs(max_lon - min_lon)

    lat_pad = max(0.0012, lat_span_raw * 0.08)
    lon_pad = max(0.0012, lon_span_raw * 0.08)
    min_lat -= lat_pad
    max_lat += lat_pad
    min_lon -= lon_pad
    max_lon += lon_pad

    bounds = [
        [round(min_lat, 6), round(min_lon, 6)],
        [round(max_lat, 6), round(max_lon, 6)]
    ]

    center = [
        round((min_lat + max_lat) / 2.0, 6),
        round((min_lon + max_lon) / 2.0, 6),
    ]

    lat_span = max(0.0001, abs(max_lat - min_lat))
    lon_span = max(0.0001, abs(max_lon - min_lon))
    zoom_lat = math.log2(170.0 / lat_span)
    zoom_lon = math.log2(360.0 / lon_span)

    user_agent = (request.headers.get("User-Agent", "") or "").lower()
    is_mobile = any(
        token in user_agent
        for token in ["mobile", "android", "iphone", "ipad"]
    )
    min_zoom = 14 if is_mobile else (15 if len(filtrado) == 1 else 13)
    max_zoom = 16
    zoom_val = math.floor(min(zoom_lat, zoom_lon))
    zoom = int(max(min_zoom, min(max_zoom, zoom_val)))

    return center, zoom, bounds


def resolver_comando_viewport(
    data_localizacao,
    gps_ts,
    tab_filtro,
    linhas_sel,
    linhas_sel_debounce,
    linhas_recenter_token,
    veiculos_sel,
    veiculos_recenter_token,
    gerar_svg_usuario,
    calcular_viewport_linhas_fn,
    calcular_viewport_veiculos_fn,
    get_gps_snapshot,
    map_supports_viewport,
):
    """
    Resolve comando de viewport (dict com center/zoom ou bounds)
    e camada de localização.
    """
    ctx = dash.callback_context
    triggered_props = [
        item.get("prop_id", "")
        for item in (ctx.triggered or [])
    ]
    trigger = triggered_props[0].split(".")[0] \
        if triggered_props else None
    has_location_trigger = any(
        prop.startswith("store-localizacao.") for prop in triggered_props
    )
    has_gps_trigger = any(
        prop.startswith("store-gps-ts.") for prop in triggered_props
    )
    has_dropdown_trigger = any(
        prop.startswith("dropdown-linhas.") for prop in triggered_props
    )
    has_debounce_trigger = any(
        prop.startswith("store-linhas-debounce.") for prop in triggered_props
    )
    has_veiculos_store_trigger = any(
        prop.startswith("store-veiculos-debounce.") for prop in triggered_props
    )
    has_linhas_recenter_trigger = any(
        prop.startswith("store-linhas-recenter-token.")
        for prop in triggered_props
    )
    has_veiculos_recenter_trigger = any(
        prop.startswith("store-veiculos-recenter-token.")
        for prop in triggered_props
    )
    has_tab_trigger = any(
        prop.startswith("store-tab-filtro.")
        for prop in triggered_props
    )
    has_lines_trigger = (
        has_dropdown_trigger
        or has_debounce_trigger
        or has_linhas_recenter_trigger
    )
    has_vehicles_selection_trigger = has_veiculos_store_trigger
    modo = "veiculos" if tab_filtro == "veiculos" else "linhas"

    if has_debounce_trigger:
        linhas_ativas = linhas_sel_debounce or []
    elif has_dropdown_trigger:
        linhas_ativas = linhas_sel or []
    else:
        linhas_ativas = linhas_sel_debounce or linhas_sel or []

    veiculos_ativos = veiculos_sel or []

    if has_location_trigger or trigger == "store-localizacao":
        if not data_localizacao or data_localizacao.get("lat") is None:
            return dash.no_update, dash.no_update

        lat = float(data_localizacao["lat"])
        lon = float(data_localizacao["lon"])
        marker_icon = {
            "iconSize": [22, 22],
            "iconAnchor": [11, 11],
            "popupAnchor": [0, -11],
            "className": "map-user-pin-icon",
        }
        try:
            icon_url = gerar_svg_usuario()
            if icon_url:
                marker_icon["iconUrl"] = icon_url
        except Exception:
            icon_url = None

        if marker_icon.get("iconUrl"):
            marcador = dl.Marker(
                position=[lat, lon],
                icon=marker_icon,
                children=dl.Tooltip("Você está aqui"),
            )
        else:
            marcador = dl.CircleMarker(
                center=[lat, lon],
                radius=8,
                color="#ffffff",
                weight=2,
                fillColor="#0d6efd",
                fillOpacity=0.95,
                children=dl.Tooltip("Você está aqui"),
            )
        zoom_loc = 16
        return {
            "center": [lat, lon],
            "zoom": zoom_loc,
            "clear_bounds": True,
            "force_view": {
                "center": [lat, lon],
                "zoom": zoom_loc,
                "token": int(time.time() * 1000),
            },
        }, [marcador]

    if (modo == "linhas" and (
        has_lines_trigger or
        trigger in ("dropdown-linhas", "store-linhas-debounce")
    )) or (modo == "linhas" and has_tab_trigger):
        if has_location_trigger and has_lines_trigger:
            return dash.no_update, dash.no_update

        center, zoom, bounds = calcular_viewport_linhas_fn(linhas_ativas)
        if center is None or zoom is None or bounds is None:
            sel = set(str(x) for x in (linhas_ativas or []))
            gps_snapshot = get_gps_snapshot()
            if not gps_snapshot.empty and sel:
                gps_snapshot = gps_snapshot[
                    gps_snapshot["linha"].astype(str).isin(sel)
                ]
                if not gps_snapshot.empty:
                    center = [
                        round(float(gps_snapshot["lat"].median()), 6),
                        round(float(gps_snapshot["lng"].median()), 6),
                    ]
                    return {"center": center, "zoom": 12}, dash.no_update
            return dash.no_update, dash.no_update

        command = {"center": center, "zoom": zoom, "bounds": bounds}
        return command, dash.no_update

    if (
        modo == "veiculos"
        and (
            has_vehicles_selection_trigger
            or has_veiculos_recenter_trigger
            or has_tab_trigger
            or (has_gps_trigger and bool(veiculos_ativos))
        )
    ):
        linhas_veiculos = []
        try:
            gps_snapshot = get_gps_snapshot()
            if not gps_snapshot.empty and veiculos_ativos:
                ordens = set(str(v) for v in veiculos_ativos)
                filtrado = gps_snapshot[
                    gps_snapshot["ordem"].astype(str).isin(ordens)
                ]
                if not filtrado.empty and "linha" in filtrado.columns:
                    linhas_veiculos = sorted(set(
                        str(v) for v in filtrado["linha"]
                        .dropna().astype(str).tolist() if str(v).strip()
                    ))
        except Exception:
            linhas_veiculos = []

        center = zoom = bounds = None
        if linhas_veiculos:
            center, zoom, bounds = calcular_viewport_linhas_fn(linhas_veiculos)

        if center is None or zoom is None or bounds is None:
            center, zoom, bounds = (
                calcular_viewport_veiculos_fn(veiculos_ativos)
            )

        if len(veiculos_ativos) == 1:
            try:
                gps_snapshot = get_gps_snapshot()
                if not gps_snapshot.empty:
                    v_id = str(veiculos_ativos[0])
                    row = gps_snapshot[
                        gps_snapshot["ordem"].astype(str) == v_id
                    ]
                    if not row.empty:
                        lat = float(row.iloc[0]["lat"])
                        lng = float(row.iloc[0]["lng"])
                        center = [round(lat, 6), round(lng, 6)]
                        zoom = max(int(zoom or 17), 17)
                        bounds = [
                            [round(lat - 0.0008, 6), round(lng - 0.0008, 6)],
                            [round(lat + 0.0008, 6), round(lng + 0.0008, 6)]
                        ]
            except Exception:
                pass

        if center is None or zoom is None or bounds is None:
            return dash.no_update, dash.no_update

        command = {
            "center": dash.no_update,
            "zoom": dash.no_update,
            "force_view": {
                "center": center,
                "zoom": zoom,
                "token": int(time.time() * 1000),
            },
        }
        return command, dash.no_update

    return dash.no_update, dash.no_update


def normalize_map_center(center_value):
    """
    Normaliza center para formato aceito pelo componente
    de mapa no fallback.
    """
    if center_value is dash.no_update or center_value is None:
        return center_value
    if isinstance(center_value, dict):
        lat = center_value.get("lat")
        lng = center_value.get("lng")
        if lat is None or lng is None:
            return center_value
        try:
            return [float(lat), float(lng)]
        except Exception:
            return center_value
    if isinstance(center_value, (list, tuple)) and len(center_value) >= 2:
        try:
            return [float(center_value[0]), float(center_value[1])]
        except Exception:
            return center_value
    return center_value
