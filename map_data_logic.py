# Shim de compatibilidade — módulo migrado para src/logic/map_data_logic.py
from src.logic.map_data_logic import *  # noqa: F401, F403
from src.logic.map_data_logic import (  # noqa: F401
    montar_opcoes_veiculos,
    filtrar_por_veiculos,
    split_gps_por_tipo,
    construir_secao_icones,
    construir_legenda_vazia,
    construir_legenda_sem_veiculos,
    linhas_ativas_por_veiculos,
    construir_legenda_veiculos,
    construir_legenda_linhas,
)
