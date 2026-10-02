"""Shared spatial input helpers for scenario allocation workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


class SpatialInputError(RuntimeError):
    """Raised when a spatial input cannot be interpreted safely."""


def normalise_gkz(value: Any) -> str:
    """Return an Austrian municipality identifier as a five-digit string."""

    if pd.isna(value):
        raise SpatialInputError("Encountered a missing municipality identifier.")

    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]

    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        raise SpatialInputError(f"Invalid municipality identifier: {value!r}")

    digits = digits.zfill(5)
    if len(digits) != 5:
        raise SpatialInputError(
            f"Municipality identifier must contain five digits: {value!r}"
        )

    return digits


def read_vector(
    path: str | Path,
    *,
    crs_if_missing: str | None = None,
    encoding: str | None = None,
) -> gpd.GeoDataFrame:
    """Read GeoParquet, a normal vector file, or a CSV containing WKT."""

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() in {".parquet", ".geoparquet"}:
        gdf = gpd.read_parquet(path)
    else:
        try:
            kwargs = {"encoding": encoding} if encoding else {}
            gdf = gpd.read_file(path, **kwargs)
        except Exception:
            if path.suffix.lower() != ".csv":
                raise

            frame = pd.read_csv(path, encoding=encoding or "utf-8")
            geometry_column = next(
                (
                    column
                    for column in ("geometry", "wkt", "WKT")
                    if column in frame.columns
                ),
                None,
            )
            if geometry_column is None:
                raise SpatialInputError(
                    f"CSV {path} contains no geometry, wkt, or WKT column."
                )

            geometry = gpd.GeoSeries.from_wkt(frame.pop(geometry_column))
            gdf = gpd.GeoDataFrame(frame, geometry=geometry)

    if gdf.empty:
        raise SpatialInputError(f"Spatial input is empty: {path}")

    if gdf.crs is None:
        if crs_if_missing is None:
            raise SpatialInputError(f"CRS is missing for {path}")
        gdf = gdf.set_crs(crs_if_missing)

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        raise SpatialInputError(f"No non-empty geometries remain in {path}")

    try:
        gdf.geometry = gdf.geometry.make_valid()
    except AttributeError:
        gdf.geometry = gdf.geometry.buffer(0)

    return gdf


def union_polygon(gdf: gpd.GeoDataFrame) -> Polygon | MultiPolygon:
    """Combine all rows and require a polygonal result."""

    geometry = unary_union(gdf.geometry.tolist())
    if geometry.is_empty:
        raise SpatialInputError("The unioned geometry is empty.")
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        raise SpatialInputError(
            "Expected a Polygon or MultiPolygon after combining the input."
        )
    return geometry


def load_aoi(
    path: str | Path,
    *,
    aoi_id: str,
    working_crs: str,
    crs_if_missing: str | None = "EPSG:4326",
) -> gpd.GeoDataFrame:
    """Load the study polygon and return exactly one AOI row."""

    raw = read_vector(path, crs_if_missing=crs_if_missing).to_crs(working_crs)
    return gpd.GeoDataFrame(
        {"aoi_id": [aoi_id]},
        geometry=[union_polygon(raw)],
        crs=working_crs,
    )


def load_municipalities(
    path: str | Path,
    *,
    municipality_id_column: str,
    municipality_name_column: str | None,
    working_crs: str,
    crs_if_missing: str | None = None,
    encoding: str | None = None,
) -> gpd.GeoDataFrame:
    """Load municipality polygons, normalise GKZ, and dissolve duplicates."""

    municipalities = read_vector(
        path,
        crs_if_missing=crs_if_missing,
        encoding=encoding,
    ).to_crs(working_crs)

    if municipality_id_column not in municipalities.columns:
        raise SpatialInputError(
            f"Municipality file has no column {municipality_id_column!r}."
        )

    rename = {municipality_id_column: "municipality_id"}
    keep = [municipality_id_column, "geometry"]

    if municipality_name_column:
        if municipality_name_column not in municipalities.columns:
            raise SpatialInputError(
                f"Municipality file has no column {municipality_name_column!r}."
            )
        rename[municipality_name_column] = "municipality_name_boundary"
        keep.insert(1, municipality_name_column)

    municipalities = municipalities[keep].rename(columns=rename)
    municipalities["municipality_id"] = municipalities[
        "municipality_id"
    ].map(normalise_gkz)

    aggregation: dict[str, str] = {}
    if "municipality_name_boundary" in municipalities.columns:
        aggregation["municipality_name_boundary"] = "first"

    municipalities = municipalities.dissolve(
        by="municipality_id",
        as_index=False,
        aggfunc=aggregation or "first",
    )

    if municipalities["municipality_id"].duplicated().any():
        raise SpatialInputError("Municipality IDs are not unique after dissolve.")

    return municipalities


def touched_municipalities(
    aoi: gpd.GeoDataFrame,
    municipalities: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Return municipalities with a positive-area overlap with the AOI."""

    aoi_geometry = aoi.geometry.iloc[0]
    touched = municipalities[
        municipalities.geometry.intersects(aoi_geometry)
    ].copy()
    touched = touched[
        touched.geometry.intersection(aoi_geometry).area > 0
    ].copy()

    if touched.empty:
        raise SpatialInputError(
            "The study polygon does not overlap a municipality polygon."
        )

    return touched.sort_values("municipality_id").reset_index(drop=True)
