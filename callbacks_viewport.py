import dash
from dash import Input, Output


def register_viewport_callbacks(
    app, map_supports_viewport,
    resolver_comando_viewport, normalize_map_center
):
    app.clientside_callback(
        """
        function(cmd) {
            if (!cmd) {
                return window.dash_clientside.no_update;
            }
            try {
                var map = window.__gps_leaflet_map || null;
                if (!map) {
                    return {
                        ok: false,
                        reason: 'leaflet_map_not_captured',
                        ts: Date.now(),
                        token: cmd.token || null
                    };
                }

                if (Array.isArray(cmd.center) && cmd.center.length >= 2) {
                    var curZ = map.getZoom();
                    var z = (typeof cmd.zoom === 'number') ? cmd.zoom : curZ;
                    map.setView([cmd.center[0], cmd.center[1]], z, {
                        animate: false
                    });
                    setTimeout(function () {
                        try {
                            var c = cmd.center;
                            map.setView([c[0], c[1]], z, {animate: false});
                        } catch (e2) {
                            // sem-op
                        }
                    }, 140);
                }

                map.invalidateSize(false);
                return {ok: true, ts: Date.now(), token: cmd.token || null};
            } catch (e) {
                return {
                    ok: false,
                    reason: String(e),
                    ts: Date.now(),
                    token: cmd.token || null
                };
            }
        }
        """,
        Output("store-force-map-view-ack", "data"),
        Input("store-force-map-view", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(n_clicks) {
            if (!n_clicks) return window.dash_clientside.no_update;
            return new Promise(function(resolve) {
                if (!navigator.geolocation) {
                    alert("Geolocalização não suportada neste navegador.");
                    resolve(window.dash_clientside.no_update);
                    return;
                }

                function toPayload(pos) {
                    return {
                        lat: pos.coords.latitude,
                        lon: pos.coords.longitude,
                        ts: Date.now(),
                        acc: pos.coords.accuracy
                    };
                }

                navigator.geolocation.getCurrentPosition(
                    function(pos1) {
                        var c1 = pos1 && pos1.coords ? pos1.coords : null;
                        var acc1 = Number(c1 ? c1.accuracy : NaN);
                        if (!isNaN(acc1) && acc1 <= 120) {
                            resolve(toPayload(pos1));
                            return;
                        }

                        navigator.geolocation.getCurrentPosition(
                            function(pos2) {
                                var c2 = (
                                    pos2 && pos2.coords ? pos2.coords : null
                                );
                                var acc2 = Number(c2 ? c2.accuracy : NaN);
                                if (!isNaN(acc2) && (
                                    isNaN(acc1) || acc2 <= acc1
                                )) {
                                    resolve(toPayload(pos2));
                                } else {
                                    resolve(toPayload(pos1));
                                }
                            },
                            function() {
                                resolve(toPayload(pos1));
                            },
                            },
                            {
                                enableHighAccuracy: true,
                                timeout: 12000,
                                maximumAge: 0
                            }
                        );
                    },
                    function(err) {
                        alert("Erro ao obter localização: " + err.message);
                        resolve(window.dash_clientside.no_update);
                    },
                    {
                        enableHighAccuracy: true,
                        timeout: 10000,
                        maximumAge: 0
                    }
                );
            });
        }
        """,
        Output("store-localizacao", "data"),
        Input("btn-localizar", "n_clicks"),
        prevent_initial_call=True,
    )

    if map_supports_viewport:
        @app.callback(
            Output("mapa", "viewport"),
            Output("layer-localizacao", "children"),
            Output("store-force-map-view", "data"),
            Input("store-localizacao", "data"),
            Input("store-gps-ts", "data"),
            Input("store-tab-filtro", "data"),
            Input("dropdown-linhas", "value"),
            Input("store-linhas-debounce", "data"),
            Input("store-veiculos-debounce", "data"),
            Input("store-veiculos-recenter-token", "data"),
            prevent_initial_call=True,
        )
        def controlar_viewport_mapa(
            data_loc, gps_ts, tab_filtro,
            linhas_sel, linhas_sel_debounce,
            veiculos_sel, veiculos_recenter_token
        ):
            command, marker_layer = resolver_comando_viewport(
                data_loc,
                gps_ts,
                tab_filtro,
                linhas_sel,
                linhas_sel_debounce,
                veiculos_sel,
                veiculos_recenter_token,
            )
            if command is dash.no_update:
                return dash.no_update, marker_layer, dash.no_update
            force_cmd = (
                command.get("force_view", dash.no_update)
                if isinstance(command, dict) else dash.no_update
            )
            if tab_filtro == "veiculos" and force_cmd is not dash.no_update:
                return dash.no_update, marker_layer, force_cmd
            return command, marker_layer, force_cmd
    else:
        @app.callback(
            Output("mapa", "center"),
            Output("mapa", "zoom"),
            Output("mapa", "bounds"),
            Output("layer-localizacao", "children"),
            Output("store-force-map-view", "data"),
            Input("store-localizacao", "data"),
            Input("store-gps-ts", "data"),
            Input("store-tab-filtro", "data"),
            Input("dropdown-linhas", "value"),
            Input("store-linhas-debounce", "data"),
            Input("store-veiculos-debounce", "data"),
            Input("store-veiculos-recenter-token", "data"),
            prevent_initial_call=True,
        )
        def controlar_viewport_mapa(
            data_loc, gps_ts, tab_filtro,
            linhas_sel, linhas_sel_debounce,
            veiculos_sel, veiculos_recenter_token
        ):
            command, marker_layer = resolver_comando_viewport(
                data_loc,
                gps_ts,
                tab_filtro,
                linhas_sel,
                linhas_sel_debounce,
                veiculos_sel,
                veiculos_recenter_token,
            )

            if command is dash.no_update:
                return (
                    dash.no_update, dash.no_update, dash.no_update,
                    marker_layer, dash.no_update
                )

            force_cmd = (
                command.get("force_view", dash.no_update)
                if isinstance(command, dict) else dash.no_update
            )

            if isinstance(command, dict):
                is_veic_force = (
                    tab_filtro == "veiculos"
                    and force_cmd is not dash.no_update
                )
                if is_veic_force:
                    return (
                        dash.no_update, dash.no_update, dash.no_update,
                        marker_layer, force_cmd
                    )

                center = command.get("center", dash.no_update)
                zoom = command.get("zoom", dash.no_update)
                center = normalize_map_center(center)
                bounds = command.get("bounds", dash.no_update)
                if command.get("clear_bounds") is True:
                    bounds = None

                if center is not dash.no_update or zoom is not dash.no_update:
                    if tab_filtro == "veiculos":
                        return (
                            center, zoom, dash.no_update,
                            marker_layer, force_cmd
                        )
                    return center, zoom, bounds, marker_layer, force_cmd

                if "bounds" in command:
                    return (
                        dash.no_update, dash.no_update, command["bounds"],
                        marker_layer, force_cmd
                    )

                return (
                    dash.no_update, dash.no_update, dash.no_update,
                    marker_layer, force_cmd
                )

            return (
                dash.no_update, dash.no_update, dash.no_update,
                marker_layer, force_cmd
            )
