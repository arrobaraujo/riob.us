import os
import pickle
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString, MultiPolygon, shape as shapely_shape
from shapely.prepared import prep


GTFS_STATIC_CACHE_PATH = "gtfs/gtfs_static_cache.pkl"
GTFS_STATIC_CACHE_VERSION = 3


def _to_float_price(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("R$", "").replace(" ", "")
    text = text.replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


def _build_line_to_fares(gtfs):
    line_to_fares = {}

    routes_df = gtfs.get("routes")
    if routes_df is None or routes_df.empty:
        return line_to_fares
    if not {"route_id", "route_short_name"}.issubset(routes_df.columns):
        return line_to_fares

    routes_base = routes_df[["route_id", "route_short_name"]].dropna(
        subset=["route_id", "route_short_name"]
    ).copy()
    if routes_base.empty:
        return line_to_fares
    routes_base["route_id"] = routes_base["route_id"].astype(str).str.strip()
    routes_base["route_short_name"] = (
        routes_base["route_short_name"].astype(str).str.strip()
    )
    routes_base = routes_base[
        (routes_base["route_id"] != "")
        & (routes_base["route_short_name"] != "")
    ]
    if routes_base.empty:
        return line_to_fares

    route_to_price = {}
    fare_rules_df = gtfs.get("fare_rules")
    fare_attrs_df = gtfs.get("fare_attributes")
    if (
        fare_rules_df is not None
        and fare_attrs_df is not None
        and not fare_rules_df.empty
        and not fare_attrs_df.empty
        and {"route_id", "fare_id"}.issubset(fare_rules_df.columns)
        and {"fare_id", "price"}.issubset(fare_attrs_df.columns)
    ):
        rules = fare_rules_df[["route_id", "fare_id"]].dropna(
            subset=["route_id", "fare_id"]
        ).copy()
        attrs = fare_attrs_df[["fare_id", "price"]].dropna(
            subset=["fare_id", "price"]
        ).copy()
        if not rules.empty and not attrs.empty:
            rules["route_id"] = rules["route_id"].astype(str).str.strip()
            rules["fare_id"] = rules["fare_id"].astype(str).str.strip()
            attrs["fare_id"] = attrs["fare_id"].astype(str).str.strip()
            attrs["price"] = attrs["price"].astype(str).str.strip()
            merged = rules.merge(attrs, on="fare_id", how="inner")
            if not merged.empty:
                merged = merged[
                    (merged["route_id"] != "")
                    & (merged["fare_id"] != "")
                    & (merged["price"] != "")
                ].copy()
                if not merged.empty:
                    merged["_price_num"] = merged["price"].apply(
                        _to_float_price
                    )
                    merged = merged.sort_values(
                        by=["route_id", "_price_num", "fare_id"],
                        na_position="last",
                    )
                    for route_id, grp in merged.groupby("route_id", sort=False):
                        price = ""
                        for _, fare_row in grp.iterrows():
                            candidate = str(fare_row.get("price", "") or "").strip()
                            if candidate:
                                price = candidate
                                break
                        if price:
                            route_to_price[route_id] = price

    for row in routes_base.itertuples(index=False):
        route_id = str(row.route_id)
        route_short_name = str(row.route_short_name)
        price = str(route_to_price.get(route_id, "") or "").strip()
        if price and route_short_name and route_short_name not in line_to_fares:
            line_to_fares[route_short_name] = price

    # Fallback legado: routes.txt.tarifas
    if "tarifas" in routes_df.columns:
        fallback = routes_df[["route_short_name", "tarifas"]].dropna(
            subset=["route_short_name", "tarifas"]
        )
        for row in fallback.itertuples(index=False):
            route_short_name = str(row.route_short_name).strip()
            price = str(row.tarifas).strip()
            if route_short_name and price and route_short_name not in line_to_fares:
                line_to_fares[route_short_name] = price

    return line_to_fares


def _normalize_line_key(value):
    """Normaliza identificador de linha para matching resiliente.

    Ex.: "0415" e "415" passam a casar.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.isdigit():
        return str(int(text))
    return text.upper()


def _resolve_requested_route_short_names(requested_lines, all_route_names):
    """Resolve linhas solicitadas para route_short_name existentes no GTFS."""
    requested = [str(v).strip() for v in (requested_lines or []) if str(v).strip()]
    if not requested:
        return set()

    all_names = [str(v).strip() for v in all_route_names if str(v).strip()]
    all_name_set = set(all_names)

    direct_hits = {ln for ln in requested if ln in all_name_set}
    unresolved = [ln for ln in requested if ln not in direct_hits]
    if not unresolved:
        return direct_hits

    gtfs_by_norm = {}
    for route_name in all_names:
        gtfs_by_norm.setdefault(_normalize_line_key(route_name), set()).add(route_name)

    resolved = set(direct_hits)
    for ln in unresolved:
        normalized = _normalize_line_key(ln)
        resolved.update(gtfs_by_norm.get(normalized, set()))
    return resolved


def _file_signature(path):
    try:
        stat = os.stat(path)
        return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    except OSError:
        return None


def _build_source_signature():
    garagens_base = "garagens/Garagens_de_operadores_SPPO"
    return {
        "gtfs_zip": _file_signature("gtfs/gtfs.zip"),
        "garagens_shp": _file_signature(f"{garagens_base}.shp"),
        "garagens_dbf": _file_signature(f"{garagens_base}.dbf"),
        "garagens_shx": _file_signature(f"{garagens_base}.shx"),
    }


def _load_cached_result(source_signature):
    try:
        if not os.path.exists(GTFS_STATIC_CACHE_PATH):
            return None
        with open(GTFS_STATIC_CACHE_PATH, "rb") as f:
            cached = pickle.load(f)
        if not isinstance(cached, dict):
            return None
        if cached.get("version") != GTFS_STATIC_CACHE_VERSION:
            return None
        if cached.get("source_signature") != source_signature:
            return None
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        rio_polygon = payload.get("rio_polygon")
        garagens_polygon = payload.get("garagens_polygon")
        try:
            prep_rio = prep(rio_polygon) if rio_polygon is not None else None
            payload["rio_polygon_prepared"] = prep_rio
        except Exception:
            payload["rio_polygon_prepared"] = None
        try:
            prep_gar = (
                prep(garagens_polygon)
                if garagens_polygon is not None else None
            )
            payload["garagens_polygon_prepared"] = prep_gar
        except Exception:
            payload["garagens_polygon_prepared"] = None
        return payload
    except Exception:
        return None


def _save_cached_result(source_signature, payload):
    try:
        payload_to_cache = dict(payload)
        # Objetos prepared do shapely não são serializáveis;
        # recompomos no load.
        payload_to_cache["rio_polygon_prepared"] = None
        payload_to_cache["garagens_polygon_prepared"] = None
        os.makedirs(os.path.dirname(GTFS_STATIC_CACHE_PATH), exist_ok=True)
        with open(GTFS_STATIC_CACHE_PATH, "wb") as f:
            pickle.dump(
                {
                    "version": GTFS_STATIC_CACHE_VERSION,
                    "source_signature": source_signature,
                    "payload": payload_to_cache,
                },
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
    except Exception:
        # Cache é apenas otimização; nunca deve quebrar o fluxo principal.
        pass


def carregar_dados_estaticos_service(empty_shapes_gdf_fn, empty_stops_gdf_fn):
    source_signature = _build_source_signature()
    cached_payload = _load_cached_result(source_signature)
    if cached_payload is not None:
        return cached_payload

    result = {
        "rio_polygon": None,
        "rio_polygon_prepared": None,
        "garagens_polygon": None,
        "garagens_polygon_prepared": None,
        "gtfs": {},
        "line_to_shape_ids": {},
        "line_to_stop_ids": {},
        "line_to_shape_coords": {},
        "line_to_stops_points": {},
        "line_to_bounds": {},
        "line_to_fares": {},
    }

    try:
        resp = requests.get(
            "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/3304557"
            "?formato=application/vnd.geo%2Bjson",
            timeout=30,
        )
        resp.raise_for_status()
        geojson = resp.json()
        geometrias = [
            shapely_shape(feat["geometry"])
            for feat in geojson.get("features", [])
            if feat.get("geometry")
        ]
        if geometrias:
            if len(geometrias) == 1:
                rio_polygon = geometrias[0]
            else:
                rio_polygon = MultiPolygon(geometrias)
            result["rio_polygon"] = rio_polygon
            try:
                result["rio_polygon_prepared"] = prep(rio_polygon)
            except Exception:
                result["rio_polygon_prepared"] = None
        else:
            print("AVISO: GeoJSON do IBGE sem geometrias.")
    except requests.RequestException as e:
        print(
            f"ERRO ao carregar limites do Rio (API): "
            f"{type(e).__name__} - {e}"
        )
    except Exception as e:
        print(f"ERRO ao carregar limites do Rio: {type(e).__name__} - {e}")

    try:
        garagens_gdf = gpd.read_file(
            "garagens/Garagens_de_operadores_SPPO.shp"
        )
        garagens_gdf = garagens_gdf.to_crs("EPSG:4326")
        garagens_polygon = garagens_gdf.geometry.union_all()
        result["garagens_polygon"] = garagens_polygon
        try:
            result["garagens_polygon_prepared"] = prep(garagens_polygon)
        except Exception:
            result["garagens_polygon_prepared"] = None
    except FileNotFoundError:
        msg = "ERRO: Arquivo Garagens_de_operadores_SPPO.shp não encontrado"
        print(msg)
    except Exception as e:
        print(f"ERRO ao carregar garagens: {type(e).__name__} - {e}")

    try:
        gtfs = {}
        line_to_shape_ids = {}
        line_to_stop_ids = {}
        line_to_shape_coords = {}
        line_to_stops_points = {}
        line_to_bounds = {}

        with zipfile.ZipFile("gtfs/gtfs.zip") as z:
            target_files = {
                "routes": {
                    "usecols": lambda c: c in {
                        "route_id", "route_short_name", "tarifas"
                    }
                },
                "trips": {"usecols": ["trip_id", "route_id", "shape_id"]},
                "shapes": {
                    "usecols": [
                        "shape_id", "shape_pt_lat",
                        "shape_pt_lon", "shape_pt_sequence"
                    ]
                },
                "stops": {
                    "usecols": [
                        "stop_id",
                        "stop_name",
                        "stop_code",
                        "stop_desc",
                        "platform_code",
                        "stop_lat",
                        "stop_lon",
                    ]
                },
                "stop_times": {"usecols": ["trip_id", "stop_id"]},
                "fare_rules": {
                    "usecols": ["fare_id", "route_id"],
                    "optional": True,
                },
                "fare_attributes": {
                    "usecols": ["fare_id", "price"],
                    "optional": True,
                },
            }
            zip_names = z.namelist()
            for key, opts in target_files.items():
                names = [n for n in zip_names if n.endswith(f"{key}.txt")]
                if not names:
                    if not opts.get("optional"):
                        print(f"  AVISO: {key}.txt não encontrado no GTFS")
                    continue
                try:
                    with z.open(names[0]) as f:
                        gtfs[key] = pd.read_csv(
                            f,
                            dtype=str,
                            usecols=opts["usecols"],
                            low_memory=False,
                        )
                except Exception:
                    if key == "stops":
                        try:
                            with z.open(names[0]) as f2:
                                gtfs[key] = pd.read_csv(
                                    f2,
                                    dtype=str,
                                    usecols=lambda c: c in {
                                        "stop_id",
                                        "stop_name",
                                        "stop_code",
                                        "stop_desc",
                                        "platform_code",
                                        "stop_lat",
                                        "stop_lon",
                                    },
                                    low_memory=False,
                                )
                            cols_to_check = [
                                "stop_name", "stop_code",
                                "stop_desc", "platform_code"
                            ]
                            for col in cols_to_check:
                                if col not in gtfs[key].columns:
                                    gtfs[key][col] = ""
                        except Exception as e2:
                            print(f"  ✗ Erro ao ler {key}: {e2}")
                    else:
                        if not opts.get("optional"):
                            print(f"  ✗ Erro ao ler {key}")

        shapes_gtfs = empty_shapes_gdf_fn()
        stops_gtfs = empty_stops_gdf_fn()

        if "shapes" in gtfs and not gtfs["shapes"].empty:
            try:
                df = gtfs["shapes"].copy()
                df["shape_pt_lat"] = pd.to_numeric(
                    df["shape_pt_lat"], errors="coerce"
                )
                df["shape_pt_lon"] = pd.to_numeric(
                    df["shape_pt_lon"], errors="coerce"
                )
                df["shape_pt_sequence"] = pd.to_numeric(
                    df["shape_pt_sequence"], errors="coerce"
                )
                df = df.dropna(
                    subset=[
                        "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"
                    ]
                )
                df = df.sort_values(["shape_id", "shape_pt_sequence"])

                lines = []
                for shape_id, grp in df.groupby("shape_id"):
                    coords = list(
                        zip(grp["shape_pt_lon"], grp["shape_pt_lat"])
                    )
                    if len(coords) < 2:
                        continue
                    lines.append({
                        "shape_id": shape_id,
                        "geometry": LineString(coords)
                    })

                if lines:
                    shapes_gtfs = gpd.GeoDataFrame(
                        lines, geometry="geometry", crs="EPSG:4326"
                    )
            except Exception as e:
                print(f"  ERRO ao processar shapes: {type(e).__name__} - {e}")
        else:
            print("  AVISO: shapes.txt não encontrado ou vazio no GTFS")

        if "stops" in gtfs and not gtfs["stops"].empty:
            try:
                df = gtfs["stops"].copy()
                df["stop_lat"] = pd.to_numeric(
                    df["stop_lat"], errors="coerce"
                )
                df["stop_lon"] = pd.to_numeric(
                    df["stop_lon"], errors="coerce"
                )
                df = df.dropna(subset=["stop_lat", "stop_lon"])
                cols_to_chk = [
                    "stop_name", "stop_code",
                    "stop_desc", "platform_code"
                ]
                for col in cols_to_chk:
                    if col not in df.columns:
                        df[col] = ""

                if len(df) > 0:
                    pts = gpd.points_from_xy(df["stop_lon"], df["stop_lat"])
                    stops_gtfs = gpd.GeoDataFrame(
                        df,
                        geometry=pts,
                        crs="EPSG:4326",
                    )
            except Exception as e:
                print(f"  ERRO ao processar stops: {type(e).__name__} - {e}")
        else:
            print("  AVISO: stops.txt não encontrado ou vazio no GTFS")

        if all(k in gtfs for k in ["routes", "trips"]):
            try:
                rotas = gtfs["routes"].dropna(
                    subset=["route_id", "route_short_name"]
                )
                trips = gtfs["trips"].dropna(
                    subset=["trip_id", "route_id"]
                ).merge(rotas, on="route_id", how="inner")

                if "shape_id" in trips.columns:
                    line_to_shape_ids = (
                        trips.dropna(subset=["shape_id"])
                        .groupby("route_short_name")["shape_id"]
                        .unique()
                        .apply(list)
                        .to_dict()
                    )

                if "stop_times" in gtfs and not gtfs["stop_times"].empty:
                    st = gtfs["stop_times"].dropna(
                        subset=["trip_id", "stop_id"]
                    ).merge(
                        trips[["trip_id", "route_short_name"]],
                        on="trip_id", how="inner"
                    )
                    line_to_stop_ids = (
                        st.groupby("route_short_name")["stop_id"]
                        .unique()
                        .apply(list)
                        .to_dict()
                    )

                if not shapes_gtfs.empty and line_to_shape_ids:
                    shapes_lookup = shapes_gtfs.set_index("shape_id")
                    for linha_id, shape_ids in line_to_shape_ids.items():
                        coords_linha = []
                        min_lat = None
                        min_lon = None
                        max_lat = None
                        max_lon = None
                        for shp_id in shape_ids:
                            if shp_id not in shapes_lookup.index:
                                continue
                            try:
                                geom = shapes_lookup.loc[shp_id, "geometry"]
                                if geom is None:
                                    continue
                                coords = [[pt[1], pt[0]] for pt in geom.coords]
                                if len(coords) > 1:
                                    coords_linha.append(coords)
                                    lats = [c[0] for c in coords]
                                    lons = [c[1] for c in coords]
                                    seg_min_lat = min(lats)
                                    seg_max_lat = max(lats)
                                    seg_min_lon = min(lons)
                                    seg_max_lon = max(lons)
                                    min_lat = (
                                        seg_min_lat if min_lat is None
                                        else min(min_lat, seg_min_lat)
                                    )
                                    min_lon = (
                                        seg_min_lon if min_lon is None
                                        else min(min_lon, seg_min_lon)
                                    )
                                    max_lat = (
                                        seg_max_lat if max_lat is None
                                        else max(max_lat, seg_max_lat)
                                    )
                                    max_lon = (
                                        seg_max_lon if max_lon is None
                                        else max(max_lon, seg_max_lon)
                                    )
                            except Exception:
                                continue
                        if coords_linha:
                            line_to_shape_coords[linha_id] = coords_linha
                            is_bound_ok = all(
                                x is not None
                                for x in (min_lat, min_lon, max_lat, max_lon)
                            )
                            if is_bound_ok:
                                line_to_bounds[linha_id] = [
                                    [min_lat, min_lon], [max_lat, max_lon]
                                ]

                if not stops_gtfs.empty and line_to_stop_ids:
                    stops_lookup = stops_gtfs.set_index("stop_id")
                    for linha_id, stop_ids in line_to_stop_ids.items():
                        pontos_linha = []
                        for stop_id in stop_ids:
                            if stop_id not in stops_lookup.index:
                                continue
                            try:
                                stop_row = stops_lookup.loc[stop_id]
                                stop_name = ""
                                if (
                                    "stop_name" in stop_row
                                    and pd.notna(stop_row["stop_name"])
                                ):
                                    stop_name = str(stop_row["stop_name"])
                                stop_code = str(
                                    stop_row.get("stop_code", "") or ""
                                )
                                stop_desc = str(
                                    stop_row.get("stop_desc", "") or ""
                                )
                                platform_code = str(
                                    stop_row.get("platform_code", "") or ""
                                )
                                pontos_linha.append(
                                    {
                                        "lat": float(stop_row["stop_lat"]),
                                        "lon": float(stop_row["stop_lon"]),
                                        "stop_name": stop_name,
                                        "stop_code": stop_code,
                                        "stop_desc": stop_desc,
                                        "platform_code": platform_code,
                                    }
                                )
                            except Exception:
                                continue
                        if pontos_linha:
                            line_to_stops_points[linha_id] = pontos_linha
            except Exception as e:
                print(
                    f"ERRO ao montar índices GTFS por linha: "
                    f"{type(e).__name__} - {e}"
                )

        result["gtfs"] = gtfs
        result["line_to_shape_ids"] = line_to_shape_ids
        result["line_to_stop_ids"] = line_to_stop_ids
        result["line_to_shape_coords"] = line_to_shape_coords
        result["line_to_stops_points"] = line_to_stops_points
        result["line_to_bounds"] = line_to_bounds
        result["line_to_fares"] = _build_line_to_fares(gtfs)

    except FileNotFoundError:
        print("ERRO: Arquivo gtfs/gtfs.zip não encontrado")
    except KeyError as e:
        print(f"ERRO ao carregar GTFS (coluna faltante): {e}")
    except Exception as e:
        print(f"ERRO ao carregar GTFS: {type(e).__name__} - {e}")

    _save_cached_result(source_signature, result)
    return result


def recarregar_gtfs_estatico_sob_demanda_service(linhas_sel):
    linhas_sel = [str(ln) for ln in (linhas_sel or [])]
    if not linhas_sel:
        return None

    try:
        with zipfile.ZipFile("gtfs/gtfs.zip") as z:
            gtfs = {}
            target_files = {
                "routes": {
                    "usecols": lambda c: c in {
                        "route_id", "route_short_name", "tarifas"
                    }
                },
                "trips": {"usecols": ["trip_id", "route_id", "shape_id"]},
                "shapes": {
                    "usecols": [
                        "shape_id", "shape_pt_lat",
                        "shape_pt_lon", "shape_pt_sequence"
                    ]
                },
                "stops": {
                    "usecols": [
                        "stop_id",
                        "stop_name",
                        "stop_code",
                        "stop_desc",
                        "platform_code",
                        "stop_lat",
                        "stop_lon",
                    ]
                },
                "stop_times": {"usecols": ["trip_id", "stop_id"]},
                "fare_rules": {
                    "usecols": ["fare_id", "route_id"],
                    "optional": True,
                },
                "fare_attributes": {
                    "usecols": ["fare_id", "price"],
                    "optional": True,
                },
            }
            zip_names = z.namelist()
            for key, opts in target_files.items():
                names = [n for n in zip_names if n.endswith(f"{key}.txt")]
                if not names:
                    continue
                with z.open(names[0]) as f:
                    try:
                        gtfs[key] = pd.read_csv(
                            f,
                            dtype=str,
                            usecols=opts["usecols"],
                            low_memory=False,
                        )
                    except ValueError:
                        if key == "stops":
                            with z.open(names[0]) as f2:
                                gtfs[key] = pd.read_csv(
                                    f2,
                                    dtype=str,
                                    usecols=lambda c: c in {
                                        "stop_id",
                                        "stop_name",
                                        "stop_code",
                                        "stop_desc",
                                        "platform_code",
                                        "stop_lat",
                                        "stop_lon",
                                    },
                                    low_memory=False,
                                )
                            cols_to_chk = [
                                "stop_name", "stop_code",
                                "stop_desc", "platform_code"
                            ]
                            for col in cols_to_chk:
                                if col not in gtfs[key].columns:
                                    gtfs[key][col] = ""

        if not all(k in gtfs for k in ["routes", "trips"]):
            print("AVISO: Fallback GTFS com routes/trips indisponíveis")
            return None

        rotas = gtfs["routes"].dropna(subset=["route_id", "route_short_name"])
        trips = gtfs["trips"].dropna(subset=["trip_id", "route_id"]).merge(
            rotas, on="route_id", how="inner"
        )

        line_to_shape_ids = {}
        line_to_stop_ids = {}
        line_to_shape_coords = {}
        line_to_stops_points = {}
        line_to_bounds = {}

        trips_filtradas = trips
        if "route_short_name" in trips.columns:
            target_route_names = _resolve_requested_route_short_names(
                linhas_sel,
                trips["route_short_name"].dropna().astype(str).tolist(),
            )
            if target_route_names:
                trips_filtradas = trips[
                    trips["route_short_name"].isin(target_route_names)
                ]
            else:
                trips_filtradas = trips.iloc[0:0]

        if "shape_id" in trips_filtradas.columns:
            line_to_shape_ids = (
                trips_filtradas.dropna(subset=["shape_id"])
                .groupby("route_short_name")["shape_id"]
                .unique()
                .apply(list)
                .to_dict()
            )
        
        # Coleta shape_ids que realmente precisamos processar
        needed_shape_ids = set()
        for sids in line_to_shape_ids.values():
            needed_shape_ids.update(sids)

        shapes_by_id = {}
        shape_bounds_by_id = {}
        if "shapes" in gtfs and not gtfs["shapes"].empty:
            df_shapes = gtfs["shapes"].copy()
            # Filtra shapes antes de converter/ordenar
            if needed_shape_ids:
                df_shapes = df_shapes[
                    df_shapes["shape_id"].isin(needed_shape_ids)
                ]
            
            if not df_shapes.empty:
                df_shapes["shape_pt_lat"] = pd.to_numeric(
                    df_shapes["shape_pt_lat"], errors="coerce"
                )
                df_shapes["shape_pt_lon"] = pd.to_numeric(
                    df_shapes["shape_pt_lon"], errors="coerce"
                )
                df_shapes["shape_pt_sequence"] = pd.to_numeric(
                    df_shapes["shape_pt_sequence"], errors="coerce"
                )
                df_shapes = df_shapes.dropna(
                    subset=[
                        "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"
                    ]
                )
                df_shapes = df_shapes.sort_values(
                    ["shape_id", "shape_pt_sequence"]
                )

                for shape_id, grp in df_shapes.groupby("shape_id"):
                    coords = grp[
                        ["shape_pt_lat", "shape_pt_lon"]
                    ].values.tolist()
                    if len(coords) < 2:
                        continue
                    shapes_by_id[shape_id] = coords
                    lats = [c[0] for c in coords]
                    lons = [c[1] for c in coords]
                    shape_bounds_by_id[shape_id] = [
                        min(lats), min(lons), max(lats), max(lons)
                    ]

        if shapes_by_id and line_to_shape_ids:
            for linha_id, shape_ids in line_to_shape_ids.items():
                coords_linha = []
                min_lat = None
                min_lon = None
                max_lat = None
                max_lon = None
                for shp_id in shape_ids:
                    coords = shapes_by_id.get(shp_id)
                    if not coords:
                        continue
                    coords_linha.append(coords)
                    b = shape_bounds_by_id.get(shp_id)
                    if not b:
                        continue
                    min_lat = b[0] if min_lat is None else min(min_lat, b[0])
                    min_lon = b[1] if min_lon is None else min(min_lon, b[1])
                    max_lat = b[2] if max_lat is None else max(max_lat, b[2])
                    max_lon = b[3] if max_lon is None else max(max_lon, b[3])
                if coords_linha:
                    line_to_shape_coords[linha_id] = coords_linha
                    if None not in (min_lat, min_lon, max_lat, max_lon):
                        line_to_bounds[linha_id] = [
                            [min_lat, min_lon], [max_lat, max_lon]
                        ]

        if (
            "stop_times" in gtfs and "stops" in gtfs
            and not gtfs["stop_times"].empty
        ):
            st = gtfs["stop_times"].dropna(
                subset=["trip_id", "stop_id"]
            ).merge(
                trips_filtradas[["trip_id", "route_short_name"]],
                on="trip_id", how="inner"
            )
            line_to_stop_ids = (
                st.groupby("route_short_name")["stop_id"]
                .unique()
                .apply(list)
                .to_dict()
            )

            stops_df = gtfs["stops"].copy()
            stop_cols = [
                "stop_name", "stop_code", "stop_desc", "platform_code"
            ]
            for col in stop_cols:
                if col not in stops_df.columns:
                    stops_df[col] = ""
            stops_df["stop_lat"] = pd.to_numeric(
                stops_df["stop_lat"], errors="coerce"
            )
            stops_df["stop_lon"] = pd.to_numeric(
                stops_df["stop_lon"], errors="coerce"
            )
            stops_df = stops_df.dropna(
                subset=["stop_lat", "stop_lon", "stop_id"]
            )
            stops_lookup = stops_df.drop_duplicates(
                subset=["stop_id"]
            ).set_index("stop_id")

            for linha_id, stop_ids in line_to_stop_ids.items():
                pontos_linha = []
                for stop_id in stop_ids:
                    if stop_id not in stops_lookup.index:
                        continue
                    stop_row = stops_lookup.loc[stop_id]
                    pontos_linha.append(
                        {
                            "lat": float(stop_row["stop_lat"]),
                            "lon": float(stop_row["stop_lon"]),
                            "stop_name": str(stop_row.get(
                                "stop_name", ""
                            ) or ""),
                            "stop_code": str(stop_row.get(
                                "stop_code", ""
                            ) or ""),
                            "stop_desc": str(stop_row.get(
                                "stop_desc", ""
                            ) or ""),
                            "platform_code": str(stop_row.get(
                                "platform_code", ""
                            ) or ""),
                        }
                    )
                if pontos_linha:
                    line_to_stops_points[linha_id] = pontos_linha

        return {
            "gtfs": gtfs,
            "line_to_shape_ids": line_to_shape_ids,
            "line_to_stop_ids": line_to_stop_ids,
            "line_to_shape_coords": line_to_shape_coords,
            "line_to_stops_points": line_to_stops_points,
            "line_to_bounds": line_to_bounds,
            "line_to_fares": _build_line_to_fares(gtfs),
        }
    except Exception as e:
        print(f"ERRO no fallback GTFS: {type(e).__name__} - {e}")
        return None
