import unittest

import dash

from src.ui.callbacks_ui import (
    _normalize_multi_values,
    _parse_deep_link,
    _resolve_tab_filter_state,
    _resolve_vehicle_alias,
    _split_vehicle_options_with_selected_fallback,
)


class CallbacksUiHelpersTests(unittest.TestCase):
    def test_normalize_multi_values_accepts_string(self):
        self.assertEqual(_normalize_multi_values("D53573"), ["D53573"])

    def test_normalize_multi_values_removes_empty(self):
        self.assertEqual(_normalize_multi_values(["", " A50001 ", None]), ["A50001"])

    def test_parse_deep_link_linhas(self):
        self.assertEqual(
            _parse_deep_link("/linhas/LECD137", None),
            ("linhas", "LECD137"),
        )

    def test_parse_deep_link_veiculos_desabilitado(self):
        self.assertIsNone(_parse_deep_link("/veiculos/A50001", None))

    def test_parse_deep_link_invalido(self):
        self.assertIsNone(_parse_deep_link("/status", None))

    def test_parse_deep_link_query_linha(self):
        self.assertEqual(
            _parse_deep_link("/", "?linha=LECD137"),
            ("linhas", "LECD137"),
        )

    def test_parse_deep_link_query_veiculo_desabilitado(self):
        self.assertIsNone(_parse_deep_link("/", "?veiculo=D53573"))

    def test_resolve_vehicle_alias_por_digitos(self):
        options = [
            {"label": "A50001 · LECD137 · SPPO", "value": "A50001"},
            {"label": "B50002 · LECD138 · SPPO", "value": "B50002"},
        ]
        self.assertEqual(_resolve_vehicle_alias(options, "50001"), "A50001")

    def test_resolve_vehicle_alias_sem_match(self):
        options = [
            {"label": "A50001 · LECD137 · SPPO", "value": "A50001"},
        ]
        self.assertEqual(_resolve_vehicle_alias(options, "99999"), "99999")

    def test_selected_fallback_keeps_deeplink_visible_when_options_empty(self):
        selected_opts, unselected_opts, known_values = (
            _split_vehicle_options_with_selected_fallback([], ["A50001"])
        )
        self.assertEqual(unselected_opts, [])
        self.assertEqual(known_values, set())
        self.assertEqual(len(selected_opts), 1)
        self.assertEqual(selected_opts[0]["value"], "A50001")
        self.assertIn("selecionado", selected_opts[0]["label"])

    def test_selected_fallback_handles_string_value(self):
        selected_opts, unselected_opts, known_values = (
            _split_vehicle_options_with_selected_fallback([], "D53573")
        )
        self.assertEqual(unselected_opts, [])
        self.assertEqual(known_values, set())
        self.assertEqual(len(selected_opts), 1)
        self.assertEqual(selected_opts[0]["value"], "D53573")

    def test_tab_switch_to_vehicles_preserves_selected_lines(self):
        result = _resolve_tab_filter_state(
            tab_value="veiculos",
            pathname="/",
            search="",
            linhas_sel=["LECD137", "LECD138"],
            linhas_opts=[
                {"label": "137", "value": "LECD137"},
                {"label": "138", "value": "LECD138"},
            ],
            triggers={"tabs-filtro"},
        )
        self.assertEqual(result[0], "veiculos")
        self.assertIs(result[1], dash.no_update)
        self.assertIs(result[2], dash.no_update)
        self.assertIsNone(result[3])

    def test_invalid_persisted_lines_are_removed_with_warning(self):
        result = _resolve_tab_filter_state(
            tab_value="linhas",
            pathname="/",
            search="",
            linhas_sel=["LECD137", "INVALIDA"],
            linhas_opts=[
                {"label": "137", "value": "LECD137"},
            ],
            triggers={"tabs-filtro"},
        )
        self.assertEqual(result[0], "linhas")
        self.assertEqual(result[1], ["LECD137"])
        self.assertEqual(result[2], [])
        self.assertIn("foram removidas", result[3])

    def test_tab_round_trip_preserves_lines_context(self):
        linhas_opts = [
            {"label": "137", "value": "LECD137"},
            {"label": "138", "value": "LECD138"},
        ]

        go_to_vehicles = _resolve_tab_filter_state(
            tab_value="veiculos",
            pathname="/",
            search="",
            linhas_sel=["LECD137", "LECD138"],
            linhas_opts=linhas_opts,
            triggers={"tabs-filtro"},
        )
        self.assertEqual(go_to_vehicles[0], "veiculos")
        self.assertIs(go_to_vehicles[1], dash.no_update)
        self.assertIs(go_to_vehicles[2], dash.no_update)
        self.assertIsNone(go_to_vehicles[3])

        back_to_lines = _resolve_tab_filter_state(
            tab_value="linhas",
            pathname="/",
            search="",
            linhas_sel=["LECD137", "LECD138"],
            linhas_opts=linhas_opts,
            triggers={"tabs-filtro"},
        )
        self.assertEqual(back_to_lines[0], "linhas")
        self.assertIs(back_to_lines[1], dash.no_update)
        self.assertEqual(back_to_lines[2], [])
        self.assertIsNone(back_to_lines[3])


if __name__ == "__main__":
    unittest.main()
