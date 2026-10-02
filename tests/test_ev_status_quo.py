from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lv_scenario_benchmark.allocation.ev_status_quo import (  # noqa: E402
    EVStatusQuoConfig,
    load_ev_config,
    run_ev_status_quo_allocation,
)


class EVStatusQuoAllocationTest(unittest.TestCase):
    def test_config_uses_project_from_parameters(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "at-lv-scenario-benchmark"
            config_dir = repo / "configs"
            parameters_dir = repo / "external" / "lv-syn-grid" / "scripts"
            config_dir.mkdir(parents=True)
            parameters_dir.mkdir(parents=True)

            parameters_path = parameters_dir / "parameters.py"
            parameters_path.write_text(
                "\n".join(
                    [
                        'PROJECT = "SelectedArea"',
                        'FILEPATH_DATA = "grids/" + PROJECT + "/data/"',
                        'FILEPATH_LV_GRID = "grids/" + PROJECT + "/lvgrid/"',
                        'FILEPATH_PLOTS = "grids/" + PROJECT + "/plots/"',
                        'FILENAME_POLYGON_CSV = "polygon_coordinates.csv"',
                        'FILE_BUILDINGS_PARQUET = "buildings.parquet"',
                        'CRS_XY = "EPSG:9273"',
                        'FOOTPRINT_AREA_THRESHHOLD = 60.0',
                    ]
                ),
                encoding="utf-8",
            )

            config_path = config_dir / "ev_status_quo.yaml"
            config_path.write_text(
                """
project:
  parameters: ../external/lv-syn-grid/scripts/parameters.py
  pandapower_net_filename: net.p
case:
  scenario_id: ev_status_quo
paths:
  municipality_boundaries: ../data/raw/gkz_polygon/municipalities.shp
  harmonised_ev: ../harmonisation/harmonisation_EV/outputs/ev_municipality_harmonised.xlsx
  harmonised_ev_sheet: ev_by_municipality
  municipality_building_cache: ../data/processed/municipality_buildings
  allocation_output_root: ../outputs
columns: {}
spatial:
  working_crs: null
allocation:
  minimum_footprint_area_m2: null
plotting:
  output_subdir: ev_status_quo
""".strip(),
                encoding="utf-8",
            )

            config = load_ev_config(config_path)
            self.assertEqual(config.project_name, "SelectedArea")
            self.assertEqual(config.aoi_id, "SelectedArea")
            self.assertEqual(
                config.output_dir,
                repo / "outputs" / "SelectedArea" / "ev_status_quo" / "allocation",
            )
            self.assertEqual(config.ev_sheet, "ev_by_municipality")
            self.assertEqual(config.sampling_weight, "base_load")

    def test_allocation_is_reproducible_and_allows_multiple_evs_per_building(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache = root / "cache"
            cache.mkdir()

            municipalities = gpd.GeoDataFrame(
                {
                    "g_id": ["10001", "10002"],
                    "g_name": ["A", "B"],
                    "geometry": [box(0, 0, 10, 10), box(10, 0, 20, 10)],
                },
                crs="EPSG:3857",
            )
            municipality_path = root / "municipalities.geojson"
            municipalities.to_file(municipality_path, driver="GeoJSON")

            aoi = gpd.GeoDataFrame(
                {"geometry": [box(0, 0, 15, 10)]},
                crs="EPSG:3857",
            )
            aoi_path = root / "aoi.geojson"
            aoi.to_file(aoi_path, driver="GeoJSON")

            municipality_geometries = {
                "10001": [box(index + 0.1, 1, index + 0.8, 2) for index in range(10)],
                "10002": [
                    box(10 + index + 0.1, 1, 10 + index + 0.8, 2)
                    for index in range(10)
                ],
            }
            for municipality_id, geometries in municipality_geometries.items():
                frame = gpd.GeoDataFrame(
                    {
                        "building_uid": [
                            f"osm:way:{municipality_id}{index}"
                            for index in range(len(geometries))
                        ],
                        "area": [100.0] * len(geometries),
                        "residential": [True] * len(geometries),
                        "geometry": geometries,
                    },
                    crs="EPSG:3857",
                )
                frame.to_file(
                    cache / f"municipality_{municipality_id}.geojson",
                    driver="GeoJSON",
                )
                (cache / f"municipality_{municipality_id}.parquet").touch()

            grid_geometries = (
                municipality_geometries["10001"]
                + municipality_geometries["10002"][:5]
            )
            grid = gpd.GeoDataFrame(
                {
                    "id": [f"BD{index:03d}" for index in range(len(grid_geometries))],
                    "area": [100.0] * len(grid_geometries),
                    "residential": [True] * len(grid_geometries),
                    "geometry": grid_geometries,
                },
                crs="EPSG:3857",
            )
            grid_path = root / "grid.geojson"
            grid.to_file(grid_path, driver="GeoJSON")

            ev = pd.DataFrame(
                {
                    "municipality_id": ["10001", "10002"],
                    "municipality_name": ["A", "B"],
                    "reference_date": ["2025-12-31", "2025-12-31"],
                    "unit_count": [6, 16],
                }
            )
            ev_path = root / "ev.csv"
            ev.to_csv(ev_path, index=False)

            config = EVStatusQuoConfig(
                project_name="test_aoi",
                aoi_id="test_aoi",
                scenario_id="ev_status_quo",
                seiler_parameters_path=root / "parameters.py",
                aoi_path=aoi_path,
                municipality_boundaries_path=municipality_path,
                harmonised_ev_path=ev_path,
                grid_buildings_path=grid_path,
                pandapower_net_path=root / "net.p",
                municipality_building_cache_dir=cache,
                output_dir=root / "output",
                map_output_dir=root / "plots" / "ev_status_quo",
                working_crs="EPSG:3857",
                minimum_footprint_area_m2=60.0,
                sampling_weight="uniform",
                realisations=2,
            )

            bus_map = pd.DataFrame(
                {
                    "building_id": grid["id"],
                    "bus_id": range(len(grid)),
                    "base_load_kw": [1.0] * len(grid),
                }
            )

            def pv_cache_reader(path, *, crs_if_missing=None, encoding=None):
                path = Path(path)
                if path.suffix == ".parquet" and "municipality_" in path.name:
                    path = path.with_suffix(".geojson")
                from lv_scenario_benchmark.spatial import read_vector

                return read_vector(
                    path,
                    crs_if_missing=crs_if_missing,
                    encoding=encoding,
                )

            with patch(
                "lv_scenario_benchmark.allocation.pv_status_quo.read_vector",
                side_effect=pv_cache_reader,
            ), patch(
                "lv_scenario_benchmark.allocation.ev_status_quo._load_building_bus_load_map",
                return_value=bus_map,
            ), patch(
                "lv_scenario_benchmark.allocation.ev_status_quo._write_outputs",
                return_value={},
            ):
                first = run_ev_status_quo_allocation(config)
                second = run_ev_status_quo_allocation(config)

            expected_targets = {
                ("10001", 0): 6,
                ("10002", 0): 8,
                ("10001", 1): 6,
                ("10002", 1): 8,
            }
            actual_targets = {
                (row.municipality_id, row.realisation): row.target_unit_count
                for row in first.summary.itertuples(index=False)
            }
            self.assertEqual(actual_targets, expected_targets)

            compare_columns = [
                "realisation",
                "municipality_id",
                "building_id",
                "unit_at_building",
                "random_seed",
            ]
            pd.testing.assert_frame_equal(
                first.allocation[compare_columns].reset_index(drop=True),
                second.allocation[compare_columns].reset_index(drop=True),
            )

            b_rows = first.allocation.loc[
                (first.allocation["municipality_id"] == "10002")
                & (first.allocation["realisation"] == 0)
            ]
            self.assertEqual(len(b_rows), 8)
            self.assertLessEqual(b_rows["building_id"].nunique(), 5)
            self.assertGreater(b_rows.groupby("building_id").size().max(), 1)
            self.assertTrue(first.allocation["allocation_id"].is_unique)


if __name__ == "__main__":
    unittest.main()
