#!/usr/bin/env python
"""Allocate municipal PV unit counts and create the final map output."""

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

from lv_scenario_benchmark.allocation import (  # noqa: E402
    load_config,
    run_pv_status_quo_allocation,
)
from lv_scenario_benchmark.visualisation import (  # noqa: E402
    plot_pv_allocation_maps,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Disaggregate harmonised municipal PV unit counts to the study "
            "polygon, sample grid buildings, and save a PV/transformer map."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--skip-map",
        action="store_true",
        help="Create tables only and skip PNG/SVG map generation.",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    print(f"Active PROJECT: {config.project_name}")
    print(f"Study polygon: {config.aoi_path}")
    print(f"Grid buildings: {config.grid_buildings_path}")
    print(f"Pandapower net: {config.pandapower_net_path}")
    print(f"Map output: {config.map_output_dir}")

    result = run_pv_status_quo_allocation(config)

    map_outputs = {}
    if not args.skip_map:
        map_outputs = plot_pv_allocation_maps(result.allocation, config)

    print("PV status-quo allocation completed.\n")
    print(result.summary.to_string(index=False))

    print("\nData outputs:")
    for label, path in result.output_files.items():
        print(f"  {label}: {path}")

    if map_outputs:
        print("\nMap outputs:")
        for label, path in map_outputs.items():
            print(f"  {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
