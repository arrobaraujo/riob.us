import unittest
from urllib.parse import parse_qs
import dash

from src.i18n.localization import locale_from_search, normalize_locale, t
from src.ui.ui_layout import build_app_layout, get_localized_index_string
from src.core.app_runtime import sincronizar_lang_na_url


class LocalizationTests(unittest.TestCase):
    def test_normalize_locale_aliases(self):
        self.assertEqual(normalize_locale("pt"), "pt-BR")
        self.assertEqual(normalize_locale("en-US"), "en")
        self.assertEqual(normalize_locale("es-MX"), "es")

    def test_locale_from_search(self):
        self.assertEqual(locale_from_search("?lang=en"), "en")
        self.assertEqual(locale_from_search("?foo=1&lang=es"), "es")
        self.assertIsNone(locale_from_search("?foo=1"))

    def test_translation_fallback(self):
        self.assertEqual(t("unknown", "tab.lines"), "Linhas")
        self.assertEqual(t("en", "missing.key"), "missing.key")

    def test_localized_index_string_en(self):
        html_index = get_localized_index_string("en")
        self.assertIn('<html lang="en">', html_index)
        self.assertIn("Loading application", html_index)
        self.assertIn("Bus tracking - Rio de Janeiro", html_index)

    def test_localized_index_string_es(self):
        html_index = get_localized_index_string("es")
        self.assertIn('<html lang="es">', html_index)
        self.assertIn("Cargando aplicación", html_index)
        self.assertIn("Consulta de autobuses - Río de Janeiro", html_index)

    def test_layout_includes_localized_map_control_labels(self):
        layout_en = build_app_layout([], lambda value: value, "dev", locale="en")
        as_text_en = str(layout_en)
        self.assertIn("Carto Light", as_text_en)
        self.assertIn("Routes", as_text_en)

        layout_es = build_app_layout([], lambda value: value, "dev", locale="es")
        as_text_es = str(layout_es)
        self.assertIn("Carto Oscuro", as_text_es)
        self.assertIn("Mi posición", as_text_es)

    def test_sync_lang_url_removes_lang_query_and_keeps_base_path_for_pt(self):
        out_path, out_search = sincronizar_lang_na_url(
            "pt-BR",
            "/en/linhas/LECD137",
            "?lang=en&foo=1",
        )
        self.assertEqual(out_path, "/linhas/LECD137")
        parsed = parse_qs(str(out_search).lstrip("?"), keep_blank_values=False)
        self.assertEqual(parsed.get("foo"), ["1"])
        self.assertIsNone(parsed.get("lang"))

    def test_sync_lang_url_uses_path_prefix_for_non_default_locale(self):
        out_path, out_search = sincronizar_lang_na_url(
            "en",
            "/linhas/LECD137",
            "",
        )
        self.assertEqual(out_path, "/en/linhas/LECD137")
        self.assertIs(out_search, dash.no_update)


if __name__ == "__main__":
    unittest.main()
