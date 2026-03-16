"""Pipeline de processamento de dados GPS: bearing, histórico, filtragem."""
import math
import time

import pandas as pd

from typing import Dict, Any, Union, List
from math_helpers import haversine, bearing_between


def processar_dados_gps(
    df: pd.DataFrame, config: Dict[str, Any]
) -> pd.DataFrame:
    """Processa DataFrame GPS de acordo com configuração de mapeamento.

    Args:
        df: DataFrame com dados brutos
        config: Dicionário com mapeamento de colunas

    Returns:
        DataFrame processado ou vazio se erro
    """
    from datetime import timedelta

    try:
        if df.empty or config["ordem_col"] not in df.columns:
            return pd.DataFrame()

        df = df.copy()

        # Processar timestamp
        ts_col = config["timestamp_col"]
        if ts_col in df.columns:
            df[ts_col] = pd.to_datetime(
                df[ts_col].astype(float) / config["timestamp_divisor"],
                unit="s"
            ) - timedelta(hours=3)

        # Renomear coluna ordem se necessário
        if config["ordem_col"] != "ordem":
            df = df.rename(columns={config["ordem_col"]: "ordem"})

        # Processar coordenadas
        lat_col = config["lat_col"]
        lon_col = config["lon_col"]

        if config["lat_needs_conversion"]:
            df[lat_col] = pd.to_numeric(
                df[lat_col].astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            )
        else:
            df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")

        if config["lon_needs_conversion"]:
            df[lon_col] = pd.to_numeric(
                df[lon_col].astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            )
        else:
            df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

        # Processar velocidade
        vel_col = config["velocidade_col"]
        if vel_col in df.columns:
            df[vel_col] = pd.to_numeric(df[vel_col], errors="coerce")

        # Selecionar colunas finais
        colunas = [
            "ordem", ts_col, lat_col, lon_col,
            config["linha_col"], config["velocidade_col"]
        ]
        if config["sentido_col"]:
            colunas.append(config["sentido_col"])

        colunas = [c for c in colunas if c in df.columns]
        df = df[colunas].copy()

        # Renomear para nomes padrão
        rename_map = {
            ts_col: "datahora",
            lat_col: "latitude",
            lon_col: "longitude",
            config["linha_col"]: "linha",
            config["velocidade_col"]: "velocidade",
        }
        if config["sentido_col"]:
            rename_map[config["sentido_col"]] = "sentido"

        df = df.rename(columns=rename_map)
        df["tipo"] = config["tipo"]

        if "sentido" not in df.columns:
            df["sentido"] = None

        return df

    except Exception as e:
        print(f"ERRO processando {config['tipo']}: {e}")
        return pd.DataFrame()


def calcular_bearing_df(
    df: pd.DataFrame,
    hist_list: Union[Dict[str, Any], List[Dict[str, Any]]],
    dist_min: float = 20.0
) -> pd.DataFrame:
    """Adiciona coluna 'direcao' ao DataFrame.
    Só atualiza o bearing quando o veículo andou >= dist_min m;
    caso contrário preserva o último bearing registrado.
    """
    df = df.copy()
    df["direcao"] = float("nan")

    if not hist_list:
        return df

    # Aceita histórico no formato novo (dict) e no legado (lista de dicts)
    if isinstance(hist_list, dict):
        hist_map = hist_list
    else:
        hist_map = {r["ordem"]: r for r in hist_list}
    if not hist_map:
        return df

    hist_df = pd.DataFrame.from_dict(hist_map, orient="index")
    if hist_df.empty:
        return df
    if "bearing" not in hist_df.columns:
        hist_df["bearing"] = hist_df.get("ultimo_bearing")
    hist_df["ordem"] = hist_df.index
    hist_df = hist_df.rename(columns={
        "lat": "lat_prev",
        "lng": "lng_prev",
        "datahora": "datahora_prev"
    })

    # Junta apenas veículos presentes no histórico para custo reduzido.
    cand = df.reset_index().merge(
        hist_df[["ordem", "lat_prev", "lng_prev", "datahora_prev", "bearing"]],
        on="ordem",
        how="inner",
    )
    if cand.empty:
        return df

    cand["datahora_prev"] = pd.to_datetime(
        cand["datahora_prev"], errors="coerce"
    )
    cand["datahora"] = pd.to_datetime(
        cand["datahora"], errors="coerce"
    )
    cols_to_drop = [
        "datahora", "datahora_prev", "lat_prev", "lng_prev", "lat", "lng"
    ]
    cand = cand.dropna(subset=cols_to_drop)
    if cand.empty:
        return df

    time_diff_min = (
        cand["datahora"] - cand["datahora_prev"]
    ).abs().dt.total_seconds().div(60)
    cand = cand[time_diff_min < 10]
    if cand.empty:
        return df

    for row in cand.itertuples(index=False):
        dist = haversine(row.lat_prev, row.lng_prev, row.lat, row.lng)
        if dist >= dist_min:
            df.at[row.index, "direcao"] = round(
                bearing_between(
                    row.lat_prev, row.lng_prev, row.lat, row.lng
                ), 0
            )
        elif row.bearing is not None and not (
            isinstance(row.bearing, float) and math.isnan(row.bearing)
        ):
            df.at[row.index, "direcao"] = row.bearing

    return df


def atualizar_historico(
    hist_dict: Dict[str, Any], df: pd.DataFrame
) -> Dict[str, Any]:
    """Mantém apenas a posição mais recente por veículo no histórico.
    Formato: {ordem: {"lat", "lng", "datahora", "bearing", "ts_add"}}
    """
    ts_now = time.time()
    for row in df.itertuples(index=False):
        bearing = getattr(row, "direcao", None)
        if (
            bearing is not None and
            isinstance(bearing, float) and
            math.isnan(bearing)
        ):
            bearing = None

        ordem = str(getattr(row, "ordem", "")).strip()
        if not ordem:
            continue

        hist_dict[ordem] = {
            "lat": float(getattr(row, "lat")),
            "lng": float(getattr(row, "lng")),
            "datahora": str(getattr(row, "datahora")),
            "bearing": bearing,
            "ts_add": ts_now,
        }

    return hist_dict


def limpar_historico_antigo(
    hist_dict: Dict[str, Any],
    max_age_seconds: int = 300,
    tipo: str = "SPPO"
) -> None:
    """Remove veículos antigos do histórico."""
    agora = time.time()
    ordens_remover = []
    for ordem, dados in hist_dict.items():
        ts_add = dados.get("ts_add", 0)
        if agora - ts_add > max_age_seconds:
            ordens_remover.append(ordem)

    for ordem in ordens_remover:
        del hist_dict[ordem]
