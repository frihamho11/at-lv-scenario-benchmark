#!/usr/bin/env python
"""Create one pandapower network containing enabled status-quo technologies."""

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

from lv_scenario_benchmark.integration.combined_status_quo import (  # noqa: E402
    INTEGRATION_ORDER,
    integrate_combined_status_quo,
    load_combined_status_quo_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sequentially add enabled PV, EV and HP status-quo allocations to "
            "one common copy of the synthetic base net.p."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()

    config = load_combined_status_quo_config(args.config)
    enabled = [
        technology.upper()
        for technology in INTEGRATION_ORDER
        if technology in config.enabled_technologies
    ]

    print(f"Active PROJECT: {config.project_name}")
    print(f"Base pandapower net: {config.base_net_path}")
    print(f"Scenario: {config.scenario_id}")
    print(f"Realisation: {config.realisation}")
    print(f"Enabled technologies: {', '.join(enabled)}")
    print(f"Integration order: {' -> '.join(enabled)}")
    print(f"Combined net: {config.output_net_path}")
    print(f"Combined plot enabled: {config.plot_enabled}")

    result = integrate_combined_status_quo(config)

    print("\nCombined status-quo integration completed.")
    print(f"PV units added: {result.pv_count}")
    print(f"EV units added: {result.ev_count}")
    print(f"HP units added: {result.hp_count}")
    print(f"Reference year: {result.reference_year}")
    print(f"Time resolution: {result.time_step_minutes} min")
    print(f"Time steps: {result.n_time_steps}")
    print(f"Saved combined net: {result.output_net_path}")

    print("\nOutputs:")
    for label, path in result.output_files.items():
        print(f"  {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())