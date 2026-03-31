import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import pandas as pd

from src.logic.gtfs_static_logic import (
    carregar_dados_estaticos_service,
    recarregar_gtfs_estatico_sob_demanda_service,
)


class _FakeIbgeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [-43.8, -23.2],
                            [-43.0, -23.2],
                            [-43.0, -22.7],
                            [-43.8, -22.7],
                            [-43.8, -23.2],
                        ]],
                    },
                }
            ],
        }


class _FakeGaragensGdf:
    class _Geometry:
        @staticmethod
        def union_all():
            return "GARAGENS_POLYGON"

    geometry = _Geometry()

    def to_crs(self, _crs):
        return self


def _write_gtfs_zip(base_dir, include_routes=True, include_trips=True):
    gtfs_dir = os.path.join(base_dir, "gtfs")
    os.makedirs(gtfs_dir, exist_ok=True)
    gtfs_zip_path = os.path.join(gtfs_dir, "gtfs.zip")

    sh_h = "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
    sh_d = "S1,-22.90,-43.20,1\nS1,-22.91,-43.21,2\n"
    files = {
        "shapes.txt": f"{sh_h}{sh_d}",
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "P1,Parada 1,-22.90,-43.20\n"
        ),
        "stop_times.txt": "trip_id,stop_id\nT1,P1\n",
    }
    if include_routes:
        files["routes.txt"] = "route_id,route_short_name\nR1,100\n"
    if include_trips:
        files["trips.txt"] = "trip_id,route_id,shape_id\nT1,R1,S1\n"

    with zipfile.ZipFile(gtfs_zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def _write_gtfs_zip_with_zero_padded_route(base_dir):
    gtfs_dir = os.path.join(base_dir, "gtfs")
    os.makedirs(gtfs_dir, exist_ok=True)
    gtfs_zip_path = os.path.join(gtfs_dir, "gtfs.zip")

    files = {
        "routes.txt": "route_id,route_short_name\nR1,0415\n",
        "trips.txt": "trip_id,route_id,shape_id\nT1,R1,S1\n",
        "shapes.txt": (
            "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
            "S1,-22.90,-43.20,1\n"
            "S1,-22.91,-43.21,2\n"
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "P1,Parada 1,-22.90,-43.20\n"
        ),
        "stop_times.txt": "trip_id,stop_id\nT1,P1\n",
    }

    with zipfile.ZipFile(gtfs_zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def _write_gtfs_zip_stops_without_optional_columns(base_dir):
    gtfs_dir = os.path.join(base_dir, "gtfs")
    os.makedirs(gtfs_dir, exist_ok=True)
    gtfs_zip_path = os.path.join(gtfs_dir, "gtfs.zip")

    sh_h = "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
    sh_d = "S1,-22.90,-43.20,1\nS1,-22.91,-43.21,2\n"
    files = {
        "routes.txt": "route_id,route_short_name\nR1,100\n",
        "trips.txt": "trip_id,route_id,shape_id\nT1,R1,S1\n",
        "shapes.txt": f"{sh_h}{sh_d}",
        # stop_name/stop_code/stop_desc/platform_code ausentes de proposito.
        "stops.txt": "stop_id,stop_lat,stop_lon\nP1,-22.90,-43.20\n",
        "stop_times.txt": "trip_id,stop_id\nT1,P1\n",
    }

    with zipfile.ZipFile(gtfs_zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


class GtfsStaticLogicTests(unittest.TestCase):
    def test_carregar_dados_estaticos_service_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_gtfs_zip(tmp)
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                res = _FakeIbgeResponse()
                with patch("src.logic.gtfs_static_logic.requests.get", return_value=res):
                    gdf = _FakeGaragensGdf()
                    with patch("src.logic.gtfs_static_logic.gpd.read_file",
                               return_value=gdf):
                        out = carregar_dados_estaticos_service(
                            empty_shapes_gdf_fn=lambda: pd.DataFrame(
                                columns=["shape_id", "geometry"]
                            ),
                            empty_stops_gdf_fn=lambda: pd.DataFrame(
                                columns=["stop_id", "stop_lat", "stop_lon"]
                            ),
                        )
            finally:
                os.chdir(old_cwd)

        self.assertIn("routes", out["gtfs"])
        self.assertIn("trips", out["gtfs"])
        self.assertIn("100", out["line_to_shape_ids"])
        self.assertIn("100", out["line_to_shape_coords"])
        self.assertIn("100", out["line_to_bounds"])
        self.assertIn("100", out["line_to_stops_points"])
        self.assertIsNotNone(out["rio_polygon"])

    def test_carregar_dados_estaticos_service_missing_zip_keeps_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                res = _FakeIbgeResponse()
                with patch("src.logic.gtfs_static_logic.requests.get", return_value=res):
                    gdf = _FakeGaragensGdf()
                    with patch("src.logic.gtfs_static_logic.gpd.read_file",
                               return_value=gdf):
                        out = carregar_dados_estaticos_service(
                            empty_shapes_gdf_fn=lambda: pd.DataFrame(
                                columns=["shape_id", "geometry"]
                            ),
                            empty_stops_gdf_fn=lambda: pd.DataFrame(
                                columns=["stop_id", "stop_lat", "stop_lon"]
                            ),
                        )
            finally:
                os.chdir(old_cwd)


    def test_recarregar_gtfs_sob_demanda_service_empty_selection(self):
        out = recarregar_gtfs_estatico_sob_demanda_service([])
        self.assertIsNone(out)

    def test_recarregar_gtfs_estatico_sob_demanda_service_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_gtfs_zip(tmp)
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                out = recarregar_gtfs_estatico_sob_demanda_service(["100"])
            finally:
                os.chdir(old_cwd)

        self.assertIsNotNone(out)
        self.assertIn("100", out["line_to_shape_ids"])
        self.assertIn("100", out["line_to_stop_ids"])
        self.assertIn("100", out["line_to_shape_coords"])
        self.assertIn("100", out["line_to_stops_points"])
        self.assertIn("100", out["line_to_bounds"])

    def test_recarregar_gtfs_sob_demanda_without_routes_or_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_gtfs_zip(tmp, include_routes=False, include_trips=False)
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                out = recarregar_gtfs_estatico_sob_demanda_service(["100"])
            finally:
                os.chdir(old_cwd)

        self.assertIsNone(out)

    def test_recarregar_gtfs_sob_demanda_matches_zero_padded_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_gtfs_zip_with_zero_padded_route(tmp)
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                out = recarregar_gtfs_estatico_sob_demanda_service(["415"])
            finally:
                os.chdir(old_cwd)

        self.assertIsNotNone(out)
        self.assertIn("0415", out["line_to_shape_ids"])
        self.assertIn("0415", out["line_to_shape_coords"])
        self.assertIn("0415", out["line_to_stop_ids"])

    def test_carregar_dados_estaticos_service_stops_without_optional_columns(
        self
    ):
        with tempfile.TemporaryDirectory() as tmp:
            _write_gtfs_zip_stops_without_optional_columns(tmp)
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                res = _FakeIbgeResponse()
                with patch("src.logic.gtfs_static_logic.requests.get", return_value=res):
                    gdf = _FakeGaragensGdf()
                    with patch("src.logic.gtfs_static_logic.gpd.read_file",
                               return_value=gdf):
                        out = carregar_dados_estaticos_service(
                            empty_shapes_gdf_fn=lambda: pd.DataFrame(
                                columns=["shape_id", "geometry"]
                            ),
                            empty_stops_gdf_fn=lambda: pd.DataFrame(
                                columns=["stop_id", "stop_lat", "stop_lon"]
                            ),
                        )
            finally:
                os.chdir(old_cwd)

        pontos = out["line_to_stops_points"].get("100", [])
        self.assertEqual(len(pontos), 1)
        self.assertEqual(pontos[0]["stop_name"], "")
        self.assertEqual(pontos[0]["stop_code"], "")
        self.assertEqual(pontos[0]["stop_desc"], "")
        self.assertEqual(pontos[0]["platform_code"], "")

    def test_carregar_dados_estaticos_service_reuses_persistent_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_gtfs_zip(tmp)
            old_cwd = os.getcwd()
            os.chdir(tmp)
            cache_file = os.path.join(tmp, "gtfs_static_cache.pkl")
            try:
                with patch("src.logic.gtfs_static_logic.GTFS_STATIC_CACHE_PATH",
                           cache_file):
                    with patch("src.logic.gtfs_static_logic.requests.get",
                               return_value=_FakeIbgeResponse()):
                        with patch("src.logic.gtfs_static_logic.gpd.read_file",
                                   return_value=_FakeGaragensGdf()):
                            first = carregar_dados_estaticos_service(
                                empty_shapes_gdf_fn=lambda: pd.DataFrame(
                                    columns=["shape_id", "geometry"]
                                ),
                                empty_stops_gdf_fn=lambda: pd.DataFrame(
                                    columns=["stop_id", "stop_lat", "stop_lon"]
                                ),
                            )

                    err_msg = "cache nao foi utilizado"
                    with patch("src.logic.gtfs_static_logic.pd.read_csv",
                               side_effect=AssertionError(err_msg)):
                        second = carregar_dados_estaticos_service(
                            empty_shapes_gdf_fn=lambda: pd.DataFrame(
                                columns=["shape_id", "geometry"]
                            ),
                            empty_stops_gdf_fn=lambda: pd.DataFrame(
                                columns=["stop_id", "stop_lat", "stop_lon"]
                            ),
                        )
            finally:
                os.chdir(old_cwd)

        self.assertIn("100", first["line_to_shape_ids"])
        self.assertIn("100", second["line_to_shape_ids"])


if __name__ == "__main__":
    unittest.main()
