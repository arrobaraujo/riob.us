"""Geração e cache de ícones SVG para marcadores do mapa."""
import math
import threading
import urllib.parse
from typing import Tuple, List, Optional, Union, Dict

# Cache de SVGs pré-gerados (evita recalcular toda renderização)
_svg_cache: Dict[Tuple[str, str], Tuple[str, List[int], List[int]]] = {}
_svg_cache_lock = threading.Lock()


def _gerar_svg_seta(color: str = "#888") -> str:
    """Gera SVG de seta e retorna data-URI codificado."""
    p = "14,2 24,24 14,18 4,24"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="20" height="20" viewBox="0 0 28 28">'
        f'<polygon points="{p}" fill="{color}" '
        'stroke="black" stroke-width="2"/>'
        '</svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def _gerar_svg_circulo(color: str = "#888") -> str:
    """Gera SVG de círculo e retorna data-URI codificado."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="20" height="20" viewBox="0 0 28 28">'
        f'<circle cx="14" cy="14" r="10" fill="{color}" '
        'stroke="black" stroke-width="2.5"/>'
        '<circle cx="14" cy="14" r="4" fill="white"/>'
        '</svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def gerar_svg_usuario() -> str:
    """Gera SVG de marcador de usuário e retorna data-URI codificado."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="22" height="22" viewBox="0 0 22 22">'
        '<circle cx="11" cy="11" r="9" fill="#0d6efd" '
        'stroke="white" stroke-width="2.5"/>'
        '<circle cx="11" cy="11" r="3" fill="white"/>'
        '</svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def gerar_svg_parada() -> str:
    """Gera SVG de placa de parada e retorna data-URI codificado."""
    sw = "1.4"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="26" height="26" viewBox="0 0 26 26">'
        '<g transform="translate(2,1)">'
        f'<rect x="1" y="1" width="20" height="18" rx="3" fill="#1f2a37" '
        f'stroke="#ffffff" stroke-width="{sw}"/>'
        '<rect x="4.2" y="4.5" width="13.6" height="8.2" rx="1.8" '
        'fill="#ffffff"/>'
        '<rect x="5.6" y="6" width="4.8" height="3.6" rx="0.8" '
        'fill="#9ec5ff"/>'
        '<rect x="11.6" y="6" width="4.8" height="3.6" rx="0.8" '
        'fill="#9ec5ff"/>'
        '<rect x="8.7" y="10.1" width="4.6" height="1.8" rx="0.8" '
        'fill="#1f2a37"/>'
        '<circle cx="8" cy="13.9" r="1.25" fill="#1f2a37"/>'
        '<circle cx="14" cy="13.9" r="1.25" fill="#1f2a37"/>'
        '<rect x="10.3" y="19" width="1.4" height="4.7" fill="#1f2a37"/>'
        '</g></svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def cache_or_generate_svg(
    color: str, bearing: Optional[Union[float, int]]
) -> Tuple[str, List[int], List[int]]:
    """Cache de SVG: retorna do cache ou gera e armazena."""
    is_nan = (
        bearing is None or
        (isinstance(bearing, float) and math.isnan(bearing))
    )
    if is_nan:
        cache_key = (color, "circle")
    else:
        try:
            assert bearing is not None
            bearing_norm = int(round(float(bearing))) % 360
        except Exception:
            bearing_norm = 0
        cache_key = (color, f"arrow-{bearing_norm}")

    with _svg_cache_lock:
        cached = _svg_cache.get(cache_key)
    if cached is not None:
        return cached

    if is_nan:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="19" height="19" viewBox="0 0 28 28">'
            f'<circle cx="14" cy="14" r="10" fill="{color}" '
            'stroke="black" stroke-width="2.5"/>'
            '<circle cx="14" cy="14" r="4" fill="white"/>'
            '</svg>'
        )
        url = "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)
        result = (url, [19, 19], [9, 9])
    else:
        p = "14,2 24,24 14,18 4,24"
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="28" height="28" viewBox="0 0 28 28">'
            f'<g transform="rotate({bearing_norm}, 14, 14)">'
            f'<polygon points="{p}" fill="{color}" '
            'stroke="black" stroke-width="2"/>'
            '</g></svg>'
        )
        url = "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)
        result = (url, [28, 28], [14, 14])

    with _svg_cache_lock:
        _svg_cache[cache_key] = result
    return result


def make_vehicle_icon(
    bearing: Optional[Union[float, int]], color: str = "#1a6faf"
) -> Tuple[str, List[int], List[int]]:
    """Gera ícone SVG direcional como data-URI.
    Sem direção: círculo 19x19. Com direção: seta 28x28.
    Retorna (url, [w, h], [ax, ay]).
    """
    return cache_or_generate_svg(color, bearing)


# Ícone fixo de parada (pré-gerado)
STOP_SIGN_ICON = {
    "iconUrl": gerar_svg_parada(),
    "iconSize": [26, 26],
    "iconAnchor": [13, 24],
    "popupAnchor": [0, -22],
}


def get_svg_cache_lock():
    """Retorna lock do cache SVG para uso no health check."""
    return _svg_cache_lock


def get_svg_cache():
    """Retorna referência ao cache SVG para uso no health check."""
    return _svg_cache
