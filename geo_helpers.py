import geopandas as gpd
import pandas as pd


def build_point_mask(
    df, lon_col, lat_col, polygon, prepared_polygon=None,
    predicate="covered_by"
):
    """Boolean mask for rows satisfying the predicate against polygon.

    Supported predicates:
    - "covered_by": point is inside polygon or on boundary.
    - "within": point is strictly inside polygon.
    """
    if df is None or df.empty or polygon is None:
        return pd.Series(False, index=getattr(df, "index", []))

    lon = pd.to_numeric(df[lon_col], errors="coerce")
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    valid = (
        lon.notna() & lat.notna() &
        lat.between(-90, 90) & lon.between(-180, 180)
    )

    # Stage 1: bbox prefilter before expensive geometric predicate.
    try:
        minx, miny, maxx, maxy = polygon.bounds
        valid = valid & lon.between(minx, maxx) & lat.between(miny, maxy)
    except Exception:
        pass

    mask = pd.Series(False, index=df.index)
    if not valid.any():
        return mask

    points = gpd.GeoSeries(
        gpd.points_from_xy(lon[valid], lat[valid]),
        index=df.index[valid],
        crs="EPSG:4326",
    )

    if predicate == "within":
        if prepared_polygon is not None:
            inside = points.apply(prepared_polygon.contains)
        else:
            inside = points.within(polygon)
    else:
        if hasattr(points, "covered_by"):
            inside = points.covered_by(polygon)
        elif prepared_polygon is not None:
            inside = points.apply(prepared_polygon.covers)
        else:
            inside = points.apply(polygon.covers)

    mask.loc[inside.index] = inside.astype(bool)
    return mask
