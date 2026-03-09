import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from gps_data_logic import fetch_gps_data_service, sanitize_selection


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, _url, headers=None, timeout=20):
        return _FakeResponse(200, self.payload)


class GpsDataLogicTests(unittest.TestCase):
    def test_sanitize_selection(self):
        values = [1, "", "  ", "A", None]
        self.assertEqual(sanitize_selection(values), ["1", "A", "None"])

    def test_fetch_service_mode_linhas_sem_linhas(self):
        out = fetch_gps_data_service(
            linhas_sel=[],
            veiculos_sel=[],
            modo="linhas",
            http_session_sppo=_FakeSession([]),
            http_session_brt=_FakeSession({"veiculos": []}),
            processar_dados_gps_fn=lambda df, _cfg: df,
            gps_config={"sppo": {}, "brt": {}},
            linhas_short=["100"],
            filtrar_pontos_fora_municipio_fn=lambda df: df,
            garagens_polygon=None,
            garagens_polygon_prepared=None,
            build_point_mask_fn=lambda *args, **kwargs: pd.Series([], dtype=bool),
        )
        self.assertTrue(out.empty)

    def test_fetch_service_filtra_e_projeta_colunas(self):
        agora = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)

        sppo_payload = [
            {
                "ordem": "A1",
                "linha": "100",
                "latitude": -22.9,
                "longitude": -43.2,
                "velocidade": 21,
                "sentido": "ida",
                "datahora": agora,
            }
        ]
        brt_payload = {
            "veiculos": [
                {
                    "ordem": "B1",
                    "linha": "200",
                    "latitude": -22.95,
                    "longitude": -43.25,
                    "velocidade": 33,
                    "sentido": "volta",
                    "datahora": agora,
                }
            ]
        }

        def processar(df, cfg):
            out = df.copy()
            out["tipo"] = cfg.get("tipo", "X")
            out["datahora"] = pd.to_datetime(out["datahora"], errors="coerce")
            return out

        out = fetch_gps_data_service(
            linhas_sel=["100"],
            veiculos_sel=[],
            modo="linhas",
            http_session_sppo=_FakeSession(sppo_payload),
            http_session_brt=_FakeSession(brt_payload),
            processar_dados_gps_fn=processar,
            gps_config={"sppo": {"tipo": "SPPO"}, "brt": {"tipo": "BRT"}},
            linhas_short=["100", "200"],
            filtrar_pontos_fora_municipio_fn=lambda df: df,
            garagens_polygon=None,
            garagens_polygon_prepared=None,
            build_point_mask_fn=lambda *args, **kwargs: pd.Series([False] * len(args[0]), index=args[0].index),
        )

        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["ordem"], "A1")
        self.assertEqual(list(out.columns), ["ordem", "lat", "lng", "linha", "velocidade", "tipo", "sentido", "datahora"])


if __name__ == "__main__":
    unittest.main()
