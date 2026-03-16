import unittest

import pandas as pd
from dash import html

from map_data_logic import (
    construir_legenda_linhas,
    construir_legenda_sem_veiculos,
    construir_legenda_veiculos,
    construir_legenda_vazia,
    filtrar_por_veiculos,
    linhas_ativas_por_veiculos,
    montar_opcoes_veiculos,
    split_gps_por_tipo,
)


def _collect_text(node):
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    children = getattr(node, "children", None)
    if children is None:
        return ""
    if isinstance(children, (list, tuple)):
        return " ".join(_collect_text(c) for c in children)
    return _collect_text(children)


class MapDataLogicTests(unittest.TestCase):
    def test_montar_opcoes_veiculos(self):
        dados = pd.DataFrame(
            [
                {"ordem": "1", "linha": "100", "tipo": "SPPO", "datahora": "2026-01-01 10:00:00"},
                {"ordem": "1", "linha": "100", "tipo": "SPPO", "datahora": "2026-01-01 09:59:00"},
                {"ordem": "2", "linha": "200", "tipo": "BRT", "datahora": "2026-01-01 09:58:00"},
            ]
        )

        opcoes = montar_opcoes_veiculos(dados, lambda ordem, linha, tipo: f"{ordem}-{linha}-{tipo}")
        self.assertEqual(len(opcoes), 2)
        self.assertEqual(opcoes[0]["value"], "1")

    def test_filtrar_por_veiculos(self):
        dados = pd.DataFrame(
            [
                {"ordem": "1", "linha": "100"},
                {"ordem": "2", "linha": "200"},
            ]
        )
        out = filtrar_por_veiculos(dados, ["2"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["ordem"], "2")

    def test_split_gps_por_tipo(self):
        dados = pd.DataFrame(
            [
                {"ordem": "1", "tipo": "SPPO"},
                {"ordem": "2", "tipo": "BRT"},
                {"ordem": "3", "tipo": "SPPO"},
            ]
        )
        sppo_df, brt_df = split_gps_por_tipo(dados)
        self.assertEqual(len(sppo_df), 2)
        self.assertEqual(len(brt_df), 1)

    def test_linhas_ativas_por_veiculos(self):
        dados = pd.DataFrame(
            [
                {"ordem": "A", "linha": "100"},
                {"ordem": "B", "linha": "200"},
                {"ordem": "C", "linha": "999"},
            ]
        )
        out = linhas_ativas_por_veiculos(dados, ["100", "200"])
        self.assertEqual(out, ["100", "200"])

    def test_construir_legenda_vazia_sem_dados_novos(self):
        legenda = construir_legenda_vazia(
            modo="linhas",
            fetch_ok=False,
            secao_icones=html.Div("icones"),
        )
        texto = _collect_text(legenda)
        self.assertIn("Sem dados novos no momento", texto)

    def test_construir_legenda_sem_veiculos(self):
        legenda = construir_legenda_sem_veiculos(
            secao_icones=html.Div("icones"),
        )
        texto = _collect_text(legenda)
        self.assertIn("Nenhum veículo selecionado", texto)

    def test_construir_legenda_veiculos(self):
        dados = pd.DataFrame(
            [
                {"ordem": "A1", "linha": "100", "tipo": "SPPO", "datahora": "2026-01-01 10:00:00"},
            ]
        )
        legenda = construir_legenda_veiculos(
            dados_filtrados=dados,
            cores={"100": "#111111"},
            linhas_dict={"100": "Linha Centro"},
            linha_exibicao_fn=lambda x: x,
            secao_icones=html.Div("icones"),
        )
        texto = _collect_text(legenda)
        self.assertIn("Veículo A1", texto)
        self.assertIn("Linha 100", texto)

    def test_construir_legenda_linhas(self):
        legenda = construir_legenda_linhas(
            linhas_render=["100"],
            cores={"100": "#111111"},
            linhas_dict={"100": "Linha Centro"},
            linha_exibicao_fn=lambda x: f"L{x}",
            secao_icones=html.Div("icones"),
        )
        texto = _collect_text(legenda)
        self.assertIn("L100", texto)
        self.assertIn("Linha Centro", texto)


if __name__ == "__main__":
    unittest.main()
