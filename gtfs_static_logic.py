import os
import pickle
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString, MultiPolygon, shape as shapely_shape
from shapely.prepared import prep


GTFS_STATIC_CACHE_PATH = "gtfs/gtfs_static_cache.pkl"
GTFS_STATIC_CACHE_VERSION = 1


def _file_signature(path):
    try:
        stat = os.stat(path)
        return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    except OSError:
        return None


def _build_source_signature():
    return {
        "gtfs_zip": _file_signature("gtfs/gtfs.zip"),
        "garagens_shp": _file_signature("garagens/Garagens_de_operadores_SPPO.shp"),
        "garagens_dbf": _file_signature("garagens/Garagens_de_operadores_SPPO.dbf"),
        "garagens_shx": _file_signature("garagens/Garagens_de_operadores_SPPO.shx"),
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
            payload["rio_polygon_prepared"] = prep(rio_polygon) if rio_polygon is not None else None
        except Exception:
            payload["rio_polygon_prepared"] = None
        try:
            payload["garagens_polygon_prepared"] = prep(garagens_polygon) if garagens_polygon is not None else None
        except Exception:
            payload["garagens_polygon_prepared"] = None
        return payload
    except Exception:
        return None


def _save_cached_result(source_signature, payload):
    try:
        payload_to_cache = dict(payload)
        # Objetos prepared do shapely não são serializáveis; recompomos no load.
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
        "shapes_gtfs": empty_shapes_gdf_fn(),
        "stops_gtfs": empty_stops_gdf_fn(),
        "line_to_shape_ids": {},
        "line_to_stop_ids": {},
        "line_to_shape_coords": {},
        "line_to_stops_points": {},
        "line_to_bounds": {},
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
            rio_polygon = geometrias[0] if len(geometrias) == 1 else MultiPolygon(geometrias)
            result["rio_polygon"] = rio_polygon
            try:
                result["rio_polygon_prepared"] = prep(rio_polygon)
            except Exception:
                result["rio_polygon_prepared"] = None
        else:
            print("AVISO: GeoJSON do IBGE sem geometrias.")
    except requests.RequestException as e:
        print(f"ERRO ao carregar limites do Rio (API): {type(e).__name__} - {e}")
    except Exception as e:
        print(f"ERRO ao carregar limites do Rio: {type(e).__name__} - {e}")

    try:
        garagens_gdf = gpd.read_file("garagens/Garagens_de_operadores_SPPO.shp")
        garagens_gdf = garagens_gdf.to_crs("EPSG:4326")
        garagens_polygon = garagens_gdf.geometry.union_all()
        result["garagens_polygon"] = garagens_polygon
        try:
            result["garagens_polygon_prepared"] = prep(garagens_polygon)
        except Exception:
            result["garagens_polygon_prepared"] = None
    except FileNotFoundError:
        print("ERRO: Arquivo Garagens_de_operadores_SPPO.shp não encontrado")
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
                "routes": {"usecols": ["route_id", "route_short_name"]},
                "trips": {"usecols": ["trip_id", "route_id", "shape_id"]},
                "shapes": {"usecols": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]},
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
            }
            zip_names = z.namelist()
            for key, opts in target_files.items():
                names = [n for n in zip_names if n.endswith(f"{key}.txt")]
                if not names:
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
                            for col in ["stop_name", "stop_code", "stop_desc", "platform_code"]:
                                if col not in gtfs[key].columns:
                                    gtfs[key][col] = ""
                        except Exception as e2:
                            print(f"  ✗ Erro ao ler {key}: {e2}")
                    else:
                        print(f"  ✗ Erro ao ler {key}")

        shapes_gtfs = empty_shapes_gdf_fn()
        stops_gtfs = empty_stops_gdf_fn()

        if "shapes" in gtfs and not gtfs["shapes"].empty:
            try:
                df = gtfs["shapes"].copy()
                df["shape_pt_lat"] = pd.to_numeric(df["shape_pt_lat"], errors="coerce")
                df["shape_pt_lon"] = pd.to_numeric(df["shape_pt_lon"], errors="coerce")
                df["shape_pt_sequence"] = pd.to_numeric(df["shape_pt_sequence"], errors="coerce")
                df = df.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
                df = df.sort_values(["shape_id", "shape_pt_sequence"])

                lines = []
                for shape_id, grp in df.groupby("shape_id"):
                    coords = list(zip(grp["shape_pt_lon"], grp["shape_pt_lat"]))
                    if len(coords) < 2:
                        continue
                    lines.append({"shape_id": shape_id, "geometry": LineString(coords)})

                if lines:
                    shapes_gtfs = gpd.GeoDataFrame(lines, geometry="geometry", crs="EPSG:4326")
            except Exception as e:
                print(f"  ERRO ao processar shapes: {type(e).__name__} - {e}")
        else:
            print("  AVISO: shapes.txt não encontrado ou vazio no GTFS")

        if "stops" in gtfs and not gtfs["stops"].empty:
            try:
                df = gtfs["stops"].copy()
                df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
                df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
                df = df.dropna(subset=["stop_lat", "stop_lon"])
                for col in ["stop_name", "stop_code", "stop_desc", "platform_code"]:
                    if col not in df.columns:
                        df[col] = ""

                if len(df) > 0:
                    stops_gtfs = gpd.GeoDataFrame(
                        df,
                        geometry=gpd.points_from_xy(df["stop_lon"], df["stop_lat"]),
                        crs="EPSG:4326",
                    )
            except Exception as e:
                print(f"  ERRO ao processar stops: {type(e).__name__} - {e}")
        else:
            print("  AVISO: stops.txt não encontrado ou vazio no GTFS")

        if all(k in gtfs for k in ["routes", "trips"]):
            try:
                rotas = gtfs["routes"].dropna(subset=["route_id", "route_short_name"])
                trips = gtfs["trips"].dropna(subset=["trip_id", "route_id"]).merge(
                    rotas, on="route_id", how="inner"
                )

                if "shape_id" in trips.columns:
                    line_to_shape_ids = (
                        trips.dropna(subset=["shape_id"])
                        .groupby("route_short_name")["shape_id"]
                        .unique()
                        .apply(list)
                        .to_dict()
                    )

                if "stop_times" in gtfs and not gtfs["stop_times"].empty:
                    st = gtfs["stop_times"].dropna(subset=["trip_id", "stop_id"]).merge(
                        trips[["trip_id", "route_short_name"]], on="trip_id", how="inner"
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
                                    seg_min_lat, seg_max_lat = min(lats), max(lats)
                                    seg_min_lon, seg_max_lon = min(lons), max(lons)
                                    min_lat = seg_min_lat if min_lat is None else min(min_lat, seg_min_lat)
                                    min_lon = seg_min_lon if min_lon is None else min(min_lon, seg_min_lon)
                                    max_lat = seg_max_lat if max_lat is None else max(max_lat, seg_max_lat)
                                    max_lon = seg_max_lon if max_lon is None else max(max_lon, seg_max_lon)
                            except Exception:
                                continue
                        if coords_linha:
                            line_to_shape_coords[linha_id] = coords_linha
                            if None not in (min_lat, min_lon, max_lat, max_lon):
                                line_to_bounds[linha_id] = [[min_lat, min_lon], [max_lat, max_lon]]

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
                                if "stop_name" in stop_row and pd.notna(stop_row["stop_name"]):
                                    stop_name = str(stop_row["stop_name"])
                                stop_code = str(stop_row.get("stop_code", "") or "")
                                stop_desc = str(stop_row.get("stop_desc", "") or "")
                                platform_code = str(stop_row.get("platform_code", "") or "")
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
                print(f"ERRO ao montar índices GTFS por linha: {type(e).__name__} - {e}")

        result["gtfs"] = gtfs
        result["shapes_gtfs"] = shapes_gtfs if shapes_gtfs is not None else empty_shapes_gdf_fn()
        result["stops_gtfs"] = stops_gtfs if stops_gtfs is not None else empty_stops_gdf_fn()
        result["line_to_shape_ids"] = line_to_shape_ids
        result["line_to_stop_ids"] = line_to_stop_ids
        result["line_to_shape_coords"] = line_to_shape_coords
        result["line_to_stops_points"] = line_to_stops_points
        result["line_to_bounds"] = line_to_bounds

    except FileNotFoundError:
        print("ERRO: Arquivo gtfs/gtfs.zip não encontrado")
        result["shapes_gtfs"] = empty_shapes_gdf_fn()
        result["stops_gtfs"] = empty_stops_gdf_fn()
    except KeyError as e:
        print(f"ERRO ao carregar GTFS (coluna faltante): {e}")
        result["shapes_gtfs"] = empty_shapes_gdf_fn()
        result["stops_gtfs"] = empty_stops_gdf_fn()
    except Exception as e:
        print(f"ERRO ao carregar GTFS: {type(e).__name__} - {e}")
        result["shapes_gtfs"] = empty_shapes_gdf_fn()
        result["stops_gtfs"] = empty_stops_gdf_fn()

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
                "routes": {"usecols": ["route_id", "route_short_name"]},
                "trips": {"usecols": ["trip_id", "route_id", "shape_id"]},
                "shapes": {"usecols": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]},
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
                            for col in ["stop_name", "stop_code", "stop_desc", "platform_code"]:
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

        if "shape_id" in trips.columns:
            line_to_shape_ids = (
                trips.dropna(subset=["shape_id"])
                .groupby("route_short_name")["shape_id"]
                .unique()
                .apply(list)
                .to_dict()
            )

        shapes_by_id = {}
        shape_bounds_by_id = {}
        if "shapes" in gtfs and not gtfs["shapes"].empty:
            df_shapes = gtfs["shapes"].copy()
            df_shapes["shape_pt_lat"] = pd.to_numeric(df_shapes["shape_pt_lat"], errors="coerce")
            df_shapes["shape_pt_lon"] = pd.to_numeric(df_shapes["shape_pt_lon"], errors="coerce")
            df_shapes["shape_pt_sequence"] = pd.to_numeric(df_shapes["shape_pt_sequence"], errors="coerce")
            df_shapes = df_shapes.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
            df_shapes = df_shapes.sort_values(["shape_id", "shape_pt_sequence"])

            for shape_id, grp in df_shapes.groupby("shape_id"):
                coords = grp[["shape_pt_lat", "shape_pt_lon"]].values.tolist()
                if len(coords) < 2:
                    continue
                shapes_by_id[shape_id] = coords
                lats = [c[0] for c in coords]
                lons = [c[1] for c in coords]
                shape_bounds_by_id[shape_id] = [min(lats), min(lons), max(lats), max(lons)]

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
                        line_to_bounds[linha_id] = [[min_lat, min_lon], [max_lat, max_lon]]

        if "stop_times" in gtfs and "stops" in gtfs and not gtfs["stop_times"].empty:
            st = gtfs["stop_times"].dropna(subset=["trip_id", "stop_id"]).merge(
                trips[["trip_id", "route_short_name"]], on="trip_id", how="inner"
            )
            line_to_stop_ids = (
                st.groupby("route_short_name")["stop_id"]
                .unique()
                .apply(list)
                .to_dict()
            )

            stops_df = gtfs["stops"].copy()
            for col in ["stop_name", "stop_code", "stop_desc", "platform_code"]:
                if col not in stops_df.columns:
                    stops_df[col] = ""
            stops_df["stop_lat"] = pd.to_numeric(stops_df["stop_lat"], errors="coerce")
            stops_df["stop_lon"] = pd.to_numeric(stops_df["stop_lon"], errors="coerce")
            stops_df = stops_df.dropna(subset=["stop_lat", "stop_lon", "stop_id"])
            stops_lookup = stops_df.drop_duplicates(subset=["stop_id"]).set_index("stop_id")

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
                            "stop_name": str(stop_row.get("stop_name", "") or ""),
                            "stop_code": str(stop_row.get("stop_code", "") or ""),
                            "stop_desc": str(stop_row.get("stop_desc", "") or ""),
                            "platform_code": str(stop_row.get("platform_code", "") or ""),
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
        }
    except Exception as e:
        print(f"ERRO no fallback GTFS: {type(e).__name__} - {e}")
        return None
