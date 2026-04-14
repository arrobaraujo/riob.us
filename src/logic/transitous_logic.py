import requests
from datetime import datetime
import pytz

RIO_TZ = pytz.timezone("America/Sao_Paulo")
TRANSITOUS_HEADERS = {
    "User-Agent": "RioB.us-App/1.0 (https://github.com/arrobaraujo/riob.us)"
}

def iso_to_ts(iso_str):
    """Converte string ISO 8601 do Transitous para timestamp Unix."""
    if not iso_str:
        return 0
    try:
        # Substitui Z por +00:00 para compatibilidade universal se necessário, 
        # embora Python 3.11+ suporte Z nativamente.
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 0

def fetch_geocoding(text, api_url="https://api.transitous.org/api/v1/geocode"):
    """Busca coordenadas para um endereço, priorizando o Rio de Janeiro."""
    params = {
        "text": text,
        "boundary.rect.min_lat": -23.08,
        "boundary.rect.max_lat": -22.74,
        "boundary.rect.min_lon": -43.79,
        "boundary.rect.max_lon": -43.09,
        "size": 1
    }
    try:
        r = requests.get(api_url, params=params, headers=TRANSITOUS_HEADERS, timeout=5)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            item = data[0]
            return {"lat": item.get("lat"), "lng": item.get("lon")}
    except Exception as e:
        print(f"Erro na geocoficação: {e}")
    return None

def fetch_routing(start, end, api_url="https://api.transitous.org/api/v1/plan"):
    """Busca rotas entre dois pontos usando a API Transitous (MOTIS 2)."""
    # Envia em UTC real para evitar confusão de fuso horário na API
    now_utc = datetime.now(pytz.UTC)
    iso_time = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    params = {
        "fromPlace": f"{start['lat']},{start['lng']}",
        "toPlace": f"{end['lat']},{end['lng']}",
        "arriveBy": "false",
        "time": iso_time,
        "mode": "TRANSIT,WALK",
    }
    try:
        r = requests.get(api_url, params=params, headers=TRANSITOUS_HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Erro na busca de rotas: {e}")
    return None

def parse_transitous_response(data):
    """Transforma a resposta da API em uma lista simplificada de itinerários."""
    itineraries = []
    if not data or "itineraries" not in data:
        return itineraries

    for it in data["itineraries"]:
        legs = []
        for leg in it.get("legs", []):
            # Normaliza nomes de origem/destino da API
            leg_from = leg["from"]["name"]
            leg_to = leg["to"]["name"]
            if leg_from == "START": leg_from = "__ORIGIN__"
            if leg_to == "END": leg_to = "__DESTINATION__"
            if leg_from == "END": leg_from = "__DESTINATION__" # Caso o motor inverta
            if leg_to == "START": leg_to = "__ORIGIN__"

            legs.append({
                "type": (leg.get("mode") or "WALK").upper(),
                "line": leg.get("routeShortName", ""),
                "from": leg_from,
                "to": leg_to,
                "departure": iso_to_ts(leg.get("startTime")),
                "arrival": iso_to_ts(leg.get("endTime")),
                "duration": leg.get("duration", 0),
                "polyline": leg.get("legGeometry", {}).get("points", ""),
                "stops": [
                    {"name": st.get("name"), "lat": st.get("lat"), "lon": st.get("lon")}
                    for st in leg.get("intermediateStops", []) if st.get("lat") and st.get("lon")
                ]
            })
        
        itineraries.append({
            "duration": it.get("duration", 0),
            "departure": iso_to_ts(it.get("startTime")),
            "arrival": iso_to_ts(it.get("endTime")),
            "transfers": it.get("transfers", 0),
            "legs": legs
        })
    return itineraries

def itineraries_to_geojson(itinerary, line_to_color=None):
    """Converte um itinerário para FeatureCollection GeoJSON com estilos por segmento."""
    import polyline
    features = []
    
    if line_to_color is None:
        line_to_color = {}
    
    for leg in itinerary.get("legs", []):
        if not leg.get("polyline"):
            continue
            
        try:
            coords = polyline.decode(leg["polyline"], 7)
            # Inverte para (lon, lat) para o padrão GeoJSON
            geojson_coords = [[c[1], c[0]] for c in coords]
            
            is_walk = leg["type"] == "WALK"
            line_label = leg.get("line", "")
            
            if is_walk:
                leg_color = "#3b82f6"
            else:
                from src.logic.gtfs_static_logic import _normalize_line_key
                norm_line = _normalize_line_key(line_label)
                leg_color = line_to_color.get(norm_line, "#ef4444")
                
            properties = {
                "type": leg["type"],
                "line": line_label,
                "color": leg_color,
                "dashArray": "5, 10" if is_walk else None,
                "weight": 4 if is_walk else 6,
                "opacity": 0.6 if is_walk else 0.9,
                "is_walk": is_walk
            }
            
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": geojson_coords
                },
                "properties": properties
            })
            
            # Add stops as dots
            for stop in leg.get("stops", []):
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [stop["lon"], stop["lat"]]
                    },
                    "properties": {
                        "type": "stop",
                        "name": stop["name"],
                        "color": leg_color,
                    }
                })
                
        except Exception as e:
            print(f"Erro ao decodificar polyline do trecho: {e}")
            
    # Calcula os limites (bounds) para o auto-zoom
    min_lat, min_lon = 90, 180
    max_lat, max_lon = -90, -180
    has_coords = False
    
    for f in features:
        if f["geometry"]["type"] == "LineString":
            for lon, lat in f["geometry"]["coordinates"]:
                min_lat, min_lon = min(min_lat, lat), min(min_lon, lon)
                max_lat, max_lon = max(max_lat, lat), max(max_lon, lon)
                has_coords = True
        elif f["geometry"]["type"] == "Point":
            lon, lat = f["geometry"]["coordinates"]
            min_lat, min_lon = min(min_lat, lat), min(min_lon, lon)
            max_lat, max_lon = max(max_lat, lat), max(max_lon, lon)
            has_coords = True
            
    bounds = [[min_lat, min_lon], [max_lat, max_lon]] if has_coords else None
    
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "bounds": bounds
    }
