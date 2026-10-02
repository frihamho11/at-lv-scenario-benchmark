#!/usr/bin/env python
"""Build municipality-wide OSM building caches for all GKZ touched by an AOI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def _find_project_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in [start.parent, *start.parents]:
        if (candidate / "src" / "lv_scenario_benchmark").exists():
            return candidate
    raise RuntimeError("Could not locate the project root.")


PROJECT_ROOT = _find_project_root()
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lv_scenario_benchmark.allocation import load_config  # noqa: E402
from lv_scenario_benchmark.data_sources.osm_municipality_buildings import (  # noqa: E402
    extract_municipality_buildings,
    write_municipality_building_cache,
)
from lv_scenario_benchmark.spatial import (  # noqa: E402
    load_aoi,
    load_municipalities,
    touched_municipalities,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Query the complete municipality building stock with the same "
            "OSM tags and area threshold used by Seiler's GeoDAQ workflow."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing municipality cache files.",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    print(f"Active PROJECT: {config.project_name}")
    print(f"Study polygon: {config.aoi_path}")
    print(f"Municipality boundaries: {config.municipality_boundaries_path}")

    aoi = load_aoi(
        config.aoi_path,
        aoi_id=config.aoi_id,
        working_crs=config.working_crs,
        crs_if_missing=config.aoi_crs_if_missing,
    )
    municipalities = load_municipalities(
        config.municipality_boundaries_path,
        municipality_id_column=config.municipality_id_column,
        municipality_name_column=config.municipality_name_column,
        working_crs=config.working_crs,
        crs_if_missing=config.municipality_crs_if_missing,
        encoding=config.municipality_encoding,
    )
    touched = touched_municipalities(aoi, municipalities)

    print("Touched municipalities:")
    for row in touched.itertuples(index=False):
        name = getattr(row, "municipality_name_boundary", "")
        print(f"  {row.municipality_id} {name}")

    for row in touched.itertuples(index=False):
        municipality_id = row.municipality_id
        output_path = (
            config.municipality_building_cache_dir
            / f"municipality_{municipality_id}.parquet"
        )

        if output_path.exists() and not args.force:
            print(f"Skip existing cache: {output_path}")
            continue

        print(f"Query OSM buildings for GKZ {municipality_id} ...")
        buildings, metadata = extract_municipality_buildings(
            municipality_id=municipality_id,
            municipality_geometry=row.geometry,
            municipality_crs=touched.crs,
            seiler_parameters_path=config.seiler_parameters_path,
            osmnx_cache_dir=config.osmnx_cache_dir,
        )
        outputs = write_municipality_building_cache(
            buildings=buildings,
            metadata=metadata,
            output_dir=config.municipality_building_cache_dir,
            municipality_id=municipality_id,
        )
        print(
            f"  stored {len(buildings)} buildings "
            f"({int(buildings['residential'].sum())} residential)"
        )
        for label, path in outputs.items():
            print(f"  {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
