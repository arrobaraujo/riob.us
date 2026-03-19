from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BRT_TZ = ZoneInfo("America/Sao_Paulo")


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.data.rio/",
}


def sanitize_selection(values):
    return [str(v) for v in (values or []) if v is not None and str(v).strip()]


def _fetch_sppo(
    http_session_sppo, inicio, agora, fmt, headers, selected_lines
):
    url_sppo = (
        "https://dados.mobilidade.rio/gps/sppo"
        f"?dataInicial={inicio.strftime(fmt)}"
        f"&dataFinal={agora.strftime(fmt)}"
    )
    try:
        resp = http_session_sppo.get(url_sppo, headers=headers, timeout=20)
        if resp.status_code != 200:
            return pd.DataFrame()
        data = resp.json()
        if not isinstance(data, list) or not data:
            return pd.DataFrame()
        if selected_lines:
            data = [
                r for r in data
                if str(r.get("linha", "")) in selected_lines
            ]
        return pd.DataFrame(data) if data else pd.DataFrame()
    except requests.Timeout:
        print("ERRO API SPPO: Timeout na requisição")
    except requests.RequestException as e:
        print(f"ERRO API SPPO: {type(e).__name__} - {e}")
    except ValueError:
        print("ERRO API SPPO: body não é JSON válido")
    except Exception as e:
        print(f"ERRO inesperado SPPO: {type(e).__name__} - {e}")
    return pd.DataFrame()


def _fetch_brt(http_session_brt, headers, selected_lines):
    try:
        url_brt = "https://dados.mobilidade.rio/gps/brt"
        resp = http_session_brt.get(url_brt, headers=headers, timeout=20)
        if resp.status_code != 200:
            return pd.DataFrame()
        veiculos = resp.json().get("veiculos") or []
        if selected_lines:
            veiculos = [
                r for r in veiculos
                if str(r.get("linha", "")) in selected_lines
            ]
        return pd.DataFrame(veiculos) if veiculos else pd.DataFrame()
    except requests.Timeout:
        print("ERRO API BRT: Timeout na requisição")
    except requests.RequestException as e:
        print(f"ERRO API BRT: {type(e).__name__} - {e}")
    except Exception as e:
        print(f"ERRO inesperado BRT: {type(e).__name__} - {e}")
    return pd.DataFrame()


def fetch_gps_data_service(
    linhas_sel,
    veiculos_sel,
    modo,
    http_session_sppo,
    http_session_brt,
    processar_dados_gps_fn,
    gps_config,
    linhas_short,
    filtrar_pontos_fora_municipio_fn,
    garagens_polygon,
    garagens_polygon_prepared,
    build_point_mask_fn,
):
    linhas_sel = sanitize_selection(linhas_sel)
    veiculos_sel = sanitize_selection(veiculos_sel)

    if modo == "linhas" and not linhas_sel:
        return pd.DataFrame()

    agora = datetime.now(BRT_TZ).replace(tzinfo=None)
    inicio = agora - timedelta(minutes=3)
    fmt = "%Y-%m-%d+%H:%M:%S"

    selected_lines = set(linhas_sel)
    selected_vehicles = set(veiculos_sel)

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_sppo = ex.submit(
            _fetch_sppo, http_session_sppo, inicio, agora,
            fmt, DEFAULT_HEADERS, selected_lines
        )
        fut_brt = ex.submit(
            _fetch_brt, http_session_brt, DEFAULT_HEADERS, selected_lines
        )
        sppo_df = fut_sppo.result()
        brt_df = fut_brt.result()

    if len(sppo_df) > 0:
        sppo_df = processar_dados_gps_fn(sppo_df, gps_config["sppo"])
    else:
        sppo_df = pd.DataFrame()

    if len(brt_df) > 0:
        brt_df = processar_dados_gps_fn(brt_df, gps_config["brt"])
    else:
        brt_df = pd.DataFrame()

    dados = pd.concat([sppo_df, brt_df], ignore_index=True)
    if len(dados) == 0:
        return pd.DataFrame()

    dados = dados.dropna(subset=["latitude", "longitude"])
    dados = dados.sort_values(
        "datahora", ascending=False
    ).drop_duplicates("ordem")
    dados = dados[dados["datahora"] >= inicio]

    if modo == "linhas" and linhas_short:
        dados = dados[dados["linha"].isin(linhas_short)]

    if selected_lines:
        dados = dados[dados["linha"].astype(str).isin(selected_lines)]

    if selected_vehicles:
        dados = dados[dados["ordem"].astype(str).isin(selected_vehicles)]

    dados = filtrar_pontos_fora_municipio_fn(dados)

    if modo == "linhas" and len(dados) > 0 and garagens_polygon is not None:
        try:
            inside_mask = build_point_mask_fn(
                dados,
                lon_col="longitude",
                lat_col="latitude",
                polygon=garagens_polygon,
                prepared_polygon=garagens_polygon_prepared,
                predicate="within",
            )
            dados = dados[~inside_mask]
        except Exception as e:
            print(f"ERRO no filtro de garagens: {type(e).__name__} - {e}")

    dados["linha"] = dados["linha"].astype(str)
    dados["lat"] = dados["latitude"].astype(float)
    dados["lng"] = dados["longitude"].astype(float)
    dados = dados.reset_index(drop=True)

    colunas_uteis = [
        "ordem", "lat", "lng", "linha", "velocidade",
        "tipo", "sentido", "datahora"
    ]
    colunas_uteis = [c for c in colunas_uteis if c in dados.columns]
    return dados[colunas_uteis]
