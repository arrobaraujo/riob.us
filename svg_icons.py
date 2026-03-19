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
        'width="28" height="28" viewBox="0 0 28 28">'
        '<path d="M14 2.5c-4.6 0-8.3 3.7-8.3 8.3c0 5.8 6.8 13.8 7.1 14.1'
        'c0.3 0.4 0.9 0.4 1.2 0c0.3-0.3 7.1-8.3 7.1-14.1c0-4.6-3.7-8.3-8.3-8.3z" '
        'fill="#e53935" stroke="white" stroke-width="1.8"/>'
        '<circle cx="14" cy="10.8" r="3.4" fill="white"/>'
        '</svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


def gerar_svg_parada() -> str:
    """Gera SVG com emoji de parada e retorna data-URI codificado."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="26" height="26" viewBox="0 0 26 26">'
        '<text x="13" y="19" text-anchor="middle" '
        'font-size="18">🚏</text>'
        '</svg>'
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
