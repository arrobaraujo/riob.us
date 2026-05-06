import unittest
from src.logic.transitous_logic import _clip_polyline, itineraries_to_geojson

class TransitousLogicTests(unittest.TestCase):
    def test_clip_polyline_no_coords(self):
        # Should return original polyline if no start/end coords provided
        poly = [[-22.9, -43.2], [-22.91, -43.21]]
        clipped = _clip_polyline(poly, None, None)
        self.assertEqual(clipped, poly)

    def test_clip_polyline_snapping(self):
        # Simple straight line
        poly = [
            [-22.90, -43.20], # Index 0
            [-22.91, -43.21], # Index 1
            [-22.92, -43.22], # Index 2
            [-22.93, -43.23], # Index 3
            [-22.94, -43.24]  # Index 4
        ]
        
        # Start coordinate closer to index 1
        start_coord = [-22.911, -43.211]
        # End coordinate closer to index 3
        end_coord = [-22.929, -43.229]
        
        clipped = _clip_polyline(poly, start_coord, end_coord)
        
        # The logic injects the exact start_coord and end_coord at the ends
        expected = [start_coord] + poly[1:4] + [end_coord]
        self.assertEqual(clipped, expected)
        self.assertEqual(len(clipped), 5)
        self.assertEqual(clipped[0], start_coord)
        self.assertEqual(clipped[-1], end_coord)

    def test_clip_polyline_reversed_indices(self):
        # If for some reason snapping returns end before start, should return original or sensible default
        poly = [[0, 0], [1, 1], [2, 2]]
        # Start snaps to 2, end snaps to 0
        clipped = _clip_polyline(poly, [1.9, 1.9], [0.1, 0.1])
        # Even if reversed, it returns [end_pt] + poly[i_min:i_max+1] + [start_pt] 
        # or something similar based on distance.
        # In this case: poly[i_min:i_max+1] is [[0,0], [1,1], [2,2]]
        # clipped[0] is closer to start_pt? dist([0,0], [1.9,1.9]) vs dist([2,2], [1.9,1.9])
        # [2,2] is closer to [1.9, 1.9]. So it enters the 'else' branch:
        # insert(0, end_pt) -> [0.1, 0.1], append(start_pt) -> [1.9, 1.9]
        expected = [[0.1, 0.1], [0, 0], [1, 1], [2, 2], [1.9, 1.9]]
        self.assertEqual(clipped, expected)

    def test_itineraries_to_geojson_basic(self):
        itinerary = {
            "legs": [
                {
                    "type": "transit",
                    "from_lat": -22.90, "from_lon": -43.20,
                    "to_lat": -22.92, "to_lon": -43.22,
                    "polyline": "bz_nCdz~jG_u@_u@", # Sample polyline string
                    "line": "100"
                },
                {
                    "type": "WALK",
                    "polyline": "bz_nCdz~jG_u@_u@"
                }
            ]
        }
        
        result = itineraries_to_geojson(itinerary)
        geojson = result["geojson"]
        self.assertEqual(geojson["type"], "FeatureCollection")
        # Should have 2 features (1 transit leg, 1 walk leg)
        # Note: it also adds stops as points, so it might have more features
        self.assertGreaterEqual(len(geojson["features"]), 2)
        
        # Transit feature should have color and line info
        transit_feat = next(f for f in geojson["features"] if f["properties"]["type"] == "transit")
        self.assertEqual(transit_feat["properties"]["line"], "100")

if __name__ == "__main__":
    unittest.main()
