#!/usr/bin/env python
"""Integrate PV-coupled BESS into a combined pandapower scenario network."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lv_scenario_benchmark.integration.bess_pandapower import (  # noqa: E402
    integrate_bess,
    load_bess_pandapower_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a full-year self-consumption BESS dispatch and add one "
            "pandapower storage element per allocated PV-coupled BESS."
        )
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the BESS pandapower integration YAML configuration.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_bess_pandapower_config(args.config)

    print(f"Active PROJECT: {config.project_name}")
    print(f"Scenario: {config.scenario_id}")
    print(f"Realisation: {config.realisation}")
    print(f"Base combined net: {config.base_net_path}")
    print(f"BESS allocation: {config.bess_allocation_path}")
    print(f"Output net: {config.output_net_path}")

    result = integrate_bess(config)

    print("\nBESS pandapower integration completed.")
    print(f"BESS units added: {result.bess_count}")
    print(f"Reference year: {result.reference_year}")
    print(f"Time resolution: {result.time_step_minutes} min")
    print(f"Time steps: {result.n_time_steps}")
    print("Outputs:")
    for label, path in result.output_files.items():
        print(f"  {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
