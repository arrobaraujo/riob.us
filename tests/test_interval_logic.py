import unittest

from src.logic.interval_logic import compute_poll_interval_ms


class IntervalLogicTests(unittest.TestCase):
    def test_idle_interval_when_no_selection(self):
        out = compute_poll_interval_ms(
            tab_filtro="linhas",
            linhas_sel=[],
            veiculos_sel=[],
            last_fetch_had_data=True,
            idle_ms=90000,
            lines_active_ms=30000,
            vehicles_active_ms=20000,
        )
        self.assertEqual(out, 90000)

    def test_active_lines_interval(self):
        out = compute_poll_interval_ms(
            tab_filtro="linhas",
            linhas_sel=["100"],
            veiculos_sel=[],
            last_fetch_had_data=True,
            idle_ms=90000,
            lines_active_ms=30000,
            vehicles_active_ms=20000,
        )
        self.assertEqual(out, 30000)

    def test_active_vehicles_interval(self):
        out = compute_poll_interval_ms(
            tab_filtro="veiculos",
            linhas_sel=[],
            veiculos_sel=["A1"],
            last_fetch_had_data=True,
            idle_ms=90000,
            lines_active_ms=30000,
            vehicles_active_ms=20000,
        )
        self.assertEqual(out, 20000)

    def test_backoff_when_fetch_has_no_data(self):
        out = compute_poll_interval_ms(
            tab_filtro="veiculos",
            linhas_sel=[],
            veiculos_sel=["A1"],
            last_fetch_had_data=False,
            idle_ms=90000,
            lines_active_ms=30000,
            vehicles_active_ms=20000,
        )
        self.assertEqual(out, 40000)


if __name__ == "__main__":
    unittest.main()
