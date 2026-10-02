#!/usr/bin/env python
"""Create a simulation-ready HP-enriched pandapower network."""

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

from lv_scenario_benchmark.integration import (  # noqa: E402
    integrate_hp_status_quo,
    load_hp_pandapower_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Add the selected HP status-quo allocation to a copy of net.p, "
            "assign reproducible rural-LV SimBench HP templates, and attach "
            "pandapower ConstControl time-series controllers."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()

    config = load_hp_pandapower_config(args.config)

    print(f"Active PROJECT: {config.project_name}")
    print(f"Base pandapower net: {config.base_net_path}")
    print(f"HP allocation: {config.hp_allocation_path}")
    print(f"Scenario: {config.scenario_id}")
    print(f"Realisation: {config.realisation}")
    print(f"SimBench source grids: {', '.join(config.simbench_source_grid_codes)}")
    print(f"Profile assignment seed: {config.profile_assignment_seed}")
    print(f"Profile weighting: {config.profile_weighting}")
    print(f"Reactive power profiles: {config.use_reactive_power}")
    print(f"Enriched net: {config.output_net_path}")

    result = integrate_hp_status_quo(config)

    print("\nHP + SimBench integration completed.")
    print(f"Base loads: {result.base_load_count}")
    print(f"HP loads added: {result.hp_count}")
    print(f"Enriched loads: {result.enriched_load_count}")
    print(f"Time steps: {result.n_time_steps}")
    print(f"Different HP profiles used: {result.n_profiles_used}")
    print(f"Saved enriched net: {result.output_net_path}")

    print("\nDiagnostic outputs:")
    for label, path in result.output_files.items():
        print(f"  {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
