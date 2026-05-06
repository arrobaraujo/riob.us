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
                "from_lat": leg.get("from", {}).get("lat"),
                "from_lon": leg.get("from", {}).get("lon"),
                "to_lat": leg.get("to", {}).get("lat"),
                "to_lon": leg.get("to", {}).get("lon"),
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

def _clip_polyline(coords, start_pt, end_pt):
    """
    Corta uma lista de coordenadas [(lat, lon), ...] para iniciar e terminar
    nos pontos mais próximos de start_pt e end_pt, mantendo a direção da rota
    e evitando problemas com trajetos circulares (loops).
    """
    if not coords or not start_pt or not end_pt:
        return coords

    def dist_sq(p1, p2):
        return (p1[0] - p2[0])**2 + (p1[1] - p2[1])**2

    def project_on_segment(p, a, b):
        ax, ay, bx, by, px, py = a[0], a[1], b[0], b[1], p[0], p[1]
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0: return a
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        return [ax + t * dx, ay + t * dy]

    n = len(coords)
    # Penalty to prefer shorter paths (approx 1 meter per point in degrees squared)
    penalty_factor = 1e-10

    # We want to find (i, j) that minimizes dist(coords[i], start_pt) + dist(coords[j], end_pt) + penalty * |i - j|
    
    # Sweep 1: i <= j
    best_pair_1 = (0, 0)
    min_score_1 = float('inf')
    best_i = 0
    min_d_start = float('inf')
    
    for j in range(n):
        d_start = dist_sq(coords[j], start_pt)
        if d_start <= min_d_start: # Use <= to pick the latest occurrence
            min_d_start = d_start
            best_i = j
        
        d_end = dist_sq(coords[j], end_pt)
        score = min_d_start + d_end + (j - best_i) * penalty_factor
        if score < min_score_1:
            min_score_1 = score
            best_pair_1 = (best_i, j)

    # Sweep 2: i > j
    best_pair_2 = (0, 0)
    min_score_2 = float('inf')
    best_i = 0
    min_d_end = float('inf')
    
    for j in range(n):
        d_end = dist_sq(coords[j], end_pt)
        if d_end <= min_d_end: # Use <= to pick the latest occurrence of end_pt in this sweep
            min_d_end = d_end
            best_i = j
            
        d_start = dist_sq(coords[j], start_pt)
        score = min_d_end + d_start + (j - best_i) * penalty_factor
        if score < min_score_2:
            min_score_2 = score
            best_pair_2 = (j, best_i) # Order is (start_idx, end_idx)

    # Choose best sweep
    if min_score_1 <= min_score_2:
        idx1, idx2 = best_pair_1
        reverse = False
    else:
        idx1, idx2 = best_pair_2
        reverse = True

    # Extract raw segment
    if not reverse:
        clipped = coords[idx1 : idx2 + 1]
    else:
        # If reversed, we still extract the segment but it's logically backwards
        clipped = coords[min(idx1, idx2) : max(idx1, idx2) + 1]
        clipped = clipped[::-1]

    if len(clipped) < 2:
        return [start_pt, end_pt]

    # Surgical adjustment: project start/end onto adjacent segments to avoid "hooks"
    def get_surgical_point(pt, center_idx, full_coords):
        best_p = full_coords[center_idx]
        best_d = dist_sq(pt, best_p)
        
        # Check segment before
        if center_idx > 0:
            p_prev = project_on_segment(pt, full_coords[center_idx-1], full_coords[center_idx])
            d_prev = dist_sq(pt, p_prev)
            if d_prev < best_d:
                best_p, best_d = p_prev, d_prev
        
        # Check segment after
        if center_idx < len(full_coords) - 1:
            p_next = project_on_segment(pt, full_coords[center_idx], full_coords[center_idx+1])
            d_next = dist_sq(pt, p_next)
            if d_next < best_d:
                best_p, best_d = p_next, d_next
        return best_p

    start_surgical = get_surgical_point(start_pt, idx1, coords)
    end_surgical = get_surgical_point(end_pt, idx2, coords)

    clipped[0] = start_surgical
    clipped[-1] = end_surgical
    
    return clipped

def itineraries_to_geojson(itinerary, line_to_color=None):
    """Converte um itinerário para FeatureCollection GeoJSON com estilos por segmento."""
    import polyline
    features = []
    
    if line_to_color is None:
        line_to_color = {}
    
    legs = itinerary.get("legs", [])
    
    # Pre-decode polylines so we can use their exact endpoints for seamless connections
    leg_coords = []
    for leg in legs:
        if leg.get("polyline"):
            try:
                leg_coords.append(polyline.decode(leg["polyline"], 7))
            except:
                leg_coords.append(None)
        else:
            leg_coords.append(None)

    for idx, leg in enumerate(legs):
        coords = leg_coords[idx]
        if not coords:
            continue
            
        try:
            # Faz o clipping da polyline se tivermos as coordenadas e não for trecho a pé
            if leg.get("from_lat") and leg.get("to_lat") and leg["type"] != "WALK":
                start_pt = (leg["from_lat"], leg["from_lon"])
                end_pt = (leg["to_lat"], leg["to_lon"])
                
                # Seamless connection: snap exactly to the adjacent walk leg's coordinates
                if idx > 0 and legs[idx-1]["type"] == "WALK" and leg_coords[idx-1]:
                    start_pt = leg_coords[idx-1][-1]
                if idx < len(legs) - 1 and legs[idx+1]["type"] == "WALK" and leg_coords[idx+1]:
                    end_pt = leg_coords[idx+1][0]
                    
                coords = _clip_polyline(coords, start_pt, end_pt)
                
            # Inverte para (lon, lat) para o padrão GeoJSON
            geojson_coords = [[c[1], c[0]] for c in coords]
            
            is_walk = leg["type"] == "WALK"
            line_label = leg.get("line", "")
            
            if is_walk:
                leg_color = "#334155" # Dark slate for high contrast
            else:
                from src.logic.gtfs_static_logic import _normalize_line_key
                norm_line = _normalize_line_key(line_label)
                leg_color = line_to_color.get(norm_line, "#ef4444")
                
            properties = {
                "type": leg["type"],
                "line": line_label,
                "color": leg_color,
                "dashArray": "6, 8" if is_walk else None,
                "weight": 5 if is_walk else 6,
                "opacity": 0.9 if is_walk else 0.9,
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
    
    def sort_key(f):
        geom_type = f["geometry"]["type"]
        is_walk = f["properties"].get("is_walk", False)
        if geom_type == "Point":
            return 2
        if is_walk:
            return 1
        return 0
        
    line_features = [f for f in features if f["geometry"]["type"] == "LineString"]
    start_pt = line_features[0]["geometry"]["coordinates"][0] if line_features else None
    end_pt = line_features[-1]["geometry"]["coordinates"][-1] if line_features else None

    features.sort(key=sort_key)
    
    return {
        "geojson": {
            "type": "FeatureCollection", 
            "features": features,
            "start_pt": start_pt,
            "end_pt": end_pt
        },
        "bounds": bounds
    }
