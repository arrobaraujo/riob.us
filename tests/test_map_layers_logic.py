import threading
import time
import unittest

import pandas as pd

from src.logic.map_layers_logic import (
    construir_camadas_estaticas, construir_camadas_veiculos
)


class MapLayersLogicTests(unittest.TestCase):
    def test_construir_camadas_estaticas_com_cache(self):
        lock = threading.Lock()
        cache = {}
        gtfs_lock = threading.Lock()

        def recarregar(_linhas):
            return None

        line_to_shape_coords = {
            "100": [[[-22.9, -43.2], [-22.91, -43.21]]]
        }
        line_to_stops_points = {
            "100": [
                {
                    "lat": -22.9,
                    "lon": -43.2,
                    "stop_name": "Parada A",
                    "stop_code": "001",
                    "stop_desc": "Desc",
                    "platform_code": "P1",
                }
            ]
        }

        shapes1, stops1 = construir_camadas_estaticas(
            modo="linhas",
            linhas_render=["100"],
            cores={"100": "#123456"},
            recarregar_gtfs_estatico_sob_demanda=recarregar,
            gtfs_data_lock=gtfs_lock,
            line_to_shape_coords=line_to_shape_coords,
            line_to_stops_points=line_to_stops_points,
            map_static_cache_lock=lock,
            map_static_cache=cache,
            map_static_cache_max_items=16,
            linha_publica_fn=lambda x: x,
            stop_sign_icon={
                "iconUrl": "x", "iconSize": [1, 1],
                "iconAnchor": [0, 0], "popupAnchor": [0, 0]
            },
            limit_list_for_render_fn=lambda values, _limit: values,
            max_stops_per_render=100,
        )

        shapes2, stops2 = construir_camadas_estaticas(
            modo="linhas",
            linhas_render=["100"],
            cores={"100": "#123456"},
            recarregar_gtfs_estatico_sob_demanda=recarregar,
            gtfs_data_lock=gtfs_lock,
            line_to_shape_coords=line_to_shape_coords,
            line_to_stops_points=line_to_stops_points,
            map_static_cache_lock=lock,
            map_static_cache=cache,
            map_static_cache_max_items=16,
            linha_publica_fn=lambda x: x,
            stop_sign_icon={
                "iconUrl": "x", "iconSize": [1, 1],
                "iconAnchor": [0, 0], "popupAnchor": [0, 0]
            },
            limit_list_for_render_fn=lambda values, _limit: values,
            max_stops_per_render=100,
        )

        self.assertEqual(len(shapes1), 1)
        self.assertEqual(len(stops1), 1)
        self.assertEqual(len(shapes2), 1)
        self.assertEqual(len(stops2), 1)
        self.assertEqual(shapes1[0].id, "shape-100-0")
        self.assertEqual(stops1[0].id, "stop-100-0")

    def test_construir_camadas_veiculos_modo_leve(self):
        sppo_df = pd.DataFrame([{
            "lat": -22.9, "lng": -43.2, "linha": "100",
            "ordem": "A", "tipo": "SPPO", "datahora": "10:00:00"
        }])
        brt_df = pd.DataFrame([{
            "lat": -22.91, "lng": -43.21, "linha": "200",
            "ordem": "B", "tipo": "BRT", "datahora": "10:00:00"
        }])

        onibus, brt = construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={"100": "#111", "200": "#222"},
            linhas_render=["100", "200"],
            lightweight_marker_threshold=1,
            build_geojson_cluster_layer_fn=(
                lambda df, lid: [lid, len(df)]
            ),
            group_vehicle_markers_fn=lambda markers: [markers],
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
        )

        self.assertEqual(onibus[0], "geojson-sppo")
        self.assertEqual(brt[0], "geojson-brt")

    def test_construir_camadas_veiculos_cache_hit(self):
        sppo_df = pd.DataFrame([{
            "lat": -22.9, "lng": -43.2, "linha": "100",
            "ordem": "A", "tipo": "SPPO", "datahora": "10:00:00"
        }])
        brt_df = pd.DataFrame([{
            "lat": -22.91, "lng": -43.21, "linha": "200",
            "ordem": "B", "tipo": "BRT", "datahora": "10:00:00"
        }])

        lock = threading.Lock()
        cache = {}
        calls = {"n": 0}

        def build_geo(df, layer_id):
            calls["n"] += 1
            return [layer_id, len(df)]

        out1 = construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={"100": "#111", "200": "#222"},
            linhas_render=["100", "200"],
            lightweight_marker_threshold=1,
            build_geojson_cluster_layer_fn=build_geo,
            group_vehicle_markers_fn=lambda markers: [markers],
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
            vehicle_layers_cache_lock=lock,
            vehicle_layers_cache=cache,
            vehicle_layers_cache_max_items=8,
        )

        out2 = construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={"100": "#111", "200": "#222"},
            linhas_render=["100", "200"],
            lightweight_marker_threshold=1,
            build_geojson_cluster_layer_fn=build_geo,
            group_vehicle_markers_fn=lambda markers: [markers],
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
            vehicle_layers_cache_lock=lock,
            vehicle_layers_cache=cache,
            vehicle_layers_cache_max_items=8,
        )

        self.assertEqual(calls["n"], 2)
        self.assertEqual(out1[0][0], "geojson-sppo")
        self.assertEqual(out2[0][0], "geojson-sppo")

    def test_construir_camadas_estaticas_limpa_cache_quando_lotado(self):
        lock = threading.Lock()
        gtfs_lock = threading.Lock()
        cache = {("old", str(i)): ([], []) for i in range(3)}

        shapes, stops = construir_camadas_estaticas(
            modo="linhas",
            linhas_render=["100"],
            cores={"100": "#123456"},
            recarregar_gtfs_estatico_sob_demanda=lambda _linhas: None,
            gtfs_data_lock=gtfs_lock,
            line_to_shape_coords={"100": [[[-22.9, -43.2], [-22.91, -43.21]]]},
            line_to_stops_points={"100": []},
            map_static_cache_lock=lock,
            map_static_cache=cache,
            map_static_cache_max_items=3,
            linha_publica_fn=lambda x: x,
            stop_sign_icon={
                "iconUrl": "x", "iconSize": [1, 1],
                "iconAnchor": [0, 0], "popupAnchor": [0, 0]
            },
            limit_list_for_render_fn=lambda values, _limit: values,
            max_stops_per_render=100,
        )

        self.assertEqual(len(shapes), 1)
        self.assertEqual(len(stops), 0)
        self.assertEqual(len(cache), 3)
        expected_key = (
            "linhas",
            "pt-BR",
            ("100",),
            (("100", "#123456"),),
        )
        self.assertIn(expected_key, cache)
        self.assertNotIn(("old", "0"), cache)

    def test_construir_camadas_estaticas_aceita_formato_legado_tupla(self):
        lock = threading.Lock()
        gtfs_lock = threading.Lock()
        cache = {}

        shapes, stops = construir_camadas_estaticas(
            modo="linhas",
            linhas_render=["100"],
            cores={"100": "#123456"},
            recarregar_gtfs_estatico_sob_demanda=lambda _linhas: None,
            gtfs_data_lock=gtfs_lock,
            line_to_shape_coords={"100": []},
            # Formato legado: (lat, lon, nome)
            line_to_stops_points={"100": [(-22.9, -43.2, "Parada antiga")]},
            map_static_cache_lock=lock,
            map_static_cache=cache,
            map_static_cache_max_items=16,
            linha_publica_fn=lambda x: x,
            stop_sign_icon={
                "iconUrl": "x", "iconSize": [1, 1],
                "iconAnchor": [0, 0], "popupAnchor": [0, 0]
            },
            limit_list_for_render_fn=lambda values, _limit: values,
            max_stops_per_render=100,
        )

        self.assertEqual(len(shapes), 0)
        self.assertEqual(len(stops), 1)

    def test_construir_camadas_estaticas_filtra_por_viewport(self):
        lock = threading.Lock()
        gtfs_lock = threading.Lock()
        cache = {}

        shapes, stops = construir_camadas_estaticas(
            modo="linhas",
            linhas_render=["100"],
            cores={"100": "#123456"},
            recarregar_gtfs_estatico_sob_demanda=lambda _linhas: None,
            gtfs_data_lock=gtfs_lock,
            line_to_shape_coords={
                "100": [
                    [[-22.90, -43.20], [-22.91, -43.21]],
                    [[-22.10, -44.10], [-22.11, -44.11]],
                ]
            },
            line_to_stops_points={
                "100": [
                    {
                        "lat": -22.90, "lon": -43.20, "stop_name": "A",
                        "stop_code": "1", "stop_desc": "", "platform_code": ""
                    },
                    {
                        "lat": -22.10, "lon": -44.10, "stop_name": "B",
                        "stop_code": "2", "stop_desc": "", "platform_code": ""
                    },
                ]
            },
            map_static_cache_lock=lock,
            map_static_cache=cache,
            map_static_cache_max_items=16,
            linha_publica_fn=lambda x: x,
            stop_sign_icon={
                "iconUrl": "x", "iconSize": [1, 1],
                "iconAnchor": [0, 0], "popupAnchor": [0, 0]
            },
            limit_list_for_render_fn=lambda values, _limit: values,
            max_stops_per_render=100,
            viewport_bounds=[[-22.95, -43.30], [-22.85, -43.10]],
        )

        self.assertEqual(len(shapes), 1)
        self.assertEqual(len(stops), 1)
        self.assertEqual(shapes[0].id, "shape-100-0")
        self.assertEqual(stops[0].id, "stop-100-0")

    def test_construir_camadas_estaticas_cache_respeita_viewport(self):
        lock = threading.Lock()
        gtfs_lock = threading.Lock()
        cache = {}

        kwargs = dict(
            modo="linhas",
            linhas_render=["100"],
            cores={"100": "#123456"},
            recarregar_gtfs_estatico_sob_demanda=lambda _linhas: None,
            gtfs_data_lock=gtfs_lock,
            line_to_shape_coords={
                "100": [
                    [[-22.90, -43.20], [-22.91, -43.21]],
                    [[-22.10, -44.10], [-22.11, -44.11]],
                ]
            },
            line_to_stops_points={
                "100": [
                    {
                        "lat": -22.90, "lon": -43.20, "stop_name": "A",
                        "stop_code": "1", "stop_desc": "", "platform_code": ""
                    },
                    {
                        "lat": -22.10, "lon": -44.10, "stop_name": "B",
                        "stop_code": "2", "stop_desc": "", "platform_code": ""
                    },
                ]
            },
            map_static_cache_lock=lock,
            map_static_cache=cache,
            map_static_cache_max_items=16,
            linha_publica_fn=lambda x: x,
            stop_sign_icon={
                "iconUrl": "x", "iconSize": [1, 1],
                "iconAnchor": [0, 0], "popupAnchor": [0, 0]
            },
            limit_list_for_render_fn=lambda values, _limit: values,
            max_stops_per_render=100,
        )

        shapes_a, stops_a = construir_camadas_estaticas(
            **kwargs,
            viewport_bounds=[[-22.95, -43.30], [-22.85, -43.10]],
        )
        shapes_b, stops_b = construir_camadas_estaticas(
            **kwargs,
            viewport_bounds=[[-22.15, -44.15], [-22.05, -44.05]],
        )

        self.assertEqual([shape.id for shape in shapes_a], ["shape-100-0"])
        self.assertEqual([stop.id for stop in stops_a], ["stop-100-0"])
        self.assertEqual([shape.id for shape in shapes_b], ["shape-100-1"])
        self.assertEqual([stop.id for stop in stops_b], ["stop-100-1"])

    def test_construir_camadas_veiculos_expira_cache_por_ttl(self):
        sppo_df = pd.DataFrame([{
            "lat": -22.9, "lng": -43.2, "linha": "100",
            "ordem": "A", "tipo": "SPPO", "datahora": "10:00:00"
        }])
        brt_df = pd.DataFrame([{
            "lat": -22.91, "lng": -43.21, "linha": "200",
            "ordem": "B", "tipo": "BRT", "datahora": "10:00:00"
        }])

        lock = threading.Lock()
        cache = {}
        calls = {"n": 0}

        def build_geo(df, layer_id):
            calls["n"] += 1
            return [layer_id, len(df)]

        construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={"100": "#111", "200": "#222"},
            linhas_render=["100", "200"],
            lightweight_marker_threshold=1,
            build_geojson_cluster_layer_fn=build_geo,
            group_vehicle_markers_fn=lambda markers: [markers],
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
            vehicle_layers_cache_lock=lock,
            vehicle_layers_cache=cache,
            vehicle_layers_cache_max_items=8,
            vehicle_layers_cache_ttl_seconds=0,
        )

        time.sleep(0.01)

        construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={"100": "#111", "200": "#222"},
            linhas_render=["100", "200"],
            lightweight_marker_threshold=1,
            build_geojson_cluster_layer_fn=build_geo,
            group_vehicle_markers_fn=lambda markers: [markers],
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
            vehicle_layers_cache_lock=lock,
            vehicle_layers_cache=cache,
            vehicle_layers_cache_max_items=8,
            vehicle_layers_cache_ttl_seconds=0,
        )

        self.assertEqual(calls["n"], 4)

    def test_construir_camadas_veiculos_fallback_fingerprint(self):
        # Sem colunas da assinatura leve -> fallback para fingerprint forte.
        sppo_df = pd.DataFrame([{
            "lat": -22.9, "lng": -43.2, "ordem": "A", "tipo": "SPPO"
        }])
        brt_df = pd.DataFrame([{
            "lat": -22.91, "lng": -43.21, "ordem": "B", "tipo": "BRT"
        }])

        lock = threading.Lock()
        cache = {}

        onibus1, brt1 = construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={},
            linhas_render=[],
            lightweight_marker_threshold=0,
            build_geojson_cluster_layer_fn=(
                lambda df, lid: [lid, len(df)]
            ),
            group_vehicle_markers_fn=lambda markers: markers,
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
            vehicle_layers_cache_lock=lock,
            vehicle_layers_cache=cache,
            vehicle_layers_cache_max_items=8,
        )

        onibus2, brt2 = construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={},
            linhas_render=[],
            lightweight_marker_threshold=0,
            build_geojson_cluster_layer_fn=(
                lambda df, lid: [lid, len(df)]
            ),
            group_vehicle_markers_fn=lambda markers: markers,
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
            vehicle_layers_cache_lock=lock,
            vehicle_layers_cache=cache,
            vehicle_layers_cache_max_items=8,
        )

        self.assertEqual(onibus1[0], "geojson-sppo")
        self.assertEqual(brt1[0], "geojson-brt")
        self.assertEqual(onibus2[0], "geojson-sppo")
        self.assertEqual(brt2[0], "geojson-brt")

    def test_construir_camadas_veiculos_popup_exibe_tarifa_gtfs(self):
        sppo_df = pd.DataFrame([{
            "lat": -22.9,
            "lng": -43.2,
            "linha": "100",
            "ordem": "A1",
            "tipo": "SPPO",
            "datahora": "2026-03-31 10:00:00",
            "velocidade": 12,
        }])
        brt_df = pd.DataFrame(columns=sppo_df.columns)

        onibus, brt = construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={"100": "#111"},
            linhas_render=["100"],
            lightweight_marker_threshold=999,
            build_geojson_cluster_layer_fn=(
                lambda df, lid: [lid, len(df)]
            ),
            group_vehicle_markers_fn=lambda markers: markers,
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={"100": "Linha 100"},
            line_to_fares={"100": "4.5"},
        )

        self.assertEqual(len(brt), 0)
        self.assertEqual(len(onibus), 1)

        popup = onibus[0].children[1]
        texts = [str(item.children) for item in popup.children.children]
        self.assertIn("Tarifa: R$ 4,50", texts)


if __name__ == "__main__":
    unittest.main()
