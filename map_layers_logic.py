import dash_leaflet as dl
from dash import html
import pandas as pd
import time


def _dataframe_fingerprint_strong(df):
    if df is None or df.empty:
        return (0, 0)
    cols = [c for c in ["ordem", "lat", "lng", "datahora", "linha", "tipo", "direcao", "sentido"] if c in df.columns]
    if not cols:
        return (len(df), 0)
    try:
        hashed = pd.util.hash_pandas_object(df[cols], index=False)
        return (len(df), int(hashed.sum()))
    except Exception:
        return (len(df), 0)


def _dataframe_fingerprint_light(df):
    if df is None or df.empty:
        return (0, "", "", 0, 0)

    cols_needed = {"ordem", "datahora", "lat", "lng"}
    if not cols_needed.issubset(set(df.columns)):
        return None

    try:
        n = int(len(df))
        first_ordem = str(df.iloc[0].get("ordem", "") or "")
        last_ordem = str(df.iloc[-1].get("ordem", "") or "")
        last_ts = str(df["datahora"].max())
        # Assinatura leve para evitar hash completo em cada ciclo.
        lat_mean = int(pd.to_numeric(df["lat"], errors="coerce").fillna(0).mean() * 10000)
        lng_mean = int(pd.to_numeric(df["lng"], errors="coerce").fillna(0).mean() * 10000)
        return (n, last_ts, f"{first_ordem}|{last_ordem}", lat_mean, lng_mean)
    except Exception:
        return None


def _build_fingerprint(df):
    light = _dataframe_fingerprint_light(df)
    if light is not None:
        return ("light", light)
    return ("strong", _dataframe_fingerprint_strong(df))


def _cache_get(cache, key, now, ttl_seconds=None):
    item = cache.get(key)
    if item is None:
        return None

    # Compatibilidade com formato legado: valor puro sem metadados.
    if not isinstance(item, dict) or "payload" not in item:
        return item

    created_at = float(item.get("created_at", now))
    if ttl_seconds is not None and (now - created_at) > float(ttl_seconds):
        cache.pop(key, None)
        return None

    item["last_access"] = now
    return item.get("payload")


def _cache_prune_lru(cache, max_items):
    if len(cache) <= max_items:
        return 0

    evicted = 0
    while len(cache) > max_items:
        lru_key = None
        lru_ts = None
        for k, v in cache.items():
            ts = 0.0
            if isinstance(v, dict):
                ts = float(v.get("last_access", v.get("created_at", 0.0)))
            if lru_key is None or ts < lru_ts:
                lru_key = k
                lru_ts = ts
        if lru_key is None:
            break
        cache.pop(lru_key, None)
        evicted += 1
    return evicted


def _cache_set(cache, key, payload, now, max_items):
    cache[key] = {
        "payload": payload,
        "created_at": now,
        "last_access": now,
    }
    return _cache_prune_lru(cache, max_items)


def construir_camadas_estaticas(
    modo,
    linhas_render,
    cores,
    gtfs_load_event,
    recarregar_gtfs_estatico_sob_demanda,
    gtfs_data_lock,
    line_to_shape_coords,
    line_to_stops_points,
    map_static_cache_lock,
    map_static_cache,
    map_static_cache_max_items,
    linha_publica_fn,
    stop_sign_icon,
    limit_list_for_render_fn,
    max_stops_per_render,
    map_static_cache_ttl_seconds=None,
    viewport_bounds=None,
    viewport_padding_degrees=0.01,
):
    if not gtfs_load_event.is_set():
        pass

    recarregar_gtfs_estatico_sob_demanda(linhas_render)

    with gtfs_data_lock:
        shape_coords_snapshot = dict(line_to_shape_coords)
        stops_points_snapshot = dict(line_to_stops_points)

    cache_key = (modo,) + tuple(sorted(str(ln) for ln in linhas_render))
    now = time.time()
    with map_static_cache_lock:
        cached_layers = _cache_get(
            map_static_cache,
            cache_key,
            now=now,
            ttl_seconds=map_static_cache_ttl_seconds,
        )

    if cached_layers is not None:
        return list(cached_layers[0]), list(cached_layers[1])

    shapes_layers = []
    paradas_layers = []

    def _normalize_bounds(bounds):
        if not bounds or not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
            return None
        try:
            sw = bounds[0]
            ne = bounds[1]
            min_lat = float(sw[0]) - float(viewport_padding_degrees)
            min_lon = float(sw[1]) - float(viewport_padding_degrees)
            max_lat = float(ne[0]) + float(viewport_padding_degrees)
            max_lon = float(ne[1]) + float(viewport_padding_degrees)
            return (min_lat, min_lon, max_lat, max_lon)
        except Exception:
            return None

    normalized_bounds = _normalize_bounds(viewport_bounds)

    def _coords_intersect_view(coords):
        if normalized_bounds is None:
            return True
        min_lat, min_lon, max_lat, max_lon = normalized_bounds
        try:
            lats = [float(c[0]) for c in coords]
            lons = [float(c[1]) for c in coords]
            if not lats or not lons:
                return False
            return not (
                max(lats) < min_lat
                or min(lats) > max_lat
                or max(lons) < min_lon
                or min(lons) > max_lon
            )
        except Exception:
            return False

    def _texto_stop_valor(valor):
        texto = str(valor).strip() if valor is not None else ""
        if not texto or texto.lower() in {"nan", "none", "null"}:
            return "N/D"
        return texto

    try:
        for linha_id in linhas_render:
            cor = cores.get(linha_id, "#888888")
            for coords in shape_coords_snapshot.get(linha_id, []):
                if not _coords_intersect_view(coords):
                    continue
                linha_label = linha_publica_fn(linha_id)
                shapes_layers.append(
                    dl.Polyline(
                        positions=coords,
                        color=cor,
                        weight=4,
                        className="itinerario-polyline",
                        children=dl.Tooltip(f"Linha {linha_label}"),
                    )
                )

            for stop_item in stops_points_snapshot.get(linha_id, []):
                if isinstance(stop_item, dict):
                    stop_lat = stop_item.get("lat")
                    stop_lon = stop_item.get("lon")
                    stop_name = stop_item.get("stop_name", "")
                    stop_code = stop_item.get("stop_code", "")
                    stop_desc = stop_item.get("stop_desc", "")
                    platform_code = stop_item.get("platform_code", "")
                else:
                    stop_lat = stop_item[0] if len(stop_item) > 0 else None
                    stop_lon = stop_item[1] if len(stop_item) > 1 else None
                    stop_name = stop_item[2] if len(stop_item) > 2 else ""
                    stop_code = ""
                    stop_desc = ""
                    platform_code = ""

                if stop_lat is None or stop_lon is None:
                    continue

                if normalized_bounds is not None:
                    min_lat, min_lon, max_lat, max_lon = normalized_bounds
                    try:
                        lat = float(stop_lat)
                        lon = float(stop_lon)
                    except Exception:
                        continue
                    if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                        continue

                popup_parada = html.Div(
                    [
                        html.P(f"Nome: {_texto_stop_valor(stop_name)}", style={"margin": "2px 0"}),
                        html.P(f"Código: {_texto_stop_valor(stop_code)}", style={"margin": "2px 0"}),
                        html.P(f"Descrição: {_texto_stop_valor(stop_desc)}", style={"margin": "2px 0"}),
                        html.P(f"Plataforma: {_texto_stop_valor(platform_code)}", style={"margin": "2px 0"}),
                    ]
                )
                paradas_layers.append(
                    dl.Marker(
                        position=[float(stop_lat), float(stop_lon)],
                        icon=stop_sign_icon,
                        children=dl.Popup(popup_parada),
                    )
                )

        paradas_layers = limit_list_for_render_fn(paradas_layers, max_stops_per_render)
    except Exception as e:
        print(f"ERRO ao montar camadas estáticas por linha: {type(e).__name__} - {e}")

    with map_static_cache_lock:
        _cache_set(
            map_static_cache,
            cache_key,
            (list(shapes_layers), list(paradas_layers)),
            now=now,
            max_items=map_static_cache_max_items,
        )

    return shapes_layers, paradas_layers


def construir_camadas_veiculos(
    sppo_df,
    brt_df,
    cores,
    linhas_render,
    lightweight_marker_threshold,
    build_geojson_cluster_layer_fn,
    group_vehicle_markers_fn,
    make_vehicle_icon_fn,
    linha_publica_fn,
    linhas_dict,
    vehicle_layers_cache_lock=None,
    vehicle_layers_cache=None,
    vehicle_layers_cache_max_items=128,
    vehicle_layers_cache_ttl_seconds=None,
    emit_cache_meta=False,
):
    def _popup(row, extra=None):
        try:
            vel = round(float(row.get("velocidade", 0)), 1)
        except Exception:
            vel = 0
        hora = str(row.get("datahora", ""))
        hora = hora[-8:] if len(hora) >= 8 else hora
        items = [
            html.P(f"Número do veículo: {row.get('ordem', '')}", style={"margin": "2px 0"}),
            html.P(f"Serviço: {linha_publica_fn(row.get('linha', ''))}", style={"margin": "2px 0"}),
            html.P(f"Vista: {linhas_dict.get(row.get('linha', ''), '')}", style={"margin": "2px 0"}),
            html.P(f"Fonte: {row.get('tipo', '')}", style={"margin": "2px 0"}),
            html.P(f"Velocidade: {vel} km/h", style={"margin": "2px 0"}),
        ]
        if extra:
            items.append(html.P(extra, style={"margin": "2px 0"}))
        items.append(html.P(f"Hora: {hora}", style={"margin": "2px 0"}))
        return dl.Popup(html.Div(items))

    lightweight_mode = (len(sppo_df) + len(brt_df)) > lightweight_marker_threshold

    cache_meta = {
        "hit": False,
        "fingerprint_mode": None,
        "evictions": 0,
    }
    cache_key = None
    now = time.time()
    if vehicle_layers_cache_lock is not None and vehicle_layers_cache is not None:
        fp_mode_sppo, fp_sppo = _build_fingerprint(sppo_df)
        fp_mode_brt, fp_brt = _build_fingerprint(brt_df)
        cache_meta["fingerprint_mode"] = f"{fp_mode_sppo}+{fp_mode_brt}"
        cache_key = (
            tuple(sorted(str(ln) for ln in (linhas_render or []))),
            bool(lightweight_mode),
            (fp_mode_sppo, fp_sppo),
            (fp_mode_brt, fp_brt),
        )
        with vehicle_layers_cache_lock:
            cached = _cache_get(
                vehicle_layers_cache,
                cache_key,
                now=now,
                ttl_seconds=vehicle_layers_cache_ttl_seconds,
            )
        if cached is not None:
            cache_meta["hit"] = True
            if emit_cache_meta:
                return list(cached[0]), list(cached[1]), cache_meta
            return list(cached[0]), list(cached[1])

    if lightweight_mode:
        onibus_children = build_geojson_cluster_layer_fn(sppo_df, "geojson-sppo")
        brt_children = build_geojson_cluster_layer_fn(brt_df, "geojson-brt")
        if cache_key is not None:
            with vehicle_layers_cache_lock:
                cache_meta["evictions"] = _cache_set(
                    vehicle_layers_cache,
                    cache_key,
                    (list(onibus_children), list(brt_children)),
                    now=now,
                    max_items=vehicle_layers_cache_max_items,
                )
        if emit_cache_meta:
            return onibus_children, brt_children, cache_meta
        return onibus_children, brt_children

    onibus_layers = []
    for row in sppo_df.itertuples(index=False):
        row_dict = row._asdict()
        cor = cores.get(str(row_dict.get("linha", "")), "#1a6faf") if linhas_render else "#1a6faf"
        try:
            bearing = float(row_dict.get("direcao", float("nan")))
        except Exception:
            bearing = float("nan")
        onibus_layers.append(
            dl.Marker(
                position=[float(row_dict["lat"]), float(row_dict["lng"])],
                icon=dict(zip(["iconUrl", "iconSize", "iconAnchor"], make_vehicle_icon_fn(bearing, cor))),
                children=_popup(row_dict),
            )
        )

    brt_layers = []
    for row in brt_df.itertuples(index=False):
        row_dict = row._asdict()
        cor = cores.get(str(row_dict.get("linha", "")), "#e67e00") if linhas_render else "#e67e00"
        try:
            bearing = float(row_dict.get("direcao", float("nan")))
        except Exception:
            bearing = float("nan")
        brt_layers.append(
            dl.Marker(
                position=[float(row_dict["lat"]), float(row_dict["lng"])],
                icon=dict(zip(["iconUrl", "iconSize", "iconAnchor"], make_vehicle_icon_fn(bearing, cor))),
                children=_popup(row_dict, extra=f"Sentido: {row_dict.get('sentido', '')}"),
            )
        )

    onibus_children = group_vehicle_markers_fn(onibus_layers)
    brt_children = group_vehicle_markers_fn(brt_layers)
    if cache_key is not None:
        with vehicle_layers_cache_lock:
            cache_meta["evictions"] = _cache_set(
                vehicle_layers_cache,
                cache_key,
                (list(onibus_children), list(brt_children)),
                now=now,
                max_items=vehicle_layers_cache_max_items,
            )
    if emit_cache_meta:
        return onibus_children, brt_children, cache_meta
    return onibus_children, brt_children
