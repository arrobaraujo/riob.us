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
        
        # New logic replaces endpoints with surgical projections and prefers shortest path
        # It should at least contain the points between the snapped indices
        self.assertGreaterEqual(len(clipped), 2)
        # First and last points should be the surgical projections (close to start/end coords)
        self.assertLess(dist_sq(clipped[0], start_coord), 1e-4)
        self.assertLess(dist_sq(clipped[-1], end_coord), 1e-4)

    def test_clip_polyline_reversed_indices(self):
        # Path: 0 -> 1 -> 2. Travel: 2 -> 1 -> 0.
        poly = [[0, 0], [1, 1], [2, 2]]
        # Start at [1.9, 1.9] (near index 2), end at [0.1, 0.1] (near index 0)
        clipped = _clip_polyline(poly, [1.9, 1.9], [0.1, 0.1])
        
        # Should return a reversed path from start to end
        self.assertGreaterEqual(len(clipped), 2)
        self.assertLess(dist_sq(clipped[0], [1.9, 1.9]), 0.1)
        self.assertLess(dist_sq(clipped[-1], [0.1, 0.1]), 0.1)
        # Midpoint should be [1,1]
        self.assertIn([1, 1], clipped)

def dist_sq(p1, p2):
    return (p1[0] - p2[0])**2 + (p1[1] - p2[1])**2

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
