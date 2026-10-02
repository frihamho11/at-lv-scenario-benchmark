"""Create municipality-wide OSM building stocks using Seiler's filters.

Only the building-extraction logic is reused. No streets, loads, transformers,
or network topology are generated for the complete municipality.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon


class MunicipalityBuildingError(RuntimeError):
    """Raised when a municipality building stock cannot be generated."""


@dataclass(frozen=True)
class SeilerBuildingRules:
    residential_tags: dict[str, Any]
    non_residential_tags: dict[str, Any]
    allowed_amenities: tuple[str, ...]
    minimum_residential_area_m2: float
    working_crs: str


@contextmanager
def _temporary_working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def load_seiler_building_rules(parameters_path: str | Path) -> SeilerBuildingRules:
    """Import Seiler's parameter file and read the building-related constants."""

    parameters_path = Path(parameters_path).resolve()
    if not parameters_path.exists():
        raise FileNotFoundError(parameters_path)

    spec = importlib.util.spec_from_file_location(
        "lv_syn_grid_parameters_for_pv_allocation",
        parameters_path,
    )
    if spec is None or spec.loader is None:
        raise MunicipalityBuildingError(
            f"Could not import Seiler parameters from {parameters_path}."
        )

    module = importlib.util.module_from_spec(spec)

    # parameters.py creates project folders relative to the lv-syn-grid root.
    # Import it from that directory so the side effect remains in the submodule.
    lv_syn_grid_root = parameters_path.parent.parent
    with _temporary_working_directory(lv_syn_grid_root):
        spec.loader.exec_module(module)

    return _rules_from_module(module)


def _rules_from_module(module: ModuleType) -> SeilerBuildingRules:
    required = [
        "TAGS_RESIDENTIAL_BUILDINGS",
        "TAGS_NONRESIDENTIAL_BUILDINGS",
        "AMENITIES",
        "FOOTPRINT_AREA_THRESHHOLD",
        "CRS_XY",
    ]
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise MunicipalityBuildingError(
            f"Seiler parameter file is missing: {missing}"
        )

    return SeilerBuildingRules(
        residential_tags=dict(module.TAGS_RESIDENTIAL_BUILDINGS),
        non_residential_tags=dict(module.TAGS_NONRESIDENTIAL_BUILDINGS),
        allowed_amenities=tuple(module.AMENITIES.keys()),
        minimum_residential_area_m2=float(module.FOOTPRINT_AREA_THRESHHOLD),
        working_crs=str(module.CRS_XY),
    )


def _features_from_polygon(
    polygon_wgs84: Polygon | MultiPolygon,
    tags: dict[str, Any],
) -> gpd.GeoDataFrame:
    try:
        import osmnx as ox
    except ImportError as exc:
        raise MunicipalityBuildingError(
            "OSMnx is required to generate municipality building stocks."
        ) from exc

    function = getattr(ox, "features_from_polygon", None)
    if function is None:
        function = ox.features.features_from_polygon

    try:
        result = function(polygon_wgs84, tags)
    except Exception as exc:
        # OSMnx raises an explicit empty-response exception if no feature
        # matches a query. That is a valid outcome for the amenity query.
        if exc.__class__.__name__ in {
            "InsufficientResponseError",
            "EmptyOverpassResponse",
        }:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        raise

    if result.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return result


def configure_osmnx_cache(cache_dir: str | Path) -> None:
    """Enable OSMnx's local request cache."""

    try:
        import osmnx as ox
    except ImportError as exc:
        raise MunicipalityBuildingError(
            "OSMnx is required to generate municipality building stocks."
        ) from exc

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(cache_dir)


def _reset_osm_index(raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = raw.reset_index()

    if "element_type" not in frame.columns:
        frame["element_type"] = "unknown"
    if "osmid" not in frame.columns:
        frame["osmid"] = frame.index.astype(str)

    frame["osm_element_type"] = frame["element_type"].astype(str)
    frame["osm_id"] = frame["osmid"].astype(str)
    frame["building_uid"] = (
        "osm:"
        + frame["osm_element_type"]
        + ":"
        + frame["osm_id"]
    )

    return gpd.GeoDataFrame(frame, geometry="geometry", crs=raw.crs)


def _prepare_residential(
    raw: gpd.GeoDataFrame,
    rules: SeilerBuildingRules,
) -> gpd.GeoDataFrame:
    if raw.empty:
        return gpd.GeoDataFrame(geometry=[], crs=rules.working_crs)

    buildings = _reset_osm_index(raw)
    buildings = buildings[
        buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ].copy()
    if buildings.empty:
        return gpd.GeoDataFrame(geometry=[], crs=rules.working_crs)

    buildings = buildings.to_crs(rules.working_crs)
    buildings["area"] = buildings.geometry.area
    buildings["residential"] = True
    buildings["amenity"] = None
    buildings = buildings[
        buildings["area"] >= rules.minimum_residential_area_m2
    ].copy()

    return buildings[
        [
            "building_uid",
            "osm_element_type",
            "osm_id",
            "amenity",
            "residential",
            "area",
            "geometry",
        ]
    ]


def _prepare_non_residential(
    raw: gpd.GeoDataFrame,
    rules: SeilerBuildingRules,
) -> gpd.GeoDataFrame:
    if raw.empty:
        return gpd.GeoDataFrame(geometry=[], crs=rules.working_crs)

    buildings = _reset_osm_index(raw)
    buildings = buildings[
        buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ].copy()
    if buildings.empty or "amenity" not in buildings.columns:
        return gpd.GeoDataFrame(geometry=[], crs=rules.working_crs)

    buildings = buildings[
        buildings["amenity"].isin(rules.allowed_amenities)
    ].copy()
    if buildings.empty:
        return gpd.GeoDataFrame(geometry=[], crs=rules.working_crs)

    buildings = buildings.to_crs(rules.working_crs)
    buildings["area"] = buildings.geometry.area
    buildings["residential"] = False
    buildings = buildings[buildings["area"] > 0].copy()

    return buildings[
        [
            "building_uid",
            "osm_element_type",
            "osm_id",
            "amenity",
            "residential",
            "area",
            "geometry",
        ]
    ]


def extract_municipality_buildings(
    *,
    municipality_id: str,
    municipality_geometry: Polygon | MultiPolygon,
    municipality_crs: Any,
    seiler_parameters_path: str | Path,
    osmnx_cache_dir: str | Path,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Query and prepare the building stock for one complete municipality."""

    rules = load_seiler_building_rules(seiler_parameters_path)
    configure_osmnx_cache(osmnx_cache_dir)

    polygon_wgs84 = gpd.GeoSeries(
        [municipality_geometry],
        crs=municipality_crs,
    ).to_crs("EPSG:4326").iloc[0]

    residential_raw = _features_from_polygon(
        polygon_wgs84,
        rules.residential_tags,
    )
    non_residential_raw = _features_from_polygon(
        polygon_wgs84,
        rules.non_residential_tags,
    )

    residential = _prepare_residential(residential_raw, rules)
    non_residential = _prepare_non_residential(non_residential_raw, rules)

    # A feature returned by both queries is treated as non-residential, just as
    # the Seiler workflow removes duplicated amenity buildings from the
    # residential set before concatenation.
    if not residential.empty and not non_residential.empty:
        residential = residential[
            ~residential["building_uid"].isin(
                non_residential["building_uid"]
            )
        ].copy()

    frames = [frame for frame in (non_residential, residential) if not frame.empty]
    if not frames:
        raise MunicipalityBuildingError(
            f"No buildings remained for municipality {municipality_id}."
        )

    buildings = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=rules.working_crs,
    )
    buildings = buildings.drop_duplicates("building_uid", keep="last").copy()
    buildings["allocation_point"] = buildings.geometry.representative_point()

    municipality_geometry_working = gpd.GeoSeries(
        [municipality_geometry],
        crs=municipality_crs,
    ).to_crs(rules.working_crs).iloc[0]

    buildings = buildings[
        buildings["allocation_point"].within(municipality_geometry_working)
    ].copy()
    if buildings.empty:
        raise MunicipalityBuildingError(
            f"No buildings lie inside municipality {municipality_id} after filtering."
        )

    buildings["municipality_id"] = municipality_id
    buildings["id"] = buildings["building_uid"]

    metadata = {
        "municipality_id": municipality_id,
        "source": "OpenStreetMap via OSMnx",
        "extraction_time_utc": datetime.now(timezone.utc).isoformat(),
        "seiler_parameters_path": str(Path(seiler_parameters_path).resolve()),
        "working_crs": rules.working_crs,
        "residential_tags": rules.residential_tags,
        "non_residential_tags": rules.non_residential_tags,
        "allowed_amenities": list(rules.allowed_amenities),
        "minimum_residential_area_m2": rules.minimum_residential_area_m2,
        "building_count_total": int(len(buildings)),
        "building_count_residential": int(buildings["residential"].sum()),
        "building_count_non_residential": int((~buildings["residential"]).sum()),
    }

    return buildings, metadata


def write_municipality_building_cache(
    *,
    buildings: gpd.GeoDataFrame,
    metadata: dict[str, Any],
    output_dir: str | Path,
    municipality_id: str,
) -> dict[str, Path]:
    """Store one municipality building stock and its metadata."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / f"municipality_{municipality_id}.parquet"
    metadata_path = output_dir / f"municipality_{municipality_id}.json"

    export = buildings.drop(columns="allocation_point", errors="ignore")
    export.to_parquet(parquet_path, index=False)
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return {
        "buildings": parquet_path,
        "metadata": metadata_path,
    }
