import unittest
from unittest.mock import patch

from src.core.app_runtime import server


class StatusRouteI18nTests(unittest.TestCase):
    def setUp(self):
        self.client = server.test_client()

    def _fake_status(self):
        return {
            "status": "healthy",
            "gtfs_loaded": True,
            "last_gps_update": "2026-04-03T10:00:00-03:00",
            "last_fetch_had_data": True,
            "cache": {
                "static_layers_items": 2,
                "vehicle_layers_items": 3,
                "svg_items": 4,
                "vehicle_layers_hit_rate": 95.5,
            },
            "build_id": "test-build",
            "memory_mb": 123.4,
        }

    def test_status_route_in_english(self):
        with patch("src.core.app_runtime._build_health_status", return_value=self._fake_status()):
            response = self.client.get("/status?lang=en")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("<html lang=\"en\">", text)
        self.assertIn("RioB.us status", text)
        self.assertIn("GTFS loaded", text)
        self.assertIn("Technical JSON", text)

    def test_status_route_in_spanish(self):
        with patch("src.core.app_runtime._build_health_status", return_value=self._fake_status()):
            response = self.client.get("/status?lang=es")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("<html lang=\"es\">", text)
        self.assertIn("Estado de RioB.us", text)
        self.assertIn("GTFS cargado", text)
        self.assertIn("JSON técnico", text)

    def test_deeplink_line_query_lang_english(self):
        response = self.client.get("/linhas/LECD137?lang=en")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Line LECD137 in real time", text)
        self.assertIn('property="og:locale" content="en_US"', text)

    def test_deeplink_line_accept_language_spanish(self):
        response = self.client.get(
            "/linhas/LECD137",
            headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"},
        )
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Línea LECD137 en tiempo real", text)
        self.assertIn('property="og:locale" content="es_ES"', text)

    def test_deeplink_line_path_prefix_locale(self):
        response = self.client.get("/en/linhas/LECD137")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Line LECD137 in real time", text)
        self.assertIn('id="canonical-link" rel="canonical" href="https://riob.us/linhas/LECD137"', text)

    def test_root_query_redirects_to_localized_path(self):
        response = self.client.get("/?linha=LECD137&lang=es", follow_redirects=False)
        self.assertEqual(response.status_code, 301)
        self.assertIn("/es/linhas/LECD137", response.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
