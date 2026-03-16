# ==============================================================================
# Constantes e configurações centralizadas
# ==============================================================================

# Paleta de cores (10 cores com alto contraste)
PALETA_CORES = [
    "#E63946",  # Vermelho
    "#FF00D9",  # Rosa
    "#FFBE0B",  # Amarelo
    "#4A47A3",  # Índigo
    "#3CB44B",  # Verde
    "#118AB2",  # Azul
    "#00BCD4",  # Ciano Elétrico
    "#8338EC",  # Roxo
    "#455A64",  # Cinza Azulado
    "#8B5E34",  # Marrom
]

# Estilos migrados para assets/styles.css

# Mapeamento de configurações para processamento de dados GPS
GPS_CONFIG = {
    "sppo": {
        "timestamp_col": "datahora",
        "timestamp_divisor": 1000,
        "lat_col": "latitude",
        "lon_col": "longitude",
        "ordem_col": "ordem",
        "linha_col": "linha",
        "velocidade_col": "velocidade",
        "sentido_col": None,
        "tipo": "SPPO",
        "lat_needs_conversion": True,
        "lon_needs_conversion": True,
    },
    "brt": {
        "timestamp_col": "dataHora",
        "timestamp_divisor": 1000,
        "lat_col": "latitude",
        "lon_col": "longitude",
        "ordem_col": "codigo",
        "linha_col": "linha",
        "velocidade_col": "velocidade",
        "sentido_col": "sentido",
        "tipo": "BRT",
        "lat_needs_conversion": False,
        "lon_needs_conversion": False,
    },
}

MARKER_LIMITS_BY_ZOOM = [
    (9, 150),
    (10, 250),
    (11, 400),
    (12, 650),
    (13, 900),
    (14, 1300),
]

# Modo leve para interação: reduz custo de renderização com muitos pontos.
LIGHTWEIGHT_MARKER_THRESHOLD = 220
MAX_STOPS_PER_RENDER = 450
