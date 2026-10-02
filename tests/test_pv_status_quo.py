from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

import pandapower as pp

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lv_scenario_benchmark.allocation.pv_status_quo import (  # noqa: E402
    PVStatusQuoConfig,
    _round_half_up_nonnegative,
    load_config,
    run_pv_status_quo_allocation,
)


class PVStatusQuoAllocationTest(unittest.TestCase):
    def test_round_half_up(self) -> None:
        self.assertEqual(_round_half_up_nonnegative(2.49), 2)
        self.assertEqual(_round_half_up_nonnegative(2.50), 3)
        self.assertEqual(_round_half_up_nonnegative(0.0), 0)


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

            config_path = config_dir / "pv_status_quo.yaml"
            config_path.write_text(
                """
project:
  parameters: ../external/lv-syn-grid/scripts/parameters.py
  pandapower_net_filename: net.p
case:
  scenario_id: pv_status_quo
paths:
  municipality_boundaries: ../data/raw/gkz_polygon/municipalities.shp
  harmonised_pv: ../harmonisation/harmonisation_PV/outputs
  municipality_building_cache: ../data/processed/municipality_buildings
  osmnx_cache: ../data/cache/osmnx
  allocation_output_root: ../outputs
columns: {}
spatial:
  working_crs: null
allocation:
  minimum_footprint_area_m2: null
plotting:
  output_subdir: pv_status_quo
""".strip(),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.project_name, "SelectedArea")
            self.assertEqual(config.aoi_id, "SelectedArea")
            self.assertEqual(
                config.aoi_path,
                repo
                / "external"
                / "lv-syn-grid"
                / "grids"
                / "SelectedArea"
                / "data"
                / "polygon_coordinates.csv",
            )
            self.assertEqual(
                config.grid_buildings_path.name,
                "buildings.parquet",
            )
            self.assertEqual(
                config.output_dir,
                repo
                / "outputs"
                / "SelectedArea"
                / "pv_status_quo"
                / "allocation",
            )
            self.assertEqual(
                config.map_output_dir,
                repo
                / "outputs"
                / "SelectedArea"
                / "pv_status_quo"
                / "figures",
            )

    def test_share_is_derived_from_municipality_cache(self) -> None:
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

            pv = pd.DataFrame(
                {
                    "municipality_id": ["10001", "10002"],
                    "municipality_name": ["A", "B"],
                    "reference_date": ["2025-12-31", "2025-12-31"],
                    "unit_count": [4, 4],
                }
            )
            pv_path = root / "pv.csv"
            pv.to_csv(pv_path, index=False)

            config = PVStatusQuoConfig(
                project_name="test_aoi",
                aoi_id="test_aoi",
                scenario_id="pv_status_quo",
                seiler_parameters_path=root / "parameters.py",
                project_data_dir=root / "project_data",
                project_lvgrid_dir=root / "lvgrid",
                project_plots_dir=root / "plots",
                aoi_path=aoi_path,
                municipality_boundaries_path=municipality_path,
                harmonised_pv_path=pv_path,
                grid_buildings_path=grid_path,
                pandapower_net_path=root / "net.p",
                municipality_building_cache_dir=cache,
                osmnx_cache_dir=root / "osmnx",
                output_dir=root / "output",
                map_output_dir=root / "plots" / "pv_status_quo",
                working_crs="EPSG:3857",
                minimum_footprint_area_m2=60.0,
                realisations=2,
            )

            def cache_reader(path, *, crs_if_missing=None, encoding=None):
                path = Path(path)
                if path.suffix == ".parquet" and "municipality_" in path.name:
                    path = path.with_suffix(".geojson")
                from lv_scenario_benchmark.spatial import read_vector

                return read_vector(
                    path,
                    crs_if_missing=crs_if_missing,
                    encoding=encoding,
                )

            def attach_bus(allocation, _config):
                result = allocation.copy()
                result["bus_id"] = range(len(result))
                return result

            with patch(
                "lv_scenario_benchmark.allocation.pv_status_quo.read_vector",
                side_effect=cache_reader,
            ), patch(
                "lv_scenario_benchmark.allocation.pv_status_quo._attach_bus_indices",
                side_effect=attach_bus,
            ), patch(
                "lv_scenario_benchmark.allocation.pv_status_quo._write_outputs",
                return_value={},
            ):
                net = pp.create_empty_network()

                for building_id in grid["id"].astype(str):
                    bus = pp.create_bus(
                        net,
                        vn_kv=0.4,
                        name=f"BUILDING_{building_id}",
                    )

                    net.bus.loc[bus, "node_id"] = building_id
                    net.bus.loc[bus, "node_type"] = "BUILDING"

                pp.to_pickle(
                    net,
                    str(config.pandapower_net_path),
                )
                first = run_pv_status_quo_allocation(config)
                second = run_pv_status_quo_allocation(config)

            expected_targets = {
                ("10001", 0): 4,
                ("10002", 0): 2,
                ("10001", 1): 4,
                ("10002", 1): 2,
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
                "random_seed",
            ]
            pd.testing.assert_frame_equal(
                first.allocation[compare_columns].reset_index(drop=True),
                second.allocation[compare_columns].reset_index(drop=True),
            )
            self.assertFalse(
                first.allocation.duplicated(
                    ["realisation", "municipality_id", "building_id"]
                ).any()
            )


if __name__ == "__main__":
    unittest.main()
