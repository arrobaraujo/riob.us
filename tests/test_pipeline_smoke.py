import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.logic.gps_data_logic import fetch_gps_data_service
from src.logic.map_data_logic import split_gps_por_tipo
from src.logic.map_layers_logic import construir_camadas_veiculos


class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload

    def get(self, _url, headers=None, timeout=20):
        return _FakeResponse(self._payload)


class PipelineSmokeTests(unittest.TestCase):
    def test_fetch_split_and_vehicle_layers_pipeline(self):
        hoje_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        agora = hoje_utc - timedelta(hours=3)
        base_payload_sppo = [
            {
                "ordem": "A1",
                "linha": "100",
                "latitude": -22.90,
                "longitude": -43.20,
                "velocidade": 20,
                "sentido": "ida",
                "datahora": agora,
            }
        ]
        base_payload_brt = {
            "veiculos": [
                {
                    "ordem": "B1",
                    "linha": "200",
                    "latitude": -22.91,
                    "longitude": -43.21,
                    "velocidade": 25,
                    "sentido": "volta",
                    "datahora": agora,
                }
            ]
        }

        def processar(df, cfg):
            out = df.copy()
            out["tipo"] = cfg["tipo"]
            out["datahora"] = pd.to_datetime(out["datahora"], errors="coerce")
            return out

        dados = fetch_gps_data_service(
            linhas_sel=["100", "200"],
            veiculos_sel=[],
            modo="linhas",
            http_session_sppo=_FakeSession(base_payload_sppo),
            http_session_brt=_FakeSession(base_payload_brt),
            processar_dados_gps_fn=processar,
            gps_config={"sppo": {"tipo": "SPPO"}, "brt": {"tipo": "BRT"}},
            linhas_short=["100", "200"],
            filtrar_pontos_fora_municipio_fn=lambda df: df,
            garagens_polygon=None,
            garagens_polygon_prepared=None,
            build_point_mask_fn=(
                lambda *args, **kwargs: pd.Series(
                    [False] * len(args[0]), index=args[0].index
                )
            ),
        )

        sppo_df, brt_df = split_gps_por_tipo(dados)

        onibus, brt = construir_camadas_veiculos(
            sppo_df=sppo_df,
            brt_df=brt_df,
            cores={"100": "#111111", "200": "#222222"},
            linhas_render=["100", "200"],
            lightweight_marker_threshold=0,
            build_geojson_cluster_layer_fn=(
                lambda df, lid: [lid, len(df)]
            ),
            group_vehicle_markers_fn=lambda markers: markers,
            make_vehicle_icon_fn=lambda bearing, cor: ["url", [1, 1], [0, 0]],
            linha_publica_fn=lambda x: x,
            linhas_dict={},
        )

        self.assertEqual(len(sppo_df), 1)
        self.assertEqual(len(brt_df), 1)
        self.assertEqual(onibus[0], "geojson-sppo")
        self.assertEqual(brt[0], "geojson-brt")


if __name__ == "__main__":
    unittest.main()
