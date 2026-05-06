import sys
import os
sys.path.append(os.getcwd())
from src.ui.callbacks_ui import atualizar_mapa_trajeto

geojson_data = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-43.2, -22.9], [-43.21, -22.91]]}, "properties": {"type": "transit", "color": "#ff0000", "dashArray": None, "weight": 6, "opacity": 0.9}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-43.2, -22.9]}, "properties": {"type": "stop", "name": "Stop A", "color": "#ff0000"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-43.21, -22.91]}, "properties": {"type": "stop", "name": "Stop B", "color": "#ff0000"}}
    ],
    "start_pt": [-43.2, -22.9],
    "end_pt": [-43.21, -22.91]
}

try:
    res = atualizar_mapa_trajeto(geojson_data, "pt-BR")
    print(f"Success! Returned {len(res)} children.")
except Exception as e:
    import traceback
    traceback.print_exc()
