def compute_poll_interval_ms(
    tab_filtro,
    linhas_sel,
    veiculos_sel,
    last_fetch_had_data,
    idle_ms=90000,
    lines_active_ms=30000,
    vehicles_active_ms=20000,
):
    """Compute GPS polling interval based on user activity and data freshness."""
    tab = tab_filtro or "linhas"
    linhas_count = len(linhas_sel or [])
    veiculos_count = len(veiculos_sel or [])

    if tab == "veiculos" and veiculos_count > 0:
        interval = int(vehicles_active_ms)
    elif tab == "linhas" and linhas_count > 0:
        interval = int(lines_active_ms)
    else:
        interval = int(idle_ms)

    if not bool(last_fetch_had_data):
        interval = int(min(max(interval * 2, 20000), 180000))

    return interval
