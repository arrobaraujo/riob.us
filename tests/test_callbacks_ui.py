import unittest

from callbacks_ui import (
    _normalize_multi_values,
    _parse_deep_link,
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


if __name__ == "__main__":
    unittest.main()
