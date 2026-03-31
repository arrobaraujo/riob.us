import unittest

import pandas as pd
from shapely.geometry import Polygon

from src.utils.geo_helpers import build_point_mask


class GeoHelpersTests(unittest.TestCase):
    def test_build_point_mask_covered_by(self):
        df = pd.DataFrame(
            [
                {"longitude": -43.2, "latitude": -22.9},
                {"longitude": -45.0, "latitude": -21.0},
            ]
        )
        poly = Polygon([
            (-43.5, -23.2), (-43.0, -23.2), (-43.0, -22.6),
            (-43.5, -22.6), (-43.5, -23.2)
        ])
        mask = build_point_mask(
            df,
            lon_col="longitude",
            lat_col="latitude",
            polygon=poly,
            prepared_polygon=None,
            predicate="covered_by",
        )
        self.assertEqual(mask.tolist(), [True, False])

    def test_build_point_mask_within(self):
        df = pd.DataFrame(
            [
                {"longitude": -43.2, "latitude": -22.9},
                {"longitude": -43.0, "latitude": -22.9},
            ]
        )
        poly = Polygon([
            (-43.5, -23.2), (-43.0, -23.2), (-43.0, -22.6),
            (-43.5, -22.6), (-43.5, -23.2)
        ])
        mask = build_point_mask(
            df,
            lon_col="longitude",
            lat_col="latitude",
            polygon=poly,
            prepared_polygon=None,
            predicate="within",
        )
        self.assertEqual(mask.tolist(), [True, False])


if __name__ == "__main__":
    unittest.main()
