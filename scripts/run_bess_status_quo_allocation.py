#!/usr/bin/env python
"""Allocate PV-coupled battery storage systems for one configured scenario."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lv_scenario_benchmark.allocation.bess_status_quo import (  # noqa: E402
    load_bess_allocation_config,
    run_bess_allocation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Allocate BESS as a deterministic target share of the PV systems "
            "already allocated in each municipality and realisation."
        )
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the BESS allocation YAML configuration.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_bess_allocation_config(args.config)

    print(f"Active PROJECT: {config.project_name}")
    print(f"Scenario: {config.scenario_id}")
    print(f"Realisations: {config.realisations}")
    print(f"PV allocation: {config.pv_allocation_path}")
    print(f"BESS attachment rate: {config.attachment_rate:.3f}")

    result = run_bess_allocation(config)

    print("\nBESS allocation completed.")
    print(f"Allocated BESS units: {len(result.allocation)}")
    print("Outputs:")
    for label, path in result.output_files.items():
        print(f"  {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
