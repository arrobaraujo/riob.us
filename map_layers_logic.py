# Shim de compatibilidade — módulo migrado para src/logic/map_layers_logic.py
from src.logic.map_layers_logic import *  # noqa: F401, F403
from src.logic.map_layers_logic import (  # noqa: F401
    to_float,
    classify_motion,
    make_popup,
    build_map_static_cache_key,
    build_static_layers,
    build_vehicle_cache_key,
    trim_cache,
    build_vehicle_layers,
    _get_now,
    _set_now_override,
)
