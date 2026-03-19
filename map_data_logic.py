import pandas as pd
from dash import html


def montar_opcoes_veiculos(dados, veiculo_exibicao_fn):
    if dados is None or dados.empty:
        return []

    base_opcoes = (
        dados.sort_values("datahora", ascending=False)
        .drop_duplicates("ordem")
        .copy()
    )

    return [
        {
            "label": veiculo_exibicao_fn(
                row["ordem"], row.get("linha", ""), row.get("tipo", "")
            ),
            "value": str(row["ordem"]),
        }
        for _, row in base_opcoes.iterrows()
        if str(row.get("ordem", "")).strip()
    ]


def filtrar_por_veiculos(dados, veiculos_sel):
    if dados is None or dados.empty or not veiculos_sel:
        return dados
    veiculos_set = set(str(v) for v in veiculos_sel)
    return dados[dados["ordem"].astype(str).isin(veiculos_set)]


def split_gps_por_tipo(dados):
    if dados is None or dados.empty:
        return pd.DataFrame(), pd.DataFrame()
    sppo_df = dados[dados["tipo"] == "SPPO"].copy()
    brt_df = dados[dados["tipo"] == "BRT"].copy()
    return sppo_df, brt_df


def construir_secao_icones(cache_or_generate_svg_fn):
    icone_seta = cache_or_generate_svg_fn("#888", float("nan"))
    icone_circulo = cache_or_generate_svg_fn("#888", 0)
    label_style = {"fontSize": "clamp(9px, 1vw, 11px)"}
    img_style = {
        "width": "clamp(14px, 1.4vw, 18px)",
        "height": "clamp(14px, 1.4vw, 18px)",
        "flexShrink": 0
    }
    return html.Div(
        [
            html.B(
                "Ícones:",
                style={
                    "display": "block",
                    "marginBottom": "4px",
                    "fontSize": "10px"
                }
            ),
            html.Div(
                [
                    html.Img(src=icone_seta[0], style=img_style),
                    html.Span("Parado/Não atualizado", style=label_style),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "5px",
                    "marginBottom": "3px"
                },
            ),
            html.Div(
                [
                    html.Img(src=icone_circulo[0], style=img_style),
                    html.Span("Em movimento", style=label_style),
                ],
                style={
                    "display": "flex", "alignItems": "center", "gap": "5px"
                },
            ),
        ],
        style={
            "marginTop": "7px",
            "paddingTop": "6px",
            "borderTop": "1px solid #dee2e6"
        },
    )


def construir_legenda_vazia(modo, fetch_ok, secao_icones):
    titulo = "Veículos no mapa:" if modo == "veiculos" else "Linhas no mapa:"
    return html.Div(
        [
            html.B(
                titulo,
                style={
                    "display": "block",
                    "marginBottom": "3px",
                    "fontSize": "clamp(10px, 1.1vw, 13px)"
                }
            ),
            secao_icones,
        ],
        className="caixa-legenda",
        style={"minWidth": "clamp(135px, 18vw, 180px)"},
    )


def construir_legenda_sem_veiculos(
    secao_icones, mensagem="Nenhum veículo selecionado"
):
    return html.Div(
        [
            html.B(
                "Veículos no mapa:",
                style={
                    "display": "block",
                    "marginBottom": "3px",
                    "fontSize": "clamp(10px, 1.1vw, 13px)"
                }
            ),
            html.Span(
                mensagem, style={"color": "#888", "fontStyle": "italic"}
            ),
            secao_icones,
        ],
        className="caixa-legenda",
        style={"minWidth": "clamp(135px, 18vw, 180px)"},
    )


def linhas_ativas_por_veiculos(dados_filtrados, linhas_short):
    linhas_short_set = set(str(x) for x in linhas_short)
    return sorted(
        {
            str(ln)
            for ln in dados_filtrados["linha"].astype(str).tolist()
            if str(ln) in linhas_short_set
        }
    )


def construir_legenda_veiculos(
    dados_filtrados, cores, linhas_dict,
    linha_exibicao_fn, secao_icones
):
    itens = []
    base_legenda = (
        dados_filtrados.sort_values("datahora", ascending=False)
        .drop_duplicates("ordem")
    )
    for row in base_legenda.itertuples(index=False):
        linha_val = str(getattr(row, "linha", "") or "")
        ordem_val = str(getattr(row, "ordem", "") or "")
        tipo_val = str(getattr(row, "tipo", "") or "")
        nome_long = linhas_dict.get(linha_val, "")
        if linha_val:
            linha_label = linha_exibicao_fn(linha_val)
        else:
            linha_label = "Sem linha"
        cor = cores.get(linha_val, "#9aa3ad")
        itens.append(
            html.Div(
                [
                    html.Span(
                        style={
                            "flexShrink": 0,
                            "marginTop": "2px",
                            "width": "clamp(11px, 1vw, 14px)",
                            "height": "clamp(11px, 1vw, 14px)",
                            "borderRadius": "2px",
                            "background": cor,
                            "display": "inline-block",
                        }
                    ),
                    html.Span(
                        [
                            html.B(f"Veículo {ordem_val}"),
                            html.Br(),
                            html.Span(
                                f"Linha {linha_label}",
                                style={
                                    "color": "#4f5b68",
                                    "fontSize": "clamp(9px, 1vw, 11px)"
                                },
                            ),
                        ]
                        + (
                            [
                                html.Br(),
                                html.Span(
                                    nome_long,
                                    style={
                                        "color": "#555",
                                        "fontSize": "clamp(9px, 1vw, 11px)"
                                    },
                                ),
                            ]
                            if nome_long
                            else []
                        )
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "flex-start",
                    "gap": "6px",
                    "marginBottom": "4px"
                },
            )
        )

    return html.Div(
        [
            html.B(
                "Veículos no mapa:",
                style={
                    "display": "block",
                    "marginBottom": "4px",
                    "fontSize": "clamp(10px, 1.1vw, 13px)"
                }
            ),
            *itens,
            secao_icones,
        ],
        className="caixa-legenda",
        style={
            "minWidth": "clamp(135px, 18vw, 180px)",
            "maxWidth": "clamp(215px, 32vw, 320px)"
        },
    )


def construir_legenda_linhas(
    linhas_render, cores, linhas_dict,
    linha_exibicao_fn, secao_icones,
    contagem_por_linha=None,
):
    contagem_por_linha = contagem_por_linha or {}
    itens = []
    for ln in linhas_render:
        cor = cores.get(ln, "#888888")
        nome_long = linhas_dict.get(ln, "")
        linha_label = linha_exibicao_fn(ln)
        total = int(contagem_por_linha.get(ln, 0) or 0)
        sufixo = "Veículo" if total == 1 else "Veículos"
        linha_titulo = f"{linha_label} - {total} {sufixo}"
        itens.append(
            html.Div(
                [
                    html.Span(
                        style={
                            "flexShrink": 0,
                            "marginTop": "2px",
                            "width": "clamp(11px, 1vw, 14px)",
                            "height": "clamp(11px, 1vw, 14px)",
                            "borderRadius": "2px",
                            "background": cor,
                            "display": "inline-block",
                        }
                    ),
                    html.Span(
                        [html.B(linha_titulo)]
                        + (
                            [
                                html.Br(),
                                html.Span(
                                    nome_long,
                                    style={
                                        "color": "#555",
                                        "fontSize": "clamp(9px, 1vw, 11px)"
                                    },
                                ),
                            ]
                            if nome_long
                            else []
                        )
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "flex-start",
                    "gap": "6px",
                    "marginBottom": "4px"
                },
            )
        )

    return html.Div(
        [
            html.B(
                "Linhas no mapa:",
                style={
                    "display": "block",
                    "marginBottom": "4px",
                    "fontSize": "clamp(10px, 1.1vw, 13px)"
                }
            ),
            *itens,
            secao_icones,
        ],
        className="caixa-legenda",
        style={
            "minWidth": "clamp(135px, 18vw, 180px)",
            "maxWidth": "clamp(195px, 28vw, 280px)"
        },
    )
