import unittest
from types import SimpleNamespace
from unittest.mock import patch

import dash
import pandas as pd

from viewport_logic import (
    calcular_viewport_linhas,
    calcular_viewport_veiculos,
    normalize_map_center,
    resolver_comando_viewport,
)


class _FakeRequest:
    def __init__(self, user_agent="pytest"):
        self.headers = {"User-Agent": user_agent}


class _DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ViewportLogicTests(unittest.TestCase):
    def test_calcular_viewport_linhas_bounds_snapshot(self):
        event = SimpleNamespace(
            is_set=lambda: True, wait=lambda timeout=0: None
        )
        lock = _DummyLock()

        center, zoom, bounds = calcular_viewport_linhas(
            linhas_sel=["100"],
            recarregar_gtfs_estatico_sob_demanda=lambda _linhas: None,
            gtfs_load_event=event,
            gtfs_data_lock=lock,
            line_to_bounds={"100": [[-22.95, -43.30], [-22.85, -43.10]]},
            line_to_shape_coords={},
            request=_FakeRequest(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            ),
        )

        self.assertIsNotNone(center)
        self.assertIsNotNone(zoom)
        self.assertIsNotNone(bounds)
        self.assertEqual(len(center), 2)
        self.assertEqual(len(bounds), 2)

    def test_calcular_viewport_veiculos_single_vehicle(self):
        df = pd.DataFrame([{"ordem": "A1", "lat": -22.90, "lng": -43.20}])

        center, zoom, bounds = calcular_viewport_veiculos(
            veiculos_sel=["A1"],
            get_gps_snapshot=lambda: df,
            rio_polygon=None,
            rio_polygon_prepared=None,
            build_point_mask=(
                lambda *args, **kwargs: pd.Series([True], index=df.index)
            ),
            request=_FakeRequest(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            ),
        )

        self.assertEqual(center, [-22.9, -43.2])
        self.assertIsInstance(zoom, int)
        self.assertEqual(len(bounds), 2)

    def test_resolver_comando_viewport_location_trigger(self):
        fake_ctx = SimpleNamespace(
            triggered=[{"prop_id": "store-localizacao.data"}]
        )
        with patch("viewport_logic.dash.callback_context", fake_ctx):
            command, marker_layer = resolver_comando_viewport(
                data_localizacao={"lat": -22.9, "lon": -43.2},
                gps_ts=0,
                tab_filtro="linhas",
                linhas_sel=[],
                linhas_sel_debounce=[],
                linhas_recenter_token=None,
                veiculos_sel=[],
                veiculos_recenter_token=None,
                gerar_svg_usuario=lambda: "data:image/svg+xml;base64,abc",
                calcular_viewport_linhas_fn=lambda _linhas: (None, None, None),
                calcular_viewport_veiculos_fn=(
                    lambda _veics: (None, None, None)
                ),
                get_gps_snapshot=lambda: pd.DataFrame(),
                map_supports_viewport=True,
            )

        self.assertEqual(command["center"], [-22.9, -43.2])
        self.assertEqual(command["zoom"], 16)
        self.assertIn("force_view", command)
        self.assertEqual(command["force_view"]["center"], [-22.9, -43.2])
        self.assertEqual(command["force_view"]["zoom"], 16)
        self.assertTrue(
            isinstance(marker_layer, list) and len(marker_layer) == 1
        )

    def test_resolver_comando_viewport_veiculos_force_view(self):
        tr_id = "store-veiculos-debounce.data"
        fake_ctx = SimpleNamespace(triggered=[{"prop_id": tr_id}])
        gps_df = pd.DataFrame([{
            "ordem": "A1", "lat": -22.9, "lng": -43.2, "linha": "100"
        }])

        with patch("viewport_logic.dash.callback_context", fake_ctx):
            command, marker_layer = resolver_comando_viewport(
                data_localizacao=None,
                gps_ts=1,
                tab_filtro="veiculos",
                linhas_sel=[],
                linhas_sel_debounce=[],
                linhas_recenter_token=None,
                veiculos_sel=["A1"],
                veiculos_recenter_token=123,
                gerar_svg_usuario=lambda: "svg",
                calcular_viewport_linhas_fn=lambda _linhas: (None, None, None),
                calcular_viewport_veiculos_fn=(
                    lambda _veics: (
                        [-22.9, -43.2], 16,
                        [[-22.91, -43.21], [-22.89, -43.19]]
                    )
                ),
                get_gps_snapshot=lambda: gps_df,
                map_supports_viewport=True,
            )

        self.assertIn("force_view", command)
        self.assertEqual(command["force_view"]["center"], [-22.9, -43.2])
        self.assertEqual(command["force_view"]["zoom"], 17)
        self.assertIs(marker_layer, dash.no_update)

    def test_normalize_map_center_variants(self):
        p1 = {"lat": -22.9, "lng": -43.2}
        self.assertEqual(normalize_map_center(p1), [-22.9, -43.2])
        self.assertEqual(normalize_map_center((-22.9, -43.2)), [-22.9, -43.2])
        self.assertIs(normalize_map_center(dash.no_update), dash.no_update)


if __name__ == "__main__":
    unittest.main()
