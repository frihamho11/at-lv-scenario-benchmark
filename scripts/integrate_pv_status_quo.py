#!/usr/bin/env python
"""Create a simulation-ready PV-enriched pandapower network."""

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

from lv_scenario_benchmark.integration.pv_pandapower import (  # noqa: E402
    integrate_pv_status_quo,
    load_pv_pandapower_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Add the selected PV status-quo allocation to a copy of net.p, "
            "assign the configured nominal PV power, normalize APCS E1, and "
            "attach a pandapower ConstControl time-series controller."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()

    config = load_pv_pandapower_config(args.config)

    print(f"Active PROJECT: {config.project_name}")
    print(f"Base pandapower net: {config.base_net_path}")
    print(f"PV allocation: {config.pv_allocation_path}")
    print(f"Scenario: {config.scenario_id}")
    print(f"Realisation: {config.realisation}")
    print(f"Nominal PV power: {config.nominal_power_kwp:.1f} kWp per unit")
    print(f"Profile source: {config.profile_source}")
    print(f"Profile file: {config.profile_path}")
    print(f"Profile ID: {config.profile_id}")
    print(f"Normalization: {config.profile_normalization}")
    print(f"Enriched net: {config.output_net_path}")

    result = integrate_pv_status_quo(config)

    print("\nPV + APCS integration completed.")
    print(f"Base sgens: {result.base_sgen_count}")
    print(f"PV sgens added: {result.pv_count}")
    print(f"Enriched sgens: {result.enriched_sgen_count}")
    print(f"Time steps: {result.n_time_steps}")
    print(f"Saved enriched net: {result.output_net_path}")

    print("\nDiagnostic outputs:")
    for label, path in result.output_files.items():
        print(f"  {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
