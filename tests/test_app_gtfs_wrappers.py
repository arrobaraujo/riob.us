import importlib
import sys
import threading
import unittest
from unittest.mock import patch

import pandas as pd


def _import_app_module_safely():
    if "app" in sys.modules:
        return sys.modules["app"]

    original_thread = threading.Thread

    class MockThread(original_thread):
        def start(self):
            trg = getattr(self, "_target", None)
            if trg and trg.__name__ == "_carregar_dados_estaticos_bg":
                return None
            return super().start()

    with patch("threading.Thread", MockThread):
        return importlib.import_module("app")


class AppGtfsWrappersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _import_app_module_safely()

    def setUp(self):
        """Reseta estado global entre testes para evitar contaminação."""
        self.app.gtfs = {}
        self.app.line_to_shape_ids = {}
        self.app.line_to_stop_ids = {}
        self.app.line_to_shape_coords = {}
        self.app.line_to_stops_points = {}
        self.app.line_to_bounds = {}
        self.app._linhas_sem_shapes = {}
        self.app._gps_cache = pd.DataFrame()

    def test_carregar_dados_estaticos_wrapper_updates_globals(self):
        loaded = {
            "rio_polygon": "RIO",
            "rio_polygon_prepared": "RIO_PREP",
            "garagens_polygon": "GAR",
            "garagens_polygon_prepared": "GAR_PREP",
            "gtfs": {"routes": "ok"},
            "line_to_shape_ids": {"100": ["S1"]},
            "line_to_stop_ids": {"100": ["P1"]},
            "line_to_shape_coords": {
                "100": [[[-22.9, -43.2], [-22.91, -43.21]]]
            },
            "line_to_stops_points": {"100": [{"lat": -22.9, "lon": -43.2}]},
            "line_to_bounds": {"100": [[-22.95, -43.3], [-22.85, -43.1]]},
        }

        self.app._map_static_cache["dummy"] = ([], [])
        self.app._gtfs_load_event.clear()

        srv_path = "carregar_dados_estaticos_service"
        with patch.object(self.app, srv_path, return_value=loaded):
            self.app._carregar_dados_estaticos()

        self.assertEqual(self.app.rio_polygon, "RIO")
        self.assertEqual(self.app._rio_polygon_prepared, "RIO_PREP")
        self.assertEqual(self.app.garagens_polygon, "GAR")
        self.assertEqual(self.app._garagens_polygon_prepared, "GAR_PREP")
        self.assertEqual(self.app.gtfs, {"routes": "ok"})
        self.assertEqual(self.app.line_to_shape_ids, {"100": ["S1"]})
        self.assertEqual(self.app.line_to_stop_ids, {"100": ["P1"]})
        self.assertEqual(
            self.app.line_to_bounds,
            {"100": [[-22.95, -43.3], [-22.85, -43.1]]}
        )
        self.assertEqual(self.app._map_static_cache, {})
        self.assertTrue(self.app._gtfs_load_event.is_set())

    def test_recarregar_gtfs_wrapper_updates_globals_when_missing(self):
        self.app.line_to_shape_coords = {}
        self.app.line_to_stops_points = {}
        self.app._map_static_cache = {"dummy": ([], [])}
        self.app._gtfs_load_event.clear()

        loaded = {
            "gtfs": {"routes": "ok2"},
            "line_to_shape_ids": {"200": ["S2"]},
            "line_to_stop_ids": {"200": ["P2"]},
            "line_to_shape_coords": {
                "200": [[[-22.8, -43.0], [-22.81, -43.01]]]
            },
            "line_to_stops_points": {"200": [{"lat": -22.8, "lon": -43.0}]},
            "line_to_bounds": {"200": [[-22.82, -43.02], [-22.79, -42.99]]},
        }

        with patch.object(
            self.app, "recarregar_gtfs_estatico_sob_demanda_service",
            return_value=loaded
        ):
            self.app._recarregar_gtfs_estatico_sob_demanda(["200"])

        self.assertEqual(self.app.gtfs, {"routes": "ok2"})
        self.assertEqual(self.app.line_to_shape_ids, {"200": ["S2"]})
        self.assertEqual(self.app.line_to_stop_ids, {"200": ["P2"]})
        self.assertEqual(
            self.app.line_to_shape_coords,
            {"200": [[[-22.8, -43.0], [-22.81, -43.01]]]}
        )
        self.assertEqual(
            self.app.line_to_stops_points,
            {"200": [{"lat": -22.8, "lon": -43.0}]}
        )
        self.assertEqual(
            self.app.line_to_bounds,
            {"200": [[-22.82, -43.02], [-22.79, -42.99]]}
        )
        self.assertEqual(self.app._map_static_cache, {})
        self.assertTrue(self.app._gtfs_load_event.is_set())

    def test_recarregar_gtfs_wrapper_skips_service_when_no_missing(self):
        self.app.line_to_shape_coords = {
            "300": [[[-22.7, -42.9], [-22.71, -42.91]]]
        }
        self.app.line_to_stops_points = {}

        srv_path = "recarregar_gtfs_estatico_sob_demanda_service"
        with patch.object(self.app, srv_path) as mocked_service:
            self.app._recarregar_gtfs_estatico_sob_demanda(["300"])

        mocked_service.assert_not_called()

    def test_recarregar_gtfs_wrapper_retries_when_only_stops_exist(self):
        self.app.line_to_shape_coords = {}
        self.app.line_to_stops_points = {
            "415": [{"lat": -22.9, "lon": -43.2}]
        }

        with patch.object(
            self.app,
            "recarregar_gtfs_estatico_sob_demanda_service",
            return_value={
                "gtfs": {},
                "line_to_shape_ids": {
                    "415": ["S1"]
                },
                "line_to_stop_ids": {},
                "line_to_shape_coords": {
                    "415": [[[-22.9, -43.2], [-22.91, -43.21]]]
                },
                "line_to_stops_points": {},
                "line_to_bounds": {},
            },
        ) as mocked_service:
            self.app._recarregar_gtfs_estatico_sob_demanda(["415"])

        mocked_service.assert_called_once()
        self.assertIn("415", self.app.line_to_shape_coords)

    def test_atualizar_gps_preserva_cache_quando_fetch_vem_vazio(self):
        cache_anterior = pd.DataFrame(
            [{
                "ordem": "A1",
                "lat": -22.9,
                "lng": -43.2,
                "linha": "100",
                "tipo": "SPPO",
                "datahora": "2026-03-16 17:00:00",
            }]
        )
        self.app._gps_cache = cache_anterior.copy()
        self.app._last_fetch_had_data = True

        with patch.object(
            self.app,
            "fetch_gps_data",
            return_value=pd.DataFrame(),
        ):
            self.app.atualizar_gps(0, 0, "linhas", ["100"], [])

        self.assertEqual(len(self.app._gps_cache), 1)
        self.assertEqual(self.app._gps_cache.iloc[0]["ordem"], "A1")
        self.assertFalse(self.app._last_fetch_had_data)

    def test_atualizar_gps_preserva_cache_quando_filtro_veiculo_zera(self):
        cache_anterior = pd.DataFrame(
            [{
                "ordem": "B1",
                "lat": -22.91,
                "lng": -43.21,
                "linha": "200",
                "tipo": "BRT",
                "datahora": "2026-03-16 17:01:00",
            }]
        )
        dados_fetch = pd.DataFrame(
            [{
                "ordem": "X1",
                "lat": -22.95,
                "lng": -43.25,
                "linha": "300",
                "tipo": "SPPO",
                "datahora": "2026-03-16 17:02:00",
            }]
        )
        self.app._gps_cache = cache_anterior.copy()

        with patch.object(
            self.app,
            "fetch_gps_data",
            return_value=dados_fetch,
        ):
            with patch.object(
                self.app,
                "montar_opcoes_veiculos",
                return_value=[{"label": "X1", "value": "X1"}],
            ):
                self.app.atualizar_gps(0, 0, "veiculos", [], ["NAO_EXISTE"])

        self.assertEqual(len(self.app._gps_cache), 1)
        self.assertEqual(self.app._gps_cache.iloc[0]["ordem"], "B1")

    def test_linha_sort_key_usa_numero_publico_lecd(self):
        self.app.lecd_public_map = {
            "LECD010": "10",
            "LECD002": "2",
            "LECD100": "100",
        }
        ordered = sorted(
            ["LECD010", "LECD100", "LECD002"],
            key=self.app.linha_sort_key,
        )
        self.assertEqual(ordered, ["LECD002", "LECD010", "LECD100"])

    def test_linha_sort_key_ordena_natural_sem_lecd(self):
        self.app.lecd_public_map = {}
        ordered = sorted(
            ["100", "2", "A20", "A3"],
            key=self.app.linha_sort_key,
        )
        self.assertEqual(ordered, ["2", "100", "A3", "A20"])


if __name__ == "__main__":
    unittest.main()
