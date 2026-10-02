from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

import numpy as np
import pandas as pd

def load_osm_buildings(path: str | Path) -> gpd.GeoDataFrame:
    """
    Load Seiler's OSM building dataset from a Parquet file.

    Parameters
    ----------
    path:
        Path to the building Parquet file produced by Seiler's pipeline.

    Returns
    -------
    geopandas.GeoDataFrame
        GeoDataFrame containing OSM buildings.

    Raises
    ------
    ValueError
        If the building dataset has no coordinate reference system.
    """
    buildings = gpd.read_parquet(path)

    if buildings.crs is None:
        raise ValueError("OSM buildings have no CRS. Cannot continue safely.")

    return buildings


def load_bev_buildings_for_osm_extent(
    gpkg_path: str | Path,
    layer: str,
    osm_buildings: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Load BEV DLM building geometries for the spatial extent of the OSM buildings.

    The BEV dataset is read only for the bounding box of the OSM building dataset.
    The BEV geometries are then transformed to the CRS of the OSM buildings.

    Parameters
    ----------
    gpkg_path:
        Path to the BEV GeoPackage file.

    layer:
        Name of the GeoPackage layer containing the BEV building geometries.

    osm_buildings:
        GeoDataFrame containing the OSM buildings used as spatial reference.

    Returns
    -------
    geopandas.GeoDataFrame
        BEV building geometries clipped by bounding box and transformed to the
        CRS of the OSM building dataset.

    Raises
    ------
    ValueError
        If the BEV layer has no CRS or if no BEV buildings are found.
    """
    osm_crs = osm_buildings.crs

    # Read a single feature to determine the CRS of the BEV layer.
    sample = gpd.read_file(gpkg_path, layer=layer, rows=1)
    bev_crs = sample.crs

    if bev_crs is None:
        raise ValueError("BEV layer has no CRS. Cannot continue safely.")

    # Transform the OSM buildings to the BEV CRS in order to calculate
    # a bounding box that is valid for reading the BEV dataset.
    osm_in_bev_crs = osm_buildings.to_crs(bev_crs)

    minx, miny, maxx, maxy = osm_in_bev_crs.total_bounds
    bbox = (minx, miny, maxx, maxy)

    # Load only BEV buildings within the bounding box of the OSM dataset.
    bev = gpd.read_file(gpkg_path, layer=layer, bbox=bbox)

    if bev.empty:
        raise ValueError("No BEV buildings found for OSM extent.")

    # Transform BEV geometries to the CRS used by Seiler's OSM buildings.
    bev = bev.to_crs(osm_crs)

    return bev


def match_by_largest_overlap(
    osm_buildings: gpd.GeoDataFrame,
    bev_buildings: gpd.GeoDataFrame,
    height_column: str = "HOEHE_OBJEKT_MEDIAN",
    min_overlap_ratio: float = 0.20,
) -> gpd.GeoDataFrame:
    """
    Match each OSM building to the BEV building with the largest area overlap.

    The function performs a spatial join between OSM and BEV building geometries.
    If multiple BEV buildings intersect one OSM building, the BEV building with
    the largest intersection area is selected.

    A match is accepted if either the overlap ratio relative to the OSM building
    or the overlap ratio relative to the BEV building is greater than or equal to
    the specified minimum overlap ratio.

    Parameters
    ----------
    osm_buildings:
        GeoDataFrame containing OSM building geometries.

    bev_buildings:
        GeoDataFrame containing BEV DLM building geometries.

    height_column:
        Name of the BEV height attribute to be transferred.

    min_overlap_ratio:
        Minimum required overlap ratio for accepting a spatial match.

    Returns
    -------
    geopandas.GeoDataFrame
        OSM buildings enriched with BEV height information and match quality
        indicators.

    Raises
    ------
    ValueError
        If OSM and BEV buildings do not use the same CRS.
    """

    if osm_buildings.crs != bev_buildings.crs:
        raise ValueError("OSM and BEV buildings must have the same CRS before matching.")

    osm = osm_buildings.copy().reset_index(drop=True)
    bev = bev_buildings.copy().reset_index(drop=True)

    osm["osm_idx"] = osm.index
    bev["bev_idx"] = bev.index

    # Calculate building footprint areas.
    # Since EPSG:9273 is a projected CRS, areas are approximately in square meters.
    osm["osm_area_m2"] = osm.geometry.area
    bev["bev_area_m2"] = bev.geometry.area

    # Keep only BEV columns relevant for height enrichment and diagnostics.
    bev_columns = [
        "bev_idx",
        height_column,
        "OBJECTID",
        "GLOBALID",
        "BAUWERKSFUNKTION",
        "AGWR_OBJEKTNUMMER",
        "bev_area_m2",
        "geometry",
    ]

    # Only use existing columns, because the BEV dataset may not contain all expected attributes.
    bev_columns = [col for col in bev_columns if col in bev.columns]

    # Spatial join:
    # Find all BEV buildings intersecting each OSM building.
    candidates = gpd.sjoin(
        osm[["osm_idx", "osm_area_m2", "geometry"]],
        bev[bev_columns],
        how="left",
        predicate="intersects",
    )

    # Remove OSM buildings without any intersecting BEV candidate.
    candidates = candidates.dropna(subset=["bev_idx"]).copy()

    if candidates.empty:
        result = osm.copy()
        result["bev_height_raw_m"] = np.nan
        result["bev_objectid"] = pd.NA
        result["bev_globalid"] = pd.NA
        result["bev_bauwerksfunktion"] = pd.NA
        result["bev_agwr_objektnummer"] = pd.NA
        result["bev_overlap_area_m2"] = 0.0
        result["bev_overlap_ratio_osm"] = 0.0
        result["bev_overlap_ratio_bev"] = 0.0
        result["bev_match_method"] = "no_overlap"
        return result

    # Add the BEV geometry again, because geopandas.sjoin keeps only the left
    # geometry column by default.
    bev_geometry = bev[["bev_idx", "geometry"]].rename(
        columns={"geometry": "bev_geometry"}
    )

    candidates = candidates.merge(
        bev_geometry,
        on="bev_idx",
        how="left",
    )

    # Calculate the intersection area between each OSM building and each BEV candidate.
    candidates["bev_overlap_area_m2"] = candidates.geometry.intersection(
        candidates["bev_geometry"]
    ).area

    candidates["bev_overlap_ratio_osm"] = (
        candidates["bev_overlap_area_m2"] / candidates["osm_area_m2"]
    )

    candidates["bev_overlap_ratio_bev"] = (
        candidates["bev_overlap_area_m2"] / candidates["bev_area_m2"]
    )

    # Select the BEV candidate with the largest overlap for each OSM building.
    best_idx = candidates.groupby("osm_idx")["bev_overlap_area_m2"].idxmax()
    best = candidates.loc[best_idx].copy()

    # Accept the match if the overlap is sufficiently large from either perspective..
    best["match_accepted"] = (
        (best["bev_overlap_ratio_osm"] >= min_overlap_ratio)
        | (best["bev_overlap_ratio_bev"] >= min_overlap_ratio)
    )

    # Rename BEV columns to stable internal column names.
    rename_map = {
        height_column: "bev_height_raw_m",
        "OBJECTID": "bev_objectid",
        "GLOBALID": "bev_globalid",
        "BAUWERKSFUNKTION": "bev_bauwerksfunktion",
        "AGWR_OBJEKTNUMMER": "bev_agwr_objektnummer",
    }

    best = best.rename(columns=rename_map)

    keep_columns = [
        "osm_idx",
        "bev_height_raw_m",
        "bev_objectid",
        "bev_globalid",
        "bev_bauwerksfunktion",
        "bev_agwr_objektnummer",
        "bev_overlap_area_m2",
        "bev_overlap_ratio_osm",
        "bev_overlap_ratio_bev",
        "match_accepted",
    ]

    keep_columns = [col for col in keep_columns if col in best.columns]

    result = osm.merge(
        best[keep_columns],
        on="osm_idx",
        how="left",
    )

    # Store the match method for later quality assessment.
    result["bev_match_method"] = np.where(
        result["match_accepted"] == True,
        "largest_overlap",
        "no_valid_overlap",
    )

    # Buildings without any candidate are explicitly marked as no-overlap cases.
    result.loc[result["bev_height_raw_m"].isna(), "bev_match_method"] = "no_overlap"

    # Do not use BEV heights from matches below the quality threshold.
    invalid_match = result["match_accepted"] != True
    result.loc[invalid_match, "bev_height_raw_m"] = np.nan

    # Remove additional help column.
    result = result.drop(columns=["match_accepted"], errors="ignore")

    return gpd.GeoDataFrame(result, geometry="geometry", crs=osm_buildings.crs)


def derive_height_and_floors(
    buildings: gpd.GeoDataFrame,
    raw_height_column: str = "bev_height_raw_m",
    room_height_m: float = 2.6,
    min_height_m: float = 5.0,
    max_height_m: float = 300.0,
    fallback_height_m: float = 5.0,
    min_floors: int = 1,
) -> gpd.GeoDataFrame:
    """
    Derive Seiler-compatible building height and floor columns from BEV height data.

    The raw BEV height is checked for plausibility. Plausible heights are used
    as input for the final height value. Missing or implausible heights are
    replaced by a conservative fallback height.

    Parameters
    ----------
    buildings:
        GeoDataFrame containing OSM buildings enriched with raw BEV height data.

    raw_height_column:
        Column containing the raw BEV height value in meters.

    room_height_m:
        Assumed average height per floor in meters.

    min_height_m:
        Minimum building height used for plausible BEV height values.

    max_height_m:
        Maximum plausible building height. Values above this threshold are
        treated as implausible.

    fallback_height_m:
        Height used if no plausible BEV height is available.

    min_floors:
        Minimum number of floors assigned to a building.

    Returns
    -------
    geopandas.GeoDataFrame
        Building GeoDataFrame with Seiler-compatible height and floors columns.
    """

    result = buildings.copy()

    raw = pd.to_numeric(result[raw_height_column], errors="coerce")

    plausible = (
        raw.notna()
        & (raw >= 2.0)
        & (raw <= max_height_m)
    )

    result["height_source"] = np.where(plausible, "bev_dlm", "fallback")
    result["height_quality"] = np.where(plausible, "plausible", "fallback_used")

    result["height"] = fallback_height_m

    result.loc[plausible, "height"] = raw.loc[plausible].clip(lower=min_height_m)

    result["floors"] = np.floor(result["height"] / room_height_m).astype(int)
    result["floors"] = result["floors"].clip(lower=min_floors)

    return gpd.GeoDataFrame(result, geometry="geometry", crs=buildings.crs)